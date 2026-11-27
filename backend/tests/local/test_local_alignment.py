"""로컬 통합 회귀: 프론트·백엔드 정합성 점검에서 찾은 사례 (docs/08 BE-Q45, 기한 정책).

docker compose 환경 대상, `pytest -m local tests/local/test_local_alignment.py`.
- 닉네임 없는 ID 토큰(dev JWT)으로 만든 계획은 `owner.nickname`·`ownerNickname`·`claimer.nickname`을 null로 내보낸다.
  빈 문자열이나 가짜 값을 쓰지 않는다. 프론트는 기본 표시명으로 바꿔 보여 준다(BE-Q45).
- 기한이 지난 뒤 다른 사람이 이어받으면 이전 Claim은 EXPIRED가 되고 이후 쓰기·완료·포기는 409 CLAIM_NOT_ACTIVE다.
  기한이 지났어도 새 실행자가 오기 전까지 실행자 본인은 기록·완료할 수 있다(늦은 완료, 기존 정책 유지).
기한은 로컬 테이블에서 dueAt을 과거로 옮겨 재현한다(3일을 기다리지 않는다). 판정 근거가 아니다(BE-Q15).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.local.conftest import boto, call, dev_token

pytestmark = pytest.mark.local

TABLE = "HaruTable"


def _plan_body(title: str) -> dict:
    return {
        "title": title,
        "summary": "회귀 확인용 계획이에요.",
        "reason": "일정이 바뀌었어요.",
        "estimatedMinutes": 30,
        "places": [{"name": "하천 벤치", "activity": "잠깐 쉬기", "whyChosen": ""}],
        "question": "무엇이 보였나요?",
        "authoring": {"mode": "MANUAL", "durationMs": 1000, "story": "하천 벤치에서 잠깐 쉬고 싶었어요."},
    }


def _past_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _move_due_into_past(plan_id: str, claim_id: str) -> None:
    ddb = boto("dynamodb")
    for key in ({"PK": {"S": f"PLAN#{plan_id}"}, "SK": {"S": "META"}}, {"PK": {"S": f"PLAN#{plan_id}"}, "SK": {"S": f"CLAIM#{claim_id}"}}):
        ddb.update_item(
            TableName=TABLE,
            Key=key,
            UpdateExpression="SET dueAt = :d",
            ExpressionAttributeValues={":d": {"S": _past_iso()}},
        )


def test_owner_without_nickname_claim_gets_null_everywhere():
    owner_id = f"u-local-nonick-{uuid.uuid4().hex[:8]}"
    owner = dev_token(owner_id)  # nickname 클레임 없음
    status, _, created = call("POST", "/plans", token=owner, body=_plan_body("닉네임 없는 계획"), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201, created
    plan_id = created["plan"]["planId"]
    assert created["plan"]["owner"] == {"userId": owner_id, "nickname": None}

    viewer = dev_token(f"u-local-viewer-{uuid.uuid4().hex[:8]}", "민준")
    status, _, detail = call("GET", f"/plans/{plan_id}", token=viewer)
    assert status == 200 and detail["plan"]["owner"]["nickname"] is None
    status, _, listed = call("GET", "/plans?status=OPEN&limit=50", token=viewer)
    assert status == 200
    summary = [i for i in listed["items"] if i["planId"] == plan_id]
    assert summary and summary[0]["ownerNickname"] is None

    status, _, claim = call("POST", f"/plans/{plan_id}/claims", token=viewer)
    assert status == 201
    assert claim["claim"]["claimer"]["nickname"] == "민준"
    # 이어받은 사람에게 닉네임이 없으면 claimer.nickname도 null이다(InboxItem의 claimerNickname도 같은 규칙)
    nonick_claimer = dev_token(f"u-local-claimer-{uuid.uuid4().hex[:8]}")
    other_plan = call("POST", "/plans", token=owner, body=_plan_body("이어받기 확인"), headers={"Idempotency-Key": str(uuid.uuid4())})[2]["plan"]["planId"]
    status, _, claim2 = call("POST", f"/plans/{other_plan}/claims", token=nonick_claimer)
    assert status == 201 and claim2["claim"]["claimer"]["nickname"] is None


def test_takeover_after_due_expires_previous_claim_and_blocks_writes():
    owner = dev_token(f"u-local-owner-{uuid.uuid4().hex[:8]}", "지연")
    first = dev_token(f"u-local-first-{uuid.uuid4().hex[:8]}", "수현")
    second = dev_token(f"u-local-second-{uuid.uuid4().hex[:8]}", "민준")

    status, _, created = call("POST", "/plans", token=owner, body=_plan_body("기한 정책"), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201
    plan_id = created["plan"]["planId"]
    status, _, claimed = call("POST", f"/plans/{plan_id}/claims", token=first)
    assert status == 201
    old_claim = claimed["claim"]["claimId"]

    # 기한 전: 다른 사람은 이어받을 수 없고 실행자 본인은 기록할 수 있다
    status, _, body = call("POST", f"/plans/{plan_id}/claims", token=second)
    assert status == 409 and body["error"]["code"] == "ALREADY_CLAIMED"

    _move_due_into_past(plan_id, old_claim)

    status, _, detail = call("GET", f"/plans/{plan_id}", token=second)
    assert status == 200 and detail["plan"]["status"] == "OPEN" and detail["claimable"] is True
    status, _, detail_first = call("GET", f"/plans/{plan_id}", token=first)
    assert detail_first["plan"]["status"] == "CLAIMED" and detail_first["myClaim"]["status"] == "ACTIVE"

    # 늦은 완료: 새 실행자가 오기 전까지 실행자 본인은 기록과 완료를 할 수 있다
    status, _, _ = call("PUT", f"/claims/{old_claim}/record", token=first, body={"letter": "늦었지만 다녀왔어요."})
    assert status == 200

    status, _, taken = call("POST", f"/plans/{plan_id}/claims", token=second)
    assert status == 201 and taken["claim"]["status"] == "ACTIVE"

    status, _, rec = call("GET", f"/claims/{old_claim}/record", token=first)
    assert status == 200 and rec["claimStatus"] == "EXPIRED" and rec["delivered"] is False
    status, _, body = call("POST", f"/claims/{old_claim}/complete", token=first, body={"mode": "TEXT_ONLY"})
    assert status == 409 and body["error"]["code"] == "CLAIM_NOT_ACTIVE"
    status, _, body = call("PUT", f"/claims/{old_claim}/record", token=first, body={"letter": "새로 쓰기"})
    assert status == 409 and body["error"]["code"] == "CLAIM_NOT_ACTIVE"
    status, _, body = call("POST", f"/claims/{old_claim}/abandon", token=first)
    assert status == 409 and body["error"]["code"] == "CLAIM_NOT_ACTIVE"

    status, _, mine = call("GET", "/me/claims?status=ACTIVE", token=first)
    assert status == 200 and old_claim not in [i["claim"]["claimId"] for i in mine["items"]]
