"""에이전트 경로 LangSmith 전송 0 (작업 11.3, Req 17, design §16).

6a 차단 장치(tracing_on)로 도구 호출·interrupt·resume·pause·체크포인트 경로를 돈다. 외부 소켓 연결도 없다(moto·Fake).
"""

import pytest

from tests.unit.agent_handler_util import agent_env, body_of, create, turns  # noqa: F401
from tests.unit.agent_util import Ctx
from tests.unit.test_ai_tracing import tracing_on  # noqa: F401


def test_interrupt_and_resume_send_nothing(agent_env, tracing_on, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    v = body_of(create())
    assert v["status"] == "ASKING"
    v = body_of(turns(v["sessionId"], {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "45분"}}))
    assert v["status"] == "READY" and tracing_on == []


def test_pause_and_continue_send_nothing(agent_env, tracing_on, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "slow_agent")
    v = body_of(create(ctx=Ctx(25_000, 25_000, 25_000, 25_000, 25_000, 11_000)))
    assert v["status"] == "WORKING"
    assert body_of(turns(v["sessionId"], {"expectedTurn": 1}))["status"] == "READY" and tracing_on == []


@pytest.mark.parametrize("scenario", ["parallel_calls", "bad_json_args", "gate_reject_thrice", "http_401", "decide_http_500",
                                      "private_place_ask"])
def test_other_agent_paths_send_nothing(agent_env, tracing_on, monkeypatch, scenario):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", scenario)
    v = create()
    if v["statusCode"] == 200 and body_of(v)["status"] == "ASKING":
        q = body_of(v)["question"]
        turns(body_of(v)["sessionId"], {"expectedTurn": 1, "answer": {"questionId": q["questionId"], "choice": q["options"][0]}})
    assert tracing_on == []


def test_recovery_path_sends_nothing(agent_env, tracing_on, monkeypatch):
    from agent import hooks
    from tests.unit.test_agent_recovery import At, Crash

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    sid = body_of(create())["sessionId"]
    hooks.HOOK = At("model_response")
    try:
        with pytest.raises(Crash):
            turns(sid, {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "45분"}})
    finally:
        hooks.HOOK = None
    agent_env.update_item(Key={"PK": f"AISESSION#{sid}", "SK": "META"}, UpdateExpression="SET lockedUntil = :p",
                          ExpressionAttributeValues={":p": 1})
    assert body_of(turns(sid, {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "45분"}}))["status"] == "READY"
    assert tracing_on == []
