"""3단계 로컬 통합 테스트 (docker compose 환경, `pytest -m local`). 판정 근거가 아니다(BE-Q15).

Floci가 TransactWriteItems의 조건식(ConditionCheck 포함)을 처리하는지 처음 확인하는 테스트이기도 하다.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.local.conftest import call, dev_token
from tests.local.test_local_flow import plan_body

pytestmark = pytest.mark.local


def _plan(owner):
    status, body = call("POST", "/plans", token=owner, body=plan_body(), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201
    return body["plan"]["planId"]


def test_claim_record_complete_flow():
    owner, runner = dev_token(f"u-{uuid.uuid4()}", "지연"), dev_token(f"u-{uuid.uuid4()}", "수현")
    pid = _plan(owner)
    status, body = call("POST", f"/plans/{pid}/claims", token=runner)
    assert status == 201
    cid = body["claim"]["claimId"]
    assert call("POST", f"/plans/{pid}/claims", token=runner)[0] == 200
    status, body = call("GET", "/me/claims?status=ACTIVE", token=runner)
    assert status == 200
    assert call("PUT", f"/claims/{cid}/record", token=runner, body={"letter": "다녀왔어요"})[0] == 200
    status, body = call("POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    assert status == 200 and body["delivered"] is True
    assert call("POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})[0] == 200


def test_concurrent_claims_condition_logic():
    """조건식 로직 확인일 뿐이다. 실제 동시성 판정은 AWS(T3)."""
    owner = dev_token(f"u-{uuid.uuid4()}", "지연")
    pid = _plan(owner)
    tokens = [dev_token(f"u-{uuid.uuid4()}", f"실행자{i}") for i in range(5)]
    with ThreadPoolExecutor(5) as ex:
        results = list(ex.map(lambda t: call("POST", f"/plans/{pid}/claims", token=t), tokens))
    assert [s for s, _, _ in results].count(201) == 1
    assert all(s in (201, 409, 503) for s, _, _ in results)


def test_abandon_then_stale_writes_rejected():
    owner, runner = dev_token(f"u-{uuid.uuid4()}", "지연"), dev_token(f"u-{uuid.uuid4()}", "수현")
    pid = _plan(owner)
    cid = call("POST", f"/plans/{pid}/claims", token=runner)[2]["claim"]["claimId"]
    assert call("POST", f"/claims/{cid}/abandon", token=runner)[0] == 200
    status, _, body = call("PUT", f"/claims/{cid}/record", token=runner, body={"letter": "늦은 글"})
    assert status == 409 and body["error"]["code"] == "CLAIM_NOT_ACTIVE"
