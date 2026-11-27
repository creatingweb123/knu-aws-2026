"""레벨 0 그래프 (작업 8.2, Requirement 9.1–9.7, 19.1). Fake 시나리오와 가짜 Lambda context로 돌린다. 외부 호출 없음."""

import ast
import asyncio
import pathlib
import time

import pytest

from agent import graph as g
from agent import llm
from agent.state import INVALID_OUTPUT, LLM_ERROR
from agent.timebudget import TimeBudget

STORY = "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
FAKE_ENV = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local"}
SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


class Ctx:
    """get_remaining_time_in_millis가 호출마다 정해진 값을 차례로 돌려준다(마지막 값 유지)."""

    def __init__(self, *values):
        self.values = list(values)
        self.n = 0

    def get_remaining_time_in_millis(self):
        v = self.values[min(self.n, len(self.values) - 1)]
        self.n += 1
        return v


class Clock:
    """실제로 흘러간 시간만큼 줄어드는 Lambda 남은 시간."""

    def __init__(self, start_ms):
        self.start_ms, self.t0 = start_ms, time.monotonic()

    def get_remaining_time_in_millis(self):
        return self.start_ms - (time.monotonic() - self.t0) * 1000


def caller(scenario, **env):
    e = {**FAKE_ENV, "FAKE_LLM_SCENARIO": scenario, **env}
    return llm.LlmCaller(llm.load_settings(e), env=e)


def run(scenario, ctx=None, c=None, story=STORY):
    c = c or caller(scenario)
    budget = TimeBudget(ctx or Ctx(25_000), None)
    state = asyncio.run(g.pipeline_graph().ainvoke(g.initial_state(story), config={"configurable": {"llm": c, "deadline": budget, "finish_requested": False}}))
    return state, c


def tools_of(state):
    return [t["tool"] for t in state["trace"]]


def test_happy():
    s, c = run("happy")
    assert g.decide_outcome(s) == ("READY", 200, None)
    assert s["model_calls"] == 1 == len(c.fake.calls) and s["attempts"] == 1
    assert s["degraded"] is False and s["blocked"] == [] and s["notes"] == []
    assert s["final_card"]["places"][0]["name"] == "출근길 빵집" and "_src" not in s["final_card"]["places"][0]
    assert tools_of(s) == ["draft", "check_draft", "submit_card"]
    assert s["first_proposal"] == s["final_card"] and s["first_report"]["notInSource"] == []
    assert s["token_in"] > 0 and s["token_estimated"] is False


def test_not_in_source_goes_to_fallback():
    s, _ = run("not_in_source")
    assert g.decide_outcome(s)[0] == "READY" and s["degraded"] is True
    assert [p["name"] for p in s["final_card"]["places"]] == ["하천 벤치"]
    assert {"path": "places[0].name", "action": "REMOVED", "reason": "사연에 없는 장소라 뺐어요."}.items() <= s["notes"][0].items()
    assert tools_of(s) == ["draft", "check_draft", "submit_card", "fallback"]
    assert "places[0].name" in s["first_report"]["notInSource"]  # 첫 보고서는 Candidate 기준
    assert [p["name"] for p in s["first_proposal"]["places"]] == ["골목 빵집", "하천 벤치"]


def test_privacy_high_masked():
    s, _ = run("privacy_high")
    assert g.decide_outcome(s)[0] == "READY" and s["degraded"] is True
    assert "010-1234-5678" not in s["final_card"]["summary"] and "1203호" not in s["final_card"]["summary"]
    assert any(f["path"] == "summary" and f["type"] == "PRIVACY" for f in s["flags"])
    trace = " ".join(t["summary"] for t in s["trace"])
    assert "010" not in trace and "연락처" in trace


def test_private_place_rules_node():
    s, _ = run("private_place")
    assert tools_of(s)[:4] == ["draft", "check_draft", "rules", "submit_card"]
    assert [p["name"] for p in s["final_card"]["places"]] == ["출근길 빵집"]
    assert s["notes"][0]["path"] == "places[0].name" and s["notes"][0]["action"] == "REMOVED"
    assert "민지" not in " ".join(t["summary"] for t in s["trace"])


