"""AiSession·AiQuota 서비스 (moto). Validates: Requirements 5.1, 5.4, 5.7, 5.8, 6.1–6.5, 19.2–19.4 · BE-Q73, BE-Q89"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from common.errors import ApiError
from domain import ai_session_service as svc
from tests.unit.moto_table import haru_table, set_env

UTC = timezone.utc
NOW = datetime(2026, 11, 26, 3, 0, 0, tzinfo=UTC)  # KST 12:00


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    monkeypatch.delenv("AI_DAILY_SESSION_LIMIT", raising=False)
    with haru_table() as t:
        yield t


def item(**over):
    base = dict(session_id="ais_" + "0" * 26, owner_id="u-owner", story="출근길 빵집", status=svc.READY, created_at=NOW, ready_at=NOW + timedelta(seconds=3),
                card={"title": "t", "summary": None, "reason": None, "estimatedMinutes": 45, "places": [], "question": None},
                flags=[{"path": "summary", "type": "MISSING"}], notes=[], trace=[{"step": 1, "tool": "draft", "summary": "초안 작성"}],
                model_calls=1, llm_mode="fake")
    base.update(over)
    return svc.build_session_item(**base)


# KST 날짜 ------------------------------------------------------------------


def test_quota_day_kst_boundary():
    before = datetime(2026, 11, 26, 14, 59, 59, 999000, tzinfo=UTC)
    after = datetime(2026, 11, 26, 15, 0, 0, tzinfo=UTC)
    d1, ttl1 = svc.quota_day(before)
    d2, ttl2 = svc.quota_day(after)
    assert (d1, d2) == ("20261126", "20261127")
    assert ttl1 == int(datetime(2026, 11, 25, 15, tzinfo=UTC).timestamp()) + 2 * 86400  # KST 11-26 00:00 + 2일
    assert ttl2 == ttl1 + 86400


def test_seoul_fallback_offset(monkeypatch):
    import zoneinfo

    monkeypatch.setattr(zoneinfo, "ZoneInfo", lambda name: (_ for _ in ()).throw(zoneinfo.ZoneInfoNotFoundError(name)))
    tz = svc._seoul()
    assert tz.utcoffset(None) == timedelta(hours=9)
    assert datetime(2026, 11, 26, 15, tzinfo=UTC).astimezone(tz).strftime("%Y%m%d") == "20261127"


# AiQuota --------------------------------------------------------------------


def test_quota_ten_then_429_and_ttl(table):
    for _ in range(10):
        svc.consume_quota("u1", NOW)
    with pytest.raises(ApiError) as e:
        svc.consume_quota("u1", NOW)
    assert e.value.code == "AI_QUOTA_EXCEEDED" and e.value.status == 429
    got = table.get_item(Key=svc.quota_key("u1", NOW))["Item"]
    assert got["sessions"] == 10 and got["ttl"] == svc.quota_day(NOW)[1] and got["PK"] == "AIQUOTA#u1#20261126"


def test_quota_next_kst_day_allowed_and_users_separate(table):
    late = datetime(2026, 11, 26, 14, 59, 59, 999000, tzinfo=UTC)
    for _ in range(10):
        svc.consume_quota("u1", late)
    with pytest.raises(ApiError):
        svc.consume_quota("u1", late)
    svc.consume_quota("u1", late + timedelta(milliseconds=1))  # KST 다음 날 00:00:00.000
    svc.consume_quota("u2", late)  # 다른 사용자
    assert table.get_item(Key=svc.quota_key("u1", late + timedelta(milliseconds=1)))["Item"]["sessions"] == 1


def test_quota_limit_env(table, monkeypatch):
    monkeypatch.setenv("AI_DAILY_SESSION_LIMIT", "2")
    svc.consume_quota("u1", NOW)
    svc.consume_quota("u1", NOW)
    with pytest.raises(ApiError):
        svc.consume_quota("u1", NOW)


def test_quota_write_error_is_500_not_429(table, monkeypatch):
    from botocore.exceptions import ClientError, ReadTimeoutError

    def boom(**kw):
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "UpdateItem")

    monkeypatch.setattr(table, "update_item", boom)
    with pytest.raises(ApiError) as e:
        svc.consume_quota("u1", NOW)
    assert e.value.code == "INTERNAL_ERROR"

    def timeout(**kw):
        raise ReadTimeoutError(endpoint_url="x")

    monkeypatch.setattr(table, "update_item", timeout)
    with pytest.raises(ApiError) as e:
        svc.consume_quota("u1", NOW)
    assert e.value.code == "INTERNAL_ERROR"


@pytest.mark.parametrize(("used", "expected"), [(0, 10), (10, 0), (7, 3)])
def test_quota_concurrent(table, used, expected):
    """동시 15건 → 성공 = 남은 한도. moto는 실제 병렬성을 재현하지 않으므로 조건식 확인이다(판정은 AWS)."""
    user = f"u-{uuid.uuid4()}"
    for _ in range(used):
        svc.consume_quota(user, NOW)
    lock, results = threading.Lock(), []

    def one(_):
        try:
            svc.consume_quota(user, NOW)
            ok = True
        except ApiError as e:
            ok = e.code
        with lock:
            results.append(ok)

    with ThreadPoolExecutor(15) as ex:
        list(ex.map(one, range(15)))
    assert results.count(True) == expected
    assert results.count("AI_QUOTA_EXCEEDED") == 15 - expected


# AiSession ------------------------------------------------------------------


def test_build_and_put_session_roundtrip(table):
    it = item()
    svc.put_session(it)
    got = svc.get_live_session(it["sessionId"], NOW)
    assert got["ownerId"] == "u-owner" and got["status"] == "READY" and got["turn"] == 1 and got["agentMode"] == "PIPELINE"
    assert got["createdAt"] == "2026-11-26T03:00:00.000Z" and got["readyAt"] == "2026-11-26T03:00:03.000Z"
    assert got["ttl"] == int((NOW + timedelta(days=30)).timestamp())
    assert got["card"]["summary"] is None and got["card"]["estimatedMinutes"] == Decimal(45)
    assert got["llmMode"] == "fake" and got["answers"] == [] and got["finishRequested"] is False


def test_put_session_conditional(table):
    from botocore.exceptions import ClientError

    svc.put_session(item())
    with pytest.raises(ClientError) as e:
        svc.put_session(item())
    assert e.value.response["Error"]["Code"] == "ConditionalCheckFailedException"


def test_failed_item_has_no_card():
    it = item(status=svc.FAILED, failure_code="LLM_ERROR", llm_error="HTTP_401")
    assert it["card"] is None and it["flags"] == [] and it["notes"] == [] and "readyAt" not in it and it["degraded"] is False
    assert it["failureCode"] == "LLM_ERROR" and it["llmError"] == "HTTP_401"


@pytest.mark.parametrize(("delta", "live"), [(-1, True), (0, False), (1, False)])
def test_ttl_boundary(table, delta, live):
    it = item()
    svc.put_session(it)
    now = datetime.fromtimestamp(it["ttl"], UTC) + timedelta(seconds=delta)
    assert (svc.get_live_session(it["sessionId"], now) is not None) is live
    assert svc.get_session(it["sessionId"]) is not None  # 항목은 남아 있다


@pytest.mark.parametrize("ttl", [None, "soon", True])
def test_invalid_ttl_is_expired(ttl):
    it = item()
    if ttl is None:
        it.pop("ttl")
    else:
        it["ttl"] = ttl
    assert svc.is_live(it, NOW) is False


def test_verify_saved(table):
    it = item()
    assert svc.verify_saved(it) is False
    svc.put_session(it)
    assert svc.verify_saved(it) is True
    other = dict(it, ownerId="u-other")
    assert svc.verify_saved(other) is False


# SessionView ----------------------------------------------------------------


def test_session_view_ready():
    it = item(notes=[{"path": "places[1].name", "action": "REMOVED", "reason": "r", "source": "STORY", "secret": "x"}])
    view = svc.serialize_session_view(it)
    assert list(view) == list(svc.VIEW_KEYS)
    assert view["question"] is None and view["degraded"] is False and view["turn"] == 1
    assert view["card"]["places"] == [] and view["flags"] == [{"path": "summary", "type": "MISSING"}]
    assert view["notes"] == [{"path": "places[1].name", "action": "REMOVED", "reason": "r", "source": "STORY"}]
    for hidden in ("ownerId", "story", "llmMode", "firstProposal", "ttl", "PK"):
        assert hidden not in view


def test_session_view_failed_and_decimal():
    it = item(status=svc.FAILED)
    it["turn"] = Decimal(1)
    view = svc.serialize_session_view(it)
    assert view["card"] is None and view["flags"] == [] and view["notes"] == [] and view["turn"] == 1 and view["trace"]
