"""초안 재시도 (BE-Q129, 2026-11-27 보완). 스키마 위반과 JSON 오류가 같은 예산(초안 2회)을 쓰고, 재시도 상태는 체크포인트에 남는다.

- 재시도 메시지는 위반 경로와 스키마 제한만 담고, 실패한 응답 원문을 다시 보내지 않는다.
- 정보 없는 카드(스키마는 맞음)는 위반이 아니므로 재시도하지 않는다(BE-Q122).
- 시간 부족·강제 종료·체크포인트 복구에서 초안 시도 수가 초기화되지 않는다. 잃은 호출은 예약에 남고(환불 없음), 복구 때
  Fake는 같은 호출 순번의 응답을 돌려준다(P45와 같은 규칙).
"""

from __future__ import annotations

import asyncio
import itertools
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import agent_nodes, hooks, llm
from agent import graph as g
from agent.agent_nodes import MAX_DRAFTS, initial_agent_state
from agent.budget import NoopBudget
from agent.fake_llm import GOOD, SUBMIT_NOTE, FakeScenarioChatModel, _card, _content, _raise, _tool
from agent.prompt import agent_draft_messages, agent_prompt_version, agent_retry_text, agent_system_prompt, schema_limit
from tests.unit.agent_util import FAKE_ENV, STORY, config, run_session

BAD_TITLE = _card(title="가" * 41)  # 제목 1–40자 위반
JSON_BAD = "JSON 객체가 아니에요."
DRAFT_VALID = _card(estimatedMinutes=45)
SUBMIT = _tool("submit_card", card=GOOD, notes=SUBMIT_NOTE)
KIND_STEP = {"valid": lambda: _content(DRAFT_VALID), "schema": lambda: _content(BAD_TITLE), "json": lambda: _content(JSON_BAD)}
KIND_LABEL = {"schema": "SCHEMA", "json": "NOT_JSON"}


def tool_names(state):
    return [t["tool"] for t in state["trace"]]


def drafts_of(state):
    return state["budget"]["drafts"]


def make_caller(steps, budget=None):
    fake = FakeScenarioChatModel(scenario="custom", steps=steps)
    settings = llm.load_settings({**FAKE_ENV, "FAKE_LLM_SCENARIO": "happy"})
    bud = budget or NoopBudget()
    c = llm.LlmCaller(settings, fake=fake, env={**FAKE_ENV}, budget=bud, agent=True)
    c.test_budget = bud  # 예약 수 확인용
    return c, fake


def run_custom(steps):
    c, fake = make_caller(steps)
    app = g.build_agent_graph(InMemorySaver())
    r = asyncio.run(app.ainvoke(initial_agent_state(STORY), config(c)))
    return r, c, fake


# ---------------------------------------------------------------- 상수, 재시도 메시지, 프롬프트


def test_budget_constants():
    assert MAX_DRAFTS == 2 and "drafts" in agent_nodes.BUDGET_KEYS


@pytest.mark.parametrize(("path", "limit"), [("title", "1–40자"), ("places[0].name", "1–30자"), ("places[2].activity", "1–60자"),
                                             ("estimatedMinutes", "10–240 사이의 정수"), ("places", "최대 3곳"), ("body", "형식 규칙")])
def test_schema_limit_text(path, limit):
    assert schema_limit(path) == limit


def test_retry_text_has_paths_and_limits_only():
    text = agent_retry_text("SCHEMA", ("title", "places[0].name"))
    assert "title(1–40자)" in text and "places[0].name(1–30자)" in text and "가" * 41 not in text
    assert agent_retry_text("NOT_JSON", ()) == "앞 응답이 JSON 객체가 아니었다. 설명 없이 JSON 객체 하나만 다시 출력하라."


def test_feedback_follows_the_story_and_no_answer_is_replayed():
    assert [m.type for m in agent_draft_messages("사연", feedback="재시도 메시지")] == ["system", "human", "human"]
    assert [m.type for m in agent_draft_messages("사연")] == ["system", "human"]


