"""같은 시나리오를 Fake와 실제 ChatOpenAI + 로컬 스텁에서 돌려 분류 코드·그래프 결과를 비교한다 (작업 7.6, Requirement 8.1–8.4, 19.6).

외부 네트워크 없음(127.0.0.1). 스텁 쪽 타임아웃은 hang 모드 + 짧은 호출 상한으로 만든다.
"""

import asyncio
import json

import pytest

from agent import graph as g
from agent import llm
from agent.fake_llm import SCENARIOS
from agent.timebudget import TimeBudget
from tests.unit.llm_stub import LlmStub

KEY = "sk-test-not-a-real-key"
STORY = "이사 전에 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했어요."


class Ctx:
    def get_remaining_time_in_millis(self):
        return 25_000


def run_graph(caller):
    config = {"configurable": {"llm": caller, "deadline": TimeBudget(Ctx(), None), "finish_requested": False}}
    return asyncio.run(g.pipeline_graph().ainvoke(g.initial_state(STORY), config=config))


def fake_result(scenario):
    env = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local", "FAKE_LLM_SCENARIO": scenario}
    return run_graph(llm.LlmCaller(llm.load_settings(env), env=env))


def stub_result(stub, **env):
    e = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": stub.url, "LLM_MODEL": "stub-model", "LLM_API_KEY": KEY, **env}
    return run_graph(llm.LlmCaller(llm.load_settings(e), env=e))


def summary(state):
    return {"outcome": g.decide_outcome(state), "llm_error": state.get("llm_error"), "model_calls": state["model_calls"],
            "invalid_kinds": state["invalid_kinds"], "tools": [t["tool"] for t in state["trace"]]}


def contents(scenario):
    return [s["text"] for s in SCENARIOS[scenario]]


@pytest.mark.parametrize("scenario", ["happy", "bad_json", "schema_error"])
def test_content_scenarios_match(scenario):
    with LlmStub() as stub:
        stub.content = contents(scenario)
        assert summary(stub_result(stub)) == summary(fake_result(scenario))
        assert len(stub.requests) == fake_result(scenario)["model_calls"]


@pytest.mark.parametrize(("scenario", "code"), [("http_400", 400), ("http_401", 401), ("http_429", 429), ("http_500", 500)])
def test_status_scenarios_match(scenario, code):
    with LlmStub() as stub:
        stub.mode = f"status:{code}"
        s = summary(stub_result(stub))
        assert s == summary(fake_result(scenario))
        assert s["outcome"] == ("FAILED", 503, "LLM_ERROR") and len(stub.requests) == 1


def test_timeout_matches():
    with LlmStub() as stub:
        stub.mode = "hang"
        s = summary(stub_result(stub, LLM_CONNECT_TIMEOUT_S="0.1", LLM_READ_TIMEOUT_S="0.3"))
    assert s == summary(fake_result("timeout")) and s["llm_error"] == "TIMEOUT"


def test_stub_card_is_same_json():
    with LlmStub() as stub:
        stub.content = contents("happy")
        a = stub_result(stub)["final_card"]
    b = fake_result("happy")["final_card"]
    assert a == b and json.loads(contents("happy")[0])["title"] == a["title"]
