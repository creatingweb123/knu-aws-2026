"""에이전트 경로 로그·trace·EMF 유출 방지 (작업 11.3, Req 17, design §16).

6a test_ai_logging 검사를 도구 호출·interrupt·resume·체크포인트 경로로 넓힌다. 모든 로거 DEBUG, 라이브러리 로거는
콜드 스타트와 같이 WARNING 고정. 체크포인트 쓰기·읽기(boto DEBUG)에 사연·답변이 나오지 않는다.
"""

import json
import logging

import pytest

from agent import hooks, llm
from agent.fake_llm import AGENT_SCENARIOS, FakeScenarioChatModel
from tests.unit.agent_handler_util import agent_env, body_of, create, get, only_session, session, turns  # noqa: F401
from tests.unit import test_ai_logging as base
from tests.unit.test_ai_logging import KEY, SECRET_STORY, SRC, _files, leaked

ANSWER_TEXT = "하천 산책로 끝 정자까지 걸어요"
PRIVATE_ANSWER = "연락은 010-9753-1086으로 주세요"
EXTRA = [ANSWER_TEXT, "정자까지 걸어요", PRIVATE_ANSWER, "010-9753-1086"]


@pytest.fixture
def capture(caplog):
    caplog.set_level(logging.DEBUG)
    llm.quiet_library_loggers()
    return caplog


@pytest.fixture
def model_messages(monkeypatch):
    """Fake가 받은 메시지(type, content)를 모두 모은다(ToolMessage 검사용)."""
    seen = []
    real = FakeScenarioChatModel._next

    def spy(self, messages, kwargs):
        seen.extend((m.type, str(m.content)) for m in messages)
        return real(self, messages, kwargs)

    monkeypatch.setattr(FakeScenarioChatModel, "_next", spy)
    return seen


def drive(sid, view, text):
    """질문이 오면 자유 입력(허용 시) 또는 첫 선택지로 답하고, WORKING이면 이어 간다. 최대 6요청."""
    for _ in range(6):
        if view.get("status") not in ("ASKING", "WORKING"):
            return view
        body = {"expectedTurn": view["turn"]}
        q = view.get("question")
        if q:
            body["answer"] = ({"questionId": q["questionId"], "text": text} if q["allowFreeText"]
                              else {"questionId": q["questionId"], "choice": q["options"][0]})
        r = turns(sid, body)
        view = body_of(r) if r["statusCode"] == 200 else body_of(get(sid))
    return view


def check_no_leak(capture, out, item, extra=()):
    trace = json.dumps(item.get("trace"), ensure_ascii=False, default=str)
    assert leaked(capture.text, [*EXTRA, *extra]) == []
    assert leaked(out.out + out.err, [*EXTRA, *extra]) == []  # EMF 포함
    assert leaked(trace, [*EXTRA, *extra]) == []


@pytest.mark.parametrize("scenario", sorted(set(AGENT_SCENARIOS) - {"slow_agent"}))
def test_no_leak_agent_scenarios(agent_env, monkeypatch, capture, capsys, model_messages, scenario):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", scenario)
    monkeypatch.setenv("LLM_API_KEY", KEY)
    resp = create(SECRET_STORY)
    item = only_session(agent_env)
    if resp["statusCode"] == 200:
        drive(item["sessionId"], body_of(resp), ANSWER_TEXT)
    else:
        assert leaked(resp["body"], EXTRA) == []
    out = capsys.readouterr()
    check_no_leak(capture, out, session(agent_env, item["sessionId"]))
    # 검사 보고서·Tool_Error ToolMessage에는 경로·유형만 있다(답변 전달 메시지는 모델에 주는 게 목적이므로 제외)
    for kind, content in model_messages:
        if kind == "tool" and '"usable": true' not in content:
            assert leaked(content, EXTRA) == [], content


def test_private_answer_withheld_everywhere(agent_env, monkeypatch, capture, capsys, model_messages):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    v = body_of(create(SECRET_STORY))
    sid = v["sessionId"]
    v = drive(sid, v, PRIVATE_ANSWER)
    item = session(agent_env, sid)
    assert v["status"] == "READY" and item["answers"][0]["privacy"] is True
    out = capsys.readouterr()
    check_no_leak(capture, out, item)
    assert all(PRIVATE_ANSWER not in c and "010-9753-1086" not in c for _, c in model_messages)  # 모델에도 보내지 않는다
    assert any('"withheld": true' in c for k, c in model_messages if k == "tool")


def test_crash_recovery_path_no_leak(agent_env, monkeypatch, capture, capsys):
    """체크포인트 읽기·tip 선택·재개 경로(강제 종료 뒤 복구)에서도 원문이 로그에 없다."""
    from tests.unit.test_agent_recovery import At, Crash

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    sid = body_of(create(SECRET_STORY))["sessionId"]
    hooks.HOOK = At("ckpt_put", 2)
    try:
        with pytest.raises(Crash):
            turns(sid, {"expectedTurn": 1, "answer": {"questionId": "q1", "text": ANSWER_TEXT}})
    finally:
        hooks.HOOK = None
    agent_env.update_item(Key={"PK": f"AISESSION#{sid}", "SK": "META"}, UpdateExpression="SET lockedUntil = :p",
                          ExpressionAttributeValues={":p": 1})
    assert body_of(turns(sid, {"expectedTurn": 1, "answer": {"questionId": "q1", "text": ANSWER_TEXT}}))["status"] == "READY"
    check_no_leak(capture, capsys.readouterr(), session(agent_env, sid))


def test_unexpected_exception_in_agent_logs_type_only(agent_env, monkeypatch, capture):
    from handlers import ai_agent

    def boom(*a, **k):
        raise RuntimeError(f"secret {SECRET_STORY} {KEY}")

    monkeypatch.setattr(ai_agent, "_run_graph", boom)
    resp = create(SECRET_STORY)
    assert resp["statusCode"] == 500 and leaked(capture.text) == [] and "RuntimeError" in capture.text
    assert leaked(resp["body"]) == [] and "Traceback" not in capture.text


def test_checkpoint_logger_quiet():
    llm.quiet_library_loggers()
    assert "langgraph_checkpoint_aws" in llm.QUIET_LOGGERS
    assert logging.getLogger("langgraph_checkpoint_aws").level == logging.WARNING


def test_agent_modules_in_forbidden_pattern_scan():
    names = {p.name for p in _files()}
    assert {"agent_tools.py", "agent_nodes.py", "checkpoint.py", "budget.py", "hooks.py", "fault.py"} <= names


def test_forbidden_patterns_agent_handler():
    base.test_forbidden_logging_patterns(SRC / "handlers" / "ai_agent.py")
