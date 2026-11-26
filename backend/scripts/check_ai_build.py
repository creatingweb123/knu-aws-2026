"""`sam build --use-container` 산출물 검사 (6a 작업 13, design §17.3, Requirement 16.3·16.6·16.8, BE-Q18).

사용: backend/에서 `sam build --use-container` 뒤 `python scripts/check_ai_build.py [--runs 5]`.
결과 JSON을 표준 출력에 쓴다. 실패 항목이 있으면 종료 코드 1.

1. AiCardFunction 밖의 함수 산출물에 AI 패키지가 없다.
2. AiCardFunction 압축 해제·zip 크기, 상위 10개 패키지, 250MB 한도.
3. Lambda 런타임 컨테이너(public.ecr.aws/lambda/python:3.12)에서 handlers.ai_card import 시간(N회, 매번 새 프로세스),
   Fake 모델로 그래프 1회(DB 없음), zoneinfo Asia/Seoul, 최대 RSS.
4. 함수마다 그 산출물 디렉터리 하나만 /var/task로 붙여 독립 import·실행: 인증 없는 API 이벤트 → 401,
   sys.modules에 AI 패키지 없음(AiCardFunction 제외), PlansFunction은 ai_metrics 계산, PreSignUp은 표본 이벤트.
5. (--local-ddb-network 지정 시) PlansFunction 산출물을 AI 패키지 import를 막은 채 로컬 Floci DynamoDB에 붙여
   인증된 MANUAL·AI_EDITED POST /plans와 AiSession 지표 계산을 실행하고, 루트 DEBUG 로그에 세션 본문이 없는지 본다.
외부 네트워크·AWS 자격 증명을 쓰지 않는다(컨테이너는 --network none, 5번만 로컬 compose 네트워크).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import subprocess
import sys
import tempfile
import zipfile

BACKEND = pathlib.Path(__file__).resolve().parents[1]
BUILD = BACKEND / ".aws-sam" / "build"
IMAGE = "public.ecr.aws/lambda/python:3.12"
AI_FUNCTION = "AiCardFunction"
FORBIDDEN = ("langgraph", "langchain", "langsmith", "openai", "tiktoken", "httpx", "httpcore", "ormsgpack", "xxhash", "zstandard", "jiter", "orjson")
MODULE_PREFIXES = ("langgraph", "langchain", "langchain_core", "langchain_openai", "openai", "langsmith")
LIMIT_MB = 250
HANDLERS = {
    "MeFunction": ("handlers.me", "GET /me"),
    "PlansFunction": ("handlers.plans", "GET /plans"),
    "ClaimsFunction": ("handlers.claims", "POST /claims/{claimId}/abandon"),
    "AiCardFunction": ("handlers.ai_card", "POST /ai/card-sessions"),
    "PreSignUpFunction": ("handlers.pre_signup", None),
}
ENV = {
    "TABLE_NAME": "HaruTable", "AWS_DEFAULT_REGION": "ap-northeast-2", "AWS_EC2_METADATA_DISABLED": "true",
    "LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local", "PYTHONPATH": "/var/task",
    "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false", "PYTHONDONTWRITEBYTECODE": "1",
}


def dir_size(path: pathlib.Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def zip_size(path: pathlib.Path) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "fn.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(path.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(path))
        return out.stat().st_size


def top_packages(path: pathlib.Path, n: int = 10) -> list[dict[str, float]]:
    sizes = [(p.name, dir_size(p)) for p in path.iterdir() if p.is_dir() and not p.name.endswith((".dist-info", ".egg-info"))]
    return [{"name": k, "mb": round(v / 1e6, 1)} for k, v in sorted(sizes, key=lambda x: -x[1])[:n]]


def forbidden_in(path: pathlib.Path) -> list[str]:
    return sorted(p.name for p in path.iterdir() if p.name.lower().split("-")[0].split(".")[0] in FORBIDDEN
                  or p.name.lower().startswith(FORBIDDEN))


def run_in_runtime(fn_dir: pathlib.Path, code: str, timeout: int = 120, network: str = "none", extra_env: dict | None = None) -> dict:
    cmd = ["docker", "run", "--rm", "--network", network, "--entrypoint", "/var/lang/bin/python3",
           "-v", f"{fn_dir}:/var/task:ro", "-w", "/var/task"]
    for k, v in {**ENV, **(extra_env or {})}.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += [IMAGE, "-c", code]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        return {"ok": False, "error": out.stderr.strip().splitlines()[-1:] or ["(no stderr)"]}
    return {"ok": True, **json.loads(out.stdout.strip().splitlines()[-1])}


IMPORT_CODE = r"""
import json, time
t = time.perf_counter()
import handlers.ai_card
print(json.dumps({"import_s": round(time.perf_counter() - t, 3)}))
"""

GRAPH_CODE = r"""
import asyncio, json, resource, time
from zoneinfo import ZoneInfo
t = time.perf_counter()
import handlers.ai_card
from agent import graph as g, llm
from agent.timebudget import TimeBudget
import_s = time.perf_counter() - t
class Ctx:
    def get_remaining_time_in_millis(self):
        return 25000
