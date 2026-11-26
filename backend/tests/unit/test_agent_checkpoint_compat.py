"""DynamoDBSaver 내부 속성 의존의 호환성 검사 (작업 3.6, design §24.1, BE-Q119).

라이브러리 버전을 올리면 이 테스트가 먼저 깨진다. 그때 design §24.1과 설계 검증 V1–V13을 다시 확인한다.
"""

import asyncio
import importlib.metadata as md
import pathlib
import re
import threading
import time

import boto3
import pytest

from agent import checkpoint as ck
from tests.unit.test_agent_checkpoint import TABLE, create_table, graph, hist, run

LOCK = pathlib.Path(__file__).resolve().parents[2] / "src" / "ai-requirements.lock"


def locked(name):
    m = re.search(rf"^{re.escape(name)}==([^\s\\]+)", LOCK.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


@pytest.mark.parametrize("pkg", ["langgraph", "langgraph-checkpoint", "langgraph-checkpoint-aws"])
def test_installed_versions_match_lock(pkg):
    assert md.version(pkg) == locked(pkg), "버전이 바뀌었다. design §24.1(BE-Q119)과 V1–V13을 다시 확인하라"


@pytest.fixture
def env(monkeypatch):
    from moto import mock_aws

    for k, v in {"AWS_DEFAULT_REGION": "ap-northeast-2", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        c = boto3.client("dynamodb", region_name="ap-northeast-2")
        create_table(c)
        yield c


def test_internal_attributes_exist(env):
    store = ck.CheckpointStore(TABLE, region_name="ap-northeast-2")
    s = store.shared
    assert hasattr(s, "repo") and hasattr(s, "storage") and hasattr(s.repo, "ttl_seconds") and hasattr(s.storage, "ttl_seconds")
    assert s.repo.storage is s.storage and hasattr(s, "serializer") and callable(s.serializer.serialize)
    for m in ("put", "put_writes", "get_tuple", "list", "delete_thread"):
        assert callable(getattr(s, m))


def test_only_iam_operations_and_metadata_markers(env):
    store = ck.CheckpointStore(TABLE, region_name="ap-northeast-2")
    ops = []
    store.shared.client.meta.events.register("before-call.dynamodb.*", lambda model, **kw: ops.append(model.name))
    saver = store.for_run(session_ttl=int(time.time()) + 3600)
    app = graph(saver)
    run(app, {"log": []}, "c1", 1, "R1", 1)
    h = hist(saver, "c1")
    asyncio.run(saver.adelete_thread("c1"))
    assert set(ops) <= {"GetItem", "PutItem", "Query", "BatchGetItem", "BatchWriteItem"}, set(ops)
    assert all((t.metadata or {}).get("runId") == "R1" and t.metadata.get("runTurn") == 1 and t.metadata.get("runAttempt") == 1 for t in h)


def test_payload_bytes_measured(env):
    store = ck.CheckpointStore(TABLE, region_name="ap-northeast-2")
    saver = store.for_run(session_ttl=int(time.time()) + 3600)
    run(graph(saver), {"log": ["가" * 500]}, "c2", 1, "R1", 1)
    assert saver.max_payload > 500


def test_thread_count_stable(env):
    store = ck.CheckpointStore(TABLE, region_name="ap-northeast-2")
    before = threading.active_count()
    for i in range(5):
        run(graph(store.for_run(session_ttl=int(time.time()) + 3600)), {"log": []}, f"c3{i}", 1, "R1", 1)
    assert threading.active_count() <= before + 1
