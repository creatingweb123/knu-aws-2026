"""6b 에이전트 세션 흐름 (design §4, §5, §6, §7, §9.3, §13, BE-Q93–BE-Q113).

ai_card.handler가 AGENT_MODE=agent인 생성과 agentMode=AGENT 세션의 turns를 여기로 넘긴다. 레벨 0(6a) 경로는 바꾸지 않는다.

- 턴 잠금(lockToken)·커밋·중단 해제·결정적 폐쇄는 ai_session_service, 예약은 BudgetService, 체크포인트는 CheckpointStore.
- 그래프 실행은 tracing_context(enabled=False) 안에서 asyncio.run(…ainvoke(…, durability="sync"))로 한다.
- 응답은 커밋 성공(또는 확인) 뒤에만 보낸다. 커밋을 확정하지 못하면 500이고 다음 요청이 복구한다(design §7).
- 로그에는 sessionId·사유 코드·개수·시간만 남긴다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from agent import agent_tools as at
from agent import checkpoint as ck
from agent import hooks, llm, repair, tools
from agent.agent_nodes import FALLBACK_INVARIANT, LLM_ERROR_CODE, initial_agent_state
from agent.budget import BudgetService, FenceLost
from agent.graph import build_agent_graph
from agent.prompt import agent_prompt_version
from agent.timebudget import VERIFY_MIN_MS, AgentDeadline, TimeBudget
from common import metrics
from common.errors import (
    AI_INVALID_OUTPUT,
    AI_SESSION_BUSY,
    AI_SESSION_CLOSED,
    AI_UNAVAILABLE,
    INTERNAL_ERROR,
    NOT_FOUND,
    VALIDATION_ERROR,
    ApiError,
)
from common.ids import new_session_id
from common.responses import iso_utc, ok, utc_now
from domain import ai_session_service as svc
from domain.privacy import scan_privacy

_log = logging.getLogger("haru.ai")

AGENT_MODEL_CALLS, AGENT_TOKENS, AGENT_TURN_MS = "AgentModelCalls", "AgentTokens", "AgentTurnMs"
AGENT_QUESTIONS, AGENT_GATE_REJECTED, AGENT_DEGRADED = "AgentQuestionsAsked", "AgentGateRejected", "AgentDegraded"
AGENT_SELF_REPAIRS, AGENT_CHECKPOINT_BYTES = "AgentSelfRepairs", "AgentCheckpointBytes"
LLM_ERROR_CODES = {llm.TIMEOUT, llm.CONNECTION, llm.HTTP_400, llm.HTTP_401, llm.HTTP_403, llm.HTTP_429, llm.HTTP_5XX,
                   llm.HTTP_OTHER, llm.KEY_READ_FAILED, llm.CONFIG, llm.TIME_BUDGET, llm.PROVIDER_RESPONSE}

_store: ck.CheckpointStore | None = None


def store() -> ck.CheckpointStore:
    global _store
    if _store is None:
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        _store = ck.CheckpointStore(os.environ.get("CHECKPOINT_TABLE", "HaruAgentCheckpoints"), region_name=region,
                                    endpoint_url=os.environ.get("CHECKPOINT_DDB_ENDPOINT") or None)
    return _store


def use_store(s: ck.CheckpointStore | None) -> None:
    global _store
    _store = s


# ---------------------------------------------------------------------------
# 결과 → 커밋 필드
# ---------------------------------------------------------------------------


def _numbered(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"step": i, "tool": t["tool"], "summary": t["summary"]} for i, t in enumerate(trace, start=1)]


def _privacy_detected(story: str, answers: list[dict[str, Any]], first_report: dict[str, Any] | None) -> int:
    n = len(scan_privacy({"story": story}))
    for a in answers:
        t = at.answer_text(a)
        if t:
            n += len(scan_privacy({"answer": t}))
    return n + len((first_report or {}).get("privacy") or [])


def _new_answers(session: dict[str, Any], values: dict[str, Any]) -> list[dict[str, Any]]:
    """그래프가 소비했지만 아직 AiSession answers에 없는 pendingResume을 answers 형식으로(design §5.3)."""
    pr = session.get("pendingResume")
    if not isinstance(pr, dict):
        return []
    rid = pr.get("resumeId")
    if rid not in (values.get("consumed_resume_ids") or []):
        return []
    if any(a.get("resumeId") == rid for a in session.get("answers") or []):
        return []
    src = next((a for a in values.get("answers") or [] if a.get("resumeId") == rid), {})
    rec = {"questionId": pr.get("questionId"), "path": src.get("path") or (session.get("question") or {}).get("path"),
           "resumeId": rid, "askedAt": session.get("questionAskedAt"), "answeredAt": pr.get("answeredAt"),
           "privacy": bool(src.get("privacy"))}
    for k in ("choice", "text", "skipped"):
        if pr.get(k) is not None:
            rec[k] = pr[k]
    if pr.get("viaFinish"):
        rec["viaFinish"] = True
    return [rec]


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def build_updates(session: dict[str, Any], values: dict[str, Any], *, checkpoint_id: str | None, payload_bytes: int,
                  now: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], int]:
    """(SET 필드, if_not_exists 필드, 추가할 answers, tokenCharged 보정)."""
    outcome = values["outcome"]
    b = values.get("budget") or {}
    answers_new = _new_answers(session, values)
    all_answers = list(session.get("answers") or []) + answers_new
    up: dict[str, Any] = {
        "status": outcome,
        "question": values.get("question_view") if outcome == svc.ASKING else None,
        "askedPaths": [q["path"] for q in values.get("questions") or []],
        "trace": _numbered(values.get("trace") or []),
        "checkpointId": checkpoint_id,
        "modelCalls": _int(b.get("modelCalls")),
        "tokenIn": _int(b.get("tokenReported")),
        "tokenInEstimated": _int(b.get("tokenEstimated")),
        "tokenOut": _int(b.get("tokenOut")),
        "tokenEstimated": _int(b.get("tokenEstimated")) > 0,
        "tokenCorrected": _int(b.get("tokenCorrection")),
        "checkDraftCount": _int(b.get("checkDrafts")),
        "gateRejects": _int(b.get("gateRejects")),
        "questionsAsked": _int(b.get("questions")),
        "checkpointBytesMax": max(_int(session.get("checkpointBytesMax")), int(payload_bytes or 0)),
        "promptVersion": agent_prompt_version(),
    }
    if values.get("candidate"):
        up["bestCard"] = values["candidate"]
    if outcome == svc.ASKING:
        up["questionAskedAt"] = iso_utc(now)
    if outcome == svc.READY:
        up.update(card=values.get("final_card"), flags=values.get("flags") or [], notes=values.get("notes") or [],
                  degraded=bool(values.get("degraded")), readyAt=iso_utc(now))
    else:
        up.update(card=None, flags=[], notes=[], degraded=False)
    if outcome in svc.TERMINAL:
        up["privacyDetected"] = _privacy_detected(session.get("story") or "", all_answers, values.get("first_report"))
    if outcome == svc.FAILED:
        up["failureCode"] = values.get("failure_code") or LLM_ERROR_CODE
        up["llmError"] = values.get("llm_error") or "NO_CANDIDATE"
    if_absent = {}
    if values.get("first_report") is not None:
        if_absent = {"firstProposal": values.get("first_proposal"), "firstReport": values.get("first_report")}
    correction = max(0, _int(b.get("tokenCorrection")) - _int(session.get("tokenCorrected")))
    return up, if_absent, answers_new, correction


def view_after(session: dict[str, Any], updates: dict[str, Any], expected_turn: int, answers_new: list[dict[str, Any]]) -> dict[str, Any]:
    merged = {**session, **updates, "turn": expected_turn + 1}
    merged["answers"] = list(session.get("answers") or []) + answers_new
    for k in ("lockToken", "lockedUntil", "lockedAt", "pendingResume"):
        merged.pop(k, None)
    return merged


def respond(item: dict[str, Any]) -> dict[str, Any]:
    status = item.get("status")
    if status == svc.FAILED:
        raise ApiError(AI_INVALID_OUTPUT if item.get("failureCode") == FALLBACK_INVARIANT else AI_UNAVAILABLE)
    return ok(200, svc.serialize_session_view(item))


# ---------------------------------------------------------------------------
# 커밋 (확인 포함)
# ---------------------------------------------------------------------------


def commit(session: dict[str, Any], *, token: str, expected_turn: int, updates: dict[str, Any], if_absent: dict[str, Any],
           answers_new: list[dict[str, Any]], correction: int, deadline: AgentDeadline | None) -> dict[str, Any]:
    sid = session["sessionId"]
    hooks.fire("before_commit")
    res = svc.commit_turn(sid, token=token, expected_turn=expected_turn, updates=updates, if_absent=if_absent,
                          append_answers=answers_new, token_correction=correction,
                          recoveries=max(0, _int(session.get("turnAttempts")) - 1))
    hooks.fire("after_commit")
    if res == svc.OK:
        return view_after(session, updates, expected_turn, answers_new)
    if res == svc.UNCERTAIN and (deadline is None or deadline.lambda_remaining_ms() >= VERIFY_MIN_MS):
        try:
            got = svc.get_session(sid)
        except (ClientError, BotoCoreError):
            got = None
        if svc.commit_landed(got, expected_turn=expected_turn, checkpoint_id=updates.get("checkpointId")):
            return got
    if res == svc.CONDITION:
        try:
            got = svc.get_session(sid)
        except (ClientError, BotoCoreError):
            got = None
        if got and svc.turn_of(got) == expected_turn + 1:  # 다른 실행이 이미 커밋했다(F8)
            _log.warning("ai_commit id=%s reason=COMMITTED_BY_OTHER", sid)
            return got
    _log.warning("ai_commit id=%s reason=COMMIT_NOT_CONFIRMED result=%s", sid, res)
    raise ApiError(INTERNAL_ERROR)


def delete_checkpoints(saver: Any, sid: str, deadline: AgentDeadline | None) -> None:
    if deadline is not None and deadline.lambda_remaining_ms() < VERIFY_MIN_MS:
        _log.info("ai_ckpt id=%s reason=CHECKPOINT_DELETE_SKIPPED", sid)
        return
    try:
        hooks.fire("before_delete")
        saver.delete_thread(sid)
    except Exception as e:  # noqa: BLE001 - 삭제 실패는 응답을 바꾸지 않는다(TTL이 지운다, BE-Q103)
        _log.warning("ai_ckpt id=%s reason=CHECKPOINT_DELETE_FAILED type=%s", sid, type(e).__name__)


# ---------------------------------------------------------------------------
# 결정적 폐쇄 (design §7.1) — 체크포인트 없음·이상·복구 한도·모드 전환
# ---------------------------------------------------------------------------


def close_deterministically(session: dict[str, Any], *, token: str, expected_turn: int, reason: str,
                            deadline: AgentDeadline | None = None) -> dict[str, Any]:
    sid = session["sessionId"]
    answers = list(session.get("answers") or [])
    sources = at.sources_for(session.get("story") or "", answers)
    cand = at.valid_candidate(session.get("bestCard"))
    trace = list(session.get("trace") or [])
    up: dict[str, Any] = {"question": None, "promptVersion": agent_prompt_version()}
    if cand:
        work, rule_notes = repair.apply_rules(repair.with_src(cand))
        card, notes, masked, allowed = repair.apply_fallback(work, sources)
        flags, blocked = tools.final_check(card, sources, masked=masked, allowed_nis_activities=allowed)
        trace.append({"step": len(trace) + 1, "tool": "fallback", "summary": "자동 정리: 진행 중이던 정리를 마무리함"})
        if blocked:
            up.update(status=svc.FAILED, failureCode=FALLBACK_INVARIANT, llmError=reason, card=None, flags=[], notes=[], degraded=False)
        else:
            up.update(status=svc.READY, card=tools.public_card(card), flags=flags, notes=rule_notes + notes, degraded=True,
                      readyAt=iso_utc(utc_now()))
    else:
        trace.append({"step": len(trace) + 1, "tool": "fallback", "summary": "자동 정리: 쓸 수 있는 초안이 없음"})
        up.update(status=svc.FAILED, failureCode=LLM_ERROR_CODE, llmError=reason, card=None, flags=[], notes=[], degraded=False)
    up["trace"] = trace
    up["privacyDetected"] = _privacy_detected(session.get("story") or "", answers, session.get("firstReport"))
    _log.warning("ai_session id=%s reason=CLOSED_DETERMINISTICALLY cause=%s status=%s", sid, reason, up["status"])
    item = commit(session, token=token, expected_turn=expected_turn, updates=up, if_absent={}, answers_new=[], correction=0,
                  deadline=deadline)
    delete_checkpoints(store().for_run(session_ttl=_int(session.get("ttl"))), sid, deadline)
    if up["status"] == svc.READY:
        metrics.emit(AGENT_DEGRADED)
    return item


# ---------------------------------------------------------------------------
# 그래프 실행 (design §6.2–§6.3)
# ---------------------------------------------------------------------------


class _Outcome:
    def __init__(self, kind: str, values: dict[str, Any] | None = None, checkpoint_id: str | None = None, reason: str | None = None,
                 saver: Any = None, ran: bool = False, graph_ms: int = 0) -> None:
        self.kind, self.values, self.checkpoint_id, self.reason = kind, values, checkpoint_id, reason
        self.saver, self.ran, self.graph_ms = saver, ran, graph_ms


def _run_graph(session: dict[str, Any], *, token: str, expected_turn: int, deadline: AgentDeadline, fence: float,
               settings: llm.LlmSettings) -> _Outcome:
    from langgraph.types import Command
    from langsmith import tracing_context

    sid = session["sessionId"]
    run_turn = expected_turn + 1
    turn_runs = [str(r) for r in session.get("turnRuns") or []]
    attempt = turn_runs.index(token) + 1 if token in turn_runs else len(turn_runs) + 1
    pr = session.get("pendingResume") if isinstance(session.get("pendingResume"), dict) else None
    saver = store().for_run(session_ttl=_int(session.get("ttl")), fence_deadline=fence, remaining_ms=deadline.lambda_remaining_ms)
    app = build_agent_graph(saver)
    budget = BudgetService(sid, token, reserved=_int(session.get("modelCallsReserved")), charged=_int(session.get("tokenCharged")))
    caller = llm.LlmCaller(settings, budget=budget, agent=True)
    base = session.get("checkpointId")
    known = {a.get("resumeId") for a in session.get("answers") or [] if a.get("resumeId")} | ({pr.get("resumeId")} if pr else set())
    conf: dict[str, Any] = {"thread_id": sid, "llm": caller, "deadline": deadline, "run_turn": run_turn,
                            "finish_requested": bool(session.get("finishRequested"))}
    md = {"runTurn": run_turn, "runId": token, "runAttempt": attempt, "resumeId": pr.get("resumeId") if pr else None}

    async def go() -> _Outcome:
        try:
            hist = [t async for t in saver.alist({"configurable": {"thread_id": sid}})]
        except (ClientError, BotoCoreError) as e:
            _log.warning("ai_ckpt id=%s reason=CHECKPOINT_READ_FAILED type=%s", sid, type(e).__name__)
            return _Outcome("READ_FAILED", saver=saver)
        if base is None and not hist:
            inp: Any = initial_agent_state(session.get("story") or "")
        else:
            tip = ck.select_tip(hist, base=base, run_turn=run_turn, turn_runs=turn_runs, my_run_id=token, known_resume_ids=known)
            if tip.kind == "MISSING" or (tip.kind == "NEW" and hist):
                return _Outcome("CLOSE", reason="NO_CHECKPOINT", saver=saver)
            if tip.kind == "NEW":
                inp = initial_agent_state(session.get("story") or "")
            else:
                conf["checkpoint_id"] = tip.checkpoint_id
                snap = await app.aget_state({"configurable": {"thread_id": sid, "checkpoint_id": tip.checkpoint_id}})
                dec = ck.classify_resume(snap, pending_resume=pr, run_turn=run_turn)
                if dec.kind == ck.ANOMALY:
                    return _Outcome("CLOSE", reason=dec.reason, saver=saver)
                if dec.kind == ck.COMMIT_AS_IS:
                    _log.info("ai_ckpt id=%s reason=TURN_ALREADY_DONE", sid)
                    return _Outcome("DONE", values=dict(snap.values), checkpoint_id=tip.checkpoint_id, saver=saver)
                if dec.kind in (ck.RESUME_ANSWER, ck.RESUME_CONTINUE):
                    inp = Command(resume={dec.interrupt_id: dec.value})
                else:
                    inp = None
        t0 = time.monotonic()
        try:
            result = await app.ainvoke(inp, {"configurable": conf, "metadata": md}, durability="sync")
        except ck.CheckpointFenceError as e:
            _log.warning("ai_ckpt id=%s reason=%s", sid, e.reason)
            return _Outcome("FENCED", saver=saver, checkpoint_id=ck.checkpoint_id_of(saver.last_config), ran=True)
        except FenceLost:
            return _Outcome("LOST", saver=saver)
        except (ClientError, BotoCoreError) as e:
            _log.warning("ai_ckpt id=%s reason=CHECKPOINT_WRITE_FAILED type=%s", sid, type(e).__name__)
            return _Outcome("FENCED", saver=saver, checkpoint_id=ck.checkpoint_id_of(saver.last_config), ran=True)
        values = {k: v for k, v in result.items() if k != "__interrupt__"}
        cid = ck.checkpoint_id_of(saver.last_config) or conf.get("checkpoint_id")
        return _Outcome("DONE", values=values, checkpoint_id=cid, saver=saver, ran=True, graph_ms=int((time.monotonic() - t0) * 1000))

    with tracing_context(enabled=False):
        return asyncio.run(go())


def _emit(session: dict[str, Any], values: dict[str, Any], outcome: _Outcome, turn_ms: int) -> None:
    b = values.get("budget") or {}
    calls = max(0, _int(b.get("modelCalls")) - _int(session.get("modelCalls")))
    tokens = max(0, (_int(b.get("tokenReported")) + _int(b.get("tokenEstimated")) + _int(b.get("tokenOut")))
                 - (_int(session.get("tokenIn")) + _int(session.get("tokenInEstimated")) + _int(session.get("tokenOut"))))
    metrics.emit(AGENT_MODEL_CALLS, calls)
    metrics.emit(AGENT_TOKENS, tokens)
    metrics.emit(AGENT_TURN_MS, turn_ms, unit="Milliseconds")
    metrics.emit(AGENT_CHECKPOINT_BYTES, int(getattr(outcome.saver, "max_payload", 0) or 0), unit="Bytes")
    if outcome.graph_ms:
        metrics.emit(metrics.AI_LATENCY_MS, outcome.graph_ms, unit="Milliseconds")
    rejects = _int(b.get("gateRejects")) - _int(session.get("gateRejects"))
    if rejects > 0:
        metrics.emit(AGENT_GATE_REJECTED, rejects)
    if values.get("outcome") == svc.ASKING:
        metrics.emit(AGENT_QUESTIONS)
    if values.get("llm_error") in LLM_ERROR_CODES and outcome.ran:
        metrics.emit(metrics.AI_FAILURE)
    if values.get("failure_code") == FALLBACK_INVARIANT:
        metrics.emit(metrics.AI_INVALID_OUTPUT)
    if values.get("outcome") == svc.READY:
        if values.get("degraded"):
            metrics.emit(AGENT_DEGRADED)
        repairs = sum(1 for n in values.get("notes") or [] if n.get("action") in ("REWRITTEN", "REMOVED"))
        if repairs:
            metrics.emit(AGENT_SELF_REPAIRS, repairs)


def execute_turn(session: dict[str, Any], *, token: str, expected_turn: int, context: Any, event: dict[str, Any],
                 settings: llm.LlmSettings) -> dict[str, Any]:
    """잠금을 잡은 세션의 한 턴을 실행하고 커밋한 뒤 응답한다."""
    sid = session["sessionId"]
    t0 = time.monotonic()
    fence = t0 + ck.FENCE_MS / 1000
    deadline = AgentDeadline(TimeBudget(context, event), fence)
    hooks.fire("lock_after")
    if _int(session.get("turnAttempts")) > svc.MAX_TURN_ATTEMPTS:  # BE-Q113
        return respond(close_deterministically(session, token=token, expected_turn=expected_turn, reason="RECOVERY_LIMIT", deadline=deadline))
    out = _run_graph(session, token=token, expected_turn=expected_turn, deadline=deadline, fence=fence, settings=settings)
    if out.kind == "CLOSE":
        return respond(close_deterministically(session, token=token, expected_turn=expected_turn, reason=out.reason or "ANOMALY",
                                               deadline=deadline))
    if out.kind == "LOST":
        _log.warning("ai_session id=%s reason=FENCE_LOST", sid)
        raise ApiError(INTERNAL_ERROR)
    if out.kind == "READ_FAILED":
        svc.release_lock(sid, token=token)
        raise ApiError(INTERNAL_ERROR)
    if out.kind == "FENCED":
        if expected_turn == 0:  # 생성 응답은 turn 1이어야 한다(docs/03). 마지막 체크포인트로 WORKING 커밋
            if not out.checkpoint_id:
                return respond(close_deterministically(session, token=token, expected_turn=0, reason="FENCED", deadline=deadline))
            snap_values = _values_at(out.saver, sid, out.checkpoint_id)
            snap_values["outcome"] = svc.WORKING
            out = _Outcome("DONE", values=snap_values, checkpoint_id=out.checkpoint_id, saver=out.saver, ran=True)
        else:  # 중단 해제(design §9.3, BE-Q121): 같은 turn의 WORKING
            svc.release_lock(sid, token=token)
            view = dict(session, status=svc.WORKING)
            view.pop("question", None)
            return ok(200, svc.serialize_session_view(view))
    values = out.values or {}
    if values.get("outcome") not in (svc.ASKING, svc.WORKING, svc.READY, svc.FAILED):
        return respond(close_deterministically(session, token=token, expected_turn=expected_turn, reason="NO_OUTCOME", deadline=deadline))
    up, if_absent, answers_new, correction = build_updates(session, values, checkpoint_id=out.checkpoint_id,
                                                           payload_bytes=getattr(out.saver, "max_payload", 0), now=utc_now())
    item = commit(session, token=token, expected_turn=expected_turn, updates=up, if_absent=if_absent, answers_new=answers_new,
                  correction=correction, deadline=deadline)
    turn_ms = int((time.monotonic() - t0) * 1000)
    _emit(session, values, out, turn_ms)
    _log.info("ai_turn id=%s turn=%d status=%s attempt=%d calls=%d ran=%s ms=%d lock=%s", sid, expected_turn + 1, item.get("status"),
              _int(session.get("turnAttempts")), _int((values.get("budget") or {}).get("modelCalls")), out.ran, turn_ms, token[:8])
    if item.get("status") in svc.TERMINAL:
        delete_checkpoints(out.saver, sid, deadline)
    return respond(item)


def _values_at(saver: Any, sid: str, checkpoint_id: str) -> dict[str, Any]:
    t = saver.get_tuple({"configurable": {"thread_id": sid, "checkpoint_id": checkpoint_id}})
    return dict(((t.checkpoint if t else {}) or {}).get("channel_values") or {})


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def create(user: Any, story: str, *, created_at: Any, context: Any, event: dict[str, Any], settings: llm.LlmSettings) -> dict[str, Any]:
    """에이전트 세션 생성(design §4.1, BE-Q100). 할당량은 호출자가 이미 소모했다."""
    sid = new_session_id()
    token = str(uuid.uuid4())
    item = svc.build_agent_session_item(session_id=sid, owner_id=user.id, story=story, created_at=created_at, lock_token=token,
                                        lock_now_ms=svc.now_ms(), prompt_version=agent_prompt_version(), llm_mode=settings.mode,
                                        llm_provider_label=settings.provider_label or None)
    try:
        svc.put_session(item)
    except (ClientError, BotoCoreError) as e:
        _log.warning("ai_session id=%s reason=SESSION_SAVE_FAILED type=%s", sid, type(e).__name__)
        raise ApiError(INTERNAL_ERROR) from None
    try:
        exists = store().shared.get_tuple({"configurable": {"thread_id": sid}})
    except (ClientError, BotoCoreError):
        exists = None
    if exists is not None:  # ULID 충돌 방어(Req 2.3)
        _log.warning("ai_session id=%s reason=CHECKPOINT_EXISTS", sid)
        raise ApiError(INTERNAL_ERROR)
    return execute_turn(item, token=token, expected_turn=0, context=context, event=event, settings=settings)


def _detail(path: str, msg: str) -> ApiError:
    return ApiError(VALIDATION_ERROR, details={path: msg})


def state_check(session: dict[str, Any], body: Any) -> tuple[dict[str, Any] | None, str | None]:
    """잠금 전 상태 기반 검증(design §5.4). (pendingResume 값 또는 None, 조건에 쓸 questionId). 위반은 400."""
    status = session.get("status")
    q = session.get("question") if isinstance(session.get("question"), dict) else None
    ans = body.answer
    turn = svc.turn_of(session) or 0
    if status == svc.ASKING and q:
        if ans is not None:
            if ans.questionId != q.get("questionId"):
                raise _detail("answer.questionId", "지금 질문과 다른 질문이에요.")
            if ans.choice is not None and ans.choice not in (q.get("options") or []):
                raise _detail("answer.choice", "선택지 중에서 골라 주세요.")
            if ans.text is not None and not q.get("allowFreeText"):
                raise _detail("answer.text", "이 질문은 직접 입력을 받지 않아요.")
            resume = {"resumeId": f"r{turn}-{ans.questionId}", "questionId": ans.questionId, "answeredAt": iso_utc(utc_now())}
            for k in ("choice", "text", "skipped"):
                if getattr(ans, k) is not None:
                    resume[k] = getattr(ans, k)
            return resume, ans.questionId
        if body.finish:
            qid = q.get("questionId")
            return {"resumeId": f"r{turn}-{qid}", "questionId": qid, "skipped": True, "viaFinish": True,
                    "answeredAt": iso_utc(utc_now())}, qid
        raise _detail("answer", "질문에 답하거나 finish를 보내 주세요.")
    if ans is not None:  # WORKING
        pr = session.get("pendingResume") if isinstance(session.get("pendingResume"), dict) else None
        if pr and pr.get("questionId") == ans.questionId:
            return None, None  # 같은 답의 재전송: 값은 바꾸지 않고 이어서 진행(BE-Q109·BE-Q118)
        raise _detail("answer.questionId", "지금은 답할 질문이 없어요.")
    return None, None


def turn(user: Any, body: Any, session: dict[str, Any], *, mode: str, context: Any, event: dict[str, Any],
         settings: llm.LlmSettings) -> dict[str, Any]:
    """agentMode=AGENT 세션의 turns(design §5.1). 형태 검증·소유 확인은 호출자가 했다."""
    sid = session["sessionId"]
    expected = body.expectedTurn
    if svc.turn_of(session) != expected:
        return ok(200, svc.serialize_session_view(session))
    if session.get("status") in svc.TERMINAL:
        raise ApiError(AI_SESSION_CLOSED)
    switch = mode != "agent"
    resume, qid = (None, None) if switch else state_check(session, body)
    token = str(uuid.uuid4())
    now = utc_now()
    res, item = svc.acquire_lock(sid, owner_id=user.id, expected_turn=expected, token=token, now_utc=now, now_ms_value=svc.now_ms(),
                                 resume=resume, resume_question_id=qid, finish=bool(body.finish) and not switch)
    if res == svc.UNCERTAIN:
        raise ApiError(INTERNAL_ERROR)
    if res == svc.CONDITION:
        try:
            got = svc.get_session(sid)
        except (ClientError, BotoCoreError):
            raise ApiError(INTERNAL_ERROR) from None
        why = svc.lock_failure(got, owner_id=user.id, expected_turn=expected, now_utc=utc_now(), now_ms_value=svc.now_ms())
        if why == "NOT_FOUND":
            raise ApiError(NOT_FOUND)
        if why == "TURN_MISMATCH":
            return ok(200, svc.serialize_session_view(got))
        if why == "CLOSED":
            raise ApiError(AI_SESSION_CLOSED)
        if why == "BUSY":
            raise ApiError(AI_SESSION_BUSY)
        if not switch:
            state_check(got, body)  # 경합으로 상태가 바뀌었으면 400
        _log.warning("ai_lock id=%s reason=LOCK_CHANGED", sid)
        raise ApiError(INTERNAL_ERROR)
    assert item is not None
    if switch:  # BE-Q101: pipeline으로 내린 뒤 진행 중 에이전트 세션은 모델 없이 결정적으로 끝낸다
        return respond(close_deterministically(item, token=token, expected_turn=expected, reason="MODE_SWITCH"))
    return execute_turn(item, token=token, expected_turn=expected, context=context, event=event, settings=settings)
