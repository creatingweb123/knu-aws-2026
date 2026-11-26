"""오프라인 평가 도구 Fake 실행 (작업 18.2). 표 형식과 열만 본다. Fake 결과는 품질 근거가 아니다."""

import json
import pathlib
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[2]


def run(tmp_path, *extra):
    out = tmp_path / "eval.json"
    r = subprocess.run([sys.executable, "scripts/eval_agent.py", "--fake", "--reps", "2", "--stories", "demo,injection_1",
                        "--out", str(out), *extra], cwd=BACKEND, capture_output=True, text=True, timeout=180,
                       env={"PATH": "/usr/bin:/bin", "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"})
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout, json.loads(out.read_text(encoding="utf-8")), r.stderr


def test_table_and_columns(tmp_path):
    stdout, report, stderr = run(tmp_path)
    assert "Fake 결과는 품질 근거가 아니다" in stdout and report["llmMode"] == "fake"
    assert "예상 모델 호출: 최대 32회" in stderr
    header = "| 방식 | 실행 | READY | degraded | 실패 | NOT_IN_SOURCE | MISSING | PRIVACY | NEW_PLACE | 호출(중앙) | 토큰(중앙) | 지연 중앙/p95 ms | 질문 |"
    assert header in stdout and "| ① 단발 |" in stdout and "| ② 레벨 0 |" in stdout and "| ③ 에이전트 |" in stdout
    assert "| 사연 | 유형 | ② 결과 | ③ 결과 |" in stdout and "| injection_1 |" in stdout
    assert set(report["summary"]) == {"single", "pipeline", "agent"} and report["reps"] == 2 and len(report["rows"]) == 4
    assert {"pipeline", "agent"} == set(report["promptVersion"]) and report["autoAnswer"]
    for it in report["stories"]:
        assert it["agent_vs_pipeline"] in ("BETTER", "WORSE", "SAME", "MIXED")
        assert len(it["agent"]["outcomes"]) == 2


def test_no_story_text_or_key_in_output(tmp_path):
    from tests.fixtures.stories import story

    stdout, report, _ = run(tmp_path)
    blob = stdout + json.dumps(report, ensure_ascii=False)
    for sid in ("demo", "injection_1"):
        text = story(sid)["story"]
        assert text not in blob and text[:15] not in blob
    assert "LLM_API_KEY" not in json.dumps(report["config"])
    assert all(r["agent"]["calls"] <= 6 for r in report["rows"])  # 예산을 완화하지 않는다
