"""수신함 4종과 GET /me 핸들러 (moto). 인증 거부는 DB 금지 픽스처로 확인한다.

Validates: spec backend-stage4-record-inbox Requirements 4.1, 4.8, 6.4, 8.1, 8.5, 9.6, 10.1, 10.8, 11.1
"""

import json
import logging

import pytest

pytest.importorskip("moto")

from common import ddb  # noqa: E402
from handlers import claims, inbox, me, plans  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

OWNER = {"sub": "u-owner", "nickname": "지연"}
SUHYUN = {"sub": "u-suhyun", "nickname": "수현"}
MINJUN = {"sub": "u-minjun", "nickname": "민준"}
PLAN = {
    "title": "이사 전, 마지막 동네 산책",
    "summary": "출근길 빵집에 들르고 싶었어요.",
    "reason": "이삿짐 정리가 길어졌어요.",
    "estimatedMinutes": 45,
    "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}],
    "question": "어떤 소리가 들렸나요?",
    "authoring": {"mode": "MANUAL", "durationMs": 1000, "story": "출근길 빵집에 들러 빵을 사고 싶었어요."},
}
INBOX_ROUTES = [
    ("GET /inbox", None),
    ("GET /inbox/{itemId}", {"itemId": "clm_x"}),
    ("POST /inbox/{itemId}/read", {"itemId": "clm_x"}),
    ("POST /inbox/{itemId}/reply", {"itemId": "clm_x"}),
]


def ev(route, claims_=None, body=None, path=None, raw_body=None):
    return {
        "version": "2.0",
        "routeKey": route,
        "headers": {"idempotency-key": "k1"},
        "pathParameters": path,
        "queryStringParameters": None,
        "body": raw_body if raw_body is not None else (json.dumps(body, ensure_ascii=False) if body is not None else None),
        "isBase64Encoded": False,
        "requestContext": {"authorizer": {"jwt": {"claims": claims_}}} if claims_ is not None else {},
    }


def idt(c):
    return {"token_use": "id", **c}


def call(handler, route, who=None, **kw):
    resp = handler(ev(route, idt(who) if who is not None else None, **kw), None)
    return resp["statusCode"], (json.loads(resp["body"]) if resp.get("body") else None), resp


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


@pytest.fixture
def no_db(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("DB를 호출하면 안 된다")

    monkeypatch.setattr(ddb, "table", boom)
    monkeypatch.setattr(ddb, "transact_with_retry", boom)


def delivered(table):
    """계획 생성 → 이어받기 → 글 저장 → 완료. (planId, claimId)."""
    status, body, _ = call(plans.handler, "POST /plans", OWNER, body=PLAN)
    assert status == 201
    pid = body["plan"]["planId"]
    _, b, _ = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    cid = b["claim"]["claimId"]
    assert call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "소금빵을 샀어요"}, path={"claimId": cid})[0] == 200
    assert call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})[0] == 200
    return pid, cid


def test_inbox_flow_shapes(table):
    pid, cid = delivered(table)
    status, body, _ = call(me.handler, "GET /me", OWNER)
    assert status == 200 and body == {"userId": "u-owner", "nickname": "지연", "unreadInboxCount": 1}

    status, body, _ = call(inbox.handler, "GET /inbox", OWNER)
    assert status == 200 and [i["itemId"] for i in body["items"]] == [cid]
    item = body["items"][0]
    assert set(item) == {"itemId", "planId", "planTitle", "claimerNickname", "hasPhoto", "read", "createdAt", "reply"}
    assert item["planId"] == pid and item["claimerNickname"] == "수현" and item["read"] is False and item["reply"] is None

    status, body, _ = call(inbox.handler, "GET /inbox/{itemId}", OWNER, path={"itemId": cid})
    assert status == 200 and set(body) == {"item", "plan", "record"}
    assert body["plan"]["planId"] == pid and "metrics" in body["plan"]  # 소유자 직렬화
    assert body["record"] == {"letter": "소금빵을 샀어요", "deliveredAt": body["record"]["deliveredAt"], "photoUrl": None, "photoCaption": None}
    assert body["record"]["deliveredAt"]

    status, body, resp = call(inbox.handler, "POST /inbox/{itemId}/read", OWNER, path={"itemId": cid})
    assert status == 204 and body is None and "body" not in resp
    assert call(me.handler, "GET /me", OWNER)[1]["unreadInboxCount"] == 0

    status, body, _ = call(inbox.handler, "POST /inbox/{itemId}/reply", OWNER, body={"text": "고마워요"}, path={"itemId": cid})
    assert status == 201 and set(body) == {"reply"} and body["reply"]["text"] == "고마워요" and body["reply"]["sentAt"].endswith("Z")
    status, body, _ = call(inbox.handler, "POST /inbox/{itemId}/reply", OWNER, body={"text": "또"}, path={"itemId": cid})
    assert status == 409 and body == {"error": {"code": "REPLY_ALREADY_SENT", "message": "이미 답장을 보냈어요."}}
    listed = call(inbox.handler, "GET /inbox", OWNER)[1]["items"][0]
    assert listed["read"] is True and listed["reply"]["text"] == "고마워요"


