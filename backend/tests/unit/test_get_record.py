"""작업 A: GET /claims/{claimId}/record (BE-REC-05, BE-Q46 권장안 구현, 계약 변경 승인 대기).

- transact_get_with_retry: TransactionConflict만 유한하게 재시도, 대기는 equal jitter 상한 안
- 핸들러: moto 대상으로 기록 없음·정상·남·없음·포기·만료·완료·사진 상태
- 스냅샷: 충돌 재시도 소진 → 503, 동시 쓰기 사이에서도 한 시점의 값
"""

import json
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from hypothesis import given, settings
from hypothesis import strategies as st

pytest.importorskip("moto")

from common import ddb  # noqa: E402
from common.ddb import BACKOFF_SECONDS, transact_get_with_retry  # noqa: E402
from common.errors import ApiError  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from handlers import claims, plans  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402
from tests.unit.test_handlers_claims import MINJUN, OWNER, SUHYUN, call, make_plan  # noqa: E402

KEYS = [{"PK": "PLAN#p", "SK": "CLAIM#c"}, {"PK": "PLAN#p", "SK": "RECORD#c"}]


# ------------------------------------------------------------ transact_get_with_retry


@pytest.fixture
def stubbed(monkeypatch):
    set_env(monkeypatch)
    client = boto3.resource(
        "dynamodb", region_name="ap-northeast-2", aws_access_key_id="test", aws_secret_access_key="test"
    ).Table("HaruTable").meta.client
    monkeypatch.setattr(ddb, "_table", type("T", (), {"name": "HaruTable", "meta": type("M", (), {"client": client})})())
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


def cancel(stub, *codes):
    stub.add_client_error(
        "transact_get_items",
        service_error_code="TransactionCanceledException",
        modeled_fields={"CancellationReasons": [{"Code": c} for c in codes]},
    )


def good(stub, claim=True, record=False):
    stub.add_response(
        "transact_get_items",
        {"Responses": [{"Item": {"PK": {"S": "PLAN#p"}, "SK": {"S": "CLAIM#c"}}} if claim else {}, {"Item": {"PK": {"S": "x"}}} if record else {}]},
    )


def test_first_try_success_in_order(stubbed):
    client, stub = stubbed
    good(stub, claim=True, record=False)
    sleeps = []
    out = transact_get_with_retry(KEYS, client=client, sleep=sleeps.append)
    assert out[0]["SK"] == "CLAIM#c" and out[1] is None and sleeps == []


def test_conflicts_then_success(stubbed):
    client, stub = stubbed
    cancel(stub, "TransactionConflict", "None")
    cancel(stub, "None", "TransactionConflict")
    good(stub)
    sleeps = []
    transact_get_with_retry(KEYS, client=client, sleep=sleeps.append, rand=lambda: 1.0)
    assert sleeps == [0.05, 0.1]


@pytest.mark.parametrize("rand,expected", [(1.0, [0.05, 0.1, 0.2]), (0.0, [0.025, 0.05, 0.1])])
def test_exhausted_is_503_with_bounded_waits(stubbed, rand, expected):
    client, stub = stubbed
    for _ in range(4):
        cancel(stub, "TransactionConflict", "TransactionConflict")
    sleeps = []
    with pytest.raises(ApiError) as e:
        transact_get_with_retry(KEYS, client=client, sleep=sleeps.append, rand=lambda: rand)
    assert e.value.code == "TRY_AGAIN" and sleeps == pytest.approx(expected)


@pytest.mark.parametrize("codes", [("TransactionConflict", "ThrottlingError"), ("ValidationError", "None"), ("ThrottlingError",), ("None", "None")])
def test_mixed_or_other_reasons_do_not_retry(stubbed, codes):
    client, stub = stubbed
    cancel(stub, *codes)
    sleeps = []
    with pytest.raises(ClientError) as e:
        transact_get_with_retry(KEYS, client=client, sleep=sleeps.append)
    assert e.value.response["Error"]["Code"] == "TransactionCanceledException" and sleeps == []


def test_non_transaction_error_propagates(stubbed):
    client, stub = stubbed
    stub.add_client_error("transact_get_items", service_error_code="ProvisionedThroughputExceededException")
    with pytest.raises(ClientError):
        transact_get_with_retry(KEYS, client=client, sleep=lambda s: None)


def test_logs_only_reason_codes(stubbed, caplog):
    client, stub = stubbed
    cancel(stub, "ValidationError", "None")
    caplog.set_level("INFO")
    with pytest.raises(ClientError):
        transact_get_with_retry(KEYS, client=client, sleep=lambda s: None)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "ValidationError" in text and "PLAN#" not in text and "CLAIM#" not in text