def test_prompt_rule_and_version():
    text = agent_system_prompt()
    assert "스키마 위반은 계획자에게 질문할 문제가 아니다" in text and "배열 개수 위반은 직접 수정한다" in text
    assert agent_prompt_version() == "3db437c63971"


def test_retry_text_is_only_in_the_agent_path():
    """레벨 0(day_card.md, 6a retry_message)에는 이 재시도 문구가 없다."""
    from agent import prompt as p

    assert "앞 초안의 형식 규칙 위반" not in p.system_prompt()
    assert "앞 초안의 형식 규칙 위반" not in p.retry_message("SCHEMA", ("title",)).content


# ---------------------------------------------------------------- 두 초안 응답의 모든 조합 (초안 2회, 한 예산)


@pytest.mark.parametrize(("first", "second"), list(itertools.product(["valid", "schema", "json"], repeat=2)))
def test_every_pair_of_draft_outputs(first, second):
    steps = [KIND_STEP[first]()] + ([KIND_STEP[second]()] if first != "valid" else []) + [SUBMIT]
    r, c, _ = run_custom(steps)
    expected = 1 if first == "valid" else 2
    assert drafts_of(r) == expected, (first, second)
    names = tool_names(r)
    assert names.count("draft") == expected and names[:expected] == ["draft"] * expected
    viol = [k for k in (first, second)[:expected] if k != "valid"]
    assert r["invalid_kinds"] == [KIND_LABEL[k] for k in viol]
    assert r["outcome"] == "READY" and c.calls_made <= 6


def test_schema_then_valid_uses_valid_draft_for_first_proposal():
    r, _, fake = run_custom([_content(BAD_TITLE), _content(DRAFT_VALID), SUBMIT])
    assert drafts_of(r) == 2 and r["invalid_kinds"] == ["SCHEMA"]
    assert r["first_report"]["schemaErrors"] == []  # check_draft는 재시도 뒤 초안을 처음 본다
    assert r["first_proposal"]["estimatedMinutes"] == 45 and r["outcome"] == "READY"
    assert r["budget"]["modelCalls"] == 3 and fake.index == 3


def test_json_then_schema_reports_the_schema_of_the_last_object():
    r, _, _ = run_custom([_content(JSON_BAD), _content(BAD_TITLE), SUBMIT])
    assert drafts_of(r) == 2 and r["invalid_kinds"] == ["NOT_JSON", "SCHEMA"]
    assert r["first_report"]["schemaErrors"] == ["title"] and r["outcome"] == "READY"


def test_schema_then_json_keeps_the_last_parsed_card():
    r, _, _ = run_custom([_content(BAD_TITLE), _content(JSON_BAD), SUBMIT])
    assert drafts_of(r) == 2 and r["invalid_kinds"] == ["SCHEMA", "NOT_JSON"]
    assert r["first_report"]["schemaErrors"] == ["title"]  # 두 번째 JSON 실패가 첫 파싱 카드를 지우지 않는다


def test_schema_twice_goes_to_check_as_before():
    r, _, _ = run_custom([_content(BAD_TITLE), _content(_card(estimatedMinutes=300)), SUBMIT])
    assert drafts_of(r) == 2 and r["invalid_kinds"] == ["SCHEMA", "SCHEMA"]
    assert r["first_report"]["schemaErrors"] == ["estimatedMinutes"] and r["outcome"] == "READY"


def test_info_less_card_is_not_retried():
    """모든 값 null, places 0은 스키마를 통과한다. 위반이 아니므로 재시도하지 않는다(BE-Q122)."""
    empty = json.dumps({"title": None, "summary": None, "reason": None, "estimatedMinutes": None, "places": [], "question": None})
    r, _, _ = run_custom([_content(empty), SUBMIT])
    assert drafts_of(r) == 1 and r["invalid_kinds"] == []


