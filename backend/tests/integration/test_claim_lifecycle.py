"""T6·T7·T16: 포기 뒤 이전 요청 거부와 목록 재노출 (AWS 스택 대상). G3의 판정이다.

Validates: spec backend-stage3-claim Requirements 2.1, 2.5, 3.3, 4.9, 4.10 / Property 15
"""

import time

import pytest

from tests.integration.conftest import call, create_plan, create_user, query_items

pytestmark = pytest.mark.integration


def _claim(stack, pid, token):
    status, body = call(stack, "POST", f"/plans/{pid}/claims", token=token)
    assert status == 201, body
    return body["claim"]["claimId"]


def test_T6_writes_after_abandon_are_rejected(stack):
    owner_sub, owner = create_user(stack, "T6지연")
    pid = create_plan(stack, owner)
    _, token = create_user(stack, "T6수현")
    cid = _claim(stack, pid, token)
    assert call(stack, "PUT", f"/claims/{cid}/record", token=token, body={"letter": "쓰던 글"})[0] == 200
    status, body = call(stack, "POST", f"/claims/{cid}/abandon", token=token)
    assert status == 200 and body["claim"]["status"] == "ABANDONED"

    status, err = call(stack, "PUT", f"/claims/{cid}/record", token=token, body={"letter": "포기 뒤 글"})
    assert status == 409 and err["error"]["code"] == "CLAIM_NOT_ACTIVE"
    status, err = call(stack, "POST", f"/claims/{cid}/complete", token=token, body={"mode": "TEXT_ONLY"})
    assert status == 409 and err["error"]["code"] == "CLAIM_NOT_ACTIVE"
    assert query_items(stack, f"USER#{owner_sub}", "INBOX#") == []


def test_T7_late_completion_after_reclaim(stack):
    owner_sub, owner = create_user(stack, "T7지연")
    pid = create_plan(stack, owner)
    _, first = create_user(stack, "T7수현")
    _, second = create_user(stack, "T7민준")
    old = _claim(stack, pid, first)
    call(stack, "PUT", f"/claims/{old}/record", token=first, body={"letter": "첫 글"})
    assert call(stack, "POST", f"/claims/{old}/abandon", token=first)[0] == 200
    new = _claim(stack, pid, second)

    status, err = call(stack, "POST", f"/claims/{old}/complete", token=first, body={"mode": "TEXT_ONLY"})
    assert status == 409 and err["error"]["code"] == "CLAIM_NOT_ACTIVE"
    assert call(stack, "PUT", f"/claims/{new}/record", token=second, body={"letter": "두 번째 글"})[0] == 200
    status, body = call(stack, "POST", f"/claims/{new}/complete", token=second, body={"mode": "TEXT_ONLY"})
    assert status == 200 and body["delivered"] is True
    inbox = query_items(stack, f"USER#{owner_sub}", "INBOX#")
    assert [i["itemId"] for i in inbox] == [new]


def test_T16_abandoned_plan_is_listed_again(stack):
    _, owner = create_user(stack, "T16지연")
    pid = create_plan(stack, owner)
    _, token = create_user(stack, "T16수현")
    cid = _claim(stack, pid, token)
    assert call(stack, "POST", f"/claims/{cid}/abandon", token=token)[0] == 200
    # 목록은 GSI1(최종 일관성)이므로 잠시 기다리며 다시 본다
    for _ in range(10):
        status, listed = call(stack, "GET", "/plans?status=OPEN&limit=50", token=token)
        assert status == 200
        if pid in [i["planId"] for i in listed["items"]]:
            break
        time.sleep(1)
    else:
        pytest.fail("포기한 계획이 10초 안에 OPEN 목록에 다시 나오지 않았다")
    status, detail = call(stack, "GET", f"/plans/{pid}", token=token)
    assert detail["plan"]["status"] == "OPEN" and detail["claimable"] is True and detail["myClaim"] is None
