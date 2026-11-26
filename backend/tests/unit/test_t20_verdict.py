"""T20 판정 기준의 순수 함수 검사 (tests/integration/verdicts.py). AWS에 접속하지 않는다.

각 항목이 실제로 깨지는 사례를 하나씩 만든다(판정이 항상 통과하지 않는지 확인).
"""

import pytest

from tests.integration.verdicts import CHECK_NAMES, t20_checks, t20_pass

VIEW2 = {"sessionId": "ais_x", "status": "READY", "turn": 2, "card": {"title": "t"}, "question": None}
BUSY = (409, {"error": {"code": "AI_SESSION_BUSY", "message": "x"}})
BEFORE = {"turn": 1, "status": "ASKING", "modelCallsReserved": 2, "modelCalls": 2}
AFTER = {"turn": 2, "status": "READY", "modelCallsReserved": 4, "modelCalls": 4}


def ok_results(view=VIEW2, n=1):
    return [(200, view)] * n + [BUSY] * (5 - n)


def test_clean_run_passes():
    c = t20_checks(BEFORE, AFTER, ok_results())
    assert t20_pass(c) and set(CHECK_NAMES) <= set(c)
    assert c["_numbers"] == {"turn_delta": 1, "reserved_delta": 2, "calls_delta": 2, "codes": [200, 409, 409, 409, 409], "busy": 4,
                             "ok200": 1}


def test_many_200_with_same_view_pass():
    assert t20_pass(t20_checks(BEFORE, AFTER, ok_results(n=3)))


def test_working_by_fence_without_commit_passes():
    before = {"turn": 1, "status": "WORKING", "modelCallsReserved": 0, "modelCalls": 0}
    after = {"turn": 1, "status": "WORKING", "modelCallsReserved": 1, "modelCalls": 1}
    view = {"sessionId": "ais_x", "status": "WORKING", "turn": 1, "card": None, "question": None}
    assert t20_pass(t20_checks(before, after, ok_results(view)))


def test_duplicate_request_that_reserved_a_call_fails():
    """중복 요청이 예약을 한 번 더 쓰면(모델 추가 호출 가능) 실패한다."""
    c = t20_checks(BEFORE, dict(AFTER, modelCallsReserved=5), ok_results())
    assert c["no_extra_calls"] is False and not t20_pass(c)


def test_reserved_without_matching_calls_fails():
    c = t20_checks(BEFORE, dict(AFTER, modelCalls=3), ok_results())
    assert c["no_extra_calls"] is False


def test_two_commits_fail():
    c = t20_checks(BEFORE, dict(AFTER, turn=3), ok_results(dict(VIEW2, turn=3)))
    assert c["one_commit"] is False and not t20_pass(c)


def test_no_commit_and_not_working_fails():
    c = t20_checks(BEFORE, dict(AFTER, turn=1, status="ASKING"), ok_results(dict(VIEW2, turn=1)))
    assert c["one_commit"] is False


@pytest.mark.parametrize("code", [500, 404, 503, 429])
def test_unexpected_codes_fail(code):
    res = [(200, VIEW2), (code, {"error": {"code": "X"}}), BUSY, BUSY, BUSY]
    assert t20_checks(BEFORE, AFTER, res)["codes"] is False


def test_non_busy_409_fails():
    res = [(200, VIEW2), (409, {"error": {"code": "AI_SESSION_CLOSED"}}), BUSY, BUSY, BUSY]
    assert t20_checks(BEFORE, AFTER, res)["busy_only"] is False


def test_no_200_fails():
    assert t20_checks(BEFORE, AFTER, [BUSY] * 5)["winner_present"] is False


def test_different_views_at_same_turn_fail():
    other = dict(VIEW2, card={"title": "다른 카드"})
    c = t20_checks(BEFORE, AFTER, [(200, VIEW2), (200, other), BUSY, BUSY, BUSY])
    assert c["same_view"] is False and not t20_pass(c)


def test_stale_turn_in_200_fails():
    stale = dict(VIEW2, turn=1)
    c = t20_checks(BEFORE, AFTER, [(200, stale), BUSY, BUSY, BUSY, BUSY])
    assert c["same_view"] is False


def test_reservation_cap_fails():
    c = t20_checks(BEFORE, dict(AFTER, modelCallsReserved=7, modelCalls=7), ok_results())
    assert c["reserved_cap"] is False and not t20_pass(c)
