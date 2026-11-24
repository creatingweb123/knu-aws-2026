"""plan_service 단위·속성 테스트.

- 5.3 멱등 분기, 지표 저장 (Requirements 3.5, 4.1–4.12, 5.1–5.6, 8.5)
- Property 2(서비스 수준): 같은 (본문, 키) n회 호출에도 Plan 1건, 같은 planId
- Property 6: list_plans 정렬·필터 (Requirements 6.1–6.7)
- Property 7: get_plan 상태 규칙 (Requirements 7.1, 7.3–7.11)
- Plan 갱신 헬퍼 (Requirements 8.6, 8.7)
"""

import copy
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from common import ddb
from common.auth import User
from common.errors import ApiError
from common.responses import iso_utc
from common.validation import PlanCreate
from domain import plan_service as svc
from tests.unit.fake_table import FakeTable

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
OWNER = User("u-owner", "지연")
OTHER = User("u-other", "수현")
DEMO_STORY = (
    "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, "
    "저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
)


def body(**over) -> PlanCreate:
    data = {
        "title": "이사 전, 마지막 동네 산책",
        "summary": "출근길 빵집에 들르고 하천 벤치에 앉아 쉬고 싶었어요.",
        "reason": "이삿짐 정리가 길어져 마지막 산책을 하지 못했어요.",
        "estimatedMinutes": 45,
        "places": [
            {"name": "골목 빵집", "activity": "빵", "whyChosen": ""},
            {"name": "하천 벤치", "activity": "쉬기", "whyChosen": "연락은 010-1234-5678"},
        ],
        "question": "벤치에 앉았을 때 어떤 소리가 들렸나요?",
        "authoring": {"mode": "AI_EDITED", "durationMs": 183000, "aiSessionId": "ais_x", "story": DEMO_STORY},
    }
    data.update(over)
    return PlanCreate.model_validate(data)


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(ddb, "table", lambda: t)
    monkeypatch.setattr(ddb, "transact_with_retry", t.transact)
    return t


# ---------------------------------------------------------------- create_plan


def test_create_stores_plan_and_key_in_one_transaction(table):
    plan, created = svc.create_plan(OWNER, "k1", body(), NOW)
    assert created and table.transact_calls == 1
    stored = table.items[(plan["PK"], "META")]
    assert stored["status"] == "OPEN" and stored["ownerId"] == "u-owner" and stored["ownerNickname"] == "지연"
    assert stored["areaId"] == "default" and stored["version"] == 1 and stored["planId"].startswith("pln_")
    assert stored["GSI1PK"] == "AREA#default#STATUS#OPEN" and stored["GSI2PK"] == "USER#u-owner"
    assert stored["GSI1SK"] == stored["createdAt"] and stored["GSI2SK"] == "PLAN#" + stored["createdAt"]
    assert [p["order"] for p in stored["places"]] == [1, 2]
    for absent in ("currentClaimId", "claimerId", "dueAt", "completedAt"):
        assert absent not in stored
    assert DEMO_STORY not in repr(stored)  # 사연 원문은 저장하지 않는다
    key = table.items[("IDEM#u-owner#k1", "META")]
    assert key["planId"] == plan["planId"] and len(key["bodyHash"]) == 64
    assert key["ttl"] == int((NOW + timedelta(hours=24)).timestamp())


def test_metrics_only_four_values(table):
    plan, _ = svc.create_plan(OWNER, "k1", body(), NOW)
    # 원문에 없음: "골목 빵집", "쉬기"(사연은 활용형 "쉬려고"라 BE-Q25 기본안에서는 hit)
    assert plan["metrics"] == {
        "authoringMode": "AI_EDITED",
        "durationMs": 183000,
        "addedNotInSource": 2,
        "privacyInPublished": 1,  # whyChosen의 전화번호
    }


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_idempotency_key(table, key):
    with pytest.raises(ApiError) as exc:
        svc.create_plan(OWNER, key, body(), NOW)
    assert exc.value.code == "VALIDATION_ERROR" and exc.value.details == {"Idempotency-Key": "필수 헤더예요."}
    assert table.items == {}


