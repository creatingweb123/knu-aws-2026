"""핸들러 테스트.

- Property 11: PreSignUp 출력은 두 플래그 true이고 나머지 필드가 입력과 같다 (Requirement 1.4)
- GET /me가 DB를 호출하지 않음, sub 없는 이벤트 401, 예상치 못한 예외 500,
  응답 시간 값이 ISO 8601 UTC (Requirements 2.3, 2.4, 2.5, 2.7, 3.4, 3.5, 11.1, 11.4, 11.5, 11.6)
"""

import base64
import copy
import json
import logging
import re
from datetime import datetime, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from common import ddb
from domain import plan_service
from handlers import me, plans, pre_signup
from handlers.routes import ROUTES
from tests.unit.fake_table import FakeTable
from tests.unit.test_plan_service import plan_item

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def event(route, claims=None, body=None, headers=None, query=None, path=None, raw_body=None):
    ev = {
        "version": "2.0",
        "routeKey": route,
        "headers": headers or {},
        "queryStringParameters": query,
        "pathParameters": path,
        "body": raw_body if raw_body is not None else (json.dumps(body, ensure_ascii=False) if body is not None else None),
        "isBase64Encoded": False,
        "requestContext": {"authorizer": {"jwt": {"claims": {"token_use": "id", **claims}}}} if claims is not None else {},
    }
    return ev


OWNER = {"sub": "u-owner", "nickname": "지연"}
VALID = {
    "title": "이사 전, 마지막 동네 산책",
    "summary": "출근길 빵집에 들르고 싶었어요.",
    "reason": "이삿짐 정리가 길어졌어요.",
    "estimatedMinutes": 45,
    "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}],
    "question": "어떤 소리가 들렸나요?",
    "authoring": {"mode": "MANUAL", "durationMs": 1000, "story": "출근길 빵집에 들러 빵을 사고 싶었어요."},
}


def body_of(resp):
    return json.loads(resp["body"])


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(ddb, "table", lambda: t)
    monkeypatch.setattr(ddb, "transact_with_retry", t.transact)
    return t


@pytest.fixture
def no_db(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("DB를 호출하면 안 된다")

    monkeypatch.setattr(ddb, "table", boom)
    monkeypatch.setattr(ddb, "transact_with_retry", boom)


# -------------------------------------------------------------------- PreSignUp

json_value = st.recursive(st.none() | st.booleans() | st.integers() | st.text(max_size=10), lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=8), c, max_size=3), max_leaves=10)


@given(
    extra=st.dictionaries(st.text(max_size=10).filter(lambda k: k != "response"), json_value, max_size=5),
    resp_extra=st.dictionaries(st.text(max_size=10).filter(lambda k: k not in ("autoConfirmUser", "autoVerifyEmail")), json_value, max_size=3),
    flags=st.fixed_dictionaries({"autoConfirmUser": st.booleans(), "autoVerifyEmail": st.booleans()}),
)
def test_property11_pre_signup(extra, resp_extra, flags):
    ev = {**extra, "triggerSource": "PreSignUp_SignUp", "response": {**resp_extra, **flags}}
    original = copy.deepcopy(ev)
    out = pre_signup.handler(copy.deepcopy(ev), None)
    assert out["response"]["autoConfirmUser"] is True and out["response"]["autoVerifyEmail"] is True
    assert {k: v for k, v in out.items() if k != "response"} == {k: v for k, v in original.items() if k != "response"}
    assert {k: v for k, v in out["response"].items() if k not in flags} == resp_extra


# ------------------------------------------------------------------------ GET /me


def test_me_returns_claims_without_db(no_db):
    resp = me.handler(event("GET /me", OWNER, body={"userId": "someone-else"}), None)
    assert resp["statusCode"] == 200
    assert body_of(resp) == {"userId": "u-owner", "nickname": "지연", "unreadInboxCount": 0}


@pytest.mark.parametrize("handler,route", [(me.handler, "GET /me"), (plans.handler, "GET /plans"), (plans.handler, "POST /plans"), (plans.handler, "GET /plans/{planId}")])
def test_missing_sub_is_401_without_db(no_db, handler, route):
    for claims in (None, {}, {"nickname": "지연"}):
        resp = handler(event(route, claims, query={"status": "OPEN"}, path={"planId": "p1"}, body=VALID, headers={"idempotency-key": "k"}), None)
        assert resp["statusCode"] == 401
        assert body_of(resp) == {"error": {"code": "UNAUTHORIZED", "message": body_of(resp)["error"]["message"]}}


# ---------------------------------------------------------------------- POST /plans


def test_create_returns_201_and_replays_201(table):
    ev = event("POST /plans", OWNER, body=VALID, headers={"idempotency-key": "k1"})
    first = plans.handler(ev, None)
    again = plans.handler(copy.deepcopy(ev), None)
    assert first["statusCode"] == 201 and again["statusCode"] == 201
    p1, p2 = body_of(first)["plan"], body_of(again)["plan"]
    assert p1 == p2 and p1["status"] == "OPEN" and "metrics" in p1
    assert ISO_UTC.match(p1["createdAt"]) and p1["completedAt"] is None
    assert table.count("PLAN#") == 1


