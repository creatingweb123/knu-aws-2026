"""AWS 통합 테스트 정리(`tests/integration/conftest._cleanup`) 회귀 테스트.

2026-11-25 haru-dev 판정 뒤 멱등 키(IDEM#) 14건, Cognito 사용자 15명 등이 남았다.
- IDEM#{sub}#{key}는 키마다 파티션이 따로라 USER#{sub} 조회로는 지워지지 않았다(코드로 확인한 원인).
- 사용자 삭제 예외를 삼켜 원인 기록이 없었고, DynamoDB 삭제는 예외 하나로 나머지 정리가 모두 멈췄다.
AWS에 접속하지 않는다. DynamoDB는 moto, Cognito는 호출을 기록하는 가짜 클라이언트로 대신한다.
"""

from __future__ import annotations

import json
import uuid

import boto3
import jwt
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from tests.integration import conftest as it
from tests.unit.moto_table import create_haru_table, set_env

POOL = "ap-northeast-2_test"


class FakeIdp:
    def __init__(self, fail: dict[str, str] | None = None):
        self.fail = fail or {}
        self.deleted: list[str] = []

    def admin_delete_user(self, UserPoolId: str, Username: str) -> None:  # noqa: N803 (boto3 인자 이름)
        assert UserPoolId == POOL
        if Username in self.fail:
            raise ClientError({"Error": {"Code": self.fail[Username], "Message": "x"}}, "AdminDeleteUser")
        self.deleted.append(Username)


@pytest.fixture
def ddb(monkeypatch, tmp_path):
    set_env(monkeypatch)
    monkeypatch.setattr(it, "RESULTS_DIR", str(tmp_path))
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-northeast-2")
        create_haru_table(client)
        yield client


def put(client, pk: str, sk: str = "META") -> None:
    client.put_item(TableName="HaruTable", Item={"PK": {"S": pk}, "SK": {"S": sk}})


def keys(client) -> set[tuple[str, str]]:
    return {(i["PK"]["S"], i["SK"]["S"]) for i in client.scan(TableName="HaruTable")["Items"]}


def stack(**kw) -> it.Stack:
    return it.Stack("https://api.example", POOL, "client", "HaruTable", **kw)


def id_token(sub: str) -> str:
    return jwt.encode({"sub": sub, "token_use": "id"}, "k" * 32, algorithm="HS256")


def test_idem_keys_are_deleted_and_others_kept(ddb):
    """회귀: 테스트가 쓴 멱등 키 항목이 지워진다. 등록하지 않은 키는 건드리지 않는다."""
    put(ddb, "IDEM#u1#k1")
    put(ddb, "IDEM#u1#k2")
    put(ddb, "IDEM#other#k9")
    s = stack(created_subs=["u1"], created_idem_pks=["IDEM#u1#k1", "IDEM#u1#k2"])
    it._cleanup(s, idp=FakeIdp(), ddb=ddb)
    assert keys(ddb) == {("IDEM#other#k9", "META")}


def test_plan_user_partitions_and_claim_lookup_are_deleted(ddb):
    for sk in ("META", "CLAIM#clm_1", "RECORD#clm_1"):
        put(ddb, "PLAN#pln_1", sk)
    put(ddb, "CLAIM#clm_1")  # ClaimLookup
    put(ddb, "USER#owner", "INBOX#clm_1")
    put(ddb, "PLAN#pln_other")  # 다른 사람 계획
    s = stack(created_plan_ids=["pln_1", "pln_1"], created_subs=["owner"])  # 중복 등록도 한 번만
    it._cleanup(s, idp=FakeIdp(), ddb=ddb)
    assert keys(ddb) == {("PLAN#pln_other", "META")}


def test_large_partition_is_fully_deleted(ddb):
    """쿼리 한 페이지(1MB)를 넘는 파티션도 끝까지 지운다."""
    blob = "x" * 50_000
    for i in range(30):  # 약 1.5MB
        ddb.put_item(TableName="HaruTable", Item={"PK": {"S": "PLAN#big"}, "SK": {"S": f"R#{i:02d}"}, "b": {"S": blob}})
    it._cleanup(stack(created_plan_ids=["big"]), idp=FakeIdp(), ddb=ddb)
    assert keys(ddb) == set()


