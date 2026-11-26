"""장애 복구 F0–F17 (작업 10.8, design §7, 필수). moto + moto 체크포인터 + Fake(ask_once).

강제 종료는 주입 지점에서 BaseException(Crash)을 던져 흉내 낸다(핸들러의 예외 처리도 건너뛴다).
다음 시도는 잠금 만료(lockedUntil을 과거로)를 흉내 낸 뒤 같은 expectedTurn으로 보낸다.
기준선(ask_once): 생성 턴에 예약 3(draft·check·ask), 답변 턴에 예약 1(submit) → 합계 4.
"""

import asyncio
import json

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from agent import checkpoint as ck
from agent import hooks
from agent.llm import LlmCaller, quiet_library_loggers
from domain import ai_session_service as svc
from handlers import ai_agent
from tests.unit.agent_handler_util import agent_env, body_of, ckpt_items, create, session, turns  # noqa: F401

ANSWER = {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "45분"}}
BASE_RESERVED = 4


class Crash(BaseException):
    pass


class At:
    """point가 n번째로 불릴 때 exc를 던진다. Crash면 그 뒤 모든 지점에서도 던진다(강제 종료)."""

    def __init__(self, point, n=1, exc=Crash):
        self.point, self.n, self.exc, self.seen, self.fired = point, n, exc, 0, False

    def __call__(self, p):
        if self.fired and self.exc is Crash:
            raise Crash()  # 죽은 프로세스는 더 진행하지 않는다(LangGraph가 늦게 드러내는 put 예외 대비)
        if p == self.point and not self.fired:
            self.seen += 1
            if self.seen == self.n:
                self.fired = True
                raise self.exc() if isinstance(self.exc, type) else self.exc


class Fence:
    """n번째 체크포인트 쓰기부터 모든 쓰기를 막는다(FencedSaver의 시간 펜스처럼 한 번 넘으면 계속)."""

    def __init__(self, n):
        self.n, self.seen, self.on = n, 0, False

    def __call__(self, p):
        if p == "ckpt_writes":
            self.seen += 1
            self.on = self.on or self.seen >= self.n
        if self.on and p in ("ckpt_writes", "ckpt_put"):
            raise ck.CheckpointFenceError("FENCE_TIME")


