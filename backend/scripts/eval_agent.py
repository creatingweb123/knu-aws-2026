"""오프라인 평가: ① 최초 draft, ② 레벨 0 최종 카드, ③ 에이전트 (6b 작업 18·20.3, design §21, BE-Q112).

사용(backend/에서):
    .venv/bin/python scripts/eval_agent.py --env-file ../../knu-aws-2026/backend/.env --reps 3 --out test-results/eval-agent-<날짜>.json
    .venv/bin/python scripts/eval_agent.py --fake --reps 1 --stories demo,nis_1 --out /tmp/eval-fake.json   # 도구 확인만

- 사연은 tests/fixtures/stories.json의 합성 사연만 쓴다. 실제 사용자 사연을 넣지 않는다.
- ①과 ②는 같은 레벨 0 실행 1회의 출력이다(BE-Q112). 같은 `draft` 호출(재시도 포함)을 공유하므로 ①과 ②의 차이는
  후처리(규칙 노드·Gate·폴백·Final_Check)의 효과이고 모델 출력의 차이가 아니다. ①은 검사만 한 초안, ②는 최종 카드다.
- ③은 별도 호출이다(에이전트 프롬프트, 도구 루프, 자동 답). 체크포인터는 메모리(InMemorySaver)이고 예산은 NoopBudget이다.
  이 결과는 DynamoDB 예약·잠금을 거치지 않는다. 그 경로는 로컬 통합 스모크(tests/local/test_local_agent_real.py)가 본다.
- 6a·6b 제한과 예산(모델 호출 6회, 입력 토큰 3만, 12초 규칙, 턴 27초, 울타리 24초)을 완화하지 않는다.
- 429가 나면 10초 쉬고 계속한다. 같은 실행 흐름에서 429가 3회 연속이면 중단하고 그때까지의 결과를 남긴다(우회하지 않는다).
- 결과 파일은 실행 중에도 매 사연·반복마다 갱신한다(complete: false → 끝나면 true). 사연·카드 원문은 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import pathlib
import statistics
import sys
import time
from collections import Counter
from typing import Any

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(BACKEND))

TURN_MS = 27_000
FENCE_S = 24.0
MAX_TURNS = 8
RATE_LIMIT = "HTTP_429"
RATE_BACKOFF_S = 10.0
RATE_ABORT_STREAK = 3
METHODS = ("single", "pipeline", "agent")
LABEL = {"single": "① 최초 draft", "pipeline": "② 레벨 0 최종", "agent": "③ 에이전트"}
DELIVERED = ("READY", "DEGRADED", "DRAFT")
FAILED = ("FAILED", "UNFINISHED", "NO_DRAFT")
FAKE_NOTE = "llmMode=fake: Fake 결과는 품질 근거가 아니다. 도구가 도는지만 본다."
TRIAL_NOTE = "개발용 trial 결과이며 운영 공급자 결정 근거가 아니다(작업 23)."
SCALARS = ("title", "summary", "reason", "estimatedMinutes", "question")


class Ctx:
    """Lambda context 흉내: 턴마다 27초에서 실제 시간으로 줄어든다."""

    def __init__(self, ms: int = TURN_MS) -> None:
        self.deadline = time.monotonic() + ms / 1000

    def get_remaining_time_in_millis(self) -> int:
        return max(0, int((self.deadline - time.monotonic()) * 1000))


def read_env(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip().startswith("LLM_"):
            env[k.strip()] = v.strip().strip('"').strip("'")
    if env.get("LLM_PROVIDER", "openai_compat") != "fake" and not env.get("LLM_API_KEY"):
        raise SystemExit("LLM_API_KEY가 비어 있다. .env에 직접 넣는다(출력하지 않는다).")
    env.setdefault("LLM_PROVIDER", "openai_compat")
    env["LLM_MAX_RETRIES"] = "0"
    return env


def fake_env(pipeline_scenario: str, agent_scenario: str) -> tuple[dict[str, str], dict[str, str]]:
    base = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local"}
    return {**base, "FAKE_LLM_SCENARIO": pipeline_scenario}, {**base, "FAKE_LLM_SCENARIO": agent_scenario}


# ---------------------------------------------------------------- 공통 검사(세 방식에 같은 잣대)


def residuals(card: dict[str, Any] | None, sources: list[str], legit: list[str]) -> dict[str, int]:
    """카드에 남은 NOT_IN_SOURCE·MISSING·PRIVACY 수와, legitPlaces 밖 장소 수(NEW_PLACE)."""
    from domain.ai_metrics import place_targets
    from domain.fidelity import find_not_in_source
    from domain.privacy import scan_privacy

    if not isinstance(card, dict):
        return {"NOT_IN_SOURCE": 0, "MISSING": 0, "PRIVACY": 0, "NEW_PLACE": 0, "places": 0}
    places = [p for p in card.get("places") or [] if isinstance(p, dict)]
    text = {k: card.get(k) for k in ("title", "summary", "reason", "question") if isinstance(card.get(k), str)}
    text |= {f"places[{i}].{f}": p.get(f) for i, p in enumerate(places) for f in ("name", "activity", "whyChosen")
             if isinstance(p.get(f), str)}
    missing = sum(1 for k in SCALARS if card.get(k) in (None, "")) + (0 if places else 1)
    names = [{"name": p.get("name"), "activity": None} for p in places]
    if legit:
        new_place = sum(1 for h in find_not_in_source([" ".join(legit)], place_targets(names)) if h.path.endswith(".name"))
    else:
        new_place = len(places)
    return {"NOT_IN_SOURCE": len(find_not_in_source(sources, place_targets(places))), "MISSING": missing,
            "PRIVACY": len(scan_privacy(text)), "NEW_PLACE": new_place, "places": len(places)}


def flags_count(flags: list[dict[str, Any]] | None) -> dict[str, int]:
    out = {"NOT_IN_SOURCE": 0, "MISSING": 0, "PRIVACY": 0}
    for f in flags or []:
        if f.get("type") in out:
            out[f["type"]] += 1
    return out


def self_repairs(notes: list[dict[str, Any]] | None) -> int:
    return sum(1 for n in notes or [] if isinstance(n, dict) and n.get("action") in ("REWRITTEN", "REMOVED"))


def _row(outcome: str, res: dict[str, int], **kw: Any) -> dict[str, Any]:
    base = {"outcome": outcome, "http": None, "failure": None, "degraded": False, "calls": 0, "tokens_in": 0, "tokens_out": 0,
            "token_estimated": False, "latency_ms": 0, "turn_ms_max": 0, "turns": 0, "questions": 0, "skipped": 0, "gate_rejects": 0,
            "self_repairs": 0, "llm_error": None, "flags": flags_count([]), "tools": []}
    return {**base, **kw, **res}


# ---------------------------------------------------------------- ① ② 레벨 0 실행 1회 (draft 공유)


def run_pipeline(env: dict[str, str], fx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from agent import graph as g
    from agent import llm
    from agent.timebudget import TimeBudget

    caller = llm.LlmCaller(llm.load_settings(env), env=env)
    t0 = time.monotonic()
    state = asyncio.run(g.build_pipeline_graph().ainvoke(
        g.initial_state(fx["story"]), config={"configurable": {"llm": caller, "deadline": TimeBudget(Ctx(), None)}}))
    ms = int((time.monotonic() - t0) * 1000)
    status, http, failure = g.decide_outcome(state)
    calls = int(state.get("model_calls") or 0)
    sources = [fx["story"]]
    first = state.get("first_proposal")
    draft = _row("DRAFT" if isinstance(first, dict) else "NO_DRAFT", residuals(first, sources, fx["legitPlaces"]),
                 calls=calls, tokens_in=int(state.get("token_in") or 0), tokens_out=int(state.get("token_out") or 0),
                 token_estimated=bool(state.get("token_estimated")), latency_ms=ms, llm_error=state.get("llm_error"),
                 flags=flags_count([]))
    if status != "READY":
        outcome = "FAILED"
    else:
        outcome = "DEGRADED" if state.get("degraded") else "READY"
    pipe = _row(outcome, residuals(state.get("final_card"), sources, fx["legitPlaces"]), http=http, failure=failure,
                degraded=bool(state.get("degraded")), calls=calls, tokens_in=int(state.get("token_in") or 0),
                tokens_out=int(state.get("token_out") or 0), token_estimated=bool(state.get("token_estimated")), latency_ms=ms,
                gate_rejects=0 if state.get("gate_ok", True) else 1,  # 레벨 0 게이트는 한 번만 본다. 거부되면 폴백
                self_repairs=self_repairs(state.get("notes")), llm_error=state.get("llm_error"),
                flags=flags_count(state.get("flags")))
    return draft, pipe


# ---------------------------------------------------------------- ③ 에이전트(메모리 체크포인터, 자동 답)


def run_agent(env: dict[str, str], fx: dict[str, Any], pause_s: float) -> dict[str, Any]:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agent import agent_tools as at
    from agent import llm
    from agent.agent_nodes import initial_agent_state
    from agent.budget import NoopBudget
    from agent.graph import build_agent_graph
    from agent.timebudget import AgentDeadline, TimeBudget
    from tests.fixtures.stories import auto_answer

    app = build_agent_graph(InMemorySaver())
    caller = llm.LlmCaller(llm.load_settings(env), env=env, budget=NoopBudget(), agent=True)
    tid = f"eval-{fx['id']}-{time.monotonic_ns()}"
    turns, working, finish, turn_ms = 0, 0, False, []
    inp: Any = initial_agent_state(fx["story"])
    result: dict[str, Any] = {}
    questions = skipped = 0
    while turns < MAX_TURNS:
        turns += 1
        conf = {"thread_id": tid, "llm": caller, "run_turn": turns, "finish_requested": finish,
                "deadline": AgentDeadline(TimeBudget(Ctx(), None), time.monotonic() + FENCE_S)}
        t0 = time.monotonic()
        result = asyncio.run(app.ainvoke(inp, {"configurable": conf}))
        turn_ms.append(int((time.monotonic() - t0) * 1000))
        if "__interrupt__" not in result:
            break
        it = result["__interrupt__"][0]
        payload = it.value
        if payload.get("kind") == "question":
            working = 0
            questions += 1
            ans = {"skipped": True, "viaFinish": True} if finish else auto_answer(payload, fx["answers"])
            skipped += int(bool(ans.get("skipped")))
            ans = {k: v for k, v in ans.items() if k != "questionId"}
            inp = Command(resume={it.id: {"questionId": payload["questionId"], "resumeId": f"r{turns}-{payload['questionId']}", **ans}})
        else:
            working += 1
            finish = finish or working >= 2  # docs/03: 연속 2회 WORKING 뒤 finish
            inp = Command(resume={it.id: "continue"})
        time.sleep(pause_s)
    b = result.get("budget") or {}
    answers = [a for a in result.get("answers") or [] if isinstance(a, dict)]
    sources = at.sources_for(fx["story"], answers)
    final = result.get("final_card")
    if "__interrupt__" in result:
        outcome = "UNFINISHED"
    elif result.get("outcome") == "READY" and final is not None:
        outcome = "DEGRADED" if result.get("degraded") else "READY"
    else:
        outcome = "FAILED"
    return _row(outcome, residuals(final if outcome in ("READY", "DEGRADED") else None, sources, fx["legitPlaces"]),
                degraded=bool(result.get("degraded")), calls=int(b.get("modelCalls") or 0),
                tokens_in=int(b.get("tokenReported") or 0) + int(b.get("tokenEstimated") or 0),
                tokens_out=int(b.get("tokenOut") or 0), token_estimated=int(b.get("tokenEstimated") or 0) > 0,
                latency_ms=sum(turn_ms), turn_ms_max=max(turn_ms), turns=turns, questions=questions, skipped=skipped,
                gate_rejects=int(b.get("gateRejects") or 0), self_repairs=self_repairs(result.get("notes")),
                llm_error=result.get("llm_error"), flags=flags_count(result.get("flags")),
                tools=[t.get("tool") for t in result.get("trace") or []])


# ---------------------------------------------------------------- 집계(순수 함수, 단위 테스트 대상)


def nearest_rank(xs: list[float], p: float) -> float | None:
    """백분위 nearest-rank: ceil(p·n)번째 값. 표본이 작을 때 보간하지 않는다."""
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, math.ceil(p * len(s)) - 1)]


def _med(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def verdict(agent: tuple[int, int, int], pipe: tuple[int, int, int]) -> str:
    """사연별 비교 벡터 (실패 수, 잔존 품질 문제 합(NOT_IN_SOURCE+PRIVACY+NEW_PLACE), MISSING 합). 작을수록 낫다.

    개선: 모든 항목이 ② 이하이고 하나 이상 작다. 악화: 모든 항목이 ② 이상이고 하나 이상 크다. 동일: 같다. 그 밖은 혼합.
    """
    if agent == pipe:
        return "동일"
    le = all(a <= p for a, p in zip(agent, pipe))
    ge = all(a >= p for a, p in zip(agent, pipe))
    if le:
        return "개선"
    if ge:
        return "악화"
    return "혼합"


def _vec(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    failed = sum(r["outcome"] in FAILED for r in rows)
    dl = [r for r in rows if r["outcome"] in DELIVERED]
    issues = sum(r["NOT_IN_SOURCE"] + r["PRIVACY"] + r["NEW_PLACE"] for r in dl)
    missing = sum(r["MISSING"] for r in dl)
    return failed, issues, missing


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in METHODS:
        rs = [r[m] for r in rows]
        n = len(rs)
        dl = [r for r in rs if r["outcome"] in DELIVERED]
        pct = lambda k: round(100 * sum(r["outcome"] == k for r in rs) / n, 1) if n else None  # noqa: E731
        lat = [r["latency_ms"] for r in rs]
        calls = [r["calls"] for r in rs]
        err = Counter(r["llm_error"] for r in rs if r["llm_error"])
        out[m] = {
            "runs": n,
            "READY_pct": pct("READY"), "DEGRADED_pct": pct("DEGRADED"), "FAILED_pct": round(100 * sum(r["outcome"] in FAILED for r in rs) / n, 1) if n else None,
            "DRAFT_pct": pct("DRAFT"),
            "delivered": len(dl),
            **{f"{k}_total": sum(r[k] for r in dl) for k in ("NOT_IN_SOURCE", "MISSING", "PRIVACY", "NEW_PLACE")},
            "calls_median": _med(calls), "calls_max": max(calls) if calls else None, "calls_total": sum(calls),
            "tokens_in_median": _med([r["tokens_in"] for r in rs]), "tokens_in_total": sum(r["tokens_in"] for r in rs),
            "tokens_out_median": _med([r["tokens_out"] for r in rs]), "tokens_out_total": sum(r["tokens_out"] for r in rs),
            "tokens_estimated_runs": sum(r["token_estimated"] for r in rs),
            "questions_total": sum(r["questions"] for r in rs), "skipped_total": sum(r["skipped"] for r in rs),
            "gate_rejects_total": sum(r["gate_rejects"] for r in rs), "self_repairs_total": sum(r["self_repairs"] for r in rs),
            "latency_ms_median": _med(lat), "latency_ms_p95": nearest_rank(lat, 0.95), "latency_ms_max": max(lat) if lat else None,
            "turn_ms_max": max((r["turn_ms_max"] for r in rs), default=None),
            "llm_errors": dict(err), "timeouts": err.get("TIMEOUT", 0),
            "provider_errors": sum(v for k, v in err.items() if k and (k.startswith("HTTP_") or k in ("CONNECTION", "KEY_READ_FAILED", "CONFIG", "PROVIDER_RESPONSE"))),
            "rate_limited": err.get("HTTP_429", 0),
            "budget_stops": sum(v for k, v in err.items() if k and k.startswith("BUDGET_")),
        }
    return out


def per_story(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for sid in dict.fromkeys(r["id"] for r in rows):
        rs = [r for r in rows if r["id"] == sid]
        item: dict[str, Any] = {"id": sid, "category": rs[0]["category"], "reps": len(rs)}
        for m in METHODS:
            ms = [r[m] for r in rs]
            dl = [x for x in ms if x["outcome"] in DELIVERED]
            item[m] = {
                "outcomes": [x["outcome"] for x in ms],
                **{k: _med([x[k] for x in dl]) for k in ("NOT_IN_SOURCE", "MISSING", "PRIVACY", "NEW_PLACE")},
                "calls_median": _med([x["calls"] for x in ms]),
                "questions_median": _med([x["questions"] for x in ms]),
                "gate_rejects_total": sum(x["gate_rejects"] for x in ms),
                "self_repairs_median": _med([x["self_repairs"] for x in ms]),
                "errors": [x["llm_error"] for x in ms if x["llm_error"]],
            }
        item["verdict"] = verdict(_vec([r["agent"] for r in rs]), _vec([r["pipeline"] for r in rs]))
        out.append(item)
    return out


def _pct_s(x: float | None) -> str:
    return "-" if x is None else f"{x:g}%"


def _n(x: Any) -> str:
    return "-" if x is None else f"{x:g}"


def markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"모델 `{report['config'].get('LLM_MODEL') or '-'}` · llmMode `{report['llmMode']}` · 반복 {report['reps']} · "
        f"레벨 0 프롬프트 `{report['promptVersion']['pipeline']}` · 에이전트 프롬프트 `{report['promptVersion']['agent']}`",
        report["note"],
        "",
        "① 최초 draft와 ② 레벨 0 최종은 **같은 draft 호출**의 출력이다. 두 열의 차이는 후처리 효과다. ③은 별도 호출이다.",
        "",
        "| 지표 | ① 최초 draft | ② 레벨 0 최종 | ③ 에이전트 |",
        "|---|---|---|---|",
    ]
    rows = [
        ("실행 수", lambda m: _n(s[m]["runs"])),
        ("정상 READY", lambda m: _pct_s(s[m]["READY_pct"])),
        ("degraded READY", lambda m: _pct_s(s[m]["DEGRADED_pct"])),
        ("FAILED·미완료", lambda m: _pct_s(s[m]["FAILED_pct"])),
        ("초안 생성(검사만)", lambda m: _pct_s(s[m]["DRAFT_pct"]) if m == "single" else "-"),
        ("NOT_IN_SOURCE 합계", lambda m: _n(s[m]["NOT_IN_SOURCE_total"])),
        ("MISSING 합계", lambda m: _n(s[m]["MISSING_total"])),
        ("PRIVACY 합계", lambda m: _n(s[m]["PRIVACY_total"])),
        ("NEW_PLACE 합계(legitPlaces 밖)", lambda m: _n(s[m]["NEW_PLACE_total"])),
        ("모델 호출 중앙값 / 최댓값 / 합계", lambda m: f"{_n(s[m]['calls_median'])} / {_n(s[m]['calls_max'])} / {_n(s[m]['calls_total'])}"),
        ("입력 토큰 중앙값 / 합계", lambda m: f"{_n(s[m]['tokens_in_median'])} / {_n(s[m]['tokens_in_total'])}"),
        ("출력 토큰 중앙값 / 합계", lambda m: f"{_n(s[m]['tokens_out_median'])} / {_n(s[m]['tokens_out_total'])}"),
        ("질문 횟수 합계(건너뜀)", lambda m: f"{_n(s[m]['questions_total'])}({_n(s[m]['skipped_total'])})"),
        ("게이트 거부 합계", lambda m: _n(s[m]["gate_rejects_total"])),
        ("자체 수정 합계(REWRITTEN·REMOVED)", lambda m: _n(s[m]["self_repairs_total"])),
        ("응답 시간 ms 중앙값 / p95 / 최댓값", lambda m: f"{_n(s[m]['latency_ms_median'])} / {_n(s[m]['latency_ms_p95'])} / {_n(s[m]['latency_ms_max'])}"),
        ("타임아웃 / 공급자 오류 / 429 / 예산 중단", lambda m: f"{s[m]['timeouts']} / {s[m]['provider_errors']} / {s[m]['rate_limited']} / {s[m]['budget_stops']}"),
    ]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(m) for m in METHODS) + " |")
    lines += ["", "| 사연 | 유형 | ② 결과 | ③ 결과 | ① NIS/MIS/PRI/NEW(중앙) | ② 같은 항목 | ③ 같은 항목 | ③ 호출(중앙) | ③ 질문(중앙) | ③ 자체수정(중앙) | ③ 게이트 거부 | 판정 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]

    def f4(x: dict[str, Any]) -> str:
        return f"{_n(x['NOT_IN_SOURCE'])}/{_n(x['MISSING'])}/{_n(x['PRIVACY'])}/{_n(x['NEW_PLACE'])}"

    for it in report["stories"]:
        p, a, d = it["pipeline"], it["agent"], it["single"]
        lines.append(f"| {it['id']} | {it['category']} | {','.join(p['outcomes'])} | {','.join(a['outcomes'])} | {f4(d)} | {f4(p)} | {f4(a)} | "
                     f"{_n(a['calls_median'])} | {_n(a['questions_median'])} | {_n(a['self_repairs_median'])} | {a['gate_rejects_total']} | {it['verdict']} |")
    lines += ["", "NIS=NOT_IN_SOURCE, MIS=MISSING, PRI=PRIVACY, NEW=NEW_PLACE. 사연별 값은 전달된 실행의 중앙값이고, 판정은 "
              "(실패 수, 잔존 품질 문제 합, MISSING 합)을 ②와 ③에서 비교한다(개선·악화·동일·혼합)."]
    if report.get("aborted"):
        lines += ["", f"**중단:** {report['aborted']}. 그 이후 사연은 실행하지 않았다."]
    return "\n".join(lines)


def write(path: pathlib.Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_report(rows: list[dict[str, Any]], *, mode: str, reps: int, cfg: dict[str, str], aborted: str | None, complete: bool) -> dict[str, Any]:
    from agent.prompt import agent_prompt_version, prompt_version
    from tests.fixtures.stories import AUTO_ANSWER_RULE

    report = {
        "complete": complete, "llmMode": mode, "note": FAKE_NOTE if mode == "fake" else TRIAL_NOTE, "reps": reps, "config": cfg,
        "promptVersion": {"pipeline": prompt_version(), "agent": agent_prompt_version()}, "autoAnswer": AUTO_ANSWER_RULE,
        "methods": {"single": "① 레벨 0 실행의 첫 초안, 검사만(후처리 전)", "pipeline": "② 같은 실행의 최종 카드(규칙·Gate·폴백·Final_Check)",
                    "agent": "③ 별도 호출(에이전트 프롬프트·도구 루프·자동 답·메모리 체크포인터·NoopBudget)"},
        "limits": {"turn_ms": TURN_MS, "fence_s": FENCE_S, "max_turns": MAX_TURNS, "calls": 6, "input_tokens": 30000},
        "aborted": aborted, "rows_done": len(rows),
        "summary": summarize(rows) if rows else {}, "stories": per_story(rows) if rows else [], "rows": rows,
    }
    return report


def run_all(stories: list[dict[str, Any]], *, reps: int, pipe_env: dict[str, str], agent_env: dict[str, str], pause: float,
            real: bool, on_row: Any = None) -> tuple[list[dict[str, Any]], str | None]:
    """사연 × 반복. 실행 흐름은 ①②(같은 draft) → ③ 순서다. 429가 RATE_ABORT_STREAK회 연속이면 멈춘다."""
    rows: list[dict[str, Any]] = []
    streak = 0
    for rep in range(reps):
        for fx in stories:
            d, p = run_pipeline(pipe_env, fx)
            time.sleep(pause if real else 0)
            a = run_agent(agent_env, fx, pause if real else 0)
            row = {"id": fx["id"], "category": fx["category"], "rep": rep + 1, "single": d, "pipeline": p, "agent": a}
            rows.append(row)
            print(f"[{rep + 1}/{reps}] {fx['id']}: ① {d['outcome']} ② {p['outcome']} ③ {a['outcome']} ({a['calls']}회)", file=sys.stderr)
            if on_row:
                on_row(rows)
            hit429 = any(r["llm_error"] == RATE_LIMIT for r in (p, a))
            streak = streak + 1 if hit429 else 0
            if hit429 and real:
                time.sleep(RATE_BACKOFF_S)
            if streak >= RATE_ABORT_STREAK:
                return rows, f"공급자 HTTP 429가 {RATE_ABORT_STREAK}회 연속이라 중단(우회하지 않음)"
            time.sleep(pause if real else 0)
    return rows, None


def main() -> int:
    from agent import llm
    from tests.fixtures.stories import load_stories

    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default="")
    ap.add_argument("--fake", action="store_true", help="Fake 모델로 도구만 확인(품질 근거 아님)")
    ap.add_argument("--fake-pipeline-scenario", default="happy")
    ap.add_argument("--fake-agent-scenario", default="ask_once")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--stories", default="", help="쉼표로 구분한 id(기본 전체 15건)")
    ap.add_argument("--pause", type=float, default=2.0, help="호출 사이 쉼(초, 공급자 분당 한도 보호)")
    ap.add_argument("--out", default="")
    ap.add_argument("--yes", action="store_true", help="예상 호출 수를 보고 확인 없이 진행")
    args = ap.parse_args()
    llm.quiet_library_loggers()
    os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"

    stories = load_stories()
    if args.stories:
        want = set(args.stories.split(","))
        stories = [s for s in stories if s["id"] in want]
    if args.fake:
        pipe_env, agent_env = fake_env(args.fake_pipeline_scenario, args.fake_agent_scenario)
        mode = "fake"
    elif args.env_file:
        pipe_env = agent_env = read_env(args.env_file)
        mode = "fake" if pipe_env.get("LLM_PROVIDER") == "fake" else "openai_compat"
    else:
        raise SystemExit("--env-file 또는 --fake가 필요하다")
    settings = llm.load_settings(pipe_env)
    if settings.error:
        raise SystemExit(f"설정 오류: {settings.error}")
    cfg = {k: v for k, v in pipe_env.items() if k.startswith("LLM_") and k != "LLM_API_KEY"}
    max_calls = len(stories) * args.reps * (2 + 6)
    print(f"예상 모델 호출: 최대 {max_calls}회(사연 {len(stories)} × 반복 {args.reps} × (레벨 0 ≤2 + 에이전트 ≤6)), "
          f"호출 사이 쉼 {args.pause}초", file=sys.stderr)
    if mode != "fake" and not args.yes:
        if input("진행할까요? [y/N] ").strip().lower() != "y":
            return 1

    out = pathlib.Path(args.out) if args.out else None
    rows, aborted = run_all(stories, reps=args.reps, pipe_env=pipe_env, agent_env=agent_env, pause=args.pause, real=mode != "fake",
                            on_row=(lambda r: write(out, build_report(r, mode=mode, reps=args.reps, cfg=cfg, aborted=None, complete=False)))
                            if out else None)
    report = build_report(rows, mode=mode, reps=args.reps, cfg=cfg, aborted=aborted,
                          complete=aborted is None and len(rows) == len(stories) * args.reps)
    if out:
        write(out, report)
    print(markdown(report))
    if not out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if aborted is None else 2


if __name__ == "__main__":
    os.chdir(BACKEND)
    sys.exit(main())