def test_same_key_same_body_replays(table):
    first, created1 = svc.create_plan(OWNER, "k1", body(), NOW)
    again, created2 = svc.create_plan(OWNER, "k1", body(), NOW + timedelta(minutes=5))
    assert created1 and not created2
    assert again == first  # metrics도 다시 계산하지 않는다
    assert table.count("PLAN#") == 1 and table.transact_calls == 1


def test_same_key_other_body_conflicts(table):
    first, _ = svc.create_plan(OWNER, "k1", body(), NOW)
    with pytest.raises(ApiError) as exc:
        svc.create_plan(OWNER, "k1", body(title="다른 제목"), NOW)
    assert exc.value.code == "IDEMPOTENCY_CONFLICT" and exc.value.status == 409
    assert table.count("PLAN#") == 1
    assert table.items[(first["PK"], "META")]["title"] == first["title"]


def test_new_key_creates_new_plan(table):
    svc.create_plan(OWNER, "k1", body(), NOW)
    svc.create_plan(OWNER, "k2", body(), NOW)
    assert table.count("PLAN#") == 2


def test_key_is_per_user(table):
    a, _ = svc.create_plan(OWNER, "same", body(), NOW)
    b, _ = svc.create_plan(OTHER, "same", body(), NOW)
    assert a["planId"] != b["planId"]


def test_concurrent_loser_replays_winner(table):
    # 키 조회 뒤, 트랜잭션 전에 다른 요청이 같은 키로 먼저 커밋한 상황
    winner_table = FakeTable()
    winner, _ = _create_in(winner_table, OWNER, "k1", body())

    def race():
        for item in winner_table.items.values():
            table.put(item)

    table.before_transact = race
    plan, created = svc.create_plan(OWNER, "k1", body(), NOW)
    assert not created and plan["planId"] == winner["planId"]
    assert table.count("PLAN#") == 1


def test_concurrent_loser_with_other_body_conflicts(table):
    winner_table = FakeTable()
    _create_in(winner_table, OWNER, "k1", body(title="먼저 온 요청"))
    table.before_transact = lambda: [table.put(i) for i in winner_table.items.values()]
    with pytest.raises(ApiError) as exc:
        svc.create_plan(OWNER, "k1", body(), NOW)
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"


def test_condition_failed_without_key_item_is_try_again(table, monkeypatch):
    def fail(items):
        raise ddb.ConditionFailed(["ConditionalCheckFailed", "None"])

    monkeypatch.setattr(ddb, "transact_with_retry", fail)
    with pytest.raises(ApiError) as exc:
        svc.create_plan(OWNER, "k1", body(), NOW)
    assert exc.value.code == "TRY_AGAIN" and exc.value.status == 503


def test_transaction_conflict_exhausted_stores_nothing(table, monkeypatch):
    def conflict(items):
        raise ApiError("TRY_AGAIN")  # transact_with_retry가 재시도를 다 쓴 경우(test_ddb.py에서 검증)

    monkeypatch.setattr(ddb, "transact_with_retry", conflict)
    with pytest.raises(ApiError) as exc:
        svc.create_plan(OWNER, "k1", body(), NOW)
    assert exc.value.code == "TRY_AGAIN"
    assert table.items == {}


def test_body_hash_ignores_key_order():
    a = body()
    b = PlanCreate.model_validate(dict(reversed(list(a.model_dump().items()))))
    assert svc.body_hash(a) == svc.body_hash(b)


def _create_in(t, user, key, b):
    orig_table, orig_tx = ddb.table, ddb.transact_with_retry
    ddb.table, ddb.transact_with_retry = (lambda: t), t.transact
    try:
        return svc.create_plan(user, key, b, NOW)
    finally:
        ddb.table, ddb.transact_with_retry = orig_table, orig_tx


titles = st.sampled_from(["산책", "마지막 동네 산책", "벤치"])
keys = st.text(alphabet="abc123-", min_size=1, max_size=8)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
@given(title=titles, key=keys, n=st.integers(1, 5))
def test_property2_repeated_calls_one_plan(table, title, key, n):
    table.items.clear()
    ids = {svc.create_plan(OWNER, key, body(title=title), NOW)[0]["planId"] for _ in range(n)}
    assert len(ids) == 1 and table.count("PLAN#") == 1


