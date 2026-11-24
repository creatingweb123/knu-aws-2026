"""로컬 통합 테스트 (태스크 10.1). docker compose 환경 대상, `pytest -m local`.

Validates: Requirements 2.4, 4.5, 13.5, 13.8, 13.12, 13.13 (판정 근거 아님, BE-Q15)
"""

import base64
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from boto3.dynamodb.conditions import Key

from tests.local.conftest import (
    CLIENT_ID,
    POOL_ID,
    SEED_EMAIL,
    SEED_NICKNAME,
    SEED_PASSWORD,
    boto,
    call,
    dev_token,
)

pytestmark = pytest.mark.local


def plan_body(title="로컬 산책"):
    return {
        "title": title,
        "summary": "출근길 빵집에 들르고 싶었어요.",
        "reason": "이삿짐 정리가 길어졌어요.",
        "estimatedMinutes": 45,
        "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}],
        "question": "어떤 소리가 들렸나요?",
        "authoring": {"mode": "MANUAL", "durationMs": 1000, "story": "출근길 빵집에 들러 빵을 사고 싶었어요."},
    }


def _claims(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_seed_user_login_and_me_nickname():
    """BE-Q17: Floci ID 토큰에 nickname·aud·token_use가 있는지와 GET /me 닉네임. 결과를 PR·README에 기록한다."""
    idp = boto("cognito-idp")
    auth = idp.initiate_auth(
        ClientId=CLIENT_ID, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": SEED_EMAIL, "PASSWORD": SEED_PASSWORD}
    )
    token = auth["AuthenticationResult"]["IdToken"]
    claims = _claims(token)
    print("BE-Q17 floci id token claims:", sorted(claims))  # -s로 실행하면 보인다
    assert claims.get("token_use") == "id"
    assert claims.get("aud") == CLIENT_ID
    assert claims.get("iss", "").endswith(POOL_ID)
    status, _, body = call("GET", "/me", token=token)
    assert status == 200
    assert body["nickname"] == SEED_NICKNAME, "Floci ID 토큰에 nickname 클레임이 없으면 dev JWT 경로를 쓴다(BE-Q17)"


def test_me_with_dev_jwt():
    status, _, body = call("GET", "/me", token=dev_token("u-local-1", "수현"))
    assert status == 200 and body == {"userId": "u-local-1", "nickname": "수현", "unreadInboxCount": 0}


def test_plan_create_detail_list():
    owner = dev_token(f"u-{uuid.uuid4()}", "지연")
    status, _, created = call("POST", "/plans", token=owner, body=plan_body(), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201
    plan_id = created["plan"]["planId"]
    status, _, detail = call("GET", f"/plans/{plan_id}", token=dev_token("u-other", "민준"))
    assert status == 200 and detail["claimable"] is True and "metrics" not in detail["plan"]
    status, _, listed = call("GET", "/plans?status=OPEN&limit=50", token=owner)
    assert status == 200 and listed["nextCursor"] is None
    # GSI는 최종 일관성이라 목록에는 늦게 보일 수 있다(design.md). 존재만 확인하지 않고 형식을 확인한다.
    assert all(i["status"] == "OPEN" for i in listed["items"])


def _plan_items(plan_id):
    ddb = boto("dynamodb")
    return ddb.query(TableName="HaruTable", KeyConditionExpression="PK = :pk", ExpressionAttributeValues={":pk": {"S": f"PLAN#{plan_id}"}})["Items"]


def test_same_key_three_times_one_plan():
    user = f"u-{uuid.uuid4()}"
    token, key = dev_token(user, "지연"), str(uuid.uuid4())
    ids = set()
    for _ in range(3):
        status, _, body = call("POST", "/plans", token=token, body=plan_body(), headers={"Idempotency-Key": key})
        assert status == 201
        ids.add(body["plan"]["planId"])
    assert len(ids) == 1 and len(_plan_items(ids.pop())) == 1


def test_same_key_concurrent_one_plan():
    """조건식 로직 확인일 뿐이다. 실제 동시성 판정은 AWS(T13)."""
    token, key = dev_token(f"u-{uuid.uuid4()}", "지연"), str(uuid.uuid4())
    with ThreadPoolExecutor(5) as ex:
        results = list(ex.map(lambda _: call("POST", "/plans", token=token, body=plan_body(), headers={"Idempotency-Key": key}), range(5)))
    ok = [b["plan"]["planId"] for s, _, b in results if s == 201]
    assert ok and len(set(ok)) == 1
    assert all(s in (201, 503) for s, _, _ in results)


def test_same_key_other_body_409():
    token, key = dev_token(f"u-{uuid.uuid4()}", "지연"), str(uuid.uuid4())
    call("POST", "/plans", token=token, body=plan_body(), headers={"Idempotency-Key": key})
    status, _, body = call("POST", "/plans", token=token, body=plan_body("다른 제목"), headers={"Idempotency-Key": key})
    assert status == 409 and body["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("path,method", [("/me", "GET"), ("/plans", "POST"), ("/plans", "GET"), ("/plans/pln_x", "GET")])
def test_no_token_401(path, method):
    status, _, body = call(method, path, body={} if method == "POST" else None)
    assert status == 401 and body["error"]["code"] == "UNAUTHORIZED"


def test_preflight_204():
    status, headers, _ = call("OPTIONS", "/plans", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert status == 204
    assert {k.lower(): v for k, v in headers.items()}["access-control-allow-origin"] == "http://localhost:5173"


def test_checkpoint_table_and_ttl():
    ddb = boto("dynamodb")
    table = ddb.describe_table(TableName="HaruAgentCheckpoints")["Table"]
    assert {k["AttributeName"] for k in table["KeySchema"]} == {"PK", "SK"}
    ttl = ddb.describe_time_to_live(TableName="HaruAgentCheckpoints")["TimeToLiveDescription"]
    assert ttl.get("AttributeName") == "ttl"


def test_haru_table_indexes():
    table = boto("dynamodb").describe_table(TableName="HaruTable")["Table"]
    assert {g["IndexName"] for g in table["GlobalSecondaryIndexes"]} == {"GSI1", "GSI2"}
