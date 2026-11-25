"""GET /inbox, GET /inbox/{itemId}, POST /inbox/{itemId}/read, POST /inbox/{itemId}/reply.

BE-INBOX-01–04 (4단계). 모든 핸들러는 맨 앞에서 get_user()로 요청자를 얻는다. 본문 검증과 DB 접근은 그 뒤다.
"""

from __future__ import annotations

from typing import Any

from common.auth import get_user
from common.responses import api_handler, ok, serialize_inbox_item, serialize_inbox_record, serialize_plan
from common.validation import Reply
from domain import inbox_service
from handlers._http import dispatch, json_body, path_param


def _list(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    return ok(200, {"items": [serialize_inbox_item(i) for i in inbox_service.list_items(user)]})


def _detail(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    detail = inbox_service.get_detail(path_param(event, "itemId"), user)
    plan = detail["plan"]
    return ok(
        200,
        {
            "item": serialize_inbox_item(detail["item"]),
            # 정상 데이터에서는 항상 소유자라 metrics가 들어간다. 어긋난 데이터에서 남의 metrics가 나가지 않게 비교한다.
            "plan": serialize_plan(plan, is_owner=plan.get("ownerId") == user.id),
            "record": serialize_inbox_record(detail["record"]),
        },
    )


def _read(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    inbox_service.mark_read(path_param(event, "itemId"), user)
    return ok(204, None)


def _reply(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    item_id = path_param(event, "itemId")
    data = Reply.model_validate(json_body(event))  # DB 접근 전에 검증한다
    return ok(201, {"reply": inbox_service.reply(item_id, user, data.text)})


ROUTES = {
    "GET /inbox": _list,
    "GET /inbox/{itemId}": _detail,
    "POST /inbox/{itemId}/read": _read,
    "POST /inbox/{itemId}/reply": _reply,
}


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return dispatch(ROUTES, event)
