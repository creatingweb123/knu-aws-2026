"""429 세 종류 중 서버가 만드는 두 가지 (작업 9.6, design §19.1, BE-Q92). 경로 스로틀은 test_template.py에서 본다."""

import logging

from tests.unit.ai_handler_util import ai_env, body_of, create, metric_names, quota_count, sessions  # noqa: F401
from tests.unit.llm_stub import LlmStub

KEY = "sk-test-not-a-real-key"


def test_provider_429_fake_is_503(ai_env, monkeypatch, capsys, caplog):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "http_429")
    resp = create()
    assert resp["statusCode"] == 503 and body_of(resp)["error"]["code"] == "AI_UNAVAILABLE"
    [item] = sessions(ai_env)
    assert item["llmError"] == "HTTP_429" and item["status"] == "FAILED"
    assert "AiFailure" in dict(metric_names(capsys.readouterr().out))
    assert "reason=HTTP_429" in caplog.text


def test_provider_429_stub_is_503(ai_env, monkeypatch, capsys):
    with LlmStub() as stub:
        stub.mode = "status:429"
        for k, v in {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": stub.url, "LLM_MODEL": "stub-model", "LLM_API_KEY": KEY}.items():
            monkeypatch.setenv(k, v)
        resp = create()
        assert len(stub.requests) == 1  # 재시도 없음
    assert resp["statusCode"] == 503 and body_of(resp)["error"]["code"] == "AI_UNAVAILABLE"
    assert sessions(ai_env)[0]["llmError"] == "HTTP_429" and sessions(ai_env)[0]["llmMode"] == "openai_compat"


def test_quota_429_is_contract_error_without_ai_failure(ai_env, monkeypatch, capsys, caplog):
    caplog.set_level(logging.INFO, "haru.ai")
    monkeypatch.setenv("AI_DAILY_SESSION_LIMIT", "0")
    resp = create()
    assert resp["statusCode"] == 429
    assert body_of(resp) == {"error": {"code": "AI_QUOTA_EXCEEDED", "message": "오늘 AI 정리 횟수를 모두 썼어요. 직접 정리해 주세요."}}
    assert metric_names(capsys.readouterr().out) == [] and "HTTP_429" not in caplog.text
    assert sessions(ai_env) == [] and quota_count(ai_env) == 0

