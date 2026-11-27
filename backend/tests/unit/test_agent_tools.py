"""6b 도구 정의·검증·보고서 (작업 7.6, design §10–§11)."""

import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import invalid_tool_call, tool_call

from agent import agent_tools as at
from agent import tools
from agent.fake_llm import GOOD, NIS_CARD, PRIVATE_CARD

STORY = "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
Q = dict(path="estimatedMinutes", question="얼마나 걸릴까요?", reason="사연에 없어요.", options=["30분", "45분"], allowFreeText=True)


def ask(**over):
    return at.AskPlannerArgs(**(Q | over))


def test_tool_specs_and_filter():
    specs = at.tool_specs()
    assert [s["function"]["name"] for s in specs] == ["check_draft", "ask_planner", "submit_card"]
    assert at.tools_for(questions=0, finish_requested=False, last_call=False) == at.TOOL_NAMES
    for kw in ({"questions": 2, "finish_requested": False, "last_call": False},
               {"questions": 0, "finish_requested": True, "last_call": False},
               {"questions": 0, "finish_requested": False, "last_call": True}):
        assert "ask_planner" not in at.tools_for(**kw)


@pytest.mark.parametrize(("over", "kw", "reason"), [
    ({}, {"questions": 2}, "QUESTION_LIMIT"),
    ({}, {"asked_paths": ["estimatedMinutes"]}, "SAME_PATH"),
    ({"path": "title"}, {}, "PATH_NOT_ALLOWED"),
    ({"path": "places[5].name"}, {}, "PATH_NOT_ALLOWED"),
    ({"question": "가" * 61}, {}, "QUESTION_LENGTH"),
    ({"reason": ""}, {}, "REASON_LENGTH"),
    ({"options": ["a", "b", "c", "d", "e"]}, {}, "OPTIONS"),
    ({"options": ["가" * 16]}, {}, "OPTIONS"),
    ({"options": [], "allowFreeText": False}, {}, "NO_ANSWER_POSSIBLE"),
    ({"question": "010-1234-5678로 연락해도 될까요?"}, {}, "PRIVACY"),
    ({"options": ["101동 1203호"]}, {}, "PRIVACY"),
    ({}, {"finish_requested": True}, "FINISH_REQUESTED"),
    ({}, {}, None),
    ({"path": "places[0].name"}, {}, None),
])
def test_validate_question(over, kw, reason):
    args = dict(asked_paths=[], questions=0, finish_requested=False, card=GOOD) | kw
    assert at.validate_question(ask(**over), **args) == reason


def test_private_place_question_and_answers():
    report = tools.check_draft(PRIVATE_CARD, [STORY])
    q = at.accepted_question(ask(path="places[0].name", options=["빼기", "두기"], allowFreeText=False), number=1, report=report)
    assert q["questionId"] == "q1" and q["options"] == [at.PRIVATE_OPTION] and q["allowFreeText"] is True
    card, note = at.apply_private_place_answer(PRIVATE_CARD, q, {"questionId": "q1", "choice": at.PRIVATE_OPTION})
    assert [p["name"] for p in card["places"]] == ["출근길 빵집"] and note["action"] == "REMOVED" and note["source"] == "ANSWER"
    assert note["reason"] == "계획자가 장소에서 뺐어요."
    card, note = at.apply_private_place_answer(PRIVATE_CARD, q, {"questionId": "q1", "text": "동네 공원"})
    assert card["places"][0]["name"] == "동네 공원" and note["action"] == "REWRITTEN"
    card, note = at.apply_private_place_answer(PRIVATE_CARD, q, {"questionId": "q1", "skipped": True})
    assert card == PRIVATE_CARD and note is None
    card, note = at.apply_private_place_answer(PRIVATE_CARD, q, {"questionId": "q1", "text": "010-1111-2222", "privacy": True})
    assert note is None
    normal = at.accepted_question(ask(), number=2, report=report)
    assert normal["options"] == ["30분", "45분"] and normal["questionId"] == "q2"


