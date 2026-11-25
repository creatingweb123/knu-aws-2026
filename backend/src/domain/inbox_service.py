"""수신함 목록·상세·읽음·답장과 미확인 수 (BE-INBOX-01–04, BE-AUTH-05, spec backend-stage4-record-inbox).

InboxItem(`USER#{ownerId}` / `INBOX#{claimId}`)은 3단계 완료 트랜잭션만 만든다. 이 모듈은 InboxItem의
`read`와 `reply` 두 속성만 조건부 UpdateItem으로 바꾸고 Plan·Claim·Record에는 쓰지 않는다(G4).

권한은 키의 `USER#{요청자 sub}`와 저장된 `ownerId` 비교로만 판단한다(docs/02 §2.8). 남의 항목과 없는 항목은
같은 404다. 반환값은 저장 항목(dict)이며, 응답 직렬화는 핸들러가 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import ddb
from common.auth import User
from common.errors import NOT_FOUND, REPLY_ALREADY_SENT, ApiError
from common.responses import iso_utc, utc_now
from domain.plan_service import _get


class InboxIntegrityError(Exception):
    """정상 경로에서 생기지 않는 상태(InboxItem은 있는데 Plan·Record가 없음, 조건 실패 원인이 보이지 않음 등).

    api_handler가 500 INTERNAL_ERROR로 바꾸고 로그에는 예외 유형 이름만 남긴다(BE-Q23, BE-Q47).
    """


def _inbox_key(user_id: str, item_id: str) -> dict[str, str]:
    return {"PK": f"USER#{user_id}", "SK": f"INBOX#{item_id}"}


def _is_condition_failed(e: ClientError) -> bool:
    return e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def _query_mine(user: User) -> list[dict[str, Any]]:
    """요청자의 InboxItem 전부. 기본 테이블 Query라 ConsistentRead를 쓸 수 있다(InboxItem에는 GSI 속성이 없다, §2.6).

    키와 속성이 어긋난 데이터가 남의 목록에 나가지 않도록 저장된 ownerId도 비교한다(Requirement 3.5·8.7).
    """
    items: list[dict[str, Any]] = []
    start: dict[str, Any] | None = None
    while True:
        args: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(f"USER#{user.id}") & Key("SK").begins_with("INBOX#"),
            "ConsistentRead": True,
        }
        if start:
            args["ExclusiveStartKey"] = start
        resp = ddb.table().query(**args)
        items += resp.get("Items", [])
        start = resp.get("LastEvaluatedKey")
        if not start:
            break
    return [i for i in items if i.get("ownerId") == user.id]


def list_items(user: User) -> list[dict[str, Any]]:
    """GET /inbox: createdAt 역순. SK가 INBOX#{claimId}라 Query 순서로는 정렬할 수 없어 Lambda에서 정렬한다(§2.6)."""
    return sorted(_query_mine(user), key=lambda i: i.get("createdAt") or "", reverse=True)


def unread_count(user: User) -> int:
    """GET /me의 unreadInboxCount. read가 불리언 False인 항목만 센다."""
    return sum(1 for i in _query_mine(user) if i.get("read") is False)


def get_detail(item_id: str, user: User) -> dict[str, Any]:
    """GET /inbox/{itemId}: {"item", "plan", "record"} 저장 항목. read는 바꾸지 않는다."""
    item = ddb.table().get_item(Key=_inbox_key(user.id, item_id), ConsistentRead=True).get("Item")
    if item is None or item.get("ownerId") != user.id:
        raise ApiError(NOT_FOUND)
    plan_id = item.get("planId")
    plan = _get(f"PLAN#{plan_id}") if plan_id else None
    record = _get(f"PLAN#{plan_id}", f"RECORD#{item_id}") if plan_id else None
    if plan is None or record is None or not record.get("deliveredAt"):
        # 완료 트랜잭션이 Plan·Claim·Record·InboxItem을 함께 쓰므로 정상 경로에서는 생기지 않는다(G4, BE-Q47).
        raise InboxIntegrityError()
    return {"item": item, "plan": plan, "record": record}


def mark_read(item_id: str, user: User) -> None:
    """POST /inbox/{itemId}/read. 존재·소유자 확인을 조건부 갱신 한 번으로 한다. 이미 읽었어도 성공(BE-Q44)."""
    try:
        ddb.table().update_item(
            Key=_inbox_key(user.id, item_id),
            UpdateExpression="SET #read = :true",
            # attribute_exists(PK)가 없으면 UpdateItem이 없는 키에 새 항목을 만든다.
            ConditionExpression="attribute_exists(PK) AND #owner = :me",
            ExpressionAttributeNames={"#read": "read", "#owner": "ownerId"},
            ExpressionAttributeValues={":true": True, ":me": user.id},
        )
    except ClientError as e:
        if _is_condition_failed(e):
            raise ApiError(NOT_FOUND) from None  # 실패 원인은 없음·남의 것 둘뿐이고 둘 다 404다
        raise


def reply(item_id: str, user: User, text: str, now: datetime | None = None) -> dict[str, Any]:
    """POST /inbox/{itemId}/reply: {"text", "sentAt"}. InboxItem당 한 번만 저장한다(T17)."""
    value = {"text": text, "sentAt": iso_utc(now or utc_now())}
    key = _inbox_key(user.id, item_id)
    try:
        ddb.table().update_item(
            Key=key,
            UpdateExpression="SET #reply = :reply",
            # 항목이 없으면 ownerId = :me가 거짓이라 존재 확인도 겸한다(docs/03 §3.5).
            ConditionExpression="#owner = :me AND attribute_not_exists(#reply)",
            ExpressionAttributeNames={"#reply": "reply", "#owner": "ownerId"},
            ExpressionAttributeValues={":reply": value, ":me": user.id},
        )
    except ClientError as e:
        if not _is_condition_failed(e):
            raise
        # ownerId는 바뀌지 않고 reply는 지워지지 않으므로 다시 읽은 값이 실패 원인과 같다(§2.6 분기용 재조회).
        current = ddb.table().get_item(Key=key, ConsistentRead=True).get("Item")
        if current is None or current.get("ownerId") != user.id:
            raise ApiError(NOT_FOUND) from None
        if "reply" in current:
            raise ApiError(REPLY_ALREADY_SENT) from None
        raise InboxIntegrityError() from None
    return value
