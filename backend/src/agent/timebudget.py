"""Remaining_Time과 LLM 호출 deadline (design §13, Requirement 9.5, 12.2, 12.5, 12.6, BE-Q90).

남은 시간 = min(Lambda 남은 시간, API Gateway가 요청을 받은 시각(requestContext.timeEpoch) + 29초 − 지금).
HTTP API 통합 상한 30초에는 콜드 스타트 Init도 들어가므로 Lambda 타임아웃만 보지 않는다.
timeEpoch가 없거나 숫자가 아니거나 허용 범위 밖이면 무시하고 Lambda 남은 시간만 쓴다(TIME_EPOCH_IGNORED).
이 계산은 강제 종료를 줄일 뿐 없애지 못한다(Requirement 12.6).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

_log = logging.getLogger("haru.ai")

API_BUDGET_MS = 29_000
SKEW_MS = 2_000
MIN_CALL_START_MS = 12_000   # 12초 규칙: 이보다 적게 남으면 LLM을 부르지 않는다
SAVE_RESERVE_MS = 4_000      # 취소·AsyncClient 종료, PutItem 1회, 확인 조회 일부
VERIFY_MIN_MS = 1_500        # 저장 결과가 불확실할 때 확인 조회를 할 최소 시간
NO_CONTEXT_MS = 27_000       # context가 없는 호출(테스트·스크립트)의 기본 Lambda 예산


def _valid_epoch(value: Any, now_ms: float) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not (now_ms - 30_000 - SKEW_MS <= value <= now_ms + SKEW_MS):
        return None
    return value


class TimeBudget:
    def __init__(
        self,
        context: Any,
        event: dict[str, Any] | None,
        *,
        now_ms: Callable[[], float] = lambda: time.time() * 1000,
        mono: Callable[[], float] = time.monotonic,
    ) -> None:
        self._context = context
        self._now_ms = now_ms
        self._mono = mono
        self._start = mono()
        raw = ((event or {}).get("requestContext") or {}).get("timeEpoch")
        epoch = _valid_epoch(raw, now_ms())
        if raw is not None and epoch is None:
            _log.warning("ai_time reason=TIME_EPOCH_IGNORED")
        self._api_deadline_ms = None if epoch is None else epoch + API_BUDGET_MS

    def _lambda_ms(self) -> float:
        fn = getattr(self._context, "get_remaining_time_in_millis", None)
        if callable(fn):
            return float(fn())
        return NO_CONTEXT_MS - (self._mono() - self._start) * 1000

    def remaining_ms(self) -> float:
        remaining = self._lambda_ms()
        if self._api_deadline_ms is not None:
            remaining = min(remaining, self._api_deadline_ms - self._now_ms())
        return max(0.0, remaining)

    def can_start_call(self) -> bool:
        return self.remaining_ms() >= MIN_CALL_START_MS

    def call_deadline_s(self, max_s: float) -> float:
        """min(호출 1회 상한, 남은 시간 − 저장 여유). 0 이하이면 호출하지 않는다."""
        return max(0.0, min(max_s, (self.remaining_ms() - SAVE_RESERVE_MS) / 1000))

    def can_verify(self) -> bool:
        return self.remaining_ms() >= VERIFY_MIN_MS


AGENT_SAVE_RESERVE_MS = 5_000   # 6b: 호출 뒤 체크포인트 쓰기 수 회 + 커밋 + 확인 조회(임시, BE-Q106)


class AgentDeadline:
    """에이전트 실행의 남은 시간 = min(Remaining_Time, 울타리까지 남은 시간)(design §9.1).

    울타리 뒤에 LLM 호출이 끝나지 않도록 12초 규칙과 호출 deadline을 이 값으로 계산한다.
    """

    def __init__(self, budget: TimeBudget, fence_deadline: float | None, *, mono: Callable[[], float] = time.monotonic,
                 save_reserve_ms: int = AGENT_SAVE_RESERVE_MS) -> None:
        self.budget = budget
        self.fence_deadline = fence_deadline
        self._mono = mono
        self.save_reserve_ms = save_reserve_ms

    def remaining_ms(self) -> float:
        r = self.budget.remaining_ms()
        if self.fence_deadline is not None:
            r = min(r, (self.fence_deadline - self._mono()) * 1000)
        return max(0.0, r)

    def lambda_remaining_ms(self) -> float:
        return self.budget.remaining_ms()

    def can_start_call(self) -> bool:
        return self.remaining_ms() >= MIN_CALL_START_MS

    def call_deadline_s(self, max_s: float) -> float:
        return max(0.0, min(max_s, (self.remaining_ms() - self.save_reserve_ms) / 1000))

    def can_verify(self) -> bool:
        return self.budget.remaining_ms() >= VERIFY_MIN_MS
