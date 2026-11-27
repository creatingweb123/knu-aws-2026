"""규칙 노드와 결정적 폴백의 카드 수리 (design §9.1, §9.3, §10, BE-Q76, BE-Q88).

순수 함수다. 작업 카드의 장소는 `_src`(Candidate_Card에서의 인덱스)를 들고 다닌다.
- REMOVED 메모의 path는 Candidate_Card 인덱스(BE-Q13 제안안), 그 밖의 메모와 flags는 최종 카드 인덱스.
- 위반을 지우거나 플래그로 남길 뿐 조용히 통과시키지 않는다. 남은 위반은 Final_Check가 막는다.
"""

from __future__ import annotations

import copy
from typing import Any

from agent.tools import PRIVATE_PLACE, check_draft, field_of, place_index
from common.validation import CARD_LIMITS
from domain.privacy import mask, scan_privacy

REMOVED, KEPT_FLAGGED, STORY = "REMOVED", "KEPT_FLAGGED", "STORY"
REASON_PRIVATE = "비공개 장소라 뺐어요."
REASON_NOT_IN_SOURCE = "사연에 없는 장소라 뺐어요."
REASON_ACTIVITY = "사연에서 확인하지 못한 활동이에요. 확인해 주세요."


def with_src(card: dict[str, Any]) -> dict[str, Any]:
    """Candidate_Card를 작업 카드로 복사하고 장소마다 `_src`를 붙인다."""
    work = copy.deepcopy(card)
    work["places"] = [dict(p, _src=i) for i, p in enumerate(work.get("places") or [])]
    return work


def _note(path: str, action: str, reason: str) -> dict[str, str]:
    return {"path": path, "action": action, "reason": reason, "source": STORY}


def apply_rules(card: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """레벨 0 규칙 노드: 장소 이름·활동에 비공개 장소가 있으면 뺀다(질문 예산이 0이므로, docs/03 §3.2).

    비공개 장소가 다른 필드(whyChosen·title 등)에만 있으면 빼지 않는다(MEDIUM, PRIVACY 플래그, BE-Q22).
    """
    work = copy.deepcopy(card)
    kept, notes = [], []
    for p in work.get("places") or []:
        hits = scan_privacy({"name": p.get("name"), "activity": p.get("activity")})
        private = [h.path for h in hits if h.kind == PRIVATE_PLACE]
        if private:
            notes.append(_note(f"places[{p['_src']}].{private[0]}", REMOVED, REASON_PRIVATE))
        else:
            kept.append(p)
    work["places"] = kept
    return work, notes


def _mask_field(value: Any, field: str) -> tuple[Any, bool]:
    if not isinstance(value, str):
        return value, False
    masked = mask(value)
    if masked == value:
        return value, False
    limit = CARD_LIMITS.get(field)
    if limit is not None and len(masked) > limit:  # 이론상 "1호"(2자) → "***"(3자)
        masked = masked[:limit]
    return masked, True


def apply_fallback(
    card: dict[str, Any], sources: list[str]
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]], set[int]]:
    """결정적 폴백. (카드, 메모, 가린 필드 [{src, field}], KEPT_FLAGGED로 허용한 장소의 _src).

    1. 모든 문자열 필드의 HIGH 개인정보를 가린다.
    2. 다시 검사한다(가린 "***"는 원문에 없으므로 이름에 연락처가 있던 장소는 여기서 NOT_IN_SOURCE가 된다).
    3. 이름이 NOT_IN_SOURCE인 장소를 뺀다(REMOVED, Candidate 인덱스).
    4. 활동만 NOT_IN_SOURCE인 장소는 남기고 KEPT_FLAGGED(최종 인덱스).
    """
    work = copy.deepcopy(card)
    masked: list[dict[str, Any]] = []
    for f in ("title", "summary", "reason", "question"):
        work[f], changed = _mask_field(work.get(f), f)
        if changed:
            masked.append({"src": None, "field": f})
    for p in work.get("places") or []:
        for f in ("name", "activity", "whyChosen"):
            p[f], changed = _mask_field(p.get(f), f)
            if changed:
                masked.append({"src": p["_src"], "field": f})

    report = check_draft(work, sources)
    bad_names = {place_index(x) for x in report["notInSource"] if field_of(x) == "name"}
    bad_acts = {place_index(x) for x in report["notInSource"] if field_of(x) == "activity"}
    notes: list[dict[str, str]] = []
    kept: list[tuple[int, dict[str, Any]]] = []
    for i, p in enumerate(work.get("places") or []):
        if i in bad_names:
            notes.append(_note(f"places[{p['_src']}].name", REMOVED, REASON_NOT_IN_SOURCE))
        else:
            kept.append((i, p))
    allowed: set[int] = set()
    for final_i, (i, p) in enumerate(kept):
        if i in bad_acts:
            allowed.add(p["_src"])
            notes.append(_note(f"places[{final_i}].activity", KEPT_FLAGGED, REASON_ACTIVITY))
    work["places"] = [p for _, p in kept]
    return work, notes, masked, allowed
