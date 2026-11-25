"""운영자 복구 스크립트 (moto SQS·DynamoDB). Validates: Requirement 9.3 · BE-Q68"""

import importlib.util
import json
import sys
from pathlib import Path

import boto3
import pytest

pytest.importorskip("moto")

from tests.unit.photo_fixtures import NOW, SUHYUN, claimed, photo_env, record, s3_record, with_photo  # noqa: E402

SCRIPT = Path(__file__).parents[2] / "scripts" / "photo_dlq_recover.py"
spec = importlib.util.spec_from_file_location("photo_dlq_recover", SCRIPT)
rec_mod = importlib.util.module_from_spec(spec)
sys.modules["photo_dlq_recover"] = rec_mod
spec.loader.exec_module(rec_mod)

FORBIDDEN = ("delete_message", "delete_message_batch", "send_message", "send_message_batch", "change_message_visibility",
             "change_message_visibility_batch", "purge_queue", "start_message_move_task")


@pytest.fixture
def env(monkeypatch):
    with photo_env(monkeypatch) as (table, _):
        sqs = boto3.client("sqs", region_name="ap-northeast-2")
        dlq = sqs.create_queue(QueueName="PhotoDLQ")["QueueUrl"]
        q = sqs.create_queue(QueueName="PhotoQueue")["QueueUrl"]
        called = []
        for name in FORBIDDEN:
            monkeypatch.setattr(sqs, name, lambda *a, _n=name, **k: called.append(_n) or (_ for _ in ()).throw(AssertionError(f"{_n} 금지")))
        yield table, sqs, dlq, q, called


def put_dlq(sqs, dlq, key):
    # 금지 목록에 send_message가 있으므로 테스트 준비는 원래 메서드로 한다
    type(sqs).send_message(sqs, QueueUrl=dlq, MessageBody=json.dumps({"Records": [s3_record(key, "e")]}))


def scenario(table, sqs, dlq):
    """판정표 각 줄을 하나씩 만든다. {판정: (planId, claimId, key)}"""
    out = {}
    pid, cid = claimed(key="k-rec")
    key = with_photo(pid, cid)
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :p", ExpressionAttributeValues={":p": "PROCESSING"})
    out["recover"] = (pid, cid, key)
    pid, cid = claimed(key="k-fail")
    key = with_photo(pid, cid)
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :p", ExpressionAttributeValues={":p": "FAILED"})
    out["already_failed"] = (pid, cid, key)
    pid, cid = claimed(key="k-stale")
    key = with_photo(pid, cid)
    with_photo(pid, cid)  # 교체됨 → 지난 키
    out["stale_message"] = (pid, cid, key)
    pid, cid = claimed(key="k-pend")
    key = with_photo(pid, cid)
    out["upload_pending"] = (pid, cid, key)
    pid, cid = claimed(key="k-ready")
    key = with_photo(pid, cid)
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :p", ExpressionAttributeValues={":p": "READY"})
    out["abnormal_ready"] = (pid, cid, key)
    for _, _, k in out.values():
        put_dlq(sqs, dlq, k)
    put_dlq(sqs, dlq, "not/a/photo.jpg")
    return out


def snapshot(table):
    return sorted(json.dumps(i, sort_keys=True, default=str) for i in table.scan(ConsistentRead=True)["Items"])


def test_dry_run_judges_and_writes_nothing(env):
    table, sqs, dlq, q, called = env
    sc = scenario(table, sqs, dlq)
    before = snapshot(table)
    lines = []
    res = rec_mod.run(sqs=sqs, cw=None, dlq_url=dlq, queue_url=q, function=None, apply=False, out=lines.append)
    assert res["counts"] == {"recover": 1, "already_failed": 1, "stale_message": 1, "upload_pending": 1, "abnormal_ready": 1, "unparseable": 1}
    assert snapshot(table) == before and called == []
    text = "\n".join(lines)
    assert "mode=dry-run" in text
    for pid, cid, key in sc.values():
        assert key not in text and cid not in text and pid not in text and "u-suhyun" not in text


