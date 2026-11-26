"""Remaining_Time과 deadline 계산 (design §13.1, Requirement 9.5, 12.2, 12.5 · BE-Q90)."""

import logging

import pytest

from agent.timebudget import MIN_CALL_START_MS, SAVE_RESERVE_MS, TimeBudget

NOW = 1_800_000_000_000.0


class Ctx:
    def __init__(self, ms):
        self.ms = ms

    def get_remaining_time_in_millis(self):
        return self.ms


def tb(lambda_ms=27_000, epoch=None, now=NOW):
    event = {"requestContext": {} if epoch is None else {"timeEpoch": epoch}}
    return TimeBudget(Ctx(lambda_ms), event, now_ms=lambda: now)


def test_lambda_only_without_epoch():
    assert tb(27_000).remaining_ms() == 27_000


def test_epoch_limits_remaining():
    assert tb(27_000, int(NOW) - 3_000).remaining_ms() == 26_000  # 29 − 3
    assert tb(20_000, int(NOW) - 3_000).remaining_ms() == 20_000  # Lambda가 더 작음


def test_cold_start_init_eats_api_budget():
    """Init 3.5초 뒤 핸들러 시작: Lambda는 27초 남았어도 API 기준 25.5초."""
    assert tb(27_000, int(NOW) - 3_500).remaining_ms() == 25_500


@pytest.mark.parametrize("bad", ["1800000000000", -5, 1.5e12, True, int(NOW) + 10_000, int(NOW) - 40_000, [1]])
def test_invalid_epoch_ignored(bad, caplog):
    caplog.set_level(logging.WARNING, logger="haru.ai")
    assert tb(27_000, bad).remaining_ms() == 27_000
    assert "TIME_EPOCH_IGNORED" in caplog.text


def test_epoch_skew_tolerance():
    assert tb(27_000, int(NOW) + 1_500).remaining_ms() == 27_000  # 미래 1.5초까지는 받아들이지만 Lambda가 더 작다
    assert tb(27_000, int(NOW) - 31_000).remaining_ms() == 0      # 허용 범위 안이지만 이미 지남 → 0


@pytest.mark.parametrize(("ms", "can"), [(MIN_CALL_START_MS - 1, False), (MIN_CALL_START_MS, True)])
def test_twelve_second_rule(ms, can):
    assert tb(ms).can_start_call() is can


def test_call_deadline():
    assert tb(27_000).call_deadline_s(10) == 10
    assert tb(12_000).call_deadline_s(10) == (12_000 - SAVE_RESERVE_MS) / 1000
    assert tb(3_000).call_deadline_s(10) == 0


def test_verify_threshold():
    assert tb(1_500).can_verify() and not tb(1_499).can_verify()


def test_no_context_uses_default_budget():
    b = TimeBudget(None, None)
    assert 26_000 < b.remaining_ms() <= 27_000
