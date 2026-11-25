"""Property 18–21, 23: 수신함 목록·단건 접근·읽음·답장·미확인 수.

P18·P23은 FakeTable(임의 페이지 크기)로 목록과 계수를, P19–P21은 moto로 조건부 갱신을 실제로 평가한다.

Validates: spec backend-stage4-record-inbox Requirements 3.1–3.5, 4.3, 4.7, 5.1–5.4, 6.1–6.4, 6.6, 8.1, 8.2, 8.7, 10.7
"""

import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

pytest.importorskip("moto")

from common import ddb  # noqa: E402
from common.auth import User  # noqa: E402
from common.errors import ApiError  # noqa: E402
from domain import inbox_service as inbox  # noqa: E402
from handlers import inbox as inbox_handler  # noqa: E402
from tests.unit.fake_table import FakeTable  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

USERS = ["u-a", "u-b", "u-c"]
PBT = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])

created_at = st.datetimes().map(lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z")


@st.composite
def inbox_items(draw, max_size=12):
    """여러 사용자의 InboxItem. 일부는 키(PK)와 ownerId가 어긋난다."""
    n = draw(st.integers(0, max_size))
    items = []
    for i in range(n):
        pk_user = draw(st.sampled_from(USERS))
        owner = pk_user if draw(st.integers(0, 4)) else draw(st.sampled_from(USERS))  # 약 20%는 다른 값 후보
        item = {
            "PK": f"USER#{pk_user}", "SK": f"INBOX#clm_{i}", "ownerId": owner, "itemId": f"clm_{i}", "planId": f"pln_{i}",
            "planTitle": "t", "hasPhoto": False, "read": draw(st.sampled_from([False, True, False, "false", None])),
            "createdAt": draw(created_at),
        }
        if item["read"] is None:
            del item["read"]
        if draw(st.booleans()):
            item["reply"] = {"text": "답", "sentAt": draw(created_at)}
        items.append(item)
    return items


def mine(items, user_id):
    return [i for i in items if i["PK"] == f"USER#{user_id}" and i["ownerId"] == user_id]


@PBT
@given(items=inbox_items(), page_size=st.integers(1, 5), who=st.sampled_from(USERS))
def test_property18_list_only_mine_desc(monkeypatch, items, page_size, who):
    """Feature: backend-stage4-record-inbox, Property 18: 수신함 목록은 요청자 항목만 createdAt 역순으로 돌려준다."""
    t = FakeTable(page_size=page_size)
    monkeypatch.setattr(ddb, "table", lambda: t)
    for i in items:
        t.put(i)
    out = inbox.list_items(User(who, None))
    assert sorted(i["itemId"] for i in out) == sorted(i["itemId"] for i in mine(items, who))
    assert all(i["PK"] == f"USER#{who}" and i["ownerId"] == who for i in out)
    stamps = [i["createdAt"] for i in out]
    assert stamps == sorted(stamps, reverse=True)


@PBT
@given(items=inbox_items(), page_size=st.integers(1, 5), who=st.sampled_from(USERS))
def test_property23_unread_count(monkeypatch, items, page_size, who):
    """Feature: backend-stage4-record-inbox, Property 23: 미확인 수는 요청자의 안 읽은 항목 수와 같다."""
    t = FakeTable(page_size=page_size)
    monkeypatch.setattr(ddb, "table", lambda: t)
    for i in items:
        t.put(i)
    assert inbox.unread_count(User(who, None)) == sum(1 for i in mine(items, who) if i.get("read") is False)


# ---------------------------------------------------------------- moto 대상


@pytest.fixture(scope="module")
def moto_table():
    mp = pytest.MonkeyPatch()
    set_env(mp)
    with haru_table() as t:
        yield t
    mp.undo()


def reset(t, items, with_plan=True):
    for i in t.scan(ConsistentRead=True)["Items"]:
        t.delete_item(Key={"PK": i["PK"], "SK": i["SK"]})
    ddb._table = t
    for i in items:
        t.put_item(Item=i)
        if with_plan:  # 상세 조회가 읽는 Plan·Record(전달됨)
            t.put_item(Item={"PK": f"PLAN#{i['planId']}", "SK": "META", "planId": i["planId"], "ownerId": i["ownerId"], "title": "t", "status": "COMPLETED"})
            t.put_item(Item={"PK": f"PLAN#{i['planId']}", "SK": f"RECORD#{i['itemId']}", "claimId": i["itemId"], "letter": "글", "deliveredAt": "2026-11-20T09:00:00.000Z"})


def snapshot(t):
    return sorted((json.dumps(i, sort_keys=True, default=str) for i in t.scan(ConsistentRead=True)["Items"]))


def stored(t, user_id, item_id):
    return t.get_item(Key={"PK": f"USER#{user_id}", "SK": f"INBOX#{item_id}"}, ConsistentRead=True).get("Item")


@PBT
@given(items=inbox_items(max_size=6), who=st.sampled_from(USERS), pick=st.integers(0, 7), op=st.sampled_from(["detail", "read", "reply"]))
def test_property19_single_item_access(moto_table, items, who, pick, op):
    """Feature: backend-stage4-record-inbox, Property 19: 수신함 단건 접근은 소유자에게만 허용되고 조회는 쓰지 않는다."""
    reset(moto_table, items)
    item_id = items[pick]["itemId"] if pick < len(items) else "clm_none"
    target = stored(moto_table, who, item_id)
    allowed = target is not None and target.get("ownerId") == who
    before = snapshot(moto_table)
    user = User(who, None)
    try:
        if op == "detail":
            inbox.get_detail(item_id, user)
        elif op == "read":
            inbox.mark_read(item_id, user)
        else:
            inbox.reply(item_id, user, "고마워요")
        outcome = "ok"
    except ApiError as e:
        outcome = e.code
    if not allowed:
        assert outcome == "NOT_FOUND"
        assert snapshot(moto_table) == before  # 어떤 항목도 만들거나 바꾸지 않는다
    elif op == "reply" and "reply" in target:
        assert outcome == "REPLY_ALREADY_SENT" and snapshot(moto_table) == before
    else:
        assert outcome == "ok"
        if op == "detail":
            assert snapshot(moto_table) == before  # 상세는 read를 포함해 아무것도 바꾸지 않는다


@PBT
@given(
    read=st.sampled_from([False, True]),
    has_reply=st.booleans(),
    extra=st.dictionaries(st.sampled_from(["planTitle", "claimerNickname", "hasPhoto", "memo"]), st.text(max_size=5), max_size=3),
    times=st.integers(1, 4),
)
def test_property20_read_idempotent(moto_table, read, has_reply, extra, times):
    """Feature: backend-stage4-record-inbox, Property 20: 읽음 처리는 멱등하고 read만 바꾼다."""
    item = {"PK": "USER#u-a", "SK": "INBOX#clm_1", "ownerId": "u-a", "itemId": "clm_1", "planId": "pln_1", "read": read, "createdAt": "2026-11-20T09:00:00.000Z", **extra}
    if has_reply:
        item["reply"] = {"text": "답", "sentAt": "2026-11-20T10:00:00.000Z"}
    reset(moto_table, [item], with_plan=False)
    for _ in range(times):
        inbox.mark_read("clm_1", User("u-a", None))  # 예외 없음 = 204
    after = stored(moto_table, "u-a", "clm_1")
    assert after == {**item, "read": True}


text_value = st.one_of(
    st.text(min_size=1, max_size=100).map(lambda t: ("valid", t)),
    st.sampled_from(["", "가" * 101]).map(lambda t: ("invalid", t)),
    st.sampled_from([None, 3, ["x"]]).map(lambda t: ("invalid", t)),
)


@PBT
@given(texts=st.lists(text_value, min_size=1, max_size=5), read=st.booleans())
def test_property21_reply_once(moto_table, texts, read):
    """Feature: backend-stage4-record-inbox, Property 21: 답장은 최대 한 번만 저장되고 reply만 바꾼다."""
    item = {"PK": "USER#u-a", "SK": "INBOX#clm_1", "ownerId": "u-a", "itemId": "clm_1", "planId": "pln_1", "read": read, "createdAt": "2026-11-20T09:00:00.000Z"}
    reset(moto_table, [item], with_plan=False)
    first = None
    for kind, text in texts:
        before = stored(moto_table, "u-a", "clm_1")
        event = {
            "routeKey": "POST /inbox/{itemId}/reply",
            "pathParameters": {"itemId": "clm_1"},
            "body": json.dumps({"text": text}, ensure_ascii=False),
            "requestContext": {"authorizer": {"jwt": {"claims": {"token_use": "id", "sub": "u-a"}}}},
        }
        resp = inbox_handler.handler(event, None)
        body = json.loads(resp["body"])
        if kind == "invalid":
            assert resp["statusCode"] == 400 and "text" in body["error"]["details"]
            assert stored(moto_table, "u-a", "clm_1") == before
        elif first is None:
            assert resp["statusCode"] == 201 and body["reply"]["text"] == text
            first = body["reply"]
        else:
            assert resp["statusCode"] == 409 and body["error"]["code"] == "REPLY_ALREADY_SENT"
    after = stored(moto_table, "u-a", "clm_1")
    expected = {**item, "reply": first} if first else item
    assert after == expected  # reply 외 속성(read 포함)은 그대로
