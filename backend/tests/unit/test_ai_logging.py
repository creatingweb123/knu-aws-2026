"""로그·trace 유출 방지 (작업 9.6, Requirement 13.1–13.8, design §15.2).

모든 시나리오에서 로그(모든 로거, DEBUG까지)·EMF 출력·trace·응답 오류 본문에 사연 표본, 카드 문자열, 가짜 키,
모델 응답 원문, 공급자 오류 본문, Base URL이 나오지 않는지 본다. 정적 검사로 금지 패턴도 막는다.
"""

import ast
import json
import logging
import pathlib

import pytest

from agent import llm
from agent.fake_llm import SCENARIOS
from tests.unit.ai_handler_util import ai_env, body_of, create, sessions  # noqa: F401
from tests.unit.llm_stub import LlmStub

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
KEY = "sk-test-not-a-real-key-7f3a"
SECRET_STORY = "출근길 빵집에 들러 빵을 사고 하천 벤치에 앉아 쉬고 싶었어요. 연락처 010-2468-1357, 메일 jiyeon@example.com, 101동 1203호."
STORY_SAMPLES = ["출근길 빵집에 들러", "010-2468-1357", "jiyeon@example.com", "101동 1203호", "앉아 쉬고 싶었어요"]
MODEL_SAMPLES = ["카드를 만들 수 없어요", "여전히 JSON이 아니에요", "이사 전, 마지막 동네 산책", "저녁마다 걷던 길이에요", "민지네 집", "골목 빵집",
                 "010-1234-5678", "fake provider error", "stub error with echo"]


def leaked(text, extra=()):
    return [s for s in [*STORY_SAMPLES, *MODEL_SAMPLES, KEY, "sk-test", *extra] if s in text]


@pytest.fixture
def capture(caplog):
    caplog.set_level(logging.DEBUG)  # 루트까지 DEBUG
    llm.quiet_library_loggers()       # 콜드 스타트 초기화와 같게
    return caplog


@pytest.mark.parametrize("scenario", sorted(set(SCENARIOS) - {"slow"}))
def test_no_leak_fake_scenarios(ai_env, monkeypatch, capture, capsys, scenario):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", scenario)
    monkeypatch.setenv("LLM_API_KEY", KEY)
    resp = create(SECRET_STORY)
    out = capsys.readouterr()
    [item] = sessions(ai_env)
    trace = json.dumps(item["trace"], ensure_ascii=False, default=str)
    assert leaked(capture.text) == [] and leaked(out.out + out.err) == [] and leaked(trace) == []
    if resp["statusCode"] != 200:
        assert leaked(resp["body"]) == []


@pytest.mark.parametrize("mode", ["ok", "status:400", "status:401", "status:500", "close", "prose"])
def test_no_leak_real_client_stub(ai_env, monkeypatch, capture, capsys, mode):
    with LlmStub() as stub:
        stub.mode = mode
        env = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": stub.url, "LLM_MODEL": "stub-model", "LLM_API_KEY": KEY}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        create(SECRET_STORY)
        url = stub.url
    out = capsys.readouterr()
    [item] = sessions(ai_env)
    host = url.split("//")[1]
    assert leaked(capture.text, [host]) == [] and leaked(out.out + out.err, [host]) == []
    assert leaked(json.dumps(item["trace"], ensure_ascii=False, default=str)) == []


def test_unexpected_exception_logs_type_only(ai_env, monkeypatch, capture):
    from handlers import ai_card

    def boom(*a, **k):
        raise RuntimeError(f"secret {SECRET_STORY} {KEY}")

    monkeypatch.setattr(ai_card, "_run_graph", boom)
    resp = create(SECRET_STORY)
    assert resp["statusCode"] == 500 and leaked(capture.text) == [] and "RuntimeError" in capture.text
    assert leaked(resp["body"]) == [] and "Traceback" not in capture.text


def test_ssm_key_failure_logs_no_name_or_message(ai_env, monkeypatch, capture):
    class Boom:
        def get_parameter(self, **k):
            raise RuntimeError(f"AccessDenied for /haru/dev/llm/api-key {KEY}")

    monkeypatch.setattr(llm, "_ssm", lambda: Boom())
    for k, v in {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "http://127.0.0.1:1/v1", "LLM_MODEL": "m",
                 "LLM_API_KEY_PARAM": "/haru/dev/llm/api-key"}.items():
        monkeypatch.setenv(k, v)
    resp = create(SECRET_STORY)
    assert resp["statusCode"] == 503 and sessions(ai_env)[0]["llmError"] == "KEY_READ_FAILED"
    assert leaked(capture.text, ["/haru/dev/llm/api-key", "AccessDenied"]) == []


def test_library_loggers_warning():
    llm.quiet_library_loggers()
    for name in ("openai", "httpx", "httpcore", "langchain", "langchain_core", "langchain_openai", "langgraph", "langsmith",
                 "boto3", "botocore", "urllib3"):
        assert logging.getLogger(name).level == logging.WARNING


def _files():
    return [*sorted((SRC / "agent").glob("*.py")), SRC / "handlers" / "ai_card.py", SRC / "domain" / "ai_session_service.py"]


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_forbidden_logging_patterns(path):
    """logger.exception, exc_info=True, str(e)·repr(e)(예외 변수), f-string·format의 !r, %r 포맷을 쓰지 않는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    exc_names = {h.name for h in ast.walk(tree) if isinstance(h, ast.ExceptHandler) and h.name}
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "exception":
                problems.append(f"exception() line {node.lineno}")
            if any(k.arg == "exc_info" for k in node.keywords):
                problems.append(f"exc_info line {node.lineno}")
            if isinstance(f, ast.Name) and f.id in ("str", "repr") and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in exc_names:
                problems.append(f"{f.id}(exception) line {node.lineno}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "%r" in node.value:
            problems.append(f"%r line {node.lineno}")
        if isinstance(node, ast.FormattedValue) and isinstance(node.value, ast.Name) and node.value.id in exc_names:
            problems.append(f"f-string exception line {node.lineno}")
    assert problems == []


def test_failed_response_has_no_model_text(ai_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "bad_json")
    resp = create(SECRET_STORY)
    assert resp["statusCode"] == 502 and set(body_of(resp)["error"]) == {"code", "message"}
