"""API Gateway HTTP API(payload 2.0) 응답과 에러 형식 (BE-NFR-05)."""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from common.errors import INTERNAL_ERROR, VALIDATION_ERROR, ApiError
from common.validation import to_details

_log = logging.getLogger(__name__)
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


def api_handler(fn: Callable[[dict[str, Any], Any], dict[str, Any]]) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    """핸들러 공통 에러 변환. ApiError·pydantic ValidationError·예상치 못한 예외를 모두 에러 형식으로 바꾼다.

    예상치 못한 예외는 500 INTERNAL_ERROR(BE-Q23 임시)이고, 응답에는 예외 메시지·스택을 담지 않으며
    로그에는 예외 유형만 남긴다(요구사항 11.4, 11.5).
    """

    @functools.wraps(fn)
    def wrapper(event: dict[str, Any], context: Any) -> dict[str, Any]:
        try:
            return fn(event, context)
        except ApiError as e:
            return error_response(e)
        except ValidationError as e:
            return error_response(ApiError(VALIDATION_ERROR, details=to_details(e)))
        except Exception as e:  # noqa: BLE001
            _log.error("unhandled_error type=%s", type(e).__name__)
            return error_response(ApiError(INTERNAL_ERROR))

    return wrapper


# ---------------------------------------------------------------------------
# 직렬화 (BE-PLAN-08). 허용 목록에 있는 필드만 내보낸다. 저장 속성(PK, SK, claimerId,
# currentClaimId, dueAt(Plan), GSI*, version, ttl 등)은 목록에 없으므로 어느 깊이에도 나가지 않는다.
# currentClaimId는 응답에 내보내지 않는다(BE-Q33).
# ---------------------------------------------------------------------------

PLAN_FIELDS = (
    "planId", "areaId", "owner", "title", "summary", "reason", "estimatedMinutes",
    "places", "question", "status", "createdAt", "completedAt",
)  # + 소유자에게만 "metrics"
PLACE_FIELDS = ("order", "name", "activity", "whyChosen")
METRIC_FIELDS = (
    "authoringMode", "durationMs", "agentMode",
    "addedNotInSource", "addedNotInSourceOrAnswers",
    "firstProposalNotInSource", "deliveredNotInSource", "agentSelfRepairs",
    "missingFirst", "missingDelivered", "questionsAsked", "questionsSkipped",
    "privacyDetected", "privacyInPublished",
    "agentWaitMs", "answerWaitMs", "editMs", "fieldsEditedAfterHandoff", "modelCalls",
)  # §2.5 Plan 예시의 metrics 필드
SUMMARY_FIELDS = (
    "planId", "title", "summary", "estimatedMinutes", "placeCount", "status", "ownerNickname", "createdAt",
)
CLAIM_FIELDS = ("claimId", "planId", "claimer", "status", "claimedAt", "dueAt", "completedAt", "late")


def _plain(value: Any) -> Any:
    """DynamoDB Decimal을 int/float로 바꾼다."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _place(p: Any) -> dict[str, Any]:
    p = p if isinstance(p, dict) else {}
    return {k: _plain(p.get(k)) for k in PLACE_FIELDS if k in p}


def _metrics(m: Any) -> dict[str, Any]:
    m = m if isinstance(m, dict) else {}
    return {k: _plain(m[k]) for k in METRIC_FIELDS if k in m}


def serialize_plan(item: dict[str, Any], *, is_owner: bool, status_override: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "planId": item.get("planId"),
        "areaId": item.get("areaId"),
        "owner": {"userId": item.get("ownerId"), "nickname": item.get("ownerNickname")},
        "title": item.get("title"),
        "summary": item.get("summary"),
        "reason": item.get("reason"),
        "estimatedMinutes": _plain(item.get("estimatedMinutes")),
        "places": [_place(p) for p in item.get("places") or []],
        "question": item.get("question"),
        "status": status_override or item.get("status"),
        "createdAt": item.get("createdAt"),
        "completedAt": item.get("completedAt"),  # 없으면 null
    }
    if is_owner:
        out["metrics"] = _metrics(item.get("metrics"))
    return out


def serialize_plan_summary(item: dict[str, Any], status_override: str | None = None) -> dict[str, Any]:
    """PlanSummary 여덟 필드. 소유자여도 metrics는 넣지 않는다."""
    return {
        "planId": item.get("planId"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "estimatedMinutes": _plain(item.get("estimatedMinutes")),
        "placeCount": len(item.get("places") or []),
        "status": status_override or item.get("status"),
        "ownerNickname": item.get("ownerNickname"),
        "createdAt": item.get("createdAt"),
    }


def serialize_claim(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Claim(§2.5). 저장 속성 claimerId·claimerNickname은 claimer 객체로만 내보낸다."""
    if item is None:
        return None
    return {
        "claimId": item.get("claimId"),
        "planId": item.get("planId"),
        "claimer": {"userId": item.get("claimerId"), "nickname": item.get("claimerNickname")},
        "status": item.get("status"),
        "claimedAt": item.get("claimedAt"),
        "dueAt": item.get("dueAt"),
        "completedAt": item.get("completedAt"),
        "late": bool(item.get("late", False)),
    }