def test_two_violations_then_failed_call_has_no_candidate():
    r, _, _ = run_custom([_content(BAD_TITLE), _content(BAD_TITLE), _raise("http_500")])
    assert drafts_of(r) == 2 and r["outcome"] == "FAILED" and r["llm_error"] == "HTTP_5XX"


# ---------------------------------------------------------------- 재시도 메시지: 실패한 응답을 다시 보내지 않는다


def test_retry_message_does_not_resend_the_failed_answer():
    marker = "RESEND_MARKER_9731"
    failed = json.dumps({"title": "가" * 41, "summary": marker + " 요약", "reason": None, "estimatedMinutes": 45, "places": [],
                         "question": None}, ensure_ascii=False)
    _, _, fake = run_custom([_content(failed), _content(DRAFT_VALID), SUBMIT])
    first_call, second_call = fake.calls[0]["messages"], fake.calls[1]["messages"]
    assert len(first_call) == 2
    assert [t for t, _ in second_call] == ["system", "human", "human"]  # 실패한 AI 응답은 붙지 않는다
    retry = second_call[-1][1]
    assert "title(1–40자)" in retry and marker not in retry and "가" * 41 not in retry
    assert all(marker not in str(c) for _, c in second_call)


# ---------------------------------------------------------------- 시간 부족: 재시도 전 pause, 재개 뒤 같은 시도 수


def test_time_short_before_retry_pauses_and_resume_continues_without_a_third_draft():
    fake = FakeScenarioChatModel(scenario="custom", steps=[_content(BAD_TITLE), _content(DRAFT_VALID), SUBMIT])

    class Clock:
        ms = 25_000

        def get_remaining_time_in_millis(self):
            return self.ms

    clock = Clock()
    settings = llm.load_settings({**FAKE_ENV, "FAKE_LLM_SCENARIO": "happy"})
    c = llm.LlmCaller(settings, fake=fake, env={**FAKE_ENV}, budget=NoopBudget(), agent=True)
    real = c.ainvoke

    shortened = {"done": False}

    async def first_call_then_short(messages, deadline_s, **kw):
        out = await real(messages, deadline_s, **kw)
        if not shortened["done"]:  # 첫 초안 뒤 한 번만 12초 미만: guard_draft가 재시도 전에 pause한다
            shortened["done"] = True
            clock.ms = 5_000
        return out

    c.ainvoke = first_call_then_short
    app = g.build_agent_graph(InMemorySaver())
    r = asyncio.run(app.ainvoke(initial_agent_state(STORY), config(c, ctx=clock)))
    assert r["outcome"] == "WORKING" and r["resume_to"] == "draft" and fake.index == 1
    assert r["budget"]["drafts"] == 1
    clock.ms = 25_000
    r2 = asyncio.run(app.ainvoke(Command(resume={r["__interrupt__"][0].id: "continue"}), config(c, run_turn=2, ctx=clock)))
    assert r2["outcome"] == "READY" and drafts_of(r2) == 2 and r2["invalid_kinds"] == ["SCHEMA"]
    assert r2["budget"]["modelCalls"] == 3 and fake.index == 3  # 초안 2회 + 제출 1회, 세 번째 초안은 없다


# ---------------------------------------------------------------- 강제 종료와 체크포인트 복구


class Crash(BaseException):
    pass


def crash_on_response(n: int):
    seen = {"n": 0}

    def hook(point):
        if point == "model_response":
            seen["n"] += 1
            if seen["n"] == n:
                raise Crash()
    return hook


