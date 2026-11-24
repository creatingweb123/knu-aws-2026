"""배포된 AWS 스택 대상 테스트 공통 (실행: AWS 담당, `pytest -m integration`).

필요한 환경 변수
- STACK_NAME: 예 `haru-dev` (samconfig.toml의 stack_name)
- AWS_REGION 또는 AWS_DEFAULT_REGION: 기본 `ap-northeast-2`
- AWS 자격 증명: 보통의 AWS CLI 프로필(AWS_PROFILE 등). 테스트 사용자 생성·삭제와 테이블 조회에 쓴다.

스택 출력(ApiUrl, UserPoolId, UserPoolClientId)과 테이블 이름은 CloudFormation에서 읽는다.
STACK_NAME이 없으면 모든 테스트를 건너뛴다. 테스트가 만든 사용자와 항목은 끝나면 지운다.
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


def _boto(service: str):
    import boto3

    return boto3.client(service, region_name=REGION)


@pytest.fixture(scope="session")
def stack() -> Stack:
    if not STACK_NAME:
        pytest.skip("STACK_NAME이 없다. AWS 스택 대상 테스트는 AWS 담당이 실행한다(backend/README.md 판정 실행표).")
    cfn = _boto("cloudformation")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in cfn.describe_stacks(StackName=STACK_NAME)["Stacks"][0]["Outputs"]}
    table = cfn.describe_stack_resource(StackName=STACK_NAME, LogicalResourceId="HaruTable")["StackResourceDetail"]["PhysicalResourceId"]
    s = Stack(outputs["ApiUrl"].rstrip("/"), outputs["UserPoolId"], outputs["UserPoolClientId"], table)
    yield s
    _cleanup(s)


def _cleanup(s: Stack) -> None:
    idp, ddb = _boto("cognito-idp"), _boto("dynamodb")
    for username in s.created_users:
        try:
            idp.admin_delete_user(UserPoolId=s.pool_id, Username=username)
        except Exception:  # noqa: BLE001
            pass
    def delete_partition(pk: str) -> None:
        items = ddb.query(TableName=s.table_name, KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": {"S": pk}})["Items"]
        for item in items:
            ddb.delete_item(TableName=s.table_name, Key={"PK": item["PK"], "SK": item["SK"]})
            if item["SK"]["S"].startswith("CLAIM#"):  # ClaimLookup
                ddb.delete_item(TableName=s.table_name, Key={"PK": {"S": item["SK"]["S"]}, "SK": {"S": "META"}})

    for plan_id in s.created_plan_ids:
        delete_partition(f"PLAN#{plan_id}")
    for sub in s.created_subs:  # 수신함(USER#{owner}/INBOX#)과 멱등 키(IDEM#{sub}#…)는 남겨도 TTL·사용자 삭제로 정리되지만 지운다
        delete_partition(f"USER#{sub}")


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
    status, body = call(stack, "POST", "/plans", token=token, body=plan_body(title), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201, body
    stack.created_plan_ids.append(body["plan"]["planId"])
    return body["plan"]["planId"]
