"""요청자 식별 (BE-AUTH-04).

사용자 ID는 API Gateway JWT authorizer(로컬은 어댑터)가 넣은
requestContext.authorizer.jwt.claims의 `sub`에서만 읽는다. 본문·쿼리·헤더는 보지 않는다.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from common.errors import UNAUTHORIZED, ApiError


class User(NamedTuple):
    id: str
    nickname: str | None  # ID 토큰 nickname 클레임. 없을 때 처리는 BE-Q17·BE-Q30 미결


def _claims(event: dict[str, Any]) -> dict[str, Any]:
    node: Any = event
    for key in ("requestContext", "authorizer", "jwt", "claims"):
        if not isinstance(node, dict):
            return {}
        node = node.get(key)
    return node if isinstance(node, dict) else {}


def get_user(event: dict[str, Any]) -> User:
    claims = _claims(event)
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise ApiError(UNAUTHORIZED)
    nickname = claims.get("nickname")
    return User(sub, nickname if isinstance(nickname, str) and nickname else None)
