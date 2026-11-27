"""Property 4: 출력 키 집합이 허용 목록의 부분집합이고 비소유자 응답에 metrics가 없다.

Validates: Requirements 7.6, 8.1, 8.2, 8.3, 8.4, 8.8
"""

import json
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from common.responses import (
    CLAIM_FIELDS,
    INBOX_FIELDS,
    METRIC_FIELDS,
    PLACE_FIELDS,
    PLAN_FIELDS,
    SUMMARY_FIELDS,
    serialize_claim,
    serialize_inbox_item,
    serialize_inbox_record,
    serialize_plan,
    serialize_plan_summary,
)

INTERNAL = ["PK", "SK", "claimerId", "currentClaimId", "dueAt", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "version", "ttl"]
junk_key = st.sampled_from(INTERNAL) | st.text(min_size=1, max_size=8)
value = st.none() | st.text(max_size=10) | st.integers(-5, 500) | st.integers(0, 500).map(Decimal)
junk = st.dictionaries(junk_key, value, max_size=6)


@st.composite
def stored_plan(draw):
    places = [
        {**draw(junk), "order": Decimal(i + 1), "name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}
        for i in range(draw(st.integers(1, 3)))
    ]
    metrics = {**draw(junk), "authoringMode": "MANUAL", "durationMs": Decimal(183000), "addedNotInSource": Decimal(0)}
    item = {
        **draw(junk),
        "PK": "PLAN#pln_1", "SK": "META", "planId": "pln_1", "areaId": "default",
        "ownerId": "u-owner", "ownerNickname": "지연", "title": "t", "summary": "s", "reason": "r",
        "estimatedMinutes": Decimal(45), "places": places, "question": "q",
        "status": draw(st.sampled_from(["OPEN", "CLAIMED", "COMPLETED"])),
        "createdAt": "2026-11-17T09:00:00Z", "version": Decimal(1),
        "GSI1PK": "AREA#default#STATUS#OPEN", "GSI1SK": "2026-11-17T09:00:00Z",
        "GSI2PK": "USER#u-owner", "GSI2SK": "PLAN#2026-11-17T09:00:00Z", "metrics": metrics,
    }
    if draw(st.booleans()):
        item.update(currentClaimId="clm_1", claimerId="u-other", dueAt="2026-11-20T09:00:00Z")
    return item


def all_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from all_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from all_keys(v)


@given(item=stored_plan(), is_owner=st.booleans())
def test_plan_allowlist(item, is_owner):
    out = serialize_plan(item, is_owner=is_owner)
    allowed_top = set(PLAN_FIELDS) | ({"metrics"} if is_owner else set())
    assert set(out) == allowed_top
    assert set(out["owner"]) == {"userId", "nickname"}
    for p in out["places"]:
        assert set(p) <= set(PLACE_FIELDS)
    if is_owner:
        assert set(out["metrics"]) <= set(METRIC_FIELDS)
    else:
        assert "metrics" not in out
    keys = set(all_keys(out))
    assert not keys & set(INTERNAL)
    json.dumps(out)  # Decimal이 남지 않는다


@given(item=stored_plan())
def test_summary_has_eight_fields(item):
    out = serialize_plan_summary(item, status_override="OPEN")
    assert set(out) == set(SUMMARY_FIELDS)
    assert out["status"] == "OPEN" and out["placeCount"] == len(item["places"])
    json.dumps(out)


def test_plan_shape_and_nulls():
    item = {
        "planId": "pln_1", "areaId": "default", "ownerId": "u1", "ownerNickname": "지연",
        "title": "t", "summary": "s", "reason": "r", "estimatedMinutes": Decimal(45),
        "places": [{"order": Decimal(1), "name": "n", "activity": "a", "whyChosen": "w"}],
        "question": "q", "status": "CLAIMED", "createdAt": "2026-11-17T09:00:00Z",
        "metrics": {"authoringMode": "MANUAL", "durationMs": Decimal(1), "addedNotInSource": Decimal(0), "privacyInPublished": Decimal(0)},
    }
    out = serialize_plan(item, is_owner=True, status_override="OPEN")
    assert out["owner"] == {"userId": "u1", "nickname": "지연"}
    assert out["completedAt"] is None and "completedAt" in out
    assert out["status"] == "OPEN"
    assert out["estimatedMinutes"] == 45 and isinstance(out["estimatedMinutes"], int)
    assert out["places"] == [{"order": 1, "name": "n", "activity": "a", "whyChosen": "w"}]
    assert out["metrics"] == {"authoringMode": "MANUAL", "durationMs": 1, "addedNotInSource": 0, "privacyInPublished": 0}


def test_claim_allowlist():
    item = {
        "PK": "PLAN#pln_1", "SK": "CLAIM#clm_1", "GSI2PK": "USER#u2", "GSI2SK": "CLAIM#x",
        "claimId": "clm_1", "planId": "pln_1", "claimerId": "u2", "claimerNickname": "수현",
        "status": "ACTIVE", "claimedAt": "2026-11-17T09:00:00Z", "dueAt": "2026-11-20T09:00:00Z", "version": 1,
    }
    out = serialize_claim(item)
    assert set(out) == set(CLAIM_FIELDS)
    assert out["claimer"] == {"userId": "u2", "nickname": "수현"}
    assert out["completedAt"] is None and out["late"] is False
    assert serialize_claim(None) is None


# ---------------------------------------------------------------- 수신함 (spec backend-stage4-record-inbox)

ISO_MS = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
INBOX_INTERNAL = ["PK", "SK", "ownerId", "GSI1PK", "GSI2PK", "version", "ttl"]


def test_inbox_item_shape_and_nulls():
    """Requirement 7.1–7.4: 허용 목록, reply·claimerNickname 없으면 null, 불리언(BE-Q17·BE-Q43·BE-Q45)."""
    stored = {
        "PK": "USER#u-owner", "SK": "INBOX#clm_1", "ownerId": "u-owner", "itemId": "clm_1", "planId": "pln_1",
        "planTitle": "제목", "hasPhoto": False, "read": False, "createdAt": "2026-11-20T09:00:00.000Z",
    }
    out = serialize_inbox_item(stored)
    assert out == {
        "itemId": "clm_1", "planId": "pln_1", "planTitle": "제목", "claimerNickname": None,
        "hasPhoto": False, "read": False, "createdAt": "2026-11-20T09:00:00.000Z", "reply": None,
    }
    with_reply = serialize_inbox_item({**stored, "claimerNickname": "수현", "read": True, "reply": {"text": "고마워요", "sentAt": "2026-11-20T10:00:00.000Z", "extra": 1}})
    assert with_reply["reply"] == {"text": "고마워요", "sentAt": "2026-11-20T10:00:00.000Z"}
    assert with_reply["claimerNickname"] == "수현" and with_reply["read"] is True


def test_inbox_time_values_are_millis_utc():
    import re

    out = serialize_inbox_item({"itemId": "c", "createdAt": "2026-11-20T09:00:00.000Z", "reply": {"text": "t", "sentAt": "2026-11-20T10:00:00.123Z"}})
    rec = serialize_inbox_record({"letter": "글", "deliveredAt": "2026-11-20T09:00:00.000Z"})
    for v in (out["createdAt"], out["reply"]["sentAt"], rec["deliveredAt"]):
        assert re.match(ISO_MS, v)


def test_inbox_record_photo_fields_null():
    """BE-Q42: 5단계 전까지 photoUrl·photoCaption은 null. photoKey 등 내부 속성은 나가지 않는다."""
    rec = {"PK": "PLAN#p", "SK": "RECORD#c", "letter": "글", "deliveredAt": "2026-11-20T09:00:00.000Z", "photoKey": "photos/x.jpg", "authorId": "u"}
    assert serialize_inbox_record(rec) == {"letter": "글", "deliveredAt": "2026-11-20T09:00:00.000Z", "photoUrl": None, "photoCaption": None}


inbox_value = st.none() | st.text(max_size=10) | st.booleans() | st.integers(0, 5).map(Decimal)


@st.composite
def stored_inbox_item(draw):
    item = {
        "PK": "USER#" + draw(st.text(min_size=1, max_size=5)),
        "SK": "INBOX#" + draw(st.text(min_size=1, max_size=5)),
        "ownerId": draw(st.text(min_size=1, max_size=5)),
        "itemId": draw(st.text(min_size=1, max_size=8)),
        "planId": draw(st.text(min_size=1, max_size=8)),
        "planTitle": draw(st.text(max_size=40)),
        "hasPhoto": draw(st.booleans()),
        "read": draw(st.booleans()),
        "createdAt": draw(st.text(max_size=24)),
    }
    if draw(st.booleans()):
        item["claimerNickname"] = draw(st.text(min_size=1, max_size=10))
    if draw(st.booleans()):
        item["reply"] = {"text": draw(st.text(min_size=1, max_size=100)), "sentAt": draw(st.text(max_size=24)), **draw(st.dictionaries(st.text(min_size=1, max_size=5), inbox_value, max_size=2))}
    item.update(draw(st.dictionaries(st.sampled_from(INBOX_INTERNAL) | st.text(min_size=1, max_size=8), inbox_value, max_size=4)))
    return item


@settings(max_examples=200)
@given(item=stored_inbox_item(), record=st.fixed_dictionaries({"letter": st.text(max_size=20), "deliveredAt": st.text(max_size=24)}, optional={"photoKey": st.text(max_size=5), "photoStatus": st.text(max_size=5)}))
def test_property22_inbox_serialization(item, record):
    """Feature: backend-stage4-record-inbox, Property 22: 수신함·기록 직렬화는 허용 목록을 벗어나지 않고 round-trip이 안정하다.

    Validates: Requirements 4.6, 7.1, 7.2, 7.3, 7.4, 7.5
    """
    out = serialize_inbox_item(item)
    assert set(out) <= set(INBOX_FIELDS)
    assert not ({"PK", "SK", "ownerId"} & set(out))
    assert isinstance(out["hasPhoto"], bool) and isinstance(out["read"], bool)
    if isinstance(item.get("reply"), dict):
        assert set(out["reply"]) == {"text", "sentAt"} and out["reply"]["text"] == item["reply"]["text"]
    else:
        assert out["reply"] is None
    assert out["claimerNickname"] == item.get("claimerNickname")
    assert json.loads(json.dumps(out, ensure_ascii=False)) == out
    rec = serialize_inbox_record(record)
    assert rec["photoUrl"] is None and rec["photoCaption"] is None and set(rec) == {"letter", "deliveredAt", "photoUrl", "photoCaption"}
    assert json.loads(json.dumps(rec, ensure_ascii=False)) == rec