class _Fake:
    def __init__(self, outcomes):
        self.outcomes, self.calls, self.get_item_calls = list(outcomes), 0, 0

    def transact_get_items(self, TransactItems):
        self.calls += 1
        o = self.outcomes.pop(0)
        if o == "ok":
            return {"Responses": [{}, {}]}
        code, reasons = o
        raise ClientError({"Error": {"Code": code}, "CancellationReasons": [{"Code": r} for r in reasons]}, "TransactGetItems")

    def get_item(self, **_):
        self.get_item_calls += 1
        raise AssertionError("GetItem 폴백 금지")


_attempt = st.one_of(
    st.just("ok"),
    st.tuples(st.just("TransactionCanceledException"), st.lists(st.sampled_from(["None", "TransactionConflict", "ThrottlingError", "ValidationError"]), max_size=3)),
    st.tuples(st.just("InternalServerError"), st.just([])),
)


@settings(max_examples=150, deadline=None)
@given(st.lists(_attempt, min_size=1, max_size=5), st.lists(st.floats(0, 0.999), min_size=4, max_size=4))
def test_property_retry_bounded(outcomes, rands):
    """Property: 호출 ≤ 4, 재시도 수 = 대기 수, 대기 ∈ [cap/2, cap], GetItem 0회."""
    outcomes = outcomes + [("TransactionCanceledException", ["TransactionConflict"])] * 5
    fake = _Fake(outcomes)
    sleeps, r = [], iter(rands)
    with pytest.MonkeyPatch.context() as mp:
        set_env(mp)
        mp.setattr(ddb, "_table", type("T", (), {"name": "HaruTable"})())
        try:
            transact_get_with_retry(KEYS, client=fake, sleep=sleeps.append, rand=lambda: next(r))
        except (ApiError, ClientError):
            pass
    assert 1 <= fake.calls <= len(BACKOFF_SECONDS) + 1
    assert len(sleeps) <= fake.calls - 1
    assert fake.get_item_calls == 0
    for i, s in enumerate(sleeps):
        assert BACKOFF_SECONDS[i] / 2 <= s <= BACKOFF_SECONDS[i]


# ------------------------------------------------------------ 핸들러·서비스 (moto)


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


def claimed():
    pid = make_plan()
    _, b = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    return pid, b["claim"]["claimId"]


def get_record(who, cid):
    return call(claims.handler, "GET /claims/{claimId}/record", who, path={"claimId": cid})


def test_no_record_yet(table):
    _, cid = claimed()
    assert get_record(SUHYUN, cid) == (200, {"record": None, "claimStatus": "ACTIVE", "delivered": False, "photoStatus": "NONE"})


def test_with_record_and_exact_keys(table):
    _, cid = claimed()
    call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "소금빵"}, path={"claimId": cid})
    status, body = get_record(SUHYUN, cid)
    assert status == 200 and list(body) == ["record", "claimStatus", "delivered", "photoStatus"]
    assert set(body["record"]) == {"claimId", "planId", "letter", "photoStatus", "updatedAt", "deliveredAt"}
    assert body["record"]["letter"] == "소금빵" and body["delivered"] is False and body["photoStatus"] == "NONE"
    assert "authorId" not in json.dumps(body) and "photoKey" not in json.dumps(body) and "PK" not in body["record"]


@pytest.mark.parametrize("who,code,status", [(MINJUN, "FORBIDDEN", 403), (OWNER, "FORBIDDEN", 403)])
def test_not_claimer_403_without_content(table, who, code, status):
    _, cid = claimed()
    call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "비밀 글"}, path={"claimId": cid})
    s, body = get_record(who, cid)
    assert s == status and body["error"]["code"] == code and "비밀 글" not in json.dumps(body, ensure_ascii=False)


def test_missing_claim_404_without_transaction(table, monkeypatch):
    monkeypatch.setattr(ddb, "transact_get_with_retry", lambda *a, **k: pytest.fail("트랜잭션 호출 금지"))
    assert get_record(SUHYUN, "clm_none")[0] == 404


def test_abandoned_is_readable_and_discarded_photo(table, monkeypatch):
    monkeypatch.setenv("PHOTO_BUCKET", "haru-photos-test")
    _, cid = claimed()
    call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "글", "photo": {"contentType": "image/jpeg", "size": 10}}, path={"claimId": cid})
    assert get_record(SUHYUN, cid)[1]["photoStatus"] == "UPLOAD_PENDING"
    call(claims.handler, "POST /claims/{claimId}/abandon", SUHYUN, path={"claimId": cid})
    status, body = get_record(SUHYUN, cid)
    assert status == 200 and body["claimStatus"] == "ABANDONED" and body["delivered"] is False
    assert body["photoStatus"] == body["record"]["photoStatus"]


def test_abandoned_without_record(table):
    _, cid = claimed()
    call(claims.handler, "POST /claims/{claimId}/abandon", SUHYUN, path={"claimId": cid})
    assert get_record(SUHYUN, cid) == (200, {"record": None, "claimStatus": "ABANDONED", "delivered": False, "photoStatus": "NONE"})


