"""레벨 0 그래프 (design §7.2, BE-AI-11, BE-AI-13). AGENT_MODE=pipeline.

draft → check_draft → rules → gate → (통과) final_check → END / (거부) fallback → final_check → END.
interrupt가 없어 체크포인터 없이 컴파일하고 ainvoke 1회로 END에 닿는다. 범용 prebuilt 에이전트는 쓰지 않는다.
6b는 rules 자리에 decide를 연결하고 체크포인터를 붙인다(같은 상태·노드·설정 전달 방식).
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agent import nodes
from agent.state import LLM_ERROR, AgentState

READY, FAILED = "READY", "FAILED"
LLM_ERROR_CODE, INVALID_OUTPUT_CODE, FALLBACK_INVARIANT = "LLM_ERROR", "INVALID_OUTPUT", "FALLBACK_INVARIANT"


def build_pipeline_graph() -> Any:
    g = StateGraph(AgentState)
    g.add_node("draft", nodes.draft)
    g.add_node("check_draft", nodes.check_draft)
    g.add_node("rules", nodes.rules)
    g.add_node("gate", nodes.gate)
    g.add_node("fallback", nodes.fallback)
    g.add_node("final_check", nodes.final_check)
    g.add_edge(START, "draft")
    g.add_conditional_edges("draft", lambda s: "check_draft" if s.get("candidate") else END, ["check_draft", END])
    g.add_edge("check_draft", "rules")
    g.add_edge("rules", "gate")
    g.add_conditional_edges("gate", lambda s: "final_check" if s.get("gate_ok") else "fallback", ["final_check", "fallback"])
    g.add_edge("fallback", "final_check")
    g.add_edge("final_check", END)
    return g.compile()  # 체크포인터 없음


_graph: Any = None


def pipeline_graph() -> Any:
    """모듈 로드 뒤 한 번 만든다(상태를 들고 있지 않다)."""
    global _graph
    if _graph is None:
        _graph = build_pipeline_graph()
    return _graph


def initial_state(story: str) -> AgentState:
    return {"story": story, "sources": [story], "notes": [], "trace": [], "degraded": False, "first_proposal": None, "first_report": None}


def decide_outcome(state: AgentState) -> tuple[str, int, str | None]:
    """(세션 status, HTTP 상태, failureCode). design §4.1 표, BE-Q75·BE-Q88."""
    if state.get("final_card") is not None:
        return READY, 200, None
    if state.get("blocked"):
        return FAILED, 502, FALLBACK_INVARIANT
    if state.get("last_failure") == LLM_ERROR:
        return FAILED, 503, LLM_ERROR_CODE
    return FAILED, 502, INVALID_OUTPUT_CODE
