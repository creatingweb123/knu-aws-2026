"""배포된 AWS 스택 대상 테스트 공통 (실행: AWS 담당, `pytest -m integration`).

필요한 환경 변수
- STACK_NAME: 예 `haru-dev` (samconfig.toml의 stack_name)
- AWS_REGION 또는 AWS_DEFAULT_REGION: 기본 `ap-northeast-2`
- AWS 자격 증명: 보통의 AWS CLI 프로필(AWS_PROFILE 등). 테스트 사용자 생성·삭제와 테이블 조회에 쓴다.

스택 출력(ApiUrl, UserPoolId, UserPoolClientId)과 테이블 이름은 CloudFormation에서 읽는다.
STACK_NAME이 없으면 모든 테스트를 건너뛴다. 테스트가 만든 사용자와 항목은 끝나면 지운다(`_cleanup`).
정리에 실패한 대상은 `test-results/cleanup-failures-*.json`에 남기고 세션 끝에 오류로 알린다.

5단계 사진 테스트: 버킷·큐·DLQ·알람·처리 함수 이름은 처음 쓸 때 `DescribeStackResource`로 읽는다(4단계 이전 스택에서도
다른 테스트는 그대로 돈다). 사진을 올린 Claim은 업로드 전에 `register_photo_claim`으로 등록하고, `_cleanup`은 DynamoDB를
지운 **뒤** 그 Claim의 `photos/original/{id}/`·`photos/processed/{id}/` prefix만 지운다. 30초 뒤 한 번 더 지우고 그때
새로 생긴 객체는 `cleanup-late-objects-*.json`에 남긴다. 버킷 전체 삭제·큐 purge는 하지 않는다.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

STACK_NAME = os.environ.get("STACK_NAME")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-northeast-2"
RESULTS_DIR = os.environ.get("RESULTS_DIR", "test-results")


@dataclass
class Stack:
    api_url: str
    pool_id: str
    client_id: str
    table_name: str
    created_users: list[str] = field(default_factory=list)
    created_subs: list[str] = field(default_factory=list)
    created_plan_ids: list[str] = field(default_factory=list)
    # 멱등 키 항목의 PK(`IDEM#{sub}#{key}`). 키마다 파티션이 따로라 USER#·PLAN# 파티션 조회로는 찾을 수 없다.
    created_idem_pks: list[str] = field(default_factory=list)
    # AI 세션(`AISESSION#{id}`/META)과 하루 할당량(`AIQUOTA#{sub}#{KST yyyymmdd}`/META, 6a).
    created_ai_session_ids: list[str] = field(default_factory=list)
    created_ai_quota_pks: list[str] = field(default_factory=list)
    # 6b: 체크포인트 테이블 물리 이름(없는 스택이면 None). AI 세션 ID마다 스레드(thread_id = sessionId)를 지운다.
    checkpoint_table: str | None = None
    # 사진을 올린 Claim. 업로드 전에 등록한다(응답을 못 받아도 prefix를 지우도록).
    created_photo_claim_ids: list[str] = field(default_factory=list)
    photo: dict[str, str] | None = None  # photo_resources()가 채운다


PHOTO_RESOURCES = {
    "bucket": "PhotoBucket",
    "queue_url": "PhotoQueue",
    "dlq_url": "PhotoDLQ",
    "alarm": "PhotoDLQNotEmpty",
    "function": "PhotoProcessorFunction",
}
CLEANUP_SECOND_PASS_S = 30


def _boto(service: str, config=None):
    import boto3

    return boto3.client(service, region_name=REGION, config=config)


def _cleanup_config():
    """정리용 클라이언트: 스로틀(TooManyRequests 등)을 적응형 재시도로 흡수한다."""
    from botocore.config import Config

    return Config(retries={"max_attempts": 10, "mode": "adaptive"})


def _selects_fault(markexpr: str) -> bool:
    """`-m`이 fault를 직접 고른 경우만 True. `-m integration`만 주면 addopts의 `not fault`가 덮여 fault 테스트가 수집되므로."""
    expr = " ".join(markexpr.split())
    return "fault" in expr and "not fault" not in expr


def pytest_collection_modifyitems(config, items):
    if _selects_fault(config.getoption("markexpr") or ""):
        return
    skip = pytest.mark.skip(reason='장애·지연 주입 테스트는 -m "integration and fault"로만 실행한다(dev 주입 배포 전용)')
    for item in items:
        if item.get_closest_marker("fault"):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def stack() -> Stack:
    if not STACK_NAME:
        pytest.skip("STACK_NAME이 없다. AWS 스택 대상 테스트는 AWS 담당이 실행한다(backend/README.md 판정 실행표).")
    cfn = _boto("cloudformation")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in cfn.describe_stacks(StackName=STACK_NAME)["Stacks"][0]["Outputs"]}
    table = cfn.describe_stack_resource(StackName=STACK_NAME, LogicalResourceId="HaruTable")["StackResourceDetail"]["PhysicalResourceId"]
    s = Stack(outputs["ApiUrl"].rstrip("/"), outputs["UserPoolId"], outputs["UserPoolClientId"], table)
    try:
        s.checkpoint_table = cfn.describe_stack_resource(StackName=STACK_NAME, LogicalResourceId="HaruAgentCheckpoints")[
            "StackResourceDetail"]["PhysicalResourceId"]
    except Exception:  # noqa: BLE001 - 6a 스택에는 없다
        s.checkpoint_table = None
    yield s
    _cleanup(s)


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code") or type(exc).__name__)
    return type(exc).__name__


def _delete_user(idp, pool_id: str, username: str) -> None:
    try:
        idp.admin_delete_user(UserPoolId=pool_id, Username=username)
    except Exception as e:  # noqa: BLE001
        if _error_code(e) != "UserNotFoundException":  # 이미 없으면 정리된 것으로 본다
            raise


def _delete_partition(ddb, table_name: str, pk: str) -> None:
    """파티션의 모든 항목과, Claim이 있으면 짝인 ClaimLookup(`CLAIM#{id}`/META)을 지운다."""
    start: dict[str, Any] | None = None
    while True:
        kwargs: dict[str, Any] = {
            "TableName": table_name,
            "KeyConditionExpression": "PK = :pk",
            "ExpressionAttributeValues": {":pk": {"S": pk}},
            "ConsistentRead": True,
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = ddb.query(**kwargs)
        for item in page["Items"]:
            ddb.delete_item(TableName=table_name, Key={"PK": item["PK"], "SK": item["SK"]})
            if item["SK"]["S"].startswith("CLAIM#"):  # ClaimLookup
                ddb.delete_item(TableName=table_name, Key={"PK": {"S": item["SK"]["S"]}, "SK": {"S": "META"}})
        start = page.get("LastEvaluatedKey")
        if not start:
            return


def _delete_checkpoint_thread(table_name: str, thread_id: str, saver=None) -> None:
    """체크포인트 스레드 삭제(라이브러리 delete_thread: Query + BatchWriteItem). 테스트 주체에 이 테이블의
    dynamodb:Query·BatchWriteItem 권한이 필요하다(README 판정 실행표)."""
    if saver is None:
        from langgraph_checkpoint_aws import DynamoDBSaver

        saver = DynamoDBSaver(table_name=table_name, region_name=REGION)
    saver.delete_thread(thread_id)


def _photo_prefixes(claim_id: str) -> tuple[str, str]:
    return f"photos/original/{claim_id}/", f"photos/processed/{claim_id}/"


def _delete_prefix(s3, bucket: str, prefix: str) -> list[str]:
    """prefix 아래 객체를 페이지로 읽어 하나씩 지운다. 지운 키를 돌려준다."""
    deleted: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])
            deleted.append(obj["Key"])
        if not page.get("IsTruncated"):
            return deleted
        token = page["NextContinuationToken"]


def _cleanup(s: Stack, idp=None, ddb=None, saver=None, s3=None, sleep=time.sleep) -> None:
    """테스트가 등록한 대상만 지운다(테이블 스캔 없음).

    대상마다 따로 시도해 하나가 실패해도 나머지를 계속한다. 실패는 삼키지 않고 모아서
    `cleanup-failures-*.json`에 남긴 뒤 RuntimeError로 알린다(세션 teardown 오류로 보인다. 개별 T 판정과는 별개).
    사진 prefix는 DynamoDB 정리 뒤에 지운다. ClaimLookup·Record가 없으면 늦게 온 처리 Lambda는 무시 조건으로 끝난다.
    """
    idp = idp or _boto("cognito-idp", _cleanup_config())
    ddb = ddb or _boto("dynamodb", _cleanup_config())
    failures: list[dict[str, str]] = []

    def attempt(kind: str, target: str, fn) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failures.append({"kind": kind, "target": target, "error": _error_code(e)})

    for username in dict.fromkeys(s.created_users):
        attempt("cognito_user", username, lambda u=username: _delete_user(idp, s.pool_id, u))
    for plan_id in dict.fromkeys(s.created_plan_ids):
        attempt("partition", f"PLAN#{plan_id}", lambda pk=f"PLAN#{plan_id}": _delete_partition(ddb, s.table_name, pk))
    for sub in dict.fromkeys(s.created_subs):  # 수신함(USER#{owner}/INBOX#)
        attempt("partition", f"USER#{sub}", lambda pk=f"USER#{sub}": _delete_partition(ddb, s.table_name, pk))
    for pk in dict.fromkeys(s.created_idem_pks):  # 멱등 키(IDEM#{sub}#{key}/META). TTL 24시간이 있지만 바로 지운다
        attempt(
            "idem_key", pk,
            lambda pk=pk: ddb.delete_item(TableName=s.table_name, Key={"PK": {"S": pk}, "SK": {"S": "META"}}),
        )

    for sid in dict.fromkeys(s.created_ai_session_ids):
        attempt("ai_session", sid,
                lambda sid=sid: ddb.delete_item(TableName=s.table_name, Key={"PK": {"S": f"AISESSION#{sid}"}, "SK": {"S": "META"}}))
    for pk in dict.fromkeys(s.created_ai_quota_pks):
        attempt("ai_quota", pk, lambda pk=pk: ddb.delete_item(TableName=s.table_name, Key={"PK": {"S": pk}, "SK": {"S": "META"}}))
    if s.checkpoint_table:  # 6b: 종료 커밋 뒤 이미 지워졌어도(BE-Q103) 남았을 수 있다(삭제 실패·중단 세션)
        for sid in dict.fromkeys(s.created_ai_session_ids):
            attempt("checkpoint_thread", sid, lambda sid=sid: _delete_checkpoint_thread(s.checkpoint_table, sid, saver))
    photo_ids = list(dict.fromkeys(s.created_photo_claim_ids))
    if photo_ids:
        bucket = (s.photo or {}).get("bucket")
        if not bucket:
            failures.extend({"kind": "s3_prefix", "target": cid, "error": "PhotoBucketUnknown"} for cid in photo_ids)
        else:
            s3 = s3 or _boto("s3", _cleanup_config())
            for cid in photo_ids:
                for prefix in _photo_prefixes(cid):
                    attempt("s3_prefix", prefix, lambda p=prefix: _delete_prefix(s3, bucket, p))
            sleep(CLEANUP_SECOND_PASS_S)  # ClaimLookup을 읽은 직후 정리가 끼어든 지연 Lambda가 만든 처리본
            late: list[str] = []
            for cid in photo_ids:
                for prefix in _photo_prefixes(cid):
                    attempt("s3_prefix", prefix, lambda p=prefix: late.extend(_delete_prefix(s3, bucket, p)))
            if late:
                save_result("cleanup-late-objects", {"objects": late})

    if failures:
        path = save_result("cleanup-failures", {"failures": failures})
        raise RuntimeError(f"테스트 데이터 정리 실패 {len(failures)}건. 남은 대상은 수동 확인이 필요하다(로그: {path})")


def token_sub(token: str) -> str:
    """테스트가 받은 ID 토큰의 `sub`(서명 검증 없이 읽는다. 정리 대상 기록용)."""
    import jwt

    return jwt.decode(token, options={"verify_signature": False})["sub"]


def register_idem_key(stack: Stack, token: str, key: str) -> None:
    """POST /plans에 쓴 멱등 키를 정리 대상으로 등록한다. 요청 전에 부른다(응답을 못 받아도 지우도록)."""
    stack.created_idem_pks.append(f"IDEM#{token_sub(token)}#{key}")


def new_password() -> str:
    return "Haru-" + secrets.token_urlsafe(12) + "9a!"


def create_user(stack: Stack, nickname: str) -> tuple[str, str]:
    """AdminCreateUser로 테스트 사용자를 만들고 (sub, ID 토큰)을 돌려준다."""
    idp = _boto("cognito-idp")
    email = f"it-{uuid.uuid4().hex[:12]}@example.com"
    password = new_password()
    resp = idp.admin_create_user(
        UserPoolId=stack.pool_id,
        Username=email,
        MessageAction="SUPPRESS",
        UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}, {"Name": "nickname", "Value": nickname}],
    )
    stack.created_users.append(email)
    sub = next(a["Value"] for a in resp["User"]["Attributes"] if a["Name"] == "sub")
    stack.created_subs.append(sub)
    idp.admin_set_user_password(UserPoolId=stack.pool_id, Username=email, Password=password, Permanent=True)
    return sub, login(stack, email, password)


def login(stack: Stack, email: str, password: str) -> str:
    auth = _boto("cognito-idp").initiate_auth(
        ClientId=stack.client_id, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": email, "PASSWORD": password}
    )
    return auth["AuthenticationResult"]["IdToken"]


def call(stack: Stack, method: str, path: str, *, token: str | None = None, body: Any = None, headers: dict[str, str] | None = None):
    """(status, json 또는 None). 네트워크 오류는 그대로 올린다."""
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(stack.api_url + path, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = {"_raw": raw.decode("utf-8", "replace")}
    return status, parsed


def save_result(name: str, data: Any) -> str:
    """판정 근거 로그(T3·T5 등)를 RESULTS_DIR에 JSON으로 남긴다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{name}-{time.strftime('%Y%m%dT%H%M%S')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"stack": STACK_NAME, "region": REGION, **data}, f, ensure_ascii=False, indent=2)
    return path


