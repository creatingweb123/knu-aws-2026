"""4단계 로컬 통합 테스트: 수신함 흐름 (docker compose 환경, `pytest -m local`).

Floci에서 수신함 조건부 갱신(읽음·답장)이 처음 도는 테스트다. 조건식·흐름 확인용이고 T2·T17 판정 근거가 아니다(BE-Q15).

Validates: spec backend-stage4-record-inbox Requirement 11.2
"""

import uuid

import pytest

from tests.local.conftest import call, dev_token
from tests.local.test_local_flow import plan_body

pytestmark = pytest.mark.local


def _delivered():
    """계획 생성 → 이어받기 → 글 저장 → 완료. (owner, runner, planId, claimId)."""
    owner, runner = dev_token(f"u-{uuid.uuid4()}", "지연"), dev_token(f"u-{uuid.uuid4()}", "수현")
    status, _, body = call("POST", "/plans", token=owner, body=plan_body(), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201
    pid = body["plan"]["planId"]
    status, _, body = call("POST", f"/plans/{pid}/claims", token=runner)
    assert status == 201
    cid = body["claim"]["claimId"]
    assert call("PUT", f"/claims/{cid}/record", token=runner, body={"letter": "소금빵을 샀어요"})[0] == 200
    status, _, body = call("POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    assert status == 200 and body["delivered"] is True
    return owner, runner, pid, cid


def test_inbox_flow_read_and_reply():
    owner, runner, pid, cid = _delivered()

    status, _, me = call("GET", "/me", token=owner)
    assert status == 200 and me["unreadInboxCount"] == 1

    status, _, listed = call("GET", "/inbox", token=owner)
    assert status == 200 and [i["itemId"] for i in listed["items"]] == [cid]
    item = listed["items"][0]
    assert item["planId"] == pid and item["read"] is False and item["reply"] is None and item["hasPhoto"] is False
    assert item["claimerNickname"] == "수현" and "ownerId" not in item

    status, _, detail = call("GET", f"/inbox/{cid}", token=owner)
    assert status == 200 and detail["plan"]["planId"] == pid
    assert detail["record"]["letter"] == "소금빵을 샀어요" and detail["record"]["deliveredAt"]
    assert detail["record"]["photoUrl"] is None and detail["record"]["photoCaption"] is None  # BE-Q42
    assert call("GET", "/me", token=owner)[2]["unreadInboxCount"] == 1  # 상세 조회는 읽음 처리가 아니다

    status, _, body = call("POST", f"/inbox/{cid}/read", token=owner)
    assert status == 204 and body is None
    assert call("POST", f"/inbox/{cid}/read", token=owner)[0] == 204  # BE-Q44 재요청
    assert call("GET", "/me", token=owner)[2]["unreadInboxCount"] == 0

    status, _, body = call("POST", f"/inbox/{cid}/reply", token=owner, body={"text": "고마워요"})
    assert status == 201 and body["reply"]["text"] == "고마워요" and body["reply"]["sentAt"].endswith("Z")
    status, _, body = call("POST", f"/inbox/{cid}/reply", token=owner, body={"text": "한 번 더"})
    assert status == 409 and body["error"]["code"] == "REPLY_ALREADY_SENT"

    status, _, listed = call("GET", "/inbox", token=owner)
    assert listed["items"][0]["read"] is True and listed["items"][0]["reply"]["text"] == "고마워요"


def test_inbox_is_owner_only():
    owner, runner, _, cid = _delivered()
    other = dev_token(f"u-{uuid.uuid4()}", "민준")
    for token in (runner, other):  # 실행자도 itemId(= claimId)를 알지만 볼 수 없다
        assert call("GET", "/inbox", token=token)[2] == {"items": []}
        assert call("GET", "/me", token=token)[2]["unreadInboxCount"] == 0
        assert call("GET", f"/inbox/{cid}", token=token)[0] == 404
        assert call("POST", f"/inbox/{cid}/read", token=token)[0] == 404
        status, _, body = call("POST", f"/inbox/{cid}/reply", token=token, body={"text": "가로채기"})
        assert status == 404 and body["error"]["code"] == "NOT_FOUND"
    status, _, listed = call("GET", "/inbox", token=owner)
    assert listed["items"][0]["read"] is False and listed["items"][0]["reply"] is None  # 404 요청 뒤 불변


def test_inbox_missing_item_and_validation():
    owner = dev_token(f"u-{uuid.uuid4()}", "지연")
    assert call("GET", "/inbox/clm_none", token=owner)[0] == 404
    assert call("POST", "/inbox/clm_none/read", token=owner)[0] == 404
    status, _, body = call("POST", "/inbox/clm_none/reply", token=owner, body={"text": ""})
    assert status == 400 and "text" in body["error"]["details"]


@pytest.mark.parametrize("method,path", [("GET", "/inbox"), ("GET", "/inbox/clm_x"), ("POST", "/inbox/clm_x/read"), ("POST", "/inbox/clm_x/reply")])
def test_inbox_no_token_401(method, path):
    status, _, body = call(method, path, body={} if method == "POST" else None)
    assert status == 401 and body["error"]["code"] == "UNAUTHORIZED"
