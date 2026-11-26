"""LLM 호출 취소·AsyncClient 종료·Warm 호출 (design §12, Requirement 7.11, 12.5, 12.6 · BE-Q78).

asyncio.wait_for는 취소가 끝날 때까지 기다리고, 그 뒤 AsyncClient.aclose()도 기다린다. 그래서 반환이 deadline보다
늦을 수 있다. 여기서 그 지연이 CANCEL_SLACK_S 안인지 반복 측정한다(측정값은 -s로 출력해 README 근거로 쓴다).
"""

import asyncio
import gc
import json
import os
import statistics
import sys
import time
import warnings

import pytest

from agent import llm
from agent.prompt import build_messages
from tests.unit.llm_stub import LlmStub

KEY = "sk-test-not-a-real-key"
DEADLINE_S = 0.5
CANCEL_SLACK_S = 0.5
REPEAT = 20


def make_caller(url):
    env = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": url, "LLM_MODEL": "m", "LLM_API_KEY": KEY}
    return llm.LlmCaller(llm.load_settings(env), env=env)


def one_call(url, deadline=DEADLINE_S):
    t = time.monotonic()
    code = "OK"
    try:
        asyncio.run(make_caller(url).ainvoke(build_messages("출근길 빵집"), deadline))
    except llm.LlmError as e:
        code = e.code
    return code, time.monotonic() - t


def open_fds():
    return len(os.listdir("/proc/self/fd"))


@pytest.mark.parametrize(("mode", "expected"), [("drip", "TIMEOUT"), ("hang", "TIMEOUT"), ("close", "CONNECTION")])
def test_cancel_return_time_bounded(mode, expected):
    with LlmStub() as stub:
        stub.mode = mode
        stub.drip_interval = 0.05
        one_call(stub.url)  # 첫 호출의 라이브러리 지연 초기화는 따로 센다
        times = []
        for _ in range(REPEAT):
            code, elapsed = one_call(stub.url)
            assert code == expected
            times.append(elapsed)
        time.sleep(0.3)
        if mode in ("drip", "hang"):  # 서버 쪽에서 클라이언트가 연결을 닫은 것을 봤다
            assert stub.closed_early >= REPEAT, stub.closed_early
    worst = max(times)
    print(json.dumps({"mode": mode, "deadline_s": DEADLINE_S, "n": REPEAT, "max_s": round(worst, 3),
                      "median_s": round(statistics.median(times), 3)}))
    assert worst <= DEADLINE_S + CANCEL_SLACK_S, times


def test_next_call_after_cancel_is_normal():
    with LlmStub() as stub:
        stub.mode = "hang"
        assert one_call(stub.url)[0] == "TIMEOUT"
        stub.mode = "ok"
        assert one_call(stub.url, deadline=5)[0] == "OK"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="열린 소켓 수를 /proc/self/fd로 센다(리눅스 전용)")
def test_warm_invocations_no_leaks():
    """같은 프로세스에서 asyncio.run을 30회(정상·취소 섞음). 루프 오류·ResourceWarning·소켓 누수가 없어야 한다."""
    with LlmStub() as stub:
        stub.drip_interval = 0.05
        one_call(stub.url, deadline=5)  # 라이브러리 지연 초기화를 먼저 끝낸다
        gc.collect()
        before = open_fds()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            for i in range(30):
                stub.mode = ("ok", "drip", "hang")[i % 3]
                code, _ = one_call(stub.url, deadline=5 if stub.mode == "ok" else DEADLINE_S)
                assert code == ("OK" if stub.mode == "ok" else "TIMEOUT")
            gc.collect()
        leaks = [w for w in caught if issubclass(w.category, ResourceWarning)]
        assert leaks == [], [str(w.message) for w in leaks]
        assert open_fds() - before <= 2, (before, open_fds())