RECORD_FIELDS = ("claimId", "planId", "letter", "photoStatus", "updatedAt", "deliveredAt")


def serialize_record(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Record(§2.5). photoKey·processedKey·photoError·authorId·키 속성은 내보내지 않는다."""
    if item is None:
        return None
    return {
        "claimId": item.get("claimId"),
        "planId": item.get("planId"),
        "letter": item.get("letter"),
        "photoStatus": item.get("photoStatus") or "NONE",
        "updatedAt": item.get("updatedAt"),
        "deliveredAt": item.get("deliveredAt"),
    }


INBOX_FIELDS = ("itemId", "planId", "planTitle", "claimerNickname", "hasPhoto", "read", "createdAt", "reply")


def serialize_reply(value: Any) -> dict[str, Any] | None:
    """InboxItem.reply. 저장 속성이 없으면 null, 있으면 {text, sentAt}만."""
    if not isinstance(value, dict):
        return None
    return {"text": value.get("text"), "sentAt": value.get("sentAt")}


def serialize_inbox_item(item: dict[str, Any]) -> dict[str, Any]:
    """InboxItem(§2.5). PK·SK·ownerId는 내보내지 않는다(BE-Q43).

    claimerNickname은 이어받을 때 ID 토큰에 nickname 클레임이 없었으면 저장되지 않아 null이다(BE-Q17, BE-Q45).
    """
    return {
        "itemId": item.get("itemId"),
        "planId": item.get("planId"),
        "planTitle": item.get("planTitle"),
        "claimerNickname": item.get("claimerNickname"),
        "hasPhoto": bool(item.get("hasPhoto", False)),
        "read": bool(item.get("read", False)),
        "createdAt": item.get("createdAt"),
        "reply": serialize_reply(item.get("reply")),
    }


def serialize_inbox_record(record: dict[str, Any], *, photo_url: str | None = None, caption: str | None = None) -> dict[str, Any]:
    """GET /inbox/{itemId}의 record. 사진이 없으면 photoUrl·photoCaption은 null이다(docs/03 §3.5)."""
    return {"letter": record.get("letter"), "deliveredAt": record.get("deliveredAt"), "photoUrl": photo_url, "photoCaption": caption}


def photo_caption(plan: dict[str, Any]) -> str | None:
    """마지막 장소 이름 + "에서"(docs/03 §3.5). 장소가 없거나 이름이 비면 null. 저장하지 않고 응답 때 만든다."""
    places = plan.get("places") or []
    name = places[-1].get("name") if places and isinstance(places[-1], dict) else None
    return f"{name}에서" if name else None


def iso_utc(dt: datetime) -> str:
    """ISO 8601 UTC 문자열(`2026-11-17T09:00:00.000Z`). naive datetime은 UTC로 본다.

    자릿수를 밀리초로 고정한다. 저장한 시각(createdAt, dueAt)을 DynamoDB에서 문자열로 비교·정렬하므로
    자릿수가 다르면 순서가 틀어진다("…00.500Z" < "…00Z").
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