def crash_then_resume(steps, crash_n: int):
    """crash_n번째 모델 응답 뒤 강제 종료하고 같은 스레드에서 이어 실행한다. (최종 상태, Fake, 예약 수)를 돌려준다."""
    c, fake = make_caller(steps)
    app = g.build_agent_graph(InMemorySaver())
    hooks.HOOK = crash_on_response(crash_n)
    try:
        with pytest.raises(Crash):
            asyncio.run(app.ainvoke(initial_agent_state(STORY), config(c, tid="t1")))
    finally:
        hooks.HOOK = None
    r = asyncio.run(app.ainvoke(None, config(c, tid="t1", run_turn=2)))
    return r, fake, c.test_budget.reserved


def test_crash_after_first_draft_response_redoes_only_that_attempt():
    """첫 응답 뒤 종료: 체크포인트에 초안 시도가 없으니 첫 시도를 다시 한다. 응답은 같은 순번에서 같다."""
    r, fake, reserved = crash_then_resume([_content(BAD_TITLE), _content(DRAFT_VALID), SUBMIT], crash_n=1)
    assert drafts_of(r) == 2 and r["outcome"] == "READY" and r["invalid_kinds"] == ["SCHEMA"]
    assert [c["index"] for c in fake.calls][:2] == [0, 0]  # 잃은 첫 시도가 다시 나갔다
    assert reserved <= 6


def test_crash_after_second_draft_response_does_not_repeat_the_first_attempt():
    """첫 시도가 체크포인트에 남은 뒤 두 번째 응답에서 종료: 첫 시도(순번 0)는 다시 나가지 않는다. 세 번째 초안은 없다."""
    r, fake, reserved = crash_then_resume([_content(BAD_TITLE), _content(DRAFT_VALID), SUBMIT], crash_n=2)
    assert drafts_of(r) == 2 and r["outcome"] == "READY" and r["invalid_kinds"] == ["SCHEMA"]
    indexes = [c["index"] for c in fake.calls]
    assert indexes.count(0) == 1  # 첫 시도는 체크포인트에서 이어져서 한 번만 나갔다
    assert indexes.count(1) == 2  # 두 번째 시도: 잃은 응답 1 + 다시 한 응답 1
    assert reserved <= 6


def test_repeated_crashes_keep_logical_draft_count_and_ceiling():
    """응답 두 번이 연속으로 강제 종료돼도 논리 초안 수는 2를 넘지 않고 예약은 6 이하다."""
    c, fake = make_caller([_content(BAD_TITLE), _content(DRAFT_VALID), SUBMIT])
    app = g.build_agent_graph(InMemorySaver())
    left = {"n": 2}

    def hook(point):
        if point == "model_response" and left["n"] > 0:
            left["n"] -= 1
            raise Crash()

    hooks.HOOK = hook
    inp = initial_agent_state(STORY)
    r = None
    try:
        for _ in range(5):
            try:
                r = asyncio.run(app.ainvoke(inp, config(c, tid="t2", run_turn=2)))
                break
            except Crash:
                inp = None  # 같은 스레드의 마지막 체크포인트에서 이어간다
    finally:
        hooks.HOOK = None
    assert r is not None and r["outcome"] == "READY"
    assert drafts_of(r) <= MAX_DRAFTS and c.test_budget.reserved <= 6
    assert len(r["invalid_kinds"]) <= MAX_DRAFTS


# ---------------------------------------------------------------- 이름 있는 시나리오 회귀


@pytest.mark.parametrize(("scenario", "drafts", "invalid"), [
    ("happy", 1, []), ("ask_once", 1, []), ("schema_then_ok", 2, ["SCHEMA"]), ("json_then_schema", 2, ["NOT_JSON", "SCHEMA"]),
    ("schema_then_json", 2, ["SCHEMA", "NOT_JSON"]), ("schema_twice", 2, ["SCHEMA", "SCHEMA"]), ("empty_info_card", 1, []),
])
def test_named_scenarios(scenario, drafts, invalid):
    s = run_session(scenario)["state"]
    assert drafts_of(s) == drafts and s["invalid_kinds"] == invalid
    assert s["outcome"] == "READY" and s["budget"]["modelCalls"] <= 6
