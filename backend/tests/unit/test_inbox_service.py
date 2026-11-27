"""수신함 서비스 단위 테스트 (moto: 조건식을 실제로 평가한다. 페이지 이어 읽기는 FakeTable).

Validates: spec backend-stage4-record-inbox Requirements 3.1–3.5, 4.1–4.5, 4.7, 4.8, 5.1–5.4, 6.1–6.3, 6.5, 6.6,
8.2–8.4, 8.7, 10.7, 11.1 (BE-Q44, BE-Q47)
"""

import re
from datetime import datetime, timezone

import pytest

pytest.importorskip("moto")

from common import ddb  # noqa: E402
from common.auth import User  # noqa: E402
from common.errors import ApiError  # noqa: E402
from common.validation import PlanCreate  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from domain import inbox_service as inbox  # noqa: E402
from domain import plan_service as ps  # noqa: E402
from tests.unit.fake_table import FakeTable  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

OWNER = User("u-owner", "지연")
SUHYUN = User("u-suhyun", "수현")
MINJUN = User("u-minjun", "민준")
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
ISO_MS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
PLAN = {
    "title": "이사 전, 마지막 동네 산책", "summary": "출근길 빵집", "reason": "이삿짐", "estimatedMinutes": 45,
    "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}], "question": "q",
    "authoring": {"mode": "MANUAL", "durationMs": 1, "story": "출근길 빵집에 들러 빵을 사요"},
}


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


def completed_item(owner=OWNER, claimer=SUHYUN, key="k1", letter="소금빵을 샀어요"):
    """3단계 완료 트랜잭션으로 InboxItem을 만든다. (planId, claimId)."""
    plan = ps.create_plan(owner, key, PlanCreate.model_validate(PLAN), NOW)[0]
    claim, _ = cs.claim_plan(plan["planId"], claimer, NOW)
    cs.put_record(claim["claimId"], claimer, letter, NOW)
    cs.complete_by_user(claim["claimId"], claimer, "TEXT_ONLY", NOW)
    return plan["planId"], claim["claimId"]


def put_inbox(t, owner_pk, item_id, owner_id=None, **extra):
    item = {
        "PK": f"USER#{owner_pk}", "SK": f"INBOX#{item_id}", "ownerId": owner_id or owner_pk, "itemId": item_id,
        "planId": f"pln_{item_id}", "planTitle": "t", "hasPhoto": False, "read": False, "createdAt": "2026-11-20T09:00:00.000Z",
        **extra,
    }
    t.put_item(Item=item)
    return item


def get_inbox(t, owner_id, item_id):
    return t.get_item(Key={"PK": f"USER#{owner_id}", "SK": f"INBOX#{item_id}"}, ConsistentRead=True).get("Item")


def scan(t):
    return sorted(t.scan(ConsistentRead=True)["Items"], key=lambda i: (i["PK"], i["SK"]))


def spy(monkeypatch, t, name):
    calls = []
    original = getattr(t, name)

    def wrapper(**kw):
        calls.append(kw)
        return original(**kw)

    monkeypatch.setattr(t, name, wrapper)
    return calls


def code_of(exc_info):
    return exc_info.value.code


# ------------------------------------------------------------------ 목록 (Requirement 3)


def test_list_from_completed_transaction(table):
    pid, cid = completed_item()
    items = inbox.list_items(OWNER)
    assert [i["itemId"] for i in items] == [cid]
    assert items[0]["planId"] == pid and items[0]["read"] is False and items[0]["claimerNickname"] == "수현"
    assert inbox.list_items(SUHYUN) == []  # 실행자의 수신함에는 없다


def test_list_sorted_desc_and_isolated(table):
    put_inbox(table, "u-owner", "a", createdAt="2026-11-20T09:00:00.000Z")
    put_inbox(table, "u-owner", "b", createdAt="2026-11-21T09:00:00.000Z")
    put_inbox(table, "u-owner", "c", createdAt="2026-11-19T09:00:00.000Z")
    put_inbox(table, "u-other", "d")
    put_inbox(table, "u-owner", "e", owner_id="u-other")  # 키와 ownerId가 어긋난 항목
    assert [i["itemId"] for i in inbox.list_items(OWNER)] == ["b", "a", "c"]


def test_list_empty(table):
    assert inbox.list_items(OWNER) == []