def test_completed_text_only_is_delivered_consistent(table):
    _, cid = claimed()
    call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "글"}, path={"claimId": cid})
    call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
    status, body = get_record(SUHYUN, cid)
    assert status == 200 and body["claimStatus"] == "COMPLETED" and body["delivered"] is True and body["record"]["deliveredAt"]


def test_expired_claim_status_is_returned(table):
    pid, cid = claimed()
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"CLAIM#{cid}"}, UpdateExpression="SET #s = :e", ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":e": "EXPIRED"})
    assert get_record(SUHYUN, cid)[1]["claimStatus"] == "EXPIRED"


def test_read_does_not_write(table):
    pid, cid = claimed()
    call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "글"}, path={"claimId": cid})
    before = sorted(map(str, table.scan()["Items"]))
    get_record(SUHYUN, cid)
    assert sorted(map(str, table.scan()["Items"])) == before


def test_conflict_exhausted_is_503_and_no_getitem_fallback(table, monkeypatch):
    _, cid = claimed()
    client = ddb.table().meta.client
    n = {"c": 0}

    def conflict(**kw):
        n["c"] += 1
        raise ClientError({"Error": {"Code": "TransactionCanceledException"}, "CancellationReasons": [{"Code": "TransactionConflict"}, {"Code": "None"}]}, "TransactGetItems")

    monkeypatch.setattr(client, "transact_get_items", conflict)
    monkeypatch.setattr(ddb.time, "sleep", lambda s: None)
    status, body = get_record(SUHYUN, cid)
    assert status == 503 and body["error"]["code"] == "TRY_AGAIN" and n["c"] == 4


def test_non_conflict_cancel_is_500_without_reason(table, monkeypatch):
    _, cid = claimed()
    client = ddb.table().meta.client

    def boom(**kw):
        raise ClientError({"Error": {"Code": "TransactionCanceledException"}, "CancellationReasons": [{"Code": "ValidationError"}]}, "TransactGetItems")

    monkeypatch.setattr(client, "transact_get_items", boom)
    status, body = get_record(SUHYUN, cid)
    assert status == 500 and body["error"]["code"] == "INTERNAL_ERROR" and "ValidationError" not in json.dumps(body)


def test_snapshot_is_one_consistent_point_when_write_lands_between(table, monkeypatch):
    """두 키를 한 번의 호출로 읽으므로, 호출 사이에 완료가 끝나도 claimStatus와 delivered가 같은 시점이다."""
    _, cid = claimed()
    call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "글"}, path={"claimId": cid})
    client = ddb.table().meta.client
    real = client.transact_get_items
    seen = {"calls": 0}

    def once(**kw):
        seen["calls"] += 1
        out = real(**kw)  # 한 시점의 값을 읽은 뒤
        if seen["calls"] == 1:  # 응답이 돌아온 직후 완료가 끝나는 경우
            call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
        return out

    monkeypatch.setattr(client, "transact_get_items", once)
    _, body = get_record(SUHYUN, cid)
    assert seen["calls"] == 1 and (body["claimStatus"], body["delivered"]) == ("ACTIVE", False)
    _, later = get_record(SUHYUN, cid)
    assert (later["claimStatus"], later["delivered"]) == ("COMPLETED", True)


def test_photo_status_polling_sequence(table, monkeypatch):
    """UPLOAD_PENDING → PROCESSING → READY → (글만 완료 시) DISCARDED가 폴링으로 보인다."""
    monkeypatch.setenv("PHOTO_BUCKET", "haru-photos-test")
    pid, cid = claimed()
    call(claims.handler, "PUT /claims/{claimId}/record", SUHYUN, body={"letter": "글", "photo": {"contentType": "image/jpeg", "size": 10}}, path={"claimId": cid})
    key = table.get_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"})["Item"]["photoKey"]
    seq = [get_record(SUHYUN, cid)[1]["photoStatus"]]
    for to, frm in [("PROCESSING", ("UPLOAD_PENDING",)), ("READY", ("PROCESSING",))]:
        assert cs.photo_status_update(pid, cid, key=key, to=to, allowed_from=frm)
        seq.append(get_record(SUHYUN, cid)[1]["photoStatus"])
    call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
    _, body = get_record(SUHYUN, cid)
    seq.append(body["photoStatus"])
    assert seq == ["UPLOAD_PENDING", "PROCESSING", "READY", "DISCARDED"] and body["delivered"] is True
    assert body["record"]["photoStatus"] == body["photoStatus"]


def test_route_registered_in_template_and_routes():
    from handlers.routes import ROUTES

    assert ROUTES["GET /claims/{claimId}/record"] == "handlers.claims.handler"