def test_missing_kept_as_flags():
    s, _ = run("missing")
    assert g.decide_outcome(s)[0] == "READY" and s["degraded"] is False
    assert {(f["path"], f["type"]) for f in s["flags"]} >= {("estimatedMinutes", "MISSING"), ("question", "MISSING")}


def test_all_places_removed():
    s, _ = run("all_places_removed")
    assert g.decide_outcome(s)[0] == "READY" and s["final_card"]["places"] == []
    assert {"path": "places", "type": "MISSING"} in s["flags"]


@pytest.mark.parametrize(("scenario", "calls", "kinds"), [("bad_json", 2, ["NOT_JSON", "NOT_JSON"]), ("schema_error", 2, ["SCHEMA", "SCHEMA"])])
def test_invalid_twice_is_502(scenario, calls, kinds):
    s, c = run(scenario)
    assert g.decide_outcome(s) == ("FAILED", 502, "INVALID_OUTPUT")
    assert s["model_calls"] == calls == len(c.fake.calls) and s["invalid_kinds"] == kinds and s["last_failure"] == INVALID_OUTPUT
    assert s["candidate"] is None and s["first_report"] is None and tools_of(s) == ["draft", "draft"]


@pytest.mark.parametrize("scenario", ["bad_json_then_ok", "schema_error_then_ok"])
def test_invalid_then_ok(scenario):
    s, c = run(scenario)
    assert g.decide_outcome(s)[0] == "READY" and s["model_calls"] == 2 and s["attempts"] == 2
    retry = c.fake.calls[1]["messages"]
    assert len(retry) == 3 and "카드를 만들 수 없어요" not in retry[2][1] and "300" not in retry[2][1]  # 실패 원문 미포함


@pytest.mark.parametrize(("scenario", "code"), [("timeout", "TIMEOUT"), ("connection", "CONNECTION"), ("http_400", "HTTP_400"),
                                                ("http_401", "HTTP_401"), ("http_429", "HTTP_429"), ("http_500", "HTTP_5XX")])
def test_llm_error_no_retry(scenario, code):
    s, c = run(scenario)
    assert g.decide_outcome(s) == ("FAILED", 503, "LLM_ERROR")
    assert s["llm_error"] == code and s["last_failure"] == LLM_ERROR and s["model_calls"] == 1 == len(c.fake.calls)


def test_no_retry_under_12s():
    s, c = run("bad_json", ctx=Ctx(20_000, 20_000, 11_999))  # 시도 1: 확인·deadline, 시도 2: 확인
    assert g.decide_outcome(s) == ("FAILED", 502, "INVALID_OUTPUT") and len(c.fake.calls) == 1 and s["model_calls"] == 1


def test_time_budget_before_first_call():
    s, c = run("happy", ctx=Ctx(11_999))
    assert g.decide_outcome(s) == ("FAILED", 503, "LLM_ERROR") and s["llm_error"] == llm.TIME_BUDGET
    assert s["model_calls"] == 0 and c.fake.calls == [] and s["trace"] == []


def test_slow_cut_by_deadline():
    c = caller("slow", LLM_CONNECT_TIMEOUT_S="0.1", LLM_READ_TIMEOUT_S="0.2")
    t = time.monotonic()
    s, _ = run("slow", ctx=Clock(25_000), c=c)
    assert time.monotonic() - t < 2.0
    assert s["llm_error"] == "TIMEOUT" and s["model_calls"] == 1 and g.decide_outcome(s)[1] == 503


def test_deadline_uses_save_reserve():
    seen = []
    c = caller("happy")
    orig = c.ainvoke

    async def spy(messages, deadline_s):
        seen.append(deadline_s)
        return await orig(messages, deadline_s)

    c.ainvoke = spy
    run("happy", ctx=Ctx(13_000), c=c)
    assert seen and seen[0] == pytest.approx(9.0)  # min(10, (13 − 4))


