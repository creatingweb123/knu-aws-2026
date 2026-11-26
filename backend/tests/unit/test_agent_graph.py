"""6b 에이전트 그래프 (작업 8.4, Fake + 메모리 체크포인터). 체크포인터·잠금을 낀 경로는 test_handlers_ai_agent·test_agent_recovery."""

import asyncio
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent import graph as g
from agent.agent_nodes import initial_agent_state
from agent.budget import NoopBudget
from tests.unit.agent_util import STORY, Ctx, caller, config, run_session

ANS = {"estimatedMinutes": {"choice": "45분"}, "places[0].name": {"choice": "동선에서 빼기"}}


def run(sc, **kw):
    return run_session(sc, answers=ANS, **kw)


def tools_of(state):
    return [t["tool"] for t in state["trace"]]


def test_happy():
    s = run("happy")["state"]
    assert s["outcome"] == "READY" and not s["degraded"] and s["budget"]["modelCalls"] == 2
    assert tools_of(s) == ["draft", "check_draft", "submit_card"] and s["first_report"] is not None
    assert s["notes"] and all(n["action"] in ("REWRITTEN", "ASKED") for n in s["notes"])


def test_ask_once_demo_path():
    r = run("ask_once")
    s = r["state"]
    assert r["turns"] == ["ASKING", "READY"] and s["final_card"]["estimatedMinutes"] == 45
    assert s["answers"][0]["choice"] == "45분" and s["consumed_resume_ids"] == ["r1-q1"]
    assert s["first_report"]["notInSource"]  # 첫 초안('골목 빵집')은 원문에 없음, 이후 고침
    assert s["sources"] == [STORY, "45분"]


@pytest.mark.parametrize(("sc", "degraded", "calls"), [
    ("no_tool_call", False, 3), ("no_tool_call_twice", True, 3), ("bad_json_args", False, 3), ("unknown_tool", False, 3),
    ("parallel_calls", False, 3), ("gate_reject_twice", False, 4), ("gate_reject_thrice", True, 4), ("budget_exhausted", True, 6),
    ("question_rejected", False, 4), ("decide_http_500", True, 2), ("places_empty_then_error", True, 2), ("privacy_card", True, 4),
])
def test_ready_paths(sc, degraded, calls):
    s = run(sc)["state"]
    assert s["outcome"] == "READY" and bool(s["degraded"]) is degraded and s["budget"]["modelCalls"] == calls
    assert s["final_card"] is not None and s["blocked"] == []


@pytest.mark.parametrize(("sc", "err"), [("timeout", "TIMEOUT"), ("http_500", "HTTP_5XX"), ("http_401", "HTTP_401"),
                                         ("http_400", "HTTP_400"), ("empty_draft_then_error", "HTTP_5XX")])
def test_failed_without_candidate(sc, err):
    s = run(sc)["state"]
    assert s["outcome"] == "FAILED" and s["failure_code"] == "LLM_ERROR" and s["llm_error"] == err and s["final_card"] is None


def test_places_only_empty_card_is_valid_candidate():
    """BE-Q122: 정보는 있고 places만 빈 카드는 유효 후보라 LLM 오류여도 READY degraded(장소 MISSING)."""
    s = run("places_empty_then_error")["state"]
    assert s["final_card"]["places"] == [] and {"path": "places", "type": "MISSING"} in s["flags"]


def test_parallel_calls_answered_once_each():
    s = run("parallel_calls")["state"]
    ids = [c["id"] for m in s["messages"] for c in (getattr(m, "tool_calls", None) or [])]
    answered = [m.tool_call_id for m in s["messages"] if m.type == "tool"]
    assert sorted(ids) == sorted(answered)
    errs = [json.loads(m.content).get("error") for m in s["messages"] if m.type == "tool" and m.content.startswith("{")]
    assert "ONE_TOOL_PER_TURN" in errs


