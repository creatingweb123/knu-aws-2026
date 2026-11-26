"""운영자 복구 스크립트 (moto SQS·DynamoDB). Validates: Requirement 9.3 · BE-Q68"""

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
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


T0 = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)
MAPPING = "11111111-2222-3333-4444-555555555555"
LAMBDA_FORBIDDEN = ("update_event_source_mapping", "delete_event_source_mapping", "create_event_source_mapping",
                    "update_function_configuration", "put_function_concurrency", "invoke")


class FakeLambda:
    def __init__(self, state="Disabled", age_s=600, extra=None, fail=None):
        self.items = [{"UUID": MAPPING, "State": state, "LastModified": T0 - timedelta(seconds=age_s)}] + list(extra or [])
        self.fail = fail
        self.calls = []
        for name in LAMBDA_FORBIDDEN:
            setattr(self, name, lambda *a, _n=name, **k: (_ for _ in ()).throw(AssertionError(f"{_n} 금지")))

    def list_event_source_mappings(self, FunctionName):
        self.calls.append(FunctionName)
        if self.fail:
            raise self.fail
        return {"EventSourceMappings": self.items}


class FakeCw:
    def __init__(self, peaks=(), fail=None):
        self.peaks, self.fail, self.calls = list(peaks), fail, []

    def get_metric_statistics(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        return {"Datapoints": [{"Maximum": v} for v in self.peaks]}


def apply_kw(**over):
    kw = {"lam": FakeLambda(), "cw": FakeCw(), "mapping": MAPPING, "stack": "haru-dev", "confirm_stack": "haru-dev",
          "now": lambda: T0, "sleep": lambda s: None}
    kw.update(over)
    return kw


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
    res = rec_mod.run(sqs=sqs, dlq_url=dlq, queue_url=q, function="haru-dev-PhotoProcessorFunction-x", apply=True, out=lambda *_: None, **apply_kw())
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
    res = rec_mod.run(sqs=sqs, dlq_url=dlq, queue_url=q, function="haru-dev-PhotoProcessorFunction-x", apply=True, out=lambda *_: None, **apply_kw())
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
    rec_mod.run(sqs=sqs, dlq_url=dlq, queue_url=q, function="haru-dev-PhotoProcessorFunction-x", apply=True, out=lambda *_: None, **apply_kw())
    attrs = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    assert int(attrs["ApproximateNumberOfMessages"]) + int(attrs["ApproximateNumberOfMessagesNotVisible"]) == 6  # 하나도 지우지 않았다
    assert called == []


def test_cli_requires_stack_and_defaults_to_dry_run(monkeypatch):
    with pytest.raises(SystemExit):
        rec_mod.main([])  # --stack 필수
    seen = {}
    monkeypatch.setattr(rec_mod, "resolve", lambda stack, region: {"dlq_url": "d", "queue_url": "q", "table": "HaruTable", "function": "f", "mapping": MAPPING})
    monkeypatch.setattr(rec_mod, "run", lambda **kw: seen.update(kw) or {"counts": {}})
    monkeypatch.setattr(rec_mod.boto3, "resource", lambda *a, **k: type("R", (), {"Table": lambda self, n: n})())
    monkeypatch.setattr(rec_mod.boto3, "client", lambda *a, **k: None)
    monkeypatch.setattr(rec_mod.ddb, "use_table", lambda t: None)  # 전역 테이블을 더럽히지 않는다
    rec_mod.main(["--stack", "haru-dev"])
    assert seen["apply"] is False
    rec_mod.main(["--stack", "haru-dev", "--apply", "--confirm-stack", "haru-dev"])
    assert seen["apply"] is True and seen["confirm_stack"] == "haru-dev" and seen["mapping"] == MAPPING
    monkeypatch.setattr(rec_mod, "run", lambda **kw: {"counts": {}, "blocked": ["confirm_stack_mismatch"]})
    assert rec_mod.main(["--stack", "haru-dev", "--apply"]) == rec_mod.EXIT_BLOCKED


# ------------------------------------------------------------------ --apply 안전 확인


def _blocked(env, capsys=None, **over):
    """안전 확인 실패 시: DLQ를 읽지 않고(수신 횟수 불변) 아무것도 쓰지 않는다."""
    table, sqs, dlq, q, called = env
    scenario(table, sqs, dlq)
    before = snapshot(table)
    received = []
    real = sqs.receive_message
    sqs.receive_message = lambda **kw: received.append(kw["QueueUrl"]) or real(**kw)
    lines = []
    res = rec_mod.run(sqs=sqs, dlq_url=dlq, queue_url=q, function="haru-dev-PhotoProcessorFunction-x", apply=True, out=lines.append, **apply_kw(**over))
    assert snapshot(table) == before and called == []
    assert dlq not in received, "막혔으면 DLQ를 읽지 않는다(가시성 변경 없음)"
    assert res["counts"] == {} and any(line.startswith("BLOCKED") for line in lines)
    return res["blocked"]


def test_gate_passes_and_reports(env):
    table, sqs, dlq, q, _ = env
    scenario(table, sqs, dlq)
    lines = []
    lam = FakeLambda()
    res = rec_mod.run(sqs=sqs, dlq_url=dlq, queue_url=q, function="haru-dev-PhotoProcessorFunction-x", apply=True, out=lines.append, **apply_kw(lam=lam))
    assert res["gate"]["in_flight_samples"] == [0, 0, 0] and res["gate"]["executions_peak"] == 0
    assert any(line.startswith("apply_gate ok") for line in lines) and any(line.startswith("NEXT") for line in lines)
    assert lam.calls == ["haru-dev-PhotoProcessorFunction-x"] * 2  # 실행 전 확인 + 실행 뒤 재확인. 매핑을 바꾸지 않는다


def test_gate_confirm_stack_required(env):
    assert "confirm_stack_mismatch" in _blocked(env, confirm_stack=None)
    assert "confirm_stack_mismatch" in _blocked(env, confirm_stack="haru-demo")


@pytest.mark.parametrize("state", ["Enabled", "Enabling", "Disabling", "Updating"])
def test_gate_mapping_must_be_disabled(env, state):
    assert f"mapping_not_disabled:{state}" in _blocked(env, lam=FakeLambda(state=state))


def test_gate_mapping_disabled_recently(env):
    assert "mapping_disabled_less_than_60s" in _blocked(env, lam=FakeLambda(age_s=59))


def test_gate_any_other_enabled_mapping_blocks(env):
    other = {"UUID": "other", "State": "Enabled", "LastModified": T0 - timedelta(hours=1)}
    assert "mapping_not_disabled:Enabled" in _blocked(env, lam=FakeLambda(extra=[other]))


def test_gate_mapping_lookup_failure_blocks(env):
    assert any(r.startswith("mapping_unavailable") for r in _blocked(env, lam=FakeLambda(fail=RuntimeError("denied"))))
    assert "mapping_not_found" in _blocked(env, mapping="not-this-stack")


def test_gate_in_flight_sampled_repeatedly(env):
    _, sqs, _, q, _ = env
    counts = iter(["0", "1", "0"])  # 한 번이라도 0이 아니면 막는다(근사값)
    real = sqs.get_queue_attributes

    def attrs(**kw):
        if kw["QueueUrl"] == q and kw["AttributeNames"] == ["ApproximateNumberOfMessagesNotVisible"]:
            return {"Attributes": {"ApproximateNumberOfMessagesNotVisible": next(counts)}}
        return real(**kw)

    sqs.get_queue_attributes = attrs
    sleeps = []
    assert "queue_in_flight_not_zero" in _blocked(env, sleep=sleeps.append)
    assert sleeps == [rec_mod.QUEUE_SAMPLE_INTERVAL_S] * (rec_mod.QUEUE_SAMPLES - 1)


def test_gate_executions_after_disable_block(env):
    assert "executions_after_disable" in _blocked(env, cw=FakeCw(peaks=[0, 1]))


def test_gate_executions_window_starts_after_disable(env):
    cw = FakeCw()
    _, sqs, dlq, q, _ = env
    rec_mod.run(sqs=sqs, dlq_url=dlq, queue_url=q, function="f", apply=True, out=lambda *_: None, **apply_kw(cw=cw, lam=FakeLambda(age_s=120)))
    start = cw.calls[-1]["StartTime"]
    assert start == T0 - timedelta(seconds=120) + timedelta(seconds=rec_mod.FUNCTION_TIMEOUT_S)


@pytest.mark.parametrize("cw", [None, FakeCw(fail=RuntimeError("AccessDenied"))])
def test_gate_executions_unavailable_blocks(env, cw):
    assert any(r.startswith("executions_unavailable") for r in _blocked(env, cw=cw))


def test_dry_run_notes_visibility_change(env):
    table, sqs, dlq, q, _ = env
    scenario(table, sqs, dlq)
    lines = []
    rec_mod.run(sqs=sqs, cw=None, dlq_url=dlq, queue_url=q, function=None, apply=False, out=lines.append)
    assert any(line.startswith("NOTE dry-run도 ReceiveMessage") for line in lines)
    attrs = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    assert int(attrs["ApproximateNumberOfMessagesNotVisible"]) == 6  # dry-run도 읽은 메시지를 잠시 숨긴다(문서화한 동작)
