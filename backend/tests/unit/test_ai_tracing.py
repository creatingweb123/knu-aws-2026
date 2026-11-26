"""LangSmith 비활성화 (작업 9.6, Requirement 13.5, design §15.2).

추적 변수를 true로 둬도 핸들러 실행에서 LangSmith 전송이 0회이고, 127.0.0.1 밖으로 나가는 소켓 연결이 없다.
대조 실험: tracing_context로 감싸지 않고 그래프를 직접 돌리면 같은 차단 장치에 전송 시도가 잡힌다(장치가 실제로 동작하는지 확인).
"""

import asyncio
import socket

import pytest

from agent import graph as g
from agent import llm
from agent.timebudget import TimeBudget
from tests.unit.ai_handler_util import STORY, Ctx, ai_env, create  # noqa: F401


@pytest.fixture
def tracing_on(monkeypatch):
    """두 변수를 true로 두고 전송 경로를 막아 기록한다. 외부 소켓 연결도 막는다."""
    import langsmith.client
    import langsmith.run_trees

    for k in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(k, "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test-not-real")  # 키가 있어도 전송하지 않아야 한다
    from langsmith import utils as ls_utils

    if hasattr(ls_utils.get_env_var, "cache_clear"):
        ls_utils.get_env_var.cache_clear()  # 앞선 테스트가 읽어 둔 값을 버린다
    sent = []

    def record(name):
        def f(*a, **k):
            sent.append(name)
        return f

    for name in ("create_run", "update_run", "batch_ingest_runs", "multipart_ingest", "_send_compressed_multipart_req", "_send_multipart_req"):
        if hasattr(langsmith.client.Client, name):
            monkeypatch.setattr(langsmith.client.Client, name, record(name))
    monkeypatch.setattr(langsmith.run_trees.RunTree, "post", record("RunTree.post"))
    monkeypatch.setattr(langsmith.run_trees.RunTree, "patch", record("RunTree.patch"))
    import requests

    def no_http(self, request, **k):  # langsmith 백그라운드 전송(requests)도 막는다
        sent.append(f"http:{request.url.split('/')[2]}")
        raise requests.ConnectionError("테스트에서 차단")

    monkeypatch.setattr(requests.Session, "send", no_http)

    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            sent.append(f"socket:{host}")
            raise OSError("외부 연결 차단(테스트)")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield sent
    if hasattr(ls_utils.get_env_var, "cache_clear"):
        ls_utils.get_env_var.cache_clear()  # 뒤 테스트에 true 값이 남지 않게 한다


def test_handler_sends_nothing(ai_env, tracing_on):
    resp = create()
    assert resp["statusCode"] == 200
    assert tracing_on == []


@pytest.mark.parametrize("scenario", ["bad_json", "http_401", "privacy_high"])
def test_handler_sends_nothing_other_paths(ai_env, tracing_on, monkeypatch, scenario):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", scenario)
    create()
    assert tracing_on == []


def test_control_without_tracing_context_is_caught(tracing_on):
    """대조: tracing_context(enabled=False) 없이 그래프를 돌리면 전송 시도가 차단 장치에 기록된다."""
    env = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local"}
    caller = llm.LlmCaller(llm.load_settings(env), env=env)
    config = {"configurable": {"llm": caller, "deadline": TimeBudget(Ctx(), None)}}
    asyncio.run(g.pipeline_graph().ainvoke(g.initial_state(STORY), config=config))
    from langchain_core.tracers.langchain import wait_for_all_tracers

    wait_for_all_tracers()
    from langsmith.run_trees import get_cached_client

    try:
        get_cached_client().flush()  # 백그라운드 큐를 여기서 비운다(뒤 테스트로 전송이 넘어가지 않게)
    except Exception:  # noqa: BLE001 - 차단된 전송의 오류는 무시
        pass
    assert tracing_on, "차단 장치가 실제 전송 시도를 잡아야 한다"
    print("control:", sorted(set(tracing_on)))