def test_question_rejections_and_privacy():
    s = run("question_rejected")["state"]
    rejected = [json.loads(m.content) for m in s["messages"] if m.type == "tool" and "QUESTION_REJECTED" in m.content]
    assert [r["reason"] for r in rejected] == ["PRIVACY", "PATH_NOT_ALLOWED"] and s["budget"]["questions"] == 0
    assert "010" not in json.dumps([t["summary"] for t in s["trace"]], ensure_ascii=False)


def test_ask_twice_then_tools_drop_ask_planner():
    r = run("ask_twice")
    assert r["turns"] == ["ASKING", "ASKING", "READY"]
    last = r["caller"].fake.calls[-1]
    assert "ask_planner" not in last["tools"] and "submit_card" in last["tools"]


def test_private_place_answer_removes_place():
    s = run("private_place_ask")["state"]
    assert s["outcome"] == "READY" and [p["name"] for p in s["final_card"]["places"]] == ["출근길 빵집"]
    assert any(n["action"] == "REMOVED" and n["source"] == "ANSWER" for n in s["notes"])
    assert s["questions"][0]["options"] == ["동선에서 빼기"]


def test_finish_requested_drops_ask_planner():
    app = g.build_agent_graph(InMemorySaver())
    c = caller("ask_once")
    asyncio.run(app.ainvoke(initial_agent_state(STORY), config(c, finish=True)))
    assert all("ask_planner" not in call["tools"] for call in c.fake.calls if call["tools"])


def test_last_call_drops_ask_planner():
    app = g.build_agent_graph(InMemorySaver())
    c = caller("ask_once", budget=NoopBudget(max_calls=2))  # draft 1 + decide 1(마지막)
    asyncio.run(app.ainvoke(initial_agent_state(STORY), config(c)))
    decide_calls = [call for call in c.fake.calls if call["tools"]]
    assert decide_calls and "ask_planner" not in decide_calls[-1]["tools"]


def test_token_budget_exhausted_goes_to_fallback():
    app = g.build_agent_graph(InMemorySaver())
    c = caller("token_heavy", budget=NoopBudget(max_tokens=4000))
    s = asyncio.run(app.ainvoke(initial_agent_state(STORY), config(c)))
    assert s["outcome"] == "READY" and s["degraded"] and s["llm_error"] == "BUDGET_TOKENS" and c.budget.charged <= 4000


def test_pause_when_time_short_then_resume():
    from langgraph.types import Command

    app = g.build_agent_graph(InMemorySaver())
    c = caller("slow_agent")
    r = asyncio.run(app.ainvoke(initial_agent_state(STORY), config(c, ctx=Ctx(25_000, 25_000, 25_000, 11_000))))
    assert r["outcome"] == "WORKING" and r["__interrupt__"][0].value == {"kind": "continue"}
    r2 = asyncio.run(app.ainvoke(Command(resume={r["__interrupt__"][0].id: "continue"}), config(c, run_turn=2)))
    assert r2["outcome"] == "READY" and r2["outcome_turn"] == 2


def test_time_short_before_draft():
    app = g.build_agent_graph(InMemorySaver())
    c = caller("happy")
    r = asyncio.run(app.ainvoke(initial_agent_state(STORY), config(c, ctx=Ctx(11_000))))
    assert r["outcome"] == "WORKING" and c.fake.calls == [] and r["resume_to"] == "draft"


def test_final_check_block_is_failed_502(monkeypatch):
    from agent import agent_nodes

    monkeypatch.setattr(agent_nodes.tools, "final_check", lambda *a, **k: ([], ["SCHEMA"]))
    s = run("happy")["state"]
    assert s["outcome"] == "FAILED" and s["failure_code"] == "FALLBACK_INVARIANT"


def test_no_prebuilt_and_level0_unchanged():
    import pathlib

    src = (pathlib.Path(g.__file__).parent / "agent_nodes.py").read_text(encoding="utf-8")
    assert "prebuilt" not in src and "create_react_agent" not in src
    assert g.build_pipeline_graph().checkpointer is None
    assert set(g.build_agent_graph(InMemorySaver()).get_graph().nodes) >= set(g.AGENT_NODES)
