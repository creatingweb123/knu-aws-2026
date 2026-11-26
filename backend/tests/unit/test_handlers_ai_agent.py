"""6b 핸들러 (작업 10.7, moto + Fake + moto 체크포인터). design §4, §5, §13."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from domain import ai_session_service as svc
from tests.unit.agent_handler_util import (  # noqa: F401
    STORY, agent_env, body_of, ckpt_items, create, get, only_session, session, turns)
from tests.unit.agent_util import Ctx
from tests.unit.ai_handler_util import OTHER, metric_names, quota_count

Q_ANSWER = {"questionId": "q1", "choice": "45분"}


def set_scenario(monkeypatch, sc):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", sc)


def test_create_happy_ready(agent_env, capsys):
    resp = create()
    view = body_of(resp)
    assert resp["statusCode"] == 200 and view["status"] == "READY" and view["turn"] == 1 and view["question"] is None
    assert [t["tool"] for t in view["trace"]] == ["draft", "check_draft", "submit_card"] and [t["step"] for t in view["trace"]] == [1, 2, 3]
    item = only_session(agent_env)
    assert item["agentMode"] == "AGENT" and item["turn"] == 1 and "lockToken" not in item and item["turnRuns"] == []
    assert int(item["modelCallsReserved"]) == 2 and int(item["modelCalls"]) == 2 and item["llmMode"] == "fake"
    assert item["firstReport"] and item["readyAt"] and quota_count(agent_env) == 1
    assert ckpt_items(item["sessionId"]) == []  # 종료 뒤 체크포인트 삭제(BE-Q103)
    names = [n for n, _ in metric_names(capsys.readouterr().out)]
    assert {"AgentModelCalls", "AgentTokens", "AgentTurnMs", "AgentCheckpointBytes"} <= set(names)


def test_ask_once_flow(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    v1 = body_of(create())
    assert v1["status"] == "ASKING" and v1["turn"] == 1
    assert v1["question"]["questionId"] == "q1" and v1["question"]["path"] == "estimatedMinutes" and v1["question"]["options"] == ["30분", "45분", "1시간"]
    sid = v1["sessionId"]
    assert body_of(get(sid)) == v1 and ckpt_items(sid)
    v2 = body_of(turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER}))
    assert v2["status"] == "READY" and v2["turn"] == 2 and v2["card"]["estimatedMinutes"] == 45
    item = session(agent_env, sid)
    assert len(item["answers"]) == 1 and item["answers"][0]["choice"] == "45분" and item["answers"][0]["resumeId"] == "r1-q1"
    assert item["answers"][0]["askedAt"] and item["answers"][0]["answeredAt"] and "pendingResume" not in item
    assert int(item["modelCallsReserved"]) == 4 and item["questionsAsked"] == 1 and ckpt_items(sid) == []


def test_same_turn_resend_after_commit_is_idempotent(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    sid = body_of(create())["sessionId"]
    v2 = body_of(turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER}))
    again = turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER})  # 같은 턴 재전송 → 현재 상태 200, 모델 호출 없음
    assert again["statusCode"] == 200 and body_of(again) == v2
    assert int(session(agent_env, sid)["modelCallsReserved"]) == 4
    assert turns(sid, {"expectedTurn": 2})["statusCode"] == 409  # 종료 상태


def test_finish_skips_question(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    sid = body_of(create())["sessionId"]
    v = body_of(turns(sid, {"expectedTurn": 1, "finish": True}))
    item = session(agent_env, sid)
    assert v["status"] == "READY" and item["finishRequested"] is True and item["answers"][0]["skipped"] is True
    assert item["answers"][0]["viaFinish"] is True


@pytest.mark.parametrize(("body", "path"), [
    ({"expectedTurn": 1, "answer": {"questionId": "q9", "choice": "45분"}}, "answer.questionId"),
    ({"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "2시간"}}, "answer.choice"),
    ({"expectedTurn": 1}, "answer"),
])
def test_state_based_validation(agent_env, monkeypatch, body, path):
    set_scenario(monkeypatch, "ask_once")
    sid = body_of(create())["sessionId"]
    before = session(agent_env, sid)
    r = turns(sid, body)
    assert r["statusCode"] == 400 and path in body_of(r)["error"]["details"]
    after = session(agent_env, sid)
    assert after == before  # 잠금·모델·체크포인트 무변화


def test_free_text_not_allowed(agent_env, monkeypatch):
    set_scenario(monkeypatch, "private_place_ask")
    v = body_of(create())
    assert v["question"]["options"] == ["동선에서 빼기"] and v["question"]["allowFreeText"] is True
    r = turns(v["sessionId"], {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "동선에서 빼기"}})
    assert body_of(r)["status"] == "READY" and [p["name"] for p in body_of(r)["card"]["places"]] == ["출근길 빵집"]


def test_busy_and_not_found_order(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    sid = body_of(create())["sessionId"]
    agent_env.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockToken = :t, lockedUntil = :u",
                          ExpressionAttributeValues={":t": "other", ":u": svc.now_ms() + 20_000})
    r = turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER})
    assert r["statusCode"] == 409 and body_of(r)["error"]["code"] == "AI_SESSION_BUSY"
    assert turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER}, claims=OTHER)["statusCode"] == 404
    assert turns(sid, {"expectedTurn": 5})["statusCode"] == 200


def test_failed_generation_is_503(agent_env, monkeypatch):
    set_scenario(monkeypatch, "http_401")
    r = create()
    assert r["statusCode"] == 503 and body_of(r)["error"]["code"] == "AI_UNAVAILABLE"
    item = only_session(agent_env)
    assert item["status"] == "FAILED" and item["llmError"] == "HTTP_401" and item["turn"] == 1


def test_degraded_ready(agent_env, monkeypatch):
    set_scenario(monkeypatch, "decide_http_500")
    v = body_of(create())
    assert v["status"] == "READY" and v["degraded"] is True


def test_time_short_working_then_continue(agent_env, monkeypatch):
    set_scenario(monkeypatch, "slow_agent")
    v1 = body_of(create(ctx=Ctx(25_000, 25_000, 25_000, 25_000, 25_000, 11_000)))
    assert v1["status"] == "WORKING" and v1["turn"] == 1
    v2 = body_of(turns(v1["sessionId"], {"expectedTurn": 1}))
    assert v2["status"] == "READY" and v2["turn"] == 2


def test_mode_switch_closes_agent_session(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    v = body_of(create())
    sid = v["sessionId"]
    reserved = int(session(agent_env, sid)["modelCallsReserved"])
    monkeypatch.setenv("AGENT_MODE", "pipeline")
    r = turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER})
    item = session(agent_env, sid)
    assert r["statusCode"] == 200 and body_of(r)["status"] == "READY" and body_of(r)["degraded"] is True
    assert item["turn"] == 2 and int(item["modelCallsReserved"]) == reserved and ckpt_items(sid) == []
    assert body_of(get(sid))["status"] == "READY"


def test_mode_switch_without_candidate_is_503(agent_env, monkeypatch):
    set_scenario(monkeypatch, "slow_agent")
    v = body_of(create(ctx=Ctx(11_000)))  # draft 전에 시간 부족 → WORKING, 후보 없음
    assert v["status"] == "WORKING"
    monkeypatch.setenv("AGENT_MODE", "pipeline")
    r = turns(v["sessionId"], {"expectedTurn": 1})
    assert r["statusCode"] == 503 and session(agent_env, v["sessionId"])["status"] == "FAILED"


def test_pipeline_nonterminal_session_still_500(agent_env):
    item = svc.build_session_item(session_id="ais_01ABCDEFGHJKMNPQRSTVWXYZ00", owner_id="u-owner", story="s", status="WORKING",
                                  created_at=datetime.now(timezone.utc))
    svc.put_session(item)
    r = turns(item["sessionId"], {"expectedTurn": 1})
    assert r["statusCode"] == 500 and session(agent_env, item["sessionId"])["status"] == "WORKING"


def test_pipeline_mode_create_is_level0(agent_env, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "pipeline")
    v = body_of(create())
    assert v["status"] == "READY" and only_session(agent_env)["agentMode"] == "PIPELINE"
    assert ckpt_items(v["sessionId"]) == []


def test_invalid_mode_503_for_agent_turns(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    sid = body_of(create())["sessionId"]
    monkeypatch.setenv("AGENT_MODE", "foo")
    assert turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER})["statusCode"] == 503


def test_recovery_limit_closes(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    sid = body_of(create())["sessionId"]
    agent_env.update_item(Key=svc.session_key(sid), UpdateExpression="SET turnAttempts = :n", ExpressionAttributeValues={":n": 3})
    r = turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER})
    assert r["statusCode"] == 200 and body_of(r)["degraded"] is True
    item = session(agent_env, sid)
    assert item["status"] == "READY" and item["turn"] == 2


def test_expired_session_404(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    sid = body_of(create())["sessionId"]
    agent_env.update_item(Key=svc.session_key(sid), UpdateExpression="SET #t = :t", ExpressionAttributeNames={"#t": "ttl"},
                          ExpressionAttributeValues={":t": int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())})
    assert turns(sid, {"expectedTurn": 1, "answer": Q_ANSWER})["statusCode"] == 404 and get(sid)["statusCode"] == 404


def test_view_has_no_internal_fields(agent_env, monkeypatch):
    set_scenario(monkeypatch, "ask_once")
    r = create()
    text = r["body"]
    for k in ("lockToken", "pendingResume", "bestCard", "modelCallsReserved", "turnRuns", "llmMode", "story"):
        assert k not in text
    assert list(json.loads(text)) == list(svc.VIEW_KEYS)
