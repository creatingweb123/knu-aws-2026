"""claim_service를 moto에 실행해 이어받기·포기·기록·완료의 모든 분기를 실제 조건식으로 확인한다.

moto는 실제 병렬성·TransactionConflict를 재현하지 않는다. 경합은 "읽은 뒤 다른 요청이 먼저 커밋"하는
순차 경합으로 만든다. 실제 동시성 판정은 AWS 스택(T3–T5)에서 한다.

Validates: spec backend-stage3-claim Requirements 1–6 (T3·T4·T5·T6·T7·T14·T16의 순차판)
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("moto")

from common import ddb  # noqa: E402
from common.auth import User  # noqa: E402
from common.errors import ApiError  # noqa: E402
from common.responses import iso_utc  # noqa: E402
from common.validation import PlanCreate  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from domain import plan_service as ps  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
OWNER = User("u-owner", "지연")
SUHYUN = User("u-suhyun", "수현")
MINJUN = User("u-minjun", "민준")


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


def new_plan(title="이사 전, 마지막 동네 산책"):
    body = PlanCreate.model_validate(
        {
            "title": title,
            "summary": "출근길 빵집에 들르고 싶었어요.",
            "reason": "이삿짐 정리가 길어졌어요.",
            "estimatedMinutes": 45,
            "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}],
            "question": "어떤 소리가 들렸나요?",
            "authoring": {"mode": "MANUAL", "durationMs": 1000, "story": "출근길 빵집에 들러 빵을 사고 싶었어요."},
        }
    )
    plan, _ = ps.create_plan(OWNER, f"k-{title}", body, NOW - timedelta(days=10))
    return plan["planId"]


def get(table, pk, sk="META"):
    return table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")


def plan_of(table, pid):
    return get(table, f"PLAN#{pid}")


def claim_of(table, pid, cid):
    return get(table, f"PLAN#{pid}", f"CLAIM#{cid}")


def inbox_items(table):
    return [i for i in table.scan()["Items"] if i["SK"].startswith("INBOX#")]


def claims_of_plan(table, pid):
    return [i for i in table.scan()["Items"] if i["PK"] == f"PLAN#{pid}" and i["SK"].startswith("CLAIM#")]


def metric_names(capsys):
    names = []
    for line in capsys.readouterr().out.splitlines():
        if line.startswith('{"_aws"'):
            doc = json.loads(line)
            names.append(doc["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"])
    return names


def codes(fn):
    with pytest.raises(ApiError) as exc:
        fn()
    return exc.value.code


# ---------------------------------------------------------------- 이어받기


def test_claim_new(table):
    pid = new_plan()
    claim, created = cs.claim_plan(pid, SUHYUN, NOW)
    assert created and claim["claimId"].startswith("clm_") and len(claim["claimId"]) == 30
    plan = plan_of(table, pid)
    assert plan["status"] == "CLAIMED" and plan["currentClaimId"] == claim["claimId"] and plan["claimerId"] == "u-suhyun"
    assert plan["GSI1PK"] == "AREA#default#STATUS#CLAIMED" and plan["version"] == 2
    assert plan["dueAt"] == iso_utc(NOW + timedelta(days=3)) == claim["dueAt"]
    stored = claim_of(table, pid, claim["claimId"])
    assert stored["status"] == "ACTIVE" and stored["claimerNickname"] == "수현"
    assert stored["GSI2PK"] == "USER#u-suhyun" and stored["GSI2SK"] == "CLAIM#" + iso_utc(NOW)
    assert "late" not in stored and "completedAt" not in stored
    lookup = get(table, f"CLAIM#{claim['claimId']}")
    assert lookup == {"PK": f"CLAIM#{claim['claimId']}", "SK": "META", "claimId": claim["claimId"], "planId": pid, "claimerId": "u-suhyun"}


def test_same_user_again_returns_existing(table):
    pid = new_plan()
    first, _ = cs.claim_plan(pid, SUHYUN, NOW)
    again, created = cs.claim_plan(pid, SUHYUN, NOW + timedelta(minutes=1))
    assert not created and again["claimId"] == first["claimId"]
    assert len(claims_of_plan(table, pid)) == 1 and plan_of(table, pid)["version"] == 2


def test_same_user_after_due_still_returns_existing(table):
    pid = new_plan()
    first, _ = cs.claim_plan(pid, SUHYUN, NOW)
    again, created = cs.claim_plan(pid, SUHYUN, NOW + timedelta(days=5))
    assert not created and again["claimId"] == first["claimId"]


def test_owner_cannot_claim(table):
    pid = new_plan()
    assert codes(lambda: cs.claim_plan(pid, OWNER, NOW)) == "CANNOT_CLAIM_OWN_PLAN"
    assert plan_of(table, pid)["status"] == "OPEN"


def test_other_user_while_active_conflicts_and_emits(table, capsys):
    pid = new_plan()
    cs.claim_plan(pid, SUHYUN, NOW)
    capsys.readouterr()
    assert codes(lambda: cs.claim_plan(pid, MINJUN, NOW + timedelta(hours=1))) == "ALREADY_CLAIMED"
    assert metric_names(capsys) == ["ClaimConflict"]
    assert len(claims_of_plan(table, pid)) == 1


def test_missing_plan_404(table):
    assert codes(lambda: cs.claim_plan("pln_none", SUHYUN, NOW)) == "NOT_FOUND"


def test_expired_takeover_marks_previous_expired(table):
    """T14 순차판."""
    pid = new_plan()
    old, _ = cs.claim_plan(pid, SUHYUN, NOW - timedelta(days=4))  # 기한 NOW-1일
    new, created = cs.claim_plan(pid, MINJUN, NOW)
    assert created
    assert claim_of(table, pid, old["claimId"])["status"] == "EXPIRED"
    plan = plan_of(table, pid)
    assert plan["currentClaimId"] == new["claimId"] and plan["claimerId"] == "u-minjun" and plan["version"] == 3


def test_race_loser_sees_already_claimed(table, monkeypatch):
    """T3 순차판: 패자가 읽은 뒤 승자가 먼저 커밋한다."""
    pid = new_plan()
    real = ddb.transact_with_retry
    state = {"raced": False}

    def racing(items):
        if not state["raced"]:
            state["raced"] = True
            cs.claim_plan(pid, SUHYUN, NOW)  # 승자
        return real(items)

    monkeypatch.setattr(ddb, "transact_with_retry", racing)
    assert codes(lambda: cs.claim_plan(pid, MINJUN, NOW)) == "ALREADY_CLAIMED"
    monkeypatch.setattr(ddb, "transact_with_retry", real)
    claims = claims_of_plan(table, pid)
    assert len(claims) == 1 and plan_of(table, pid)["currentClaimId"] == claims[0]["claimId"]


def test_race_same_user_gets_existing(table, monkeypatch):
    """T4 순차판."""
    pid = new_plan()
    real = ddb.transact_with_retry
    state = {"raced": False}

    def racing(items):
        if not state["raced"]:
            state["raced"] = True
            cs.claim_plan(pid, SUHYUN, NOW)
        return real(items)

    monkeypatch.setattr(ddb, "transact_with_retry", racing)
    claim, created = cs.claim_plan(pid, SUHYUN, NOW)
    assert not created
    monkeypatch.setattr(ddb, "transact_with_retry", real)
    assert len(claims_of_plan(table, pid)) == 1 and claims_of_plan(table, pid)[0]["claimId"] == claim["claimId"]


def test_replacement_target_abandoned_meanwhile_retries(table, monkeypatch):
    """대체하려던 Claim이 그사이 포기되면 다시 읽어 OPEN을 이어받는다(리뷰 지적 1)."""
    pid = new_plan()
    old, _ = cs.claim_plan(pid, SUHYUN, NOW - timedelta(days=4))
    real = ddb.transact_with_retry
    state = {"raced": False}

    def racing(items):
        if not state["raced"]:
            state["raced"] = True
            cs.abandon(old["claimId"], SUHYUN, NOW)
        return real(items)

    monkeypatch.setattr(ddb, "transact_with_retry", racing)
    new, created = cs.claim_plan(pid, MINJUN, NOW)
    assert created and plan_of(table, pid)["currentClaimId"] == new["claimId"]
    assert claim_of(table, pid, old["claimId"])["status"] == "ABANDONED"


def test_try_again_is_rejudged_before_503(table, monkeypatch):
    """TransactionConflict 소진(503) 뒤에도 다시 읽어 판정한다(리뷰 지적 2)."""
    pid = new_plan()
    real = ddb.transact_with_retry
    state = {"n": 0}

    # 승자가 커밋한 뒤 패자는 TransactionConflict 재시도를 다 써서 503을 받는다 → 다시 읽으면 남의 CLAIMED → 409
    def winner_then_conflict(items):
        if state["n"] == 0:
            state["n"] = 1
            cs.claim_plan(pid, SUHYUN, NOW)
            raise ApiError("TRY_AGAIN")
        return real(items)

    monkeypatch.setattr(ddb, "transact_with_retry", winner_then_conflict)
    assert codes(lambda: cs.claim_plan(pid, MINJUN, NOW)) == "ALREADY_CLAIMED"


def test_completed_plan_is_already_claimed(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "다녀왔어요", NOW)
    cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW)
    assert codes(lambda: cs.claim_plan(pid, MINJUN, NOW)) == "ALREADY_CLAIMED"


# ---------------------------------------------------------------- 포기


def test_abandon_reopens_plan(table):
    """T16 순차판."""
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "쓰던 글", NOW)
    out = cs.abandon(c["claimId"], SUHYUN, NOW)
    assert out["status"] == "ABANDONED"
    plan = plan_of(table, pid)
    assert plan["status"] == "OPEN" and plan["GSI1PK"] == "AREA#default#STATUS#OPEN" and plan["version"] == 3
    for absent in ("currentClaimId", "claimerId", "dueAt"):
        assert absent not in plan
    assert claim_of(table, pid, c["claimId"])["status"] == "ABANDONED"
    assert get(table, f"PLAN#{pid}", f"RECORD#{c['claimId']}")["photoStatus"] == "DISCARDED"
    assert [p["planId"] for p in ps.list_plans("OPEN", None, NOW)] == [pid]


def test_abandon_without_record(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.abandon(c["claimId"], SUHYUN, NOW)
    assert get(table, f"PLAN#{pid}", f"RECORD#{c['claimId']}") is None


def test_abandon_errors(table, capsys):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    assert codes(lambda: cs.abandon("clm_none", SUHYUN, NOW)) == "NOT_FOUND"
    assert codes(lambda: cs.abandon(c["claimId"], MINJUN, NOW)) == "FORBIDDEN"
    cs.abandon(c["claimId"], SUHYUN, NOW)
    capsys.readouterr()
    assert codes(lambda: cs.abandon(c["claimId"], SUHYUN, NOW)) == "CLAIM_NOT_ACTIVE"
    assert metric_names(capsys) == ["StaleRequestRejected"]


# ---------------------------------------------------------------- 기록


def test_put_record_create_and_overwrite(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    r1 = cs.put_record(c["claimId"], SUHYUN, "첫 글", NOW)
    assert r1["letter"] == "첫 글" and r1["photoStatus"] == "NONE" and r1["authorId"] == "u-suhyun"
    r2 = cs.put_record(c["claimId"], SUHYUN, "고친 글", NOW + timedelta(minutes=5))
    assert r2["letter"] == "고친 글" and r2["updatedAt"] == iso_utc(NOW + timedelta(minutes=5))


def test_put_record_errors(table):
    """T6·T7 순차판(기록 저장)."""
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    assert codes(lambda: cs.put_record(c["claimId"], MINJUN, "남의 글", NOW)) == "FORBIDDEN"
    assert codes(lambda: cs.put_record("clm_none", SUHYUN, "x", NOW)) == "NOT_FOUND"
    cs.abandon(c["claimId"], SUHYUN, NOW)
    assert codes(lambda: cs.put_record(c["claimId"], SUHYUN, "포기 뒤", NOW)) == "CLAIM_NOT_ACTIVE"


def test_put_record_after_takeover_rejected(table):
    pid = new_plan()
    old, _ = cs.claim_plan(pid, SUHYUN, NOW - timedelta(days=4))
    cs.claim_plan(pid, MINJUN, NOW)
    assert codes(lambda: cs.put_record(old["claimId"], SUHYUN, "늦은 글", NOW)) == "CLAIM_NOT_ACTIVE"


def test_put_record_after_completion_rejected(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW)
    assert codes(lambda: cs.put_record(c["claimId"], SUHYUN, "완료 뒤", NOW)) == "CLAIM_NOT_ACTIVE"
    assert get(table, f"PLAN#{pid}", f"RECORD#{c['claimId']}")["letter"] == "글"


# ---------------------------------------------------------------- 완료


def test_complete_requires_record(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    assert codes(lambda: cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW)) == "RECORD_REQUIRED"


def test_complete_success(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "다녀왔어요", NOW)
    res = cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW + timedelta(hours=1))
    assert res["delivered"] is True and res["hasPhoto"] is False and res["claim"]["status"] == "COMPLETED"
    plan = plan_of(table, pid)
    assert plan["status"] == "COMPLETED" and plan["GSI1PK"] == "AREA#default#STATUS#COMPLETED" and plan["version"] == 3
    assert plan["completedAt"] == iso_utc(NOW + timedelta(hours=1))
    claim = claim_of(table, pid, c["claimId"])
    assert claim["status"] == "COMPLETED" and claim["late"] is False
    record = get(table, f"PLAN#{pid}", f"RECORD#{c['claimId']}")
    assert record["deliveredAt"] == iso_utc(NOW + timedelta(hours=1)) and record["photoStatus"] == "NONE"
    (inbox,) = inbox_items(table)
    assert inbox["PK"] == "USER#u-owner" and inbox["SK"] == f"INBOX#{c['claimId']}"
    assert inbox["itemId"] == c["claimId"] and inbox["planTitle"] == "이사 전, 마지막 동네 산책"
    assert inbox["claimerNickname"] == "수현" and inbox["hasPhoto"] is False and inbox["read"] is False
    assert "reply" not in inbox


def test_complete_late(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "늦었어요", NOW)
    res = cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW + timedelta(days=4))
    assert res["claim"]["late"] is True and claim_of(table, pid, c["claimId"])["late"] is True


def test_complete_repeated_is_idempotent(table, capsys):
    """T5 순차판: n회 호출해도 InboxItem 1건, 모두 delivered, CompleteDuplicate n-1회."""
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    capsys.readouterr()
    results = [cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW) for _ in range(5)]
    assert all(r["delivered"] for r in results) and len(inbox_items(table)) == 1
    assert metric_names(capsys) == ["CompleteDuplicate"] * 4


def test_complete_race_loser_gets_duplicate(table, monkeypatch, capsys):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    real = ddb.transact_with_retry
    state = {"raced": False}

    def racing(items):
        if not state["raced"]:
            state["raced"] = True
            cs.complete_claim(c["claimId"], "TEXT_ONLY", now=NOW)
        return real(items)

    monkeypatch.setattr(ddb, "transact_with_retry", racing)
    capsys.readouterr()
    res = cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW)
    assert res["delivered"] and len(inbox_items(table)) == 1
    assert metric_names(capsys) == ["CompleteDuplicate"]


def test_complete_errors(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    assert codes(lambda: cs.complete_by_user(c["claimId"], MINJUN, "TEXT_ONLY", NOW)) == "FORBIDDEN"
    assert codes(lambda: cs.complete_by_user("clm_none", SUHYUN, "TEXT_ONLY", NOW)) == "NOT_FOUND"
    assert codes(lambda: cs.complete_claim(c["claimId"], "WRONG", now=NOW)) == "VALIDATION_ERROR"


def test_complete_after_abandon_rejected(table):
    """T6 순차판."""
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    cs.abandon(c["claimId"], SUHYUN, NOW)
    assert codes(lambda: cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW)) == "CLAIM_NOT_ACTIVE"
    assert inbox_items(table) == []


def test_late_completion_after_reclaim_rejected(table):
    """T7 순차판: 포기 → 다른 사용자 이어받기 → 첫 실행자의 늦은 완료는 409, 두 번째 완료는 정상."""
    pid = new_plan()
    first, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(first["claimId"], SUHYUN, "첫 글", NOW)
    cs.abandon(first["claimId"], SUHYUN, NOW)
    second, _ = cs.claim_plan(pid, MINJUN, NOW + timedelta(minutes=1))
    assert codes(lambda: cs.complete_by_user(first["claimId"], SUHYUN, "TEXT_ONLY", NOW)) == "CLAIM_NOT_ACTIVE"
    cs.put_record(second["claimId"], MINJUN, "두 번째 글", NOW)
    res = cs.complete_by_user(second["claimId"], MINJUN, "TEXT_ONLY", NOW)
    assert res["delivered"]
    (inbox,) = inbox_items(table)
    assert inbox["itemId"] == second["claimId"] and inbox["claimerNickname"] == "민준"


def test_expired_claim_completion_after_takeover_rejected(table):
    pid = new_plan()
    old, _ = cs.claim_plan(pid, SUHYUN, NOW - timedelta(days=4))
    cs.put_record(old["claimId"], SUHYUN, "글", NOW - timedelta(days=2))
    cs.claim_plan(pid, MINJUN, NOW)
    assert codes(lambda: cs.complete_by_user(old["claimId"], SUHYUN, "TEXT_ONLY", NOW)) == "CLAIM_NOT_ACTIVE"


def _set_photo(table, pid, cid, status, key=None):
    expr, values = "SET photoStatus = :s", {":s": status}
    if key:
        expr += ", photoKey = :k"
        values[":k"] = key
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression=expr, ExpressionAttributeValues=values)


@pytest.mark.parametrize("status", ["UPLOAD_PENDING", "PROCESSING", "FAILED", "READY"])
def test_text_only_discards_pending_photo(table, status):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    _set_photo(table, pid, c["claimId"], status, key="photos/original/x.jpg")
    res = cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW)
    assert res["hasPhoto"] is False
    assert get(table, f"PLAN#{pid}", f"RECORD#{c['claimId']}")["photoStatus"] == "DISCARDED"


def test_with_photo_completion_then_text_only_duplicate(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    _set_photo(table, pid, c["claimId"], "PROCESSING", key="photos/original/a.jpg")
    res = cs.complete_claim(c["claimId"], "WITH_PHOTO", key="photos/original/a.jpg", processed_key="photos/processed/a.jpg", now=NOW)
    assert res["hasPhoto"] is True
    record = get(table, f"PLAN#{pid}", f"RECORD#{c['claimId']}")
    assert record["photoStatus"] == "READY" and record["processedKey"] == "photos/processed/a.jpg"
    assert inbox_items(table)[0]["hasPhoto"] is True
    dup = cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW)
    assert dup["hasPhoto"] is True and len(inbox_items(table)) == 1


def test_with_photo_wrong_key_rejected(table):
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    _set_photo(table, pid, c["claimId"], "PROCESSING", key="photos/original/new.jpg")
    assert codes(lambda: cs.complete_claim(c["claimId"], "WITH_PHOTO", key="photos/original/old.jpg", now=NOW)) == "CLAIM_NOT_ACTIVE"
    assert inbox_items(table) == []


def test_photo_status_changed_meanwhile_is_rejudged(table, monkeypatch):
    """읽은 photoStatus와 달라지면(방어 조건 BE-Q40) 다시 읽어 새 값으로 완료한다."""
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "글", NOW)
    real = ddb.transact_with_retry
    state = {"raced": False}

    def racing(items):
        if not state["raced"]:
            state["raced"] = True
            _set_photo(table, pid, c["claimId"], "UPLOAD_PENDING", key="photos/original/z.jpg")
        return real(items)

    monkeypatch.setattr(ddb, "transact_with_retry", racing)
    cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW)
    assert get(table, f"PLAN#{pid}", f"RECORD#{c['claimId']}")["photoStatus"] == "DISCARDED"


# ---------------------------------------------------------------- 내 이어받기


def test_list_my_claims(table):
    p1, p2 = new_plan("하나"), new_plan("둘")
    c1, _ = cs.claim_plan(p1, SUHYUN, NOW)
    c2, _ = cs.claim_plan(p2, SUHYUN, NOW + timedelta(minutes=1))
    cs.put_record(c2["claimId"], SUHYUN, "글", NOW)
    cs.complete_by_user(c2["claimId"], SUHYUN, "TEXT_ONLY", NOW)
    active = cs.list_my_claims(SUHYUN, "ACTIVE", NOW)
    assert [i["claim"]["claimId"] for i in active] == [c1["claimId"]]
    assert active[0]["record"] is None and active[0]["plan"]["status"] == "CLAIMED" and "metrics" not in active[0]["plan"]
    assert active[0]["claim"]["claimer"] == {"userId": "u-suhyun", "nickname": "수현"}
    done = cs.list_my_claims(SUHYUN, "COMPLETED", NOW)
    assert [i["claim"]["claimId"] for i in done] == [c2["claimId"]]
    assert done[0]["record"]["letter"] == "글" and done[0]["record"]["deliveredAt"] is not None
    assert set(done[0]["record"]) == {"claimId", "planId", "letter", "photoStatus", "updatedAt", "deliveredAt"}
    assert cs.list_my_claims(MINJUN, "ACTIVE", NOW) == []


@pytest.mark.parametrize("status", [None, "", "ABANDONED", "active"])
def test_list_my_claims_bad_status(table, status):
    with pytest.raises(ApiError) as exc:
        cs.list_my_claims(SUHYUN, status, NOW)
    assert exc.value.code == "VALIDATION_ERROR" and "status" in exc.value.details


def test_get_plan_sees_my_claim(table):
    """1·2단계 get_plan이 3단계 Claim을 읽는지(myClaim, 실행자 정보 숨김)."""
    pid = new_plan()
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    mine = ps.get_plan(pid, SUHYUN, NOW)
    assert mine["myClaim"]["claimId"] == c["claimId"] and mine["claimable"] is False
    other = ps.get_plan(pid, MINJUN, NOW)
    assert other["plan"]["status"] == "CLAIMED" and other["myClaim"] is None and other["claimable"] is False
