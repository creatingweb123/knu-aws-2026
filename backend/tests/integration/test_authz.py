"""T1: 토큰 없이(또는 잘못된 토큰으로) 모든 경로를 호출하면 401, T2: 역할별 권한 (AWS 스택 대상).

판정 기준은 HTTP 상태 코드 401이다. API Gateway JWT authorizer가 거부한 401은 본문이
`{"message":"Unauthorized"}`로 계약의 에러 형식과 다르다(requirements 1.7 참고). 프론트는 401을 상태 코드로 처리한다.

Property 1 / Validates: Requirements 1.6, 1.7, 7.2, 14.1
T2 / Validates: spec backend-stage4-record-inbox Requirements 3.4, 3.5, 4.3, 5.2, 6.2, 8.7, 11.3, 11.8
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from handlers.routes import ROUTES
import json

from tests.integration.conftest import call, create_plan, create_user, get_item, query_items, save_result

pytestmark = pytest.mark.integration


def _concrete(route_key: str) -> tuple[str, str]:
    method, path = route_key.split(" ", 1)
    return method, (
        path.replace("{planId}", "pln_00000000000000000000000000")
        .replace("{claimId}", "clm_00000000000000000000000000")
        .replace("{itemId}", "clm_00000000000000000000000000")
        .replace("{sessionId}", "ais_00000000000000000000000000")
    )


def _foreign_token(stack) -> str:
    """서명 키가 다른 토큰. iss·aud는 진짜처럼 맞춘다."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    region = stack.pool_id.split("_", 1)[0]
    claims = {
        "sub": "attacker", "aud": stack.client_id, "token_use": "id", "iat": now, "exp": now + 600,
        "iss": f"https://cognito-idp.{region}.amazonaws.com/{stack.pool_id}",
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "not-a-cognito-key"})


def _expired_shape_token(stack) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    return jwt.encode({"sub": "x", "aud": stack.client_id, "exp": now - 3600, "iat": now - 7200}, key, algorithm="RS256")


def test_valid_id_token_reaches_api(stack):
    """대조군: 정상 ID 토큰이면 401이 아니다(인증 실패가 API 고장 때문이 아님을 확인)."""
    _, token = create_user(stack, "T1확인")
    status, body = call(stack, "GET", "/me", token=token)
    assert status == 200 and body["nickname"] == "T1확인"


def test_all_routes_reject_missing_or_bad_tokens(stack):
    cases = {
        "none": None,
        "malformed": "not-a-jwt",
        "foreign_signature": _foreign_token(stack),
        "expired_foreign": _expired_shape_token(stack),
    }
    results = []
    for route_key in sorted(ROUTES):
        method, path = _concrete(route_key)
        for name, token in cases.items():
            status, body = call(stack, method, path, token=token, body={} if method in ("POST", "PUT") else None)
            results.append({"route": route_key, "case": name, "status": status, "body": body})
    path = save_result("T1-authz", {"results": results})
    failures = [r for r in results if r["status"] != 401]
    assert failures == [], f"401이 아닌 응답 {len(failures)}건 (로그: {path})"


# 액세스 토큰으로 확인하는 경로. Auth_Guard(get_user)가 DB 조회 전에 거부하므로 ID는 없는 값이어도 된다.
ACCESS_TOKEN_ROUTES = ["GET /me", "GET /claims/{claimId}/record", "GET /inbox", "GET /inbox/{itemId}", "POST /inbox/{itemId}/read", "POST /inbox/{itemId}/reply"]


def test_access_token_is_rejected(stack):
    """ID 토큰만 받는다. authorizer가 통과시킨 액세스 토큰도 핸들러가 401 UNAUTHORIZED(계약 형식)로 거부한다."""
    import boto3

    from tests.integration.conftest import REGION, new_password

    idp = boto3.client("cognito-idp", region_name=REGION)
    email = f"it-access-{int(time.time())}@example.com"
    password = new_password()
    idp.admin_create_user(
        UserPoolId=stack.pool_id, Username=email, MessageAction="SUPPRESS",
        UserAttributes=[{"Name": "email", "Value": email}, {"Name": "nickname", "Value": "액세스"}],
    )
    stack.created_users.append(email)
    idp.admin_set_user_password(UserPoolId=stack.pool_id, Username=email, Password=password, Permanent=True)
    access = idp.initiate_auth(
        ClientId=stack.client_id, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": email, "PASSWORD": password}
    )["AuthenticationResult"]["AccessToken"]
    results = []
    for route_key in ACCESS_TOKEN_ROUTES:
        method, path = _concrete(route_key)
        status, body = call(stack, method, path, token=access, body={"text": "x"} if method == "POST" else None)
        results.append({"route": route_key, "status": status, "body": body})
    log = save_result("T1-access-token", {"results": results})
    failures = [r for r in results if r["status"] != 401 or (r["body"] or {}).get("error", {}).get("code") != "UNAUTHORIZED"]
    assert failures == [], f"401 UNAUTHORIZED가 아닌 응답 {len(failures)}건 (로그: {log})"


