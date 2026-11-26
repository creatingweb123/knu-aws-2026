"""레벨 0 프롬프트와 데이터 블록 (design §8.1, Requirement 10, BE-AI-03).

- 사연은 <story> 블록 안에만 넣는다. 블록 경계를 흉내 내는 태그는 '<'를 전각 '＜'로 바꿔 무력화한다.
  그 밖의 글자는 원문 그대로다(전송 전 마스킹은 BE-Q10 미결, 결정 전에는 하지 않는다).
- 원문 대조 근거(Sources)는 바꾸지 않은 원문이다.
- 재시도 메시지에는 실패한 응답 원문을 넣지 않고 오류 종류와 경로만 넣는다.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompts" / "day_card.md"
_TAG = re.compile(r"<(?=\s*/?\s*(?:story|answer)\b)", re.IGNORECASE)
FULLWIDTH_LT = "＜"


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def prompt_version() -> str:
    """day_card.md SHA-256 앞 12자(AiSession.promptVersion)."""
    return hashlib.sha256(system_prompt().encode("utf-8")).hexdigest()[:12]


def neutralize(story: str) -> str:
    return _TAG.sub(FULLWIDTH_LT, story)


def user_message(story: str) -> str:
    return "<story>\n" + neutralize(story) + "\n</story>"


def build_messages(story: str) -> list[BaseMessage]:
    return [SystemMessage(system_prompt()), HumanMessage(user_message(story))]


PLACES_RULE = "places는 최대 3곳이다. 공개 장소가 4곳 이상이면 사연에 나온 순서대로 앞의 3곳만 넣어라."


def retry_message(kind: str, paths: tuple[str, ...] | list[str]) -> HumanMessage:
    """실패 원문 없이 오류 종류와 경로만 알린다. places 배열 자체가 틀렸으면 장소 선택 규칙을 덧붙인다(BE-Q127).

    서버는 배열을 자르지 않는다. 재시도도 위반이면 6a 정책대로 502다(BE-Q91).
    """
    where = ", ".join(paths) if paths else "전체"
    what = "JSON 객체가 아니었다" if kind == "NOT_JSON" else "필드 규칙에 맞지 않았다"
    text = f"앞 응답이 형식에 맞지 않았다({what}: {where}). 같은 규칙으로 JSON 객체 하나만 다시 출력하라."
    if kind != "NOT_JSON" and "places" in paths:
        text += " " + PLACES_RULE
    return HumanMessage(text)


# ---------------------------------------------------------------------------
# 6b 에이전트 프롬프트 (design §12, BE-AI-03)
# ---------------------------------------------------------------------------

AGENT_PROMPT_FILE = Path(__file__).resolve().parents[1] / "prompts" / "day_card_agent.md"
DRAFT_MARK = "## 초안"


@lru_cache(maxsize=1)
def agent_prompt_text() -> str:
    return AGENT_PROMPT_FILE.read_text(encoding="utf-8")


def agent_system_prompt() -> str:
    """도구 사용 단계의 시스템 프롬프트(초안 절 제외)."""
    return agent_prompt_text().split(DRAFT_MARK)[0].rstrip() + "\n"


def agent_draft_instruction() -> str:
    return agent_prompt_text().split(DRAFT_MARK, 1)[1].strip()


def agent_prompt_version() -> str:
    return hashlib.sha256(agent_prompt_text().encode("utf-8")).hexdigest()[:12]


# 스키마 제한(common/validation.py AiCardDraft·AiPlaceDraft와 같은 값). 재시도 메시지에는 이 제한만 넣는다(BE-Q129).
SCHEMA_LIMITS: dict[str, str] = {
    "title": "1–40자", "summary": "1–120자", "reason": "1–300자", "question": "1–80자",
    "estimatedMinutes": "10–240 사이의 정수", "places": "최대 3곳", "name": "1–30자", "activity": "1–60자", "whyChosen": "0–120자",
}


def schema_limit(path: str) -> str:
    """경로의 마지막 필드 이름으로 제한 문구를 찾는다(places[0].name → name, places[2] → places)."""
    last = re.sub(r"\[\d+\]", "", path.rsplit(".", 1)[-1])
    return SCHEMA_LIMITS.get(last, "형식 규칙")


def agent_retry_text(kind: str, paths: tuple[str, ...] | list[str]) -> str:
    """에이전트 초안 재시도 메시지. 위반한 경로와 스키마 제한만 담는다. 실패한 응답 원문은 넣지 않는다(BE-Q129)."""
    if kind == "NOT_JSON":
        return "앞 응답이 JSON 객체가 아니었다. 설명 없이 JSON 객체 하나만 다시 출력하라."
    where = ", ".join(f"{p}({schema_limit(p)})" for p in paths) or "카드 전체"
    return f"앞 초안의 형식 규칙 위반: {where}. 위반한 필드만 규칙에 맞게 고쳐서 JSON 객체 하나만 다시 출력하라. 앞 응답을 그대로 반복하지 마라."


def agent_draft_messages(story: str, feedback: str | None = None) -> list[BaseMessage]:
    msgs: list[BaseMessage] = [SystemMessage(agent_system_prompt() + "\n" + agent_draft_instruction()), HumanMessage(user_message(story))]
    if feedback:
        msgs.append(HumanMessage(feedback))
    return msgs


def answer_block(text: str) -> str:
    return "<answer>\n" + neutralize(text) + "\n</answer>"