def test_list_and_count_read_all_pages(monkeypatch):
    t = FakeTable(page_size=2)
    monkeypatch.setattr(ddb, "table", lambda: t)
    for n in range(5):
        t.put({"PK": "USER#u-owner", "SK": f"INBOX#{n}", "ownerId": "u-owner", "itemId": str(n), "read": n % 2 == 0, "createdAt": f"2026-11-2{n}T00:00:00.000Z"})
    t.put({"PK": "USER#u-owner", "SK": "INBOX#x", "ownerId": "u-x", "itemId": "x", "read": False, "createdAt": "2026-11-29T00:00:00.000Z"})
    assert [i["itemId"] for i in inbox.list_items(OWNER)] == ["4", "3", "2", "1", "0"]
    assert inbox.unread_count(OWNER) == 2


def test_list_query_is_consistent_base_table(monkeypatch, table):
    calls = spy(monkeypatch, table, "query")
    inbox.list_items(OWNER)
    assert len(calls) == 1 and calls[0]["ConsistentRead"] is True
    assert "IndexName" not in calls[0] and "FilterExpression" not in calls[0] and "Select" not in calls[0]


# ------------------------------------------------------------------ 미확인 수 (Requirement 8)


def test_unread_count_rules(monkeypatch, table):
    put_inbox(table, "u-owner", "a")
    put_inbox(table, "u-owner", "b", read=True)
    put_inbox(table, "u-owner", "c", owner_id="u-other")  # 어긋난 ownerId는 세지 않는다
    put_inbox(table, "u-other", "d")
    put_inbox(table, "u-owner", "e", read="false")  # 불리언이 아니면 세지 않는다
    item = put_inbox(table, "u-owner", "f")
    del item["read"]
    table.put_item(Item=item)  # read 속성 없음
    calls = spy(monkeypatch, table, "query")
    assert inbox.unread_count(OWNER) == 1
    assert calls[0]["ConsistentRead"] is True


def test_unread_count_drops_after_read(table):
    _, cid = completed_item()
    assert inbox.unread_count(OWNER) == 1
    inbox.mark_read(cid, OWNER)
    assert inbox.unread_count(OWNER) == 0


# ------------------------------------------------------------------ 상세 (Requirement 4)


def test_detail_reads_item_plan_record(monkeypatch, table):
    pid, cid = completed_item()
    calls = spy(monkeypatch, table, "get_item")
    detail = inbox.get_detail(cid, OWNER)
    assert detail["item"]["itemId"] == cid and detail["plan"]["planId"] == pid
    assert detail["record"]["letter"] == "소금빵을 샀어요" and detail["record"]["deliveredAt"]
    assert calls[0]["Key"] == {"PK": "USER#u-owner", "SK": f"INBOX#{cid}"}
    assert all(c["ConsistentRead"] is True for c in calls)
    assert get_inbox(table, "u-owner", cid)["read"] is False  # 상세 조회는 read를 바꾸지 않는다


@pytest.mark.parametrize("who,item_id", [(SUHYUN, None), (MINJUN, None), (OWNER, "clm_none")])
def test_detail_404(table, who, item_id):
    _, cid = completed_item()
    with pytest.raises(ApiError) as e:
        inbox.get_detail(item_id or cid, who)
    assert code_of(e) == "NOT_FOUND"


def test_detail_404_when_owner_mismatch(table):
    put_inbox(table, "u-owner", "x", owner_id="u-other")
    with pytest.raises(ApiError) as e:
        inbox.get_detail("x", OWNER)
    assert code_of(e) == "NOT_FOUND"


@pytest.mark.parametrize("missing", ["plan", "record", "delivered"])
def test_detail_integrity_error(table, missing):
    pid, cid = completed_item()
    if missing == "plan":
        table.delete_item(Key={"PK": f"PLAN#{pid}", "SK": "META"})
    elif missing == "record":
        table.delete_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"})
    else:
        table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="REMOVE deliveredAt")
    with pytest.raises(inbox.InboxIntegrityError):
        inbox.get_detail(cid, OWNER)


# ------------------------------------------------------------------ 읽음 (Requirement 5)