def test_config_error_is_llm_error():
    s, c = run("happy", c=caller("nope"))
    assert s["llm_error"] == llm.CONFIG and s["model_calls"] == 0 and g.decide_outcome(s)[1] == 503


def test_compiled_without_checkpointer():
    graph = g.build_pipeline_graph()
    assert graph.checkpointer is None
    assert set(graph.get_graph().nodes) >= {"draft", "check_draft", "rules", "gate", "fallback", "final_check"}
    assert g.pipeline_graph() is g.pipeline_graph()


def test_no_prebuilt_import():
    for path in (SRC / "agent").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any("prebuilt" in n for n in names), path.name


def test_blocked_final_check_is_502(monkeypatch):
    from agent import nodes

    monkeypatch.setattr(nodes.tools, "final_check", lambda *a, **k: ([], ["SCHEMA"]))
    s, _ = run("happy")
    assert s["final_card"] is None and g.decide_outcome(s) == ("FAILED", 502, "FALLBACK_INVARIANT")


# ---------------------------------------------------------------- 산책이 아닌 활동(대표 활용 사례 밖)
# 시나리오 이름과 짝인 사연은 tests/fixtures/stories.json의 nonwalk_* 이다. Fake는 사연을 읽지 않는다.

NONWALK = [("exhibition", "nonwalk_exhibition", "일정이 바뀌어"), ("cafe", "nonwalk_cafe", "감기"),
           ("bookstore", "nonwalk_bookstore", "회사 일"), ("park_photo", "nonwalk_park_photo", "비가 와서")]
WALK_WORDS = ("산책", "걷", "도보", "경로", "동선")


def card_text(card):
    return " ".join(str(v) for k, v in card.items() if k != "places" and v) + " " + " ".join(
        str(v) for p in card["places"] for v in p.values() if v)


@pytest.mark.parametrize(("scenario", "sid", "reason_word"), NONWALK)
def test_nonwalk_story_stays_its_own_activity(scenario, sid, reason_word):
    """전시회·카페·서점·공원 사진 사연은 산책 카드로 바뀌지 않고, 장소 한 곳이어도 정상이며 이유가 남는다."""
    from tests.fixtures.stories import story as fixture_story

    story = fixture_story(sid)["story"]
    s, _ = run(scenario, story=story)
    assert g.decide_outcome(s)[0] == "READY" and s["degraded"] is False and s["blocked"] == [] and s["notes"] == []
    card = s["final_card"]
    assert len(card["places"]) == 1 and card["places"][0]["name"] in story
    assert s["first_report"]["notInSource"] == []
    assert reason_word in story and reason_word in card["reason"]
    blob = card_text(card)
    for w in WALK_WORDS:
        assert w in story or w not in blob, w
    assert not any(f["type"] == "NOT_IN_SOURCE" for f in s["flags"])


def test_nonwalk_extra_nearby_place_is_not_in_source():
    """사연에 없는 주변 장소(공원·산책)를 덧붙이면 NOT_IN_SOURCE로 걸려 빠진다. 원래 계획 장소는 남는다."""
    from tests.fixtures.stories import story as fixture_story

    s, _ = run("exhibition_extra_place", story=fixture_story("nonwalk_exhibition")["story"])
    assert g.decide_outcome(s)[0] == "READY" and s["degraded"] is True
    assert "places[1].name" in s["first_report"]["notInSource"]
    assert [p["name"] for p in s["final_card"]["places"]] == ["시립미술관"]
    assert s["notes"][0]["action"] == "REMOVED" and s["notes"][0]["reason"] == "사연에 없는 장소라 뺐어요."


def test_private_place_note_has_no_route_wording():
    from agent import repair

    assert repair.REASON_PRIVATE == "비공개 장소라 뺐어요."
    s, _ = run("private_place")
    assert s["notes"][0]["reason"] == repair.REASON_PRIVATE and "동선" not in repair.REASON_PRIVATE

