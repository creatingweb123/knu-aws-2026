"""T20 판정 기준(순수 함수). AWS 없이 단위 테스트한다(tests/unit/test_t20_verdict.py).

T20: 같은 expectedTurn으로 turns를 5회 동시에 보낸다. 판정 항목:
1. 커밋 1회: turn이 1 오르거나(ASKING·READY), 울타리로 같은 turn의 WORKING이다(BE-Q121).
2. 응답: 모두 200 또는 409이고, 200이 1건 이상이며, 409는 모두 AI_SESSION_BUSY다.
3. 같은 SessionView: 200 본문은 모두 같은 턴의 같은 본문이다(중복 요청이 다른 상태를 보지 않는다).
4. 추가 호출 0: 예약 증가(modelCallsReserved 차이) = 커밋된 턴의 모델 호출 수(modelCalls 차이).
   중복 요청이 모델을 부르거나 예약을 쓰면 이 항목이 깨진다. 단일 요청 처리분과 같은지를 본다.
5. 세션당 상한: 예약 합계 ≤ 6.
"""

from __future__ import annotations

import json
from typing import Any

CHECK_NAMES = ("one_commit", "codes", "winner_present", "busy_only", "same_view", "no_extra_calls", "reserved_cap")


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def t20_checks(before: dict[str, Any], after: dict[str, Any], results: list[tuple[int, Any]]) -> dict[str, Any]:
    """before·after는 세션 항목(turn·status·modelCallsReserved·modelCalls). results는 (HTTP, 본문) 목록."""
    codes = [s for s, _ in results]
    oks = [b for s, b in results if s == 200]
    busy = [b for s, b in results if s == 409]
    turn_delta = _int(after.get("turn")) - _int(before.get("turn"))
    reserved_delta = _int(after.get("modelCallsReserved")) - _int(before.get("modelCallsReserved"))
    calls_delta = _int(after.get("modelCalls")) - _int(before.get("modelCalls"))
    same_turn_views = {json.dumps(b, sort_keys=True, ensure_ascii=False) for b in oks if b.get("turn") == after.get("turn")}
    checks = {
        "one_commit": turn_delta == 1 or (turn_delta == 0 and after.get("status") == "WORKING"),
        "codes": all(c in (200, 409) for c in codes),
        "winner_present": len(oks) >= 1,
        "busy_only": all(isinstance(b, dict) and (b.get("error") or {}).get("code") == "AI_SESSION_BUSY" for b in busy),
        "same_view": len(same_turn_views) <= 1 and all(b.get("turn") == after.get("turn") for b in oks),
        "no_extra_calls": reserved_delta == calls_delta,
        "reserved_cap": _int(after.get("modelCallsReserved")) <= 6,
    }
    checks["_numbers"] = {"turn_delta": turn_delta, "reserved_delta": reserved_delta, "calls_delta": calls_delta,
                          "codes": codes, "busy": len(busy), "ok200": len(oks)}
    return checks


def t20_pass(checks: dict[str, Any]) -> bool:
    return all(bool(checks[k]) for k in CHECK_NAMES)
