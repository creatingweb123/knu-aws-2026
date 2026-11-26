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


def test_legit_index_matches_story_order():
    """BE-Q127 확인용: 장소 이름이 legitPlaces의 몇 번째인지(목록 밖은 None). 이름 자체는 결과에 남지 않는다."""
    mod = load_probe()
    st = {"legitPlaces": ["빵집", "국숫집", "서점", "공원", "하천 다리"]}
    assert [mod._legit_index(st, n) for n in ("출근길 빵집", "국숫집", "하천 다리", "카페", None, "")] == [0, 1, 4, None, None, None]


def test_pipeline_ids_and_reps_with_fake(monkeypatch):
    """Fake 시나리오로 --ids/--reps 경로를 돌린다(공급자 호출 0). 요약과 행에 이름이 없어야 한다."""
    mod = load_probe()
    monkeypatch.setattr(mod, "PAUSE_S", 0)
    env = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local", "FAKE_LLM_SCENARIO": "happy"}
    out = mod.probe_pipeline(env, 0, ids=["demo"], reps=2)
    assert len(out["rows"]) == 2 and {r["id"] for r in out["rows"]} == {"demo"}
    assert all(r["status"] == "READY" and r["legit_order"] == [0, 1] for r in out["rows"])  # happy 장소 2곳은 legitPlaces[0], [1]
    text = json.dumps(out, ensure_ascii=False)
    assert "출근길 빵집" not in text and "빵집에" not in text
    # 원문에 없는 장소(many_places 사연의 happy 카드)는 게이트가 빼서 degraded이고 legit_order가 비어야 한다
    gate = mod.probe_pipeline(env, 0, ids=["many_places"], reps=1)["rows"][0]
    assert gate["degraded"] is True and gate["legit_order"] == [] and gate["first_not_in_source"] >= 1
    bad = mod.probe_pipeline(env, 0, ids=["nope"], reps=1)
    assert "config_error" in bad and "nope" in bad["config_error"]
