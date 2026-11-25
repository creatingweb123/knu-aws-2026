"""T13: 같은 Idempotency-Key로 POST /plans를 여러 번 보내도 Plan 1건 (AWS 스택 대상).

가입 직후 로그인(PreSignUp 자동 확인, 요구사항 1.5·14.4)도 여기서 확인한다.

Property 2 / Validates: Requirements 1.5, 4.5, 4.7, 4.8, 14.2, 14.3, 14.4
"""

import uuid
from concurrent.futures import ThreadPoolExecutor

import boto3
import pytest

from tests.integration.conftest import REGION, call, create_user, login, new_password, plan_body, register_idem_key, save_result

pytestmark = pytest.mark.integration


def plan_items(stack, plan_id):
    ddb = boto3.client("dynamodb", region_name=REGION)
    return ddb.query(
        TableName=stack.table_name,
        KeyConditionExpression="PK = :pk AND SK = :sk",
        ExpressionAttributeValues={":pk": {"S": f"PLAN#{plan_id}"}, ":sk": {"S": "META"}},
        ConsistentRead=True,
    )["Items"]


def plans_of(stack, owner_sub):
    """GSI2(USER#owner)는 최종 일관성이라 판정에는 쓰지 않고 참고 값으로만 남긴다."""
    ddb = boto3.client("dynamodb", region_name=REGION)
    return ddb.query(
        TableName=stack.table_name,
        IndexName="GSI2",
        KeyConditionExpression="GSI2PK = :pk",
        ExpressionAttributeValues={":pk": {"S": f"USER#{owner_sub}"}},
    )["Items"]


def test_same_key_same_body_three_times(stack):
    sub, token = create_user(stack, "T13지연")
    key = str(uuid.uuid4())
    register_idem_key(stack, token, key)
    responses = [call(stack, "POST", "/plans", token=token, body=plan_body(), headers={"Idempotency-Key": key}) for _ in range(3)]
    ids = {b["plan"]["planId"] for s, b in responses if s == 201}
    stack.created_plan_ids.extend(ids)
    save_result("T13-sequential", {"responses": [{"status": s, "planId": (b or {}).get("plan", {}).get("planId")} for s, b in responses]})
    assert [s for s, _ in responses] == [201, 201, 201]
    assert len(ids) == 1
    plan_id = ids.pop()
    assert len(plan_items(stack, plan_id)) == 1
    status, detail = call(stack, "GET", f"/plans/{plan_id}", token=token)
    assert status == 200 and detail["isOwner"] is True


def test_same_key_other_body_conflicts(stack):
    _, token = create_user(stack, "T13수현")
    key = str(uuid.uuid4())
    register_idem_key(stack, token, key)
    s1, first = call(stack, "POST", "/plans", token=token, body=plan_body(), headers={"Idempotency-Key": key})
    assert s1 == 201
    plan_id = first["plan"]["planId"]
    stack.created_plan_ids.append(plan_id)
    s2, err = call(stack, "POST", "/plans", token=token, body=plan_body("바뀐 제목"), headers={"Idempotency-Key": key})
    assert s2 == 409 and err["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    _, detail = call(stack, "GET", f"/plans/{plan_id}", token=token)
    assert detail["plan"]["title"] == plan_body()["title"]


def test_same_key_concurrent(stack):
    sub, token = create_user(stack, "T13민준")
    key = str(uuid.uuid4())
    register_idem_key(stack, token, key)
    with ThreadPoolExecutor(10) as ex:
        responses = list(ex.map(lambda _: call(stack, "POST", "/plans", token=token, body=plan_body(), headers={"Idempotency-Key": key}), range(10)))
    ids = {b["plan"]["planId"] for s, b in responses if s == 201}
    stack.created_plan_ids.extend(ids)
    save_result("T13-concurrent", {"responses": [{"status": s, "body": b} for s, b in responses], "gsi2_items": len(plans_of(stack, sub))})
    assert len(ids) == 1
    assert all(s in (201, 503) for s, _ in responses)  # 503 TRY_AGAIN은 재시도 소진(허용), 다른 코드는 실패
    assert len(plan_items(stack, ids.pop())) == 1


def test_signup_then_login_without_code(stack):
    """PreSignUp 트리거가 자동 확인하므로 인증 코드 없이 바로 로그인된다."""
    idp = boto3.client("cognito-idp", region_name=REGION)
    email = f"it-signup-{uuid.uuid4().hex[:10]}@example.com"
    password = new_password()
    idp.sign_up(ClientId=stack.client_id, Username=email, Password=password, UserAttributes=[{"Name": "email", "Value": email}, {"Name": "nickname", "Value": "가입확인"}])
    stack.created_users.append(email)
    token = login(stack, email, password)
    status, me = call(stack, "GET", "/me", token=token)
    assert status == 200 and me["nickname"] == "가입확인"


def test_signup_without_nickname_is_rejected(stack):
    idp = boto3.client("cognito-idp", region_name=REGION)
    email = f"it-nonick-{uuid.uuid4().hex[:10]}@example.com"
    with pytest.raises(idp.exceptions.InvalidParameterException):
        idp.sign_up(ClientId=stack.client_id, Username=email, Password=new_password(), UserAttributes=[{"Name": "email", "Value": email}])