@pytest.fixture
def asking(agent_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    v = body_of(create())
    assert v["status"] == "ASKING"
    return v["sessionId"]


def expire_lock(table, sid):
    table.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockedUntil = :p", ExpressionAttributeValues={":p": 1})


def crash_turn(sid, hook):
    hooks.HOOK = hook
    try:
        with pytest.raises(Crash):
            turns(sid, ANSWER)
    finally:
        hooks.HOOK = None


def finish_ok(table, sid, extra_calls=0, attempts_before=None):
    expire_lock(table, sid)
    r = turns(sid, ANSWER)
    assert r["statusCode"] == 200, r["body"]
    v = body_of(r)
    item = session(table, sid)
    assert v["status"] == "READY" and v["turn"] == 2 and v["card"]["estimatedMinutes"] == 45
    assert len(item["answers"]) == 1 and item["answers"][0]["choice"] == "45분"          # 답변은 한 번만
    assert int(item["modelCallsReserved"]) == BASE_RESERVED + extra_calls <= 6
    assert "lockToken" not in item and item["turnAttempts"] == 0 and ckpt_items(sid) == []
    return v, item


def test_baseline(agent_env, asking):
    finish_ok(agent_env, asking)


def test_F0_lock_uncertain(agent_env, asking, monkeypatch):
    real = svc.acquire_lock

    def landed_then_unknown(*a, **k):
        real(*a, **k)
        return svc.UNCERTAIN, None

    monkeypatch.setattr(svc, "acquire_lock", landed_then_unknown)
    assert turns(asking, ANSWER)["statusCode"] == 500
    monkeypatch.setattr(svc, "acquire_lock", real)
    assert session(agent_env, asking)["pendingResume"]["choice"] == "45분"
    assert turns(asking, ANSWER)["statusCode"] == 409  # 잠금이 실제로 걸렸다 → BUSY
    finish_ok(agent_env, asking)


def test_F1_crash_after_lock(agent_env, asking):
    crash_turn(asking, At("lock_after"))
    assert session(agent_env, asking)["status"] == "WORKING"
    finish_ok(agent_env, asking)


def test_F2_crash_before_resume_write(agent_env, asking):
    crash_turn(asking, At("ckpt_writes", 1))
    finish_ok(agent_env, asking)


def test_F3_crash_after_reservation_before_response(agent_env, asking, monkeypatch):
    real = LlmCaller._call
    state = {"done": False}

    async def boom(model, messages, deadline_s, delay_s=0.0):
        if not state["done"]:  # 예약은 끝났고 응답은 아직(강제 종료)
            state["done"] = True
            raise Crash()
        return await real(model, messages, deadline_s, delay_s)

    monkeypatch.setattr(LlmCaller, "_call", staticmethod(boom))
    with pytest.raises(Crash):
        turns(asking, ANSWER)
    assert int(session(agent_env, asking)["modelCallsReserved"]) == BASE_RESERVED  # 예약은 남고 환불 없음
    finish_ok(agent_env, asking, extra_calls=1)


def test_F4_crash_after_model_response(agent_env, asking):
    crash_turn(asking, At("model_response"))
    finish_ok(agent_env, asking, extra_calls=1)  # 외부 호출은 정확히 한 번이 아니다(design §8.5)


@pytest.mark.parametrize(("n", "extra"), [(2, 0), (3, 1), (4, 0), (5, 0)])  # 답변 턴의 쓰기는 5번(재개·ask·decide·gate·final)
def test_F5_crash_between_writes(agent_env, asking, n, extra):
    """n=3은 decide 응답을 받은 뒤 그 쓰기 전에 죽는 경우라 다음 시도가 모델을 한 번 더 부른다(P45 상한 안)."""
    crash_turn(asking, At("ckpt_writes", n))
    finish_ok(agent_env, asking, extra_calls=extra)


@pytest.mark.parametrize(("n", "extra"), [(1, 0), (2, 0), (3, 1)])
def test_F5_crash_before_checkpoint_put(agent_env, asking, n, extra):
    """쓰기는 남고 체크포인트 put 전에 종료. 다음 시도는 기준 체크포인트를 고정(checkpoint_id)해 이어 가므로
    LangGraph(1.2)가 그 단계를 다시 실행한다(시간 여행 재실행, 남은 쓰기를 재적용하지 않음).
    모델 노드(decide, n=3)면 예약이 1회 더 든다. 상한 6 안이고 답변은 한 번만 소비된다(P45)."""
    crash_turn(asking, At("ckpt_put", n))
    finish_ok(agent_env, asking, extra_calls=extra)


def test_F6_divergence_commit_without_model(agent_env, asking, capsys):
    crash_turn(asking, At("before_commit"))
    assert session(agent_env, asking)["turn"] == 1  # 체크포인트는 끝났는데 세션은 이전 턴
    calls = []
    hooks.HOOK = lambda p: calls.append(p) if p == "reserve" else None
    try:
        finish_ok(agent_env, asking)
    finally:
        hooks.HOOK = None
    assert calls == []  # 모델을 다시 부르지 않았다


def test_F7_commit_uncertain_but_landed(agent_env, asking, monkeypatch):
    real = svc.commit_turn

    def landed(*a, **k):
        real(*a, **k)
        return svc.UNCERTAIN

    monkeypatch.setattr(svc, "commit_turn", landed)
    r = turns(asking, ANSWER)
    assert r["statusCode"] == 200 and body_of(r)["status"] == "READY"


def test_F7_commit_uncertain_not_landed(agent_env, asking, monkeypatch):
    real = svc.commit_turn
    monkeypatch.setattr(svc, "commit_turn", lambda *a, **k: svc.UNCERTAIN)
    assert turns(asking, ANSWER)["statusCode"] == 500
    monkeypatch.setattr(svc, "commit_turn", real)
    finish_ok(agent_env, asking)  # 다음 시도가 F6처럼 커밋


def test_F8_commit_condition_lost_lock(agent_env, asking, monkeypatch):
    real = svc.commit_turn

    def steal_then_commit(sid, **k):
        agent_env.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockToken = :o", ExpressionAttributeValues={":o": "other"})
        return real(sid, **k)

    monkeypatch.setattr(svc, "commit_turn", steal_then_commit)
    assert turns(asking, ANSWER)["statusCode"] == 500
    monkeypatch.setattr(svc, "commit_turn", real)
    agent_env.update_item(Key=svc.session_key(asking), UpdateExpression="REMOVE lockToken")
    finish_ok(agent_env, asking)


def test_F8_other_already_committed(agent_env, asking, monkeypatch):
    real = svc.commit_turn

    def other_commits_first(sid, **k):
        real(sid, **k)  # 다른 실행이 먼저 커밋했다고 보고
        return svc.CONDITION

    monkeypatch.setattr(svc, "commit_turn", other_commits_first)
    r = turns(asking, ANSWER)
    assert r["statusCode"] == 200 and body_of(r)["turn"] == 2


def test_F9_delete_failure_does_not_change_response(agent_env, asking, monkeypatch):
    monkeypatch.setattr(ck.FencedSaver, "delete_thread", lambda self, tid: (_ for _ in ()).throw(RuntimeError("x")))
    r = turns(asking, ANSWER)
    assert r["statusCode"] == 200 and body_of(r)["status"] == "READY" and ckpt_items(asking)  # TTL이 지운다


def test_F10_checkpoint_read_failure(agent_env, asking, monkeypatch):
    real = ck.FencedSaver.list

    def boom(self, *a, **k):
        raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "Query")

    monkeypatch.setattr(ck.FencedSaver, "list", boom)
    assert turns(asking, ANSWER)["statusCode"] == 500
    item = session(agent_env, asking)
    assert "lockToken" not in item and item["turn"] == 1 and item["pendingResume"]["choice"] == "45분"
    monkeypatch.setattr(ck.FencedSaver, "list", real)
    r = turns(asking, ANSWER)  # 잠금이 풀려 바로 재시도된다
    assert body_of(r)["status"] == "READY" and len(session(agent_env, asking)["answers"]) == 1


