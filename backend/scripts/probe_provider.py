"""실제 OpenAI 호환 공급자 호환성 확인 (BE-Q6 개발용 공급자, BE-Q9·BE-Q12 실측).

사용(backend/에서):
    .venv/bin/python scripts/probe_provider.py --env-file .env [--stories 15] [--only raw,pipeline,tools,handler]

- 설정은 --env-file의 LLM_* 줄에서만 읽는다(os.environ을 바꾸지 않는다). API 키는 출력·저장하지 않는다.
- 사연은 tests/fixtures/stories.json의 합성 사연만 쓴다. 실제 사용자 사연을 넣지 않는다.
- 결과는 test-results/provider-probe-*.json(gitignore)에 남긴다. 모델 응답 원문·카드 문자열·공급자 오류 본문은
  남기지 않고 상태 코드·필드 존재·길이·토큰 수·지연·판정 결과만 남긴다.
- 6a 제한(connect 2초, read 8초, 재시도 0, 12초 규칙, Lambda 27초 흉내)을 완화하지 않는다.
- 호출 수를 작게 유지한다(기본 약 40회). 공급자 trial 한도를 넘지 않도록 호출 사이에 쉰다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import statistics
import sys
import time
from typing import Any

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

STORIES = json.loads((BACKEND / "tests" / "fixtures" / "stories.json").read_text(encoding="utf-8"))["stories"]
PAUSE_S = 1.6  # 호출 사이 쉼(trial 분당 한도 보호)
# 공급자별 추가 본문은 .env의 LLM_EXTRA_BODY만 따른다(범용). 특정 공급자의 기본값을 넣지 않는다.
# 예: NVIDIA NIM 추론 끄기 = {"chat_template_kwargs":{"enable_thinking":false}}, OpenAI 계열 = {"reasoning_effort":"none"}
REASONING_NONE = {"reasoning_effort": "none"}


def configured_extra(env: dict[str, str]) -> dict[str, Any]:
    """운영 설정의 추가 본문(LLM_EXTRA_BODY). 없으면 빈 dict."""
    raw = env.get("LLM_EXTRA_BODY", "").strip()
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SystemExit("LLM_EXTRA_BODY는 JSON 객체여야 한다")
    return value


def read_env(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.startswith("LLM_"):
            env[k.strip()] = v.strip().strip('"').strip("'")
    if not env.get("LLM_API_KEY"):
        raise SystemExit("LLM_API_KEY가 비어 있다. .env에 직접 넣는다(출력하지 않는다).")
    return env


# ---------------------------------------------------------------- raw HTTP (요청 필드 수용 확인)


def summarize_response(status: int, data: Any, latency: float) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status, "latency_s": round(latency, 3)}
    if status != 200 or not isinstance(data, dict):
        out["error_keys"] = sorted(data.keys()) if isinstance(data, dict) else None  # 본문 내용은 남기지 않는다
        return out
    ch = (data.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    out.update({
        "finish_reason": ch.get("finish_reason"),
        "content_len": len(content),
        "has_think_tag": "<think>" in content,
        "reasoning_len": len(reasoning),
        "tool_calls": len(msg.get("tool_calls") or []),
        "usage": {k: (data.get("usage") or {}).get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
        # 추론 토큰이 출력 토큰 안에 숨어 있는지(OpenAI 계열 completion_tokens_details). 없으면 null
        "reasoning_tokens": ((data.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "korean": any("\uac00" <= c <= "\ud7a3" for c in content),
    })
    return out


def raw_call(env: dict[str, str], body: dict[str, Any], timeout: float = 10.0) -> tuple[dict[str, Any], Any]:
    import httpx

    url = env["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {env['LLM_API_KEY']}", "Content-Type": "application/json"}
    t = time.monotonic()
    try:
        r = httpx.post(url, headers=headers, json={"model": env["LLM_MODEL"], **body},
                       timeout=httpx.Timeout(timeout - 2, connect=2.0))
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        return summarize_response(r.status_code, data, time.monotonic() - t), data
    except Exception as e:  # noqa: BLE001
        return {"status": None, "error": type(e).__name__, "latency_s": round(time.monotonic() - t, 3)}, None


TOOLS = [
    {"type": "function", "function": {"name": "check_draft", "description": "카드 초안을 검사한다",
                                       "parameters": {"type": "object", "properties": {"card": {"type": "object"}}, "required": ["card"]}}},
    {"type": "function", "function": {"name": "submit_card", "description": "정리가 끝난 카드를 제출한다",
                                       "parameters": {"type": "object", "properties": {"card": {"type": "object"}, "notes": {"type": "array", "items": {"type": "object"}}},
                                                      "required": ["card"]}}},
]


def probe_raw(env: dict[str, str]) -> dict[str, Any]:
    demo = STORIES[0]["story"]
    ko = [{"role": "user", "content": "다음 문장을 한국어 한 문장으로 요약해 줘: " + demo}]
    long_q = [{"role": "user", "content": "한국의 사계절을 각각 다섯 문장 이상으로 자세히 설명해 줘."}]
    res: dict[str, Any] = {}
    cfg = configured_extra(env)  # 운영 설정 그대로(LLM_EXTRA_BODY)
    cases = {
        "basic_default": {"messages": ko, "max_tokens": 200},
        "configured": {"messages": ko, "max_tokens": 200, **cfg},
        "reasoning_effort_none": {"messages": ko, "max_tokens": 200, **REASONING_NONE},
        "temperature_0": {"messages": ko, "max_tokens": 200, "temperature": 0, **cfg},
        "max_completion_tokens_16": {"messages": long_q, "max_completion_tokens": 16, "temperature": 0, **cfg},
        "max_tokens_16": {"messages": long_q, "max_tokens": 16, "temperature": 0, **cfg},
        "both_16": {"messages": long_q, "max_tokens": 16, "max_completion_tokens": 16, "temperature": 0, **cfg},
    }
    for name, body in cases.items():
        res[name], _ = raw_call(env, body)
        time.sleep(PAUSE_S)
    # 도구 호출 + parallel_tool_calls=false + 후속 ToolMessage
    sys_msg = {"role": "system", "content": "너는 하루 카드 정리 도우미다. 반드시 도구를 하나만 호출해 진행한다. 먼저 check_draft로 초안을 검사한다."}
    user = {"role": "user", "content": "<story>\n" + demo + "\n</story>\n카드 초안을 만들어 check_draft를 호출해."}
    for label, extra in (("tools_parallel_false", {"parallel_tool_calls": False}), ("tools_no_parallel_param", {})):
        summ, data = raw_call(env, {"messages": [sys_msg, user], "tools": TOOLS, "max_tokens": 800, "temperature": 0, **cfg, **extra})
        res[label] = summ
        time.sleep(PAUSE_S)
        if label == "tools_parallel_false" and data and summ.get("tool_calls"):
            call = data["choices"][0]["message"]["tool_calls"][0]
            try:
                json.loads(call["function"]["arguments"])
                summ["args_json_ok"] = True
            except (ValueError, KeyError, TypeError):
                summ["args_json_ok"] = False
            summ["first_tool"] = call["function"].get("name")
            follow = [sys_msg, user, {"role": "assistant", "content": None, "tool_calls": [call]},
                      {"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"schemaErrors": [], "notInSource": [], "privacy": [], "missing": ["estimatedMinutes"]})}]
            res["tool_followup"], d2 = raw_call(env, {"messages": follow, "tools": TOOLS, "max_tokens": 800, "temperature": 0, "parallel_tool_calls": False, **cfg})
            if d2 and res["tool_followup"].get("tool_calls"):
                res["tool_followup"]["next_tool"] = d2["choices"][0]["message"]["tool_calls"][0]["function"].get("name")
            time.sleep(PAUSE_S)
    # reasoning_effort=none 을 도구 호출에서도 받는지(운영 설정과 별개로 한 번 더)
    summ, _ = raw_call(env, {"messages": [sys_msg, user], "tools": TOOLS, "max_tokens": 800, "temperature": 0, "parallel_tool_calls": False, **REASONING_NONE})
    res["tools_reasoning_none"] = summ
    return res


# ---------------------------------------------------------------- 6a 파이프라인 (실제 ChatOpenAI 경로)


class Ctx:
    def __init__(self) -> None:
        self.t0 = time.monotonic()

    def get_remaining_time_in_millis(self) -> float:
        return 27_000 - (time.monotonic() - self.t0) * 1000


def pipeline_env(env: dict[str, str]) -> dict[str, str]:
    e = dict(env)
    e["LLM_MAX_RETRIES"] = "0"  # 공급자 기본값을 넣지 않는다(LLM_EXTRA_BODY는 .env가 정한다)
    return e


def _legit_index(st: dict[str, Any], name: str | None) -> int | None:
    """장소 이름이 legitPlaces 목록의 몇 번째인지. 목록에 없으면 None(목록 밖 장소)."""
    if not name:
        return None
    for i, leg in enumerate(st.get("legitPlaces") or []):
        if leg in name or name in leg:
            return i
    return None


def probe_pipeline(env: dict[str, str], n: int, ids: list[str] | None = None, reps: int = 1) -> dict[str, Any]:
    from agent import graph as g
    from agent import llm
    from agent.timebudget import TimeBudget

    llm.quiet_library_loggers()
    e = pipeline_env(env)
    settings = llm.load_settings(e)
    if settings.error:
        return {"config_error": settings.error}
    rows = []
    chosen = [st for st in STORIES if st["id"] in ids] if ids else STORIES[:n]
    if ids and {st["id"] for st in chosen} != set(ids):
        return {"config_error": f"알 수 없는 사연 id: {sorted(set(ids) - {st['id'] for st in STORIES})}"}
    plan = [st for st in chosen for _ in range(reps)]
    for st in plan:
        caller = llm.LlmCaller(settings, env=e)
        t = time.monotonic()
        state = asyncio.run(g.pipeline_graph().ainvoke(g.initial_state(st["story"]),
                                                     config={"configurable": {"llm": caller, "deadline": TimeBudget(Ctx(), None)}}))
        status, http, failure = g.decide_outcome(state)
        flags = state.get("flags") or []
        rows.append({
            "id": st["id"], "category": st["category"], "status": status, "http": http, "failure": failure,
            "llm_error": state.get("llm_error"), "attempts": state.get("attempts"), "model_calls": state.get("model_calls"),
            "invalid_kinds": state.get("invalid_kinds"), "degraded": state.get("degraded"), "latency_s": round(time.monotonic() - t, 3),
            "token_in": state.get("token_in"), "token_out": state.get("token_out"), "token_estimated": state.get("token_estimated"),
            "flags": {k: sum(1 for f in flags if f["type"] == k) for k in ("NOT_IN_SOURCE", "MISSING", "PRIVACY")},
            "first_not_in_source": len(((state.get("first_report") or {}).get("notInSource")) or []),
            "places": len(((state.get("final_card") or {}).get("places")) or []),
            # BE-Q127: 장소는 사연 순서로 앞 3곳. 각 장소가 legitPlaces의 몇 번째인지(없으면 null). 이름은 남기지 않는다.
            "legit_order": [_legit_index(st, p.get("name")) for p in ((state.get("final_card") or {}).get("places") or [])],
        })
        time.sleep(PAUSE_S)
    lat = [r["latency_s"] for r in rows]
    return {
        "extra_body": configured_extra(e),
        "rows": rows,
        "summary": {
            "n": len(rows), "ready": sum(r["status"] == "READY" for r in rows), "degraded": sum(bool(r["degraded"]) for r in rows),
            "failed_503": sum(r["http"] == 503 for r in rows), "failed_502": sum(r["http"] == 502 for r in rows),
            "timeouts": sum(r["llm_error"] == "TIMEOUT" for r in rows), "retries": sum((r["attempts"] or 0) > 1 for r in rows),
            "latency_median_s": round(statistics.median(lat), 3) if lat else None, "latency_max_s": max(lat) if lat else None,
            "usage_reported": sum(r["token_estimated"] is False for r in rows),
        },
    }


# ---------------------------------------------------------------- ChatOpenAI bind_tools (6b 경로 미리보기)


def probe_tools_langchain(env: dict[str, str]) -> dict[str, Any]:
    import httpx
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel, SecretStr

    class check_draft(BaseModel):  # noqa: N801 - 도구 이름
        """카드 초안을 검사한다."""
        card: dict

    class submit_card(BaseModel):  # noqa: N801
        """정리가 끝난 카드를 제출한다."""
        card: dict
        notes: list[dict] = []

    async def run() -> dict[str, Any]:
        timeout = httpx.Timeout(8.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as http:
            model = ChatOpenAI(base_url=env["LLM_BASE_URL"], api_key=SecretStr(env["LLM_API_KEY"]), model=env["LLM_MODEL"], timeout=timeout,
                               max_retries=0, max_tokens=800, temperature=0, use_responses_api=False, http_async_client=http,
                               extra_body=configured_extra(env) or None)
            bound = model.bind_tools([check_draft, submit_card], parallel_tool_calls=False)  # tool_choice는 보내지 않는다
            msgs = [SystemMessage(content="반드시 도구를 하나만 호출한다. 먼저 check_draft로 초안을 검사한다."),
                    HumanMessage(content="<story>\n" + STORIES[0]["story"] + "\n</story>\n카드 초안을 만들어 check_draft를 호출해.")]
            t = time.monotonic()
            r1 = await asyncio.wait_for(bound.ainvoke(msgs), timeout=10)
            out: dict[str, Any] = {"first": {"latency_s": round(time.monotonic() - t, 3), "tool_calls": [c["name"] for c in r1.tool_calls],
                                             "invalid_tool_calls": len(r1.invalid_tool_calls), "usage": r1.usage_metadata and {k: r1.usage_metadata.get(k) for k in ("input_tokens", "output_tokens")}}}
            if r1.tool_calls:
                await asyncio.sleep(PAUSE_S)
                msgs += [r1, ToolMessage(content=json.dumps({"schemaErrors": [], "notInSource": [], "privacy": [], "missing": []}), tool_call_id=r1.tool_calls[0]["id"])]
                t = time.monotonic()
                r2 = await asyncio.wait_for(bound.ainvoke(msgs + [HumanMessage(content="검사를 통과했으면 submit_card를 호출해.")]), timeout=10)
                out["followup"] = {"latency_s": round(time.monotonic() - t, 3), "tool_calls": [c["name"] for c in r2.tool_calls],
                                   "invalid_tool_calls": len(r2.invalid_tool_calls), "content_len": len(str(r2.content or ""))}
            return out

    try:
        return asyncio.run(run())
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}


# ---------------------------------------------------------------- 6a 핸들러 끝까지 (moto + 실제 공급자)


def probe_handler(env: dict[str, str]) -> dict[str, Any]:
    from moto import mock_aws

    e = pipeline_env(env)
    keep = dict(os.environ)
    os.environ.update({"AWS_DEFAULT_REGION": "ap-northeast-2", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
                       "TABLE_NAME": "HaruTable", "STAGE": "local", **{k: v for k, v in e.items()}})
    os.environ.pop("AWS_ENDPOINT_URL", None)
    try:
        with mock_aws():
            import boto3

            from common import ddb
            from handlers import ai_card

            sys.path.insert(0, str(BACKEND))
            from tests.unit.moto_table import create_haru_table

            t = boto3.resource("dynamodb", region_name="ap-northeast-2").Table("HaruTable")
            create_haru_table(t.meta.client)
            ddb.use_table(t)
            ai_card._initialized = True
            ev = {"version": "2.0", "routeKey": "POST /ai/card-sessions", "headers": {}, "isBase64Encoded": False,
                  "body": json.dumps({"story": STORIES[0]["story"]}, ensure_ascii=False),
                  "requestContext": {"timeEpoch": int(time.time() * 1000), "authorizer": {"jwt": {"claims": {"token_use": "id", "sub": "probe-user", "nickname": "지연"}}}}}
            t0 = time.monotonic()
            resp = ai_card.handler(ev, Ctx())
            body = json.loads(resp["body"])
            items = [i for i in t.scan()["Items"] if i["PK"].startswith("AISESSION#")]
            it = items[0] if items else {}
            return {"status": resp["statusCode"], "latency_s": round(time.monotonic() - t0, 3), "view_status": body.get("status"),
                    "llmMode": it.get("llmMode"), "providerLabel": it.get("llmProviderLabel"), "modelCalls": int(it.get("modelCalls", 0)),
                    "tokenEstimated": it.get("tokenEstimated"), "trace_tools": [s["tool"] for s in body.get("trace", [])]}
    finally:
        os.environ.clear()
        os.environ.update(keep)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=str(BACKEND / ".env"))
    ap.add_argument("--stories", type=int, default=len(STORIES))
    ap.add_argument("--only", default="raw,pipeline,tools,handler")
    ap.add_argument("--ids", default="", help="쉼표로 구분한 사연 id(pipeline만). 예: many_places")
    ap.add_argument("--reps", type=int, default=1, help="ids 각각을 반복할 횟수(pipeline만)")
    args = ap.parse_args()
    env = read_env(args.env_file)
    report: dict[str, Any] = {"provider": env.get("LLM_PROVIDER_LABEL"), "base_url": env.get("LLM_BASE_URL"), "model": env.get("LLM_MODEL"),
                              "extra_body": configured_extra(env),
                              "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "limits": {"connect_s": 2, "read_s": 8, "retries": 0, "lambda_ms": 27000}}
    only = set(args.only.split(","))
    if "raw" in only:
        report["raw"] = probe_raw(env)
    if "pipeline" in only:
        ids = [x for x in args.ids.split(",") if x] or None
        report["pipeline"] = probe_pipeline(env, args.stories, ids=ids, reps=args.reps)
    if "tools" in only:
        report["tools_langchain"] = probe_tools_langchain(env)
    if "handler" in only:
        report["handler"] = probe_handler(env)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    assert env["LLM_API_KEY"] not in text  # 키가 결과에 들어가지 않는다
    out = BACKEND / "test-results"
    out.mkdir(exist_ok=True)
    path = out / f"provider-probe-{time.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"saved {path.relative_to(BACKEND)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
