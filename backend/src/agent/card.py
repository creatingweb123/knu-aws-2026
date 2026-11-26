"""모델 응답 content → Candidate_Card (design §3.1, §8.2, BE-Q91).

response_format·strict에 기대지 않고 content의 첫 JSON 객체를 읽는다. 실패한 응답 원문은 결과에 담지 않는다
(유형과 오류 경로만, Requirement 9.4·13.1).
"""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple

from pydantic import ValidationError

from common.validation import AiCardDraft, loc_to_path, normalize_card_payload

NOT_JSON, SCHEMA = "NOT_JSON", "SCHEMA"
_FENCE = re.compile(r"```[A-Za-z0-9_-]*\s*\n?(.*?)```", re.DOTALL)


class ParseResult(NamedTuple):
    card: dict[str, Any] | None
    kind: str | None  # None이면 성공
    paths: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.kind is None


def content_text(content: Any) -> str:
    """AIMessage.content(문자열 또는 블록 목록)의 텍스트."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text") and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def extract_json_object(text: str) -> dict[str, Any] | None:
    """코드 펜스가 있으면 안쪽, 첫 '{'에서 JSON 값 하나를 읽는다. 객체가 아니면 None."""
    fence = _FENCE.search(text)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def validate_card(obj: dict[str, Any]) -> ParseResult:
    try:
        model = AiCardDraft.model_validate(normalize_card_payload(obj))
    except ValidationError as e:
        paths = tuple(dict.fromkeys(loc_to_path(tuple(x["loc"])) for x in e.errors()))
        return ParseResult(None, SCHEMA, paths)
    return ParseResult(model.model_dump(), None)


def parse_card(content: Any) -> ParseResult:
    obj = extract_json_object(content_text(content))
    if obj is None:
        return ParseResult(None, NOT_JSON)
    return validate_card(obj)
