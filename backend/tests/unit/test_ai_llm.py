"""LLM 설정·Fake 차단·SSM 키 캐시·오류 분류 (Requirement 7.1–7.12, 8.1–8.3, 15.10 · BE-Q81, BE-Q85, BE-Q86)."""

import asyncio
import logging

import httpx
import openai
import pytest
from botocore.stub import Stubber

from agent import llm
from agent.card import parse_card
from agent.fake_llm import SCENARIOS, FakeScenarioChatModel
from agent.prompt import build_messages

LOCAL_FAKE = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local"}
COMPAT = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "http://127.0.0.1:9/v1", "LLM_MODEL": "m", "LLM_API_KEY": "sk-test-not-a-real-key"}


def test_defaults():
    s = llm.load_settings(COMPAT)
    assert (s.connect_s, s.read_s, s.max_retries, s.max_tokens, s.temperature, s.call_max_s) == (2.0, 8.0, 0, 800, 0.0, 10.0)
    assert s.error is None and s.mode == "openai_compat"


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({"LLM_PROVIDER": "anthropic"}, "CONFIG_PROVIDER"),
        ({**COMPAT, "LLM_BASE_URL": ""}, "CONFIG_ENDPOINT"),
        ({**COMPAT, "LLM_MODEL": ""}, "CONFIG_ENDPOINT"),
        ({**COMPAT, "LLM_EXTRA_BODY": "[1]"}, "CONFIG_EXTRA_BODY"),
        ({**COMPAT, "LLM_EXTRA_BODY": "{bad"}, "CONFIG_EXTRA_BODY"),
        ({**COMPAT, "LLM_READ_TIMEOUT_S": "abc"}, "CONFIG_NUMBER"),
        ({**COMPAT, "LLM_CONNECT_TIMEOUT_S": "0"}, "CONFIG_NUMBER"),
        ({**COMPAT, "LLM_MAX_RETRIES": "2"}, "CONFIG_RETRIES"),
    ],
)
def test_config_errors_become_llm_error_without_values_in_log(env, reason, caplog):
    caplog.set_level(logging.DEBUG)
    s = llm.load_settings(env)
    assert s.error == reason
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(llm.LlmCaller(s, env=env).ainvoke(build_messages("사연"), 5))
    assert e.value.code == llm.CONFIG and e.value.called is False
    assert reason in caplog.text and "127.0.0.1" not in caplog.text and "sk-test" not in caplog.text


def test_temperature_empty_and_extra_body():
    s = llm.load_settings({**COMPAT, "LLM_TEMPERATURE": "", "LLM_EXTRA_BODY": '{"max_tokens": 800}'})
    assert s.temperature is None and s.extra_body == {"max_tokens": 800}


def test_tool_settings_kept_for_6b():
    s = llm.load_settings({**COMPAT, "LLM_TOOL_CHOICE": "auto", "LLM_PARALLEL_TOOL_CALLS": "false"})
    assert (s.tool_choice, s.parallel_tool_calls) == ("auto", "false")


@pytest.mark.parametrize(
    ("env", "allowed"),
    [
        (LOCAL_FAKE, True),
        ({**LOCAL_FAKE, "FAKE_LLM_ALLOWED": "false"}, False),
        ({**LOCAL_FAKE, "STAGE": "dev"}, False),
        ({**LOCAL_FAKE, "AWS_LAMBDA_FUNCTION_NAME": "haru-dev-AiCardFunction-abc"}, True),
        ({**LOCAL_FAKE, "AWS_LAMBDA_FUNCTION_NAME": "haru-demo-AiCardFunction-abc"}, False),
        ({**LOCAL_FAKE, "AWS_LAMBDA_FUNCTION_NAME": "other-haru-dev-x"}, False),
    ],
)
def test_fake_runtime_guard(env, allowed):
    assert llm.fake_allowed(env) is allowed
    assert (llm.load_settings(env).error is None) is allowed


def test_unknown_fake_scenario_is_config():
    env = {**LOCAL_FAKE, "FAKE_LLM_SCENARIO": "nope"}
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(llm.LlmCaller(llm.load_settings(env), env=env).ainvoke([], 5))
    assert e.value.code == llm.CONFIG


# SSM 키 ----------------------------------------------------------------------


@pytest.fixture
def ssm(monkeypatch):
    import boto3

    llm.reset_key_cache()
    client = boto3.client("ssm", region_name="ap-northeast-2", aws_access_key_id="x", aws_secret_access_key="y")
    monkeypatch.setattr(llm, "_ssm", lambda: client)
    with Stubber(client) as stub:
        yield stub
    llm.reset_key_cache()


def test_key_read_once_and_cached(ssm):
    s = llm.load_settings({**COMPAT, "LLM_API_KEY": "", "LLM_API_KEY_PARAM": "/haru/dev/llm/api-key"})
    ssm.add_response("get_parameter", {"Parameter": {"Name": "/haru/dev/llm/api-key", "Value": "sk-from-ssm", "Type": "SecureString"}},
                     {"Name": "/haru/dev/llm/api-key", "WithDecryption": True})
    assert llm.api_key(s, {}) == "sk-from-ssm"
    assert llm.api_key(s, {}) == "sk-from-ssm"  # 두 번째는 SSM을 부르지 않는다(Stubber에 응답이 하나뿐)
    ssm.assert_no_pending_responses()


