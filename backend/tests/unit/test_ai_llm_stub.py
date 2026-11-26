"""실제 ChatOpenAI + 로컬 HTTP 스텁 (Requirement 7.1, 7.2, 7.10, 8.4, 19.6). 외부 네트워크 없음(127.0.0.1)."""

import asyncio
import time

import pytest

from agent import llm
from agent.card import parse_card
from agent.prompt import build_messages
from tests.unit.llm_stub import LlmStub

KEY = "sk-test-not-a-real-key"


@pytest.fixture
def stub():
    with LlmStub() as s:
        yield s


def caller(stub, **env):
    e = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": stub.url, "LLM_MODEL": "stub-model", "LLM_API_KEY": KEY, **env}
    return llm.LlmCaller(llm.load_settings(e), env=e)


def call(stub, deadline=5.0, **env):
    return asyncio.run(caller(stub, **env).ainvoke(build_messages("출근길 빵집에 들르고 싶었어요"), deadline))


def test_request_shape(stub):
    msg = call(stub, LLM_EXTRA_BODY='{"max_tokens": 800, "reasoning_effort": "none"}')
    req = stub.requests[-1]
    assert req["path"] == "/v1/chat/completions" and len(stub.requests) == 1  # Responses API 아님, 재시도 없음
    body = req["body"]
    assert body["model"] == "stub-model" and body["max_completion_tokens"] == 800 and body["temperature"] == 0
    assert body["max_tokens"] == 800 and body["reasoning_effort"] == "none"  # extra_body가 본문에 합쳐진다
    assert "tools" not in body and "tool_choice" not in body and "parallel_tool_calls" not in body
    assert [m["role"] for m in body["messages"]] == ["system", "user"] and body["messages"][1]["content"].startswith("<story>")
    assert req["auth_prefix"] == "Bearer sk-"
    assert parse_card(msg.content).ok and llm.usage([], msg)[:2] == (120, 60)


def test_temperature_omitted_when_empty(stub):
    call(stub, LLM_TEMPERATURE="")
    assert "temperature" not in stub.requests[-1]["body"]


@pytest.mark.parametrize(("code", "expected"), [(400, "HTTP_400"), (401, "HTTP_401"), (403, "HTTP_403"), (404, "HTTP_OTHER"),
                                                (429, "HTTP_429"), (500, "HTTP_5XX"), (503, "HTTP_5XX")])
def test_status_classification_and_no_retry(stub, code, expected, caplog):
    stub.mode = f"status:{code}"
    with pytest.raises(llm.LlmError) as e:
        call(stub)
    assert e.value.code == expected and e.value.called and len(stub.requests) == 1
    assert "stub error with echo" not in caplog.text  # 공급자 오류 본문을 로그에 남기지 않는다


def test_connection_refused():
    e = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "http://127.0.0.1:1/v1", "LLM_MODEL": "m", "LLM_API_KEY": KEY}
    with pytest.raises(llm.LlmError) as exc:
        asyncio.run(llm.LlmCaller(llm.load_settings(e), env=e).ainvoke(build_messages("x"), 5))
    assert exc.value.code == "CONNECTION"


@pytest.mark.parametrize("mode", ["fenced", "prose"])
def test_json_extraction_from_real_response_shapes(stub, mode):
    stub.mode = mode
    assert parse_card(call(stub).content).ok


def test_no_usage_is_estimated(stub):
    stub.mode = "no_usage"
    msgs = build_messages("출근길 빵집")
    msg = asyncio.run(caller(stub).ainvoke(msgs, 5))
    i, o, est = llm.usage(msgs, msg)
    assert est and i > 0 and o > 0


@pytest.mark.parametrize("mode", ["drip", "hang"])
def test_deadline_cuts_slow_response(stub, mode):
    stub.mode = mode
    t = time.monotonic()
    with pytest.raises(llm.LlmError) as e:
        call(stub, deadline=1.0)
    assert e.value.code == "TIMEOUT" and time.monotonic() - t < 1.5


def test_read_timeout_alone_does_not_bound_drip(stub):
    """httpx read 타임아웃(여기서는 0.5초)은 바이트 사이 시간이라, 0.2초마다 오는 응답을 끊지 못한다(BE-Q78 근거)."""
    stub.mode = "drip"
    t = time.monotonic()
    with pytest.raises(llm.LlmError):
        call(stub, deadline=2.0, LLM_READ_TIMEOUT_S="0.5")
    assert time.monotonic() - t >= 1.9  # read 타임아웃이 아니라 전체 deadline이 끊었다
