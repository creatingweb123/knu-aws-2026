"""로컬 어댑터 (local/adapter/app.py). Docker·네트워크 없이 dispatch를 직접 호출한다.

Validates: Requirements 13.4, 13.5, 13.6, 13.7, 13.8
"""

import importlib.util
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from common import ddb
from tests.unit.fake_table import FakeTable

APP = Path(__file__).parents[2] / "local" / "adapter" / "app.py"
spec = importlib.util.spec_from_file_location("haru_adapter", APP)
app = importlib.util.module_from_spec(spec)
sys.modules["haru_adapter"] = app  # dataclass가 모듈을 찾을 수 있게 먼저 등록한다
spec.loader.exec_module(app)

ISSUER = "http://localhost:4566/ap-northeast-2_haruLocal"
CLIENT = "haruLocalWebClient"
ORIGIN = "http://localhost:5173"
FLOCI_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def floci_token(key=FLOCI_KEY, **over):
    now = int(time.time())
    claims = {"sub": "u-jiyeon", "nickname": "지연", "aud": CLIENT, "iss": ISSUER, "token_use": "id", "iat": now, "exp": now + 600}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "floci-kid"})


def make(stage="local", resolver=None):
    cfg = app.Config(stage=stage, issuer=ISSUER, client_id=CLIENT, cors_origin=ORIGIN)
    return app.Adapter(cfg, jwks_key_resolver=resolver or (lambda token: FLOCI_KEY.public_key()))


def body(resp):
    return json.loads(resp.body) if resp.body else None


@pytest.fixture
def adapter():
    return make()


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(ddb, "table", lambda: t)
    monkeypatch.setattr(ddb, "transact_with_retry", t.transact)
    return t


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------- 토큰 검증


def test_valid_floci_token_reaches_handler(adapter):
    resp = adapter.dispatch("GET", "/me", auth(floci_token()))
    assert resp.status == 200
    assert body(resp) == {"userId": "u-jiyeon", "nickname": "지연", "unreadInboxCount": 0}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer not-a-jwt"},
        auth(floci_token(exp=int(time.time()) - 10)),  # 만료
        auth(floci_token(aud="other-client")),  # aud 불일치
        auth(floci_token(iss="http://localhost:4566/other-pool")),  # iss 불일치
        auth(floci_token(token_use="access")),  # 액세스 토큰
        auth(floci_token(key=OTHER_KEY)),  # 서명 불일치
        auth(floci_token(sub=None)),  # sub 없음
    ],
)
def test_invalid_tokens_are_401_without_calling_handler(adapter, monkeypatch, headers):
    called = []
    monkeypatch.setattr(app, "_load_handler", lambda target: called.append(target))
    resp = adapter.dispatch("GET", "/me", headers)
    assert resp.status == 401
    assert body(resp) == {"error": {"code": "UNAUTHORIZED", "message": body(resp)["error"]["message"]}}
    assert called == []


def test_token_without_bearer_prefix_is_accepted(adapter):
    assert adapter.dispatch("GET", "/me", {"Authorization": floci_token()}).status == 200


def test_claims_are_strings_like_api_gateway(adapter, monkeypatch):
    seen = {}

    def capture(target):
        def handler(event, context):
            seen.update(event["requestContext"]["authorizer"]["jwt"]["claims"])
            seen["_remaining"] = context.get_remaining_time_in_millis()
            return {"statusCode": 204}

        return handler

    monkeypatch.setattr(app, "_load_handler", capture)
    adapter.dispatch("GET", "/me", auth(floci_token()))
    assert isinstance(seen["exp"], str) and seen["sub"] == "u-jiyeon"
    assert 20_000 < seen["_remaining"] <= 27_000


# --------------------------------------------------------------- dev JWT


def test_dev_token_roundtrip(adapter):
    resp = adapter.dispatch("POST", "/dev/token", {}, json.dumps({"userId": "u-suhyun", "nickname": "수현"}).encode())
    assert resp.status == 200
    token = body(resp)["idToken"]
    me = adapter.dispatch("GET", "/me", auth(token))
    assert body(me) == {"userId": "u-suhyun", "nickname": "수현", "unreadInboxCount": 0}


