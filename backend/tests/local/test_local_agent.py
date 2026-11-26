"""로컬 통합: 6b 에이전트 (작업 16, design §18.4). docker compose 환경 대상, `pytest -m local`.

어댑터를 `AGENT_MODE=agent FAKE_LLM_SCENARIO=ask_once`로 띄우고 pytest에 `LOCAL_AGENT_MODE=agent`를 줄 때만 돈다.
컨테이너를 다시 띄우는 사례(ai-slow, 강제 종료 복구, 모드 전환)는 `LOCAL_COMPOSE_CONTROL=1`일 때만 돈다. 이 사례는
`docker compose up -d --no-deps --force-recreate api`로 api 컨테이너만 바꾸고, 끝나면 처음 설정(agent, ask_once)으로 되돌린다.
Fake 모델(`llmMode: fake`)이라 공급자 품질 근거가 아니다. 판정 근거 아님(BE-Q15).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

import pytest

from tests.local.conftest import API, boto, call, dev_token

pytestmark = [pytest.mark.local,
              pytest.mark.skipif(os.environ.get("LOCAL_AGENT_MODE") != "agent",
                                 reason="어댑터를 AGENT_MODE=agent FAKE_LLM_SCENARIO=ask_once로 띄우고 LOCAL_AGENT_MODE=agent로 실행할 때만")]

BACKEND = pathlib.Path(__file__).resolve().parents[2]
STORY = "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
ANSWER = {"questionId": "q1", "choice": "45분"}
BASE_ENV = {"AGENT_MODE": "agent", "FAKE_LLM_SCENARIO": "ask_once", "AGENT_TEST_HOOKS": "false", "AGENT_CRASH_AT": "", "FAULT_INJECT": ""}
control = pytest.mark.skipif(os.environ.get("LOCAL_COMPOSE_CONTROL") != "1",
                             reason="api 컨테이너를 다시 띄우는 사례. LOCAL_COMPOSE_CONTROL=1일 때만")


def user():
    uid = f"local-agent-{uuid.uuid4().hex[:10]}"
    return uid, dev_token(uid, "지연")


def session_item(sid):
    got = boto("dynamodb").get_item(TableName="HaruTable", Key={"PK": {"S": f"AISESSION#{sid}"}, "SK": {"S": "META"}}, ConsistentRead=True)
    return got.get("Item")


def ckpt_count(sid):
    c = boto("dynamodb")
    items = c.scan(TableName="HaruAgentCheckpoints")["Items"]
    return sum(1 for i in items if sid in i["PK"]["S"])


def expire_lock(sid):
    boto("dynamodb").update_item(TableName="HaruTable", Key={"PK": {"S": f"AISESSION#{sid}"}, "SK": {"S": "META"}},
                                 UpdateExpression="SET lockedUntil = :p", ExpressionAttributeValues={":p": {"N": "1"}})


def long_call(method, path, token, body=None, timeout=45):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Authorization": f"Bearer {token}"})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def create(token):
    return long_call("POST", "/ai/card-sessions", token, {"story": STORY})


def turn(token, sid, body):
    return long_call("POST", f"/ai/card-sessions/{sid}/turns", token, body)


def plan_body(card, sid):
    places = [{"name": p["name"], "activity": p["activity"], "whyChosen": p["whyChosen"] or ""} for p in card["places"]]
    body = {k: card[k] for k in ("title", "summary", "reason", "estimatedMinutes", "question")} | {"places": places}
    body["authoring"] = {"mode": "AI_EDITED", "durationMs": 9000, "story": STORY, "aiSessionId": sid}
    return body


# ---------------------------------------------------------------- 기본 사례(컨테이너 그대로)


def test_ask_once_publish_metrics_and_checkpoint_cleanup():
    uid, token = user()
    status, v = create(token)
    assert status == 200 and v["status"] == "ASKING" and v["turn"] == 1 and v["question"]["questionId"] == "q1", v
    sid = v["sessionId"]
    assert ckpt_count(sid) > 0  # 질문 대기 중에는 체크포인트가 남는다
    status, v = turn(token, sid, {"expectedTurn": 1, "answer": ANSWER})
    assert status == 200 and v["status"] == "READY" and v["turn"] == 2 and v["card"]["estimatedMinutes"] == 45, v
    item = session_item(sid)
    assert item["agentMode"]["S"] == "AGENT" and item["llmMode"]["S"] == "fake" and "lockToken" not in item
    print("llmMode:", item["llmMode"]["S"], "modelCallsReserved:", item["modelCallsReserved"]["N"])
    assert ckpt_count(sid) == 0  # 종료 뒤 삭제(BE-Q103)
    status, _, body = call("POST", "/plans", token=token, body=plan_body(v["card"], sid), headers={"Idempotency-Key": str(uuid.uuid4())})
    m = body["plan"]["metrics"]
    assert status == 201 and m["agentMode"] == "AGENT" and m["questionsAsked"] == 1 and m["modelCalls"] == 4, m


def test_finish_skips_question():
    _, token = user()
    sid = create(token)[1]["sessionId"]
    status, v = turn(token, sid, {"expectedTurn": 1, "finish": True})
    assert status == 200 and v["status"] == "READY", v
    a = session_item(sid)["answers"]["L"][0]["M"]
    assert a["skipped"]["BOOL"] is True


def test_same_turn_five_concurrent_requests():
    _, token = user()
    sid = create(token)[1]["sessionId"]
    results = []

    def go():
        results.append(turn(token, sid, {"expectedTurn": 1, "answer": ANSWER}))

    threads = [threading.Thread(target=go) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    codes = sorted(s for s, _ in results)
    busy = [b for s, b in results if s == 409]
    assert all(c in (200, 409) for c in codes) and 200 in codes, results
    assert all(b["error"]["code"] == "AI_SESSION_BUSY" for b in busy)
    item = session_item(sid)
    assert item["turn"]["N"] == "2" and len(item["answers"]["L"]) == 1 and int(item["modelCallsReserved"]["N"]) <= 6
    print("동시 5요청:", codes)


def test_duplicate_answer_is_idempotent():
    _, token = user()
    sid = create(token)[1]["sessionId"]
    first = turn(token, sid, {"expectedTurn": 1, "answer": ANSWER})
    again = turn(token, sid, {"expectedTurn": 1, "answer": ANSWER})
    other = turn(token, sid, {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "1시간"}})
    assert first[0] == again[0] == other[0] == 200 and first[1] == again[1] == other[1]
    item = session_item(sid)
    assert len(item["answers"]["L"]) == 1 and item["answers"]["L"][0]["M"]["choice"]["S"] == "45분"


# ---------------------------------------------------------------- 컨테이너를 다시 띄우는 사례


def recreate(**env):
    e = {**os.environ, **BASE_ENV, **env}
    out = subprocess.run(["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", "api"], cwd=BACKEND, env=e,
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-500:]
    for _ in range(60):
        try:
            urllib.request.urlopen(API + "/me", timeout=2)
        except urllib.error.HTTPError:
            return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise AssertionError("api가 다시 뜨지 않았다")


@pytest.fixture
def restore():
    yield
    recreate()


@control
def test_ai_slow_working_then_continue(restore):
    recreate(FAULT_INJECT="ai-slow")
    _, token = user()
    t0 = time.monotonic()
    status, v = create(token)
    assert status == 200 and v["status"] == "WORKING" and v["turn"] == 1, v  # 9초 × 2회 뒤 12초 규칙으로 pause
    sid = v["sessionId"]
    status, v = turn(token, sid, {"expectedTurn": 1})
    assert status == 200 and v["status"] == "ASKING" and v["turn"] == 2, v
    status, v = turn(token, sid, {"expectedTurn": 2, "answer": ANSWER})
    assert status == 200 and v["status"] == "READY" and v["turn"] == 3, v
    print(f"ai-slow 3요청 {time.monotonic() - t0:.1f}초")


@control
@pytest.mark.parametrize(("point", "extra"), [("ckpt_writes:1", 0), ("model_response:1", 1), ("before_commit:1", 0)])
def test_forced_kill_recovery(restore, point, extra):
    """F2·F4·F6: 답변 턴 처리 중 어댑터 프로세스를 끝내고(os._exit) 컨테이너를 다시 띄운 뒤 다음 요청으로 복구한다."""
    uid, token = user()
    sid = create(token)[1]["sessionId"]
    base = int(session_item(sid)["modelCallsReserved"]["N"])
    recreate(AGENT_TEST_HOOKS="true", AGENT_CRASH_AT=point)
    token = dev_token(uid, "지연")  # dev 서명 키는 어댑터 프로세스마다 새로 만든다
    with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):  # 프로세스가 끝나 연결이 끊긴다
        turn(token, sid, {"expectedTurn": 1, "answer": ANSWER})
    assert session_item(sid)["turn"]["N"] == "1"
    recreate()
    token = dev_token(uid, "지연")
    expire_lock(sid)  # 30초 잠금 만료를 기다리는 대신
    status, v = turn(token, sid, {"expectedTurn": 1, "answer": ANSWER})
    assert status == 200 and v["status"] == "READY" and v["turn"] == 2, v
    item = session_item(sid)
    assert len(item["answers"]["L"]) == 1 and int(item["modelCallsReserved"]["N"]) == base + 1 + extra <= 6
    assert ckpt_count(sid) == 0


@control
def test_mode_switch_closes_agent_session(restore):
    uid, token = user()
    status, v = create(token)
    assert v["status"] == "ASKING"
    sid = v["sessionId"]
    reserved = session_item(sid)["modelCallsReserved"]["N"]
    recreate(AGENT_MODE="pipeline")
    token = dev_token(uid, "지연")
    status, v = turn(token, sid, {"expectedTurn": 1, "answer": ANSWER})
    assert status == 200 and v["status"] == "READY" and v["degraded"] is True and v["turn"] == 2, v
    item = session_item(sid)
    assert item["modelCallsReserved"]["N"] == reserved and ckpt_count(sid) == 0