# ----------------------------------------------------------------- list_plans


def plan_item(i, status, created, due=None, owner="u-owner", claimer=None):
    item = {
        "PK": f"PLAN#p{i}", "SK": "META", "planId": f"p{i}", "areaId": "default",
        "ownerId": owner, "ownerNickname": "지연", "title": f"t{i}", "summary": "s", "reason": "r",
        "estimatedMinutes": 30, "places": [{"order": 1, "name": "n", "activity": "a", "whyChosen": ""}],
        "question": "q", "status": status, "createdAt": iso_utc(created), "version": 1,
        "metrics": {"authoringMode": "MANUAL", "durationMs": 1, "addedNotInSource": 0, "privacyInPublished": 0},
        "GSI1PK": f"AREA#default#STATUS#{status}", "GSI1SK": iso_utc(created),
    }
    if due is not None:
        item.update(dueAt=iso_utc(due), currentClaimId=f"c{i}", claimerId=claimer or "u-claimer")
    return item


plan_spec = st.tuples(
    st.sampled_from(["OPEN", "CLAIMED_EXPIRED", "CLAIMED_ACTIVE", "COMPLETED"]),
    st.integers(-10_000, 0),  # 생성 시각(분, NOW 기준)
    st.integers(1, 5_000),  # 기한까지의 차이(분)
)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=60)
@given(specs=st.lists(plan_spec, max_size=15), limit=st.none() | st.integers(-3, 60) | st.just("abc"), page=st.integers(1, 4))
def test_property6_list_order_and_filter(table, specs, limit, page):
    table.items.clear()
    table.page_size = page
    expected = []
    for i, (kind, created_min, due_min) in enumerate(specs):
        created = NOW + timedelta(minutes=created_min, milliseconds=i)  # 시각이 겹치지 않게
        if kind == "OPEN":
            table.put(plan_item(i, "OPEN", created)); expected.append((iso_utc(created), f"p{i}"))
        elif kind == "CLAIMED_EXPIRED":
            table.put(plan_item(i, "CLAIMED", created, NOW - timedelta(minutes=due_min))); expected.append((iso_utc(created), f"p{i}"))
        elif kind == "CLAIMED_ACTIVE":
            table.put(plan_item(i, "CLAIMED", created, NOW + timedelta(minutes=due_min)))
        else:
            table.put(plan_item(i, "COMPLETED", created))
    n = svc.normalize_limit(limit)
    items = svc.list_plans("OPEN", limit, NOW)
    want = [pid for _, pid in sorted(expected, reverse=True)[:n]]
    assert [x["planId"] for x in items] == want
    assert all(x["status"] == "OPEN" for x in items)
    assert all("metrics" not in x for x in items)


@pytest.mark.parametrize("raw,n", [(None, 20), ("10", 10), ("1", 1), ("0", 20), ("-1", 20), ("51", 50), ("abc", 20), ("", 20), (" 7 ", 7)])
def test_normalize_limit(raw, n):
    assert svc.normalize_limit(raw) == n


@pytest.mark.parametrize("status", [None, "CLAIMED", "open", ""])
def test_list_rejects_non_open_status(table, status):
    with pytest.raises(ApiError) as exc:
        svc.list_plans(status, None, NOW)
    assert exc.value.code == "VALIDATION_ERROR" and "status" in exc.value.details


def test_list_empty(table):
    assert svc.list_plans("OPEN", None, NOW) == []


# ------------------------------------------------------------------- get_plan


def claim_item(plan_i, claim_id, claimer, status):
    return {
        "PK": f"PLAN#p{plan_i}", "SK": f"CLAIM#{claim_id}", "claimId": claim_id, "planId": f"p{plan_i}",
        "claimerId": claimer, "claimerNickname": "수현", "status": status,
        "claimedAt": iso_utc(NOW - timedelta(days=4)), "dueAt": iso_utc(NOW - timedelta(days=1)),
    }


def test_get_plan_not_found(table):
    with pytest.raises(ApiError) as exc:
        svc.get_plan("nope", OTHER, NOW)
    assert exc.value.code == "NOT_FOUND"


