"""6b 속성 기반 테스트 (Property 37–48). 태그: Feature: backend-stage6b-ai-agent, Property {n}.

장애 주입·상태 기계 속성은 실행 비용이 커서 max_examples 50 + 고정 @example을 쓴다(tasks.md 공통 규칙).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from botocore.exceptions import ReadTimeoutError
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from agent import budget as b
from domain import ai_session_service as svc

NOW = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
PROPS = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
HEAVY = settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])


# ---------------------------------------------------------------- P37: 예약 상한

op_st = st.lists(st.tuples(st.sampled_from(["reserve", "reserve", "reserve", "uncertain_landed", "uncertain_lost", "relock", "steal"]),
                           st.integers(0, 9_000)), max_size=30)


# Feature: backend-stage6b-ai-agent, Property 37
@PROPS
@given(ops=op_st)
@example(ops=[("reserve", 5000)] * 10)
@example(ops=[("uncertain_landed", 1)] * 8 + [("reserve", 1)])
def test_property_37_reservation_cap(ops):
    """Property 37: 임의의 예약·불확실·잠금 교체 열에서 modelCallsReserved ≤ 6, 실제 호출 ≤ 예약, tokenCharged ≤ 30,000,
    카운터는 줄지 않는다. Validates: Requirements 11.1, 11.4, 11.8 · BE-Q97"""
    from moto import mock_aws

    from tests.unit.moto_table import _shared_table, create_haru_table

    sid = "ais_01ABCDEFGHJKMNPQRSTVWXYZ00"
    with mock_aws():
        t = _shared_table()
        create_haru_table(t.meta.client)
        t.put_item(Item=svc.build_agent_session_item(session_id=sid, owner_id="u", story="s", created_at=NOW, lock_token="L0",
                                                     lock_now_ms=NOW_MS, prompt_version=None, llm_mode="fake", llm_provider_label=None))
        token, run = "L0", 0
        svc_ = b.BudgetService(sid, token, reserved=0, charged=0, table=t)
        calls, last = 0, (0, 0)
        real = t.update_item
        for op, est in ops:
            if op in ("relock", "steal"):
                run += 1
                token = f"L{run}"
                t.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockToken = :t", ExpressionAttributeValues={":t": token})
                if op == "relock":  # 새 실행이 잠금 시점 값을 모른다고 가정(reserved=0)해도 DB가 상한을 지킨다
                    svc_ = b.BudgetService(sid, token, reserved=0, charged=0, table=t)
                continue
            if op.startswith("uncertain"):
                def flaky(_landed=(op == "uncertain_landed"), **kw):
                    if _landed:
                        real(**kw)
                    raise ReadTimeoutError(endpoint_url="https://x.invalid")
                t.update_item = flaky
            try:
                svc_.reserve(est)
                calls += 1  # 예약이 확정됐을 때만 호출한다
            except (b.BudgetExhausted, b.ReservationUncertain, b.FenceLost):
                pass
            finally:
                t.update_item = real
            item = t.get_item(Key=svc.session_key(sid))["Item"]
            now = (int(item["modelCallsReserved"]), int(item["tokenCharged"]))
            assert now[0] <= b.MAX_MODEL_CALLS and now[1] <= b.MAX_INPUT_TOKENS
            assert calls <= now[0]
            assert now[0] >= last[0] and now[1] >= last[1]
            last = now
