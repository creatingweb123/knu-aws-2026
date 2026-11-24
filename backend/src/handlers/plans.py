"""POST /plans, GET /plans, GET /plans/{planId}, POST /plans/{planId}/claims (BE-PLAN-01–08, BE-CLAIM-01–04)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from common.auth import get_user
from common.errors import VALIDATION_ERROR, ApiError
from common.responses import api_handler, ok, serialize_claim, serialize_plan
from common.validation import PlanCreate, to_details
from domain import claim_service, plan_service
from handlers._http import dispatch, header, json_body, path_param, query_param

IDEMPOTENCY_HEADER = "Idempotency-Key"


def _create(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    key = header(event, IDEMPOTENCY_HEADER)
    details: dict[str, str] = {}
    if not key or not key.strip():
        details[IDEMPOTENCY_HEADER] = "필수 헤더예요."  # BE-Q29
    body: PlanCreate | None = None
    try:
        body = PlanCreate.model_validate(json_body(event))
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
    items = plan_service.list_plans(query_param(event, "status"), query_param(event, "limit"))
    return ok(200, {"items": items, "nextCursor": None})  # BE-Q3


def _detail(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    return ok(200, plan_service.get_plan(path_param(event, "planId"), user))


def _claim(event: dict[str, Any]) -> dict[str, Any]:
    """새로 이어받으면 201, 본인의 기존 ACTIVE Claim이면 200(§3.3)."""
    user = get_user(event)
    claim, created = claim_service.claim_plan(path_param(event, "planId"), user)
    return ok(201 if created else 200, {"claim": serialize_claim(claim)})


ROUTES = {
    "POST /plans": _create,
    "GET /plans": _list,
    "GET /plans/{planId}": _detail,
    "POST /plans/{planId}/claims": _claim,
}


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return dispatch(ROUTES, event)
