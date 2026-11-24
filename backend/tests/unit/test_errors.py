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
        ApiError("FORBIDDEN")  # 이번 범위에서 쓰지 않는 코드


def test_contract_code_status_pairs():
    assert CODE_STATUS == {
        "VALIDATION_ERROR": 400,
        "UNAUTHORIZED": 401,
        "NOT_FOUND": 404,
        "IDEMPOTENCY_CONFLICT": 409,
        "TRY_AGAIN": 503,
        "INTERNAL_ERROR": 500,  # BE-Q23 임시
    }


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
