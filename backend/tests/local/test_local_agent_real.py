"""로컬 통합: 실제 공급자(NVIDIA NIM 개발용 trial)로 6b 에이전트 스모크 5건과 같은 턴 동시 5요청 (작업 20.2, 20.4).

범위와 한계:
- 로컬 어댑터(HTTP) → 실제 핸들러 → Floci DynamoDB(AiSession 잠금·예약, HaruAgentCheckpoints 체크포인터)를 쓴다.
  AWS DynamoDB가 아니다. AWS 판정은 작업 22에서 한다.
- 실제 모델 호출이 나간다. 사연은 tests/fixtures/stories.json의 합성 문장 5건(데모·비공개 장소·연락처·인젝션·빈칸)만 쓴다.
- 질문은 tests/fixtures/stories.py의 자동 답 규칙으로 답한다. 결과는 개발용 trial 근거이고 운영 공급자 결정 근거가 아니다.

실행 조건(모두 필요):
  어댑터를 AGENT_MODE=agent, LLM_PROVIDER=openai_compat, LLM_API_KEY(.env)로 띄운다.
  LOCAL_REAL_PROVIDER=1 LOCAL_AGENT_MODE=agent pytest -m local tests/local/test_local_agent_real.py -s
  llmMode 검사로 실제 공급자가 아니면(fake) 실패한다.

결과 파일: backend/test-results/local-real-agent-<시각>.json (gitignore). 사연 원문은 쓰지 않고 id와 카드 필드만 쓴다.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from boto3.dynamodb.types import TypeDeserializer

from tests.fixtures.stories import AUTO_ANSWER_RULE, auto_answer, story
from tests.integration.verdicts import t20_checks, t20_pass
from tests.local.conftest import API, boto, dev_token

pytestmark = [
    pytest.mark.local,
    pytest.mark.skipif(os.environ.get("LOCAL_REAL_PROVIDER") != "1" or os.environ.get("LOCAL_AGENT_MODE") != "agent",
                       reason="실제 공급자 스모크. LOCAL_REAL_PROVIDER=1 LOCAL_AGENT_MODE=agent이고 어댑터를 openai_compat·agent로 띄울 때만"),
]

BACKEND = pathlib.Path(__file__).resolve().parents[2]
SMOKE_IDS = ["demo", "private_place_1", "contact_1", "injection_1", "missing_1"]
PAUSE_S = float(os.environ.get("LOCAL_REAL_PAUSE_S", "2.0"))  # 공급자 분당 한도 보호(우회 아님)
DEADLINE_S = 27.0  # Lambda 타임아웃 흉내(어댑터 FakeContext)
DESER = TypeDeserializer()


def _plain(item: dict) -> dict:
    return {k: DESER.deserialize(v) for k, v in item.items()}


def session(sid: str) -> dict:
    got = boto("dynamodb").get_item(TableName="HaruTable", Key={"PK": {"S": f"AISESSION#{sid}"}, "SK": {"S": "META"}}, ConsistentRead=True)
    return _plain(got["Item"])


def ckpt_count(sid: str) -> int:
    items = boto("dynamodb").scan(TableName="HaruAgentCheckpoints")["Items"]
    return sum(1 for i in items if sid in i["PK"]["S"])


def req(method: str, path: str, token: str, body=None, timeout: float = 90.0):
    """(HTTP, 본문, 걸린 초). 90초 안에 응답이 없으면 예외로 드러낸다."""
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(API + path, data=data, method=method, headers={"Authorization": f"Bearer {token}"})
    if data is not None:
        r.add_header("Content-Type", "application/json")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    return status, (json.loads(raw) if raw else None), round(time.monotonic() - t0, 2)


def label(status: int, body) -> str | None:
    if status == 200 and isinstance(body, dict):
        return body.get("status")
    return ((body or {}).get("error") or {}).get("code")


def drive(token: str, sid_story: dict, log: list) -> tuple[int, dict]:
    """docs/03 프론트 규칙: WORKING 이어가기, 연속 2회 WORKING 뒤 finish, ASKING은 자동 답, BUSY·CLOSED는 GET."""
    status, view, secs = req("POST", "/ai/card-sessions", token, {"story": sid_story["story"]})
    log.append({"req": "create", "http": status, "label": label(status, view), "sec": secs})
    if status != 200:
        return status, view
    working, finish = int(view["status"] == "WORKING"), False
    for _ in range(10):
        if view["status"] not in ("ASKING", "WORKING"):
            break
        body: dict = {"expectedTurn": view["turn"]}
        if view["status"] == "ASKING":
            body["answer"] = auto_answer(view["question"], sid_story["answers"])
        if finish or working >= 2:
            finish = True
            body["finish"] = True
        time.sleep(PAUSE_S)
        status, nxt, secs = req("POST", f"/ai/card-sessions/{view['sessionId']}/turns", token, body)
        log.append({"req": "turns", "http": status, "label": label(status, nxt), "sec": secs, "expectedTurn": view["turn"]})
        if status == 409 and (nxt or {}).get("error", {}).get("code") in ("AI_SESSION_BUSY", "AI_SESSION_CLOSED"):
            time.sleep(2)
            status, nxt, secs = req("GET", f"/ai/card-sessions/{view['sessionId']}", token)
            log.append({"req": "get", "http": status, "label": label(status, nxt), "sec": secs})
        if status != 200:
            return status, nxt
        working = working + 1 if nxt["status"] == "WORKING" else 0
        view = nxt
    return 200, view


def summarize_card(view: dict) -> dict:
    card = view.get("card") or {}
    return {"status": view.get("status"), "degraded": view.get("degraded"), "turn": view.get("turn"),
            "places": [p.get("name") for p in card.get("places") or []],
            "estimatedMinutes": card.get("estimatedMinutes"),
            "flags": [f.get("type") for f in view.get("flags") or []],
            "notes": [n.get("action") for n in view.get("notes") or []]}


def save(name: str, data: dict) -> pathlib.Path:
    out = BACKEND / "test-results"
    out.mkdir(exist_ok=True)
    path = out / f"local-real-agent-{name}-{time.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")  # DynamoDB 숫자(Decimal)
    return path


@pytest.fixture(scope="module")
def real_token():
    uid = f"local-real-{uuid.uuid4().hex[:8]}"
    return uid, dev_token(uid, "지연")


def test_smoke_five_stories(real_token):
    _, token = real_token
    results, problems = {}, []
    for sid_ in SMOKE_IDS:
        fx = story(sid_)
        log: list = []
        status, view = drive(token, fx, log)
        entry: dict = {"requests": log, "http": status}
        if status == 200 and view.get("sessionId"):
            item = session(view["sessionId"])
            entry |= summarize_card(view) | {
                "llmMode": item.get("llmMode"), "llmProviderLabel": item.get("llmProviderLabel"),
                "modelCalls": int(item.get("modelCalls") or 0), "modelCallsReserved": int(item.get("modelCallsReserved") or 0),
                "questionsAsked": int(item.get("questionsAsked") or 0), "gateRejects": int(item.get("gateRejects") or 0),
                "checkDraftCount": int(item.get("checkDraftCount") or 0), "tokenIn": int(item.get("tokenIn") or 0),
                "tokenInEstimated": int(item.get("tokenInEstimated") or 0), "tokenOut": int(item.get("tokenOut") or 0),
                "answers": [{k: a.get(k) for k in ("questionId", "path", "choice", "text", "skipped", "resumeId")} for a in item.get("answers") or []],
                "trace": [t.get("tool") for t in item.get("trace") or []], "checkpointsLeft": ckpt_count(view["sessionId"]),
                "agentMode": item.get("agentMode"), "turnAttempts": int(item.get("turnAttempts") or 0)}
        else:
            entry["error"] = view
        results[sid_] = entry
        # 스모크 기준(문제 판정). 기준을 낮추지 않는다.
        if status != 200 or entry.get("status") != "READY":
            problems.append(f"{sid_}: HTTP {status} {entry.get('status')}")
        if entry.get("llmMode") != "openai_compat":
            problems.append(f"{sid_}: llmMode {entry.get('llmMode')}(실제 공급자가 아니다)")
        if entry.get("modelCallsReserved", 0) > 6:
            problems.append(f"{sid_}: 예약 {entry['modelCallsReserved']} > 6")
        if entry.get("checkpointsLeft", 0) != 0:
            problems.append(f"{sid_}: 종료 뒤 체크포인트 {entry['checkpointsLeft']}건 남음")
        if any(r["sec"] >= DEADLINE_S for r in log):
            problems.append(f"{sid_}: 요청 지연 27초 이상")
        if any(r["http"] not in (200, 409, 503) for r in log):
            problems.append(f"{sid_}: 예상 밖 HTTP {[r['http'] for r in log]}")
        if entry.get("answers") and len({a.get("questionId") for a in entry["answers"]}) != len(entry["answers"]):
            problems.append(f"{sid_}: 같은 질문 답이 중복 저장")
    path = save("smoke", {"scenario": "20.2 스모크 5건", "llmMode": "openai_compat", "autoAnswer": AUTO_ANSWER_RULE,
                          "pause_s": PAUSE_S, "results": results, "problems": problems})
    print(f"\n스모크 결과 파일: {path.relative_to(BACKEND)}")
    assert not problems, (str(path), problems)


def test_concurrent_same_turn_real(real_token):
    """같은 expectedTurn으로 5회 동시 요청(실제 모델 호출 포함). T20 기준을 로컬에서 같은 함수로 판정한다."""
    _, token = real_token
    fx = story("missing_1")
    status, view = req("POST", "/ai/card-sessions", token, {"story": fx["story"]})[:2]
    if status != 200 or view["status"] not in ("ASKING", "WORKING"):
        pytest.skip(f"생성 응답이 비종료가 아니다({status}, {(view or {}).get('status')}). 동시 요청 판정 대상 없음")
    sid = view["sessionId"]
    before = session(sid)
    body = {"expectedTurn": view["turn"]}
    if view["status"] == "ASKING":
        body["answer"] = auto_answer(view["question"], fx["answers"])
    time.sleep(PAUSE_S)
    with ThreadPoolExecutor(5) as ex:
        res = list(ex.map(lambda _: req("POST", f"/ai/card-sessions/{sid}/turns", token, body)[:2], range(5)))
    after = session(sid)
    checks = t20_checks(before, after, res)
    path = save("concurrent", {"scenario": "T20 로컬 실제 공급자", "llmMode": after.get("llmMode"), "checks": checks,
                               "passed": t20_pass(checks), "codes": [s for s, _ in res],
                               "before": {k: before.get(k) for k in ("turn", "modelCalls", "modelCallsReserved", "status")},
                               "after": {k: after.get(k) for k in ("turn", "modelCalls", "modelCallsReserved", "status")}})
    print(f"\n동시 요청 결과 파일: {path.relative_to(BACKEND)}")
    assert after.get("llmMode") == "openai_compat"
    assert t20_pass(checks), (str(path), checks)