caller = llm.LlmCaller(llm.load_settings())
t = time.perf_counter()
state = asyncio.run(g.build_pipeline_graph().ainvoke(g.initial_state("출근길 빵집에 들러 빵을 사고 하천 벤치에 앉아 쉬고 싶었어요."),
                    config={"configurable": {"llm": caller, "deadline": TimeBudget(Ctx(), None)}}))
print(json.dumps({"import_s": round(import_s, 3), "graph_s": round(time.perf_counter() - t, 3), "outcome": list(g.decide_outcome(state)),
                  "zoneinfo": str(ZoneInfo("Asia/Seoul")), "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}))
"""

INDEPENDENT_CODE = r"""
import importlib, json, sys
module, route, fn = %r, %r, %r
m = importlib.import_module(module)
result = {}
if route:
    resp = m.handler({"version": "2.0", "routeKey": route, "headers": {}, "requestContext": {}, "body": None,
                      "pathParameters": {"claimId": "c1"}}, None)
    result["status"] = resp["statusCode"]
    result["body"] = json.loads(resp["body"])["error"]["code"] if resp.get("body") else None
else:
    ev = {"triggerSource": "PreSignUp_SignUp", "request": {"userAttributes": {"email": "a@example.com", "nickname": "지연"}}, "response": {}}
    out = m.handler(ev, None)
    result["presignup"] = [out["response"].get("autoConfirmUser"), out["response"].get("autoVerifyEmail")]
if fn == "PlansFunction":
    from domain import ai_metrics
    s = {"status": "READY", "agentMode": "PIPELINE", "answers": [], "modelCalls": 1, "privacyDetected": 0, "flags": [], "notes": [],
         "card": {"title": "t", "summary": "s", "reason": "r", "estimatedMinutes": 45, "question": "q",
                  "places": [{"name": "빵집", "activity": "빵 사기", "whyChosen": None}]},
         "firstReport": {"notInSource": [], "missing": [], "privacy": []},
         "createdAt": "2026-11-26T00:00:00.000Z", "readyAt": "2026-11-26T00:00:03.000Z"}
    f = {"title": "t", "summary": "s", "reason": "r", "estimatedMinutes": 45, "question": "q",
         "places": [{"name": "빵집", "activity": "빵 사기", "whyChosen": ""}]}
    result["ai_metrics_agentWaitMs"] = ai_metrics.session_metrics(s, f, "빵집에서 빵 사기", "2026-11-26T00:01:00.000Z")["agentWaitMs"]
result["ai_modules"] = sorted({n.split(".")[0] for n in sys.modules if n.split(".")[0] in %r})
print(json.dumps(result, ensure_ascii=False))
"""


PLANS_DB_CODE = r"""
import importlib.abc, io, json, logging, sys, uuid
BLOCKED = %r

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError("blocked: " + name)
        return None

sys.meta_path.insert(0, Block())
buf = io.StringIO()
logging.basicConfig(level=logging.DEBUG, stream=buf, force=True)  # 최악의 설정: 루트 DEBUG, SDK 로거 NOTSET
from datetime import datetime, timedelta, timezone
import handlers.plans as plans
from common import ddb
from domain import ai_session_service as svc

STORY = "검사용 합성 사연: 출근길 빵집에 들러 빵을 사고 하천 벤치에 앉아 쉬고 싶었어요. 연락 010-7777-8888"
CARD_SECRET = "검사용 카드 이유 문장"
ANSWER = "검사용 답변 문장"
sub = "chk-" + uuid.uuid4().hex[:10]
claims = {"token_use": "id", "sub": sub, "nickname": "지연"}
card = {"title": "이사 전 산책", "summary": "빵집과 벤치", "reason": CARD_SECRET, "estimatedMinutes": 45, "question": "무엇이 보였나요?",
        "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": None}]}
created = []

def post(body):
    key = str(uuid.uuid4())
    created.append(f"IDEM#{claims['sub']}#{key}")
    ev = {"version": "2.0", "routeKey": "POST /plans", "headers": {"idempotency-key": key}, "body": json.dumps(body, ensure_ascii=False),
          "isBase64Encoded": False, "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}
    r = plans.handler(ev, None)
    out = json.loads(r["body"])
    if r["statusCode"] == 201:
        created.append("PLAN#" + out["plan"]["planId"])
    return r["statusCode"], out

def body(mode, sid=None):
    b = {k: card[k] for k in ("title", "summary", "reason", "estimatedMinutes", "question")}
    b["reason"] = "공개용 이유"
    b["places"] = [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}]
    b["authoring"] = {"mode": mode, "durationMs": 1000, "story": STORY, **({"aiSessionId": sid} if sid else {})}
    return b

result = {}
try:
    s1, m = post(body("MANUAL"))
    result["manual"] = [s1, sorted(m["plan"]["metrics"])]
    now = datetime.now(timezone.utc)
    from common.ids import new_session_id
    sid = new_session_id()
    item = svc.build_session_item(session_id=sid, owner_id=sub, story=STORY, status="READY", created_at=now - timedelta(seconds=30),
                                  ready_at=now - timedelta(seconds=25), card=card, model_calls=1, privacy_detected=1,
                                  first_report={"notInSource": [], "missing": [], "privacy": []}, first_proposal=card)
    item["answers"] = [{"questionId": "q1", "text": ANSWER}]
    svc.put_session(item)
    created.append("AISESSION#" + sid)
    buf.truncate(0); buf.seek(0)  # 세션을 넣는 로그는 검사 대상이 아니다
    s2, a = post(body("AI_EDITED", sid))
    metrics = a["plan"]["metrics"]
    result["ai_edited"] = [s2, metrics.get("agentMode"), metrics.get("modelCalls"), metrics.get("fieldsEditedAfterHandoff")]
    claims["sub"] = sub + "-x"  # 다른 사용자가 남의 세션 ID를 보냄 → AI 지표 없음
    s3, o = post(body("AI_EDITED", sid))
    claims["sub"] = sub
    result["other_owner"] = [s3, "agentMode" in o["plan"]["metrics"]]
    log = buf.getvalue()
    result["log_leaks"] = [x for x in (STORY, "010-7777-8888", CARD_SECRET, ANSWER) if x in log]
    result["sdk_debug_seen"] = "botocore" in log
    result["ai_modules"] = sorted({n.split(".")[0] for n in sys.modules if n.split(".")[0] in BLOCKED})
finally:
    t = ddb.table()
    for pk in created:
        t.delete_item(Key={"PK": pk, "SK": "META"})
print(json.dumps(result, ensure_ascii=False))
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--local-ddb-network", default="", help="로컬 compose 네트워크 이름(예: haru_default). 주면 5번 검사를 한다")
    args = ap.parse_args()
    if not BUILD.is_dir():
        print(json.dumps({"ok": False, "error": "먼저 sam build --use-container를 실행하세요"}))
        return 1
    report: dict = {"functions": {}, "failures": []}
    fn_dirs = {p.name: p for p in BUILD.iterdir() if p.is_dir()}
    for name, path in sorted(fn_dirs.items()):
        info: dict = {"unzipped_mb": round(dir_size(path) / 1e6, 1)}
        if name != AI_FUNCTION:
            info["forbidden_packages"] = forbidden_in(path)
            if info["forbidden_packages"]:
                report["failures"].append(f"{name}: AI 패키지 {info['forbidden_packages']}")
        report["functions"][name] = info

    ai_dir = fn_dirs.get(AI_FUNCTION)
    if ai_dir is None:
        report["failures"].append("AiCardFunction 산출물 없음")
    else:
        ai = report["functions"][AI_FUNCTION]
        ai["zip_mb"] = round(zip_size(ai_dir) / 1e6, 1)
        ai["top_packages"] = top_packages(ai_dir)
        ai["under_250mb"] = dir_size(ai_dir) < LIMIT_MB * 1024 * 1024
        if not ai["under_250mb"]:
            report["failures"].append("AiCardFunction 압축 해제 크기 250MB 초과")
        times = []
        for _ in range(args.runs):
            r = run_in_runtime(ai_dir, IMPORT_CODE)
            if not r["ok"]:
                report["failures"].append(f"AiCardFunction import 실패: {r['error']}")
                break
            times.append(r["import_s"])
        if times:
            ai["import_s"] = {"runs": times, "median": statistics.median(times), "max": max(times)}
        g = run_in_runtime(ai_dir, GRAPH_CODE)
        ai["graph_run"] = g
        if not g["ok"] or g.get("outcome", [None])[0] != "READY" or g.get("zoneinfo") != "Asia/Seoul":
            report["failures"].append(f"AiCardFunction 그래프·zoneinfo 확인 실패: {g}")

    independent = {}
    for name, (module, route) in HANDLERS.items():
        path = fn_dirs.get(name)
        if path is None:
            report["failures"].append(f"{name} 산출물 없음")
            continue
        r = run_in_runtime(path, INDEPENDENT_CODE % (module, route, name, MODULE_PREFIXES))
        independent[name] = r
        if not r["ok"]:
            report["failures"].append(f"{name} 독립 실행 실패: {r['error']}")
            continue
        if route and (r.get("status"), r.get("body")) != (401, "UNAUTHORIZED"):
            report["failures"].append(f"{name}: 인증 없는 이벤트가 401이 아님 {r}")
        if not route and r.get("presignup") != [True, True]:
            report["failures"].append(f"{name}: PreSignUp 결과 {r}")
        if name != AI_FUNCTION and r.get("ai_modules"):
            report["failures"].append(f"{name}: AI 모듈 로드 {r['ai_modules']}")
        if name == AI_FUNCTION and "langgraph" not in r.get("ai_modules", []):
            report["failures"].append("AiCardFunction: langgraph가 로드되지 않음(검사 자체 확인)")
    report["independent"] = independent

    if args.local_ddb_network and fn_dirs.get("PlansFunction"):
        r = run_in_runtime(fn_dirs["PlansFunction"], PLANS_DB_CODE % (MODULE_PREFIXES,), network=args.local_ddb_network,
                           extra_env={"AWS_ENDPOINT_URL": "http://aws:4566", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"})
        report["plans_authenticated"] = r
        expected_manual = [201, ["addedNotInSource", "authoringMode", "durationMs", "privacyInPublished"]]
        if not r["ok"]:
            report["failures"].append(f"PlansFunction 인증 경로 실패: {r['error']}")
        else:
            if r["manual"] != expected_manual:
                report["failures"].append(f"PlansFunction MANUAL: {r['manual']}")
            if r["ai_edited"][:3] != [201, "PIPELINE", 1]:
                report["failures"].append(f"PlansFunction AI_EDITED: {r['ai_edited']}")
            if r["other_owner"] != [201, False]:
                report["failures"].append(f"PlansFunction 남의 세션: {r['other_owner']}")
            if r["log_leaks"] or not r["sdk_debug_seen"] or r["ai_modules"]:
                report["failures"].append(f"PlansFunction 로그·모듈: {r}")
    report["ok"] = not report["failures"]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    os.chdir(BACKEND)
    sys.exit(main())
