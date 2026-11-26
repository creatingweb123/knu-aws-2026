"""로컬 통합: Floci HaruAgentCheckpoints에서 DynamoDBSaver 연결 확인 (6a 작업 15.3, design §18, BE-Q21·BE-Q84).

제품 경로(레벨 0 그래프)에는 연결하지 않는다. 6b가 쓸 체크포인터가 로컬 에뮬레이터에서 동작하는지만 본다.
스레드 ID는 t6a_ + 임의값이고, 끝나면 delete_thread 뒤 그 스레드 항목 0건을 확인한다(실패해도 정리).
"""

import asyncio
import uuid
from typing import TypedDict

import pytest

from tests.local.conftest import AWS, boto

pytestmark = pytest.mark.local

TABLE = "HaruAgentCheckpoints"


class S(TypedDict, total=False):
    a: str
    b: str


def _graph():
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt
    from langgraph_checkpoint_aws import DynamoDBSaver

    from agent.llm import sdk_config

    def ask(state: S) -> dict:
        return {"b": interrupt({"kind": "question"})}

    g = StateGraph(S)
    g.add_node("ask", ask)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    saver = DynamoDBSaver(table_name=TABLE, region_name="ap-northeast-2", endpoint_url=AWS, ttl_seconds=30 * 86400,
                          consistent_read=True, boto_config=sdk_config({}))
    return g.compile(checkpointer=saver), saver


def _items(tid):
    items, kwargs = [], {"TableName": TABLE}
    ddb = boto("dynamodb")
    while True:
        page = ddb.scan(**kwargs)
        items += [i for i in page["Items"] if tid in i["PK"]["S"]]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_interrupt_resume_delete(mode, monkeypatch):
    from langgraph.types import Command

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")  # 로컬 에뮬레이터 전용 값
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    app, saver = _graph()
    tid = f"t6a_{uuid.uuid4().hex[:12]}"
    cfg = {"configurable": {"thread_id": tid}}
    try:
        if mode == "sync":
            first = app.invoke({"a": "1"}, cfg, durability="sync")
            state = app.get_state(cfg)
            resumed = app.invoke(Command(resume="45분"), cfg, durability="sync")
        else:
            async def go():
                r = await app.ainvoke({"a": "1"}, cfg, durability="sync")
                st = await app.aget_state(cfg)
                r2 = await app.ainvoke(Command(resume="45분"), cfg, durability="sync")
                return r, st, r2

            first, state, resumed = asyncio.run(go())
        assert "__interrupt__" in first
        assert any(t.interrupts for t in state.tasks)  # 대기 중인 interrupt
        assert resumed.get("b") == "45분"
        items = _items(tid)
        assert items and all("ttl" in i for i in items), "모든 체크포인트 항목에 ttl"
        print(f"{mode}: thread items={len(items)}")
    finally:
        if mode == "sync":
            saver.delete_thread(tid)
        else:
            asyncio.run(saver.adelete_thread(tid))
    assert _items(tid) == []
