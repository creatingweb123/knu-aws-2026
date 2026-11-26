"""오프라인 평가: 단발(①)·레벨 0(②)·에이전트(③) 비교 (6b 작업 18, design §21, BE-Q112).

사용(backend/에서):
    .venv/bin/python scripts/eval_agent.py --env-file .env [--reps 3] [--stories demo,nis_1] [--pause 1.6] [--out FILE]
    .venv/bin/python scripts/eval_agent.py --fake            # 도구가 도는지만 본다(품질 근거 아님)

- 사연은 tests/fixtures/stories.json의 합성 사연만 쓴다. 실제 사용자 사연을 넣지 않는다.
- ①과 ②는 같은 레벨 0 실행 1회(day_card.md, 재시도 포함)의 후처리 전후다. ①은 첫 초안(first_proposal)에 검사만,
  ②는 규칙·Gate·폴백·Final_Check 뒤 최종 카드다. ③은 별도 호출(에이전트 프롬프트, 메모리 체크포인터, 자동 답)이다.
  ③과 ①·②의 차이에는 프롬프트·도구 루프·모델 출력의 무작위성이 섞인다. 그래서 사연마다 반복(기본 3) 중앙값을 낸다.
- 6a·6b 제한과 예산(호출 6회, 토큰 3만, 12초 규칙, 27초 턴, 24초 울타리)을 완화하지 않는다. AWS·DynamoDB를 쓰지 않는다.
- 결과 파일에는 모델·설정(키 제외)·프롬프트 버전·llmMode·자동 답 규칙을 적는다. 사연·카드 원문은 넣지 않는다(개수·이름 길이 없음).
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
sys.path.insert(0, str(BACKEND))

TURN_MS = 27_000
FENCE_S = 24.0
MAX_TURNS = 8
METHODS = ("single", "pipeline", "agent")
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
    new_place = len([h for h in find_not_in_source([" ".join(legit)], place_targets(names)) if h.path.endswith(".name")]) if legit else len(places)
    return {"NOT_IN_SOURCE": len(find_not_in_source(sources, place_targets(places))), "MISSING": missing,
            "PRIVACY": len(scan_privacy(text)), "NEW_PLACE": new_place, "places": len(places)}


def flags_count(flags: list[dict[str, Any]] | None) -> dict[str, int]:
    out = {"NOT_IN_SOURCE": 0, "MISSING": 0, "PRIVACY": 0}
    for f in flags or []:
        if f.get("type") in out:
            out[f["type"]] += 1
    return out


# ---------------------------------------------------------------- ①·② 레벨 0 실행 1회


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
    tokens = int(state.get("token_in") or 0) + int(state.get("token_out") or 0)
    sources = [fx["story"]]
    first = state.get("first_proposal")
    single = {"outcome": "READY" if isinstance(first, dict) else "FAILED", "degraded": False, "calls": calls, "tokens": tokens,
              "latency_ms": ms, "questions": 0, "llm_error": state.get("llm_error"),
              **residuals(first, sources, fx["legitPlaces"])}
    outcome = "FAILED" if status != "READY" else ("DEGRADED" if state.get("degraded") else "READY")
    pipe = {"outcome": outcome, "http": http, "failure": failure, "degraded": bool(state.get("degraded")), "calls": calls, "tokens": tokens,
            "latency_ms": ms, "questions": 0, "llm_error": state.get("llm_error"), "flags": flags_count(state.get("flags")),
            **residuals(state.get("final_card"), sources, fx["legitPlaces"])}
    return single, pipe


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
            ans = {"skipped": True, "viaFinish": True} if finish else auto_answer(payload, fx["answers"])
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
    if result.get("outcome") == "READY" and final is not None:
        outcome = "DEGRADED" if result.get("degraded") else "READY"
    else:
        outcome = "FAILED" if "__interrupt__" not in result else "UNFINISHED"
    return {"outcome": outcome, "degraded": bool(result.get("degraded")), "calls": int(b.get("modelCalls") or 0),
            "tokens": int(b.get("tokenReported") or 0) + int(b.get("tokenEstimated") or 0) + int(b.get("tokenOut") or 0),
            "token_estimated": int(b.get("tokenEstimated") or 0) > 0, "latency_ms": sum(turn_ms), "turn_ms_max": max(turn_ms),
            "turns": turns, "questions": int(b.get("questions") or 0), "skipped": sum(1 for a in answers if a.get("skipped")),
            "llm_error": result.get("llm_error"), "flags": flags_count(result.get("flags")),
            "tools": [t.get("tool") for t in result.get("trace") or []], **residuals(final, sources, fx["legitPlaces"])}


# ---------------------------------------------------------------- 집계


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def _p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in METHODS:
        rs = [r[m] for r in rows]
        ok = [r for r in rs if r["outcome"] in ("READY", "DEGRADED")]
        lat = [r["latency_ms"] for r in rs]
        out[m] = {
            "runs": len(rs), "ready": sum(r["outcome"] == "READY" for r in rs), "degraded": sum(r["outcome"] == "DEGRADED" for r in rs),
            "failed": sum(r["outcome"] not in ("READY", "DEGRADED") for r in rs),
            **{f"{k}_total": sum(r[k] for r in ok) for k in ("NOT_IN_SOURCE", "MISSING", "PRIVACY", "NEW_PLACE")},
            "calls_median": _median([r["calls"] for r in rs]), "tokens_median": _median([r["tokens"] for r in rs]),
            "latency_ms_median": _median(lat), "latency_ms_p95": _p95(lat), "questions_total": sum(r["questions"] for r in rs),
        }
    return out


def per_story(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """사연 × 방식별 반복 중앙값과 에이전트가 레벨 0보다 낫지 않은 경우."""
    out = []
    for sid in dict.fromkeys(r["id"] for r in rows):
        rs = [r for r in rows if r["id"] == sid]
        item: dict[str, Any] = {"id": sid, "category": rs[0]["category"]}
        for m in METHODS:
            ms = [r[m] for r in rs]
            item[m] = {"outcomes": [x["outcome"] for x in ms],
                       **{k: _median([x[k] for x in ms]) for k in ("NOT_IN_SOURCE", "MISSING", "PRIVACY", "NEW_PLACE", "calls", "tokens",
                                                                   "latency_ms", "questions")}}
        a, p = item["agent"], item["pipeline"]
        score = lambda x: (x["NOT_IN_SOURCE"] or 0) + (x["PRIVACY"] or 0) + (x["NEW_PLACE"] or 0)  # noqa: E731
        fails = lambda x: sum(o not in ("READY", "DEGRADED") for o in x["outcomes"])  # noqa: E731
        worse = fails(a) > fails(p) or score(a) > score(p) or ((a["MISSING"] or 0) > (p["MISSING"] or 0))
        better = fails(a) < fails(p) or score(a) < score(p) or ((a["MISSING"] or 0) < (p["MISSING"] or 0))
        item["agent_vs_pipeline"] = "WORSE" if worse and not better else ("BETTER" if better and not worse else
                                                                          ("MIXED" if worse else "SAME"))
        out.append(item)
    return out


def markdown(report: dict[str, Any]) -> str:
    lines = [f"모델 {report['config'].get('LLM_MODEL') or '-'} · llmMode {report['llmMode']} · 반복 {report['reps']} · "
             f"promptVersion 레벨0 {report['promptVersion']['pipeline']} / 에이전트 {report['promptVersion']['agent']}",
             report["note"], "", "| 방식 | 실행 | READY | degraded | 실패 | NOT_IN_SOURCE | MISSING | PRIVACY | NEW_PLACE | 호출(중앙) | "
             "토큰(중앙) | 지연 중앙/p95 ms | 질문 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    label = {"single": "① 단발", "pipeline": "② 레벨 0", "agent": "③ 에이전트"}
    for m, s in report["summary"].items():
        lines.append(f"| {label[m]} | {s['runs']} | {s['ready']} | {s['degraded']} | {s['failed']} | {s['NOT_IN_SOURCE_total']} | "
                     f"{s['MISSING_total']} | {s['PRIVACY_total']} | {s['NEW_PLACE_total']} | {s['calls_median']} | {s['tokens_median']} | "
                     f"{s['latency_ms_median']}/{s['latency_ms_p95']} | {s['questions_total']} |")
    lines += ["", "| 사연 | 유형 | ② 결과 | ③ 결과 | ② NIS/MIS/PRI/NEW | ③ NIS/MIS/PRI/NEW | ③ 호출 | ③ 질문 | 판정 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for it in report["stories"]:
        p, a = it["pipeline"], it["agent"]
        f = lambda x: f"{x['NOT_IN_SOURCE']}/{x['MISSING']}/{x['PRIVACY']}/{x['NEW_PLACE']}"  # noqa: E731
        lines.append(f"| {it['id']} | {it['category']} | {','.join(p['outcomes'])} | {','.join(a['outcomes'])} | {f(p)} | {f(a)} | "
                     f"{a['calls']} | {a['questions']} | {it['agent_vs_pipeline']} |")
    lines += ["", "합계는 READY·degraded 카드의 잔존 수다. NEW_PLACE는 legitPlaces 밖 장소 수(legitPlaces가 비면 장소 수)."]
    return "\n".join(lines)


def main() -> int:
    from agent import llm
    from agent.prompt import agent_prompt_version, prompt_version
    from tests.fixtures.stories import AUTO_ANSWER_RULE, load_stories

    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default="")
    ap.add_argument("--fake", action="store_true", help="Fake 모델로 도구만 확인(품질 근거 아님)")
    ap.add_argument("--fake-pipeline-scenario", default="happy")
    ap.add_argument("--fake-agent-scenario", default="ask_once")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--stories", default="", help="쉼표로 구분한 id(기본 전체 15건)")
    ap.add_argument("--pause", type=float, default=1.6, help="사연·턴 사이 쉼(초, 공급자 분당 한도 보호)")
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
    for e in {id(pipe_env): pipe_env, id(agent_env): agent_env}.values():
        if llm.load_settings(e).error:
            raise SystemExit(f"설정 오류: {llm.load_settings(e).error}")
    max_calls = len(stories) * args.reps * (2 + 6)
    print(f"예상 모델 호출: 최대 {max_calls}회(사연 {len(stories)} × 반복 {args.reps} × (레벨 0 ≤2 + 에이전트 ≤6)), 쉼 {args.pause}초",
          file=sys.stderr)
    if mode != "fake" and not args.yes:
        if input("진행할까요? [y/N] ").strip().lower() != "y":
            return 1

    rows = []
    for rep in range(args.reps):
        for fx in stories:
            single, pipe = run_pipeline(pipe_env, fx)
            time.sleep(args.pause if mode != "fake" else 0)
            agent = run_agent(agent_env, fx, args.pause if mode != "fake" else 0)
            rows.append({"id": fx["id"], "category": fx["category"], "rep": rep + 1, "single": single, "pipeline": pipe, "agent": agent})
            print(f"[{rep + 1}/{args.reps}] {fx['id']}: ② {pipe['outcome']} ③ {agent['outcome']} ({agent['calls']}회)", file=sys.stderr)
            time.sleep(args.pause if mode != "fake" else 0)

    cfg = {k: v for k, v in agent_env.items() if k.startswith("LLM_") and k != "LLM_API_KEY"}
    report = {
        "llmMode": mode, "note": FAKE_NOTE if mode == "fake" else TRIAL_NOTE, "reps": args.reps, "config": cfg,
        "promptVersion": {"pipeline": prompt_version(), "agent": agent_prompt_version()}, "autoAnswer": AUTO_ANSWER_RULE,
        "methods": {"single": "① 레벨 0 첫 초안에 검사만(후처리 전)", "pipeline": "② 같은 실행의 최종 카드(규칙·Gate·폴백·Final_Check)",
                    "agent": "③ 별도 호출(에이전트 프롬프트·도구 루프·자동 답)"},
        "limits": {"turn_ms": TURN_MS, "fence_s": FENCE_S, "max_turns": MAX_TURNS, "budget": "호출 6·토큰 30,000(NoopBudget)"},
        "summary": summarize(rows), "stories": per_story(rows), "rows": rows,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.out).write_text(text, encoding="utf-8")
    print(markdown(report))
    if not args.out:
        print(text)
    return 0


if __name__ == "__main__":
    os.chdir(BACKEND)
    sys.exit(main())
