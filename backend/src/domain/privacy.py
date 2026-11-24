"""개인정보 탐지 scan_privacy와 마스킹 (BE-AI-06).

- HIGH: 연락처(PHONE, EMAIL, RRN)와 동·호수(UNIT). 게이트에서 막고 마스킹하는 대상이다.
- MEDIUM: 차량번호(PLATE), 번지(LOT), 비공개 장소(PRIVATE_PLACE). 탐지만 한다(BE-Q22).
- PERSON_NAME(제3자 실명 후보)은 판정 방법이 정해지지 않아 구현하지 않는다(BE-Q26).
규칙 기반 탐지라 누락이 있을 수 있다. 로그에는 kind별 개수만 남긴다(BE-NFR-03).
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

HIGH = "HIGH"
MEDIUM = "MEDIUM"
MASK = "***"

Severity = Literal["HIGH", "MEDIUM"]


@dataclass(frozen=True)
class PrivacyHit:
    path: str
    kind: str
    severity: Severity


_ND = r"(?<!\d)"  # 앞이 숫자가 아님
_NDE = r"(?!\d)"  # 뒤가 숫자가 아님
_PLATE_LETTERS = "[가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주아바사자배하허호]"

PATTERNS: list[tuple[str, Severity, re.Pattern[str]]] = [
    ("PHONE", HIGH, re.compile(_ND + r"(?:01[016789]|0\d{1,2})[-.\s]?\d{3,4}[-.\s]?\d{4}" + _NDE)),
    ("EMAIL", HIGH, re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("RRN", HIGH, re.compile(_ND + r"\d{6}[-\s]?[1-4]\d{6}" + _NDE)),
    # 동/호수. "2호선", "1호점", "호수"는 제외한다.
    ("UNIT", HIGH, re.compile(_ND + r"(?:\d{1,4}\s*동\s*\d{1,4}\s*호|\d{1,4}\s*호(?!수|선|점))")),
    # 차량번호 용도 기호에 쓰이는 글자만 본다. "101동 1203호"가 차량번호로 잡히지 않게 한다.
    ("PLATE", MEDIUM, re.compile(_ND + r"\d{2,3}\s?" + _PLATE_LETTERS + r"\s?\d{4}" + _NDE)),
    ("LOT", MEDIUM, re.compile(_ND + r"\d{1,5}(?:-\d{1,4})?\s*번지")),
]

# 비공개 장소 사전. 공백 차이는 무시한다.
PRIVATE_PLACES: tuple[str, ...] = ("우리 집", "집 앞", "사무실 안", "내 방")
_PRIVATE_RX: list[re.Pattern[str]] = [
    re.compile(r"\s*".join(re.escape(c) for c in term.replace(" ", ""))) for term in PRIVATE_PLACES
] + [re.compile(r"[가-힣]{1,10}네\s*집")]  # "~네 집"


def _scan_text(text: str) -> list[tuple[str, Severity]]:
    found: list[tuple[str, Severity]] = []
    for kind, sev, rx in PATTERNS:
        found.extend((kind, sev) for _ in rx.finditer(text))
    for rx in _PRIVATE_RX:
        found.extend(("PRIVATE_PLACE", MEDIUM) for _ in rx.finditer(text))
    return found


def scan_privacy(texts: Mapping[str, str | None] | None) -> list[PrivacyHit]:
    """경로별 텍스트에서 탐지한 모든 항목. 빈 입력·None은 빈 목록."""
    hits: list[PrivacyHit] = []
    for path, text in (texts or {}).items():
        if not text:
            continue
        hits.extend(PrivacyHit(path, kind, sev) for kind, sev in _scan_text(text))
    return hits


def mask(text: str | None) -> str | None:
    """HIGH 탐지 부분만 가린다. 나머지는 그대로 둔다."""
    if not text:
        return text
    for _, sev, rx in PATTERNS:
        if sev == HIGH:
            text = rx.sub(MASK, text)
    return text


def count_by_kind(hits: list[PrivacyHit]) -> dict[str, int]:
    return dict(Counter(h.kind for h in hits))


def log_privacy_counts(hits: list[PrivacyHit], logger: logging.Logger | None = None) -> None:
    """kind별 개수만 기록한다. 원문·일치한 문자열은 남기지 않는다."""
    (logger or logging.getLogger(__name__)).info("privacy_hits %s", count_by_kind(hits))