# --------------------------------------------------------------------------- T2


def _error_only(body, code: str) -> bool:
    return isinstance(body, dict) and set(body) == {"error"} and body["error"].get("code") == code and set(body["error"]) == {"code", "message"}


def _leaks(body, secrets: list[str]) -> list[str]:
    text = json.dumps(body, ensure_ascii=False)
    return [s for s in secrets if s in text]


def test_T2_role_based_access(stack):
    """T2 역할별 기대 결과(requirements.md Requirement 11.3 표). `GET /claims/{claimId}/record` 행(A 403, C 200, B 403, 없는 ID 404, 403 뒤 불변)은 BE-Q46 묶음.

    Planner(A)가 계획을 만들고 Claimer(C)가 이어받는다. Claim이 ACTIVE일 때 A·B의 Claim 쓰기 경로를 먼저 확인하고,
    C가 글을 저장·완료해 InboxItem을 만든 뒤 수신함 경로를 확인한다. 상태 확인은 DynamoDB ConsistentRead(BE-Q38).
    """
    a_sub, a = create_user(stack, "T2지연")
    c_sub, c = create_user(stack, "T2수현")
    _, b = create_user(stack, "T2민준")
    title = "T2 권한 확인 산책"
    pid = create_plan(stack, a, title)
    status, body = call(stack, "POST", f"/plans/{pid}/claims", token=c)
    assert status == 201, body
    cid = body["claim"]["claimId"]
    letter, reply_text = "T2 실행자의 비공개 글", "T2 계획자의 답장"
    secrets = [letter, reply_text, title]
    rows: list[dict] = []
    failures: list[str] = []

    def check(role: str, method: str, path: str, expect: int, code: str | None = None, body=None):
        status, resp = call(stack, method, path, token={"A": a, "B": b, "C": c}[role], body=body)
        ok = status == expect and (code is None or _error_only(resp, code))
        if code is not None and _leaks(resp, secrets):
            ok = False
        rows.append({"role": role, "route": f"{method} {path}", "status": status, "expected": expect, "code": code, "ok": ok})
        if not ok:
            failures.append(f"{role} {method} {path}: {status} {resp}")
        return status, resp

    # Claim 경로: ACTIVE에서 A·B는 403
    for role in ("A", "B"):
        check(role, "PUT", f"/claims/{cid}/record", 403, "FORBIDDEN", body={"letter": "가로채기"})
        check(role, "POST", f"/claims/{cid}/complete", 403, "FORBIDDEN", body={"mode": "TEXT_ONLY"})
        check(role, "POST", f"/claims/{cid}/abandon", 403, "FORBIDDEN")
    assert get_item(stack, f"PLAN#{pid}", f"CLAIM#{cid}")["status"] == "ACTIVE"
    assert get_item(stack, f"PLAN#{pid}", f"RECORD#{cid}") is None

    # GET /record: 기록 전에는 C만 200(record null), A·B는 403 본문 에러 형식만(BE-Q1, BE-Q46)
    st, resp = check("C", "GET", f"/claims/{cid}/record", 200)
    assert resp == {"record": None, "claimStatus": "ACTIVE", "delivered": False, "photoStatus": "NONE"}, resp
    for role in ("A", "B"):
        check(role, "GET", f"/claims/{cid}/record", 403, "FORBIDDEN")
    check("C", "GET", "/claims/clm_00000000000000000000000000/record", 404, "NOT_FOUND")

    check("C", "PUT", f"/claims/{cid}/record", 200, body={"letter": letter})
    st, resp = check("C", "GET", f"/claims/{cid}/record", 200)
    assert resp["record"]["letter"] == letter and resp["delivered"] is False and resp["claimStatus"] == "ACTIVE"
    for role in ("A", "B"):
        check(role, "GET", f"/claims/{cid}/record", 403, "FORBIDDEN")
    for role in ("A", "B"):
        check(role, "PUT", f"/claims/{cid}/record", 403, "FORBIDDEN", body={"letter": "덮어쓰기"})
    record = get_item(stack, f"PLAN#{pid}", f"RECORD#{cid}")
    assert record["letter"] == letter and "deliveredAt" not in record

    # 포기 200은 별도 Claim으로 확인한다
    pid2 = create_plan(stack, a, "T2 포기 확인")
    status, body = call(stack, "POST", f"/plans/{pid2}/claims", token=c)
    assert status == 201, body
    check("C", "POST", f"/claims/{body['claim']['claimId']}/abandon", 200)

    check("C", "POST", f"/claims/{cid}/complete", 200, body={"mode": "TEXT_ONLY"})
    for role in ("A", "B"):
        check(role, "POST", f"/claims/{cid}/complete", 403, "FORBIDDEN", body={"mode": "TEXT_ONLY"})
    delivered_at = get_item(stack, f"PLAN#{pid}", f"RECORD#{cid}")["deliveredAt"]
    assert get_item(stack, f"PLAN#{pid}", f"CLAIM#{cid}")["status"] == "COMPLETED"

    # 수신함 경로
    _, me_a = check("A", "GET", "/me", 200)
    if me_a.get("unreadInboxCount") != 1:
        failures.append(f"A unreadInboxCount {me_a}")
    for role in ("B", "C"):
        _, me_x = check(role, "GET", "/me", 200)
        if me_x.get("unreadInboxCount") != 0:
            failures.append(f"{role} unreadInboxCount {me_x}")
    _, listed = check("A", "GET", "/inbox", 200)
    if cid not in [i["itemId"] for i in listed.get("items", [])]:
        failures.append("A의 GET /inbox에 InboxItem이 없음")
    for role in ("B", "C"):
        _, other = check(role, "GET", "/inbox", 200)
        if cid in [i["itemId"] for i in other.get("items", [])]:
            failures.append(f"{role}의 GET /inbox에 A의 InboxItem이 보임")

    def inbox_item():
        return get_item(stack, f"USER#{a_sub}", f"INBOX#{cid}")

    for role in ("B", "C"):  # C는 itemId(= claimId)를 알고 있다
        check(role, "GET", f"/inbox/{cid}", 404, "NOT_FOUND")
        check(role, "POST", f"/inbox/{cid}/read", 404, "NOT_FOUND")
        check(role, "POST", f"/inbox/{cid}/reply", 404, "NOT_FOUND", body={"text": "가로채기"})
    item = inbox_item()
    assert item["read"] is False and "reply" not in item

    check("A", "GET", f"/inbox/{cid}", 200)
    check("A", "POST", f"/inbox/{cid}/read", 204)
    check("A", "POST", f"/inbox/{cid}/reply", 201, body={"text": reply_text})
    for role in ("B", "C"):  # 답장이 있어도 남에게는 404이고 답장 내용이 보이지 않는다
        check(role, "GET", f"/inbox/{cid}", 404, "NOT_FOUND")
        check(role, "POST", f"/inbox/{cid}/reply", 404, "NOT_FOUND", body={"text": "덮어쓰기"})
    item = inbox_item()
    assert item["read"] is True and item["reply"]["text"] == reply_text
    assert get_item(stack, f"PLAN#{pid}", f"RECORD#{cid}")["deliveredAt"] == delivered_at
    _, me_a = check("A", "GET", "/me", 200)
    if me_a.get("unreadInboxCount") != 0:
        failures.append(f"A unreadInboxCount after read {me_a}")

    # 없는 ID는 모든 역할에서 404
    none = "clm_00000000000000000000000000"
    for role in ("A", "B", "C"):
        check(role, "GET", f"/inbox/{none}", 404, "NOT_FOUND")
        check(role, "POST", f"/inbox/{none}/read", 404, "NOT_FOUND")
        check(role, "POST", f"/inbox/{none}/reply", 404, "NOT_FOUND", body={"text": "t"})
        check(role, "PUT", f"/claims/{none}/record", 404, "NOT_FOUND", body={"letter": "t"})
        check(role, "POST", f"/claims/{none}/abandon", 404, "NOT_FOUND")
        check(role, "POST", f"/claims/{none}/complete", 404, "NOT_FOUND", body={"mode": "TEXT_ONLY"})
    for sub in (a_sub, c_sub):
        assert query_items(stack, f"USER#{sub}", f"INBOX#{none}") == []  # 404 요청이 항목을 만들지 않았다

    log = save_result("T2-role-access", {"planId": pid, "claimId": cid, "rows": rows})
    assert failures == [], f"T2 기대와 다른 응답 {len(failures)}건 (로그: {log}): {failures[:5]}"
