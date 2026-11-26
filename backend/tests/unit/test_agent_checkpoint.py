"""체크포인트 저장소·울타리·계보 선택·재개 분류 (작업 3.5, design §6, moto 위 DynamoDBSaver)."""

import asyncio
import threading
import time
from typing import Any, TypedDict

import boto3
import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent import checkpoint as ck

TABLE = "HaruAgentCheckpoints"


def create_table(client):
    client.create_table(TableName=TABLE, BillingMode="PAY_PER_REQUEST",
                        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
                        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}])


@pytest.fixture
def store(monkeypatch):
    from moto import mock_aws

    for k, v in {"AWS_DEFAULT_REGION": "ap-northeast-2", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        c = boto3.client("dynamodb", region_name="ap-northeast-2")
        create_table(c)
        s = ck.CheckpointStore(TABLE, region_name="ap-northeast-2")
        s.client = c
        yield s


class S(TypedDict, total=False):
    log: list
    consumed_resume_ids: list
    outcome: str
    outcome_turn: int


def a(s):
    return {"log": (s.get("log") or []) + ["a"], "outcome": "ASKING", "outcome_turn": 1}


def ask(s):
    v = interrupt({"kind": "question", "questionId": "q1"})
    return {"log": s["log"] + ["ask"], "consumed_resume_ids": (s.get("consumed_resume_ids") or []) + [v["resumeId"]]}


def b(s):
    return {"log": s["log"] + ["b"], "outcome": "READY", "outcome_turn": 2}


def graph(saver):
    g = StateGraph(S)
    for n, f in (("a", a), ("ask", ask), ("b", b)):
        g.add_node(n, f)
    g.add_edge(START, "a")
    g.add_edge("a", "ask")
    g.add_edge("ask", "b")
    g.add_edge("b", END)
    return g.compile(checkpointer=saver)


def run(app, inp, tid, run_turn, run_id, attempt, ckpt=None, resume_id=None):
    cfg = {"configurable": {"thread_id": tid, **({"checkpoint_id": ckpt} if ckpt else {})},
           "metadata": {"runTurn": run_turn, "runId": run_id, "runAttempt": attempt, "resumeId": resume_id}}
    return asyncio.run(app.ainvoke(inp, cfg, durability="sync"))


def hist(saver, tid):
    return list(saver.list({"configurable": {"thread_id": tid}}))


def first_turn(store, tid="s1"):
    saver = store.for_run(session_ttl=int(time.time()) + 3600)
    app = graph(saver)
    run(app, {"log": []}, tid, 1, "R1", 1)
    base = ck.checkpoint_id_of(saver.last_config)
    return app, saver, base


ANS = {"questionId": "q1", "choice": "45분", "resumeId": "r1-q1"}


def test_new_run_and_last_config(store):
    app, saver, base = first_turn(store)
    assert base and saver.writes > 0 and saver.max_payload > 0
    tip = ck.select_tip(hist(saver, "s1"), base=base, run_turn=2, turn_runs=["R2"], my_run_id="R2", known_resume_ids={"r1-q1"})
    assert tip.kind == "TIP" and tip.checkpoint_id == base  # 이번 턴 진행이 없으면 기준


def test_tip_picks_legit_progress_and_rejects_others(store):
    app, saver, base = first_turn(store)
    # 시도 1(R2): 기준에서 정상 진행
    run(app, Command(resume=ANS), "s1", 2, "R2", 1, ckpt=base, resume_id="r1-q1")
    # 모르는 실행(R9)이 같은 기준에서 갈라져 늦게 씀(포크) — 나중에 쓴 쪽이 '최신'
    run(app, Command(resume=dict(ANS, resumeId="r1-q1")), "s1", 2, "R9", 1, ckpt=base)
    h = hist(saver, "s1")
    tip = ck.select_tip(h, base=base, run_turn=2, turn_runs=["R2", "R3"], my_run_id="R3", known_resume_ids={"r1-q1"})
    r2_ids = {ck.checkpoint_id_of(t.config) for t in h if (t.metadata or {}).get("runId") == "R2"}
    assert tip.checkpoint_id in r2_ids and tip.rejected > 0
    latest = ck.checkpoint_id_of(saver.get_tuple({"configurable": {"thread_id": "s1"}}).config)
    assert (latest not in r2_ids) and tip.checkpoint_id != latest  # 최신을 믿지 않는다


def test_tip_rejects_wrong_turn_wrong_attempt_unknown_resume(store):
    app, saver, base = first_turn(store)
    run(app, Command(resume=dict(ANS, resumeId="r1-zz")), "s1", 2, "R2", 1, ckpt=base)  # 모르는 resumeId 소비
    h = hist(saver, "s1")
    assert ck.select_tip(h, base=base, run_turn=2, turn_runs=["R2"], my_run_id="X", known_resume_ids={"r1-q1"}).checkpoint_id == base
    assert ck.select_tip(h, base=base, run_turn=3, turn_runs=["R2"], my_run_id="X", known_resume_ids={"r1-zz"}).checkpoint_id == base
    assert ck.select_tip(h, base=base, run_turn=2, turn_runs=["Q", "R2"], my_run_id="X",  # R2가 2번째 시도로 기록 → attempt 불일치
                         known_resume_ids={"r1-zz"}).checkpoint_id == base
    ok = ck.select_tip(h, base=base, run_turn=2, turn_runs=["R2"], my_run_id="X", known_resume_ids={"r1-zz"})
    assert ok.checkpoint_id != base


def test_tip_prefers_higher_attempt(store):
    app, saver, base = first_turn(store)
    # 시도 2(R3)가 기준에서 진행, 그 뒤 시도 1(R2)의 늦은 쓰기가 기준 아래에 반영됨
    run(app, Command(resume=ANS), "s1", 2, "R3", 2, ckpt=base, resume_id="r1-q1")
    run(app, Command(resume=ANS), "s1", 2, "R2", 1, ckpt=base, resume_id="r1-q1")
    h = hist(saver, "s1")
    tip = ck.select_tip(h, base=base, run_turn=2, turn_runs=["R2", "R3", "R4"], my_run_id="R4", known_resume_ids={"r1-q1"})
    t = {ck.checkpoint_id_of(x.config): x for x in h}[tip.checkpoint_id]
    assert t.metadata["runId"] == "R3"


def test_missing_base_and_new_thread(store):
    app, saver, base = first_turn(store)
    assert ck.select_tip(hist(saver, "s1"), base="nope", run_turn=2, turn_runs=[], my_run_id="x", known_resume_ids=set()).kind == "MISSING"
    assert ck.select_tip([], base=None, run_turn=1, turn_runs=["R1"], my_run_id="R1", known_resume_ids=set()).kind == "NEW"
    # 생성 턴 재시도: 뿌리까지의 사슬이 이전 시도(R1)면 그 가지를 쓴다
    tip = ck.select_tip(hist(saver, "s1"), base=None, run_turn=1, turn_runs=["R1", "R1b"], my_run_id="R1b", known_resume_ids=set())
    assert tip.kind == "TIP" and tip.checkpoint_id == base


def test_classify_resume_cases(store):
    app, saver, base = first_turn(store)
    snap = app.get_state({"configurable": {"thread_id": "s1", "checkpoint_id": base}})
    pr = {"resumeId": "r1-q1", "questionId": "q1", "choice": "45분"}
    d = ck.classify_resume(snap, pending_resume=pr, run_turn=2)
    assert d.kind == ck.RESUME_ANSWER and d.value == {"questionId": "q1", "resumeId": "r1-q1", "choice": "45분"} and d.interrupt_id
    assert ck.classify_resume(snap, pending_resume=None, run_turn=1).kind == ck.COMMIT_AS_IS  # 이번 턴(1)에 질문까지 감
    assert ck.classify_resume(snap, pending_resume=None, run_turn=2).kind == ck.ANOMALY
    run(app, Command(resume={d.interrupt_id: d.value}), "s1", 2, "R2", 1, ckpt=base, resume_id="r1-q1")
    done = app.get_state({"configurable": {"thread_id": "s1"}})
    assert ck.classify_resume(done, pending_resume=pr, run_turn=2).kind == ck.COMMIT_AS_IS  # 소비됨 + 이번 턴 종료
    assert ck.classify_resume(done, pending_resume=None, run_turn=3).kind == ck.ANOMALY


def test_fence_blocks_write_start(store):
    saver = store.for_run(session_ttl=int(time.time()) + 3600, fence_deadline=time.monotonic() - 1)
    with pytest.raises(ck.CheckpointFenceError):
        run(graph(saver), {"log": []}, "s2", 1, "R1", 1)
    assert hist(saver, "s2") == []
    saver2 = store.for_run(session_ttl=int(time.time()) + 3600, remaining_ms=lambda: 2_000)
    with pytest.raises(ck.CheckpointFenceError):
        run(graph(saver2), {"log": []}, "s3", 1, "R1", 1)


def test_ttl_never_exceeds_session(store):
    now = time.time()
    session_ttl = int(now) + 7200
    saver = store.for_run(session_ttl=session_ttl, now_epoch=now)
    run(graph(saver), {"log": []}, "s4", 1, "R1", 1)
    items = store.client.scan(TableName=TABLE)["Items"]
    mine = [i for i in items if "s4" in i["PK"]["S"]]
    assert mine and all(int(i["ttl"]["N"]) <= session_ttl for i in mine)
    assert store.for_run(session_ttl=int(now) + 10, now_epoch=now).repo.ttl_seconds == ck.MIN_TTL_S


def test_run_copies_are_independent(store):
    a1 = store.for_run(session_ttl=int(time.time()) + 1000)
    a2 = store.for_run(session_ttl=int(time.time()) + 999_999)
    assert a1.repo.ttl_seconds != a2.repo.ttl_seconds and store.shared.repo.ttl_seconds == 30 * 86400
    assert a1.repo.storage is a1.storage and a1.storage is not store.shared.storage


def test_no_background_threads(store):
    before = threading.active_count()
    saver = store.for_run(session_ttl=int(time.time()) + 3600)
    app = graph(saver)
    run(app, {"log": []}, "s5", 1, "R1", 1)
    asyncio.run(saver.adelete_thread("s5"))
    assert threading.active_count() <= before + 1


def test_delete_thread(store):
    app, saver, base = first_turn(store, "s6")
    asyncio.run(saver.adelete_thread("s6"))
    assert hist(saver, "s6") == []


def test_hook_sees_writes(store):
    seen = []
    saver = store.for_run(session_ttl=int(time.time()) + 3600, hook=seen.append)
    run(graph(saver), {"log": []}, "s7", 1, "R1", 1)
    assert "ckpt_put" in seen and "ckpt_writes" in seen
