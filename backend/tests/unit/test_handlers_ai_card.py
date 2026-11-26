"""AI 세션 핸들러 (작업 9.5, moto + Fake). Requirement 1.1–1.10, 2.1–2.4, 3.1–3.5, 5.8, 6.1, 19.1, 19.2 · BE-Q87."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent import graph as g
from agent import llm
from agent import nodes
from agent.fake_llm import FakeScenarioChatModel
from common.ids import new_session_id
from domain import ai_session_service as svc
from handlers import ai_card
from tests.unit.ai_handler_util import (  # noqa: F401 - ai_env는 fixture
    OTHER,
    OWNER,
    STORY,
    Ctx,
    ai_env,
    body_of,
    create,
    event,
    get,
    metric_names,
    quota_count,
    sessions,
    turns,
)


@pytest.fixture
def model_calls(monkeypatch):
    """Fake 모델에 실제로 들어간 호출 수를 센다."""
    calls = []
    orig = FakeScenarioChatModel._agenerate

    async def spy(self, *a, **k):
        calls.append(self.scenario)
        return await orig(self, *a, **k)

    monkeypatch.setattr(FakeScenarioChatModel, "_agenerate", spy)
    return calls


# ---------------------------------------------------------------- 생성


def test_create_ready(ai_env, model_calls, capsys):
    resp = create()
    assert resp["statusCode"] == 200
    view = body_of(resp)
    assert list(view) == list(svc.VIEW_KEYS)
    assert view["status"] == "READY" and view["turn"] == 1 and view["question"] is None and view["degraded"] is False
    assert view["sessionId"].startswith("ais_") and view["card"]["places"][0]["name"] == "출근길 빵집"
    assert [t["step"] for t in view["trace"]] == [1, 2, 3] and [t["tool"] for t in view["trace"]] == ["draft", "check_draft", "submit_card"]
    assert "llmMode" not in resp["body"] and "story" not in view
    [item] = sessions(ai_env)
    assert item["status"] == "READY" and item["ownerId"] == "u-owner" and item["story"] == STORY
    assert item["llmMode"] == "fake" and item["agentMode"] == "PIPELINE" and item["modelCalls"] == 1
    assert item["promptVersion"] and item["readyAt"] and item["firstProposal"] and item["firstReport"]
    assert "failureCode" not in item and "llmError" not in item
    assert quota_count(ai_env) == 1 and model_calls == ["happy"]
    names = [n for n, _ in metric_names(capsys.readouterr().out)]
    assert names == ["AiLatencyMs"]


def test_create_privacy_detected_counts_story_and_first_report(ai_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "privacy_high")
    resp = create(STORY + " 연락은 010-9876-5432로 주세요.")
    assert body_of(resp)["degraded"] is True
    [item] = sessions(ai_env)
    assert item["privacyDetected"] == 1 + len(item["firstReport"]["privacy"]) and item["privacyDetected"] >= 3


@pytest.mark.parametrize("body", [None, {}, {"story": ""}, {"story": "가" * 1001}, {"story": 3}, ["x"]])
def test_create_validation_no_quota_no_model(ai_env, model_calls, body):
    resp = ai_card.handler(event("POST /ai/card-sessions", OWNER, body, raw=None if body is not None else ""), Ctx())
    assert resp["statusCode"] == 400
    err = body_of(resp)["error"]
    expected_key = "story" if isinstance(body, dict) else "body"  # 객체가 아닌 본문은 기존 PlanCreate와 같게 body
    assert err["code"] == "VALIDATION_ERROR" and list(err["details"]) == [expected_key]
    assert quota_count(ai_env) == 0 and model_calls == [] and sessions(ai_env) == []


def test_create_story_1000_ok(ai_env):
    assert create("빵집 " * 200)["statusCode"] == 200


def test_unauthenticated_401(ai_env, model_calls):
    resp = ai_card.handler(event("POST /ai/card-sessions", None, {"story": STORY}), Ctx())
    assert resp["statusCode"] == 401 and quota_count(ai_env) == 0 and model_calls == []


@pytest.mark.parametrize("mode", ["agent", "foo", "PIPELINE"])
def test_agent_mode_other_503_before_quota(ai_env, model_calls, monkeypatch, mode, caplog):
    monkeypatch.setenv("AGENT_MODE", mode)
    resp = create()
    assert resp["statusCode"] == 503 and body_of(resp)["error"]["code"] == "AI_UNAVAILABLE"
    assert quota_count(ai_env) == 0 and model_calls == [] and sessions(ai_env) == []
    assert "CONFIG_AGENT_MODE" in caplog.text


def test_agent_mode_pipeline_and_empty_ok(ai_env, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "pipeline")
    assert create()["statusCode"] == 200
    monkeypatch.setenv("AGENT_MODE", "")
    assert create()["statusCode"] == 200


def test_quota_429_no_model_no_session(ai_env, model_calls, monkeypatch):
    monkeypatch.setenv("AI_DAILY_SESSION_LIMIT", "2")
    assert create()["statusCode"] == 200 and create()["statusCode"] == 200
    resp = create()
    assert resp["statusCode"] == 429 and body_of(resp) == {"error": {"code": "AI_QUOTA_EXCEEDED", "message": "오늘 AI 정리 횟수를 모두 썼어요. 직접 정리해 주세요."}}
    assert len(model_calls) == 2 and len(sessions(ai_env)) == 2 and quota_count(ai_env) == 2


SCENARIO_OUTCOMES = [
    ("happy", 200, "READY", None, None, False),
    ("not_in_source", 200, "READY", None, None, True),
    ("privacy_high", 200, "READY", None, None, True),
    ("private_place", 200, "READY", None, None, False),
    ("missing", 200, "READY", None, None, False),
    ("all_places_removed", 200, "READY", None, None, True),
    ("fenced_json", 200, "READY", None, None, False),
    ("no_usage", 200, "READY", None, None, False),
    ("bad_json_then_ok", 200, "READY", None, None, False),
    ("bad_json", 502, "FAILED", "INVALID_OUTPUT", None, False),
    ("schema_error", 502, "FAILED", "INVALID_OUTPUT", None, False),
    ("timeout", 503, "FAILED", "LLM_ERROR", "TIMEOUT", False),
    ("connection", 503, "FAILED", "LLM_ERROR", "CONNECTION", False),
    ("http_400", 503, "FAILED", "LLM_ERROR", "HTTP_400", False),
    ("http_401", 503, "FAILED", "LLM_ERROR", "HTTP_401", False),
    ("http_429", 503, "FAILED", "LLM_ERROR", "HTTP_429", False),
    ("http_500", 503, "FAILED", "LLM_ERROR", "HTTP_5XX", False),
]


@pytest.mark.parametrize(("scenario", "http", "status", "failure", "llm_error", "degraded"), SCENARIO_OUTCOMES)
def test_create_scenarios(ai_env, monkeypatch, capsys, scenario, http, status, failure, llm_error, degraded):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", scenario)
    resp = create()
    assert resp["statusCode"] == http
    [item] = sessions(ai_env)
    assert item["status"] == status and item.get("failureCode") == failure and item.get("llmError") == llm_error
    assert quota_count(ai_env) == 1
    metrics = dict(metric_names(capsys.readouterr().out))
    assert "AiLatencyMs" in metrics
    assert ("AiFailure" in metrics) == (llm_error is not None)
    if http == 200:
        view = body_of(resp)
        assert view["status"] == "READY" and view["degraded"] is degraded and item["degraded"] is degraded
        assert view["card"] == svc.serialize_session_view(item)["card"]
    else:
        code = {502: "AI_INVALID_OUTPUT", 503: "AI_UNAVAILABLE"}[http]
        assert set(body_of(resp)) == {"error"} and body_of(resp)["error"]["code"] == code
        assert item["card"] is None and item["flags"] == [] and item["trace"]  # FAILED도 trace는 남긴다
    if failure == "INVALID_OUTPUT":
        assert metrics["AiInvalidOutput"] == 2 and "firstReport" not in item
    if scenario == "no_usage":
        assert item["tokenEstimated"] is True


def test_mixed_failure_invalid_then_llm_error_is_503(ai_env, monkeypatch):
    monkeypatch.setitem(__import__("agent.fake_llm", fromlist=["SCENARIOS"]).SCENARIOS, "mixed",
                        [{"kind": "content", "text": "JSON 아님", "usage": True, "sleep": 0.0}, {"kind": "raise", "error": "http_500"}])
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "mixed")
    resp = create()
    [item] = sessions(ai_env)
    assert resp["statusCode"] == 503 and item["failureCode"] == "LLM_ERROR" and item["llmError"] == "HTTP_5XX" and item["modelCalls"] == 2


def test_mixed_failure_config_then_nothing_is_503(ai_env, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")  # 공급자 값 없음 → CONFIG, 사연이 나가지 않는다
    resp = create()
    [item] = sessions(ai_env)
    assert resp["statusCode"] == 503 and item["llmError"] == "CONFIG" and item["modelCalls"] == 0 and item["llmMode"] == "openai_compat"


def test_fake_not_allowed_is_503(ai_env, monkeypatch, model_calls):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "haru-demo-AiCardFunction")
    resp = create()
    assert resp["statusCode"] == 503 and model_calls == [] and sessions(ai_env)[0]["llmError"] == "CONFIG"


def test_time_budget_503_zero_calls(ai_env, model_calls):
    resp = create(ctx=Ctx(11_000))
    [item] = sessions(ai_env)
    assert resp["statusCode"] == 503 and item["llmError"] == "TIME_BUDGET" and item["modelCalls"] == 0 and model_calls == []


def test_final_check_blocked_is_502(ai_env, monkeypatch, capsys):
    monkeypatch.setattr(nodes.tools, "final_check", lambda *a, **k: ([], ["SCHEMA"]))
    resp = create()
    [item] = sessions(ai_env)
    assert resp["statusCode"] == 502 and body_of(resp)["error"]["code"] == "AI_INVALID_OUTPUT"
    assert item["status"] == "FAILED" and item["failureCode"] == "FALLBACK_INVARIANT" and item["card"] is None
    assert dict(metric_names(capsys.readouterr().out))["AiInvalidOutput"] == 1


def test_no_plan_created(ai_env):
    create()
    assert [i["PK"] for i in ai_env.scan()["Items"] if not i["PK"].startswith(("AISESSION#", "AIQUOTA#"))] == []


def test_session_ttl_30_days(ai_env):
    create()
    [item] = sessions(ai_env)
    created = datetime.strptime(item["createdAt"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    assert int(item["ttl"]) == int((created + timedelta(days=30)).timestamp())


# ---------------------------------------------------------------- GET


def test_get_owner_200_same_view(ai_env):
    view = body_of(create())
    resp = get(view["sessionId"])
    assert resp["statusCode"] == 200 and body_of(resp) == view


def test_get_failed_session_200(ai_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "http_401")
    create()
    [item] = sessions(ai_env)
    view = body_of(get(item["sessionId"]))
    assert view["status"] == "FAILED" and view["card"] is None and view["trace"]


def _not_found_cases(table):
    sid = body_of(create())["sessionId"]
    expired = new_session_id()
    old = datetime.now(timezone.utc) - timedelta(days=31)
    svc.put_session(svc.build_session_item(session_id=expired, owner_id="u-owner", story="x", status="READY", created_at=old))
    return {"other_owner": (sid, OTHER), "missing": (new_session_id(), OWNER), "expired": (expired, OWNER),
            "malformed": ("ais_bad", OWNER), "not_ais": ("pln_01ABCDEFGHJKMNPQRSTVWXYZ01", OWNER)}


def test_get_404_same_body(ai_env, model_calls):
    cases = _not_found_cases(ai_env)
    before = (quota_count(ai_env), len(sessions(ai_env)), len(model_calls))
    resps = {k: get(sid, claims) for k, (sid, claims) in cases.items()}
    assert {(r["statusCode"], r["body"], json.dumps(r["headers"])) for r in resps.values()} == {
        (404, json.dumps({"error": {"code": "NOT_FOUND", "message": "찾을 수 없어요."}}, ensure_ascii=False), json.dumps(resps["missing"]["headers"]))}
    assert (quota_count(ai_env), len(sessions(ai_env)), len(model_calls)) == before


def test_malformed_id_does_not_read_db(ai_env, monkeypatch):
    monkeypatch.setattr(svc, "get_session", lambda *a, **k: pytest.fail("DB를 읽으면 안 된다"))
    assert get("not-a-session")["statusCode"] == 404
    assert turns("ais_x", {"expectedTurn": 1})["statusCode"] == 404


# ---------------------------------------------------------------- turns


def test_turns_same_turn_409_other_turn_200(ai_env, model_calls):
    view = body_of(create())
    before = (quota_count(ai_env), sessions(ai_env), len(model_calls))
    r = turns(view["sessionId"], {"expectedTurn": 1, "finish": True})
    assert r["statusCode"] == 409 and body_of(r)["error"]["code"] == "AI_SESSION_CLOSED"
    r = turns(view["sessionId"], {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "45분"}})
    assert r["statusCode"] == 409
    r = turns(view["sessionId"], {"expectedTurn": 2})
    assert r["statusCode"] == 200 and body_of(r) == view
    assert (quota_count(ai_env), sessions(ai_env), len(model_calls)) == before


def test_turns_failed_session_409(ai_env, monkeypatch):
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "bad_json")
    create()
    [item] = sessions(ai_env)
    assert turns(item["sessionId"], {"expectedTurn": 1})["statusCode"] == 409


@pytest.mark.parametrize("body", [
    None, {}, {"expectedTurn": 0}, {"expectedTurn": "1"}, {"expectedTurn": True},
    {"expectedTurn": 1, "answer": {"questionId": "q1"}},
    {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "a", "text": "b"}},
    {"expectedTurn": 1, "answer": {"questionId": "q1", "text": "가" * 101}},
    {"expectedTurn": 1, "answer": {"questionId": "q1", "skipped": False}},
    {"expectedTurn": 1, "finish": "yes"},
])
def test_turns_shape_400_before_404(ai_env, body):
    r = turns(new_session_id(), body)  # 없는 세션이어도 형태 오류가 먼저다(BE-Q77)
    assert r["statusCode"] == 400 and body_of(r)["error"]["code"] == "VALIDATION_ERROR"


def test_turns_404_same_body(ai_env, model_calls):
    cases = _not_found_cases(ai_env)
    bodies = {turns(sid, {"expectedTurn": 1}, claims)["body"] for sid, claims in cases.values()}
    assert bodies == {json.dumps({"error": {"code": "NOT_FOUND", "message": "찾을 수 없어요."}}, ensure_ascii=False)}
    assert len(model_calls) == 1


@pytest.mark.parametrize("status", ["WORKING", "ASKING"])
def test_turns_non_terminal_500_unchanged(ai_env, status, caplog, model_calls):
    sid = new_session_id()
    item = svc.build_session_item(session_id=sid, owner_id="u-owner", story="x", status=status, created_at=datetime.now(timezone.utc))
    svc.put_session(item)
    before = sessions(ai_env)
    r = turns(sid, {"expectedTurn": 1})
    assert r["statusCode"] == 500 and body_of(r)["error"]["code"] == "INTERNAL_ERROR"
    assert sessions(ai_env) == before and model_calls == [] and quota_count(ai_env) == 0
    assert "NON_TERMINAL_SESSION" in caplog.text
    g_resp = get(sid)
    assert g_resp["statusCode"] == 200 and body_of(g_resp)["status"] == status


def test_unknown_route_404(ai_env):
    assert ai_card.handler(event("DELETE /ai/card-sessions"), Ctx())["statusCode"] == 404


# ---------------------------------------------------------------- 초기화


def test_init_uses_ai_sdk_config(monkeypatch):
    from common import ddb

    monkeypatch.setattr(ai_card, "_initialized", False)
    monkeypatch.setenv("TABLE_NAME", "HaruTable")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    saved = ddb._table
    try:
        ai_card.init()
        cfg = ddb._table.meta.client.meta.config
        assert cfg.connect_timeout == 1 and cfg.read_timeout == 2 and cfg.retries["total_max_attempts"] == 2
        assert ai_card._initialized is True
    finally:
        ddb._table = saved


def test_graph_built_once():
    assert g.pipeline_graph() is g.pipeline_graph()
    assert llm.QUIET_LOGGERS
