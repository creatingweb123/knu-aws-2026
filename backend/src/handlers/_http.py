"""핸들러 공통 HTTP 헬퍼 (payload 2.0 이벤트)."""

from __future__ import annotations

import base64
import json
from typing import Any

from common.errors import NOT_FOUND, VALIDATION_ERROR, ApiError


def header(event: dict[str, Any], name: str) -> str | None:
    """payload 2.0은 헤더 이름을 소문자로 넘기지만, 대소문자를 가리지 않고 찾는다."""
    for k, v in (event.get("headers") or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def json_body(event: dict[str, Any]) -> Any:
    raw = event.get("body")
    if raw is None or raw == "":
        return None
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ApiError(VALIDATION_ERROR, details={"body": "JSON 형식이 아니에요."}) from None


def path_param(event: dict[str, Any], name: str) -> str:
    value = (event.get("pathParameters") or {}).get(name)
    if not value:
        raise ApiError(NOT_FOUND)
    return value


def query_param(event: dict[str, Any], name: str) -> str | None:
    return (event.get("queryStringParameters") or {}).get(name)


def dispatch(routes: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    route = routes.get(event.get("routeKey", ""))
    if route is None:
        raise ApiError(NOT_FOUND)
    return route(event)
