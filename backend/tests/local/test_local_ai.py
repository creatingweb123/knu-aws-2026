"""로컬 통합: AI 하루 카드 레벨 0 (6a 작업 15.2, design §20.4). docker compose 환경 대상, `pytest -m local`.

Fake 모델(`llmMode: fake`)이라 공급자 품질 근거가 아니다. 판정 근거 아님(BE-Q15).
시나리오별 사례는 어댑터를 `FAKE_LLM_SCENARIO=<값>`으로 띄우고 pytest에 `LOCAL_FAKE_SCENARIO=<같은 값>`을 줄 때만 돈다.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.local.conftest import boto, call, dev_token

pytestmark = pytest.mark.local

SCENARIO = os.environ.get("LOCAL_FAKE_SCENARIO", "happy")
STORY = "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
TABLE = "HaruTable"
LIMIT = int(os.environ.get("LOCAL_AI_DAILY_SESSION_LIMIT", "10"))


def only(scenario):
    if os.environ.get("LOCAL_AGENT_MODE") == "agent":  # 6b: 레벨 0 사례는 pipeline 모드에서만(에이전트는 test_local_agent.py)
        return pytest.mark.skip(reason="레벨 0 사례. AGENT_MODE=pipeline(기본)으로 띄웠을 때만")
    return pytest.mark.skipif(SCENARIO != scenario, reason=f"어댑터를 FAKE_LLM_SCENARIO={scenario}로 띄우고 LOCAL_FAKE_SCENARIO={scenario}로 실행할 때만")


def user():
    uid = f"local-ai-{uuid.uuid4().hex[:10]}"
    return uid, dev_token(uid, "지연")


def ddb_item(pk):
    got = boto("dynamodb").get_item(TableName=TABLE, Key={"PK": {"S": pk}, "SK": {"S": "META"}}, ConsistentRead=True)
    return got.get("Item")


def create(token, story=STORY):
    return call("POST", "/ai/card-sessions", token=token, body={"story": story})


def plan_body(card, sid, mode="AI_EDITED"):
    places = [{"name": p["name"], "activity": p["activity"], "whyChosen": p["whyChosen"] or ""} for p in card["places"]]
    body = {k: card[k] for k in ("title", "summary", "reason", "estimatedMinutes", "question")} | {"places": places}
    body["authoring"] = {"mode": mode, "durationMs": 9000, "story": STORY, **({"aiSessionId": sid} if sid else {})}
    return body


@only("happy")
def test_create_get_turns_and_publish():
    uid, token = user()
    status, _, view = create(token)
    assert status == 200 and view["status"] == "READY" and view["turn"] == 1 and view["question"] is None, view
    sid = view["sessionId"]
    item = ddb_item(f"AISESSION#{sid}")
    assert item["llmMode"]["S"] == "fake" and item["ownerId"]["S"] == uid and item["agentMode"]["S"] == "PIPELINE"
    print("llmMode:", item["llmMode"]["S"])

    assert call("GET", f"/ai/card-sessions/{sid}", token=token)[2] == view
    status, _, body = call("POST", f"/ai/card-sessions/{sid}/turns", token=token, body={"expectedTurn": 1, "finish": True})
    assert status == 409 and body["error"]["code"] == "AI_SESSION_CLOSED"
    status, _, body = call("POST", f"/ai/card-sessions/{sid}/turns", token=token, body={"expectedTurn": 2})
    assert status == 200 and body == view

    title = view["card"]["title"] + " (수정)"
    pb = plan_body(view["card"], sid) | {"title": title[:40]}
    status, _, created = call("POST", "/plans", token=token, body=pb, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201, created
    plan = ddb_item(f"PLAN#{created['plan']['planId']}")
    metrics = plan["metrics"]["M"]
    assert metrics["agentMode"]["S"] == "PIPELINE" and metrics["modelCalls"]["N"] == "1"
    assert metrics["fieldsEditedAfterHandoff"]["N"] == "1" and "editMs" in metrics and "agentWaitMs" in metrics
    assert "llmMode" not in metrics  # 내부 속성은 Plan 지표에 없다

    manual = plan_body(view["card"], None, mode="MANUAL")
    status, _, m = call("POST", "/plans", token=token, body=manual, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201 and set(ddb_item(f"PLAN#{m['plan']['planId']}")["metrics"]["M"]) == {
        "authoringMode", "durationMs", "addedNotInSource", "privacyInPublished"}


@only("happy")
def test_other_users_session_is_404_same_as_missing():
    _, owner = user()
    _, other = user()
    sid = create(owner)[2]["sessionId"]
    a = call("GET", f"/ai/card-sessions/{sid}", token=other)
    b = call("GET", "/ai/card-sessions/ais_01ZZZZZZZZZZZZZZZZZZZZZZZZ", token=other)
    c = call("POST", f"/ai/card-sessions/{sid}/turns", token=other, body={"expectedTurn": 1})
    assert a[0] == b[0] == c[0] == 404 and a[2] == b[2] == c[2] == {"error": {"code": "NOT_FOUND", "message": "찾을 수 없어요."}}


@only("happy")
def test_eleventh_session_is_429():
    _, token = user()
    for i in range(LIMIT):
        assert create(token)[0] == 200, i
    status, _, body = create(token)
    assert status == 429 and body == {"error": {"code": "AI_QUOTA_EXCEEDED", "message": "오늘 AI 정리 횟수를 모두 썼어요. 직접 정리해 주세요."}}


@only("happy")
def test_expired_session_404_and_no_metrics():
    _, token = user()
    status, _, view = create(token)
    sid = view["sessionId"]
    past = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    boto("dynamodb").update_item(TableName=TABLE, Key={"PK": {"S": f"AISESSION#{sid}"}, "SK": {"S": "META"}},
                                 UpdateExpression="SET #t = :t", ExpressionAttributeNames={"#t": "ttl"}, ExpressionAttributeValues={":t": {"N": str(past)}})
    assert call("GET", f"/ai/card-sessions/{sid}", token=token)[0] == 404
    status, _, created = call("POST", "/plans", token=token, body=plan_body(view["card"], sid), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201
    assert "agentMode" not in ddb_item(f"PLAN#{created['plan']['planId']}")["metrics"]["M"]


def test_validation_400_without_quota():
    uid, token = user()
    status, _, body = create(token, story="")
    assert status == 400 and body["error"]["code"] == "VALIDATION_ERROR" and "story" in body["error"]["details"]
    assert boto("dynamodb").query(TableName=TABLE, KeyConditionExpression="PK = :p",
                                  ExpressionAttributeValues={":p": {"S": f"AIQUOTA#{uid}#{datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d')}"}})["Count"] == 0


@only("http_401")
def test_provider_401_is_503():
    _, token = user()
    status, _, body = create(token)
    assert status == 503 and body["error"]["code"] == "AI_UNAVAILABLE"


@only("http_429")
def test_provider_429_is_503():
    _, token = user()
    status, _, body = create(token)
    assert status == 503 and body["error"]["code"] == "AI_UNAVAILABLE"


@only("bad_json")
def test_bad_json_is_502():
    _, token = user()
    status, _, body = create(token)
    assert status == 502 and body["error"]["code"] == "AI_INVALID_OUTPUT"


@only("privacy_high")
def test_privacy_high_is_degraded_and_masked():
    _, token = user()
    status, _, view = create(token)
    assert status == 200 and view["degraded"] is True
    assert "010-1234-5678" not in view["card"]["summary"] and {"path": "summary", "type": "PRIVACY"} in view["flags"]
