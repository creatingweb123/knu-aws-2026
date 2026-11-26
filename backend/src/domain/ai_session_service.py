"""AI 하루 카드 세션 저장·조회와 사용자별 하루 할당량 (BE-AI-07, BE-AI-10, docs/02 §2.6).

이 모듈은 AI 패키지(langgraph·langchain·openai) 없이 import된다. PlansFunction이 AiSession을 읽어
AI 세션 지표를 계산하기 때문이다(design §2).

- AiSession: AISESSION#{sessionId} / META, TTL 30일. 그래프가 끝난 뒤 최종 상태로 한 번 저장한다(BE-Q74).
- AiQuota: AIQUOTA#{userId}#{yyyymmdd} / META, TTL 2일. 날짜는 Asia/Seoul 기준(BE-Q73 권장안).
- TTL이 지난 항목은 DynamoDB가 아직 지우지 않았어도 없는 세션으로 다룬다(Requirement 5.8).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from common import ddb
from common.errors import AI_QUOTA_EXCEEDED, INTERNAL_ERROR, ApiError
from common.responses import iso_utc

_log = logging.getLogger("haru.ai")

SESSION_TTL = timedelta(days=30)
QUOTA_TTL_DAYS = 2
DEFAULT_DAILY_LIMIT = 10
READY, FAILED, WORKING, ASKING = "READY", "FAILED", "WORKING", "ASKING"
TERMINAL = (READY, FAILED)
VIEW_KEYS = ("sessionId", "status", "turn", "trace", "question", "card", "flags", "notes", "degraded")
CARD_KEYS = ("title", "summary", "reason", "estimatedMinutes", "places", "question")
PLACE_KEYS = ("name", "activity", "whyChosen")


def _seoul() -> Any:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Asia/Seoul")
    except Exception:  # noqa: BLE001 - 시간대 데이터가 없는 환경(일부 slim 이미지). 한국은 일광 절약 시간이 없다
        _log.warning("tzdata_missing fallback=UTC+9")
        return timezone(timedelta(hours=9), "KST")


SEOUL = _seoul()


# ---------------------------------------------------------------------------
# AiQuota
# ---------------------------------------------------------------------------


def quota_day(now_utc: datetime) -> tuple[str, int]:
    """(yyyymmdd, ttl epoch 초). 날짜는 Asia/Seoul, ttl은 그 날짜 00:00(KST) + 2일."""
    local = now_utc.astimezone(SEOUL)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local.strftime("%Y%m%d"), int(start.timestamp()) + QUOTA_TTL_DAYS * 86400


def daily_limit() -> int:
    try:
        return max(0, int(os.environ.get("AI_DAILY_SESSION_LIMIT", DEFAULT_DAILY_LIMIT)))
    except ValueError:
        return DEFAULT_DAILY_LIMIT


def quota_key(user_id: str, now_utc: datetime) -> dict[str, str]:
    return {"PK": f"AIQUOTA#{user_id}#{quota_day(now_utc)[0]}", "SK": "META"}


def consume_quota(user_id: str, now_utc: datetime, *, table: Any = None) -> None:
    """하루 세션 수를 1 올린다. 한도면 429 AI_QUOTA_EXCEEDED(모델을 부르기 전).

    한 항목의 조건부 갱신이라 동시 요청에서도 성공 건수 ≤ 한도다(읽고 나서 쓰지 않는다).
    되돌리지 않는다(실패한 세션도 1건, Requirement 6.4). 조건 실패가 아닌 오류는 할당량을 썼는지 모르므로
    모델을 부르지 않고 500으로 끝낸다(사유 QUOTA_WRITE_FAILED).
    """
    _, ttl = quota_day(now_utc)
    limit = daily_limit()
    if limit <= 0:  # attribute_not_exists 조건이 첫 건을 통과시키므로 한도 0은 쓰기 전에 막는다
        raise ApiError(AI_QUOTA_EXCEEDED)
    try:
        (table or ddb.table()).update_item(
            Key=quota_key(user_id, now_utc),
            UpdateExpression="ADD #s :one SET #ttl = if_not_exists(#ttl, :ttl)",
            ConditionExpression="attribute_not_exists(#s) OR #s < :limit",
            ExpressionAttributeNames={"#s": "sessions", "#ttl": "ttl"},
            ExpressionAttributeValues={":one": 1, ":ttl": ttl, ":limit": limit},
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise ApiError(AI_QUOTA_EXCEEDED) from None
        _log.warning("ai_quota reason=QUOTA_WRITE_FAILED type=%s", type(e).__name__)
        raise ApiError(INTERNAL_ERROR) from None
    except BotoCoreError as e:
        _log.warning("ai_quota reason=QUOTA_WRITE_FAILED type=%s", type(e).__name__)
        raise ApiError(INTERNAL_ERROR) from None


# ---------------------------------------------------------------------------
# AiSession
# ---------------------------------------------------------------------------


def session_key(session_id: str) -> dict[str, str]:
    return {"PK": f"AISESSION#{session_id}", "SK": "META"}


def build_session_item(
    *,
    session_id: str,
    owner_id: str,
    story: str,
    status: str,
    created_at: datetime,
    ready_at: datetime | None = None,
    card: dict[str, Any] | None = None,
    flags: list[dict[str, Any]] | None = None,
    notes: list[dict[str, Any]] | None = None,
    trace: list[dict[str, Any]] | None = None,
    degraded: bool = False,
    model_calls: int = 0,
    token_in: int = 0,
    token_out: int = 0,
    token_estimated: bool = False,
    first_proposal: dict[str, Any] | None = None,
    first_report: dict[str, Any] | None = None,
    privacy_detected: int = 0,
    failure_code: str | None = None,
    llm_error: str | None = None,
    prompt_version: str | None = None,
    llm_mode: str | None = None,
    llm_provider_label: str | None = None,
    agent_mode: str = "PIPELINE",
) -> dict[str, Any]:
    """design §5.1의 AiSession 항목. llmMode·llmProviderLabel은 내부 속성이다(SessionView에 없음)."""
    item: dict[str, Any] = {
        **session_key(session_id),
        "sessionId": session_id,
        "ownerId": owner_id,
        "story": story,
        "answers": [],
        "status": status,
        "turn": 1,
        "version": 1,
        "agentMode": agent_mode,
        "finishRequested": False,
        "modelCalls": model_calls,
        "tokenIn": token_in,
        "tokenOut": token_out,
        "tokenEstimated": token_estimated,
        "card": card if status == READY else None,
        "flags": list(flags or []) if status == READY else [],
        "notes": list(notes or []) if status == READY else [],
        "trace": list(trace or []),
        "degraded": bool(degraded) if status == READY else False,
        "privacyDetected": privacy_detected,
        "createdAt": iso_utc(created_at),
        "ttl": int((created_at + SESSION_TTL).timestamp()),
    }
    optional = {
        "readyAt": iso_utc(ready_at) if (status == READY and ready_at) else None,
        "firstProposal": first_proposal,
        "firstReport": first_report,
        "failureCode": failure_code,
        "llmError": llm_error,
        "promptVersion": prompt_version,
        "llmMode": llm_mode,
        "llmProviderLabel": llm_provider_label,
    }
    item.update({k: v for k, v in optional.items() if v is not None})
    return item


def put_session(item: dict[str, Any], *, table: Any = None) -> None:
    """최종 상태로 한 번 저장한다. 같은 키가 이미 있으면 ConditionalCheckFailedException을 그대로 올린다."""
    (table or ddb.table()).put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal)):
        try:
            return int(value)
        except (ValueError, ArithmeticError):
            return None
    return None


def turn_of(item: dict[str, Any]) -> int | None:
    """저장된 turn 값(정수가 아니면 None → 어떤 expectedTurn과도 다르다)."""
    return _int(item.get("turn"))


def is_live(item: dict[str, Any] | None, now_utc: datetime) -> bool:
    """항목이 있고 ttl > now. ttl이 없거나 숫자가 아니면 데이터 이상으로 보고 만료와 같게 다룬다."""
    if not item:
        return False
    ttl = _int(item.get("ttl"))
    if ttl is None:
        _log.warning("ai_session reason=SESSION_TTL_INVALID")
        return False
    return ttl > int(now_utc.timestamp())


def get_session(session_id: str, *, table: Any = None) -> dict[str, Any] | None:
    return (table or ddb.table()).get_item(Key=session_key(session_id), ConsistentRead=True).get("Item")


def get_live_session(session_id: str, now_utc: datetime, *, table: Any = None) -> dict[str, Any] | None:
    """ConsistentRead로 읽고 Expired_Session이면 None(Requirement 5.8). 읽기 오류는 그대로 올린다."""
    item = get_session(session_id, table=table)
    return item if is_live(item, now_utc) else None


def verify_saved(item: dict[str, Any], *, table: Any = None) -> bool:
    """저장 결과가 불확실할 때(BE-Q89) 강한 일관성으로 다시 읽어 우리 항목인지 확인한다. 읽기 오류는 올린다."""
    got = get_session(item["sessionId"], table=table)
    return bool(got) and got.get("ownerId") == item["ownerId"] and got.get("createdAt") == item["createdAt"]


# ---------------------------------------------------------------------------
# SessionView (docs/03 §3.2)
# ---------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _card_view(card: Any) -> dict[str, Any] | None:
    if not isinstance(card, dict):
        return None
    out = {k: _plain(card.get(k)) for k in CARD_KEYS if k != "places"}
    places = card.get("places") if isinstance(card.get("places"), list) else []
    out["places"] = [{k: _plain(p.get(k)) for k in PLACE_KEYS} for p in places if isinstance(p, dict)]
    return {k: out[k] for k in CARD_KEYS}


def _entries(values: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{k: _plain(v.get(k)) for k in keys} for v in (values or []) if isinstance(v, dict)]


def serialize_session_view(item: dict[str, Any]) -> dict[str, Any]:
    """허용 목록 9개 키만 내보낸다. READY가 아니면 card null, flags·notes 빈 배열. question은 6a에서 항상 null."""
    status = item.get("status")
    ready = status == READY
    view = {
        "sessionId": item.get("sessionId"),
        "status": status,
        "turn": _plain(item.get("turn", 1)),
        "trace": _entries(item.get("trace"), ("step", "tool", "summary")),
        "question": None,
        "card": _card_view(item.get("card")) if ready else None,
        "flags": _entries(item.get("flags"), ("path", "type")) if ready else [],
        "notes": _entries(item.get("notes"), ("path", "action", "reason", "source")) if ready else [],
        "degraded": bool(item.get("degraded")) if ready else False,
    }
    return {k: view[k] for k in VIEW_KEYS}
