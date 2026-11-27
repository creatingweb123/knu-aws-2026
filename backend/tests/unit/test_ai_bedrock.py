"""Amazon Bedrock 공급자(LLM_PROVIDER=bedrock): 설정, 클라이언트, Converse 호출, 오류 분류.

Converse 응답은 botocore Stubber로 흉내 낸다(네트워크·자격 증명 없음).
"""

import asyncio
import logging

import pytest
from botocore import exceptions as bx
from botocore.stub import ANY, Stubber
from langchain_core.tools import tool

from agent import llm
from agent.card import parse_card
from agent.fake_llm import _card
from agent.prompt import build_messages

BEDROCK = {"LLM_PROVIDER": "bedrock", "LLM_MODEL": "test.model-v1:0", "LLM_REGION": "ap-northeast-2"}


@pytest.fixture(autouse=True)
def _clients(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    llm.reset_bedrock_clients()
    yield
    llm.reset_bedrock_clients()


@pytest.fixture
def quiet():
    saved = {n: logging.getLogger(n).level for n in llm.QUIET_LOGGERS}
    llm.quiet_library_loggers()
    yield
    for n, level in saved.items():
        logging.getLogger(n).setLevel(level)


def test_langchain_aws_logger_is_quieted():
    assert "langchain_aws" in llm.QUIET_LOGGERS


def converse_response(content, stop="end_turn", usage=(120, 40)):
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": {"inputTokens": usage[0], "outputTokens": usage[1], "totalTokens": sum(usage)},
        "metrics": {"latencyMs": 10},
    }


def stubbed(settings):
    client = llm.bedrock_client(settings)
    return client, Stubber(client)


def test_default_provider_is_bedrock():
    s = llm.load_settings({"LLM_MODEL": "m", "AWS_REGION": "us-east-1"})
    assert s.provider == llm.BEDROCK and s.mode == "bedrock" and s.region == "us-east-1" and s.error is None


def test_llm_region_overrides_function_region():
    s = llm.load_settings({**BEDROCK, "AWS_REGION": "us-east-1"})
    assert s.region == "ap-northeast-2"


@pytest.mark.parametrize("env", [{**BEDROCK, "LLM_MODEL": ""}, {"LLM_PROVIDER": "bedrock", "LLM_MODEL": "m"}])
def test_missing_model_or_region_is_config_not_called(env, caplog):
    caplog.set_level(logging.DEBUG)
    s = llm.load_settings(env)
    assert s.error == "CONFIG_ENDPOINT"
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(llm.LlmCaller(s, env=env).ainvoke(build_messages("사연"), 5))
    assert e.value.code == llm.CONFIG and e.value.called is False


def test_bedrock_needs_no_api_key():
    s = llm.load_settings(BEDROCK)
    assert s.error is None and s.key_param == ""


def test_client_has_no_retries_and_explicit_timeouts_and_endpoint():
    s = llm.load_settings({**BEDROCK, "LLM_CONNECT_TIMEOUT_S": "1.5", "LLM_READ_TIMEOUT_S": "7"})
    c = llm.bedrock_client(s)
    assert c.meta.region_name == "ap-northeast-2"
    assert c.meta.endpoint_url == "https://bedrock-runtime.ap-northeast-2.amazonaws.com"
    assert (c.meta.config.connect_timeout, c.meta.config.read_timeout) == (1.5, 7.0)
    assert c.meta.config.retries["total_max_attempts"] == 1
    assert llm.bedrock_client(s) is c  # 재사용