def test_answers_and_sources():
    a1 = {"questionId": "q1", "text": "동네 공원"}
    a2 = {"questionId": "q2", "text": "010-1234-5678", "privacy": True}
    a3 = {"questionId": "q3", "skipped": True}
    assert at.answer_has_privacy(a2) and not at.answer_has_privacy(a1)
    assert at.sources_for("사연", [a1, a2, a3]) == ["사연", "동네 공원"]
    q = {"questionId": "q2", "path": "places"}
    withheld = at.answer_for_model(a2, q)
    assert "010" not in withheld and json.loads(withheld)["withheld"] is True
    ok = json.loads(at.answer_for_model(a1, {"questionId": "q1", "path": "places"}))
    assert ok["answer"] == "<answer>\n동네 공원\n</answer>"


def test_report_for_model_has_no_text():
    card = dict(GOOD, summary="010-1234-5678로 연락", places=NIS_CARD["places"])
    text = at.report_for_model(tools.check_draft(card, [STORY]))
    assert "010" not in text and "골목" not in text and "places[0].name" in text and "PHONE" in text


def test_valid_candidate():
    assert at.valid_candidate(GOOD) is not None
    assert at.valid_candidate(at.EMPTY_CARD) is None                       # 정보 없는 카드(BE-Q122)
    assert at.valid_candidate(dict(at.EMPTY_CARD, title="동네 산책")) is not None  # places만 빈 카드는 유효
    assert at.valid_candidate(dict(GOOD, estimatedMinutes=999)) is None
    assert at.valid_candidate("x") is None


def test_split_tool_calls():
    one = AIMessage(content="", tool_calls=[tool_call(name="check_draft", args={"card": GOOD}, id="a")])
    chosen, errs = at.split_tool_calls(one)
    assert chosen["name"] == "check_draft" and errs == []
    many = AIMessage(content="", tool_calls=[tool_call(name="check_draft", args={"card": GOOD}, id="a"),
                                             tool_call(name="submit_card", args={"card": GOOD}, id="b")])
    chosen, errs = at.split_tool_calls(many)
    assert chosen["id"] == "a" and [(e.tool_call_id, json.loads(e.content)["error"]) for e in errs] == [("b", "ONE_TOOL_PER_TURN")]
    bad = AIMessage(content="", invalid_tool_calls=[invalid_tool_call(name="check_draft", args="{bad", id="x", error="e")])
    chosen, errs = at.split_tool_calls(bad)
    assert chosen is None and json.loads(errs[0].content)["error"] == "INVALID_ARGS"
    unknown = AIMessage(content="", tool_calls=[tool_call(name="search_map", args={}, id="u")])
    assert json.loads(at.split_tool_calls(unknown)[1][0].content)["error"] == "UNKNOWN_TOOL"
    schema = AIMessage(content="", tool_calls=[tool_call(name="ask_planner", args={"path": 3}, id="s")])
    assert json.loads(at.split_tool_calls(schema)[1][0].content)["error"] == "INVALID_ARGS"
    assert at.split_tool_calls(AIMessage(content="글만")) == (None, [])


def test_clean_model_notes():
    notes = [{"path": "places[0].name", "action": "REWRITTEN", "reason": "원문으로", "source": "ANSWER"},
             {"path": "places[9].name", "action": "REWRITTEN", "reason": "x"},
             {"path": "title", "action": "REMOVED", "reason": "x"},
             {"path": "summary", "action": "ASKED", "reason": "010-1234-5678"},
             "bad"]
    out = at.clean_model_notes(notes, GOOD, [])
    assert [n["path"] for n in out] == ["places[0].name", "summary"]
    assert out[0]["source"] == "STORY" and out[1]["reason"] == at.SAFE_NOTE_REASON
    card = dict(GOOD, places=[dict(GOOD["places"][0], name="동네 공원")])
    out = at.clean_model_notes([{"path": "places[0].name", "action": "REWRITTEN", "reason": "답"}], card, [{"text": "동네 공원"}])
    assert out[0]["source"] == "ANSWER"