def test_F11_checkpoint_missing_closes_with_candidate(agent_env, asking):
    ai_agent.store().shared.delete_thread(asking)
    r = turns(asking, ANSWER)
    v = body_of(r)
    item = session(agent_env, asking)
    assert v["status"] == "READY" and v["degraded"] is True and item["turn"] == 2
    assert int(item["modelCallsReserved"]) == 3  # 모델을 부르지 않았다


def test_F12_resume_state_mismatch(agent_env, asking):
    agent_env.update_item(Key=svc.session_key(asking), UpdateExpression="SET #s = :w, pendingResume = :p",
                          ExpressionAttributeNames={"#s": "status"},
                          ExpressionAttributeValues={":w": "WORKING", ":p": {"resumeId": "r1-q9", "questionId": "q9", "choice": "x"}})
    r = turns(asking, {"expectedTurn": 1})
    assert r["statusCode"] == 200 and body_of(r)["degraded"] is True
    assert int(session(agent_env, asking)["modelCallsReserved"]) == 3


def test_F13_recovery_limit(agent_env, asking):
    for _ in range(3):
        crash_turn(asking, At("lock_after"))
        expire_lock(agent_env, asking)
    assert session(agent_env, asking)["turnAttempts"] == 3
    r = turns(asking, ANSWER)  # 네 번째 잠금 → 결정적 폐쇄
    item = session(agent_env, asking)
    assert body_of(r)["status"] == "READY" and body_of(r)["degraded"] is True and item["turn"] == 2
    assert int(item["recoveries"]) == 3


def test_F14_fence_releases_lock_same_turn(agent_env, asking):
    hooks.HOOK = Fence(3)
    try:
        r = turns(asking, ANSWER)
    finally:
        hooks.HOOK = None
    v = body_of(r)
    item = session(agent_env, asking)
    assert r["statusCode"] == 200 and v["status"] == "WORKING" and v["turn"] == 1 and v["question"] is None   # BE-Q121
    assert "lockToken" not in item and item["turnAttempts"] == 1
    r2 = turns(asking, {"expectedTurn": 1})  # 프론트는 같은 turn으로 이어서 보낸다(answer 없이)
    v2 = body_of(r2)
    assert v2["status"] == "READY" and v2["turn"] == 2 and len(session(agent_env, asking)["answers"]) == 1