def test_one_failure_does_not_stop_the_rest_and_is_reported(ddb, tmp_path):
    """회귀: 예외를 삼키지 않고, 한 대상이 실패해도 나머지를 계속 지운 뒤 실패를 알린다."""
    put(ddb, "PLAN#pln_1")
    put(ddb, "IDEM#u1#k1")
    idp = FakeIdp(fail={"a@example.com": "TooManyRequestsException"})
    s = stack(created_users=["a@example.com", "b@example.com"], created_plan_ids=["pln_1"], created_idem_pks=["IDEM#u1#k1"])
    with pytest.raises(RuntimeError, match="정리 실패 1건"):
        it._cleanup(s, idp=idp, ddb=ddb)
    assert idp.deleted == ["b@example.com"]
    assert keys(ddb) == set()
    [log] = list(tmp_path.glob("cleanup-failures-*.json"))
    data = json.loads(log.read_text(encoding="utf-8"))
    assert data["failures"] == [{"kind": "cognito_user", "target": "a@example.com", "error": "TooManyRequestsException"}]


def test_already_deleted_user_is_not_a_failure(ddb, tmp_path):
    idp = FakeIdp(fail={"gone@example.com": "UserNotFoundException"})
    it._cleanup(stack(created_users=["gone@example.com"]), idp=idp, ddb=ddb)
    assert list(tmp_path.glob("cleanup-failures-*.json")) == []


def test_create_plan_registers_idem_key_before_request(monkeypatch):
    sent = {}

    def fake_call(stack_, method, path, *, token=None, body=None, headers=None):
        sent["key"] = headers["Idempotency-Key"]
        assert stack_.created_idem_pks == [f"IDEM#u-1#{sent['key']}"]  # 요청 전에 등록
        return 201, {"plan": {"planId": "pln_1"}}

    monkeypatch.setattr(it, "call", fake_call)
    s = stack()
    assert it.create_plan(s, id_token("u-1")) == "pln_1"
    assert s.created_plan_ids == ["pln_1"]
    uuid.UUID(sent["key"])


def test_create_plan_failure_still_registers_idem_key(monkeypatch):
    monkeypatch.setattr(it, "call", lambda *a, **k: (503, {"error": {"code": "TRY_AGAIN"}}))
    s = stack()
    with pytest.raises(AssertionError):
        it.create_plan(s, id_token("u-2"))
    assert len(s.created_idem_pks) == 1 and s.created_idem_pks[0].startswith("IDEM#u-2#")
    assert s.created_plan_ids == []


# ------------------------------------------------------------------ 5단계 사진 prefix 정리

PHOTO_BUCKET = "haru-dev-photos-123"


