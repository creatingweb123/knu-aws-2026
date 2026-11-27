"""사진 처리 Lambda (moto DynamoDB·S3).

경합은 시도(Attempt.steps)를 단계별로 진행하며 다른 연산을 끼워 순차로 재현한다. 이것은 로직 확인이고
T10·T15 등 AWS 판정을 대체하지 않는다.

Validates: spec backend-stage5-photo-pipeline Requirements 5–9, 12.6, 14.1
"""

import logging
import re

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from PIL import Image

pytest.importorskip("moto")

from common.errors import TRY_AGAIN, ApiError  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from tests.unit.photo_fixtures import (  # noqa: E402
    BUCKET, MINJUN, NOW, SUHYUN, Ctx, claim_item, claimed, inbox_items, jpeg, photo_env, processed_keys, record,
    s3_record, sqs_event, upload, with_photo,
)
from workers import photo_processor as pp  # noqa: E402

_real_complete = cs.complete_claim  # monkeypatch 전에 잡아 둔 실제 함수


@pytest.fixture
def env(monkeypatch):
    with photo_env(monkeypatch) as (table, client):
        yield table, client


def ready_photo(client, body=None, ct="image/jpeg"):
    pid, cid = claimed()
    key = with_photo(pid, cid, ct=ct)
    etag = upload(client, key, body if body is not None else jpeg())
    return pid, cid, key, etag


def run(key, etag, receive_count=1, ctx=None):
    pp.handler(sqs_event([s3_record(key, etag)], receive_count=receive_count), ctx)


def step_to(attempt_iter, label):
    for got in attempt_iter:
        if got == label:
            return
    raise AssertionError(f"단계 {label}에 닿지 못함")


# ------------------------------------------------------------------ 정상


def test_happy_path(env):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    run(key, etag)
    rec = record(pid, cid)
    assert rec["photoStatus"] == "READY" and rec["deliveredAt"]
    assert re.fullmatch(rf"photos/processed/{cid}/[0-9a-f]{{32}}\.jpg", rec["processedKey"])
    assert processed_keys(client, cid) == [rec["processedKey"]]
    (item,) = inbox_items()
    assert item["hasPhoto"] is True and item["itemId"] == cid
    out = Image.open(client.get_object(Bucket=BUCKET, Key=rec["processedKey"])["Body"])
    assert out.format == "JPEG" and len(out.getexif()) == 0


def test_png_and_url_encoded_key(env):
    table, client = env
    pid, cid, key, etag = ready_photo(client, body=_png(), ct="image/png")
    pp.handler(sqs_event([s3_record(key, etag)]), None)
    assert record(pid, cid)["photoStatus"] == "READY"


def _png():
    import io

    b = io.BytesIO()
    Image.new("RGBA", (50, 40), (0, 0, 255, 128)).save(b, "PNG")
    return b.getvalue()


# ------------------------------------------------------------------ 무시 조건


@pytest.mark.parametrize("body", ['{"Service":"Amazon S3","Event":"s3:TestEvent"}', "not json", '{"foo": 1}', "[]", '{"Records": "x"}'])
def test_non_s3_messages_ignored(env, body):
    pp.handler(sqs_event(body=body), None)  # 예외 없음 = 메시지 삭제


@pytest.mark.parametrize("key", ["photos/processed/clm_01JABCDEFGHJKMNPQRSTVWXYZ0/" + "a" * 32 + ".jpg", "other/x.jpg", "photos/original/bad.jpg"])
def test_bad_keys_ignored(env, key, caplog):
    with caplog.at_level(logging.INFO):
        run(key, "e")
    assert "photo_ignored reason=bad_key" in caplog.text


def test_missing_lookup_or_record(env, caplog):
    table, client = env
    with caplog.at_level(logging.INFO):
        run("photos/original/clm_01JABCDEFGHJKMNPQRSTVWXYZ0/" + "a" * 32 + ".jpg", "e")
    assert "reason=no_lookup" in caplog.text
    pid, cid = claimed()
    with caplog.at_level(logging.INFO):
        run(f"photos/original/{cid}/" + "a" * 32 + ".jpg", "e")
    assert "reason=no_record" in caplog.text


