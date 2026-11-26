"""레벨 0 노드 (design §7.2, §8.3, §9, §10.4). draft만 LLM을 부르고 나머지는 순수 함수다. 노드는 DB에 쓰지 않는다.

trace summary에는 고정 문구·개수·유형 이름만 넣는다. 사연·카드 문자열을 인용하지 않는다(Requirement 4.9, BE-Q76 리뷰 대상).
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agent import repair, tools
from agent.card import parse_card
from agent.llm import TIME_BUDGET, LlmError, usage
from agent.prompt import build_messages, retry_message
from agent.state import INVALID_OUTPUT, LLM_ERROR, AgentState
from agent.timebudget import MIN_CALL_START_MS
from domain.privacy import HIGH

MAX_DRAFT_ATTEMPTS = 2


def _conf(config: RunnableConfig | None) -> dict[str, Any]:
    return (config or {}).get("configurable", {})


def _step(state: AgentState, tool: str, summary: str) -> list[dict[str, str]]:
    return list(state.get("trace") or []) + [{"tool": tool, "summary": summary}]


def _kinds(privacy: list[dict[str, Any]]) -> str:
    labels = list(dict.fromkeys(tools.KIND_LABELS.get(h["kind"], "개인정보") for h in privacy))
    return "·".join(labels)


async def draft(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """모델 1회 생성. 검증 실패(NOT_JSON·SCHEMA)만 남은 시간 12초 이상일 때 1회 다시 부른다. LLM_Error는 재시도하지 않는다."""
    conf = _conf(config)
    caller, budget = conf["llm"], conf["deadline"]
    base = build_messages(state["story"])
    messages = list(base)
    out: dict[str, Any] = {"attempts": 0, "model_calls": 0, "token_in": 0, "token_out": 0, "token_estimated": False,
                           "invalid_kinds": [], "candidate": None, "last_failure": None, "llm_error": None}
    trace = list(state.get("trace") or [])
    for attempt in range(1, MAX_DRAFT_ATTEMPTS + 1):
        enough = budget.remaining_ms() >= MIN_CALL_START_MS  # 시도마다 한 번만 읽는다(두 번 읽으면 판정이 엇갈린다)
        if attempt > 1 and not (out["last_failure"] == INVALID_OUTPUT and enough):
            break  # 재시도 생략: 마지막 원인(INVALID_OUTPUT)이 그대로 남는다
        if not enough:
            out.update(llm_error=TIME_BUDGET, last_failure=LLM_ERROR)
            break
        out["attempts"] = attempt
        trace.append({"tool": "draft", "summary": "초안 작성" if attempt == 1 else "초안 형식 오류, 다시 작성"})
        try:
            msg = await caller.ainvoke(messages, budget.call_deadline_s(caller.settings.call_max_s))
        except LlmError as e:
            out["model_calls"] += int(e.called)
            out.update(llm_error=e.code, last_failure=LLM_ERROR)
            break
        out["model_calls"] += 1
        tin, tout, est = usage(messages, msg)
        out["token_in"] += tin
        out["token_out"] += tout
        out["token_estimated"] = out["token_estimated"] or est
        parsed = parse_card(msg.content)
        if parsed.ok:
            out.update(candidate=parsed.card, last_failure=None, llm_error=None)
            break
        out["invalid_kinds"].append(parsed.kind)
        out["last_failure"] = INVALID_OUTPUT
        messages = base + [retry_message(parsed.kind, parsed.paths)]  # 실패한 응답 원문은 다시 보내지 않는다
    out["trace"] = trace
    return out


def check_draft(state: AgentState) -> dict[str, Any]:
    work = repair.with_src(state["candidate"])
    report = tools.check_draft(work, state["sources"])
    out: dict[str, Any] = {"card": work, "report": report}
    if state.get("first_report") is None:  # 첫 실행에서만 쓴다(6b에서 여러 번 돌아도 첫 값 유지)
        out["first_proposal"] = tools.public_card(work)
        out["first_report"] = report
    priv = report["privacy"]
    summary = f"원문에 없음 {len(report['notInSource'])}건, 빈칸 {len(report['missing'])}건, 개인정보 {len(priv)}건"
    if priv:
        summary += f"({_kinds(priv)})"
    out["trace"] = _step(state, "check_draft", summary)
    return out


def rules(state: AgentState) -> dict[str, Any]:
    card, notes = repair.apply_rules(state["card"])
    out: dict[str, Any] = {"card": card, "notes": list(state.get("notes") or []) + notes}
    if notes:
        out["trace"] = _step(state, "rules", f"비공개 장소 {len(notes)}곳 뺌")
    return out


def gate(state: AgentState) -> dict[str, Any]:
    report = tools.check_draft(state["card"], state["sources"])  # 규칙 노드 뒤 다시 검사한다
    ok = tools.gate_verdict(report)
    if ok:
        summary = "제출, 서버 검사 통과"
    else:
        parts = []
        nis = [p for p in report["notInSource"] if p.startswith("places[")]
        high = [h for h in report["privacy"] if h["severity"] == HIGH]
        if nis:
            parts.append(f"원문에 없음 {len(nis)}건")
        if high:
            parts.append(f"개인정보 {len(high)}건({_kinds(high)})")
        if report["schemaErrors"]:
            parts.append(f"형식 오류 {len(report['schemaErrors'])}건")
        summary = "서버 검사에서 걸림: " + ", ".join(parts)
    return {"report": report, "gate_ok": ok, "trace": _step(state, "submit_card", summary)}


def fallback(state: AgentState) -> dict[str, Any]:
    before = len(state["card"].get("places") or [])
    card, notes, masked, allowed = repair.apply_fallback(state["card"], state["sources"])
    parts = []
    if before - len(card["places"]):
        parts.append(f"장소 {before - len(card['places'])}곳 뺌")
    if masked:
        parts.append(f"개인정보 {len(masked)}곳 가림")
    if allowed:
        parts.append(f"확인할 활동 {len(allowed)}곳 표시")
    return {"card": card, "notes": list(state.get("notes") or []) + notes, "masked": masked,
            "allowed_nis_activities": sorted(allowed), "degraded": True,
            "trace": _step(state, "fallback", "자동 정리: " + (", ".join(parts) or "변경 없음"))}


def final_check(state: AgentState) -> dict[str, Any]:
    flags, blocked = tools.final_check(state["card"], state["sources"], masked=state.get("masked") or [],
                                       allowed_nis_activities=set(state.get("allowed_nis_activities") or []))
    return {"flags": flags, "blocked": blocked, "final_card": None if blocked else tools.public_card(state["card"])}
