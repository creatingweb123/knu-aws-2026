"""LLM 클라이언트 (Requirement 7, design §11–§14, BE-AI-02, BE-AI-05).

- LLM_PROVIDER=openai_compat: ChatOpenAI(Chat Completions, use_responses_api=False, max_retries=0, timeout 명시).
  호출마다 httpx.AsyncClient를 만들어 넘기고 닫는다(모듈 전역 모델을 asyncio.run 사이에 재사용하면
  "Event loop is closed"가 난다, 설계 단계에서 확인).
- 호출 1회 전체 시간은 asyncio.wait_for로 끊는다(BE-Q78). httpx read 타임아웃은 바이트 사이 시간이라 상한이 아니다.
  취소 완료와 AsyncClient 종료까지 기다리므로 반환이 deadline보다 조금 늦을 수 있다(SAVE_RESERVE_MS에 포함).
- LLM_PROVIDER=fake: Fake 채팅 모델. dev 스택·로컬에서만 허용한다(BE-Q86 권장안, 세 겹 차단의 런타임 부분).
- API 키: AWS는 SSM SecureString 이름(LLM_API_KEY_PARAM)만 받아 처음 필요할 때 한 번 읽어 캐시한다.
  읽기 실패는 캐시하지 않는다(KEY_READ_FAILED). 로컬은 LLM_API_KEY.
- 로그에는 분류 코드와 예외 클래스 이름만 남긴다. 키·URL·요청·응답·예외 메시지는 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from botocore.config import Config

_log = logging.getLogger("haru.ai")

FAKE, OPENAI_COMPAT = "fake", "openai_compat"
DEV_STACK = "haru-dev"
QUIET_LOGGERS = ("openai", "httpx", "httpcore", "langchain", "langchain_core", "langchain_openai", "langgraph", "langsmith",
                 "langgraph_checkpoint_aws",
                 # DEBUG에서 PutItem 요청·응답 본문(사연·카드)을 그대로 찍는다(6a 구현 중 test_ai_logging에서 확인)
                 "boto3", "botocore", "urllib3")

# 분류 코드 (design §11.3)
TIMEOUT, CONNECTION = "TIMEOUT", "CONNECTION"
HTTP_400, HTTP_401, HTTP_403, HTTP_429, HTTP_5XX, HTTP_OTHER = "HTTP_400", "HTTP_401", "HTTP_403", "HTTP_429", "HTTP_5XX", "HTTP_OTHER"
KEY_READ_FAILED, CONFIG, TIME_BUDGET, PROVIDER_RESPONSE = "KEY_READ_FAILED", "CONFIG", "TIME_BUDGET", "PROVIDER_RESPONSE"


class LlmError(Exception):
    """LLM_Error. code는 분류 코드, called는 공급자에 요청을 실제로 보냈는지."""

    def __init__(self, code: str, *, called: bool = False, reason: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.called = called
        self.reason = reason


def quiet_library_loggers() -> None:
    """요청 본문·헤더·URL을 찍을 수 있는 라이브러리 로거를 WARNING으로 고정한다(Requirement 13.3)."""
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "")
    if raw == "":
        return default
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(name)
    return value


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    base_url: str = ""
    model: str = ""
    key_param: str = ""
    connect_s: float = 2.0
    read_s: float = 8.0
    max_retries: int = 0
    max_tokens: int = 800
    temperature: float | None = 0.0
    extra_body: dict[str, Any] | None = None
    tool_choice: str = ""             # 6b bind_tools용으로 보관만 한다
    parallel_tool_calls: str = ""     # 6b bind_tools용으로 보관만 한다
    provider_label: str = ""
    fake_scenario: str = "happy"
    error: str | None = field(default=None)  # 설정 오류 사유 코드(있으면 호출 때 CONFIG)

    @property
    def call_max_s(self) -> float:
        return self.connect_s + self.read_s

    @property
    def mode(self) -> str:
        return self.provider if self.provider in (FAKE, OPENAI_COMPAT) else "invalid"


def fake_allowed(env: Mapping[str, str]) -> bool:
    """Fake는 FAKE_LLM_ALLOWED=true이고, 실제 함수 이름이 haru-dev-로 시작하거나 (함수 이름 없이) STAGE=local일 때만."""
    if env.get("FAKE_LLM_ALLOWED") != "true":
        return False
    fn = env.get("AWS_LAMBDA_FUNCTION_NAME")
    if fn is not None:
        return fn.startswith(f"{DEV_STACK}-")
    return env.get("STAGE") == "local"


def load_settings(env: Mapping[str, str] | None = None) -> LlmSettings:
    """환경 변수에서 설정을 읽는다. 오류는 예외가 아니라 error 사유로 담아 호출 때 CONFIG(→ 503)로 처리한다."""
    env = os.environ if env is None else env
    provider = env.get("LLM_PROVIDER", OPENAI_COMPAT)
    base: dict[str, Any] = {
        "provider": provider,
        "base_url": env.get("LLM_BASE_URL", ""),
        "model": env.get("LLM_MODEL", ""),
        "key_param": env.get("LLM_API_KEY_PARAM", ""),
        "tool_choice": env.get("LLM_TOOL_CHOICE", ""),
        "parallel_tool_calls": env.get("LLM_PARALLEL_TOOL_CALLS", ""),
        "provider_label": env.get("LLM_PROVIDER_LABEL", ""),
        "fake_scenario": env.get("FAKE_LLM_SCENARIO", "happy") or "happy",
    }
    error = None
    try:
        base["connect_s"] = _float(env, "LLM_CONNECT_TIMEOUT_S", 2.0)
        base["read_s"] = _float(env, "LLM_READ_TIMEOUT_S", 8.0)
        base["max_tokens"] = int(env.get("LLM_MAX_TOKENS", "") or 800)
        base["max_retries"] = int(env.get("LLM_MAX_RETRIES", "") or 0)
        raw_t = env.get("LLM_TEMPERATURE", "0")
        base["temperature"] = None if raw_t == "" else float(raw_t)
    except ValueError:
        error = "CONFIG_NUMBER"
    raw_extra = env.get("LLM_EXTRA_BODY", "")
    if raw_extra and error is None:
        try:
            extra = json.loads(raw_extra)
        except ValueError:
            extra = None
        if not isinstance(extra, dict):
            error = "CONFIG_EXTRA_BODY"
        else:
            base["extra_body"] = extra
    if error is None:
        if provider not in (FAKE, OPENAI_COMPAT):
            error = "CONFIG_PROVIDER"
        elif provider == FAKE and not fake_allowed(env):
            error = "CONFIG_FAKE_NOT_ALLOWED"
        elif provider == OPENAI_COMPAT and (not base["base_url"] or not base["model"]):
            error = "CONFIG_ENDPOINT"
        elif base.get("max_retries", 0) != 0:
            error = "CONFIG_RETRIES"  # 6a는 재시도 0만 허용한다(27초·12초 규칙)
    return LlmSettings(error=error, **base)


def sdk_config(env: Mapping[str, str] | None = None) -> Config:
    """AiCardFunction 전용 botocore 설정(BE-Q85). 다른 함수 설정(BE-Q48)은 바꾸지 않는다."""
    env = os.environ if env is None else env
    return Config(
        connect_timeout=float(env.get("AI_SDK_CONNECT_TIMEOUT_S", "1") or 1),
        read_timeout=float(env.get("AI_SDK_READ_TIMEOUT_S", "2") or 2),
        retries={"mode": "standard", "total_max_attempts": int(env.get("AI_SDK_MAX_ATTEMPTS", "2") or 2)},
    )


# ---------------------------------------------------------------------------
# API 키 (SSM SecureString, 성공만 캐시)
# ---------------------------------------------------------------------------

_key_cache: str | None = None
_ssm_client: Any = None


def _ssm() -> Any:
    global _ssm_client
    if _ssm_client is None:
        import boto3

        _ssm_client = boto3.client("ssm", config=sdk_config())
    return _ssm_client


def reset_key_cache() -> None:
    global _key_cache, _ssm_client
    _key_cache = None
    _ssm_client = None


def api_key(settings: LlmSettings, env: Mapping[str, str] | None = None) -> str:
    global _key_cache
    env = os.environ if env is None else env
    if settings.key_param:
        if _key_cache is None:
            try:
                _key_cache = _ssm().get_parameter(Name=settings.key_param, WithDecryption=True)["Parameter"]["Value"]
            except Exception as e:  # noqa: BLE001 - 없음·권한·복호화·스로틀·타임아웃 모두. 캐시하지 않는다
                _log.warning("ai_llm reason=KEY_READ_FAILED type=%s", type(e).__name__)
                raise LlmError(KEY_READ_FAILED) from None
        return _key_cache
    key = env.get("LLM_API_KEY", "")
    if not key:
        _log.warning("ai_llm reason=CONFIG_KEY")
        raise LlmError(CONFIG, reason="CONFIG_KEY")
    return key


# ---------------------------------------------------------------------------
# 호출과 오류 분류
# ---------------------------------------------------------------------------


def classify(exc: BaseException) -> str:
    import openai

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return TIMEOUT
    if isinstance(exc, openai.APITimeoutError):  # APIConnectionError의 하위 타입이라 먼저 본다
        return TIMEOUT
    if isinstance(exc, openai.APIConnectionError):
        return CONNECTION
    if isinstance(exc, openai.APIStatusError):
        code = exc.status_code
        if code == 401:
            return HTTP_401
        if code == 403:
            return HTTP_403
        if code == 429:
            return HTTP_429
        if code == 400:
            return HTTP_400
        if code >= 500:
            return HTTP_5XX
        return HTTP_OTHER
    return PROVIDER_RESPONSE


class LlmCaller:
    """요청 1건에 쓰는 호출기. Fake는 시나리오 진행 상태를 이 객체가 들고 있다.

    6b: budget(BudgetService)을 받으면 호출 직전에 예약한다(BE-Q97). 예약 예외(FenceLost·BudgetExhausted·
    ReservationUncertain)는 LlmError가 아니고 그대로 올라간다. tools를 받으면 bind_tools로 묶는다.
    call_index는 Fake 시나리오 순번(그래프 상태의 응답 받은 호출 수)이다. 재개·복구에서도 같은 응답을 고르기 위해서다.
    """

    def __init__(self, settings: LlmSettings, *, fake: Any = None, env: Mapping[str, str] | None = None, budget: Any = None) -> None:
        self.settings = settings
        self._env = os.environ if env is None else env
        self.fake = fake
        self.error = settings.error
        self.budget = budget
        self.calls_made = 0
        if settings.provider == FAKE and fake is None and self.error is None:
            from agent.fake_llm import FakeScenarioChatModel

            try:
                self.fake = FakeScenarioChatModel.for_scenario(settings.fake_scenario)
            except ValueError:
                self.error = "CONFIG_FAKE_SCENARIO"

    @property
    def mode(self) -> str:
        return self.settings.mode

    def remaining_calls(self) -> int | None:
        return None if self.budget is None else self.budget.remaining_calls()

    def _bind(self, model: Any, tools: list[Any] | None) -> Any:
        if not tools:
            return model
        kwargs: dict[str, Any] = {}
        if self.settings.parallel_tool_calls == "false":
            kwargs["parallel_tool_calls"] = False
        if self.settings.tool_choice:
            kwargs["tool_choice"] = self.settings.tool_choice
        return model.bind_tools(tools, **kwargs)

    def _reserve(self, messages: list[Any], tools: list[Any] | None) -> None:
        if self.budget is not None:
            from agent.budget import estimate_tokens

            self.last_reservation = self.budget.reserve(estimate_tokens(messages, tools))

    async def ainvoke(self, messages: list[Any], deadline_s: float, *, tools: list[Any] | None = None, call_index: int | None = None) -> Any:
        s = self.settings
        self.last_reservation = None
        if self.error:
            _log.warning("ai_llm reason=%s", self.error)
            raise LlmError(CONFIG, reason=self.error)
        if deadline_s <= 0:
            raise LlmError(TIME_BUDGET)
        from agent.fault import slow_delay_s

        delay = slow_delay_s(self._env)
        if s.provider == FAKE:
            if call_index is not None:
                self.fake.index = call_index
            self._reserve(messages, tools)
            self.calls_made += 1
            return await self._call(self._bind(self.fake, tools), messages, deadline_s, delay)
        key = api_key(s, self._env)  # 키 읽기 실패는 예약 전에(예약을 낭비하지 않는다)
        import httpx
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr

        timeout = httpx.Timeout(s.read_s, connect=s.connect_s)
        kwargs: dict[str, Any] = {}
        if s.temperature is not None:
            kwargs["temperature"] = s.temperature
        if s.extra_body:
            kwargs["extra_body"] = s.extra_body
        self._reserve(messages, tools)
        self.calls_made += 1
        async with httpx.AsyncClient(timeout=timeout) as http:
            model = ChatOpenAI(base_url=s.base_url, api_key=SecretStr(key), model=s.model, timeout=timeout, max_retries=0,
                               max_tokens=s.max_tokens, use_responses_api=False, http_async_client=http, **kwargs)
            return await self._call(self._bind(model, tools), messages, deadline_s, delay)

    @staticmethod
    async def _call(model: Any, messages: list[Any], deadline_s: float, delay_s: float = 0.0) -> Any:
        async def run() -> Any:
            if delay_s:
                await asyncio.sleep(delay_s)  # ai-slow(dev 전용). deadline 안에서 취소된다
            return await model.ainvoke(messages)

        try:
            return await asyncio.wait_for(run(), timeout=deadline_s)
        except LlmError:
            raise
        except Exception as e:  # noqa: BLE001 - 공급자 오류는 모두 LLM_Error(코드 없는 500 금지)
            code = classify(e)
            _log.warning("ai_llm reason=%s type=%s", code, type(e).__name__)
            raise LlmError(code, called=True) from None


def usage(messages: list[Any], msg: Any) -> tuple[int, int, bool]:
    """(입력 토큰, 출력 토큰, 추정 여부). usage가 없으면 글자 수 / 2(올림)로 추정한다(get_num_tokens 안 씀)."""
    meta = getattr(msg, "usage_metadata", None) or {}
    if meta.get("input_tokens") is not None and meta.get("output_tokens") is not None:
        return int(meta["input_tokens"]), int(meta["output_tokens"]), False
    in_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    out_chars = len(str(getattr(msg, "content", "")))
    return math.ceil(in_chars / 2), math.ceil(out_chars / 2), True