def test_key_read_failure_not_cached(ssm, caplog):
    s = llm.load_settings({**COMPAT, "LLM_API_KEY_PARAM": "/haru/dev/llm/api-key"})
    ssm.add_client_error("get_parameter", "ParameterNotFound")
    ssm.add_client_error("get_parameter", "ThrottlingException")
    ssm.add_response("get_parameter", {"Parameter": {"Name": "/haru/dev/llm/api-key", "Value": "sk-later", "Type": "SecureString"}})
    for _ in range(2):
        with pytest.raises(llm.LlmError) as e:
            llm.api_key(s, {})
        assert e.value.code == llm.KEY_READ_FAILED and e.value.called is False
    assert llm.api_key(s, {}) == "sk-later"
    assert "sk-later" not in caplog.text


def test_aws_param_takes_precedence_over_env_key(ssm):
    s = llm.load_settings({**COMPAT, "LLM_API_KEY_PARAM": "/p"})
    ssm.add_response("get_parameter", {"Parameter": {"Name": "/p", "Value": "sk-ssm", "Type": "SecureString"}})
    assert llm.api_key(s, {"LLM_API_KEY": "sk-env"}) == "sk-ssm"


def test_local_key_missing_is_config():
    with pytest.raises(llm.LlmError) as e:
        llm.api_key(llm.load_settings({**COMPAT, "LLM_API_KEY": ""}), {})
    assert e.value.code == llm.CONFIG


def test_sdk_config_defaults():
    cfg = llm.sdk_config({})
    assert (cfg.connect_timeout, cfg.read_timeout, cfg.retries) == (1.0, 2.0, {"mode": "standard", "total_max_attempts": 2})


# 오류 분류 ---------------------------------------------------------------------

REQ = httpx.Request("POST", "http://x/v1/chat/completions")


def status(code):
    return openai.APIStatusError("x", response=httpx.Response(code, request=REQ), body=None)


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (asyncio.TimeoutError(), "TIMEOUT"),
        (openai.APITimeoutError(request=REQ), "TIMEOUT"),
        (openai.APIConnectionError(request=REQ), "CONNECTION"),
        (status(400), "HTTP_400"), (status(401), "HTTP_401"), (status(403), "HTTP_403"), (status(404), "HTTP_OTHER"),
        (status(429), "HTTP_429"), (status(500), "HTTP_5XX"), (status(503), "HTTP_5XX"),
        (ValueError("bad response"), "PROVIDER_RESPONSE"),
    ],
)
def test_classify(exc, code):
    assert llm.classify(exc) == code


# Fake -------------------------------------------------------------------------


def test_fake_scenarios_complete():
    assert {"happy", "not_in_source", "privacy_high", "private_place", "missing", "all_places_removed", "bad_json", "bad_json_then_ok",
            "schema_error", "schema_error_then_ok", "timeout", "http_400", "http_401", "http_429", "http_500", "slow", "no_usage",
            "fenced_json"} <= set(SCENARIOS)


@pytest.mark.parametrize(("scenario", "code"), [("timeout", "TIMEOUT"), ("connection", "CONNECTION"), ("http_400", "HTTP_400"),
                                                ("http_401", "HTTP_401"), ("http_429", "HTTP_429"), ("http_500", "HTTP_5XX")])
def test_fake_errors_classified_like_real(scenario, code):
    caller = llm.LlmCaller(llm.load_settings(LOCAL_FAKE), fake=FakeScenarioChatModel.for_scenario(scenario))
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(caller.ainvoke(build_messages("사연"), 5))
    assert e.value.code == code and e.value.called is True


def test_fake_records_calls_and_usage():
    fake = FakeScenarioChatModel.for_scenario("bad_json_then_ok")
    caller = llm.LlmCaller(llm.load_settings(LOCAL_FAKE), fake=fake)
    msgs = build_messages("출근길 빵집")
    first = asyncio.run(caller.ainvoke(msgs, 5))
    second = asyncio.run(caller.ainvoke(msgs, 5))
    assert not parse_card(first.content).ok and parse_card(second.content).ok
    assert len(fake.calls) == 2 and fake.calls[0]["messages"][1][1].startswith("<story>")
    assert llm.usage(msgs, second)[2] is False
    nousage = asyncio.run(llm.LlmCaller(llm.load_settings(LOCAL_FAKE), fake=FakeScenarioChatModel.for_scenario("no_usage")).ainvoke(msgs, 5))
    i, o, est = llm.usage(msgs, nousage)
    assert est is True and i > 0 and o > 0


def test_fake_slow_cut_by_deadline():
    caller = llm.LlmCaller(llm.load_settings(LOCAL_FAKE), fake=FakeScenarioChatModel.for_scenario("slow"))
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(caller.ainvoke([], 0.2))
    assert e.value.code == "TIMEOUT"


def test_zero_deadline_is_time_budget_not_called():
    fake = FakeScenarioChatModel.for_scenario("happy")
    with pytest.raises(llm.LlmError) as e:
        asyncio.run(llm.LlmCaller(llm.load_settings(LOCAL_FAKE), fake=fake).ainvoke([], 0))
    assert e.value.code == "TIME_BUDGET" and e.value.called is False and fake.calls == []


def test_quiet_library_loggers():
    llm.quiet_library_loggers()
    for name in llm.QUIET_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
