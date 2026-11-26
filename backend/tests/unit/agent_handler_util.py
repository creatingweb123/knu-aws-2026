"""6b 핸들러 테스트 공통: moto(HaruTable + HaruAgentCheckpoints), AGENT_MODE=agent, Fake."""

from __future__ import annotations

import json
from typing import Any

import boto3
import pytest

from agent import checkpoint as ck
from agent import hooks, llm
from handlers import ai_agent, ai_card
from tests.unit.ai_handler_util import OWNER, Ctx, event
from tests.unit.moto_table import haru_table, set_env
from tests.unit.test_agent_checkpoint import TABLE, create_table

STORY = "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."


@pytest.fixture
def agent_env(monkeypatch):
    set_env(monkeypatch)
    for k in ("AWS_LAMBDA_FUNCTION_NAME", "LLM_API_KEY_PARAM", "AI_DAILY_SESSION_LIMIT", "FAULT_INJECT", "AGENT_TEST_HOOKS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local", "FAKE_LLM_SCENARIO": "happy",
                 "AGENT_MODE": "agent"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(ai_card, "_initialized", True)
    llm.reset_key_cache()
    with haru_table() as t:
        c = boto3.client("dynamodb", region_name="ap-northeast-2")
        create_table(c)
        ai_agent.use_store(ck.CheckpointStore(TABLE, region_name="ap-northeast-2"))
        hooks.HOOK = None
        yield t
    hooks.HOOK = None
    ai_agent.use_store(None)


def body_of(resp):
    return json.loads(resp["body"])


def create(story: str = STORY, claims=OWNER, ctx=None):
    return ai_card.handler(event("POST /ai/card-sessions", claims, {"story": story}), ctx or Ctx())


def turns(sid: str, body: Any, claims=OWNER, ctx=None):
    return ai_card.handler(event("POST /ai/card-sessions/{sessionId}/turns", claims, body, session_id=sid), ctx or Ctx())


def get(sid: str, claims=OWNER):
    return ai_card.handler(event("GET /ai/card-sessions/{sessionId}", claims, session_id=sid), Ctx())


def session(table, sid: str) -> dict[str, Any]:
    from domain import ai_session_service as svc

    return table.get_item(Key=svc.session_key(sid))["Item"]


def only_session(table) -> dict[str, Any]:
    items = [i for i in table.scan()["Items"] if i["PK"].startswith("AISESSION#")]
    assert len(items) == 1
    return items[0]


def ckpt_items(sid: str) -> list[dict[str, Any]]:
    c = boto3.client("dynamodb", region_name="ap-northeast-2")
    return [i for i in c.scan(TableName=TABLE)["Items"] if sid in i["PK"]["S"]]