def test_get_plan_owner_sees_metrics(table):
    table.put(plan_item(1, "OPEN", NOW))
    res = svc.get_plan("p1", OWNER, NOW)
    assert res["isOwner"] and not res["claimable"] and res["myClaim"] is None
    assert "metrics" in res["plan"]
    other = svc.get_plan("p1", OTHER, NOW)
    assert not other["isOwner"] and other["claimable"] and "metrics" not in other["plan"]


claim_states = st.lists(st.sampled_from(["ACTIVE", "COMPLETED", "ABANDONED", "EXPIRED"]), max_size=3)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=80)
@given(
    status=st.sampled_from(["OPEN", "CLAIMED", "COMPLETED"]),
    expired=st.booleans(),
    requester=st.sampled_from(["owner", "claimer", "stranger"]),
    my_claims=claim_states,
)
def test_property7_detail_rules(table, status, expired, requester, my_claims):
    table.items.clear()
    due = NOW - timedelta(hours=1) if expired else NOW + timedelta(hours=1)
    table.put(plan_item(1, status, NOW - timedelta(days=5), due if status != "OPEN" else None, claimer="u-claimer"))
    user = {"owner": OWNER, "claimer": User("u-claimer", "수현"), "stranger": OTHER}[requester]
    for j, s in enumerate(my_claims if requester != "owner" else []):
        table.put(claim_item(1, f"c{j}", user.id, s))
    has_my = any(s in ("ACTIVE", "COMPLETED") for s in (my_claims if requester != "owner" else []))
    is_owner = requester == "owner"

    if status == "COMPLETED" and not (is_owner or has_my):
        with pytest.raises(ApiError) as exc:
            svc.get_plan("p1", user, NOW)
        assert exc.value.code == "NOT_FOUND"
        return

    res = svc.get_plan("p1", user, NOW)
    shown = res["plan"]["status"]
    if status == "CLAIMED" and expired:
        assert shown == ("CLAIMED" if requester == "claimer" else "OPEN")
    else:
        assert shown == status
    assert res["isOwner"] is is_owner
    assert (res["myClaim"] is not None) is has_my
    if res["myClaim"] is not None:
        assert res["myClaim"]["status"] in ("ACTIVE", "COMPLETED")
        if "ACTIVE" in my_claims:
            assert res["myClaim"]["status"] == "ACTIVE"
    assert res["claimable"] is ((not is_owner) and res["myClaim"] is None and shown == "OPEN")
    for hidden in ("claimerId", "currentClaimId", "dueAt"):
        assert hidden not in res["plan"]


def test_get_plan_ignores_other_users_claims(table):
    table.put(plan_item(1, "OPEN", NOW))
    table.put(claim_item(1, "c1", "u-someone", "ACTIVE"))
    assert svc.get_plan("p1", OTHER, NOW)["myClaim"] is None


# ---------------------------------------------------------------- plan_update


def test_plan_update_bumps_version_and_gsi1pk(table):
    upd = svc.plan_update("p1", new_status="CLAIMED", set_values={"claimerId": "u2"}, remove=["x"], condition="#s0 = :open", condition_values={":open": "OPEN"})["Update"]
    assert upd["Key"] == {"PK": "PLAN#p1", "SK": "META"}
    assert upd["UpdateExpression"].startswith("SET #version = #version + :one")
    assert upd["ExpressionAttributeValues"][":one"] == 1
    names, values = upd["ExpressionAttributeNames"], upd["ExpressionAttributeValues"]
    set_pairs = {names[f"#s{i}"]: values[f":s{i}"] for i in range(3)}
    assert set_pairs == {"claimerId": "u2", "status": "CLAIMED", "GSI1PK": "AREA#default#STATUS#CLAIMED"}
    assert "REMOVE #r0" in upd["UpdateExpression"] and names["#r0"] == "x"
    assert upd["ConditionExpression"] == "#s0 = :open"


def test_plan_update_without_status_keeps_gsi1pk(table):
    upd = svc.plan_update("p1", set_values={"title": "t"})["Update"]
    assert "GSI1PK" not in upd["ExpressionAttributeNames"].values()
    assert upd["UpdateExpression"] == "SET #version = #version + :one, #s0 = :s0"
