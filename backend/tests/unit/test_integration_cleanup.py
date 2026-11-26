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


def test_ai_session_and_quota_items_are_deleted(ddb):
    """6a: 테스트가 등록한 AiSession·AiQuota만 지운다."""
    put(ddb, "AISESSION#ais_1")
    put(ddb, "AIQUOTA#u1#20261126")
    put(ddb, "AISESSION#ais_other")
    s = stack(created_ai_session_ids=["ais_1", "ais_1"], created_ai_quota_pks=["AIQUOTA#u1#20261126"])
    it._cleanup(s, idp=FakeIdp(), ddb=ddb)
    assert keys(ddb) == {("AISESSION#ais_other", "META")}


def test_ai_create_registers_quota_before_request_and_session_after(monkeypatch):
    seen = {}

    def fake_call(stack_, method, path, *, token=None, body=None, headers=None):
        seen["quota_before"] = list(stack_.created_ai_quota_pks)
        return 200, {"sessionId": "ais_9"}

    monkeypatch.setattr(it, "call", fake_call)
    s = stack()
    it.ai_create(s, id_token("u-3"), "합성 사연")
    assert seen["quota_before"] and all(pk.startswith("AIQUOTA#u-3#") for pk in seen["quota_before"])
    assert s.created_ai_session_ids == ["ais_9"]


def test_ai_create_failure_registers_quota_only(monkeypatch):
    monkeypatch.setattr(it, "call", lambda *a, **k: (503, {"error": {"code": "AI_UNAVAILABLE"}}))
    s = stack()
    it.ai_create(s, id_token("u-4"), "합성 사연")
    assert s.created_ai_session_ids == [] and s.created_ai_quota_pks


def test_kst_day_boundary():
    from datetime import datetime, timezone

    assert it.kst_day(datetime(2026, 11, 26, 14, 59, 59, 999000, tzinfo=timezone.utc)) == "20261126"
    assert it.kst_day(datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)) == "20261127"


def test_t12_baseline_rules(tmp_path, monkeypatch):
    """BE-Q128: 인증 실패 판정은 정상 키로 같은 엔드포인트·모델이 확인된 기록이 있을 때만."""
    import json

    from tests.integration import test_ai

    fn = {"LLM_BASE_URL": "https://integrate.api.nvidia.com/v1", "LLM_MODEL": "nvidia/nemotron-3.5-lightning-30b-a3b"}
    monkeypatch.delenv("T12_BASELINE", raising=False)
    assert test_ai.t12_baseline(fn)[0] is False
    p = tmp_path / "probe.json"
    p.write_text(json.dumps({"base_url": fn["LLM_BASE_URL"], "model": fn["LLM_MODEL"], "raw": {"thinking_off": {"status": 200}}}), encoding="utf-8")
    monkeypatch.setenv("T12_BASELINE", str(p))
    assert test_ai.t12_baseline(fn) == (True, "")
    assert test_ai.t12_baseline(dict(fn, LLM_MODEL="other"))[0] is False
    p.write_text(json.dumps({"base_url": fn["LLM_BASE_URL"], "model": fn["LLM_MODEL"], "raw": {"thinking_off": {"status": 404}}}), encoding="utf-8")
    assert test_ai.t12_baseline(fn)[0] is False
    assert test_ai.AUTH_FAILURES == ("HTTP_401", "HTTP_403")