def test_mark_read_and_repeat(monkeypatch, table):
    put_inbox(table, "u-owner", "a", reply={"text": "고마워요", "sentAt": "2026-11-20T10:00:00.000Z"})
    calls = spy(monkeypatch, table, "update_item")
    inbox.mark_read("a", OWNER)
    inbox.mark_read("a", OWNER)  # BE-Q44: 이미 읽었어도 성공
    after = get_inbox(table, "u-owner", "a")
    assert after["read"] is True and after["reply"] == {"text": "고마워요", "sentAt": "2026-11-20T10:00:00.000Z"}
    assert calls[0]["Key"] == {"PK": "USER#u-owner", "SK": "INBOX#a"}
    assert calls[0]["UpdateExpression"] == "SET #read = :true"
    assert calls[0]["ConditionExpression"] == "attribute_exists(PK) AND #owner = :me"
    assert calls[0]["ExpressionAttributeValues"] == {":true": True, ":me": "u-owner"}


@pytest.mark.parametrize("setup", ["missing", "mismatch"])
def test_mark_read_404_writes_nothing(table, setup):
    if setup == "mismatch":
        put_inbox(table, "u-owner", "a", owner_id="u-other")
    before = scan(table)
    with pytest.raises(ApiError) as e:
        inbox.mark_read("a", OWNER)
    assert code_of(e) == "NOT_FOUND"
    assert scan(table) == before  # 항목을 만들거나 바꾸지 않는다


def test_other_users_cannot_read_owner_item(table):
    _, cid = completed_item()
    for who in (SUHYUN, MINJUN):
        with pytest.raises(ApiError) as e:
            inbox.mark_read(cid, who)
        assert code_of(e) == "NOT_FOUND"
    assert get_inbox(table, "u-owner", cid)["read"] is False
    assert get_inbox(table, "u-suhyun", cid) is None and get_inbox(table, "u-minjun", cid) is None


# ------------------------------------------------------------------ 답장 (Requirement 6)


def test_reply_once(monkeypatch, table):
    _, cid = completed_item()
    calls = spy(monkeypatch, table, "update_item")
    first = inbox.reply(cid, OWNER, "고마워요", NOW)
    assert first == {"text": "고마워요", "sentAt": "2026-11-20T12:00:00.000Z"} and ISO_MS.match(first["sentAt"])
    assert calls[0]["UpdateExpression"] == "SET #reply = :reply"
    assert calls[0]["ConditionExpression"] == "#owner = :me AND attribute_not_exists(#reply)"
    with pytest.raises(ApiError) as e:
        inbox.reply(cid, OWNER, "두 번째")
    assert code_of(e) == "REPLY_ALREADY_SENT" and e.value.status == 409
    stored = get_inbox(table, "u-owner", cid)
    assert stored["reply"] == first and stored["read"] is False  # 답장은 read를 바꾸지 않는다


def test_reply_404_does_not_reveal_reply(table):
    _, cid = completed_item()
    inbox.reply(cid, OWNER, "고마워요")
    before = scan(table)
    for who in (SUHYUN, MINJUN):  # 남의 항목에 답장이 있어도 404
        with pytest.raises(ApiError) as e:
            inbox.reply(cid, who, "가로채기")
        assert code_of(e) == "NOT_FOUND"
    with pytest.raises(ApiError) as e:
        inbox.reply("clm_none", OWNER, "없음")
    assert code_of(e) == "NOT_FOUND"
    assert scan(table) == before


def test_reply_404_when_owner_mismatch(table):
    put_inbox(table, "u-owner", "a", owner_id="u-other")
    with pytest.raises(ApiError) as e:
        inbox.reply("a", OWNER, "t")
    assert code_of(e) == "NOT_FOUND"
    assert "reply" not in get_inbox(table, "u-owner", "a")


def test_reply_unknown_condition_failure_is_integrity_error(monkeypatch, table):
    """조건이 실패했는데 다시 읽어도 원인이 보이지 않으면 500(BE-Q47)."""
    from botocore.exceptions import ClientError

    put_inbox(table, "u-owner", "a")

    def failing(**kw):
        raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")

    monkeypatch.setattr(table, "update_item", failing)
    with pytest.raises(inbox.InboxIntegrityError):
        inbox.reply("a", OWNER, "t")


def test_inbox_writes_do_not_touch_plan_claim_record(table):
    pid, cid = completed_item()
    plan_part = [i for i in scan(table) if i["PK"] != "USER#u-owner"]
    inbox.mark_read(cid, OWNER)
    inbox.reply(cid, OWNER, "고마워요")
    inbox.get_detail(cid, OWNER)
    assert [i for i in scan(table) if i["PK"] != "USER#u-owner"] == plan_part
