"""Fake 도구 호출 시나리오 형태와 스텁 왕복(실제 ChatOpenAI + bind_tools) (작업 5.3, Req 19·20.6).

스텁은 127.0.0.1에서만 듣는다. 키는 가짜 값이다.
"""

import asyncio
import json

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from agent import llm
from agent.agent_tools import TOOL_NAMES, split_tool_calls, tool_specs
from agent.budget import NoopBudget
from agent.fake_llm import AGENT_SCENARIOS, SCENARIOS, FakeScenarioChatModel
from tests.unit.llm_stub import LlmStub, tool_message

KEY = "sk-test-not-a-real-key"
CARD = {"title": "t", "summary": None, "reason": None, "estimatedMinutes": 45, "places": [], "question": None}
MSGS = [SystemMessage("시스템"), HumanMessage("<story>출근길 빵집</story>")]


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("name", sorted(AGENT_SCENARIOS))
def test_agent_scenario_step_shapes(name):
    steps = AGENT_SCENARIOS[name]
    assert steps and steps[0]["kind"] in ("content", "raise")  # 첫 단계는 도구 없는 draft
    for s in steps:
        assert s["kind"] in ("content", "tool", "invalid", "raise")
        if s["kind"] == "tool":
            assert s["calls"] and all(set(c) >= {"name", "args"} and isinstance(c["args"], dict) for c in s["calls"])
        if s["kind"] == "invalid":
            with pytest.raises(json.JSONDecodeError):
                json.loads(s["raw"])


@pytest.mark.parametrize("name", sorted(AGENT_SCENARIOS))
def test_agent_scenario_messages_parse(name):
    """각 단계가 AIMessage로 만들어지고(오류 단계는 openai 예외), 도구 이름 기록이 남는다."""
    import openai

    fake = FakeScenarioChatModel.for_scenario(name, agent=True)
    bound = fake.bind_tools(tool_specs())
    for i, s in enumerate(AGENT_SCENARIOS[name]):
        if s["kind"] == "raise":
            with pytest.raises((openai.APIError, openai.APITimeoutError)):
                run(bound.ainvoke(MSGS))
            continue
        msg = run(bound.ainvoke(MSGS))
        if s["kind"] == "tool":
            assert [c["name"] for c in msg.tool_calls] == [c["name"] for c in s["calls"]]
            assert len({c["id"] for c in msg.tool_calls}) == len(msg.tool_calls)
        elif s["kind"] == "invalid":
            assert msg.invalid_tool_calls and not msg.tool_calls
        else:
            assert isinstance(msg.content, str) and not msg.tool_calls
        assert fake.calls[i]["tools"] == list(TOOL_NAMES) and fake.calls[i]["index"] == i


def test_6a_scenarios_unchanged_have_no_tool_steps():
    assert all(s["kind"] in ("content", "raise") for steps in SCENARIOS.values() for s in steps)


def test_for_scenario_unknown():
    with pytest.raises(ValueError):
        FakeScenarioChatModel.for_scenario("nope", agent=True)


# ---- 스텁 왕복 ----

@pytest.fixture
def stub():
    with LlmStub() as s:
        assert s.url.startswith("http://127.0.0.1:")
        yield s


def caller(stub, **env):
    e = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": stub.url, "LLM_MODEL": "stub-model", "LLM_API_KEY": KEY, **env}
    return llm.LlmCaller(llm.load_settings(e), env=e, budget=NoopBudget(6, 30000), agent=True)


def call(stub, **env):
    return run(caller(stub, **env).ainvoke(MSGS, 5.0, tools=tool_specs()))


def test_single_tool_call_round_trip(stub):
    stub.messages = [tool_message(("submit_card", {"card": CARD, "notes": []}))]
    msg = call(stub, LLM_PARALLEL_TOOL_CALLS="false", LLM_TOOL_CHOICE="")
    body = stub.requests[-1]["body"]
    assert [t["function"]["name"] for t in body["tools"]] == list(TOOL_NAMES)
    assert body["parallel_tool_calls"] is False and "tool_choice" not in body
    assert msg.tool_calls[0]["name"] == "submit_card" and msg.tool_calls[0]["args"]["card"] == CARD
    run_call, errors = split_tool_calls(msg)
    assert run_call["name"] == "submit_card" and errors == []


def test_parallel_flag_omitted_and_tool_choice_sent(stub):
    stub.messages = [tool_message(("check_draft", {"card": CARD}))]
    call(stub, LLM_PARALLEL_TOOL_CALLS="", LLM_TOOL_CHOICE="auto")
    body = stub.requests[-1]["body"]
    assert "parallel_tool_calls" not in body and body["tool_choice"] == "auto"


def test_multiple_tool_calls_round_trip(stub):
    stub.messages = [tool_message(("check_draft", {"card": CARD}), ("submit_card", {"card": CARD}))]
    msg = call(stub)
    run_call, errors = split_tool_calls(msg)
    assert [c["name"] for c in msg.tool_calls] == ["check_draft", "submit_card"]
    assert run_call["name"] == "check_draft" and len(errors) == 1 and "ONE_TOOL_PER_TURN" in errors[0].content
    assert errors[0].tool_call_id == msg.tool_calls[1]["id"]


def test_invalid_json_args_round_trip(stub):
    stub.messages = [tool_message(("check_draft", '{"card": {'))]
    msg = call(stub)
    assert not msg.tool_calls and msg.invalid_tool_calls and msg.invalid_tool_calls[0]["name"] == "check_draft"
    run_call, errors = split_tool_calls(msg)
    assert run_call is None and len(errors) == 1 and errors[0].tool_call_id == msg.invalid_tool_calls[0]["id"]


def test_text_only_round_trip(stub):
    stub.messages = [{"content": "정리를 마쳤어요."}]
    msg = call(stub)
    assert msg.content == "정리를 마쳤어요." and not msg.tool_calls and not msg.invalid_tool_calls
    assert split_tool_calls(msg) == (None, [])
