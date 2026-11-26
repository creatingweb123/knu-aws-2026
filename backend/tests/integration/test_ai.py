"""AI 하루 카드 레벨 0 AWS 판정 (6a 작업 16, design §20.5). 실행·판정은 AWS 담당이다.

- test_T12_invalid_key (fault): **T12 판정은 이 테스트뿐이다**(BE-Q83). 함수가 LLM_PROVIDER=openai_compat이고
  LLM_API_KEY_PARAM이 있으며, 그 SecureString에 AWS 담당이 일부러 무효 키를 넣어 둔 상태에서 실제 공급자의 401을 받는다.
  전제가 아니면 사유를 남기고 skip한다. skip은 통과가 아니다(T12 미검증 유지).
- test_T12_aux_ssm_missing (fault): 파라미터가 없을 때 503·KEY_READ_FAILED. 보조 사례이며 T12 통과로 세지 않는다.
- test_ai_routes_fake: dev 스택 함수가 LLM_PROVIDER=fake일 때만. S4 연동·AWS 경로(IAM·SessionView·할당량) 확인용이고
  공급자 품질 근거가 아니다(BE-Q86). 결과 파일에 llmMode: fake.
사연은 합성 문장만 쓴다(실제 사용자 사연 금지, BE-Q6·BE-Q7·BE-Q10).
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import (
    STACK_NAME,
    _boto,
    ai_create,
    call,
    create_user,
    find_ai_sessions,
    function_env,
    query_items,
    save_result,
)

pytestmark = pytest.mark.integration

SYNTHETIC_STORY = "합성 사연: 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬고 싶었어요."
AI_FUNCTION = "AiCardFunction"


@pytest.fixture(scope="module")
def ai_env(stack):
    return function_env(STACK_NAME, AI_FUNCTION)


def _param_exists(name: str) -> bool:
    try:
        _boto("ssm").get_parameter(Name=name)  # 값은 복호화하지 않는다(WithDecryption 없음)
        return True
    except Exception as e:  # noqa: BLE001
        if getattr(e, "response", {}).get("Error", {}).get("Code") == "ParameterNotFound":
            return False
        raise


@pytest.mark.fault
def test_T12_invalid_key(stack, ai_env):
    if ai_env.get("LLM_PROVIDER") != "openai_compat" or not ai_env.get("LLM_API_KEY_PARAM"):
        pytest.skip("실제 공급자 없음(LLM_PROVIDER=openai_compat·LLM_API_KEY_PARAM 필요), T12 미검증")
    if not _param_exists(ai_env["LLM_API_KEY_PARAM"]):
        pytest.skip("키 파라미터가 없다. 무효 키를 넣은 SecureString이 필요하다(없음 사례는 test_T12_aux_ssm_missing), T12 미검증")
    sub, token = create_user(stack, "T12")
    status, body = ai_create(stack, token, SYNTHETIC_STORY)
    sessions = find_ai_sessions(stack, sub)
    plans = query_items(stack, f"USER#{sub}", "PLAN#")
    result = {"scenario": "T12", "llmMode": "openai_compat", "status": status, "body": body,
              "sessions": [{k: s.get(k) for k in ("status", "failureCode", "llmError", "modelCalls")} for s in sessions], "plans": len(plans)}
    path = save_result("T12", result)
    assert status == 503 and body["error"]["code"] == "AI_UNAVAILABLE", path
    assert len(sessions) == 1 and sessions[0]["status"] == "FAILED" and sessions[0]["llmError"] == "HTTP_401", path
    assert plans == [], path


@pytest.mark.fault
def test_T12_aux_ssm_missing(stack, ai_env):
    name = ai_env.get("LLM_API_KEY_PARAM")
    if ai_env.get("LLM_PROVIDER") != "openai_compat" or not name:
        pytest.skip("LLM_PROVIDER=openai_compat·LLM_API_KEY_PARAM이 있는 스택에서만")
    if _param_exists(name):
        pytest.skip("파라미터가 있다. 없는 이름으로 배포한 스택에서만 돈다(보조 사례)")
    sub, token = create_user(stack, "T12보조")
    status, body = ai_create(stack, token, SYNTHETIC_STORY)
    sessions = find_ai_sessions(stack, sub)
    path = save_result("T12-aux-ssm-missing", {"scenario": "T12-aux-ssm-missing", "countsAsT12": False, "llmMode": "openai_compat",
                                               "status": status, "llmError": [s.get("llmError") for s in sessions]})
    assert status == 503 and body["error"]["code"] == "AI_UNAVAILABLE", path
    assert [s.get("llmError") for s in sessions] == ["KEY_READ_FAILED"], path


def test_ai_routes_fake(stack, ai_env):
    if ai_env.get("LLM_PROVIDER") != "fake":
        pytest.skip("함수가 LLM_PROVIDER=fake인 dev 스택에서만(BE-Q86)")
    limit = int(ai_env.get("AI_DAILY_SESSION_LIMIT", "10"))
    sub, token = create_user(stack, "AI확인")
    _, other = create_user(stack, "AI남")
    log: dict = {"scenario": "ai-routes-fake", "llmMode": "fake", "note": "공급자 품질 근거 아님"}

    status, view = ai_create(stack, token, SYNTHETIC_STORY)
    log["create"] = status
    assert status == 200 and view["status"] == "READY" and view["turn"] == 1, view
    sid = view["sessionId"]
    assert call(stack, "GET", f"/ai/card-sessions/{sid}", token=token) == (200, view)
    closed = call(stack, "POST", f"/ai/card-sessions/{sid}/turns", token=token, body={"expectedTurn": 1})
    stale = call(stack, "POST", f"/ai/card-sessions/{sid}/turns", token=token, body={"expectedTurn": 2})
    foreign = call(stack, "GET", f"/ai/card-sessions/{sid}", token=other)
    missing = call(stack, "GET", "/ai/card-sessions/ais_01ZZZZZZZZZZZZZZZZZZZZZZZZ", token=other)
    log |= {"turnsSame": closed[0], "turnsOther": stale[0], "foreign": foreign[0], "missing": missing[0]}
    assert closed[0] == 409 and closed[1]["error"]["code"] == "AI_SESSION_CLOSED"
    assert stale == (200, view)
    assert foreign == missing and foreign[0] == 404

    statuses = [ai_create(stack, token, SYNTHETIC_STORY)[0] for _ in range(limit)]  # 이미 1건 썼다
    log["quota"] = statuses
    path = save_result("ai-routes-fake", log)
    assert statuses[:-1] == [200] * (limit - 1) and statuses[-1] == 429, path
    find_ai_sessions(stack, sub)  # 정리 대상 등록
