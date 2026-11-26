"""Fake 채팅 모델 (LLM_PROVIDER=fake, Requirement 8.1–8.3, design §11.4).

시나리오마다 정해진 응답이나 예외를 호출 순서대로 돌려준다. 예외는 실제 openai 예외 타입이라
오류 분류가 실제 ChatOpenAI와 같은 경로를 탄다. 호출마다 받은 메시지·인자를 calls에 남긴다.
`slow`는 asyncio.sleep으로 기다려 wait_for 취소가 그대로 적용된다.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

_REQ = httpx.Request("POST", "http://fake-llm.invalid/v1/chat/completions")

DEMO_PLACES = [
    {"name": "출근길 빵집", "activity": "들러서 빵 사기", "whyChosen": "출근길에 지나치던 곳이에요."},
    {"name": "하천 벤치", "activity": "벤치에 앉아 쉬기", "whyChosen": "저녁마다 걷던 길이에요."},
]


def _card(**over: Any) -> str:
    card = {
        "title": "이사 전, 마지막 동네 산책",
        "summary": "출근길 빵집에 들르고, 저녁마다 걷던 하천 벤치에 앉아 쉬고 싶었어요.",
        "reason": "이삿짐 정리가 길어져 마지막 산책을 하지 못했어요.",
        "estimatedMinutes": 45,
        "places": DEMO_PLACES,
        "question": "하천 벤치에 앉았을 때 어떤 풍경이 보였나요?",
    }
    card.update(over)
    return json.dumps(card, ensure_ascii=False)


def _status(code: int) -> openai.APIStatusError:
    resp = httpx.Response(code, request=_REQ, json={"error": {"message": "fake", "type": "fake"}})
    cls = {400: openai.BadRequestError, 401: openai.AuthenticationError, 403: openai.PermissionDeniedError,
           404: openai.NotFoundError, 429: openai.RateLimitError}.get(code, openai.InternalServerError)
    return cls("fake provider error", response=resp, body=None)


def _content(text: str, usage: bool = True, sleep: float = 0.0) -> dict[str, Any]:
    return {"kind": "content", "text": text, "usage": usage, "sleep": sleep}


def _raise(error: str) -> dict[str, Any]:
    return {"kind": "raise", "error": error}


SCENARIOS: dict[str, list[dict[str, Any]]] = {
    "happy": [_content(_card())],
    "not_in_source": [_content(_card(places=[{"name": "골목 빵집", "activity": "들러서 빵 사기", "whyChosen": None}, DEMO_PLACES[1]]))],
    "privacy_high": [_content(_card(summary="010-1234-5678로 연락 주세요. 101동 1203호 앞에서 출발해요."))],
    "private_place": [_content(_card(places=[{"name": "민지네 집", "activity": "놀러 가기", "whyChosen": None}, DEMO_PLACES[0]]))],
    "missing": [_content(_card(estimatedMinutes=None, question=None))],
    "all_places_removed": [_content(_card(places=[{"name": "골목 빵집", "activity": "커피 마시기", "whyChosen": None}]))],
    "bad_json": [_content("카드를 만들 수 없어요."), _content("여전히 JSON이 아니에요.")],
    "bad_json_then_ok": [_content("카드를 만들 수 없어요."), _content(_card())],
    "schema_error": [_content(_card(estimatedMinutes=300)), _content(_card(title="가" * 41))],
    "schema_error_then_ok": [_content(_card(estimatedMinutes="45")), _content(_card())],
    "timeout": [_raise("timeout")],
    "connection": [_raise("connection")],
    "http_400": [_raise("http_400")],
    "http_401": [_raise("http_401")],
    "http_429": [_raise("http_429")],
    "http_500": [_raise("http_500")],
    "slow": [_content(_card(), sleep=30.0)],
    "no_usage": [_content(_card(), usage=False)],
    "fenced_json": [_content("```json\n" + _card() + "\n```")],
}


def _error(name: str) -> Exception:
    if name == "timeout":
        return openai.APITimeoutError(request=_REQ)
    if name == "connection":
        return openai.APIConnectionError(request=_REQ)
    return _status(int(name.split("_")[1]))


class FakeScenarioChatModel(BaseChatModel):
    scenario: str = "happy"
    steps: list[dict[str, Any]] = Field(default_factory=list)
    calls: list[dict[str, Any]] = Field(default_factory=list)
    index: int = 0

    @classmethod
    def for_scenario(cls, name: str) -> FakeScenarioChatModel:
        if name not in SCENARIOS:
            raise ValueError("unknown fake scenario")
        return cls(scenario=name, steps=[dict(s) for s in SCENARIOS[name]])

    @property
    def _llm_type(self) -> str:
        return "haru-fake"

    def _next(self, messages: list[BaseMessage], kwargs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"messages": [(m.type, m.content) for m in messages], "kwargs": dict(kwargs)})
        step = self.steps[min(self.index, len(self.steps) - 1)]
        self.index += 1
        return step

    @staticmethod
    def _result(step: dict[str, Any], messages: list[BaseMessage]) -> ChatResult:
        if step["kind"] == "raise":
            raise _error(step["error"])
        msg = AIMessage(content=step["text"])
        if step["usage"]:
            prompt_chars = sum(len(str(m.content)) for m in messages)
            msg.usage_metadata = {"input_tokens": prompt_chars // 2, "output_tokens": len(step["text"]) // 2,
                                  "total_tokens": prompt_chars // 2 + len(step["text"]) // 2}
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        step = self._next(messages, kwargs)
        if step.get("sleep"):
            await asyncio.sleep(step["sleep"])
        return self._result(step, messages)

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        step = self._next(messages, kwargs)
        if step.get("sleep"):
            time.sleep(step["sleep"])
        return self._result(step, messages)
