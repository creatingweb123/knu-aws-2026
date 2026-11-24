"""GET /me (BE-AUTH-05).

4단계(수신함) 전까지 unreadInboxCount는 0 고정이고 HaruTable을 읽지 않는다(BE-Q30).
"""

from typing import Any

from common.auth import get_user
from common.responses import api_handler, ok


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    user = get_user(event)
    return ok(200, {"userId": user.id, "nickname": user.nickname, "unreadInboxCount": 0})