def test_F14_fence_on_generation_commits_turn_1_working(agent_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    hooks.HOOK = Fence(6)
    try:
        v = body_of(create())
    finally:
        hooks.HOOK = None
    assert v["status"] == "WORKING" and v["turn"] == 1
    v2 = body_of(turns(v["sessionId"], {"expectedTurn": 1}))
    assert v2["status"] == "ASKING" and v2["turn"] == 2


def test_F15_crash_during_generation(agent_env, monkeypatch):
    from tests.unit.ai_handler_util import quota_count

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    hooks.HOOK = At("model_response")
    try:
        with pytest.raises(Crash):
            create()
    finally:
        hooks.HOOK = None
    items = [i for i in agent_env.scan()["Items"] if i["PK"].startswith("AISESSION#")]
    assert len(items) == 1 and items[0]["turn"] == 0 and items[0]["status"] == "WORKING" and quota_count(agent_env) == 1
    assert int(items[0]["modelCallsReserved"]) == 1


def test_F16_late_unknown_branch_ignored(agent_env, asking):
    """이전 시도가 남긴 진행 + 모르는 실행의 늦은 쓰기(포크)가 있어도 정당한 가지에서 이어 간다."""
    from langgraph.types import Command

    from agent.graph import build_agent_graph
    from tests.unit.agent_util import caller, config

    crash_turn(asking, At("ckpt_put", 2))
    item = session(agent_env, asking)
    saver = ai_agent.store().for_run(session_ttl=int(item["ttl"]))
    app = build_agent_graph(saver)
    snap = app.get_state({"configurable": {"thread_id": asking, "checkpoint_id": item["checkpointId"]}})
    iid = [i.id for t in snap.tasks for i in t.interrupts][0]
    cfg = config(caller("ask_once"), tid=asking, run_turn=2, ckpt=item["checkpointId"])
    cfg["metadata"] = {"runTurn": 2, "runId": "ghost", "runAttempt": 1, "resumeId": "r1-q1"}
    try:
        asyncio.run(app.ainvoke(Command(resume={iid: {"questionId": "q1", "resumeId": "r1-q1", "choice": "1시간"}}), cfg))
    except Exception:  # noqa: BLE001 - 유령 실행은 실패해도 된다(가지만 남으면 됨)
        pass
    v, item = finish_ok(agent_env, asking)
    assert item["answers"][0]["choice"] == "45분"  # 유령 가지의 '1시간'이 섞이지 않는다


def test_F17_only_polluted_branches(agent_env, asking):
    """기준 아래 가지가 모두 표지 오염(다른 턴 번호)이면 기준에서 다시 진행한다(예약 상한 안)."""
    from langgraph.types import Command

    from agent.graph import build_agent_graph
    from tests.unit.agent_util import caller, config

    item = session(agent_env, asking)
    saver = ai_agent.store().for_run(session_ttl=int(item["ttl"]))
    app = build_agent_graph(saver)
    snap = app.get_state({"configurable": {"thread_id": asking, "checkpoint_id": item["checkpointId"]}})
    iid = [i.id for t in snap.tasks for i in t.interrupts][0]
    cfg = config(caller("ask_once"), tid=asking, run_turn=7, ckpt=item["checkpointId"])
    cfg["metadata"] = {"runTurn": 7, "runId": "ghost", "runAttempt": 1}
    asyncio.run(app.ainvoke(Command(resume={iid: {"questionId": "q1", "resumeId": "r1-q1", "choice": "45분"}}), cfg))
    v, item = finish_ok(agent_env, asking)


def test_duplicate_answer_with_different_value(agent_env, asking):
    """같은 질문에 다른 답이 다시 와도 첫 답이 이긴다(BE-Q118)."""
    crash_turn(asking, At("lock_after"))
    expire_lock(agent_env, asking)
    r = turns(asking, {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "1시간"}})  # WORKING + 같은 qid → 멱등
    item = session(agent_env, asking)
    assert body_of(r)["status"] == "READY" and item["answers"][0]["choice"] == "45분"


def test_reservation_uncertain_pauses(agent_env, asking, monkeypatch):
    real = agent_env.update_item
    state = {"n": 0}

    def flaky(**kw):
        if "modelCallsReserved" in kw.get("UpdateExpression", "") and state["n"] == 0:
            state["n"] += 1
            raise ReadTimeoutError(endpoint_url="https://x.invalid")
        return real(**kw)

    monkeypatch.setattr(agent_env, "update_item", flaky)
    v = body_of(turns(asking, ANSWER))
    assert v["status"] == "WORKING" and v["turn"] == 2
    monkeypatch.setattr(agent_env, "update_item", real)
    v2 = body_of(turns(asking, {"expectedTurn": 2}))
    assert v2["status"] == "READY"
    item = session(agent_env, asking)
    assert len(item["answers"]) == 1 and int(item["modelCallsReserved"]) == BASE_RESERVED