def test_create_header_case_insensitive(table):
    resp = plans.handler(event("POST /plans", OWNER, body=VALID, headers={"Idempotency-Key": "k1"}), None)
    assert resp["statusCode"] == 201


def test_create_base64_body(table):
    raw = base64.b64encode(json.dumps(VALID).encode()).decode()
    ev = event("POST /plans", OWNER, raw_body=raw, headers={"idempotency-key": "k1"})
    ev["isBase64Encoded"] = True
    assert plans.handler(ev, None)["statusCode"] == 201


def test_create_validation_error_details(table):
    bad = copy.deepcopy(VALID)
    bad["places"][0]["name"] = ""
    resp = plans.handler(event("POST /plans", OWNER, body=bad, headers={"idempotency-key": "k1"}), None)
    assert resp["statusCode"] == 400
    err = body_of(resp)["error"]
    assert err["code"] == "VALIDATION_ERROR" and "places[0].name" in err["details"]
    assert table.items == {}


def test_create_missing_key_and_bad_body_reported_together(table):
    bad = copy.deepcopy(VALID)
    del bad["title"]
    resp = plans.handler(event("POST /plans", OWNER, body=bad), None)
    details = body_of(resp)["error"]["details"]
    assert resp["statusCode"] == 400 and set(details) == {"Idempotency-Key", "title"}
    assert table.items == {}


@pytest.mark.parametrize("raw", ["{not json", ""])
def test_create_bad_json(table, raw):
    resp = plans.handler(event("POST /plans", OWNER, raw_body=raw, headers={"idempotency-key": "k1"}), None)
    assert resp["statusCode"] == 400 and "body" in body_of(resp)["error"]["details"]


def test_create_conflict_409_has_no_details(table):
    plans.handler(event("POST /plans", OWNER, body=VALID, headers={"idempotency-key": "k1"}), None)
    changed = {**VALID, "title": "바뀐 제목"}
    resp = plans.handler(event("POST /plans", OWNER, body=changed, headers={"idempotency-key": "k1"}), None)
    assert resp["statusCode"] == 409 and set(body_of(resp)["error"]) == {"code", "message"}


# ------------------------------------------------------------------- GET /plans[/id]


def test_list_and_detail(table):
    created = body_of(plans.handler(event("POST /plans", OWNER, body=VALID, headers={"idempotency-key": "k1"}), None))["plan"]
    listed = body_of(plans.handler(event("GET /plans", {"sub": "u-other", "nickname": "수현"}, query={"status": "OPEN"}), None))
    assert listed["nextCursor"] is None and [i["planId"] for i in listed["items"]] == [created["planId"]]
    detail = plans.handler(event("GET /plans/{planId}", {"sub": "u-other"}, path={"planId": created["planId"]}), None)
    d = body_of(detail)
    assert detail["statusCode"] == 200 and d["claimable"] is True and d["isOwner"] is False and "metrics" not in d["plan"]


def test_list_bad_status_400(table):
    resp = plans.handler(event("GET /plans", OWNER, query={"status": "CLAIMED"}), None)
    assert resp["statusCode"] == 400


def test_detail_not_found(table):
    resp = plans.handler(event("GET /plans/{planId}", OWNER, path={"planId": "pln_none"}), None)
    assert resp["statusCode"] == 404 and body_of(resp)["error"]["code"] == "NOT_FOUND"


def test_unknown_route_404(table):
    assert plans.handler(event("DELETE /plans", OWNER), None)["statusCode"] == 404


# ----------------------------------------------------------------- 예상치 못한 예외


def test_unexpected_error_is_500_without_leaks(table, monkeypatch, caplog):
    secret = "토큰eyJhbGciOi 사연 원문 내부ID-123"

    def explode(*a, **k):
        raise RuntimeError(secret)

    monkeypatch.setattr(plan_service, "list_plans", explode)
    with caplog.at_level(logging.ERROR):
        resp = plans.handler(event("GET /plans", OWNER, query={"status": "OPEN"}), None)
    assert resp["statusCode"] == 500
    err = body_of(resp)["error"]
    assert err["code"] == "INTERNAL_ERROR" and set(err) == {"code", "message"}
    assert secret not in resp["body"] and "Traceback" not in resp["body"]
    assert secret not in caplog.text and "RuntimeError" in caplog.text


def test_detail_times_are_iso_utc(table):
    table.put(plan_item(1, "OPEN", datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)))
    p = body_of(plans.handler(event("GET /plans/{planId}", OWNER, path={"planId": "p1"}), None))["plan"]
    assert ISO_UTC.match(p["createdAt"])


def test_routes_cover_stage_1_to_3():
    assert set(ROUTES) == {
        "GET /me", "GET /me/claims",
        "POST /plans", "GET /plans", "GET /plans/{planId}", "POST /plans/{planId}/claims",
        "POST /claims/{claimId}/abandon", "PUT /claims/{claimId}/record", "POST /claims/{claimId}/complete",
    }
