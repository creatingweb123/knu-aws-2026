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
from langchain_core.messages.tool import invalid_tool_call, tool_call
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


def _tool(name: str, **args: Any) -> dict[str, Any]:
    return {"kind": "tool", "calls": [{"name": name, "args": args}], "usage": True, "sleep": 0.0}


def _tools(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {"kind": "tool", "calls": [{"name": n, "args": a} for n, a in calls], "usage": True, "sleep": 0.0}


def _invalid(name: str, raw: str) -> dict[str, Any]:
    return {"kind": "invalid", "name": name, "raw": raw, "usage": True, "sleep": 0.0}


def _cardd(**over: Any) -> dict[str, Any]:
    return json.loads(_card(**over))


GOOD = _cardd()
NO_TIME = _cardd(estimatedMinutes=None)
ASK_TIME = {"path": "estimatedMinutes", "question": "빵집과 하천 벤치까지 산책은 얼마나 걸릴 예정이었나요?",
            "reason": "사연에 소요 시간이 없어요.", "options": ["30분", "45분", "1시간"], "allowFreeText": True}
NIS_CARD = _cardd(places=[{"name": "골목 빵집", "activity": "들러서 빵 사기", "whyChosen": None}, DEMO_PLACES[1]])
PRIVATE_CARD = _cardd(places=[{"name": "민지네 집", "activity": "들르기", "whyChosen": None}, DEMO_PLACES[0]])
SUBMIT_NOTE = [{"path": "places[0].name", "action": "REWRITTEN", "reason": "원문의 표현으로 적었어요.", "source": "STORY"}]

# 6b 에이전트 시나리오(design §20.1). 첫 단계는 draft(도구 없음), 그 뒤는 decide(도구 호출) 응답이다.
AGENT_SCENARIOS: dict[str, list[dict[str, Any]]] = {
    "happy": [_content(_card(estimatedMinutes=45)), _tool("submit_card", card=GOOD, notes=SUBMIT_NOTE)],
    "ask_once": [_content(json.dumps(NIS_CARD | {"estimatedMinutes": None}, ensure_ascii=False)),
                 _tool("check_draft", card=NO_TIME), _tool("ask_planner", **ASK_TIME),
                 _tool("submit_card", card=_cardd(estimatedMinutes=45), notes=SUBMIT_NOTE)],
    "no_tool_call": [_content(_card()), _content("정리를 마쳤어요."), _tool("submit_card", card=GOOD)],
    "no_tool_call_twice": [_content(_card()), _content("정리를 마쳤어요."), _content("정말 마쳤어요.")],
    "bad_json_args": [_content(_card()), _invalid("check_draft", '{"card": {'), _tool("submit_card", card=GOOD)],
    "unknown_tool": [_content(_card()), _tool("search_map", query="빵집"), _tool("submit_card", card=GOOD)],
    "parallel_calls": [_content(_card()), _tools(("check_draft", {"card": GOOD}), ("submit_card", {"card": GOOD})),
                       _tool("submit_card", card=GOOD)],
    "gate_reject_twice": [_content(_card()), _tool("submit_card", card=NIS_CARD), _tool("submit_card", card=NIS_CARD),
                          _tool("submit_card", card=GOOD)],
    "gate_reject_thrice": [_content(_card()), _tool("submit_card", card=NIS_CARD), _tool("submit_card", card=NIS_CARD),
                           _tool("submit_card", card=NIS_CARD)],
    "budget_exhausted": [_content(_card())] + [_tool("check_draft", card=GOOD)] * 6,
    "question_rejected": [_content(_card(estimatedMinutes=None)),
                          _tool("ask_planner", **(ASK_TIME | {"question": "010-1234-5678로 연락해도 될까요?"})),
                          _tool("ask_planner", **(ASK_TIME | {"path": "title"})),
                          _tool("submit_card", card=NO_TIME)],
    "ask_twice": [_content(_card(estimatedMinutes=None, question=None)), _tool("ask_planner", **ASK_TIME),
                  _tool("ask_planner", **(ASK_TIME | {"path": "question", "question": "무엇을 물어볼까요?", "options": []})),
                  _tool("submit_card", card=_cardd(estimatedMinutes=45))],
    "private_place_ask": [_content(json.dumps(PRIVATE_CARD, ensure_ascii=False)),
                          _tool("ask_planner", path="places[0].name", question="이 장소를 어떻게 할까요?", reason="비공개 장소예요.",
                                options=["빼기"], allowFreeText=False),
                          _tool("submit_card", card=_cardd(places=[DEMO_PLACES[0]]))],
    "privacy_card": [_content(_card(summary="010-1234-5678로 연락 주세요. 101동 1203호 앞에서 출발해요.")),
                     _tool("submit_card", card=_cardd(summary="010-1234-5678로 연락 주세요.")),
                     _tool("submit_card", card=_cardd(summary="101동 1203호 앞에서 출발해요.")),
                     _tool("submit_card", card=_cardd(summary="010-1234-5678"))],
    "decide_http_500": [_content(_card()), _raise("http_500")],
    "empty_draft_then_error": [_content("JSON이 아니에요."), _content("여전히 아니에요."), _raise("http_500")],
    "places_empty_then_error": [_content(_card(places=[])), _raise("http_500")],
    "timeout": [_raise("timeout")],
    "http_500": [_raise("http_500")],
    "http_401": [_raise("http_401")],
    "http_400": [_raise("http_400")],
    "slow_agent": [_content(_card(estimatedMinutes=45)), _tool("check_draft", card=GOOD), _tool("submit_card", card=GOOD)],
    "token_heavy": [_content(_card())] + [_tool("check_draft", card=_cardd(reason="가" * 300))] * 6,
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
    def for_scenario(cls, name: str, *, agent: bool = False) -> FakeScenarioChatModel:
        table = AGENT_SCENARIOS if agent else SCENARIOS
        if name not in table:
            raise ValueError("unknown fake scenario")
        return cls(scenario=name, steps=[dict(s) for s in table[name]])

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        """도구 이름 목록을 호출 kwargs로 넘겨 기록한다(P39). 실제 바인딩은 하지 않는다."""
        names = []
        for t in tools:
            fn = t.get("function", t) if isinstance(t, dict) else {}
            names.append(fn.get("name") if isinstance(fn, dict) else getattr(t, "__name__", str(t)))
        return self.bind(tool_names=names, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "haru-fake"

    def _next(self, messages: list[BaseMessage], kwargs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"messages": [(m.type, m.content) for m in messages], "kwargs": dict(kwargs), "index": self.index,
                           "tools": list(kwargs.get("tool_names") or [])})
        step = dict(self.steps[min(self.index, len(self.steps) - 1)], _n=self.index)
        self.index += 1
        return step

    @staticmethod
    def _result(step: dict[str, Any], messages: list[BaseMessage]) -> ChatResult:
        if step["kind"] == "raise":
            raise _error(step["error"])
        if step["kind"] == "tool":
            msg = AIMessage(content="", tool_calls=[tool_call(name=c["name"], args=c["args"], id=f"call_{step.get('_n', 0)}_{i}")
                                                    for i, c in enumerate(step["calls"])])
        elif step["kind"] == "invalid":
            msg = AIMessage(content="", invalid_tool_calls=[invalid_tool_call(name=step["name"], args=step["raw"], id="call_bad", error="bad json")])
        else:
            msg = AIMessage(content=step["text"])
        if step["usage"]:
            prompt_chars = sum(len(str(m.content)) for m in messages)
            out_n = len(step.get("text") or json.dumps(step.get("calls") or step.get("raw") or "", ensure_ascii=False)) // 2
            msg.usage_metadata = {"input_tokens": prompt_chars // 2, "output_tokens": out_n, "total_tokens": prompt_chars // 2 + out_n}
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
