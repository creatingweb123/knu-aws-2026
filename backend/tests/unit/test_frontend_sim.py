"""프론트 모형으로 본 docs/03 S4 흐름 (작업 10.9, BE-Q121). moto + Fake + moto 체크포인터."""

import pytest

from agent import hooks
from domain import ai_session_service as svc
from tests.unit.agent_handler_util import STORY, agent_env, create, get, session, turns  # noqa: F401
from tests.unit.agent_util import Ctx
from tests.unit.frontend_sim import FrontendSim, handler_transport


class Crash(BaseException):
    pass


def expire(table, sid):
    if sid:
        table.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockedUntil = :p", ExpressionAttributeValues={":p": 1})


def sim(table, *, create_fn=create, turns_fn=turns, sleep=None, **kw):
    t = handler_transport(create_fn, turns_fn, get, on_crash=lambda sid: expire(table, sid), crash_types=(Crash,))
    return FrontendSim(**t, sleep=sleep or (lambda s: None), **kw)


def test_happy_one_request(agent_env):
    r = sim(agent_env).run(STORY)
    assert r.outcome == "READY" and r.request_count == 1


def test_ask_once_answers_first_option(agent_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    r = sim(agent_env).run(STORY)
    assert r.outcome == "READY" and [x[0] for x in r.requests] == ["create", "turns"]
    assert r.sent[0]["answer"] == {"questionId": "q1", "choice": "30분"}


def test_working_auto_continue(agent_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "slow_agent")
    r = sim(agent_env, create_fn=lambda story: create(story, ctx=Ctx(25_000, 25_000, 25_000, 25_000, 25_000, 11_000))).run(STORY)
    assert r.outcome == "READY" and r.sent == [{"expectedTurn": 1}]


def test_two_working_in_row_then_finish(agent_env, monkeypatch):
    """연속 2회 WORKING 뒤 finish: true, 그 뒤로도 finish: true."""
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_twice")
    short = {"n": 0}

    def short_turns(sid, body):
        short["n"] += 1
        ctx = Ctx(11_000) if short["n"] <= 1 else Ctx()
        return turns(sid, body, ctx=ctx)

    r = sim(agent_env, create_fn=lambda story: create(story, ctx=Ctx(25_000, 25_000, 25_000, 25_000, 25_000, 11_000)),
            turns_fn=short_turns).run(STORY)
    assert r.outcome == "READY"
    labels = [x[2] for x in r.requests]
    assert labels[:2] == ["WORKING", "WORKING"] and r.sent[1].get("finish") is True
    assert all(b.get("finish") for b in r.sent[1:])


def test_busy_waits_then_get(agent_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    state = {"sid": None, "once": True}

    def busy_turns(sid, body):
        state["sid"] = sid
        if state["once"]:
            state["once"] = False
            agent_env.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockToken = :t, lockedUntil = :u",
                                  ExpressionAttributeValues={":t": "other", ":u": svc.now_ms() + 20_000})
        return turns(sid, body)

    r = sim(agent_env, turns_fn=busy_turns, sleep=lambda s: expire(agent_env, state["sid"])).run(STORY)
    assert r.outcome == "READY" and r.waits_s == 2.0
    assert [x[2] for x in r.requests] == ["ASKING", "AI_SESSION_BUSY", "ASKING", "READY"]
    assert len(session(agent_env, state["sid"])["answers"]) == 1


def test_closed_then_get(agent_env, monkeypatch):
    """다른 탭이 먼저 끝냈으면 409 CLOSED → GET으로 READY를 보여 준다."""
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")

    def other_tab_first(sid, body):
        turns(sid, {"expectedTurn": 1, "finish": True})
        return turns(sid, {**body, "expectedTurn": 2})

    r = sim(agent_env, turns_fn=other_tab_first).run(STORY)
    assert r.outcome == "READY" and [x[2] for x in r.requests] == ["ASKING", "AI_SESSION_CLOSED", "READY"]


def test_same_turn_working_after_fence(agent_env, monkeypatch):
    """BE-Q121: 울타리로 같은 turn의 WORKING이 오면 answer 없이 같은 turn으로 이어 간다. 답은 한 번만 반영."""
    from tests.unit.test_agent_recovery import Fence

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    state = {"n": 0}

    def fenced_once(sid, body):
        state["n"] += 1
        hooks.HOOK = Fence(3) if state["n"] == 1 else None
        try:
            return turns(sid, body)
        finally:
            hooks.HOOK = None

    r = sim(agent_env, turns_fn=fenced_once).run(STORY)
    assert r.outcome == "READY" and [x[2] for x in r.requests] == ["ASKING", "WORKING", "READY"]
    assert "answer" in r.sent[0] and r.sent[1] == {"expectedTurn": 1}
    assert r.turn_requests[1] == 2 and len(session(agent_env, r.view["sessionId"])["answers"]) == 1


def test_crash_500_refresh_recovers(agent_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    state = {"n": 0}

    def crash_once(sid, body):
        state["n"] += 1
        if state["n"] == 1:
            def boom(p):
                if p == "model_response":
                    raise Crash()
            hooks.HOOK = boom
        try:
            return turns(sid, body)
        finally:
            hooks.HOOK = None

    r = sim(agent_env, turns_fn=crash_once).run(STORY)
    assert r.outcome == "READY" and [x[0] for x in r.requests] == ["create", "turns", "get", "turns"]
    item = session(agent_env, r.view["sessionId"])
    assert len(item["answers"]) == 1 and int(item["modelCallsReserved"]) <= 6


@pytest.mark.parametrize(("scenario", "code"), [("http_401", "AI_UNAVAILABLE"), ("timeout", "AI_UNAVAILABLE")])
def test_failed_create_goes_direct_write(agent_env, monkeypatch, scenario, code):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", scenario)
    r = sim(agent_env).run(STORY)
    assert r.outcome == "DIRECT_WRITE" and r.code == code and r.request_count == 1


def test_quota_goes_direct_write(agent_env, monkeypatch):
    monkeypatch.setenv("AI_DAILY_SESSION_LIMIT", "1")
    sim(agent_env).run(STORY)
    r = sim(agent_env).run(STORY)
    assert r.outcome == "DIRECT_WRITE" and r.code == "AI_QUOTA_EXCEEDED"


def test_fence_persists_every_turn_ends_bounded(agent_env, monkeypatch):
    """매 턴 울타리가 닫혀도 요청 수가 묶이고 결정적 폐쇄로 끝난다(시도 상한 3 → 4번째 잠금에서 폐쇄)."""
    from tests.unit.test_agent_recovery import Fence

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")

    def always_fenced(sid, body):
        hooks.HOOK = Fence(1)
        try:
            return turns(sid, body)
        finally:
            hooks.HOOK = None

    r = sim(agent_env, turns_fn=always_fenced).run(STORY)
    assert r.outcome == "READY" and r.view["degraded"] is True
    assert r.turn_requests[1] <= 4 and r.request_count <= 6
