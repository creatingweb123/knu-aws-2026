"""원문 충실도 판정 find_not_in_source (BE-AI-06, docs/03-api-contract.md §3.2).

판정 규칙(BE-Q25 임시 기본안):
- target 텍스트를 공백으로 나눈 토큰마다 말미 조사를 한 번 떼어 낸다.
- 토큰이 근거 텍스트(공백·문장부호 제거, 소문자) 중 하나에 부분 문자열로 있으면 일치.
- 모든 토큰이 일치해야 통과. 하나라도 없으면 NotInSourceHit.
- 동의어는 넘겨받은 사전(테스트는 tests/fixtures/normalization.json)에 있는 것만 같은 표현으로 본다.

근거 텍스트는 항목별로 따로 대조한다. 그래서 근거를 추가하면 hit가 늘지 않는다(단조성).
순수 함수다. 입력을 바꾸지 않고 LLM·DB를 부르지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

# 말미 조사 사전. 긴 것부터 대조한다. 조사를 떼면 토큰이 짧아질 뿐이라
# 원래 토큰이 근거에 있으면 뗀 토큰도 반드시 있다(떼어서 hit가 생기지는 않는다).
PARTICLES: tuple[str, ...] = tuple(
    sorted(
        [
            "에서는", "에게서", "으로는", "으로도", "에서도",
            "에서", "에게", "한테", "으로", "까지", "부터", "처럼", "보다", "이랑", "하고", "마다",
            "은", "는", "이", "가", "을", "를", "에", "로", "의", "와", "과", "도", "만", "랑",
        ],
        key=len,
        reverse=True,
    )
)

_PUNCT = re.compile(r"[\s.,!?·…~'\"`“”‘’()\[\]{}<>「」『』:;/\\|\-_]+")


class Target(NamedTuple):
    path: str
    text: str | None


@dataclass(frozen=True)
class NotInSourceHit:
    path: str
    text: str


def normalize(text: str) -> str:
    """소문자화하고 공백·문장부호를 없앤다."""
    return _PUNCT.sub("", text).lower()


def strip_particle(token: str) -> str:
    """말미 조사 하나를 뗀다. 남는 글자가 2자 미만이면 떼지 않는다."""
    for p in PARTICLES:
        if token.endswith(p) and len(token) - len(p) >= 2:
            return token[: -len(p)]
    return token


def _synonym_rules(synonyms: Iterable[Sequence[str]] | None) -> list[tuple[re.Pattern[str], str]]:
    """동의어 묶음의 각 표현을 첫 표현(대표형)으로 바꾸는 규칙. 공백 차이는 무시한다."""
    rules: list[tuple[str, str]] = []
    for group in synonyms or ():
        words = [w for w in group if w and w.strip()]
        if len(words) < 2:
            continue
        canonical = normalize(words[0])
        rules.extend((w, canonical) for w in words[1:])
    rules.sort(key=lambda r: len(normalize(r[0])), reverse=True)
    compiled = []
    for variant, canonical in rules:
        chars = [re.escape(c) for c in normalize(variant)]
        compiled.append((re.compile(r"\s*".join(chars), re.IGNORECASE), canonical))
    return compiled


def _apply(text: str, rules: list[tuple[re.Pattern[str], str]]) -> str:
    for rx, canonical in rules:
        text = rx.sub(canonical, text)
    return text


def _tokens(text: str) -> list[str]:
    raw = [normalize(t) for t in text.split()]
    toks = [strip_particle(t) for t in raw if t]
    longer = [t for t in toks if len(t) >= 2]
    return longer or toks  # 1자 토큰은 더 긴 토큰이 있을 때만 무시한다


def find_not_in_source(
    sources: Sequence[str | None],
    targets: Sequence[Target | tuple[str, str | None]],
    synonyms: Iterable[Sequence[str]] | None = None,
) -> list[NotInSourceHit]:
    rules = _synonym_rules(synonyms)
    corpora = [normalize(_apply(s, rules)) for s in sources if s and s.strip()]
    hits: list[NotInSourceHit] = []
    for path, text in targets:
        if text is None or not text.strip():
            continue  # 빈 값은 판정하지 않는다(MISSING은 check_draft 몫)
        toks = _tokens(_apply(text, rules))
        if not toks:
            continue
        if not all(any(t in c for c in corpora) for t in toks):
            hits.append(NotInSourceHit(path, text))
    return hits
