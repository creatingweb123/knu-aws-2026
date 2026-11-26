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


# ---------------------------------------------------------------- P46: 계보 선택과 TTL

run_kind = st.sampled_from(["legit", "late_unknown", "wrong_turn", "bad_resume", "late_prev_attempt"])


# Feature: backend-stage6b-ai-agent, Property 46
@HEAVY
@given(kinds=st.lists(run_kind, min_size=1, max_size=4), ttl_left=st.integers(120, 30 * 86400))
@example(kinds=["legit", "late_unknown"], ttl_left=3600)
@example(kinds=["legit", "legit", "late_prev_attempt"], ttl_left=3600)
@example(kinds=["bad_resume", "legit", "legit"], ttl_left=120)
def test_property_46_tip_selection_and_ttl(kinds, ttl_left):
    """Property 46: 체크포인트 ttl ≤ AiSession ttl. 임의의 늦은 쓰기·포크·표지 오염에서 tip은 커밋 기준의 자손이고
    조상은 이번 턴·turnRuns 실행·알려진 resumeId만 담으며, 더 큰 시도 가지가 있으면 그 가지에서 고른다.
    Validates: Requirements 6.3, 7.1 · BE-Q94, BE-Q104"""
    import time

    import boto3
    from langgraph.types import Command
    from moto import mock_aws

    from agent import checkpoint as ck
    from tests.unit.test_agent_checkpoint import ANS, TABLE, create_table, graph, hist, run

    with mock_aws():
        c = boto3.client("dynamodb", region_name="ap-northeast-2")
        create_table(c)
        store = ck.CheckpointStore(TABLE, region_name="ap-northeast-2")
        now = time.time()
        session_ttl = int(now) + ttl_left
        saver = store.for_run(session_ttl=session_ttl, now_epoch=now)
        app = graph(saver)
        run(app, {"log": []}, "p", 1, "R1", 1)
        base = ck.checkpoint_id_of(saver.last_config)
        turn_runs, legit_attempts = [], []
        for i, k in enumerate(kinds):
            rid = f"X{i}"
            if k == "legit":
                turn_runs.append(rid)
                run(app, Command(resume=ANS), "p", 2, rid, len(turn_runs), ckpt=base, resume_id="r1-q1")
                legit_attempts.append(len(turn_runs))
            elif k == "late_unknown":
                run(app, Command(resume=ANS), "p", 2, rid, 1, ckpt=base)
            elif k == "wrong_turn":
                run(app, Command(resume=ANS), "p", 1, rid, 1, ckpt=base)
            elif k == "bad_resume":
                run(app, Command(resume=dict(ANS, resumeId="r9-zz")), "p", 2, rid, 1, ckpt=base)
            elif k == "late_prev_attempt" and turn_runs:  # 이전 시도의 늦은 쓰기(같은 runId·attempt)
                prev = turn_runs[0]
                run(app, Command(resume=ANS), "p", 2, prev, 1, ckpt=base, resume_id="r1-q1")
        h = hist(saver, "p")
        me = "ME"
        tip = ck.select_tip(h, base=base, run_turn=2, turn_runs=turn_runs + [me], my_run_id=me, known_resume_ids={"r1-q1"})
        by = {ck.checkpoint_id_of(t.config): t for t in h}
        assert tip.kind == "TIP"
        cur, seen = tip.checkpoint_id, 0
        while cur != base:  # 조상 사슬이 모두 정당
            t = by[cur]
            assert t.metadata["runTurn"] == 2 and t.metadata["runId"] in turn_runs
            assert turn_runs.index(t.metadata["runId"]) + 1 == t.metadata["runAttempt"]
            cur = ck.checkpoint_id_of(t.parent_config)
            seen += 1
            assert seen < 64
        # 기대값을 따로 계산: 정당한 시도 중 가지 전체가 알려진 resumeId만 소비한 시도의 최댓값
        # (앞선 실행이 기준에 남긴 RESUME 쓰기가 먼저 적용되면 그 시도의 가지도 오염된다, V7)
        def clean(attempt):
            rid = turn_runs[attempt - 1]
            mine = [t for t in h if (t.metadata or {}).get("runId") == rid and t.metadata.get("runAttempt") == attempt]
            return mine and all(set((t.checkpoint.get("channel_values") or {}).get("consumed_resume_ids") or []) <= {"r1-q1"} for t in mine)
        good = [a for a in legit_attempts if clean(a)]
        if good:
            assert by[tip.checkpoint_id].metadata["runAttempt"] == max(good)
        else:
            assert tip.checkpoint_id == base
        items = [i for i in c.scan(TableName=TABLE)["Items"] if "p" in i["PK"]["S"]]
        assert all(int(i["ttl"]["N"]) <= session_ttl for i in items if "ttl" in i)
