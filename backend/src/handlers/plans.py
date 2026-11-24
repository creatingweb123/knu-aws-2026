"""POST /plans, GET /plans, GET /plans/{planId} (BE-PLAN-01–08)."""

from __future__ import annotations

import base64
import json
from typing import Any

from pydantic import ValidationError

from common.auth import get_user
from common.errors import NOT_FOUND, VALIDATION_ERROR, ApiError
from common.responses import api_handler, ok, serialize_plan
from common.validation import PlanCreate, to_details
from domain import plan_service

IDEMPOTENCY_HEADER = "Idempotency-Key"


def _header(event: dict[str, Any], name: str) -> str | None:
    """payload 2.0은 헤더 이름을 소문자로 넘기지만, 대소문자를 가리지 않고 찾는다."""
    for k, v in (event.get("headers") or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def _json_body(event: dict[str, Any]) -> Any:
    raw = event.get("body")
    if raw is None or raw == "":
        return None
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ApiError(VALIDATION_ERROR, details={"body": "JSON 형식이 아니에요."}) from None


def _create(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    key = _header(event, IDEMPOTENCY_HEADER)
    details: dict[str, str] = {}
    if not key or not key.strip():
        details[IDEMPOTENCY_HEADER] = "필수 헤더예요."  # BE-Q29
    body: PlanCreate | None = None
    try:
        body = PlanCreate.model_validate(_json_body(event))
    except ValidationError as e:
        details |= to_details(e)
    if details:
        raise ApiError(VALIDATION_ERROR, details=details)
    assert body is not None
    plan, _created = plan_service.create_plan(user, key, body)
    # 재요청도 처음 응답과 같은 201(BE-Q24)
    return ok(201, {"plan": serialize_plan(plan, is_owner=True)})


def _list(event: dict[str, Any]) -> dict[str, Any]:
    get_user(event)
    q = event.get("queryStringParameters") or {}
    items = plan_service.list_plans(q.get("status"), q.get("limit"))
    return ok(200, {"items": items, "nextCursor": None})  # BE-Q3


def _detail(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    plan_id = (event.get("pathParameters") or {}).get("planId")
    if not plan_id:
        raise ApiError(NOT_FOUND)
    return ok(200, plan_service.get_plan(plan_id, user))


_DISPATCH = {
    "POST /plans": _create,
    "GET /plans": _list,
    "GET /plans/{planId}": _detail,
}


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    route = _DISPATCH.get(event.get("routeKey", ""))
    if route is None:
        raise ApiError(NOT_FOUND)
    return route(event)
