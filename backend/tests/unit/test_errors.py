"""Property 10: 모든 4xx/5xx 본문이 {error:{code,message,details?}}이고 details는 VALIDATION_ERROR에만 있다.

Validates: Requirements 11.1, 11.2, 11.3, 11.6, 11.7
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from common.errors import CODE_STATUS, VALIDATION_ERROR, ApiError
from common.ids import new_plan_id
from common.responses import error_response, iso_utc, ok

details_st = st.none() | st.dictionaries(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=40), max_size=5)


@given(code=st.sampled_from(sorted(CODE_STATUS)), message=st.none() | st.text(min_size=1), details=details_st)
def test_error_body_shape(code, message, details):
    resp = error_response(ApiError(code, message=message, details=details))
    assert resp["statusCode"] == CODE_STATUS[code]
    assert 400 <= resp["statusCode"] <= 599
    body = json.loads(resp["body"])
    assert set(body) == {"error"}
    err = body["error"]
    assert isinstance(err["code"], str) and err["code"] == code
    assert isinstance(err["message"], str) and err["message"]
    if code == VALIDATION_ERROR:
        assert set(err) == {"code", "message", "details"}
        assert err["details"] == (details or {})
    else:
        assert set(err) == {"code", "message"}


def test_status_must_match_contract():
    assert ApiError("UNAUTHORIZED", 401).status == 401
    with pytest.raises(ValueError):
        ApiError("UNAUTHORIZED", 403)
    with pytest.raises(ValueError):
        ApiError("AI_UNAVAILABLE")  # 아직 구현하지 않은 단계(6단계)의 코드
    with pytest.raises(ValueError):
        ApiError("FORBIDDEN", 404)


def test_contract_code_status_pairs():
    """docs/03 §3.6과 같은 조합(1–4단계 범위)."""
    assert CODE_STATUS == {
        "VALIDATION_ERROR": 400,
        "RECORD_REQUIRED": 400,
        "UNAUTHORIZED": 401,
        "FORBIDDEN": 403,
        "NOT_FOUND": 404,
        "ALREADY_CLAIMED": 409,
        "CANNOT_CLAIM_OWN_PLAN": 409,
        "CLAIM_NOT_ACTIVE": 409,
        "IDEMPOTENCY_CONFLICT": 409,
        "REPLY_ALREADY_SENT": 409,  # 4단계
        "TRY_AGAIN": 503,
        "INTERNAL_ERROR": 500,  # BE-Q23 임시
    }


def test_emf_line_format():
    from common.metrics import emf_line

    doc = json.loads(emf_line("ClaimConflict", 1, timestamp_ms=1234))
    assert doc == {
        "_aws": {"Timestamp": 1234, "CloudWatchMetrics": [{"Namespace": "Haru", "Dimensions": [[]], "Metrics": [{"Name": "ClaimConflict", "Unit": "Count"}]}]},
        "ClaimConflict": 1,
    }


def test_claim_id_format():
    from common.ids import new_claim_id

    a, b = new_claim_id(), new_claim_id()
    assert a.startswith("clm_") and len(a) == 30 and a != b


def test_ok_without_body():
    resp = ok(204, None)
    assert resp["statusCode"] == 204 and "body" not in resp


def test_ok_keeps_korean():
    assert "지연" in ok(200, {"nickname": "지연"})["body"]


@given(st.datetimes(timezones=st.sampled_from([timezone.utc, timezone(timedelta(hours=9))])))
def test_iso_utc_is_utc_z(dt):
    text = iso_utc(dt)
    assert text.endswith("Z")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    assert abs(parsed - dt) < timedelta(milliseconds=1)


def test_iso_utc_example():
    assert iso_utc(datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)) == "2026-11-17T09:00:00.000Z"


@given(a=st.datetimes(timezones=st.just(timezone.utc)), b=st.datetimes(timezones=st.just(timezone.utc)))
def test_iso_utc_string_order_matches_time_order(a, b):
    if a.year >= 1000 and b.year >= 1000:  # 연도 자릿수가 같을 때
        assert (iso_utc(a) < iso_utc(b)) == (a.replace(microsecond=a.microsecond // 1000 * 1000) < b.replace(microsecond=b.microsecond // 1000 * 1000))


def test_plan_id_format():
    a, b = new_plan_id(), new_plan_id()
    assert a.startswith("pln_") and len(a) == 4 + 26 and a != b


def test_reply_already_sent_body():
    """spec backend-stage4-record-inbox Requirement 10.2: §3.6과 같은 409, details 없음."""
    body = json.loads(error_response(ApiError("REPLY_ALREADY_SENT")).get("body"))
    assert error_response(ApiError("REPLY_ALREADY_SENT"))["statusCode"] == 409
    assert body == {"error": {"code": "REPLY_ALREADY_SENT", "message": "이미 답장을 보냈어요."}}
