"""AI 핸들러 테스트 공통: moto 테이블, Fake 환경, 이벤트, 가짜 Lambda context."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent import llm
from handlers import ai_card
from tests.unit.moto_table import haru_table, set_env

STORY = "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
OWNER = {"sub": "u-owner", "nickname": "지연"}
OTHER = {"sub": "u-other", "nickname": "수현"}


class Ctx:
    def __init__(self, remaining_ms: float = 25_000) -> None:
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self) -> float:
        return self.remaining_ms


@pytest.fixture
def ai_env(monkeypatch):
    """moto 테이블 + Fake 허용(로컬) + AGENT_MODE 미설정. 핸들러 초기화는 건너뛴다(moto 테이블을 그대로 쓴다)."""
    set_env(monkeypatch)
    for k in ("AGENT_MODE", "AWS_LAMBDA_FUNCTION_NAME", "LLM_API_KEY_PARAM", "AI_DAILY_SESSION_LIMIT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("FAKE_LLM_ALLOWED", "true")
    monkeypatch.setenv("STAGE", "local")
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "happy")
    monkeypatch.setattr(ai_card, "_initialized", True)
    llm.reset_key_cache()
    with haru_table() as t:
        yield t
    llm.reset_key_cache()


def event(route: str, claims: dict[str, str] | None = OWNER, body: Any = None, session_id: str | None = None, raw: str | None = None) -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": route,
        "headers": {},
        "pathParameters": {"sessionId": session_id} if session_id else None,
        "body": raw if raw is not None else (json.dumps(body, ensure_ascii=False) if body is not None else None),
        "isBase64Encoded": False,
        "requestContext": {"authorizer": {"jwt": {"claims": {"token_use": "id", **claims}}}} if claims else {},
    }


def create(story: str = STORY, claims: dict[str, str] = OWNER, ctx: Ctx | None = None) -> dict[str, Any]:
    return ai_card.handler(event("POST /ai/card-sessions", claims, {"story": story}), ctx or Ctx())


def get(session_id: str, claims: dict[str, str] = OWNER) -> dict[str, Any]:
    return ai_card.handler(event("GET /ai/card-sessions/{sessionId}", claims, session_id=session_id), Ctx())


def turns(session_id: str, body: Any, claims: dict[str, str] = OWNER) -> dict[str, Any]:
    return ai_card.handler(event("POST /ai/card-sessions/{sessionId}/turns", claims, body, session_id=session_id), Ctx())


def body_of(resp: dict[str, Any]) -> Any:
    return json.loads(resp["body"])


def sessions(table) -> list[dict[str, Any]]:
    return [i for i in table.scan()["Items"] if i["PK"].startswith("AISESSION#")]


def quota_count(table) -> int:
    items = [i for i in table.scan()["Items"] if i["PK"].startswith("AIQUOTA#")]
    return sum(int(i["sessions"]) for i in items)


def metric_names(out: str) -> list[tuple[str, Any]]:
    found = []
    for line in out.splitlines():
        if line.startswith("{") and '"_aws"' in line:
            doc = json.loads(line)
            name = doc["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"]
            found.append((name, doc[name]))
    return found
