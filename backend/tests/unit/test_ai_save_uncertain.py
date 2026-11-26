"""세션 저장의 불확실성 (작업 9.6, design §4.4, BE-Q89). 어떤 경우에도 할당량은 되돌리지 않는다."""

import logging
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError

from common.ids import new_session_id
from domain import ai_session_service as svc
from handlers import ai_card
from tests.unit.ai_handler_util import Ctx, ai_env, body_of, create, quota_count, sessions  # noqa: F401

CCF = ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem")
THROTTLE = ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "PutItem")


def timeout():
    return ReadTimeoutError(endpoint_url="https://dynamodb.invalid")


@pytest.fixture
def real_put():
    return svc.put_session


def test_timeout_after_commit_verified_200(ai_env, monkeypatch, real_put, caplog):
    caplog.set_level(logging.INFO, "haru.ai")
    def put(item, **k):
        real_put(item)
        raise timeout()

    monkeypatch.setattr(svc, "put_session", put)
    resp = create()
    assert resp["statusCode"] == 200 and body_of(resp)["status"] == "READY"
    assert "SAVE_VERIFIED" in caplog.text and "SESSION_SAVE_UNCERTAIN" in caplog.text and quota_count(ai_env) == 1


def test_conditional_failure_on_our_item_200(ai_env, monkeypatch, real_put):
    def put(item, **k):  # SDK 재시도: 첫 시도가 커밋됐고 두 번째가 조건 실패
        real_put(item)
        raise CCF

    monkeypatch.setattr(svc, "put_session", put)
    assert create()["statusCode"] == 200 and quota_count(ai_env) == 1


def test_conditional_failure_other_item_500(ai_env, monkeypatch, caplog):
    sid = new_session_id()
    other = svc.build_session_item(session_id=sid, owner_id="u-someone", story="x", status="READY",
                                   created_at=datetime.now(timezone.utc))
    svc.put_session(other)
    monkeypatch.setattr(ai_card, "new_session_id", lambda: sid)
    resp = create()
    assert resp["statusCode"] == 500 and body_of(resp)["error"]["code"] == "INTERNAL_ERROR"
    assert "OTHER_ITEM" in caplog.text and quota_count(ai_env) == 1
    [kept] = sessions(ai_env)
    assert kept["ownerId"] == "u-someone"  # 남의 항목을 덮어쓰지 않는다


@pytest.mark.parametrize("err", [timeout(), EndpointConnectionError(endpoint_url="https://dynamodb.invalid"), THROTTLE])
def test_verify_read_fails_500(ai_env, monkeypatch, err, caplog):
    def put(item, **k):
        raise err

    monkeypatch.setattr(svc, "put_session", put)
    monkeypatch.setattr(svc, "get_session", lambda *a, **k: (_ for _ in ()).throw(timeout()))
    resp = create()
    assert resp["statusCode"] == 500 and "cause=READ" in caplog.text and quota_count(ai_env) == 1


def test_not_saved_and_verify_finds_nothing_500(ai_env, monkeypatch):
    monkeypatch.setattr(svc, "put_session", lambda item, **k: (_ for _ in ()).throw(timeout()))
    resp = create()
    assert resp["statusCode"] == 500 and sessions(ai_env) == [] and quota_count(ai_env) == 1


def test_no_time_to_verify_500_without_read(ai_env, monkeypatch, real_put, caplog):
    ctx = Ctx(25_000)

    def put(item, **k):
        real_put(item)
        ctx.remaining_ms = 1_499
        raise timeout()

    monkeypatch.setattr(svc, "put_session", put)
    monkeypatch.setattr(svc, "verify_saved", lambda *a, **k: pytest.fail("시간이 없으면 확인 조회를 하지 않는다"))
    resp = create(ctx=ctx)
    assert resp["statusCode"] == 500 and "cause=TIME" in caplog.text and quota_count(ai_env) == 1


def test_failed_session_save_uncertain_also_500(ai_env, monkeypatch):
    """FAILED 세션도 저장을 확정하지 못하면 503·502 대신 500이다(카드·오류 코드를 근거 없이 내보내지 않는다)."""
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "http_401")
    monkeypatch.setattr(svc, "put_session", lambda item, **k: (_ for _ in ()).throw(timeout()))
    assert create()["statusCode"] == 500
