"""3단계 핸들러: 이어받기(plans), 포기·기록·완료(claims), 내 이어받기(me). moto 대상.

Validates: spec backend-stage3-claim Requirements 1.1, 1.4, 2.1, 3.1, 3.3, 3.4, 4.5, 4.7, 5.1, 5.2, 7.1
"""

import json
from datetime import datetime, timezone

import pytest

pytest.importorskip("moto")

from handlers import claims, me, plans  # noqa: E402
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


@pytest.fixture(autouse=True)
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


def ev(route, claims_=None, body=None, path=None, query=None, headers=None):
    return {
        "version": "2.0",
        "routeKey": route,
        "headers": headers or {},
        "pathParameters": path,
        "queryStringParameters": query,
        "body": json.dumps(body, ensure_ascii=False) if body is not None else None,
        "isBase64Encoded": False,
        "requestContext": {"authorizer": {"jwt": {"claims": {"token_use": "id", **claims_}}}} if claims_ is not None else {},
    }


def call(handler, *args, **kw):
    resp = handler(ev(*args, **kw), None)
    return resp["statusCode"], json.loads(resp["body"]) if resp.get("body") else None


def make_plan():
    status, body = call(plans.handler, "POST /plans", OWNER, body=PLAN, headers={"idempotency-key": "k1"})
    assert status == 201
    return body["plan"]["planId"]


def test_claim_201_then_200():
    pid = make_plan()
    s1, b1 = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    s2, b2 = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    assert (s1, s2) == (201, 200) and b1["claim"]["claimId"] == b2["claim"]["claimId"]
    assert set(b1["claim"]) == {"claimId", "planId", "claimer", "status", "claimedAt", "dueAt", "completedAt", "late"}
    assert b1["claim"]["claimer"] == {"userId": "u-suhyun", "nickname": "수현"} and b1["claim"]["status"] == "ACTIVE"


@pytest.mark.parametrize("who,code", [(OWNER, "CANNOT_CLAIM_OWN_PLAN"), (MINJUN, "ALREADY_CLAIMED")])
def test_claim_409s(who, code):
    pid = make_plan()
    call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    status, body = call(plans.handler, "POST /plans/{planId}/claims", who, path={"planId": pid})
    assert status == 409 and body["error"]["code"] == code and "details" not in body["error"]


def test_full_flow_record_complete_and_my_claims():
    pid = make_plan()
    _, b = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    cid = b["claim"]["claimId"]
    status, body = call(me.handler, "GET /me/claims", SUHYUN, query={"status": "ACTIVE"})
    assert status == 200 and [i["claim"]["claimId"] for i in body["items"]] == [cid]

    status, body = call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "소금빵을 샀어요"}, path={"claimId": cid})
    assert status == 200 and body["upload"] is None
    assert body["record"]["letter"] == "소금빵을 샀어요" and body["record"]["photoStatus"] == "NONE" and body["record"]["deliveredAt"] is None

    status, body = call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
    assert status == 200 and body["delivered"] is True and body["hasPhoto"] is False and body["claim"]["status"] == "COMPLETED"
    status, again = call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
    assert status == 200 and again["delivered"] is True

    _, done = call(me.handler, "GET /me/claims", SUHYUN, query={"status": "COMPLETED"})
    assert [i["claim"]["claimId"] for i in done["items"]] == [cid] and done["items"][0]["record"]["deliveredAt"]


def test_abandon_flow_and_errors():
    pid = make_plan()
    _, b = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    cid = b["claim"]["claimId"]
    status, body = call(claims.handler, "POST /claims/{claimId}/abandon", MINJUN, path={"claimId": cid})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    status, body = call(claims.handler, "POST /claims/{claimId}/abandon", SUHYUN, path={"claimId": cid})
    assert status == 200 and body["claim"]["status"] == "ABANDONED"
    status, body = call(claims.handler, "POST /claims/{claimId}/abandon", SUHYUN, path={"claimId": cid})
    assert status == 409 and body["error"]["code"] == "CLAIM_NOT_ACTIVE"
    status, body = call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "늦은 글"}, path={"claimId": cid})
    assert status == 409 and body["error"]["code"] == "CLAIM_NOT_ACTIVE"
    status, body = call(claims.handler, "POST /claims/{claimId}/abandon", SUHYUN, path={"claimId": "clm_none"})
    assert status == 404


def test_record_validation():
    pid = make_plan()
    _, b = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    cid = b["claim"]["claimId"]
    for payload, key in [({"letter": ""}, "letter"), ({"letter": "가" * 1001}, "letter"), ({}, "letter"), (None, "body")]:
        status, body = call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body=payload, path={"claimId": cid})
        assert status == 400 and key in body["error"]["details"], payload
    status, body = call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "글", "photo": {"contentType": "image/jpeg", "size": 10}}, path={"claimId": cid})
    assert status == 400 and set(body["error"]["details"]) == {"photo"}  # BE-Q34


def test_complete_validation_and_record_required():
    pid = make_plan()
    _, b = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    cid = b["claim"]["claimId"]
    status, body = call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "WITH_PHOTO"}, path={"claimId": cid})
    assert status == 400 and body["error"]["details"] == {"mode": "TEXT_ONLY여야 해요."}
    status, body = call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
    assert status == 400 and body["error"]["code"] == "RECORD_REQUIRED" and "details" not in body["error"]
    status, body = call(claims.handler, "POST /claims/{claimId}/complete", MINJUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
    assert status == 403


def test_my_claims_bad_status():
    status, body = call(me.handler, "GET /me/claims", SUHYUN, query={"status": "ALL"})
    assert status == 400 and "status" in body["error"]["details"]
    status, body = call(me.handler, "GET /me/claims", SUHYUN)
    assert status == 400


@pytest.mark.parametrize(
    "handler,route,path",
    [
        (plans.handler, "POST /plans/{planId}/claims", {"planId": "p"}),
        (claims.handler, "POST /claims/{claimId}/abandon", {"claimId": "c"}),
        (claims.handler, "PUT /claims/{claimId}/record", {"claimId": "c"}),
        (claims.handler, "POST /claims/{claimId}/complete", {"claimId": "c"}),
        (me.handler, "GET /me/claims", None),
    ],
)
def test_no_sub_401(handler, route, path):
    status, body = call(handler, route, {}, body={"letter": "x", "mode": "TEXT_ONLY"}, path=path, query={"status": "ACTIVE"})
    assert status == 401 and body["error"]["code"] == "UNAUTHORIZED"


def test_me_counts_empty_inbox():
    """4단계부터 GET /me는 수신함을 Query한다(BE-AUTH-05, BE-Q30 앞부분 해소). 수신함이 빈 사용자는 0."""
    status, body = call(me.handler, "GET /me", SUHYUN)
    assert status == 200 and body["unreadInboxCount"] == 0
    resp = me.handler({"requestContext": {"authorizer": {"jwt": {"claims": {"token_use": "id", **SUHYUN}}}}}, None)  # routeKey 없는 이전 이벤트
    assert resp["statusCode"] == 200


def test_time_values_are_millis_utc():
    pid = make_plan()
    _, b = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    assert datetime.fromisoformat(b["claim"]["claimedAt"].replace("Z", "+00:00")).tzinfo == timezone.utc
    assert b["claim"]["claimedAt"].endswith("Z") and len(b["claim"]["claimedAt"]) == 24
