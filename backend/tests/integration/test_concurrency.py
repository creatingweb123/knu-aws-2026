"""T3·T4·T5·T14: 동시성 (AWS 스택 대상, 실제 병렬 호출). G1·G2의 최종 판정이다.

건수는 DynamoDB를 ConsistentRead로 직접 조회해 확인한다(수신함 API는 4단계, BE-Q38).
T3·T5는 결과 로그를 test-results/에 남긴다(docs/07 §7.6).

Validates: spec backend-stage3-claim Requirements 1.3, 1.4, 1.7, 4.5 / Property 12, 14
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import boto3
import pytest

from tests.integration.conftest import REGION, call, create_plan, create_user, get_item, query_items, save_result

pytestmark = pytest.mark.integration


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def test_T3_ten_users_claim_one_wins(stack):
    _, owner = create_user(stack, "T3지연")
    pid = create_plan(stack, owner)
    tokens = [create_user(stack, f"T3실행자{i}")[1] for i in range(10)]
    with ThreadPoolExecutor(10) as ex:
        results = list(ex.map(lambda t: call(stack, "POST", f"/plans/{pid}/claims", token=t), tokens))
    plan = get_item(stack, f"PLAN#{pid}")
    claims = query_items(stack, f"PLAN#{pid}", "CLAIM#")
    log = save_result("T3-concurrent-claims", {"planId": pid, "responses": [{"status": s, "body": b} for s, b in results], "currentClaimId": plan.get("currentClaimId"), "claimItems": len(claims)})
    winners = [b["claim"]["claimId"] for s, b in results if s == 201]
    losers = [b["error"]["code"] for s, b in results if s != 201]
    assert len(winners) == 1, f"성공은 정확히 1건이어야 한다 (로그: {log})"
    assert losers == ["ALREADY_CLAIMED"] * 9, f"나머지는 모두 409 ALREADY_CLAIMED (로그: {log})"
    assert plan["currentClaimId"] == winners[0] and len(claims) == 1


def test_T4_same_user_five_times_one_claim(stack):
    _, owner = create_user(stack, "T4지연")
    pid = create_plan(stack, owner)
    _, token = create_user(stack, "T4수현")
    with ThreadPoolExecutor(5) as ex:
        results = list(ex.map(lambda _: call(stack, "POST", f"/plans/{pid}/claims", token=token), range(5)))
    save_result("T4-same-user", {"planId": pid, "responses": [{"status": s, "body": b} for s, b in results]})
    assert all(s in (200, 201) for s, _ in results), results
    assert len({b["claim"]["claimId"] for _, b in results}) == 1
    assert len(query_items(stack, f"PLAN#{pid}", "CLAIM#")) == 1


def test_T5_ten_completions_one_inbox_item(stack):
    owner_sub, owner = create_user(stack, "T5지연")
    pid = create_plan(stack, owner)
    _, token = create_user(stack, "T5수현")
    status, body = call(stack, "POST", f"/plans/{pid}/claims", token=token)
    assert status == 201
    cid = body["claim"]["claimId"]
    status, _ = call(stack, "PUT", f"/claims/{cid}/record", token=token, body={"letter": "소금빵을 샀어요"})
    assert status == 200
    with ThreadPoolExecutor(10) as ex:
        results = list(ex.map(lambda _: call(stack, "POST", f"/claims/{cid}/complete", token=token, body={"mode": "TEXT_ONLY"}), range(10)))
    inbox = query_items(stack, f"USER#{owner_sub}", "INBOX#")
    record = get_item(stack, f"PLAN#{pid}", f"RECORD#{cid}")
    log = save_result("T5-concurrent-complete", {"claimId": cid, "responses": [{"status": s, "body": b} for s, b in results], "inboxItems": len(inbox), "recordDeliveredAt": record.get("deliveredAt")})
    assert [s for s, _ in results] == [200] * 10, f"응답은 모두 200 (로그: {log})"
    assert all(b["delivered"] is True for _, b in results)
    assert len(inbox) == 1 and inbox[0]["itemId"] == cid and "reply" not in inbox[0]
    assert record.get("deliveredAt") and get_item(stack, f"PLAN#{pid}")["status"] == "COMPLETED"


def test_T14_expired_claim_is_replaced(stack):
    """기한 3일을 기다릴 수 없으므로 dueAt을 과거로 직접 바꾼다(BE-Q38)."""
    _, owner = create_user(stack, "T14지연")
    pid = create_plan(stack, owner)
    _, first = create_user(stack, "T14수현")
    _, second = create_user(stack, "T14민준")
    status, body = call(stack, "POST", f"/plans/{pid}/claims", token=first)
    assert status == 201
    old = body["claim"]["claimId"]
    past = _iso(datetime.now(timezone.utc) - timedelta(hours=1))
    table = boto3.resource("dynamodb", region_name=REGION).Table(stack.table_name)
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": "META"}, UpdateExpression="SET dueAt = :d", ExpressionAttributeValues={":d": past})
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"CLAIM#{old}"}, UpdateExpression="SET dueAt = :d", ExpressionAttributeValues={":d": past})

    status, detail = call(stack, "GET", f"/plans/{pid}", token=second)
    assert status == 200 and detail["plan"]["status"] == "OPEN" and detail["claimable"] is True
    status, body = call(stack, "POST", f"/plans/{pid}/claims", token=second)
    assert status == 201
    assert get_item(stack, f"PLAN#{pid}", f"CLAIM#{old}")["status"] == "EXPIRED"
    assert get_item(stack, f"PLAN#{pid}")["currentClaimId"] == body["claim"]["claimId"]
    # 대체된 첫 실행자의 늦은 쓰기는 거부된다(G3)
    status, err = call(stack, "PUT", f"/claims/{old}/record", token=first, body={"letter": "늦은 글"})
    assert status == 409 and err["error"]["code"] == "CLAIM_NOT_ACTIVE"


def test_get_record_snapshot_during_writes(stack):
    """BE-Q46 권장안: 기록 저장·완료가 오가는 동안 GET /record를 반복 호출해도 한 응답 안의 값이 서로 어긋나지 않는다.

    합격 기준: 모든 응답이 200 또는 503 TRY_AGAIN(재시도 소진)이고, 200이면
    claimStatus == COMPLETED ⇔ delivered == true ⇔ record.deliveredAt != null, photoStatus == record.photoStatus.
    503 비율은 측정값으로 남긴다(판정 근거가 아니라 BE-Q46·BE-Q48 결정 자료).
    """
    _, owner = create_user(stack, "SN지연")
    pid = create_plan(stack, owner)
    _, token = create_user(stack, "SN수현")
    status, body = call(stack, "POST", f"/plans/{pid}/claims", token=token)
    assert status == 201
    cid = body["claim"]["claimId"]
    stop = {"flag": False}

    def writer():
        for i in range(5):
            call(stack, "PUT", f"/claims/{cid}/record", token=token, body={"letter": f"글 {i}"})
        for _ in range(3):
            call(stack, "POST", f"/claims/{cid}/complete", token=token, body={"mode": "TEXT_ONLY"})
        stop["flag"] = True

    def reader(_):
        seen = []
        while not stop["flag"] and len(seen) < 200:
            seen.append(call(stack, "GET", f"/claims/{cid}/record", token=token))
        return seen

    with ThreadPoolExecutor(5) as ex:
        w = ex.submit(writer)
        reads = [r for rs in ex.map(reader, range(4)) for r in rs]
        w.result()
    bad = []
    for status, body in reads:
        if status == 503 and body["error"]["code"] == "TRY_AGAIN":
            continue
        if status != 200:
            bad.append((status, body))
            continue
        rec = body["record"]
        delivered = bool(rec and rec.get("deliveredAt"))
        if (body["claimStatus"] == "COMPLETED") != body["delivered"] or body["delivered"] != delivered or (rec and rec["photoStatus"] != body["photoStatus"]):
            bad.append((status, body))
    log = save_result("T-record-snapshot", {"reads": len(reads), "try_again": sum(1 for s, _ in reads if s == 503), "inconsistent": bad[:5]})
    assert bad == [], f"스냅샷 불일치 또는 예상 밖 응답 {len(bad)}건 (로그: {log})"
