"""6b 에이전트 노드 (design §10, docs/03 §3.2 노드·조건부 엣지, BE-AI-04·08·13).

- LLM을 부르는 노드는 draft와 decide뿐이다. 나머지는 순수 함수이고 판정은 6a tools·repair와 fidelity·privacy가 한다.
- 노드는 DB에 쓰지 않는다. 모델 호출 예약은 config의 LlmCaller에 주입된 BudgetService가 한다.
- ask·pause 노드는 맨 앞에서 무조건 interrupt를 부른다(그 앞에 LLM·DB·조건 분기 없음). try/except로 감싸지 않는다.
- 다음 행선지는 state["route"]에 쓰고 조건부 엣지가 읽는다. 시간 가드·예산 판정은 guard 노드가 한다(LLM 노드 안에서
  조건부 interrupt를 걸지 않는다).
- 턴 결과(outcome·outcome_turn)는 종료·질문·정지 직전에 쓴다. 핸들러와 복구 분류가 이 값으로 턴 종료를 판단한다(design §6.3).
- trace summary에는 고정 문구·개수·유형 이름만 넣는다. 사연·카드·답변 문자열을 인용하지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agent import agent_tools as at
from agent import repair, tools
from agent.budget import BudgetExhausted, ReservationUncertain
from agent.card import NOT_JSON, SCHEMA, content_text, extract_json_object, validate_card
from agent.llm import LlmError
from agent.prompt import agent_draft_messages, agent_retry_text, agent_system_prompt, user_message
from agent.timebudget import MIN_CALL_START_MS
from common.validation import normalize_card_payload

ASKING, WORKING, READY, FAILED = "ASKING", "WORKING", "READY", "FAILED"
LLM_ERROR_CODE, FALLBACK_INVARIANT = "LLM_ERROR", "FALLBACK_INVARIANT"
NUDGE = "도구를 호출해 진행하라. 정리가 끝났으면 submit_card를 호출하라."
BUDGET_KEYS = ("modelCalls", "checkDrafts", "questions", "gateRejects", "tokenReported", "tokenEstimated", "tokenOut",
               "tokenCorrection", "nudged", "checkLimitHit", "drafts")
MAX_DRAFTS = 2  # 최초 호출을 포함한 초안 생성 한도(BE-Q129). JSON 오류와 스키마 오류가 한 예산을 나눠 쓴다


def initial_agent_state(story: str) -> dict[str, Any]:
    return {"mode": "agent", "story": story, "sources": [story], "messages": [], "trace": [], "notes": [], "answers": [],
            "questions": [], "consumed_resume_ids": [], "budget": {k: 0 for k in BUDGET_KEYS}, "candidate": None, "card": None,
            "report": None, "first_proposal": None, "first_report": None, "degraded": False, "outcome": None,
            "outcome_turn": None, "route": None, "resume_to": None, "pending_tool": None, "question_view": None,
            "llm_error": None, "invalid_kinds": [], "draft_feedback": None, "draft_card": None,
            "masked": [], "allowed_nis_activities": [], "final_card": None,
            "flags": [], "blocked": [], "failure_code": None}


def _conf(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _turn(config: RunnableConfig | None) -> int:
    return int(_conf(config).get("run_turn") or 0)


def _step(state: dict[str, Any], tool: str, summary: str) -> list[dict[str, str]]:
    return list(state.get("trace") or []) + [{"tool": tool, "summary": summary}]


def _budget(state: dict[str, Any]) -> dict[str, Any]:
    b = {k: 0 for k in BUDGET_KEYS}
    b.update(state.get("budget") or {})
    return b


def _kinds(privacy: list[dict[str, Any]]) -> str:
    return "·".join(dict.fromkeys(tools.KIND_LABELS.get(h["kind"], "개인정보") for h in privacy))


def _check_summary(report: dict[str, Any]) -> str:
    priv = report["privacy"]
    s = f"원문에 없음 {len(report['notInSource'])}건, 빈칸 {len(report['missing'])}건, 개인정보 {len(priv)}건"
    return s + (f"({_kinds(priv)})" if priv else "")


def _account(b: dict[str, Any], caller: Any, messages: list[Any], msg: Any) -> None:
    """응답 1회를 센다: 호출 수, 보고·추정 입력 토큰, 출력 토큰, 예약 추정치 대비 보정(design §8.3)."""
    from agent.llm import usage

    b["modelCalls"] += 1
    tin, tout, est = usage(messages, msg)
    if est:
        b["tokenEstimated"] += tin
    else:
        b["tokenReported"] += tin
    b["tokenOut"] += tout
    r = getattr(caller, "last_reservation", None)
    if r is not None and not est:
        b["tokenCorrection"] += max(0, tin - r.est_tokens)


def _pause(state: dict[str, Any], config: RunnableConfig, resume_to: str, reason: str) -> dict[str, Any]:
    return {"route": "pause", "resume_to": resume_to, "pause_reason": reason, "outcome": WORKING, "outcome_turn": _turn(config)}


def _fail_route(state: dict[str, Any]) -> str:
    return "fallback" if state.get("candidate") else "fail"


# ---------------------------------------------------------------------------
# 가드
# ---------------------------------------------------------------------------


def guard_draft(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    if _conf(config)["deadline"].remaining_ms() < MIN_CALL_START_MS:
        return _pause(state, config, "draft", "TIME")
    return {"route": "draft"}


def guard_decide(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    b = _budget(state)
    if b["gateRejects"] > at.MAX_GATE_REJECTS:
        return {"route": "fallback"}
    caller = _conf(config)["llm"]
    remaining = caller.remaining_calls()
    if remaining is not None and remaining <= 0:
        return {"route": "fallback", "llm_error": state.get("llm_error") or "BUDGET_CALLS"}
    if _conf(config)["deadline"].remaining_ms() < MIN_CALL_START_MS:
        return _pause(state, config, "guard_decide", "TIME")
    return {"route": "decide"}


# ---------------------------------------------------------------------------
# draft (LLM, 도구 없음)
# ---------------------------------------------------------------------------


async def draft(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """도구 없이 초안을 한 번 부른다(docs/03 §3.2, BE-Q129). 노드 실행 한 번 = 모델 호출 한 번.

    형식 위반(JSON 객체가 아님, 스키마 위반)이면 guard_draft를 거쳐 한 번 더 부른다. 초안 시도 수는 state["budget"]["drafts"]에
    두어 체크포인트에 남는다. 재시도 메시지는 위반 경로와 제한만 담고, 실패한 응답 원문은 다시 보내지 않는다.
    정보 없는 카드(스키마는 맞음)는 위반이 아니므로 재시도하지 않는다(BE-Q122). 두 번째 시도도 위반이면 마지막으로 파싱된 카드를
    check_auto로 넘긴다(스키마 위반이면 check_draft가 schemaErrors로 보고한다). 파싱된 카드가 없으면 빈 카드다.
    """
    conf = _conf(config)
    caller, deadline = conf["llm"], conf["deadline"]
    b = _budget(state)
    first = b["drafts"] == 0
    messages = agent_draft_messages(state["story"], feedback=None if first else state.get("draft_feedback"))
    trace = _step(state, "draft", "초안 작성" if first else "초안 형식 오류, 다시 작성")
    try:
        msg = await caller.ainvoke(messages, deadline.call_deadline_s(caller.settings.call_max_s), call_index=b["modelCalls"])
    except ReservationUncertain:
        return {**_pause(state, config, "draft", "RESERVATION_UNCERTAIN"), "budget": b, "trace": trace}
    except BudgetExhausted as e:
        return {"route": "fail", "llm_error": f"BUDGET_{e.kind}", "budget": b, "trace": trace}
    except LlmError as e:
        b["modelCalls"] += int(e.called)
        return {"route": "fail", "llm_error": e.code, "budget": b, "trace": trace}
    _account(b, caller, messages, msg)
    b["drafts"] += 1
    out: dict[str, Any] = {"budget": b, "trace": trace, "llm_error": None}
    obj = extract_json_object(content_text(msg.content))
    if obj is None:
        kind, paths = NOT_JSON, ()
        parsed = state.get("draft_card")
    else:
        checked = validate_card(obj)
        kind, paths = (None, ()) if checked.ok else (SCHEMA, checked.paths)
        parsed = normalize_card_payload(obj)
        out["draft_card"] = parsed
        out["candidate"] = at.valid_candidate(obj)
    if kind:
        out["invalid_kinds"] = [*(state.get("invalid_kinds") or []), kind]
    if kind and b["drafts"] < MAX_DRAFTS:
        out["draft_feedback"] = agent_retry_text(kind, paths)
        out["route"] = "guard_draft"
        return out
    out["draft_feedback"] = None
    out["card"] = parsed if parsed is not None else dict(at.EMPTY_CARD)
    out["route"] = "check_auto"
    return out


def check_auto(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    b = _budget(state)
    b["checkDrafts"] += 1
    work = repair.with_src(state["card"])
    report = tools.check_draft(work, state["sources"])
    out: dict[str, Any] = {"report": report, "budget": b, "route": "guard_decide",
                           "trace": _step(state, "check_draft", _check_summary(report))}
    if state.get("first_report") is None:
        out["first_proposal"] = tools.public_card(work)
        out["first_report"] = report
    draft_json = json.dumps(tools.public_card(work), ensure_ascii=False)
    out["messages"] = [SystemMessage(agent_system_prompt()), HumanMessage(user_message(state["story"])),
                       HumanMessage(f"초안 카드:\n{draft_json}\n\ncheck_draft 결과:\n{at.report_for_model(report)}\n\n도구를 하나 호출해 정리를 이어가라.")]
    return out


# ---------------------------------------------------------------------------
# decide (LLM, 도구 선택)
# ---------------------------------------------------------------------------


async def decide(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    conf = _conf(config)
    caller, deadline = conf["llm"], conf["deadline"]
    b = _budget(state)
    remaining = caller.remaining_calls()
    last_call = remaining is not None and remaining <= 1
    names = at.tools_for(questions=b["questions"], finish_requested=bool(conf.get("finish_requested")), last_call=last_call)
    messages = list(state.get("messages") or [])
    try:
        msg = await caller.ainvoke(messages, deadline.call_deadline_s(caller.settings.call_max_s), tools=at.tool_specs(names),
                                   call_index=b["modelCalls"])
    except ReservationUncertain:
        return {**_pause(state, config, "guard_decide", "RESERVATION_UNCERTAIN"), "budget": b}
    except BudgetExhausted as e:
        return {"route": "fallback" if state.get("candidate") else "fail", "llm_error": f"BUDGET_{e.kind}", "budget": b}
    except LlmError as e:
        b["modelCalls"] += int(e.called)
        return {"route": _fail_route(state), "llm_error": e.code, "budget": b}
    _account(b, caller, messages, msg)
    messages.append(msg)
    chosen, errors = at.split_tool_calls(msg)
    messages += errors
    trace = list(state.get("trace") or [])
    if chosen is None:
        if errors:
            trace.append({"tool": "decide", "summary": f"도구 호출 형식 오류 {len(errors)}건"})
            return {"messages": messages, "budget": b, "trace": trace, "route": "guard_decide"}
        if b["nudged"] == 0:
            b["nudged"] = 1
            messages.append(HumanMessage(NUDGE))
            trace.append({"tool": "decide", "summary": "도구 호출 재촉"})
            return {"messages": messages, "budget": b, "trace": trace, "route": "guard_decide"}
        trace.append({"tool": "decide", "summary": "도구 호출 없음, 자동 정리로 넘어감"})
        return {"messages": messages, "budget": b, "trace": trace, "route": "fallback" if state.get("candidate") else "fail",
                "llm_error": "NO_TOOL_CALL"}
    out: dict[str, Any] = {"messages": messages, "budget": b, "trace": trace, "pending_tool": chosen}
    if chosen["name"] == at.ASK:
        args = at.AskPlannerArgs.model_validate(chosen["args"])
        why = "NOT_OFFERED" if at.ASK not in names else at.validate_question(
            args, asked_paths=[q["path"] for q in state.get("questions") or []], questions=b["questions"],
            finish_requested=bool(conf.get("finish_requested")), card=state.get("card"))
        if why:
            messages.append(ToolMessage(content=at.tool_error(at.QUESTION_REJECTED, reason=why, hint="MISSING으로 남기고 submit_card"),
                                        tool_call_id=chosen["id"], name=at.ASK))
            trace.append({"tool": "ask_planner", "summary": f"질문 거절({why})"})
            return {**out, "messages": messages, "trace": trace, "pending_tool": None, "route": "guard_decide"}
        b["questions"] += 1
        q = at.accepted_question(args, number=b["questions"], report=state.get("report"))
        trace.append({"tool": "ask_planner", "summary": f"질문 {b['questions']}: {_path_kind(q['path'])}"})
        return {**out, "trace": trace, "budget": b, "questions": list(state.get("questions") or []) + [q], "question_view": q,
                "outcome": ASKING, "outcome_turn": _turn(config), "route": "ask"}
    if chosen["name"] == at.CHECK:
        return {**out, "route": "check_tool"}
    return {**out, "route": "gate"}


def _path_kind(path: str) -> str:
    if path == "estimatedMinutes":
        return "소요 시간"
    if path.startswith("places"):
        return "장소"
    return "방문 질문" if path == "question" else "기타"


# ---------------------------------------------------------------------------
# 도구 노드
# ---------------------------------------------------------------------------


def check_tool(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    b = _budget(state)
    call = state["pending_tool"]
    messages = list(state.get("messages") or [])
    if b["checkDrafts"] >= at.MAX_CHECKS:
        messages.append(ToolMessage(content=at.tool_error(at.CHECK_LIMIT, hint="검사 한도를 다 썼다. submit_card를 호출하라"),
                                    tool_call_id=call["id"], name=at.CHECK))
        route = "fallback" if b["checkLimitHit"] else "guard_decide"
        b["checkLimitHit"] = 1
        return {"messages": messages, "budget": b, "pending_tool": None, "route": route,
                "trace": _step(state, "check_draft", "검사 한도 초과")}
    b["checkDrafts"] += 1
    raw = call["args"].get("card") or {}
    card = normalize_card_payload(raw) if isinstance(raw, dict) else dict(at.EMPTY_CARD)
    work = repair.with_src(card)
    report = tools.check_draft(work, state["sources"])
    out: dict[str, Any] = {"budget": b, "pending_tool": None, "route": "guard_decide", "report": report, "card": card,
                           "trace": _step(state, "check_draft", _check_summary(report))}
    cand = at.valid_candidate(raw)
    if cand is not None:
        out["candidate"] = cand
    if state.get("first_report") is None:
        out["first_proposal"] = tools.public_card(work)
        out["first_report"] = report
    messages.append(ToolMessage(content=at.report_for_model(report), tool_call_id=call["id"], name=at.CHECK))
    out["messages"] = messages
    return out


def ask(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """맨 앞에서 무조건 interrupt. 재개 값(답변)을 기록하고 decide로 돌아간다(design §10.1)."""
    value = interrupt({"kind": "question", **(state.get("question_view") or {})})
    q = state.get("question_view") or {}
    answer = {"questionId": q.get("questionId"), "path": q.get("path"), "resumeId": (value or {}).get("resumeId")}
    for k in ("choice", "text", "skipped"):
        if isinstance(value, dict) and value.get(k) is not None:
            answer[k] = value[k]
    if not any(k in answer for k in ("choice", "text", "skipped")):
        answer["skipped"] = True
    answer["privacy"] = at.answer_has_privacy(answer)
    answers = list(state.get("answers") or []) + [answer]
    out: dict[str, Any] = {"answers": answers, "sources": at.sources_for(state["story"], answers),
                           "consumed_resume_ids": list(state.get("consumed_resume_ids") or []) + [answer["resumeId"]],
                           "question_view": None, "outcome": None, "route": "guard_decide", "pending_tool": None}
    card, note = at.apply_private_place_answer(state.get("card"), q, answer)
    if note:
        out["card"] = card
        cand = at.valid_candidate(card)
        if cand is not None:
            out["candidate"] = cand
        out["notes"] = list(state.get("notes") or []) + [note]
    call = state.get("pending_tool") or {}
    messages = list(state.get("messages") or [])
    messages.append(ToolMessage(content=at.answer_for_model(answer, q), tool_call_id=call.get("id") or "ask", name=at.ASK))
    out["messages"] = messages
    return out


def pause(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """무조건 interrupt({"kind":"continue"}). 재개되면 원래 가려던 노드로 간다."""
    interrupt({"kind": "continue"})
    return {"route": state.get("resume_to") or "guard_decide", "outcome": None, "pause_reason": None}


def gate(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    b = _budget(state)
    call = state["pending_tool"]
    raw = call["args"].get("card") or {}
    card = normalize_card_payload(raw) if isinstance(raw, dict) else dict(at.EMPTY_CARD)
    work = repair.with_src(card)
    report = tools.check_draft(work, state["sources"])
    messages = list(state.get("messages") or [])
    cand = at.valid_candidate(raw)
    out: dict[str, Any] = {"pending_tool": None, "report": report, "budget": b}
    if cand is not None:
        out["candidate"] = cand
    if tools.gate_verdict(report):
        ruled, rule_notes = repair.apply_rules(work)  # 비공개 장소는 남은 질문이 없으므로 뺀다(REMOVED)
        model_notes = call["args"].get("notes") or []
        if rule_notes:  # 장소가 빠져 인덱스가 바뀌었으면 장소 경로의 모델 메모는 버린다
            model_notes = [n for n in model_notes if not (isinstance(n, dict) and str(n.get("path", "")).startswith("places"))]
        notes = list(state.get("notes") or []) + rule_notes + at.clean_model_notes(model_notes, tools.public_card(ruled),
                                                                                    state.get("answers") or [])
        messages.append(ToolMessage(content=json.dumps({"ok": True}), tool_call_id=call["id"], name=at.SUBMIT))
        return {**out, "messages": messages, "card": ruled, "notes": notes, "route": "final_check", "work_ready": True,
                "trace": _step(state, "submit_card", "제출, 서버 검사 통과")}
    b["gateRejects"] += 1
    violations = ([{"path": p, "type": "SCHEMA"} for p in report["schemaErrors"]]
                  + [{"path": p, "type": "NOT_IN_SOURCE"} for p in report["notInSource"] if p.startswith("places[")]
                  + [{"path": h["path"], "type": "PRIVACY"} for h in report["privacy"] if h["severity"] == "HIGH"])
    messages.append(ToolMessage(content=at.tool_error(at.GATE_REJECTED, violations=violations,
                                                      remaining=max(0, at.MAX_GATE_REJECTS - b["gateRejects"] + 1)),
                                tool_call_id=call["id"], name=at.SUBMIT))
    parts = []
    nis = [v for v in violations if v["type"] == "NOT_IN_SOURCE"]
    high = [h for h in report["privacy"] if h["severity"] == "HIGH"]
    if nis:
        parts.append(f"원문에 없음 {len(nis)}건")
    if high:
        parts.append(f"개인정보 {len(high)}건({_kinds(high)})")
    if report["schemaErrors"]:
        parts.append(f"형식 오류 {len(report['schemaErrors'])}건")
    route = "fallback" if b["gateRejects"] > at.MAX_GATE_REJECTS else "guard_decide"
    return {**out, "messages": messages, "card": card, "budget": b, "route": route,
            "trace": _step(state, "submit_card", "서버 검사에서 걸림: " + ", ".join(parts))}


def fallback(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """결정적 폴백(design §7.1과 같은 규칙). 유효 후보가 없으면 FAILED."""
    cand = state.get("candidate")
    if not cand:
        return fail(state, config)
    work, rule_notes = repair.apply_rules(repair.with_src(cand))
    before = len(work.get("places") or [])
    card, notes, masked, allowed = repair.apply_fallback(work, state["sources"])
    parts = []
    removed = len(rule_notes) + before - len(card["places"])
    if removed:
        parts.append(f"장소 {removed}곳 뺌")
    if masked:
        parts.append(f"개인정보 {len(masked)}곳 가림")
    if allowed:
        parts.append(f"확인할 활동 {len(allowed)}곳 표시")
    # 모델 메모는 폴백 카드와 경로가 맞지 않을 수 있어 서버 메모만 남긴다(답변 반영 메모는 유지)
    kept = [n for n in state.get("notes") or [] if n.get("source") == "ANSWER" and n.get("action") == "REMOVED"]
    return {"card": card, "notes": kept + rule_notes + notes, "masked": masked, "allowed_nis_activities": sorted(allowed),
            "degraded": True, "route": "final_check", "trace": _step(state, "fallback", "자동 정리: " + (", ".join(parts) or "변경 없음"))}


def final_check(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    flags, blocked = tools.final_check(state["card"], state["sources"], masked=state.get("masked") or [],
                                       allowed_nis_activities=set(state.get("allowed_nis_activities") or []))
    if blocked:
        return {"flags": flags, "blocked": blocked, "final_card": None, "outcome": FAILED, "outcome_turn": _turn(config),
                "failure_code": FALLBACK_INVARIANT, "route": "end"}
    return {"flags": flags, "blocked": [], "final_card": tools.public_card(state["card"]), "outcome": READY,
            "outcome_turn": _turn(config), "failure_code": None, "route": "end"}


def fail(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    return {"outcome": FAILED, "outcome_turn": _turn(config), "failure_code": LLM_ERROR_CODE, "final_card": None,
            "llm_error": state.get("llm_error") or "NO_CANDIDATE", "route": "end"}
