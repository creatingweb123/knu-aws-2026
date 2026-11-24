"""API Gateway HTTP API(payload 2.0) 응답과 에러 형식 (BE-NFR-05)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from common.errors import VALIDATION_ERROR, ApiError

_JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


def ok(status: int, body: dict[str, Any] | None) -> dict[str, Any]:
    """성공 응답. body가 None이면 본문 없이 응답한다(204 등)."""
    resp: dict[str, Any] = {"statusCode": status, "headers": dict(_JSON_HEADERS)}
    if body is not None:
        resp["body"] = json.dumps(body, ensure_ascii=False)
    return resp


def error_body(e: ApiError) -> dict[str, Any]:
    """{"error": {"code", "message", "details"?}}. details는 VALIDATION_ERROR일 때만 담는다."""
    err: dict[str, Any] = {"code": e.code, "message": e.message}
    if e.code == VALIDATION_ERROR:
        err["details"] = dict(e.details or {})
    return {"error": err}


def error_response(e: ApiError) -> dict[str, Any]:
    return ok(e.status, error_body(e))


def iso_utc(dt: datetime) -> str:
    """ISO 8601 UTC 문자열(`2026-11-17T09:00:00Z`). naive datetime은 UTC로 본다."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    text = dt.isoformat(timespec="milliseconds" if dt.microsecond else "seconds")
    return text.replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
