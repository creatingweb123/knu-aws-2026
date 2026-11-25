"""GET /me (BE-AUTH-05), GET /me/claims (BE-CLAIM-07).

GET /me의 unreadInboxCount는 요청자 수신함의 안 읽은 항목 수다(HaruTable 기본 테이블 Query, ConsistentRead).
nickname 클레임이 없을 때의 응답은 BE-Q17을 따른다.
"""

from typing import Any

from common.auth import get_user
from common.responses import api_handler, ok
from domain import claim_service, inbox_service
from handlers._http import dispatch, query_param


def _me(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    return ok(200, {"userId": user.id, "nickname": user.nickname, "unreadInboxCount": inbox_service.unread_count(user)})


def _my_claims(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    return ok(200, {"items": claim_service.list_my_claims(user, query_param(event, "status"))})


ROUTES = {
    "GET /me": _me,
    "GET /me/claims": _my_claims,
}


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    # 1·2단계 이벤트에는 routeKey가 없을 수 있다(GET /me만 있던 시기). 없으면 GET /me로 본다.
    if not event.get("routeKey"):
        event = {**event, "routeKey": "GET /me"}
    return dispatch(ROUTES, event)