def test_apply_recovers_only_processing(env):
    table, sqs, dlq, q, called = env
    sc = scenario(table, sqs, dlq)
    res = rec_mod.run(sqs=sqs, cw=None, dlq_url=dlq, queue_url=q, function=None, apply=True, out=lambda *_: None)
    assert res["counts"]["applied"] == 1 and called == []
    pid, cid, _ = sc["recover"]
    r = record(pid, cid)
    assert r["photoStatus"] == "FAILED" and r["photoError"] == "RETRY_EXHAUSTED"
    for name in ("already_failed", "stale_message", "upload_pending", "abnormal_ready"):
        pid, cid, _ = sc[name]
        assert "RETRY_EXHAUSTED" != record(pid, cid).get("photoError")


def test_apply_condition_changed_meanwhile(env, monkeypatch):
    table, sqs, dlq, q, called = env
    sc = scenario(table, sqs, dlq)
    pid, cid, key = sc["recover"]
    real_judge = rec_mod.judge

    def judge_then_change(k):
        verdict = real_judge(k)
        if verdict[0] == "recover":  # 판정과 쓰기 사이에 사용자가 글로 완료
            from domain import claim_service as cs

            cs.complete_by_user(cid, SUHYUN, "TEXT_ONLY", NOW)
        return verdict

    monkeypatch.setattr(rec_mod, "judge", judge_then_change)
    res = rec_mod.run(sqs=sqs, cw=None, dlq_url=dlq, queue_url=q, function=None, apply=True, out=lambda *_: None)
    assert res["counts"].get("changed_meanwhile") == 1 and "applied" not in res["counts"]
    assert record(pid, cid)["photoStatus"] == "DISCARDED"


def test_safety_warning_when_queue_busy(env):
    table, sqs, dlq, q, called = env
    type(sqs).send_message(sqs, QueueUrl=q, MessageBody="{}")
    sqs.receive_message(QueueUrl=q, VisibilityTimeout=300)  # 처리 중(in flight)
    lines = []
    res = rec_mod.run(sqs=sqs, cw=None, dlq_url=dlq, queue_url=q, function=None, apply=False, out=lines.append)
    assert res["safety"]["queue_in_flight"] == 1 and any(line.startswith("WARNING") for line in lines)


def test_dlq_messages_are_only_received(env):
    table, sqs, dlq, q, called = env
    scenario(table, sqs, dlq)
    rec_mod.run(sqs=sqs, cw=None, dlq_url=dlq, queue_url=q, function=None, apply=True, out=lambda *_: None)
    attrs = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    assert int(attrs["ApproximateNumberOfMessages"]) + int(attrs["ApproximateNumberOfMessagesNotVisible"]) == 6  # 하나도 지우지 않았다
    assert called == []


def test_cli_requires_stack_and_defaults_to_dry_run(monkeypatch):
    with pytest.raises(SystemExit):
        rec_mod.main([])  # --stack 필수
    seen = {}
    monkeypatch.setattr(rec_mod, "resolve", lambda stack, region: {"dlq_url": "d", "queue_url": "q", "table": "HaruTable", "function": "f"})
    monkeypatch.setattr(rec_mod, "run", lambda **kw: seen.update(kw))
    monkeypatch.setattr(rec_mod.boto3, "resource", lambda *a, **k: type("R", (), {"Table": lambda self, n: n})())
    monkeypatch.setattr(rec_mod.boto3, "client", lambda *a, **k: None)
    monkeypatch.setattr(rec_mod.ddb, "use_table", lambda t: None)  # 전역 테이블을 더럽히지 않는다
    rec_mod.main(["--stack", "haru-dev"])
    assert seen["apply"] is False
    rec_mod.main(["--stack", "haru-dev", "--apply"])
    assert seen["apply"] is True
