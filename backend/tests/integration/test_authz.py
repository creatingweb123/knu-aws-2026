"""T1: 토큰 없이(또는 잘못된 토큰으로) 모든 경로를 호출하면 401 (AWS 스택 대상).

판정 기준은 HTTP 상태 코드 401이다. API Gateway JWT authorizer가 거부한 401은 본문이
`{"message":"Unauthorized"}`로 계약의 에러 형식과 다르다(requirements 1.7 참고). 프론트는 401을 상태 코드로 처리한다.

Property 1 / Validates: Requirements 1.6, 1.7, 7.2, 14.1
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from handlers.routes import ROUTES
from tests.integration.conftest import call, create_user, save_result

pytestmark = pytest.mark.integration


def _concrete(route_key: str) -> tuple[str, str]:
    method, path = route_key.split(" ", 1)
    return method, path.replace("{planId}", "pln_00000000000000000000000000").replace("{claimId}", "clm_00000000000000000000000000")


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


def test_access_token_is_rejected(stack):
    """ID 토큰만 받는다. 액세스 토큰에는 aud가 없어 authorizer가 401로 거부해야 한다."""
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
    status, _ = call(stack, "GET", "/me", token=access)
    assert status == 401
