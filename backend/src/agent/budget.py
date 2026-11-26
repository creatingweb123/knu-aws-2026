"""세션 예산의 모델 호출 예약 (design §8.1·§8.3, BE-Q97·BE-Q120).

- 모델 호출 직전에 AiSession에 조건부 ADD로 예약한다. 조건: 이 실행의 lockToken, 예약 수 < 6, 차감 토큰 + 추정 ≤ 30,000.
- 예약 결과를 모르면(타임아웃·연결 오류) 호출하지 않는다. 예약은 환불하지 않는다. 그래서 세션 하나의 실제 외부 호출 수 ≤ 6이다.
  복구 재호출도 같은 예약에서만 나온다(복구용 별도 한도 없음).
- 노드·도구는 DB를 모른다. 핸들러가 만든 BudgetService를 LlmCaller에 주입한다(BE-AI-04 해석).
- 토큰 추정은 보수적으로 한다(BE-Q120): 글자 수 / 2에 1.15배. NVIDIA NIM 실측에서 글자 수 / 2가 실제보다 6–8% 작았다.
  추정은 상한이 아니다. 실제 usage가 오면 커밋 때 차이를 더 차감한다. 응답 usage를 남기기 전 강제 종료된 호출은 추정치만 차감된다.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

_log = logging.getLogger("haru.ai")

MAX_MODEL_CALLS = 6
MAX_INPUT_TOKENS = 30_000
TOKEN_CHARS_PER_TOKEN = 2.0      # 6a와 같음
TOKEN_SAFETY = 1.15              # BE-Q120 보수 계수(실측 비 1.06–1.08 + 여유)


class BudgetError(Exception):
    """예약 실패. LlmError가 아니다(공급자 오류와 구분)."""


class FenceLost(BudgetError):
    """이 실행이 더 이상 잠금을 갖고 있지 않다(lockToken 불일치). 실행을 멈추고 커밋하지 않는다."""


class BudgetExhausted(BudgetError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind  # CALLS | TOKENS


class ReservationUncertain(BudgetError):
    """예약 결과를 모른다. 호출하지 않는다(환불도 없다)."""


@dataclass(frozen=True)
class Reservation:
    index: int       # 갱신 뒤 modelCallsReserved(1–6)
    est_tokens: int


def estimate_tokens(messages: list[Any], tools: list[Any] | None = None) -> int:
    chars = sum(len(str(getattr(m, "content", "") or "")) for m in messages)
    for m in messages:
        for c in getattr(m, "tool_calls", None) or []:
            chars += len(json.dumps(c.get("args", {}), ensure_ascii=False))
    if tools:
        chars += len(json.dumps(tools, ensure_ascii=False, default=str))
    divisor = float(os.environ.get("AI_TOKEN_EST_DIVISOR", "") or TOKEN_CHARS_PER_TOKEN)
    return math.ceil(chars / divisor * TOKEN_SAFETY)


class NoopBudget:
    """DB 없이 같은 상한을 지키는 메모리 예산(단위 테스트·평가 스크립트). 레벨 0은 예산을 쓰지 않는다."""

    def __init__(self, max_calls: int = MAX_MODEL_CALLS, max_tokens: int = MAX_INPUT_TOKENS) -> None:
        self.reserved = 0
        self.charged = 0
        self.max_calls = max_calls
        self.max_tokens = max_tokens

    def reserve(self, est_tokens: int) -> Reservation:
        if self.reserved >= self.max_calls:
            raise BudgetExhausted("CALLS")
        if self.charged + est_tokens > self.max_tokens:
            raise BudgetExhausted("TOKENS")
        self.reserved += 1
        self.charged += est_tokens
        return Reservation(self.reserved, est_tokens)

    def remaining_calls(self) -> int:
        return self.max_calls - self.reserved


class BudgetService:
    """실행 1개(잠금 1개)에 하나. reserved는 잠금 시점의 modelCallsReserved에서 시작한다."""

    def __init__(self, session_id: str, lock_token: str, *, reserved: int, charged: int, table: Any = None,
                 max_calls: int = MAX_MODEL_CALLS, max_tokens: int = MAX_INPUT_TOKENS, hook: Any = None) -> None:
        self.session_id = session_id
        self.lock_token = lock_token
        self.reserved = int(reserved)
        self.charged = int(charged)
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self._table = table
        self._hook = hook
        self.reservations: list[Reservation] = []

    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self.reserved)

    def _tbl(self) -> Any:
        if self._table is not None:
            return self._table
        from common import ddb

        return ddb.table()

    def reserve(self, est_tokens: int) -> Reservation:
        from domain.ai_session_service import get_session, session_key

        from agent import hooks

        hooks.fire("reserve")
        if self._hook:
            self._hook("reserve")
        if self.reserved >= self.max_calls:
            raise BudgetExhausted("CALLS")
        if self.charged + est_tokens > self.max_tokens:
            raise BudgetExhausted("TOKENS")
        try:
            got = self._tbl().update_item(
                Key=session_key(self.session_id),
                # 조건식에는 산술이 없으므로 한도 − 추정을 값으로 넘긴다
                ConditionExpression="lockToken = :token AND modelCallsReserved < :max AND tokenCharged <= :tokLimit",
                UpdateExpression="ADD modelCallsReserved :one, tokenCharged :est",
                ExpressionAttributeValues={":token": self.lock_token, ":max": self.max_calls, ":est": int(est_tokens),
                                           ":tokLimit": self.max_tokens - int(est_tokens), ":one": 1},
                ReturnValues="UPDATED_NEW",
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                _log.warning("ai_budget id=%s reason=RESERVATION_UNCERTAIN type=%s", self.session_id, type(e).__name__)
                raise ReservationUncertain() from None
            try:
                item = get_session(self.session_id, table=self._table) or {}
            except (ClientError, BotoCoreError):
                raise ReservationUncertain() from None
            if item.get("lockToken") != self.lock_token:
                _log.warning("ai_budget id=%s reason=FENCE_LOST", self.session_id)
                raise FenceLost() from None
            self.reserved = int(item.get("modelCallsReserved", self.reserved))
            self.charged = int(item.get("tokenCharged", self.charged))
            kind = "CALLS" if self.reserved >= self.max_calls else "TOKENS"
            raise BudgetExhausted(kind) from None
        except BotoCoreError as e:
            _log.warning("ai_budget id=%s reason=RESERVATION_UNCERTAIN type=%s", self.session_id, type(e).__name__)
            raise ReservationUncertain() from None
        attrs = got.get("Attributes", {})
        self.reserved = int(attrs.get("modelCallsReserved", self.reserved + 1))
        self.charged = int(attrs.get("tokenCharged", self.charged + est_tokens))
        r = Reservation(self.reserved, int(est_tokens))
        self.reservations.append(r)
        return r