@pytest.fixture
def s3(ddb):
    client = boto3.client("s3", region_name="ap-northeast-2")
    client.create_bucket(Bucket=PHOTO_BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
    return client


def objects(client) -> set[str]:
    return {o["Key"] for o in client.list_objects_v2(Bucket=PHOTO_BUCKET).get("Contents", [])}


def photo_stack(**kw) -> it.Stack:
    return stack(photo={"bucket": PHOTO_BUCKET}, **kw)


def test_photo_prefixes_deleted_others_kept(ddb, s3):
    for key in ("photos/original/clm_1/a.jpg", "photos/processed/clm_1/x.jpg", "photos/original/clm_10/b.jpg",
                "photos/original/clm_other/c.jpg", "photos/processed/clm_other/y.jpg"):
        s3.put_object(Bucket=PHOTO_BUCKET, Key=key, Body=b"1")
    it._cleanup(photo_stack(created_photo_claim_ids=["clm_1", "clm_1"]), idp=FakeIdp(), ddb=ddb, s3=s3, sleep=lambda s: None)
    # clm_1/ prefix는 끝에 /가 있어 clm_10을 건드리지 않는다
    assert objects(s3) == {"photos/original/clm_10/b.jpg", "photos/original/clm_other/c.jpg", "photos/processed/clm_other/y.jpg"}


def test_photo_prefix_pagination(ddb, s3):
    for i in range(1005):  # ListObjectsV2 한 페이지(1000개)를 넘는다
        s3.put_object(Bucket=PHOTO_BUCKET, Key=f"photos/processed/clm_1/{i:04d}.jpg", Body=b"")
    it._cleanup(photo_stack(created_photo_claim_ids=["clm_1"]), idp=FakeIdp(), ddb=ddb, s3=s3, sleep=lambda s: None)
    assert objects(s3) == set()


def test_dynamodb_deleted_before_s3_and_second_pass_records_late_objects(ddb, s3, tmp_path):
    for sk in ("META", "CLAIM#clm_1", "RECORD#clm_1"):
        put(ddb, "PLAN#pln_1", sk)
    put(ddb, "CLAIM#clm_1")  # ClaimLookup
    s3.put_object(Bucket=PHOTO_BUCKET, Key="photos/original/clm_1/a.jpg", Body=b"1")
    order = []

    class SpyS3:
        def list_objects_v2(self, **kw):
            order.append(("s3", sorted(keys(ddb))))
            return s3.list_objects_v2(**kw)

        def delete_object(self, **kw):
            return s3.delete_object(**kw)

    def late_lambda(seconds):
        assert seconds == it.CLEANUP_SECOND_PASS_S
        s3.put_object(Bucket=PHOTO_BUCKET, Key="photos/processed/clm_1/late.jpg", Body=b"1")  # 정리 중 늦게 온 처리본

    it._cleanup(photo_stack(created_plan_ids=["pln_1"], created_photo_claim_ids=["clm_1"]), idp=FakeIdp(), ddb=ddb, s3=SpyS3(), sleep=late_lambda)
    assert order and all(snapshot == [] for _, snapshot in order)  # S3를 처음 볼 때 이미 DynamoDB는 비어 있다
    assert objects(s3) == set()
    [log] = list(tmp_path.glob("cleanup-late-objects-*.json"))
    assert json.loads(log.read_text(encoding="utf-8"))["objects"] == ["photos/processed/clm_1/late.jpg"]
    assert list(tmp_path.glob("cleanup-failures-*.json")) == []


def test_s3_failure_recorded_and_independent(ddb, s3, tmp_path):
    put(ddb, "PLAN#pln_1")

    class BrokenS3:
        def list_objects_v2(self, **kw):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "ListObjectsV2")

    idp = FakeIdp()
    s = photo_stack(created_users=["a@example.com"], created_plan_ids=["pln_1"], created_photo_claim_ids=["clm_1"])
    with pytest.raises(RuntimeError, match="정리 실패 4건"):  # 2 prefix × 2회
        it._cleanup(s, idp=idp, ddb=ddb, s3=BrokenS3(), sleep=lambda s: None)
    assert idp.deleted == ["a@example.com"] and keys(ddb) == set()
    [log] = list(tmp_path.glob("cleanup-failures-*.json"))
    fails = json.loads(log.read_text(encoding="utf-8"))["failures"]
    assert {f["kind"] for f in fails} == {"s3_prefix"} and {f["error"] for f in fails} == {"AccessDenied"}


def test_no_photo_claims_no_s3_and_no_wait(ddb):
    def no_sleep(_):
        raise AssertionError("사진 Claim이 없으면 기다리지 않는다")

    it._cleanup(stack(), idp=FakeIdp(), ddb=ddb, s3=object(), sleep=no_sleep)


