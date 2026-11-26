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