def plan_body(title: str = "통합 테스트 산책") -> dict[str, Any]:
    return {
        "title": title,
        "summary": "출근길 빵집에 들르고 싶었어요.",
        "reason": "이삿짐 정리가 길어졌어요.",
        "estimatedMinutes": 45,
        "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}],
        "question": "어떤 소리가 들렸나요?",
        "authoring": {"mode": "MANUAL", "durationMs": 1000, "story": "출근길 빵집에 들러 빵을 사고 싶었어요."},
    }


def get_item(stack: Stack, pk: str, sk: str = "META") -> dict[str, Any] | None:
    """판정용 ConsistentRead 조회(BE-Q38). 반환값은 boto3 resource 형식(파이썬 기본 타입)."""
    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(stack.table_name)
    return table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")


def query_items(stack: Stack, pk: str, sk_prefix: str) -> list[dict[str, Any]]:
    import boto3
    from boto3.dynamodb.conditions import Key

    table = boto3.resource("dynamodb", region_name=REGION).Table(stack.table_name)
    return table.query(KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with(sk_prefix), ConsistentRead=True)["Items"]


def create_plan(stack: Stack, token: str, title: str = "통합 테스트 산책") -> str:
    key = str(uuid.uuid4())
    register_idem_key(stack, token, key)
    status, body = call(stack, "POST", "/plans", token=token, body=plan_body(title), headers={"Idempotency-Key": key})
    assert status == 201, body
    stack.created_plan_ids.append(body["plan"]["planId"])
    return body["plan"]["planId"]


