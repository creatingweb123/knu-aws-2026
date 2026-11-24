"""Property 13·14·15: 무작위 순서의 이어받기·포기·기록·완료 뒤에도 상태가 서로 맞는다 (moto).

- P13 상태 일관성: Plan CLAIMED ⇔ currentClaimId의 Claim이 ACTIVE, ACTIVE Claim은 최대 1건,
  Plan COMPLETED ⇔ COMPLETED Claim 정확히 1건 ⇔ 그 Record에 deliveredAt ⇔ InboxItem 1건,
  version = 1 + 성공한 Plan 갱신 수.
- P14 완료 멱등: 완료를 여러 번 불러도 InboxItem은 최대 1건.
- P15 끝난 이어받기 쓰기 거부: ACTIVE가 아니거나 Current_Claim이 아닌 Claim으로의 기록·완료·포기는 409이고
  Plan·Record·InboxItem을 바꾸지 않는다.

Validates: spec backend-stage3-claim Requirements 2.1, 2.4, 3.3, 4.2, 4.5, 4.9, 4.10, 6.3
"""

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

pytest.importorskip("moto")

from common.auth import User  # noqa: E402
from common.errors import ApiError  # noqa: E402
from common.validation import PlanCreate  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from domain import plan_service as ps  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

START = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
OWNER = User("u-owner", "지연")
USERS = [User("u-a", "가"), User("u-b", "나"), User("u-c", "다")]

op = st.one_of(
    st.tuples(st.just("claim"), st.integers(0, 2)),
    st.tuples(st.just("abandon"), st.integers(0, 2)),
    st.tuples(st.just("record"), st.integers(0, 2)),
    st.tuples(st.just("complete"), st.integers(0, 2)),
    st.tuples(st.just("advance"), st.integers(1, 4)),  # 일 단위로 시간이 흐른다(기한 지난 대체)
)


def snapshot(table, pid):
    items = table.scan(ConsistentRead=True)["Items"]
    plan = next(i for i in items if i["PK"] == f"PLAN#{pid}" and i["SK"] == "META")
    claims = {i["claimId"]: i for i in items if i["PK"] == f"PLAN#{pid}" and i["SK"].startswith("CLAIM#")}
    records = {i["claimId"]: i for i in items if i["PK"] == f"PLAN#{pid}" and i["SK"].startswith("RECORD#")}
    inbox = [i for i in items if i["SK"].startswith("INBOX#")]
    return plan, claims, records, inbox


def check_invariants(table, pid, plan_updates):
    plan, claims, records, inbox = snapshot(table, pid)
    active = [c for c in claims.values() if c["status"] == "ACTIVE"]
    completed = [c for c in claims.values() if c["status"] == "COMPLETED"]
    assert len(active) <= 1
    assert len(inbox) <= 1
    assert int(plan["version"]) == 1 + plan_updates
    assert plan["GSI1PK"] == f"AREA#default#STATUS#{plan['status']}"
    if plan["status"] == "OPEN":
        assert active == [] and completed == [] and inbox == []
        assert not any(k in plan for k in ("currentClaimId", "claimerId", "dueAt"))
    elif plan["status"] == "CLAIMED":
        cur = claims[plan["currentClaimId"]]
        assert cur["status"] == "ACTIVE" and active == [cur] and plan["claimerId"] == cur["claimerId"]
        assert completed == [] and inbox == []
    else:
        assert plan["status"] == "COMPLETED"
        assert len(completed) == 1 and active == [] and len(inbox) == 1
        done = completed[0]
        assert plan["currentClaimId"] == done["claimId"] == inbox[0]["itemId"]
        assert "deliveredAt" in records[done["claimId"]]
    delivered = [r for r in records.values() if "deliveredAt" in r]
    assert len(delivered) == len(inbox)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(ops=st.lists(op, min_size=1, max_size=12))
def test_random_operation_sequences_keep_state_consistent(monkeypatch, ops):
    set_env(monkeypatch)
    with haru_table() as table:
        body = PlanCreate.model_validate(
            {
                "title": "속성 테스트", "summary": "s", "reason": "r", "estimatedMinutes": 30,
                "places": [{"name": "빵집", "activity": "빵 사기", "whyChosen": ""}], "question": "q",
                "authoring": {"mode": "MANUAL", "durationMs": 1, "story": "빵집에서 빵을 사요"},
            }
        )
        pid = ps.create_plan(OWNER, "k", body, START)[0]["planId"]
        now = START
        latest: dict[str, str] = {}  # 사용자별 마지막 claimId
        plan_updates = 0
        for name, arg in ops:
            if name == "advance":
                now += timedelta(days=arg)
                continue
            user = USERS[arg]
            before = snapshot(table, pid)
            try:
                if name == "claim":
                    claim, created = cs.claim_plan(pid, user, now)
                    latest[user.id] = claim["claimId"]
                    plan_updates += 1 if created else 0
                elif user.id not in latest:
                    continue
                elif name == "abandon":
                    cs.abandon(latest[user.id], user, now)
                    plan_updates += 1
                elif name == "record":
                    cs.put_record(latest[user.id], user, f"{user.nickname}의 글", now)
                else:
                    was_done = before[0]["status"] == "COMPLETED"
                    cs.complete_by_user(latest[user.id], user, "TEXT_ONLY", now)
                    plan_updates += 0 if was_done else 1
            except ApiError as e:
                assert e.code in {"ALREADY_CLAIMED", "CANNOT_CLAIM_OWN_PLAN", "CLAIM_NOT_ACTIVE", "RECORD_REQUIRED", "FORBIDDEN"}
                if e.code in ("CLAIM_NOT_ACTIVE", "ALREADY_CLAIMED", "RECORD_REQUIRED"):
                    # P15: 거부된 요청은 Plan·Record·InboxItem을 바꾸지 않는다
                    after = snapshot(table, pid)
                    assert after[0] == before[0] and after[2] == before[2] and after[3] == before[3]
            check_invariants(table, pid, plan_updates)