def test_unknown_bucket_is_a_failure(ddb):
    with pytest.raises(RuntimeError, match="정리 실패 1건"):
        it._cleanup(stack(created_photo_claim_ids=["clm_1"]), idp=FakeIdp(), ddb=ddb, sleep=lambda s: None)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_wait_photo_settled_requires_stable_terminal_state(monkeypatch, tmp_path):
    monkeypatch.setattr(it, "RESULTS_DIR", str(tmp_path))
    clock = Clock()
    states = iter([{"photoStatus": "PROCESSING"}] * 3 + [{"photoStatus": "READY", "deliveredAt": "t"}] * 100)
    procs = iter([[]] * 3 + [["photos/processed/c/a.jpg"]] * 100)
    ok = it.wait_photo_settled(photo_stack(), "p", "c", read=lambda: next(states), list_processed=lambda: next(procs),
                               sleep=clock.sleep, clock=clock, interval=2, stable_s=30)
    assert ok is True
    assert clock.t >= 6 + 30  # 마지막 변화(6초) 뒤 30초 안정
    assert list(tmp_path.glob("cleanup_after_unsettled-*.json")) == []


def test_wait_photo_settled_timeout_records(monkeypatch, tmp_path):
    monkeypatch.setattr(it, "RESULTS_DIR", str(tmp_path))
    clock = Clock()
    ok = it.wait_photo_settled(photo_stack(), "p", "clm_9", read=lambda: {"photoStatus": "PROCESSING"}, list_processed=list,
                               sleep=clock.sleep, clock=clock, timeout_s=300)
    assert ok is False and clock.t >= 300
    [log] = list(tmp_path.glob("cleanup_after_unsettled-*.json"))
    assert json.loads(log.read_text(encoding="utf-8"))["claimId"] == "clm_9"


def test_wait_photo_settled_changing_processed_list_resets_timer(monkeypatch, tmp_path):
    monkeypatch.setattr(it, "RESULTS_DIR", str(tmp_path))
    clock = Clock()
    n = {"i": 0}

    def procs():
        n["i"] += 1
        return [f"k{n['i']}"] if n["i"] <= 10 else ["k10"]  # 20초 동안 처리본 목록이 계속 바뀐다

    ok = it.wait_photo_settled(photo_stack(), "p", "c", read=lambda: {"photoStatus": "FAILED"}, list_processed=procs,
                               sleep=clock.sleep, clock=clock, interval=2, stable_s=30)
    assert ok is True and clock.t >= 18 + 30


def test_wait_record_reports_observed_states():
    clock = Clock()
    seq = iter([None, {"photoStatus": "UPLOAD_PENDING"}, {"photoStatus": "PROCESSING"}, {"photoStatus": "PROCESSING"},
                {"photoStatus": "READY", "deliveredAt": "t"}])
    rec, seen = it.wait_record(photo_stack(), "p", "c", lambda r: bool(r.get("deliveredAt")), read=lambda: next(seq),
                               sleep=clock.sleep, clock=clock)
    assert rec["photoStatus"] == "READY"
    assert seen == ["NONE", "UPLOAD_PENDING", "PROCESSING", "READY+delivered"]


def test_register_photo_claim_before_upload(monkeypatch):
    s = photo_stack()
    it.register_photo_claim(s, "clm_1")  # photo가 이미 있으면 CloudFormation을 부르지 않는다
    assert s.created_photo_claim_ids == ["clm_1"]


def test_photo_resources_reads_stack_once(monkeypatch):
    monkeypatch.setattr(it, "STACK_NAME", "haru-dev")
    calls = []

    class Cfn:
        def describe_stack_resource(self, StackName, LogicalResourceId):
            calls.append((StackName, LogicalResourceId))
            return {"StackResourceDetail": {"PhysicalResourceId": f"phys-{LogicalResourceId}"}}

    s = stack()
    res = it.photo_resources(s, cfn=Cfn())
    assert res == {"bucket": "phys-PhotoBucket", "queue_url": "phys-PhotoQueue", "dlq_url": "phys-PhotoDLQ",
                   "alarm": "phys-PhotoDLQNotEmpty", "function": "phys-PhotoProcessorFunction"}
    it.photo_resources(s, cfn=Cfn())
    assert len(calls) == 5


@pytest.mark.parametrize(
    ("expr", "selected"),
    [("integration and fault", True), ("fault", True), ("integration", False), ("integration and not fault", False),
     ("not local and not integration and not slow and not fault", False), ("", False)],
)
def test_fault_tests_only_with_explicit_marker(expr, selected):
    assert it._selects_fault(expr) is selected
