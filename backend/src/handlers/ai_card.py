"""AI 하루 카드 세션 (docs/03 §3.2, BE-AI-01, BE-AI-09–11, 6a 레벨 0).

- POST /ai/card-sessions: 검증 → AGENT_MODE → AiQuota → 레벨 0 그래프 → 결과 판정 → AiSession 저장(확인) → EMF → 응답.
- GET /ai/card-sessions/{sessionId}: 소유자의 Live_Session만 200 SessionView. 나머지는 같은 404.
- POST /ai/card-sessions/{sessionId}/turns: 형태 400 → 404 → turn 불일치 200 → 종료 409. 레벨 0은 모델을 부르지 않는다.

로그에는 sessionId·상태·분류 코드·개수·시간만 남긴다. 사연·카드·모델 응답·예외 메시지·키는 남기지 않는다(Requirement 13).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from agent import graph as pipeline
from agent import llm
from agent.prompt import prompt_version
from agent.timebudget import TimeBudget
from common import ddb, metrics
from common.auth import get_user
from common.errors import AI_INVALID_OUTPUT, AI_SESSION_CLOSED, AI_UNAVAILABLE, INTERNAL_ERROR, NOT_FOUND, VALIDATION_ERROR, ApiError
from common.ids import is_session_id, new_session_id
from common.responses import api_handler, ok, utc_now
from common.validation import AiSessionCreate, AiTurn, to_details
from domain import ai_session_service as svc
from domain.privacy import scan_privacy
from handlers._http import dispatch, json_body, path_param

_log = logging.getLogger("haru.ai")

PIPELINE = "pipeline"
_ERROR_CODES = {502: AI_INVALID_OUTPUT, 503: AI_UNAVAILABLE}

# ---------------------------------------------------------------------------
# 콜드 스타트 초기화 (design §13.3, BE-Q85)
# ---------------------------------------------------------------------------

_initialized = False


def init() -> None:
    """AI 전용 SDK 설정으로 HaruTable 리소스를 만들어 꽂는다. 첫 요청에서 한 번만 한다.

    import 시점이 아니라 첫 요청에서 하는 것은 테스트(moto)와 로컬 어댑터가 import 뒤에 환경을 정하기 때문이다.
    """
    global _initialized
    if _initialized:
        return
    import boto3

    llm.quiet_library_loggers()
    ddb.use_table(boto3.resource("dynamodb", config=llm.sdk_config()).Table(os.environ["TABLE_NAME"]))
    prompt_version()  # 프롬프트 파일을 한 번 읽어 둔다
    pipeline.pipeline_graph()
    _initialized = True


# ---------------------------------------------------------------------------
# POST /ai/card-sessions
# ---------------------------------------------------------------------------


def _agent_mode() -> str:
    """미설정 → pipeline. 그 밖의 값은 할당량을 쓰기 전에 503(BE-Q87). 6b가 agent를 연다."""
    mode = os.environ.get("AGENT_MODE", "") or PIPELINE
    if mode != PIPELINE:
        _log.warning("ai_session reason=CONFIG_AGENT_MODE")
        raise ApiError(AI_UNAVAILABLE)
    return mode


def _run_graph(story: str, caller: llm.LlmCaller, budget: TimeBudget) -> dict[str, Any]:
    from langsmith import tracing_context

    config = {"configurable": {"llm": caller, "deadline": budget, "finish_requested": False}}
    with tracing_context(enabled=False):
        return asyncio.run(pipeline.pipeline_graph().ainvoke(pipeline.initial_state(story), config=config))


def _numbered(trace: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [{"step": i, "tool": t["tool"], "summary": t["summary"]} for i, t in enumerate(trace, start=1)]


def _privacy_detected(story: str, first_report: dict[str, Any] | None) -> int:
    """세션 값(design §16.2): 사연 탐지 수 + 첫 Check_Report의 탐지 수. Gate·Fallback·Final_Check 재검사는 세지 않는다."""
    return len(scan_privacy({"story": story})) + len((first_report or {}).get("privacy") or [])


def _save(item: dict[str, Any], budget: TimeBudget) -> None:
    """한 번 저장하고, 결과가 불확실하면 남은 시간이 있을 때 강한 일관성으로 다시 읽어 확인한다(BE-Q89).

    확인하지 못하면 500. 할당량은 되돌리지 않는다.
    """
    try:
        svc.put_session(item)
        return
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        reason = "SESSION_SAVE_CONDITION" if code == "ConditionalCheckFailedException" else "SESSION_SAVE_FAILED"
        _log.warning("ai_session id=%s reason=%s type=%s", item["sessionId"], reason, type(e).__name__)
    except BotoCoreError as e:
        _log.warning("ai_session id=%s reason=SESSION_SAVE_UNCERTAIN type=%s", item["sessionId"], type(e).__name__)
    if not budget.can_verify():
        _log.warning("ai_session id=%s reason=SESSION_SAVE_UNVERIFIED cause=TIME", item["sessionId"])
        raise ApiError(INTERNAL_ERROR)
    try:
        if svc.verify_saved(item):
            _log.info("ai_session id=%s reason=SAVE_VERIFIED", item["sessionId"])
            return
        _log.warning("ai_session id=%s reason=SESSION_SAVE_UNVERIFIED cause=OTHER_ITEM", item["sessionId"])
    except (ClientError, BotoCoreError) as e:
        _log.warning("ai_session id=%s reason=SESSION_SAVE_UNVERIFIED cause=READ type=%s", item["sessionId"], type(e).__name__)
    raise ApiError(INTERNAL_ERROR)


def _emit(state: dict[str, Any], failure_code: str | None, latency_ms: int) -> None:
    """AiLatencyMs(그래프 실행 시간), AiFailure(LLM_Error 1회마다), AiInvalidOutput(검증 실패 출력 1회마다 + FALLBACK_INVARIANT)."""
    metrics.emit(metrics.AI_LATENCY_MS, latency_ms, unit="Milliseconds")
    if state.get("llm_error"):
        metrics.emit(metrics.AI_FAILURE)
    invalid = len(state.get("invalid_kinds") or []) + int(failure_code == pipeline.FALLBACK_INVARIANT)
    if invalid:
        metrics.emit(metrics.AI_INVALID_OUTPUT, invalid)


def _log_outcome(session_id: str, status: str, failure_code: str | None, state: dict[str, Any], latency_ms: int) -> None:
    report = state.get("first_report") or {}
    kinds = sorted({h["kind"] for h in report.get("privacy") or []})
    _log.info(
        "ai_session id=%s status=%s failureCode=%s llmError=%s attempts=%d modelCalls=%d invalid=%s "
        "notInSource=%d missing=%d privacy=%s blocked=%s degraded=%s latencyMs=%d prompt=%s",
        session_id, status, failure_code, state.get("llm_error"), state.get("attempts", 0), state.get("model_calls", 0),
        ",".join(state.get("invalid_kinds") or []) or "-", len(report.get("notInSource") or []), len(report.get("missing") or []),
        ",".join(kinds) or "-", ",".join(state.get("blocked") or []) or "-", bool(state.get("degraded")), latency_ms, prompt_version(),
    )


def _create(event: dict[str, Any], context: Any) -> dict[str, Any]:
    user = get_user(event)
    try:
        body = AiSessionCreate.model_validate(json_body(event))
    except ValidationError as e:
        raise ApiError(VALIDATION_ERROR, details=to_details(e)) from None
    _agent_mode()
    created_at: datetime = utc_now()
    budget = TimeBudget(context, event)
    svc.consume_quota(user.id, created_at)  # 429는 모델·세션 없이 끝난다

    session_id = new_session_id()
    settings = llm.load_settings()
    caller = llm.LlmCaller(settings)
    t0 = time.monotonic()
    state = _run_graph(body.story, caller, budget)
    latency_ms = int((time.monotonic() - t0) * 1000)
    status, http, failure_code = pipeline.decide_outcome(state)

    item = svc.build_session_item(
        session_id=session_id, owner_id=user.id, story=body.story, status=status, created_at=created_at,
        ready_at=utc_now() if status == svc.READY else None,
        card=state.get("final_card"), flags=state.get("flags"), notes=state.get("notes"), trace=_numbered(state.get("trace") or []),
        degraded=bool(state.get("degraded")), model_calls=state.get("model_calls", 0), token_in=state.get("token_in", 0),
        token_out=state.get("token_out", 0), token_estimated=bool(state.get("token_estimated")),
        first_proposal=state.get("first_proposal"), first_report=state.get("first_report"),
        privacy_detected=_privacy_detected(body.story, state.get("first_report")),
        failure_code=failure_code, llm_error=state.get("llm_error"),
        prompt_version=prompt_version(), llm_mode=caller.mode, llm_provider_label=settings.provider_label or None,
    )
    _emit(state, failure_code, latency_ms)
    _log_outcome(session_id, status, failure_code, state, latency_ms)
    _save(item, budget)
    if status != svc.READY:
        raise ApiError(_ERROR_CODES[http])
    return ok(200, svc.serialize_session_view(item))


# ---------------------------------------------------------------------------
# GET /ai/card-sessions/{sessionId}, POST …/turns
# ---------------------------------------------------------------------------


def _owned_session(event: dict[str, Any], user_id: str) -> dict[str, Any]:
    """없음·만료·남의 세션·형식 오류 ID는 모두 같은 404(Requirement 2.2, 2.4)."""
    session_id = path_param(event, "sessionId")
    if not is_session_id(session_id):
        raise ApiError(NOT_FOUND)
    item = svc.get_live_session(session_id, utc_now())
    if item is None or item.get("ownerId") != user_id:
        raise ApiError(NOT_FOUND)
    return item


def _get(event: dict[str, Any], context: Any) -> dict[str, Any]:
    user = get_user(event)
    return ok(200, svc.serialize_session_view(_owned_session(event, user.id)))


def _turns(event: dict[str, Any], context: Any) -> dict[str, Any]:
    user = get_user(event)
    try:
        body = AiTurn.model_validate(json_body(event))
    except ValidationError as e:
        raise ApiError(VALIDATION_ERROR, details=to_details(e)) from None
    item = _owned_session(event, user.id)                       # ①
    if svc.turn_of(item) != body.expectedTurn:                  # ② 같은 턴 재전송 멱등
        return ok(200, svc.serialize_session_view(item))
    if item.get("status") in svc.TERMINAL:                      # ③
        raise ApiError(AI_SESSION_CLOSED)
    # 레벨 0은 비종료 세션을 만들지 않는다. 데이터 이상이나 6b 세션(BE-Q87 미결): 세션을 바꾸지 않는다.
    _log.warning("ai_session id=%s reason=NON_TERMINAL_SESSION", item.get("sessionId"))
    raise ApiError(INTERNAL_ERROR)


ROUTES = {
    "POST /ai/card-sessions": _create,
    "GET /ai/card-sessions/{sessionId}": _get,
    "POST /ai/card-sessions/{sessionId}/turns": _turns,
}


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    init()
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return dispatch({}, event)
    return route(event, context)
