"""모델 호출 예약 (작업 2.4, design §8, BE-Q97·BE-Q120, moto)."""

import asyncio
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from langchain_core.messages import HumanMessage

from agent import budget as b
from agent import llm
from domain import ai_session_service as svc
from tests.unit.moto_table import haru_table, set_env

NOW = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)
SID = "ais_01ABCDEFGHJKMNPQRSTVWXYZ00"
FAKE_ENV = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local"}


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        t.put_item(Item=svc.build_agent_session_item(session_id=SID, owner_id="u1", story="s", created_at=NOW, lock_token="t1",
                                                     lock_now_ms=int(NOW.timestamp() * 1000), prompt_version=None, llm_mode="fake",
                                                     llm_provider_label=None))
        yield t


def item(table):
    return table.get_item(Key=svc.session_key(SID))["Item"]


def service(**kw):
    return b.BudgetService(SID, kw.pop("token", "t1"), reserved=kw.pop("reserved", 0), charged=kw.pop("charged", 0), **kw)


def test_six_reservations_then_exhausted(table):
    s = service()
    assert [s.reserve(10).index for _ in range(6)] == [1, 2, 3, 4, 5, 6]
    with pytest.raises(b.BudgetExhausted) as e:
        s.reserve(10)
    assert e.value.kind == "CALLS" and int(item(table)["modelCallsReserved"]) == 6 and int(item(table)["tokenCharged"]) == 60


def test_db_is_source_of_truth_across_runs(table):
    """복구 실행이 잠금 때의 예약 수를 모른 척해도(reserved=0) DB 조건이 6회를 지킨다(보완 4)."""
    for _ in range(4):
        service().reserve(1)
    s2 = service(reserved=0)
    s2.reserve(1)
    s2.reserve(1)
    with pytest.raises(b.BudgetExhausted):
        s2.reserve(1)
    assert int(item(table)["modelCallsReserved"]) == 6 and s2.reserved == 6


def test_token_limit(table):
    s = service()
    s.reserve(29_000)
    with pytest.raises(b.BudgetExhausted) as e:
        s.reserve(1_001)
    assert e.value.kind == "TOKENS" and int(item(table)["modelCallsReserved"]) == 1
    s.reserve(1_000)  # 정확히 30,000은 허용
    assert int(item(table)["tokenCharged"]) == 30_000


def test_lost_lock_is_fence_lost(table):
    table.update_item(Key=svc.session_key(SID), UpdateExpression="SET lockToken = :o", ExpressionAttributeValues={":o": "other"})
    with pytest.raises(b.FenceLost):
        service().reserve(1)
    assert int(item(table)["modelCallsReserved"]) == 0


@pytest.mark.parametrize("err", [ReadTimeoutError(endpoint_url="https://x.invalid"),
                                 ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "UpdateItem")])
def test_uncertain_reservation_means_no_call_and_no_refund(table, monkeypatch, err):
    real = table.update_item

    def landed_then_fail(**kw):  # 서버에는 반영되고 응답은 실패(늦게 반영된 예약)
        real(**kw)
        raise err

    monkeypatch.setattr(table, "update_item", landed_then_fail)
    e = dict(FAKE_ENV, FAKE_LLM_SCENARIO="happy")
    caller = llm.LlmCaller(llm.load_settings(e), env=e, budget=service(table=table))
    with pytest.raises(b.ReservationUncertain):
        asyncio.run(caller.ainvoke([HumanMessage("x")], 5))
    assert caller.fake.calls == [] and caller.calls_made == 0
    monkeypatch.setattr(table, "update_item", real)
    assert int(item(table)["modelCallsReserved"]) == 1  # 환불하지 않는다


def test_failed_call_after_reservation_is_not_refunded(table):
    e = dict(FAKE_ENV, FAKE_LLM_SCENARIO="http_500")
    caller = llm.LlmCaller(llm.load_settings(e), env=e, budget=service())
    with pytest.raises(llm.LlmError):
        asyncio.run(caller.ainvoke([HumanMessage("x")], 5))
    assert int(item(table)["modelCallsReserved"]) == 1


def test_config_error_and_time_budget_do_not_reserve(table):
    e = {"LLM_PROVIDER": "openai_compat"}
    caller = llm.LlmCaller(llm.load_settings(e), env=e, budget=service())
    with pytest.raises(llm.LlmError):
        asyncio.run(caller.ainvoke([HumanMessage("x")], 5))
    e = dict(FAKE_ENV)
    caller = llm.LlmCaller(llm.load_settings(e), env=e, budget=service())
    with pytest.raises(llm.LlmError):
        asyncio.run(caller.ainvoke([HumanMessage("x")], 0))
    assert int(item(table)["modelCallsReserved"]) == 0


def test_key_read_failure_does_not_reserve(table, monkeypatch):
    e = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "http://127.0.0.1:1/v1", "LLM_MODEL": "m", "LLM_API_KEY_PARAM": "/haru/x"}

    class Boom:
        def get_parameter(self, **k):
            raise RuntimeError("no")

    llm.reset_key_cache()
    monkeypatch.setattr(llm, "_ssm", lambda: Boom())
    caller = llm.LlmCaller(llm.load_settings(e), env=e, budget=service())
    with pytest.raises(llm.LlmError) as err:
        asyncio.run(caller.ainvoke([HumanMessage("x")], 5))
    assert err.value.code == "KEY_READ_FAILED" and int(item(table)["modelCallsReserved"]) == 0
    llm.reset_key_cache()


def test_estimate_is_conservative():
    msgs = [HumanMessage("가" * 1000)]
    est = b.estimate_tokens(msgs)
    assert est == 575  # 1000 / 2 × 1.15
    assert b.estimate_tokens(msgs, tools=[{"name": "x"}]) > est
    from agent.llm import usage

    assert est > usage(msgs, HumanMessage(""))[0]  # 6a 보고용 추정(글자 수 / 2)보다 크다


def test_noop_budget():
    n = b.NoopBudget()
    assert [n.reserve(1).index for _ in range(3)] == [1, 2, 3] and n.remaining_calls() == 3


def test_fake_call_index_selects_step():
    e = dict(FAKE_ENV, FAKE_LLM_SCENARIO="bad_json_then_ok")
    caller = llm.LlmCaller(llm.load_settings(e), env=e)
    m = asyncio.run(caller.ainvoke([HumanMessage("x")], 5, call_index=1))
    assert m.content.startswith("{")  # 두 번째 단계(정상 카드)
