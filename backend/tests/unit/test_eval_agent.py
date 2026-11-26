"""오프라인 평가 도구 (작업 18.2·20.3). 집계·판정·중단 로직은 합성 행으로 확인한다. 실제 공급자를 부르지 않는다.

Fake 실행 두 건은 표 형식과 열, 원문 미노출만 본다. Fake 결과는 품질 근거가 아니다.
"""

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("eval_agent", BACKEND / "scripts" / "eval_agent.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

LEGIT = ["출근길 빵집", "하천 벤치"]


def story(sid, category="데모"):
    return {"id": sid, "category": category, "story": "합성 사연 문장 하나.", "legitPlaces": LEGIT, "answers": {}}


def row(outcome="READY", *, nis=0, mis=0, pri=0, new=0, **kw):
    base = {"outcome": outcome, "NOT_IN_SOURCE": nis, "MISSING": mis, "PRIVACY": pri, "NEW_PLACE": new, "places": 1}
    return ev._row(outcome, {k: base[k] for k in ("NOT_IN_SOURCE", "MISSING", "PRIVACY", "NEW_PLACE", "places")}, **kw)


# ---------------------------------------------------------------- 순수 함수


def test_nearest_rank_percentiles():
    assert ev.nearest_rank(list(range(1, 21)), 0.95) == 19  # ceil(0.95·20) = 19번째
    assert ev.nearest_rank([1, 2, 3, 4], 0.5) == 2
    assert ev.nearest_rank([7], 0.95) == 7
    assert ev.nearest_rank([], 0.95) is None


@pytest.mark.parametrize(("agent", "pipe", "expected"), [
    ((0, 0, 0), (0, 0, 0), "동일"),
    ((0, 0, 0), (1, 0, 0), "개선"),
    ((0, 0, 0), (0, 2, 3), "개선"),
    ((1, 0, 0), (0, 0, 0), "악화"),
    ((0, 1, 0), (0, 0, 1), "혼합"),
])
def test_verdict_rule(agent, pipe, expected):
    assert ev.verdict(agent, pipe) == expected


def test_summarize_counts_and_percentages():
    rows = [
        {"single": row("DRAFT", nis=2, calls=1, tokens_in=100, tokens_out=10), "pipeline": row("READY", calls=1, tokens_in=100, tokens_out=10,
                                                                                                gate_rejects=0),
         "agent": row("READY", calls=4, questions=1, tokens_in=900, tokens_out=80, latency_ms=3000)},
        {"single": row("NO_DRAFT", calls=2, llm_error="TIMEOUT"),
         "pipeline": row("DEGRADED", nis=0, mis=1, calls=2, gate_rejects=1, self_repairs=2, llm_error="HTTP_429"),
         "agent": row("UNFINISHED", calls=6, llm_error="TIMEOUT", latency_ms=20000)},
        {"single": row("DRAFT", new=1, calls=1, tokens_in=50, tokens_out=5),
         "pipeline": row("FAILED", calls=1, llm_error="HTTP_401"), "agent": row("DEGRADED", pri=1, calls=3, skipped=1, latency_ms=5000)},
    ]
    s = ev.summarize(rows)
    assert s["single"]["DRAFT_pct"] == pytest.approx(66.7) and s["single"]["delivered"] == 2
    assert s["single"]["NOT_IN_SOURCE_total"] == 2 and s["single"]["NEW_PLACE_total"] == 1  # NO_DRAFT는 전달되지 않는다
    assert s["pipeline"]["READY_pct"] == pytest.approx(33.3) and s["pipeline"]["DEGRADED_pct"] == pytest.approx(33.3)
    assert s["pipeline"]["FAILED_pct"] == pytest.approx(33.3)
    assert s["pipeline"]["MISSING_total"] == 1 and s["pipeline"]["delivered"] == 2  # FAILED 카드는 합계에 없다
    assert s["pipeline"]["gate_rejects_total"] == 1 and s["pipeline"]["self_repairs_total"] == 2
    assert s["pipeline"]["rate_limited"] == 1 and s["pipeline"]["provider_errors"] == 2  # HTTP_429, HTTP_401
    assert s["agent"]["timeouts"] == 1 and s["agent"]["questions_total"] == 1 and s["agent"]["skipped_total"] == 1
    assert s["agent"]["tokens_in_total"] == 900 + 0 + 0 and s["agent"]["calls_max"] == 6
    assert s["agent"]["latency_ms_max"] == 20000 and s["agent"]["latency_ms_p95"] == 20000
    assert s["agent"]["FAILED_pct"] == pytest.approx(33.3)  # UNFINISHED도 미완료로 센다


def test_per_story_verdict_uses_run_level_vectors():
    rows = [
        {"id": "a", "category": "x", "rep": 1, "single": row("DRAFT", nis=3), "pipeline": row("READY", nis=0),
         "agent": row("READY", nis=0)},
        {"id": "a", "category": "x", "rep": 2, "single": row("DRAFT", nis=3), "pipeline": row("DEGRADED", nis=1),
         "agent": row("FAILED")},
        {"id": "b", "category": "y", "rep": 1, "single": row("DRAFT"), "pipeline": row("READY", mis=2), "agent": row("READY", mis=1)},
    ]
    stories = ev.per_story(rows)
    assert stories[0]["id"] == "a" and stories[0]["verdict"] == "혼합"  # ② 실패 0·잔존 1, ③ 실패 1·잔존 0
    assert stories[1]["verdict"] == "개선"  # MISSING 2 → 1
    assert stories[0]["agent"]["outcomes"] == ["READY", "FAILED"]
    assert stories[0]["single"]["NOT_IN_SOURCE"] == 3  # 초안의 중앙값(전달된 실행만)


def test_markdown_states_shared_draft_and_failures():
    rows = [{"id": "a", "category": "x", "rep": 1, "single": row("DRAFT"), "pipeline": row("FAILED", llm_error="HTTP_429"),
             "agent": row("FAILED", llm_error="HTTP_429")}]
    report = ev.build_report(rows, mode="openai_compat", reps=1, cfg={"LLM_MODEL": "m"}, aborted="중단 사유", complete=False)
    text = ev.markdown(report)
    assert "**같은 draft 호출**" in text
    assert "| 지표 | ① 최초 draft | ② 레벨 0 최종 | ③ 에이전트 |" in text
    assert "**중단:** 중단 사유" in text and "모델 `m`" in text
    assert report["complete"] is False and report["rows_done"] == 1


def test_three_consecutive_429_stops_and_keeps_partial(tmp_path, monkeypatch):
    """HTTP 429가 3회 연속이면 우회하지 않고 멈춘다. 그때까지의 행은 파일에 complete: false로 남는다."""
    calls = {"n": 0}

    def pipe(env, fx):
        calls["n"] += 1
        return row("DRAFT"), row("FAILED", llm_error="HTTP_429")

    monkeypatch.setattr(ev, "run_pipeline", pipe)
    monkeypatch.setattr(ev, "run_agent", lambda env, fx, pause: row("FAILED", llm_error="HTTP_429"))
    out = tmp_path / "partial.json"
    stories = [story(f"s{i}") for i in range(5)]

    def save(rows):
        ev.write(out, ev.build_report(rows, mode="openai_compat", reps=1, cfg={}, aborted=None, complete=False))

    rows, aborted = ev.run_all(stories, reps=1, pipe_env={}, agent_env={}, pause=0, real=False, on_row=save)
    assert calls["n"] == 3 and len(rows) == 3 and aborted and "429" in aborted
    report = ev.build_report(rows, mode="openai_compat", reps=1, cfg={}, aborted=aborted, complete=False)
    ev.write(out, report)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["complete"] is False and saved["rows_done"] == 3 and saved["aborted"] == aborted
    assert saved["summary"]["pipeline"]["rate_limited"] == 3


def test_non_429_failures_do_not_abort(monkeypatch):
    monkeypatch.setattr(ev, "run_pipeline", lambda env, fx: (row("DRAFT"), row("FAILED", llm_error="TIMEOUT")))
    monkeypatch.setattr(ev, "run_agent", lambda env, fx, pause: row("READY"))
    rows, aborted = ev.run_all([story(f"s{i}") for i in range(4)], reps=1, pipe_env={}, agent_env={}, pause=0, real=False)
    assert len(rows) == 4 and aborted is None


def test_429_streak_resets_on_success(monkeypatch):
    seq = iter(["HTTP_429", "HTTP_429", None, "HTTP_429", "HTTP_429", None])

    def pipe(env, fx):
        return row("DRAFT"), row("FAILED", llm_error=next(seq, None))

    monkeypatch.setattr(ev, "run_pipeline", pipe)
    monkeypatch.setattr(ev, "run_agent", lambda env, fx, pause: row("READY"))
    rows, aborted = ev.run_all([story(f"s{i}") for i in range(6)], reps=1, pipe_env={}, agent_env={}, pause=0, real=False)
    assert len(rows) == 6 and aborted is None


# ---------------------------------------------------------------- Fake 실행(도구 확인, 원문 미노출)


def run_fake(tmp_path, *extra):
    out = tmp_path / "eval.json"
    r = subprocess.run([sys.executable, "scripts/eval_agent.py", "--fake", "--reps", "2", "--stories", "demo,injection_1",
                        "--out", str(out), *extra], cwd=BACKEND, capture_output=True, text=True, timeout=240,
                       env={"PATH": "/usr/bin:/bin", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"})
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout, json.loads(out.read_text(encoding="utf-8")), r.stderr


def test_fake_table_columns_and_completion(tmp_path):
    stdout, report, stderr = run_fake(tmp_path)
    assert "Fake 결과는 품질 근거가 아니다" in stdout and report["llmMode"] == "fake" and report["complete"] is True
    assert "예상 모델 호출: 최대 32회" in stderr
    assert "| 지표 | ① 최초 draft | ② 레벨 0 최종 | ③ 에이전트 |" in stdout
    for label in ("정상 READY", "degraded READY", "FAILED·미완료", "NOT_IN_SOURCE 합계", "MISSING 합계", "PRIVACY 합계",
                  "NEW_PLACE 합계", "모델 호출 중앙값", "입력 토큰 중앙값", "출력 토큰 중앙값", "질문 횟수", "게이트 거부 합계",
                  "자체 수정 합계", "응답 시간 ms", "타임아웃 / 공급자 오류"):
        assert label in stdout, label
    assert "| 사연 | 유형 | ② 결과 | ③ 결과 |" in stdout and "| injection_1 |" in stdout
    assert len(report["rows"]) == 4 and {"id", "category", "rep", "single", "pipeline", "agent"} <= set(report["rows"][0])
    assert all(it["verdict"] in ("개선", "악화", "동일", "혼합") for it in report["stories"])


def test_no_story_text_or_key_in_output(tmp_path):
    from tests.fixtures.stories import story as fixture_story

    stdout, report, _ = run_fake(tmp_path)
    blob = stdout + json.dumps(report, ensure_ascii=False)
    for sid in ("demo", "injection_1"):
        text = fixture_story(sid)["story"]
        assert text not in blob and text[:15] not in blob
    assert "LLM_API_KEY" not in json.dumps(report["config"])
    assert all(r["agent"]["calls"] <= 6 for r in report["rows"])  # 예산을 완화하지 않는다


def test_tool_error_counts_codes_and_question_reasons():
    from langchain_core.messages import HumanMessage, ToolMessage

    msgs = [HumanMessage("x"), ToolMessage(content='{"error": "QUESTION_REJECTED", "reason": "PATH_NOT_ALLOWED"}', tool_call_id="1"),
            ToolMessage(content='{"error": "QUESTION_REJECTED", "reason": "QUESTION_LIMIT"}', tool_call_id="2"),
            ToolMessage(content='{"error": "INVALID_ARGS", "hint": "x"}', tool_call_id="3"),
            ToolMessage(content="not json", tool_call_id="4")]
    codes, rejects = ev.tool_error_counts(msgs)
    assert dict(codes) == {"QUESTION_REJECTED": 2, "INVALID_ARGS": 1}
    assert dict(rejects) == {"PATH_NOT_ALLOWED": 1, "QUESTION_LIMIT": 1}
