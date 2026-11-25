"""중첩 재시도 상한 (design "중첩 재시도", BE-Q71).

complete_claim(3단계, 바꾸지 않음) 한 번의 최악 경로: 4회 반복 × GetItem 4 = 16, 트랜잭션을 실행하는 3회 반복 × 4 = 12,
합계 API 호출 28회. 처리 Lambda의 botocore 설정(total_max_attempts=2)이면 HTTP 시도는 최대 56회다.
transact_with_retry의 대기(50·100·200ms)는 반복마다 최대 350ms, 합계 1.05초다(이 테스트는 실제로 기다린다:
transact_with_retry의 sleep 기본값이 정의 시점에 묶여 있고 3단계 코드는 바꾸지 않는다).

Validates: Requirements 9.3 · BE-Q71
"""

import time

import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError

pytest.importorskip("moto")

from common import ddb  # noqa: E402
from common.errors import ApiError  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from tests.unit.photo_fixtures import Ctx, claimed, jpeg, photo_env, record, s3_record, upload, with_photo  # noqa: E402
from workers import photo_processor as pp  # noqa: E402


@pytest.fixture
def env(monkeypatch):
    with photo_env(monkeypatch) as (table, client):
        yield table, client


def test_worst_case_call_counts(env, monkeypatch, capsys):
    table, client = env
    pid, cid = claimed()
    key = with_photo(pid, cid)
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :p", ExpressionAttributeValues={":p": "PROCESSING"})
    low = ddb.table().meta.client
    counts = {"get_item": 0, "transact_write_items": 0}
    real_get = low.get_item

    def get_item(**kw):
        counts["get_item"] += 1
        return real_get(**kw)

    def conflict(**kw):
        counts["transact_write_items"] += 1
        raise ClientError({"Error": {"Code": "TransactionCanceledException"}, "CancellationReasons": [{"Code": "TransactionConflict"}] * 4}, "TransactWriteItems")

    monkeypatch.setattr(low, "get_item", get_item)
    monkeypatch.setattr(low, "transact_write_items", conflict)
    started = time.monotonic()
    with pytest.raises(ApiError) as e:
        cs.complete_claim(cid, "WITH_PHOTO", key=key, processed_key="photos/processed/x.jpg")
    elapsed = time.monotonic() - started
    assert e.value.code == "TRY_AGAIN"
    assert counts == {"get_item": 16, "transact_write_items": 12}  # 합계 28
    assert 1.05 <= elapsed < 5  # 대기 합 1.05초 + moto 처리 시간
    print(f"photo_retry_budget calls={counts} total={sum(counts.values())} sdk_attempts_max={2 * sum(counts.values())} elapsed_s={elapsed:.2f}")
    assert record(pid, cid)["photoStatus"] == "PROCESSING"  # 쓰기 없음


def test_sdk_config_makes_at_most_two_http_attempts():
    client = boto3.client("dynamodb", region_name="ap-northeast-2", aws_access_key_id="x", aws_secret_access_key="y",
                          endpoint_url="https://example.invalid", config=pp.sdk_config())
    sent = []

    class Raw:
        def stream(self, **kw):
            yield b'{"__type":"com.amazonaws.dynamodb.v20120810#InternalServerError","message":"x"}'

    def fake_500(request, **kw):
        sent.append(request.url)
        return AWSResponse(request.url, 500, {}, Raw())

    client.meta.events.register("before-send.dynamodb.GetItem", fake_500)
    with pytest.raises(ClientError):
        client.get_item(TableName="t", Key={"PK": {"S": "a"}, "SK": {"S": "b"}})
    assert len(sent) == 2  # standard 모드, total_max_attempts=2


def test_guard_only_before_complete_not_inside(env, monkeypatch):
    """guard는 완료를 시작할지만 정한다. 완료 안에서 시간이 얼마나 걸려도 끊지 않는다(강제 종료 위험은 BE-Q71·S8)."""
    table, client = env
    pid, cid = claimed()
    key = with_photo(pid, cid)
    etag = upload(client, key, jpeg())
    ctx = Ctx(30_000, 30_000, 30_000, 15_000, 100)  # 완료 직전 15초(통과), 그 뒤 100ms
    inside = []
    real = cs.complete_claim

    def slow_complete(*a, **k):
        inside.append(ctx.get_remaining_time_in_millis())  # 완료 안에서는 이미 시간이 거의 없다
        return real(*a, **k)

    monkeypatch.setattr(cs, "complete_claim", slow_complete)
    pp.Attempt(s3_record(key, etag), ctx).run(1)
    assert inside == [100] and record(pid, cid)["photoStatus"] == "READY"  # 끝까지 진행했다