def test_delivered_discarded_stale_ignored_without_processed(env, caplog):
    table, client = env
    # 전달됨
    pid, cid, key, etag = ready_photo(client)
    cs.complete_by_user(cid, SUHYUN, "TEXT_ONLY", NOW)
    with caplog.at_level(logging.INFO):
        run(key, etag)
    assert "reason=delivered" in caplog.text and processed_keys(client, cid) == []
    # 포기(DISCARDED)
    pid2, cid2 = claimed(key="k2")
    key2 = with_photo(pid2, cid2)
    etag2 = upload(client, key2, jpeg())
    cs.abandon(cid2, SUHYUN, NOW)
    with caplog.at_level(logging.INFO):
        run(key2, etag2)
    assert "reason=discarded" in caplog.text and processed_keys(client, cid2) == []
    # 지난 키(교체)
    pid3, cid3 = claimed(key="k3")
    key3 = with_photo(pid3, cid3)
    etag3 = upload(client, key3, jpeg())
    with_photo(pid3, cid3)
    with caplog.at_level(logging.INFO):
        run(key3, etag3)
    assert "reason=stale_key" in caplog.text and processed_keys(client, cid3) == []


def test_unexpected_ready_is_not_processed(env, caplog):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :r", ExpressionAttributeValues={":r": "READY"})
    with caplog.at_level(logging.WARNING):
        run(key, etag)
    assert "photo_unexpected_ready" in caplog.text and processed_keys(client, cid) == [] and inbox_items() == []


def test_etag_mismatch_and_gone(env, caplog):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    with caplog.at_level(logging.INFO):
        run(key, "deadbeef")  # 재업로드로 객체가 바뀐 경우
    assert "reason=etag_changed" in caplog.text and record(pid, cid)["photoStatus"] == "UPLOAD_PENDING"
    client.delete_object(Bucket=BUCKET, Key=key)
    with caplog.at_level(logging.INFO):
        run(key, etag)
    assert "reason=gone" in caplog.text and processed_keys(client, cid) == []


def test_head_403_is_retried_not_ignored(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)

    def denied(**kw):
        raise ClientError({"Error": {"Code": "403"}, "ResponseMetadata": {"HTTPStatusCode": 403}}, "HeadObject")

    monkeypatch.setattr(client, "head_object", denied)
    with pytest.raises(ClientError):
        run(key, etag)  # BE-Q70: 권한 결함을 숨기지 않는다


def test_state_changed_before_processing(env, caplog):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    a = pp.Attempt(s3_record(key, etag))
    it = a.steps()
    step_to(it, "checked")
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :f", ExpressionAttributeValues={":f": "FAILED"})
    with caplog.at_level(logging.INFO):
        list(it)
    assert a.result == "ignored" and "reason=state_changed" in caplog.text


# ------------------------------------------------------------------ 검사 실패


@pytest.mark.parametrize("body,code", [(jpeg()[:200], "CORRUPT_IMAGE"), (b"GIF89a" + b"0" * 100, "UNSUPPORTED_FORMAT")])
def test_rejected_image_marks_failed_without_retry(env, body, code, capsys):
    table, client = env
    pid, cid, key, etag = ready_photo(client, body=body)
    run(key, etag)  # 예외 없음 = 재시도 안 함
    rec = record(pid, cid)
    assert rec["photoStatus"] == "FAILED" and rec["photoError"] == code and processed_keys(client, cid) == []
    assert '"PhotoFailed":1' in capsys.readouterr().out