def test_endpoint_ignores_local_emulator_override(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://aws:4566")
    c = llm.bedrock_client(llm.load_settings(BEDROCK))
    assert c.meta.endpoint_url.startswith("https://bedrock-runtime.")


def test_converse_text_happy_path():
    s = llm.load_settings({**BEDROCK, "LLM_EXTRA_BODY": '{"top_k": 5}'})
    client, stub = stubbed(s)
    stub.add_response("converse", converse_response([{"text": _card()}]), {
        "modelId": "test.model-v1:0",
        "messages": ANY,
        "system": ANY,
        "inferenceConfig": {"maxTokens": 800, "temperature": 0.0},
        "additionalModelRequestFields": {"top_k": 5},
    })
    caller = llm.LlmCaller(s, env=BEDROCK)
    with stub:
        msg = asyncio.run(caller.ainvoke(build_messages("이사 전에 동네를 걷고 싶었다"), 5))
    stub.assert_no_pending_responses()
    assert parse_card(msg.content).card is not None
    assert llm.usage([], msg) == (120, 40, False)
    assert caller.calls_made == 1


def test_converse_tool_call_and_required_maps_to_any(monkeypatch):
    @tool
    def ask_planner(question: str) -> str:
        """계획자에게 질문한다."""
        return question

    env = {**BEDROCK, "LLM_MODEL": "apac.anthropic.claude-test-v1:0", "LLM_TOOL_CHOICE": "required", "LLM_PARALLEL_TOOL_CALLS": "false"}
    s = llm.load_settings(env)
    client = llm.bedrock_client(s)
    content = [{"toolUse": {"toolUseId": "t1", "name": "ask_planner", "input": {"question": "어디였나요?"}}}]
    seen = {}

    def converse(**params):
        seen.update(params)
        return converse_response(content, stop="tool_use")

    monkeypatch.setattr(client, "converse", converse)
    msg = asyncio.run(llm.LlmCaller(s, env=env).ainvoke(build_messages("사연"), 5, tools=[ask_planner]))
    assert seen["toolConfig"]["toolChoice"] == {"any": {}}  # required → Converse any
    assert [t["toolSpec"]["name"] for t in seen["toolConfig"]["tools"]] == ["ask_planner"]
    assert "parallel_tool_calls" not in str(seen)  # Converse에는 없는 인자
    assert [(c["name"], c["args"]) for c in msg.tool_calls] == [("ask_planner", {"question": "어디였나요?"})]


@pytest.mark.parametrize(("error_code", "status", "code"), [
    ("ThrottlingException", 429, llm.HTTP_429),
    ("ServiceQuotaExceededException", 400, llm.HTTP_429),
    ("AccessDeniedException", 403, llm.HTTP_403),
    ("UnrecognizedClientException", 403, llm.HTTP_401),
    ("ValidationException", 400, llm.HTTP_400),
    ("ModelTimeoutException", 408, llm.TIMEOUT),
    ("InternalServerException", 500, llm.HTTP_5XX),
    ("ServiceUnavailableException", 503, llm.HTTP_5XX),
    ("ResourceNotFoundException", 404, llm.HTTP_OTHER),
])
def test_converse_errors_classified(error_code, status, code, caplog, quiet):
    caplog.set_level(logging.DEBUG)
    s = llm.load_settings(BEDROCK)
    client, stub = stubbed(s)
    stub.add_client_error("converse", service_error_code=error_code, service_message="secret-detail", http_status_code=status)
    with stub, pytest.raises(llm.LlmError) as e:
        asyncio.run(llm.LlmCaller(s, env=BEDROCK).ainvoke(build_messages("사연"), 5))
    assert e.value.code == code and e.value.called is True
    # 핸들러처럼 라이브러리 로거를 잠그면 공급자 오류 본문·모델 ID·사연(langchain_aws DEBUG)이 남지 않는다
    assert "secret-detail" not in caplog.text and "model-v1" not in caplog.text and "사연" not in caplog.text
    assert f"reason={code}" in caplog.text


@pytest.mark.parametrize(("exc", "code"), [
    (bx.ReadTimeoutError(endpoint_url="u"), llm.TIMEOUT),
    (bx.ConnectTimeoutError(endpoint_url="u"), llm.TIMEOUT),
    (bx.EndpointConnectionError(endpoint_url="u"), llm.CONNECTION),
    (bx.NoCredentialsError(), llm.HTTP_401),
    (asyncio.TimeoutError(), llm.TIMEOUT),
    (ValueError("x"), llm.PROVIDER_RESPONSE),
])
def test_classify_botocore(exc, code):
    assert llm.classify(exc) == code


def test_deadline_cuts_slow_converse(monkeypatch):
    s = llm.load_settings(BEDROCK)
    client = llm.bedrock_client(s)
    import time

    def slow(**_):
        time.sleep(1.0)
        return converse_response([{"text": "{}"}])

    monkeypatch.setattr(client, "converse", slow)

    async def run():
        t0 = time.monotonic()
        with pytest.raises(llm.LlmError) as e:
            await llm.LlmCaller(s, env=BEDROCK).ainvoke(build_messages("사연"), 0.2)
        return e.value, time.monotonic() - t0

    err, elapsed = asyncio.run(run())
    assert err.code == llm.TIMEOUT and err.called is True
    assert elapsed < 0.8  # 응답을 기다리지 않고 deadline에 돌아온다(실행기 스레드는 뒤에서 끝난다)


def test_unsupported_tool_choice_is_config_before_reservation(monkeypatch):
    @tool
    def ask_planner(question: str) -> str:
        """계획자에게 질문한다."""
        return question

    env = {**BEDROCK, "LLM_TOOL_CHOICE": "required"}  # test.model은 langchain-aws가 tool_choice 미지원으로 본다
    s = llm.load_settings(env)
    client = llm.bedrock_client(s)
    monkeypatch.setattr(client, "converse", lambda **_: pytest.fail("호출하면 안 된다"))
    caller = llm.LlmCaller(s, env=env)
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(caller.ainvoke(build_messages("사연"), 5, tools=[ask_planner]))
    assert e.value.code == llm.CONFIG and e.value.reason == "CONFIG_TOOL_CHOICE" and e.value.called is False
    assert caller.calls_made == 0