@pytest.mark.parametrize("payload", [b"{}", b'{"userId": ""}', b'{"userId": 1}', b"not json", b'{"userId": "u", "nickname": 3}'])
def test_dev_token_validation(adapter, payload):
    resp = adapter.dispatch("POST", "/dev/token", {}, payload)
    assert resp.status == 400 and body(resp)["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("stage", ["dev", "demo", "prod", ""])
def test_dev_token_route_absent_outside_local(stage):
    other = make(stage=stage)
    resp = other.dispatch("POST", "/dev/token", {}, b'{"userId": "u"}')
    assert resp.status == 404
    # local 어댑터가 발급한 dev JWT도 신뢰하지 않는다
    token = body(make().dispatch("POST", "/dev/token", {}, b'{"userId": "u"}'))["idToken"]
    assert other.dispatch("GET", "/me", auth(token)).status == 401


def test_dev_token_from_another_adapter_is_rejected(adapter):
    token = body(make().dispatch("POST", "/dev/token", {}, b'{"userId": "u"}'))["idToken"]
    assert adapter.dispatch("GET", "/me", auth(token)).status == 401  # 키가 다르다


# ------------------------------------------------------------------ CORS


def test_preflight_without_auth(adapter):
    resp = adapter.dispatch("OPTIONS", "/plans", {"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
    assert resp.status == 204
    assert resp.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert resp.headers["Access-Control-Allow-Headers"] == "Authorization,Content-Type,Idempotency-Key"
    assert resp.headers["Access-Control-Allow-Methods"] == "GET,POST,PUT,OPTIONS"


def test_preflight_other_origin_refused(adapter):
    resp = adapter.dispatch("OPTIONS", "/plans", {"Origin": "http://evil.example"})
    assert resp.status == 403 and "Access-Control-Allow-Origin" not in resp.headers


def test_cors_header_on_normal_and_error_responses(adapter):
    ok = adapter.dispatch("GET", "/me", {"Origin": ORIGIN, **auth(floci_token())})
    denied = adapter.dispatch("GET", "/me", {"Origin": ORIGIN})
    assert ok.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert denied.headers["Access-Control-Allow-Origin"] == ORIGIN


# --------------------------------------------------------------- 라우팅·이벤트


def test_unknown_route_404(adapter):
    for method, path in [("GET", "/claims/1"), ("DELETE", "/plans"), ("GET", "/plans/a/b")]:
        resp = adapter.dispatch(method, path, auth(floci_token()))
        assert resp.status == 404 and body(resp)["error"]["code"] == "NOT_FOUND"


def test_event_shape(adapter):
    ev = adapter.build_event(
        "GET", "/plans/pln_1", "status=OPEN&limit=5&a=1&a=2", {"x-test": "1"}, b"", "GET /plans/{planId}", {"planId": "pln_1"}
    )
    assert ev["version"] == "2.0" and ev["routeKey"] == "GET /plans/{planId}"
    assert ev["pathParameters"] == {"planId": "pln_1"}
    assert ev["queryStringParameters"] == {"status": "OPEN", "limit": "5", "a": "1,2"}
    assert ev["body"] is None and ev["requestContext"]["http"]["method"] == "GET"


def test_plans_flow_through_adapter(adapter, table):
    plan_body = {
        "title": "산책", "summary": "s", "reason": "r", "estimatedMinutes": 45,
        "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}],
        "question": "q", "authoring": {"mode": "MANUAL", "durationMs": 1, "story": "출근길 빵집에서 빵을 사고 싶었어요."},
    }
    owner = auth(floci_token())
    created = adapter.dispatch("POST", "/plans", {**owner, "Idempotency-Key": "k1", "Content-Type": "application/json"}, json.dumps(plan_body).encode())
    assert created.status == 201
    plan_id = body(created)["plan"]["planId"]
    detail = adapter.dispatch("GET", f"/plans/{plan_id}", auth(floci_token(sub="u-other")))
    assert detail.status == 200 and body(detail)["claimable"] is True
    listed = adapter.dispatch("GET", "/plans?status=OPEN", owner)
    assert [i["planId"] for i in body(listed)["items"]] == [plan_id]


def test_routes_come_from_routes_py(adapter):
    from handlers.routes import ROUTES

    assert {r[2] for r in adapter.routes} == set(ROUTES)


# ------------------------------------------------------------- 실제 HTTP 서버


def test_http_server_end_to_end():
    adapter = make()
    adapter.config.port = 0  # 빈 포트
    server = app.make_server(adapter, host="127.0.0.1")
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/me", headers=auth(floci_token()))
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200 and json.loads(r.read())["nickname"] == "지연"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/me", timeout=5)
        assert exc.value.code == 401
    finally:
        server.shutdown()
