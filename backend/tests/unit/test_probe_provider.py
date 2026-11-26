"""공급자 확인 스크립트(scripts/probe_provider.py)와 합성 사연 픽스처의 안전 규칙. 네트워크를 쓰지 않는다."""

import importlib.util
import json
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[2]
KEY = "nvapi-test-not-a-real-key-0000"


def load_probe():
    spec = importlib.util.spec_from_file_location("probe_provider", BACKEND / "scripts" / "probe_provider.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_read_env_only_llm_lines(tmp_path):
    p = tmp_path / ".env"
    p.write_text(f"SEED_PASSWORD=secret\nLLM_API_KEY={KEY}\nLLM_MODEL='m'\n# LLM_X=1\nAWS_SECRET_ACCESS_KEY=x\n", encoding="utf-8")
    env = load_probe().read_env(str(p))
    assert env == {"LLM_API_KEY": KEY, "LLM_MODEL": "m"}


def test_summary_has_no_content_or_error_body():
    probe = load_probe()
    ok = {"choices": [{"finish_reason": "stop", "message": {"content": "출근길 빵집 비밀 문장", "reasoning_content": "생각"}}],
          "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}
    s = probe.summarize_response(200, ok, 0.5)
    text = json.dumps(s, ensure_ascii=False)
    assert "출근길" not in text and "생각" not in text and s["content_len"] == len("출근길 빵집 비밀 문장") and s["korean"] is True
    err = probe.summarize_response(401, {"detail": f"bad key {KEY}", "status": 401}, 0.1)
    assert KEY not in json.dumps(err) and err["error_keys"] == ["detail", "status"]


def test_pipeline_env_defaults_thinking_off():
    env = load_probe().pipeline_env({"LLM_API_KEY": KEY})
    assert json.loads(env["LLM_EXTRA_BODY"]) == {"chat_template_kwargs": {"enable_thinking": False}} and env["LLM_MAX_RETRIES"] == "0"
    kept = load_probe().pipeline_env({"LLM_API_KEY": KEY, "LLM_EXTRA_BODY": '{"x": 1}'})
    assert kept["LLM_EXTRA_BODY"] == '{"x": 1}'


def test_stories_fixture_is_synthetic_and_complete():
    data = json.loads((BACKEND / "tests" / "fixtures" / "stories.json").read_text(encoding="utf-8"))
    stories = data["stories"]
    assert len(stories) == 15 and len({s["id"] for s in stories}) == 15 and "합성" in data["note"]
    assert all(1 <= len(s["story"]) <= 1000 and isinstance(s["legitPlaces"], list) and isinstance(s["answers"], dict) for s in stories)
    cats = {s["category"] for s in stories}
    assert {"데모", "비공개 장소", "연락처", "동호수", "원문에 없는 장소 유도", "인젝션", "빈칸 많음"} <= cats


def test_test_results_dir_is_gitignored():
    assert "test-results/" in (BACKEND / ".gitignore").read_text(encoding="utf-8").splitlines()
