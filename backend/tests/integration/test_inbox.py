"""T17: 한 줄 답장은 InboxItem당 한 번만 저장된다 (AWS 스택 대상, 실제 병렬 호출).

결과 로그를 test-results/에 남긴다. 저장 값은 DynamoDB ConsistentRead로 직접 확인한다(BE-Q38).

Validates: spec backend-stage4-record-inbox Requirements 6.1, 6.3, 11.3
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.integration.conftest import call, create_plan, create_user, get_item, save_result

pytestmark = pytest.mark.integration


def _delivered(stack, owner: str, runner: str, title: str) -> str:
    """계획 생성 → 이어받기 → 글 저장 → 완료. claimId(= itemId)."""
    pid = create_plan(stack, owner, title)
    status, body = call(stack, "POST", f"/plans/{pid}/claims", token=runner)
    assert status == 201, body
    cid = body["claim"]["claimId"]
    status, body = call(stack, "PUT", f"/claims/{cid}/record", token=runner, body={"letter": "다녀왔어요"})
    assert status == 200, body
    status, body = call(stack, "POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    assert status == 200, body
    return cid


def test_T17_second_reply_is_409(stack):
    owner_sub, owner = create_user(stack, "T17지연")
    _, runner = create_user(stack, "T17수현")
    cid = _delivered(stack, owner, runner, "T17 답장 확인")
    first = call(stack, "POST", f"/inbox/{cid}/reply", token=owner, body={"text": "고마워요"})
    second = call(stack, "POST", f"/inbox/{cid}/reply", token=owner, body={"text": "한 번 더"})
    stored = get_item(stack, f"USER#{owner_sub}", f"INBOX#{cid}")
    log = save_result("T17-reply-twice", {"itemId": cid, "responses": [{"status": s, "body": b} for s, b in (first, second)], "storedReply": stored.get("reply")})
    assert first[0] == 201 and first[1]["reply"]["text"] == "고마워요", f"첫 답장은 201 (로그: {log})"
    assert second[0] == 409 and second[1]["error"]["code"] == "REPLY_ALREADY_SENT", f"두 번째는 409 (로그: {log})"
    assert stored["reply"] == first[1]["reply"]


def test_T17_concurrent_replies_one_wins(stack):
    owner_sub, owner = create_user(stack, "T17동시지연")
    _, runner = create_user(stack, "T17동시수현")
    cid = _delivered(stack, owner, runner, "T17 동시 답장")
    texts = [f"동시 답장 {i}" for i in range(10)]
    with ThreadPoolExecutor(10) as ex:
        results = list(ex.map(lambda t: call(stack, "POST", f"/inbox/{cid}/reply", token=owner, body={"text": t}), texts))
    stored = get_item(stack, f"USER#{owner_sub}", f"INBOX#{cid}")
    log = save_result("T17-concurrent-replies", {"itemId": cid, "responses": [{"status": s, "body": b} for s, b in results], "storedReply": stored.get("reply")})
    winners = [b["reply"] for s, b in results if s == 201]
    losers = [b["error"]["code"] for s, b in results if s != 201]
    assert len(winners) == 1, f"201은 정확히 1건 (로그: {log})"
    assert losers == ["REPLY_ALREADY_SENT"] * 9, f"나머지는 모두 409 REPLY_ALREADY_SENT (로그: {log})"
    assert stored["reply"] == winners[0], f"저장된 답장은 201 응답의 값 (로그: {log})"
