"""AI 하루 카드 세션 저장·조회와 사용자별 하루 할당량 (BE-AI-07, BE-AI-10, docs/02 §2.6).

이 모듈은 AI 패키지(langgraph·langchain·openai) 없이 import된다. PlansFunction이 AiSession을 읽어
AI 세션 지표를 계산하기 때문이다(design §2).

- AiSession: AISESSION#{sessionId} / META, TTL 30일. 그래프가 끝난 뒤 최종 상태로 한 번 저장한다(BE-Q74).
- AiQuota: AIQUOTA#{userId}#{yyyymmdd} / META, TTL 2일. 날짜는 Asia/Seoul 기준(BE-Q73 권장안).
- TTL이 지난 항목은 DynamoDB가 아직 지우지 않았어도 없는 세션으로 다룬다(Requirement 5.8).
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
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


SDK_LOGGERS = ("boto3", "botocore", "urllib3")


@contextlib.contextmanager
def quiet_sdk_logs() -> Iterator[None]:
    """이 블록 안에서만 SDK 로거를 WARNING 이상으로 올린다.

    DEBUG에서 botocore가 GetItem 응답 본문(사연·카드·답변)을 그대로 찍기 때문이다. PlansFunction처럼
    AI 로거 설정(agent.llm.quiet_library_loggers)을 쓰지 않는 함수의 다른 로그 수준은 바꾸지 않으려고 끝나면 되돌린다.
    """
    saved = {n: logging.getLogger(n).level for n in SDK_LOGGERS}
    for n, level in saved.items():
        if level == logging.NOTSET or level < logging.WARNING:
            logging.getLogger(n).setLevel(logging.WARNING)
    try:
        yield
    finally:
        for n, level in saved.items():
            logging.getLogger(n).setLevel(level)


def get_session(session_id: str, *, table: Any = None) -> dict[str, Any] | None:
    with quiet_sdk_logs():
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


QUESTION_KEYS = ("questionId", "path", "text", "reason", "options", "allowFreeText")


def _question_view(q: Any) -> dict[str, Any] | None:
    if not isinstance(q, dict) or not all(k in q for k in QUESTION_KEYS):
        return None
    out = {k: _plain(q.get(k)) for k in QUESTION_KEYS}
    out["options"] = [str(o) for o in (out["options"] or [])]
    out["allowFreeText"] = bool(out["allowFreeText"])
    return out


def _entries(values: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{k: _plain(v.get(k)) for k in keys} for v in (values or []) if isinstance(v, dict)]


def serialize_session_view(item: dict[str, Any]) -> dict[str, Any]:
    """허용 목록 9개 키만 내보낸다. READY가 아니면 card null, flags·notes 빈 배열.

    question은 ASKING이고 저장된 질문이 허용 형식일 때만 채운다(6b). 6a 레벨 0 세션은 ASKING이 없으므로 항상 null이다.
    """
    status = item.get("status")
    ready = status == READY
    view = {
        "sessionId": item.get("sessionId"),
        "status": status,
        "turn": _plain(item.get("turn", 1)),
        "trace": _entries(item.get("trace"), ("step", "tool", "summary")),
        "question": _question_view(item.get("question")) if status == ASKING else None,
        "card": _card_view(item.get("card")) if ready else None,
        "flags": _entries(item.get("flags"), ("path", "type")) if ready else [],
        "notes": _entries(item.get("notes"), ("path", "action", "reason", "source")) if ready else [],
        "degraded": bool(item.get("degraded")) if ready else False,
    }
    return {k: view[k] for k in VIEW_KEYS}


# ---------------------------------------------------------------------------
# 6b 에이전트 세션: 잠금·커밋 (design §3.1, §5, §9.3, BE-Q93·BE-Q96·BE-Q100·BE-Q110)
# ---------------------------------------------------------------------------

AGENT = "AGENT"
PIPELINE = "PIPELINE"
LOCK_MS = 30_000                 # BE-Q110
MAX_TURN_ATTEMPTS = 3            # BE-Q113: 같은 턴 복구 2회까지(세 번째 시도까지 실행)
OK, CONDITION, UNCERTAIN = "OK", "CONDITION", "UNCERTAIN"


def now_ms() -> int:
    import time

    return int(time.time() * 1000)


def build_agent_session_item(
    *,
    session_id: str,
    owner_id: str,
    story: str,
    created_at: datetime,
    lock_token: str,
    lock_now_ms: int,
    prompt_version: str | None,
    llm_mode: str | None,
    llm_provider_label: str | None,
) -> dict[str, Any]:
    """에이전트 생성 항목(BE-Q100): turn 0, WORKING, 잠금을 건 채로 그래프 전에 저장한다."""
    item: dict[str, Any] = {
        **session_key(session_id),
        "sessionId": session_id,
        "ownerId": owner_id,
        "story": story,
        "answers": [],
        "askedPaths": [],
        "status": WORKING,
        "turn": 0,
        "version": 1,
        "agentMode": AGENT,
        "finishRequested": False,
        "lockToken": lock_token,
        "lockedUntil": lock_now_ms + LOCK_MS,
        "lockedAt": iso_utc(created_at),
        "turnAttempts": 1,
        "turnRuns": [lock_token],
        "modelCallsReserved": 0,
        "tokenCharged": 0,
        "modelCalls": 0,
        "tokenIn": 0,
        "tokenOut": 0,
        "tokenInEstimated": 0,
        "tokenEstimated": False,
        "checkDraftCount": 0,
        "gateRejects": 0,
        "questionsAsked": 0,
        "recoveries": 0,
        "card": None,
        "flags": [],
        "notes": [],
        "trace": [],
        "degraded": False,
        "privacyDetected": 0,
        "createdAt": iso_utc(created_at),
        "ttl": int((created_at + SESSION_TTL).timestamp()),
    }
    for k, v in {"promptVersion": prompt_version, "llmMode": llm_mode, "llmProviderLabel": llm_provider_label}.items():
        if v is not None:
            item[k] = v
    return item


def _code(e: ClientError) -> str:
    return e.response.get("Error", {}).get("Code", "")


def acquire_lock(
    session_id: str,
    *,
    owner_id: str,
    expected_turn: int,
    token: str,
    now_utc: datetime,
    now_ms_value: int,
    resume: dict[str, Any] | None = None,
    resume_question_id: str | None = None,
    finish: bool = False,
    table: Any = None,
) -> tuple[str, dict[str, Any] | None]:
    """잠금 획득·WORKING 전환·답변(pendingResume) 기록을 한 번의 조건부 갱신으로 한다(design §5.2).

    pendingResume은 if_not_exists라 처음 기록한 답이 이긴다(BE-Q118). 결과: (OK, ALL_NEW) | (CONDITION, None) | (UNCERTAIN, None).
    """
    names = {"#turn": "turn", "#status": "status", "#ttl": "ttl"}
    values: dict[str, Any] = {
        ":me": owner_id, ":nowEpoch": int(now_utc.timestamp()), ":expected": expected_turn,
        ":ASKING": ASKING, ":WORKING": WORKING, ":nowMs": now_ms_value,
        ":token": token, ":until": now_ms_value + LOCK_MS, ":at": iso_utc(now_utc),
        ":run": [token], ":empty": [], ":one": 1,
    }
    cond = ("attribute_exists(PK) AND ownerId = :me AND #ttl > :nowEpoch AND #turn = :expected "
            "AND #status IN (:ASKING, :WORKING) AND (attribute_not_exists(lockedUntil) OR lockedUntil < :nowMs)")
    sets = ["lockToken = :token", "lockedUntil = :until", "lockedAt = :at", "#status = :WORKING",
            "turnRuns = list_append(if_not_exists(turnRuns, :empty), :run)"]
    if resume is not None:
        values[":qid"] = resume_question_id
        values[":resume"] = resume
        cond += (" AND ((#status = :ASKING AND question.questionId = :qid AND attribute_not_exists(pendingResume))"
                 " OR pendingResume.questionId = :qid)")
        sets.append("pendingResume = if_not_exists(pendingResume, :resume)")
    if finish:
        values[":true"] = True
        sets.append("finishRequested = :true")
    try:
        got = (table or ddb.table()).update_item(
            Key=session_key(session_id),
            ConditionExpression=cond,
            UpdateExpression="SET " + ", ".join(sets) + " ADD turnAttempts :one",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )
        return OK, got["Attributes"]
    except ClientError as e:
        if _code(e) == "ConditionalCheckFailedException":
            return CONDITION, None
        _log.warning("ai_lock id=%s reason=LOCK_UNCERTAIN type=%s", session_id, type(e).__name__)
        return UNCERTAIN, None
    except BotoCoreError as e:
        _log.warning("ai_lock id=%s reason=LOCK_UNCERTAIN type=%s", session_id, type(e).__name__)
        return UNCERTAIN, None


def lock_failure(item: dict[str, Any] | None, *, owner_id: str, expected_turn: int, now_utc: datetime, now_ms_value: int) -> str:
    """잠금 조건 실패 뒤 다시 읽은 항목으로 분기한다(docs/03 §3.2 순서): NOT_FOUND → TURN_MISMATCH → CLOSED → BUSY → CHANGED."""
    if not is_live(item, now_utc) or item.get("ownerId") != owner_id:
        return "NOT_FOUND"
    if turn_of(item) != expected_turn:
        return "TURN_MISMATCH"
    if item.get("status") in TERMINAL:
        return "CLOSED"
    locked = _int(item.get("lockedUntil"))
    if locked is not None and locked >= now_ms_value:
        return "BUSY"
    return "CHANGED"  # 질문·답변 조건이 경합으로 바뀜(다시 검증)


def commit_turn(
    session_id: str,
    *,
    token: str,
    expected_turn: int,
    updates: dict[str, Any],
    if_absent: dict[str, Any] | None = None,
    append_answers: list[dict[str, Any]] | None = None,
    token_correction: int = 0,
    recoveries: int = 0,
    table: Any = None,
) -> str:
    """턴 결과를 lockToken·turn 조건으로 한 번 쓴다(design §5.3). OK | CONDITION | UNCERTAIN."""
    names = {"#turn": "turn"}
    values: dict[str, Any] = {":token": token, ":expected": expected_turn, ":next": expected_turn + 1,
                              ":zero": 0, ":empty": [], ":corr": int(token_correction), ":rec": int(recoveries)}
    sets = ["#turn = :next", "turnAttempts = :zero", "turnRuns = :empty"]
    for i, (k, v) in enumerate(updates.items()):
        names[f"#u{i}"] = k
        values[f":u{i}"] = v
        sets.append(f"#u{i} = :u{i}")
    for i, (k, v) in enumerate((if_absent or {}).items()):
        names[f"#a{i}"] = k
        values[f":a{i}"] = v
        sets.append(f"#a{i} = if_not_exists(#a{i}, :a{i})")
    if append_answers:
        values[":answers"] = append_answers
        sets.append("answers = list_append(if_not_exists(answers, :empty), :answers)")
    expr = "SET " + ", ".join(sets) + " ADD tokenCharged :corr, recoveries :rec REMOVE lockToken, lockedUntil, lockedAt, pendingResume"
    try:
        (table or ddb.table()).update_item(
            Key=session_key(session_id),
            ConditionExpression="lockToken = :token AND #turn = :expected",
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        return OK
    except ClientError as e:
        if _code(e) == "ConditionalCheckFailedException":
            return CONDITION
        _log.warning("ai_commit id=%s reason=COMMIT_UNCERTAIN type=%s", session_id, type(e).__name__)
        return UNCERTAIN
    except BotoCoreError as e:
        _log.warning("ai_commit id=%s reason=COMMIT_UNCERTAIN type=%s", session_id, type(e).__name__)
        return UNCERTAIN


def commit_landed(item: dict[str, Any] | None, *, expected_turn: int, checkpoint_id: str | None) -> bool:
    """커밋 결과를 모를 때 다시 읽은 항목이 이 커밋인지(design §5.3)."""
    return (bool(item) and turn_of(item) == expected_turn + 1 and "lockToken" not in item
            and item.get("checkpointId") == checkpoint_id)


def release_lock(session_id: str, *, token: str, table: Any = None) -> bool:
    """중단 해제(design §9.3): turn·status·pendingResume·turnAttempts는 그대로 두고 잠금만 푼다."""
    try:
        (table or ddb.table()).update_item(
            Key=session_key(session_id),
            ConditionExpression="lockToken = :token",
            UpdateExpression="REMOVE lockToken, lockedUntil, lockedAt",
            ExpressionAttributeValues={":token": token},
        )
        return True
    except (ClientError, BotoCoreError) as e:
        _log.warning("ai_lock id=%s reason=RELEASE_FAILED type=%s", session_id, type(e).__name__)
        return False


def is_agent_session(item: dict[str, Any]) -> bool:
    """agentMode가 없는 항목(6a 이전 형식)은 PIPELINE으로 본다(design §13)."""
    return item.get("agentMode") == AGENT