def test_logs_have_no_story_or_answer(agent_env, asking, caplog):
    import logging

    quiet_library_loggers()  # 핸들러 init과 같은 설정(픽스처는 init을 건너뛴다)
    caplog.set_level(logging.DEBUG)
    crash_turn(asking, At("model_response"))
    expire_lock(agent_env, asking)
    turns(asking, ANSWER)
    text = caplog.text
    assert "출근길" not in text and "45분" not in text and "하천" not in text
    assert json.dumps(session(agent_env, asking)["trace"], ensure_ascii=False, default=str).count("45분") == 0


# ---------------------------------------------------------------- BE-Q129: 초안 재시도 (보완, moto 체크포인터)


class Clock:
    """남은 시간을 테스트가 정한다(핸들러 context 흉내)."""

    def __init__(self, ms: int) -> None:
        self.ms = ms

    def get_remaining_time_in_millis(self) -> int:
        return self.ms


def test_F18_crash_on_second_draft_after_checkpointed_first_attempt(agent_env, monkeypatch):
    """첫 초안이 체크포인트에 남은 뒤(시간 부족으로 WORKING) 재개 턴의 두 번째 초안 응답 뒤 종료.
    복구는 첫 시도를 다시 하지 않고(추적의 초안 항목은 2개), 예약은 6 이하다. 생성 턴 자체의 종료는 설계 §4.1대로 복구하지 않는다."""
    from agent import hooks
    from tests.unit.agent_handler_util import create, session, turns, body_of, only_session

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "schema_then_ok")
    clock = Clock(25_000)
    hooks.HOOK = lambda p: setattr(clock, "ms", 5_000) if p == "model_response" else None
    try:
        v1 = body_of(create(ctx=clock))
    finally:
        hooks.HOOK = None
    assert v1["status"] == "WORKING"
    sid = v1["sessionId"]
    clock.ms = 25_000
    hooks.HOOK = At("model_response", 1)  # 재개 턴의 두 번째 초안 응답 뒤
    try:
        with pytest.raises(Crash):
            turns(sid, {"expectedTurn": v1["turn"]}, ctx=clock)
    finally:
        hooks.HOOK = None
    expire_lock(agent_env, sid)
    v2 = body_of(turns(sid, {"expectedTurn": v1["turn"]}, ctx=clock))
    assert v2["status"] == "READY", v2
    assert [t["tool"] for t in v2["trace"]].count("draft") == 2  # 첫 시도는 체크포인트에서 이어졌다(다시 기록되지 않는다)
    item = session(agent_env, sid)
    assert int(item["modelCallsReserved"]) <= 6 and int(item["modelCallsReserved"]) >= 3  # 첫 시도 + 잃은 응답 + 다시 한 응답 + 제출
    assert ckpt_items(sid) == []


def test_F19_time_short_before_retry_pauses_and_next_request_finishes(agent_env, monkeypatch):
    """첫 초안 뒤 남은 시간이 12초 미만이면 재시도 전에 WORKING으로 멈춘다. 다음 요청은 초안 2회째부터 이어 간다."""
    from agent import hooks
    from tests.unit.agent_handler_util import create, session, turns, body_of

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "schema_then_ok")
    clock = Clock(25_000)
    hooks.HOOK = lambda p: setattr(clock, "ms", 5_000) if p == "model_response" else None
    try:
        v1 = body_of(create(ctx=clock))
    finally:
        hooks.HOOK = None
    assert v1["status"] == "WORKING", v1
    sid = v1["sessionId"]
    before = session(agent_env, sid)
    assert int(before["modelCallsReserved"]) == 1  # 첫 초안만 예약됐다
    clock.ms = 25_000
    r = turns(sid, {"expectedTurn": v1["turn"]}, ctx=clock)
    v2 = body_of(r)
    assert r["statusCode"] == 200 and v2["status"] == "READY", v2
    assert [t["tool"] for t in v2["trace"]].count("draft") == 2
    assert int(session(agent_env, sid)["modelCallsReserved"]) <= 6
