"""6b 그래프 테스트 공통: Fake 시나리오로 에이전트를 끝까지(또는 정해진 턴까지) 돌린다."""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import llm
from agent.agent_nodes import initial_agent_state
from agent.budget import NoopBudget
from agent.graph import build_agent_graph
from agent.timebudget import AgentDeadline, TimeBudget

STORY = "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
FAKE_ENV = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local"}


class Ctx:
    def __init__(self, ms: float = 25_000, *seq: float) -> None:
        self.values = [ms, *seq]
        self.n = 0

    def get_remaining_time_in_millis(self) -> float:
        v = self.values[min(self.n, len(self.values) - 1)]
        self.n += 1
        return v


def caller(scenario: str, budget: Any = None, **env: str) -> llm.LlmCaller:
    e = {**FAKE_ENV, "FAKE_LLM_SCENARIO": scenario, **env}
    return llm.LlmCaller(llm.load_settings(e), env=e, budget=budget if budget is not None else NoopBudget(), agent=True)


def config(c: Any, *, tid: str = "t", run_turn: int = 1, ctx: Any = None, finish: bool = False, ckpt: str | None = None) -> dict[str, Any]:
    conf = {"thread_id": tid, "llm": c, "deadline": AgentDeadline(TimeBudget(ctx or Ctx(), None), None), "run_turn": run_turn,
            "finish_requested": finish}
    if ckpt:
        conf["checkpoint_id"] = ckpt
    return {"configurable": conf}


def run_session(scenario: str, *, answers: dict[str, Any] | None = None, story: str = STORY, max_turns: int = 8,
                saver: Any = None, ctx_factory: Any = None, finish_after: int | None = None) -> dict[str, Any]:
    """질문에는 answers[path](기본 skipped)로, pause에는 continue로 재개해 END까지 돌린다."""
    app = build_agent_graph(saver or InMemorySaver())
    c = caller(scenario)
    turn = 1
    result = asyncio.run(app.ainvoke(initial_agent_state(story), config(c, run_turn=1, ctx=ctx_factory(1) if ctx_factory else None)))
    turns = [result.get("outcome")]
    while "__interrupt__" in result and turn < max_turns:
        turn += 1
        it = result["__interrupt__"][0]
        payload = it.value
        finish = finish_after is not None and turn > finish_after
        if payload.get("kind") == "question":
            ans = dict((answers or {}).get(payload["path"], {"skipped": True}))
            if finish:
                ans = {"skipped": True, "viaFinish": True}
            value = {"questionId": payload["questionId"], "resumeId": f"r{turn - 1}-{payload['questionId']}", **ans}
        else:
            value = "continue"
        result = asyncio.run(app.ainvoke(Command(resume={it.id: value}),
                                         config(c, run_turn=turn, finish=finish, ctx=ctx_factory(turn) if ctx_factory else None)))
        turns.append(result.get("outcome"))
    return {"state": result, "turns": turns, "caller": c, "app": app}
