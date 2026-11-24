"""plan_service를 moto(인프로세스 DynamoDB 흉내)에 실행해 실제 조건식·갱신식·GSI 조회를 확인한다.

Docker 로컬 환경 대신 쓴다. moto도 실제 병렬성과 TransactionConflict는 재현하지 않으므로
동시성 판정은 AWS 스택(T13)에서 한다.

Validates: Requirements 4.1, 4.3, 4.4, 4.5, 4.7, 4.11, 5.6, 6.3, 6.4, 7.4, 7.5, 7.7, 8.5, 8.6, 8.7
"""

from datetime import datetime, timedelta, timezone

import boto3
import pytest

moto = pytest.importorskip("moto")
from moto import mock_aws  # noqa: E402

from common import ddb  # noqa: E402
from common.auth import User  # noqa: E402
from common.errors import ApiError  # noqa: E402
from common.responses import iso_utc  # noqa: E402
from common.validation import PlanCreate  # noqa: E402
from domain import plan_service as svc  # noqa: E402

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
OWNER = User("u-owner", "지연")
OTHER = User("u-other", "수현")


def create_haru_table(client):
    def key(n, t):
        return {"AttributeName": n, "KeyType": t}

    client.create_table(
        TableName="HaruTable",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")],
        KeySchema=[key("PK", "HASH"), key("SK", "RANGE")],
        GlobalSecondaryIndexes=[
            {"IndexName": "GSI1", "KeySchema": [key("GSI1PK", "HASH"), key("GSI1SK", "RANGE")], "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "GSI2", "KeySchema": [key("GSI2PK", "HASH"), key("GSI2SK", "RANGE")], "Projection": {"ProjectionType": "ALL"}},
        ],
    )


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("TABLE_NAME", "HaruTable")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        create_haru_table(boto3.client("dynamodb"))
        monkeypatch.setattr(ddb, "_table", None)
        yield ddb.table()
    monkeypatch.setattr(ddb, "_table", None)


def body(**over):
    data = {
        "title": "이사 전, 마지막 동네 산책",
        "summary": "출근길 빵집에 들르고 싶었어요.",
        "reason": "이삿짐 정리가 길어졌어요.",
        "estimatedMinutes": 45,
        "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}],
        "question": "어떤 소리가 들렸나요?",
        "authoring": {"mode": "MANUAL", "durationMs": 1000, "story": "출근길 빵집에 들러 빵을 사고 싶었어요."},
    }
    data.update(over)
    return PlanCreate.model_validate(data)


def count_plans(table):
    return sum(1 for i in table.scan()["Items"] if i["PK"].startswith("PLAN#") and i["SK"] == "META")


# ---------------------------------------------------------------- create_plan


def test_create_writes_plan_and_key_with_real_transaction(table):
    plan, created = svc.create_plan(OWNER, "k1", body(), NOW)
    assert created
    stored = table.get_item(Key={"PK": plan["PK"], "SK": "META"})["Item"]
    assert stored["status"] == "OPEN" and stored["version"] == 1 and stored["GSI1PK"] == "AREA#default#STATUS#OPEN"
    for absent in ("currentClaimId", "claimerId", "dueAt", "completedAt"):
        assert absent not in stored
    key = table.get_item(Key={"PK": "IDEM#u-owner#k1", "SK": "META"})["Item"]
    assert key["planId"] == plan["planId"] and int(key["ttl"]) == int((NOW + timedelta(hours=24)).timestamp())


def test_replay_and_conflict(table):
    first, _ = svc.create_plan(OWNER, "k1", body(), NOW)
    again, created = svc.create_plan(OWNER, "k1", body(), NOW)
    assert not created and again["planId"] == first["planId"]
    with pytest.raises(ApiError) as exc:
        svc.create_plan(OWNER, "k1", body(title="다른 제목"), NOW)
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"
    assert count_plans(table) == 1


def test_race_loser_hits_real_conditional_check(table, monkeypatch):
    """키 조회와 트랜잭션 사이에 다른 요청이 커밋한 상황. 실제 취소 사유 코드로 ConditionFailed 분기를 탄다."""
    winner, _ = svc.create_plan(OWNER, "k1", body(), NOW)
    real_get = svc._get
    calls = {"n": 0}

    def stale_first_read(pk, sk="META"):
        calls["n"] += 1
        if calls["n"] == 1 and pk.startswith("IDEM#"):
            return None  # 첫 조회에서는 아직 키가 없었다
        return real_get(pk, sk)

    monkeypatch.setattr(svc, "_get", stale_first_read)
    plan, created = svc.create_plan(OWNER, "k1", body(), NOW)
    assert not created and plan["planId"] == winner["planId"]
    assert count_plans(table) == 1  # 진 쪽의 Plan은 트랜잭션과 함께 취소됐다


def test_race_loser_with_other_body_conflicts(table, monkeypatch):
    svc.create_plan(OWNER, "k1", body(title="먼저 온 요청"), NOW)
    real_get = svc._get
    first = {"done": False}

    def stale(pk, sk="META"):
        if not first["done"] and pk.startswith("IDEM#"):
            first["done"] = True
            return None
        return real_get(pk, sk)

    monkeypatch.setattr(svc, "_get", stale)
    with pytest.raises(ApiError) as exc:
        svc.create_plan(OWNER, "k1", body(), NOW)
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"
    assert count_plans(table) == 1


# ------------------------------------------------------------ list / detail


def put_plan(table, i, status, created, due=None, claimer=None):
    item = {
        "PK": f"PLAN#p{i}", "SK": "META", "planId": f"p{i}", "areaId": "default",
        "ownerId": "u-owner", "ownerNickname": "지연", "title": f"t{i}", "summary": "s", "reason": "r",
        "estimatedMinutes": 30, "places": [{"order": 1, "name": "n", "activity": "a", "whyChosen": ""}],
        "question": "q", "status": status, "createdAt": iso_utc(created), "version": 1,
        "GSI1PK": f"AREA#default#STATUS#{status}", "GSI1SK": iso_utc(created),
    }
    if due is not None:
        item.update(dueAt=iso_utc(due), currentClaimId=f"c{i}", claimerId=claimer or "u-claimer")
    table.put_item(Item=item)


def test_list_uses_gsi1_and_due_filter(table):
    put_plan(table, 1, "OPEN", NOW - timedelta(hours=3))
    put_plan(table, 2, "CLAIMED", NOW - timedelta(hours=2), due=NOW - timedelta(minutes=1))  # 기한 지남
    put_plan(table, 3, "CLAIMED", NOW - timedelta(hours=1), due=NOW + timedelta(days=1))  # 기한 내
    put_plan(table, 4, "COMPLETED", NOW)
    put_plan(table, 5, "OPEN", NOW - timedelta(minutes=10))
    items = svc.list_plans("OPEN", None, NOW)
    assert [i["planId"] for i in items] == ["p5", "p2", "p1"]
    assert all(i["status"] == "OPEN" for i in items)


def test_list_limit_after_filter(table):
    for i in range(6):
        put_plan(table, i, "CLAIMED", NOW - timedelta(minutes=i), due=NOW + timedelta(days=1))  # 걸러질 항목
    for i in range(6, 9):
        put_plan(table, i, "CLAIMED", NOW - timedelta(minutes=i), due=NOW - timedelta(hours=1))
    assert [i["planId"] for i in svc.list_plans("OPEN", "2", NOW)] == ["p6", "p7"]


def test_detail_with_real_claim_query(table):
    put_plan(table, 1, "CLAIMED", NOW - timedelta(days=4), due=NOW - timedelta(hours=1), claimer="u-other")
    table.put_item(Item={"PK": "PLAN#p1", "SK": "CLAIM#c-old", "claimId": "c-old", "planId": "p1", "claimerId": "u-other", "status": "ABANDONED"})
    table.put_item(Item={"PK": "PLAN#p1", "SK": "CLAIM#c1", "claimId": "c1", "planId": "p1", "claimerId": "u-other", "claimerNickname": "수현", "status": "ACTIVE"})
    mine = svc.get_plan("p1", OTHER, NOW)
    assert mine["plan"]["status"] == "CLAIMED" and mine["myClaim"]["claimId"] == "c1" and mine["claimable"] is False
    stranger = svc.get_plan("p1", User("u-x", "민준"), NOW)
    assert stranger["plan"]["status"] == "OPEN" and stranger["myClaim"] is None and stranger["claimable"] is True


def test_completed_plan_hidden_from_strangers(table):
    put_plan(table, 1, "COMPLETED", NOW)
    assert svc.get_plan("p1", OWNER, NOW)["isOwner"] is True
    with pytest.raises(ApiError) as exc:
        svc.get_plan("p1", OTHER, NOW)
    assert exc.value.code == "NOT_FOUND"


# ---------------------------------------------------------------- plan_update


def test_plan_update_applies_in_real_transaction(table):
    put_plan(table, 1, "OPEN", NOW)
    upd = svc.plan_update(
        "p1",
        new_status="CLAIMED",
        set_values={"claimerId": "u-other", "currentClaimId": "c1", "dueAt": iso_utc(NOW + timedelta(days=3))},
        condition="#s3 = :open",  # #s3 = status (set 순서: claimerId, currentClaimId, dueAt, status, GSI1PK)
        condition_values={":open": "OPEN"},
    )
    ddb.transact_with_retry([upd])
    item = table.get_item(Key={"PK": "PLAN#p1", "SK": "META"})["Item"]
    assert item["version"] == 2 and item["status"] == "CLAIMED" and item["GSI1PK"] == "AREA#default#STATUS#CLAIMED"

    back = svc.plan_update("p1", new_status="OPEN", remove=["claimerId", "currentClaimId", "dueAt"])
    ddb.transact_with_retry([back])
    item = table.get_item(Key={"PK": "PLAN#p1", "SK": "META"})["Item"]
    assert item["version"] == 3 and item["status"] == "OPEN" and item["GSI1PK"] == "AREA#default#STATUS#OPEN"
    for absent in ("claimerId", "currentClaimId", "dueAt"):
        assert absent not in item


def test_plan_update_condition_failure_is_condition_failed(table):
    put_plan(table, 1, "COMPLETED", NOW)
    upd = svc.plan_update("p1", new_status="CLAIMED", condition="#s0 = :open", condition_values={":open": "OPEN"})
    with pytest.raises(ddb.ConditionFailed) as exc:
        ddb.transact_with_retry([upd])
    assert exc.value.reasons == ["ConditionalCheckFailed"]
    assert table.get_item(Key={"PK": "PLAN#p1", "SK": "META"})["Item"]["version"] == 1