# ---------------------------------------------------------------------------
# 6a: AI 하루 카드
# ---------------------------------------------------------------------------


def kst_day(now=None) -> str:
    from datetime import datetime, timedelta, timezone

    return (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d")


def register_ai_quota(stack: Stack, token: str) -> None:
    """요청 전에 오늘(KST)과 내일 할당량 키를 정리 대상으로 등록한다(실행 중 자정을 넘어도 지우도록)."""
    from datetime import datetime, timedelta, timezone

    sub = token_sub(token)
    now = datetime.now(timezone.utc)
    for day in dict.fromkeys([kst_day(now), kst_day(now + timedelta(minutes=10))]):
        stack.created_ai_quota_pks.append(f"AIQUOTA#{sub}#{day}")


def ai_create(stack: Stack, token: str, story: str) -> tuple[int, Any]:
    """POST /ai/card-sessions. 할당량 키는 요청 전, 세션 ID는 200 응답에서 등록한다.

    502·503 응답에는 sessionId가 없으므로 그 세션은 find_ai_sessions로 찾아 등록한다.
    """
    register_ai_quota(stack, token)
    status, body = call(stack, "POST", "/ai/card-sessions", token=token, body={"story": story})
    if status == 200 and isinstance(body, dict) and body.get("sessionId"):
        stack.created_ai_session_ids.append(body["sessionId"])
    return status, body


def ai_turn(stack: Stack, token: str, sid: str, body: dict[str, Any]) -> tuple[int, Any]:
    return call(stack, "POST", f"/ai/card-sessions/{sid}/turns", token=token, body=body)


def ai_run(stack: Stack, token: str, story_text: str, answers: dict[str, Any] | None = None, max_requests: int = 8):
    """docs/03 프론트 규칙으로 세션을 끝까지 진행한다(질문은 픽스처 자동 답, WORKING은 이어가기, 연속 2회 WORKING 뒤 finish).
    반환: (마지막 HTTP 상태, 마지막 본문, 요청 기록[(HTTP, status 또는 code, 초)])."""
    from tests.fixtures.stories import auto_answer

    log: list[tuple[int, Any, float]] = []
    t0 = time.monotonic()
    status, view = ai_create(stack, token, story_text)
    log.append((status, (view or {}).get("status") or ((view or {}).get("error") or {}).get("code"), round(time.monotonic() - t0, 2)))
    working, finish = int(status == 200 and view.get("status") == "WORKING"), False
    while status == 200 and view.get("status") in ("ASKING", "WORKING") and len(log) < max_requests:
        body: dict[str, Any] = {"expectedTurn": view["turn"]}
        if view["status"] == "ASKING":
            body["answer"] = auto_answer(view["question"], answers)
        if finish or working >= 2:
            finish = True
            body["finish"] = True
        t0 = time.monotonic()
        status, nxt = ai_turn(stack, token, view["sessionId"], body)
        log.append((status, (nxt or {}).get("status") or ((nxt or {}).get("error") or {}).get("code"), round(time.monotonic() - t0, 2)))
        if status == 409 and (nxt or {}).get("error", {}).get("code") in ("AI_SESSION_BUSY", "AI_SESSION_CLOSED"):
            time.sleep(2)
            status, nxt = call(stack, "GET", f"/ai/card-sessions/{view['sessionId']}", token=token)
        if status == 200:
            working = working + 1 if nxt.get("status") == "WORKING" else 0
            view = nxt
        else:
            view = nxt
    return status, view, log


def find_ai_sessions(stack: Stack, sub: str) -> list[dict[str, Any]]:
    """그 사용자의 AiSession(판정·정리용). AiSession에는 소유자 인덱스가 없어 dev 테이블을 필터 스캔한다.

    AI 테스트에서만 쓰고 결과를 정리 대상으로 등록한다(_cleanup 자체는 스캔하지 않는다).
    """
    import boto3
    from boto3.dynamodb.conditions import Attr

    table = boto3.resource("dynamodb", region_name=REGION).Table(stack.table_name)
    items, kwargs = [], {"FilterExpression": Attr("PK").begins_with("AISESSION#") & Attr("ownerId").eq(sub), "ConsistentRead": True}
    while True:
        page = table.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    stack.created_ai_session_ids.extend(i["sessionId"] for i in items)
    return items


def function_env(stack_name: str, logical_id: str) -> dict[str, str]:
    """배포된 함수의 환경 변수(lambda:GetFunctionConfiguration). 판정 전제(공급자·키 이름)를 확인한다."""
    cfn = _boto("cloudformation")
    name = cfn.describe_stack_resource(StackName=stack_name, LogicalResourceId=logical_id)["StackResourceDetail"]["PhysicalResourceId"]
    return _boto("lambda").get_function_configuration(FunctionName=name).get("Environment", {}).get("Variables", {})
# ------------------------------------------------------------------ 5단계 사진 도우미


def photo_resources(stack: Stack, cfn=None) -> dict[str, str]:
    """사진 버킷·큐 URL·DLQ URL·알람 이름·처리 함수 이름. 처음 한 번만 읽는다."""
    if stack.photo is None:
        cfn = cfn or _boto("cloudformation")
        stack.photo = {
            k: cfn.describe_stack_resource(StackName=STACK_NAME, LogicalResourceId=logical)["StackResourceDetail"]["PhysicalResourceId"]
            for k, logical in PHOTO_RESOURCES.items()
        }
    return stack.photo


def register_photo_claim(stack: Stack, claim_id: str) -> None:
    """업로드 전에 부른다. 정리 때 이 Claim의 사진 prefix만 지운다."""
    photo_resources(stack)
    stack.created_photo_claim_ids.append(claim_id)


def upload_photo(upload: dict[str, Any], body: bytes, *, origin: str | None = None):
    """presigned PUT. (status, 응답 헤더(소문자), S3 오류 코드 또는 None). URL은 결과에 남기지 않는다."""
    import re

    headers = dict(upload["headers"])
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(upload["url"], data=body, method=upload["method"], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        m = re.search(r"<Code>([^<]+)</Code>", raw)
        return e.code, {k.lower(): v for k, v in e.headers.items()}, (m.group(1) if m else None)


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def photo_record(stack: Stack, plan_id: str, claim_id: str) -> dict[str, Any] | None:
    return get_item(stack, f"PLAN#{plan_id}", f"RECORD#{claim_id}")


def wait_record(stack: Stack, plan_id: str, claim_id: str, pred, *, timeout: float = 60.0, interval: float = 0.2,
                sleep=time.sleep, clock=time.monotonic, read=None) -> tuple[dict[str, Any] | None, list[str]]:
    """ConsistentRead 폴링. (조건을 만족한 Record 또는 None, 관측한 photoStatus 열(연속 중복 제거))."""
    read = read or (lambda: photo_record(stack, plan_id, claim_id))
    seen: list[str] = []
    deadline = clock() + timeout
    while True:
        rec = read()
        st = (rec or {}).get("photoStatus") or "NONE"
        if rec and rec.get("deliveredAt"):
            st += "+delivered"
        if not seen or seen[-1] != st:
            seen.append(st)
        if rec is not None and pred(rec):
            return rec, seen
        if clock() >= deadline:
            return None, seen
        sleep(interval)


def processed_keys(stack: Stack, claim_id: str, s3=None) -> list[str]:
    s3 = s3 or _boto("s3")
    resp = s3.list_objects_v2(Bucket=photo_resources(stack)["bucket"], Prefix=_photo_prefixes(claim_id)[1])
    return sorted(o["Key"] for o in resp.get("Contents", []))


def _settled(rec: dict[str, Any] | None) -> bool:
    return rec is not None and (bool(rec.get("deliveredAt")) or rec.get("photoStatus") in ("FAILED", "DISCARDED"))


def wait_photo_settled(stack: Stack, plan_id: str, claim_id: str, *, stable_s: float = 30.0, timeout_s: float = 300.0,
                       interval: float = 2.0, sleep=time.sleep, clock=time.monotonic, read=None, list_processed=None) -> bool:
    """정리 전 대기. Record가 전달·FAILED·DISCARDED이고 stable_s 동안 Record와 처리본 목록이 바뀌지 않으면 True.

    시간 안에 안 되면 `cleanup_after_unsettled`를 결과 파일에 남기고 False(정리 대상에서 빼지 않는다).
    """
    read = read or (lambda: photo_record(stack, plan_id, claim_id))
    list_processed = list_processed or (lambda: processed_keys(stack, claim_id))
    deadline = clock() + timeout_s
    last: tuple[Any, ...] | None = None
    since = clock()
    while True:
        rec = read()
        snap = (repr(sorted((rec or {}).items())), tuple(list_processed()))
        now = clock()
        if snap != last:
            last, since = snap, now
        elif _settled(rec) and now - since >= stable_s:
            return True
        if now >= deadline:
            save_result("cleanup_after_unsettled", {"claimId": claim_id, "photoStatus": (rec or {}).get("photoStatus")})
            return False
        sleep(interval)