def test_too_large_by_head(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    real = client.head_object
    monkeypatch.setattr(client, "head_object", lambda **kw: {**real(**kw), "ContentLength": 10_485_761})
    run(key, etag)
    assert record(pid, cid)["photoError"] == "TOO_LARGE"


# ------------------------------------------------------------------ 처리본 PutObject


def test_processed_put_412_never_touches_existing(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    taken = f"photos/processed/{cid}/" + "f" * 32 + ".jpg"
    client.put_object(Bucket=BUCKET, Key=taken, Body=b"someone else")
    from common import s3 as s3mod

    keys = iter([taken, f"photos/processed/{cid}/" + "e" * 32 + ".jpg"])
    monkeypatch.setattr(s3mod, "new_processed_key", lambda c: next(keys))
    run(key, etag)
    assert client.get_object(Bucket=BUCKET, Key=taken)["Body"].read() == b"someone else"  # 남의 객체 그대로
    assert record(pid, cid)["processedKey"].endswith("e" * 32 + ".jpg")


def test_processed_put_412_twice_raises_and_deletes_nothing(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    taken = f"photos/processed/{cid}/" + "f" * 32 + ".jpg"
    client.put_object(Bucket=BUCKET, Key=taken, Body=b"x")
    from common import s3 as s3mod

    monkeypatch.setattr(s3mod, "new_processed_key", lambda c: taken)
    with pytest.raises(RuntimeError):
        run(key, etag)
    assert processed_keys(client, cid) == [taken] and inbox_items() == []


def test_processed_put_timeout_no_complete_no_delete(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    real_put = client.put_object
    created = []

    def put_then_timeout(**kw):
        real_put(**kw)  # 실제로는 생성됐지만 응답을 못 받음
        created.append(kw["Key"])
        raise ReadTimeoutError(endpoint_url="s3")

    monkeypatch.setattr(client, "put_object", put_then_timeout)
    called = []
    monkeypatch.setattr(cs, "complete_claim", lambda *a, **k: called.append(1))
    with pytest.raises(ReadTimeoutError):
        run(key, etag)
    assert called == [] and processed_keys(client, cid) == created  # 지우지 않는다(생성 여부를 몰랐다)


# ------------------------------------------------------------------ 경합 (순차 재현)


def test_S2_duplicate_attempts_one_delivery(env):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    a, b = pp.Attempt(s3_record(key, etag)), pp.Attempt(s3_record(key, etag))
    ia, ib = a.steps(), b.steps()
    step_to(ia, "uploaded")
    step_to(ib, "uploaded")
    list(ia)
    list(ib)
    assert (a.result, b.result) == ("delivered", "not_delivered")
    rec = record(pid, cid)
    assert rec["processedKey"] == a.attempt_key and processed_keys(client, cid) == [a.attempt_key]
    assert len(inbox_items()) == 1
    run(key, etag)  # 세 번째 전달은 무시
    assert processed_keys(client, cid) == [a.attempt_key]


def test_S3_reupload_same_key(env):
    table, client = env
    pid, cid, key, etag1 = ready_photo(client, body=jpeg((255, 0, 0)))
    etag2 = upload(client, key, jpeg((0, 0, 255)))
    run(key, etag1)  # 첫 이벤트: 객체가 바뀌어 무시
    assert record(pid, cid)["photoStatus"] == "UPLOAD_PENDING"
    run(key, etag2)
    rec = record(pid, cid)
    px = Image.open(client.get_object(Bucket=BUCKET, Key=rec["processedKey"])["Body"]).getpixel((5, 5))
    assert px[2] > 200 and px[0] < 60  # 파랑 = 전달 시점 객체(v2)


def test_S3_reupload_after_read_delivers_v1_once(env):
    table, client = env
    pid, cid, key, etag1 = ready_photo(client, body=jpeg((255, 0, 0)))
    a = pp.Attempt(s3_record(key, etag1))
    it = a.steps()
    step_to(it, "uploaded")  # v1을 읽고 처리본까지 만듦
    etag2 = upload(client, key, jpeg((0, 0, 255)))
    list(it)
    run(key, etag2)  # v2 이벤트는 delivered로 무시
    rec = record(pid, cid)
    assert a.result == "delivered" and processed_keys(client, cid) == [rec["processedKey"]] and len(inbox_items()) == 1


def test_S4_text_only_during_processing(env):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    a = pp.Attempt(s3_record(key, etag))
    it = a.steps()
    step_to(it, "processing")
    cs.complete_by_user(cid, SUHYUN, "TEXT_ONLY", NOW)
    list(it)
    assert a.result == "not_delivered" and processed_keys(client, cid) == []
    (item,) = inbox_items()
    assert item["hasPhoto"] is False and record(pid, cid)["photoStatus"] == "DISCARDED"


def test_S4_text_only_before_processing_transition(env):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    a = pp.Attempt(s3_record(key, etag))
    it = a.steps()
    step_to(it, "checked")
    cs.complete_by_user(cid, SUHYUN, "TEXT_ONLY", NOW)
    list(it)
    assert a.result == "ignored" and processed_keys(client, cid) == []


def test_S5_replace_during_processing(env):
    table, client = env
    pid, cid, key1, etag1 = ready_photo(client, body=jpeg((255, 0, 0)))
    a = pp.Attempt(s3_record(key1, etag1))
    it = a.steps()
    step_to(it, "uploaded")
    cs.replace_photo(cid, SUHYUN, __import__("common.validation", fromlist=["PhotoIn"]).PhotoIn(contentType="image/jpeg", size=10), NOW)
    key2 = record(pid, cid)["photoKey"]
    etag2 = upload(client, key2, jpeg((0, 0, 255)))
    list(it)
    assert a.result == "not_delivered"
    run(key2, etag2)
    rec = record(pid, cid)
    assert rec["photoKey"] == key2 and processed_keys(client, cid) == [rec["processedKey"]]
    px = Image.open(client.get_object(Bucket=BUCKET, Key=rec["processedKey"])["Body"]).getpixel((5, 5))
    assert px[2] > 200  # 두 번째 사진


def test_S6_abandon_during_processing(env):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    a = pp.Attempt(s3_record(key, etag))
    it = a.steps()
    step_to(it, "uploaded")
    cs.abandon(cid, SUHYUN, NOW)
    list(it)
    assert a.result == "not_delivered" and processed_keys(client, cid) == [] and inbox_items() == []


def test_S6_expired_replacement_during_processing(env):
    from datetime import timedelta

    table, client = env
    pid, cid, key, etag = ready_photo(client)
    a = pp.Attempt(s3_record(key, etag))
    it = a.steps()
    step_to(it, "uploaded")
    cs.claim_plan(pid, MINJUN, NOW + timedelta(days=4))  # 기한 지난 대체: 이전 Claim EXPIRED, Record는 그대로
    assert claim_item(pid, cid)["status"] == "EXPIRED" and record(pid, cid)["photoStatus"] == "PROCESSING"
    list(it)
    assert a.result == "not_delivered" and processed_keys(client, cid) == [] and inbox_items() == []


# ------------------------------------------------------------------ 결과 불확실 (S7)


def test_S7_commit_then_error_preserves_and_next_attempt_ignores(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    real = cs.complete_claim

    def commit_then_timeout(*a, **k):
        real(*a, **k)
        raise ReadTimeoutError(endpoint_url="dynamodb")

    monkeypatch.setattr(cs, "complete_claim", commit_then_timeout)
    run(key, etag)  # 재조회로 delivered 확정 → 정상 종료
    rec = record(pid, cid)
    assert rec["deliveredAt"] and processed_keys(client, cid) == [rec["processedKey"]]


def test_S7_uncertain_when_still_processing(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    monkeypatch.setattr(cs, "complete_claim", lambda *a, **k: (_ for _ in ()).throw(ApiError(TRY_AGAIN)))
    with pytest.raises(pp.PhotoOutcomeUncertain):
        run(key, etag)
    (kept,) = processed_keys(client, cid)  # 보존
    monkeypatch.setattr(cs, "complete_claim", _real_complete)
    run(key, etag)  # 재시도: 새 시도가 전달
    rec = record(pid, cid)
    assert rec["deliveredAt"] and rec["processedKey"] != kept and kept in processed_keys(client, cid)  # 이전 처리본은 고아로 남는다(BE-Q67)


def test_S7_verify_read_failure_preserves(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    a = pp.Attempt(s3_record(key, etag))
    it = a.steps()
    step_to(it, "completed")
    from domain import plan_service

    monkeypatch.setattr(pp, "_get", lambda *a, **k: (_ for _ in ()).throw(ReadTimeoutError(endpoint_url="dynamodb")))
    with pytest.raises(ReadTimeoutError):
        list(it)
    monkeypatch.setattr(pp, "_get", plan_service._get)
    assert processed_keys(client, cid) == [a.attempt_key] and record(pid, cid)["processedKey"] == a.attempt_key



# ------------------------------------------------------------------ 재시도·시간·주입


def test_transient_error_raises_and_third_receive_marks_failed(env, monkeypatch, capsys):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    real_get = client.get_object
    monkeypatch.setattr(client, "get_object", lambda **kw: (_ for _ in ()).throw(ClientError({"Error": {"Code": "InternalError"}, "ResponseMetadata": {"HTTPStatusCode": 500}}, "GetObject")))
    for n in (1, 2):
        with pytest.raises(ClientError):
            run(key, etag, receive_count=n)
        assert record(pid, cid)["photoStatus"] == "PROCESSING"
    with pytest.raises(ClientError):
        run(key, etag, receive_count=3)
    rec = record(pid, cid)
    assert rec["photoStatus"] == "FAILED" and rec["photoError"] == "RETRY_EXHAUSTED" and '"PhotoFailed":1' in capsys.readouterr().out
    monkeypatch.setattr(client, "get_object", real_get)


def test_failed_write_failure_still_raises_original(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    monkeypatch.setattr(client, "get_object", lambda **kw: (_ for _ in ()).throw(ClientError({"Error": {"Code": "SlowDown"}, "ResponseMetadata": {"HTTPStatusCode": 503}}, "GetObject")))
    real_update = cs.photo_status_update
    calls = []

    def flaky(*a, **k):
        calls.append(k["to"])
        if k["to"] == "FAILED":
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "UpdateItem")
        return real_update(*a, **k)

    monkeypatch.setattr(cs, "photo_status_update", flaky)
    with pytest.raises(ClientError) as e:
        run(key, etag, receive_count=3)
    assert e.value.response["Error"]["Code"] == "SlowDown" and calls == ["PROCESSING", "FAILED"]


def test_complete_try_again_preserves_and_raises(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    monkeypatch.setattr(cs, "complete_claim", lambda *a, **k: (_ for _ in ()).throw(ApiError(TRY_AGAIN)))
    with pytest.raises(pp.PhotoOutcomeUncertain):
        run(key, etag)
    assert len(processed_keys(client, cid)) == 1


@pytest.mark.parametrize("step_env,remaining", [("PRE_READ_MS", [11_000]), ("PRE_PROCESS_MS", [30_000, 16_000]), ("PRE_UPLOAD_MS", [30_000, 30_000, 11_000])])
def test_time_guard_before_steps(env, step_env, remaining):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    with pytest.raises(pp.TimeBudgetExceeded):
        run(key, etag, ctx=Ctx(*remaining))
    assert processed_keys(client, cid) == []


def test_time_guard_before_complete_deletes_own_only(env, monkeypatch):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    called = []
    monkeypatch.setattr(cs, "complete_claim", lambda *a, **k: called.append(1))
    with pytest.raises(pp.TimeBudgetExceeded):
        run(key, etag, ctx=Ctx(30_000, 30_000, 30_000, 14_000))
    assert called == [] and processed_keys(client, cid) == [] and record(pid, cid)["photoStatus"] == "PROCESSING"


def test_fault_photo_after_processing(env, monkeypatch):
    table, client = env
    monkeypatch.setenv("FAULT_INJECT", "photo")
    monkeypatch.setenv("FAULT_INJECT_ALLOWED", "true")
    monkeypatch.setenv("STAGE", "local")
    pid, cid, key, etag = ready_photo(client)
    with pytest.raises(pp.FaultInjected):
        run(key, etag)
    assert record(pid, cid)["photoStatus"] == "PROCESSING"
    with pytest.raises(pp.FaultInjected):
        run(key, etag, receive_count=3)
    assert record(pid, cid)["photoError"] == "RETRY_EXHAUSTED"


def test_fault_photo_slow_sleeps(env, monkeypatch):
    table, client = env
    monkeypatch.setenv("FAULT_INJECT", "photo-slow")
    monkeypatch.setenv("FAULT_INJECT_ALLOWED", "true")
    monkeypatch.setenv("STAGE", "local")
    monkeypatch.setenv("FAULT_DELAY_S", "50")
    slept = []
    monkeypatch.setattr(pp.time, "sleep", slept.append)
    pid, cid, key, etag = ready_photo(client)
    run(key, etag)
    assert slept == [10] and record(pid, cid)["photoStatus"] == "READY"  # 1–10초로 제한


def test_logs_have_no_identifiers(env, caplog):
    table, client = env
    pid, cid, key, etag = ready_photo(client)
    with caplog.at_level(logging.DEBUG, logger="workers.photo_processor"):
        run(key, etag)
        run(key, etag)
    text = caplog.text
    assert "photo_delivered" in text and cid not in text and pid not in text and "u-suhyun" not in text and "photos/" not in text


def test_sdk_config():
    cfg = pp.sdk_config()
    assert cfg.connect_timeout == 2 and cfg.read_timeout == 5 and cfg.retries == {"mode": "standard", "total_max_attempts": 2}


def test_delete_own_requires_created(env):
    """이 실행이 PutObject 200으로 만든 객체만 지운다(키를 알아도 created가 아니면 지우지 않는다)."""
    table, client = env
    key = "photos/processed/clm_01JABCDEFGHJKMNPQRSTVWXYZ0/" + "d" * 32 + ".jpg"
    client.put_object(Bucket=BUCKET, Key=key, Body=b"x")
    a = pp.Attempt(s3_record("photos/original/x.jpg", "e"))
    a.attempt_key, a.created = key, False
    a._delete_own("test")
    assert client.head_object(Bucket=BUCKET, Key=key)["ContentLength"] == 1
    a.created = True
    a._delete_own("test")
    with pytest.raises(ClientError):
        client.head_object(Bucket=BUCKET, Key=key)