@pytest.mark.parametrize("who", [SUHYUN, MINJUN])
def test_non_owner_gets_404_without_data(table, who):
    _, cid = delivered(table)
    assert call(inbox.handler, "GET /inbox", who)[1] == {"items": []}
    assert call(me.handler, "GET /me", who)[1]["unreadInboxCount"] == 0
    for route, body in [("GET /inbox/{itemId}", None), ("POST /inbox/{itemId}/read", None), ("POST /inbox/{itemId}/reply", {"text": "가로채기"})]:
        status, resp_body, _ = call(inbox.handler, route, who, body=body, path={"itemId": cid})
        assert status == 404 and resp_body == {"error": {"code": "NOT_FOUND", "message": "찾을 수 없어요."}}, route


@pytest.mark.parametrize(
    "body,raw,key",
    [({"text": ""}, None, "text"), ({"text": "가" * 101}, None, "text"), ({}, None, "text"), ({"text": 1}, None, "text"), (None, None, "body"), (None, "[]", "body"), (None, "{", "body")],
)
def test_reply_validation_before_db(no_db, body, raw, key):
    status, resp_body, _ = call(inbox.handler, "POST /inbox/{itemId}/reply", OWNER, body=body, raw_body=raw, path={"itemId": "clm_x"})
    assert status == 400 and resp_body["error"]["code"] == "VALIDATION_ERROR" and key in resp_body["error"]["details"]


@pytest.mark.parametrize("route,path", INBOX_ROUTES + [("GET /me", None)])
@pytest.mark.parametrize("claims_", [{"token_use": "access", "sub": "u-owner"}, {"sub": "u-owner"}, {"token_use": "id"}, {"token_use": "id", "sub": ""}])
def test_bad_identity_is_401_without_db(no_db, route, path, claims_):
    handler = me.handler if route == "GET /me" else inbox.handler
    resp = handler(ev(route, claims_, body={"text": "x"}, path=path), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 401 and body == {"error": {"code": "UNAUTHORIZED", "message": "로그인이 필요해요."}}


def test_integrity_error_is_500_without_leaks(table, caplog):
    pid, cid = delivered(table)
    table.delete_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"})
    with caplog.at_level(logging.ERROR):
        status, body, _ = call(inbox.handler, "GET /inbox/{itemId}", OWNER, path={"itemId": cid})
    assert status == 500 and body == {"error": {"code": "INTERNAL_ERROR", "message": "일시적인 오류가 발생했어요."}}
    text = caplog.text
    assert "InboxIntegrityError" in text and cid not in text and "u-owner" not in text and "소금빵" not in text


def test_me_ignores_body_user_id(table):
    status, body, _ = call(me.handler, "GET /me", SUHYUN, body={"userId": "u-owner"})
    assert status == 200 and body == {"userId": "u-suhyun", "nickname": "수현", "unreadInboxCount": 0}


def test_unknown_inbox_route_404(table):
    status, body, _ = call(inbox.handler, "DELETE /inbox/{itemId}", OWNER, path={"itemId": "x"})
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"
