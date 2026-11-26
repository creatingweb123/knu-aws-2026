"""결정적 검사: check_draft, Gate 판정, Final_Check (design §9, BE-AI-04, BE-Q88).

순수 함수다. LLM·DB를 부르지 않고 입력을 바꾸지 않는다. 1·2단계의 find_not_in_source·scan_privacy를 그대로 쓴다.
6b의 check_draft 도구와 submit_card 게이트도 이 함수들을 쓴다.

Report = {schemaErrors: [path], notInSource: [path], privacy: [{path, kind, severity}], missing: [path]}
경로는 작업 카드의 현재 순서 기준이다. 텍스트는 Report에 넣지 않는다.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from common.validation import CARD_SCALAR_FIELDS, AiCardDraft, loc_to_path
from domain.fidelity import Target, find_not_in_source
from domain.privacy import HIGH, scan_privacy

PRIVATE_PLACE = "PRIVATE_PLACE"
MISSING, NOT_IN_SOURCE, PRIVACY = "MISSING", "NOT_IN_SOURCE", "PRIVACY"
STRING_SCALARS = ("title", "summary", "reason", "question")
PLACE_TEXT_FIELDS = ("name", "activity", "whyChosen")
KIND_LABELS = {
    "PHONE": "연락처", "EMAIL": "연락처", "RRN": "주민번호", "UNIT": "동호수",
    "PLATE": "차량번호", "LOT": "번지", PRIVATE_PLACE: "비공개 장소",
}
# Final_Check 차단 사유 (BE-Q88)
SCHEMA_BLOCK, HIGH_BLOCK = "SCHEMA", "HIGH_PRIVACY"
PRIVATE_BLOCK, NIS_NAME_BLOCK, NIS_ACTIVITY_BLOCK = "PRIVATE_PLACE_IN_PLACES", "NIS_PLACE_NAME", "NIS_ACTIVITY_UNFLAGGED"


CARD_ORDER = ("title", "summary", "reason", "estimatedMinutes", "places", "question")


def public_card(card: dict[str, Any]) -> dict[str, Any]:
    """내부 키(_src)를 뺀 카드(필드 순서는 POST /plans와 같다)."""
    places = [{k: p.get(k) for k in PLACE_TEXT_FIELDS} for p in card.get("places") or [] if isinstance(p, dict)]
    return {k: (places if k == "places" else card.get(k)) for k in CARD_ORDER}


def text_fields(card: dict[str, Any]) -> dict[str, str]:
    """{경로: 문자열} — 카드의 모든 문자열 필드."""
    out = {f: card.get(f) for f in STRING_SCALARS if isinstance(card.get(f), str)}
    for i, p in enumerate(card.get("places") or []):
        if isinstance(p, dict):
            for f in PLACE_TEXT_FIELDS:
                if isinstance(p.get(f), str):
                    out[f"places[{i}].{f}"] = p[f]
    return out


def _schema_errors(card: dict[str, Any]) -> list[str]:
    try:
        AiCardDraft.model_validate(public_card(card))
    except ValidationError as e:
        return list(dict.fromkeys(loc_to_path(tuple(x["loc"])) for x in e.errors()))
    return []


def _missing(card: dict[str, Any]) -> list[str]:
    out = [f for f in CARD_SCALAR_FIELDS if card.get(f) is None]
    places = card.get("places") or []
    if not places:
        out.append("places")
    for i, p in enumerate(places):
        for f in ("name", "activity"):  # whyChosen은 Plan이 0자를 허용하므로 MISSING이 아니다
            if isinstance(p, dict) and p.get(f) is None:
                out.append(f"places[{i}].{f}")
    return out


def check_draft(card: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    targets = []
    for i, p in enumerate(card.get("places") or []):
        if isinstance(p, dict):
            targets += [Target(f"places[{i}].name", p.get("name")), Target(f"places[{i}].activity", p.get("activity"))]
    hits = find_not_in_source(sources, [t for t in targets if isinstance(t.text, str)])
    privacy = scan_privacy(text_fields(card))
    return {
        "schemaErrors": _schema_errors(card),
        "notInSource": [h.path for h in hits],
        "privacy": [{"path": h.path, "kind": h.kind, "severity": h.severity} for h in privacy],
        "missing": _missing(card),
    }


def gate_verdict(report: dict[str, Any]) -> bool:
    """통과하면 True. 스키마 오류, places의 NOT_IN_SOURCE(이름·활동), privacy HIGH 중 하나라도 있으면 거부."""
    return not (
        report["schemaErrors"]
        or any(p.startswith("places[") for p in report["notInSource"])
        or any(h["severity"] == HIGH for h in report["privacy"])
    )


def place_index(path: str) -> int | None:
    if not path.startswith("places["):
        return None
    return int(path[len("places["): path.index("]")])


def field_of(path: str) -> str:
    return path.rsplit(".", 1)[-1] if "." in path else path


_TYPE_ORDER = {MISSING: 0, NOT_IN_SOURCE: 1, PRIVACY: 2}


def _path_order(path: str) -> tuple:
    scalars = ["title", "summary", "reason", "estimatedMinutes"]
    if path in scalars:
        return (scalars.index(path),)
    if path == "places":
        return (4, -1)
    i = place_index(path)
    if i is not None:
        return (4, i, PLACE_TEXT_FIELDS.index(field_of(path)) if field_of(path) in PLACE_TEXT_FIELDS else 9)
    return (5,)  # question


def sort_flags(flags: list[dict[str, str]]) -> list[dict[str, str]]:
    uniq = {(f["path"], f["type"]): f for f in flags}
    return sorted(uniq.values(), key=lambda f: (_path_order(f["path"]), _TYPE_ORDER[f["type"]]))


def final_check(
    card: dict[str, Any],
    sources: list[str],
    *,
    masked: list[dict[str, Any]] | None = None,
    allowed_nis_activities: set[int] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """(flags, blocked). blocked가 비어 있어야 READY로 돌려줄 수 있다(design §9.4, BE-Q88).

    masked: Fallback이 가린 필드 [{src: 장소 Candidate 인덱스 또는 None, field}]. 장소는 `_src`로 최종 인덱스를 찾는다.
    allowed_nis_activities: Fallback이 KEPT_FLAGGED로 남긴 장소의 `_src`.
    """
    report = check_draft(card, sources)
    places = card.get("places") or []
    allowed = allowed_nis_activities or set()
    blocked: list[str] = []
    flags: list[dict[str, str]] = [{"path": p, "type": MISSING} for p in report["missing"]]

    if report["schemaErrors"]:
        blocked.append(SCHEMA_BLOCK)
    if any(h["severity"] == HIGH for h in report["privacy"]):
        blocked.append(HIGH_BLOCK)
    for h in report["privacy"]:
        i = place_index(h["path"])
        if h["kind"] == PRIVATE_PLACE and i is not None and field_of(h["path"]) in ("name", "activity"):
            blocked.append(PRIVATE_BLOCK)
        elif h["severity"] != HIGH:
            flags.append({"path": h["path"], "type": PRIVACY})
    for path in report["notInSource"]:
        i = place_index(path)
        if field_of(path) == "name":
            blocked.append(NIS_NAME_BLOCK)
        elif i is not None and places[i].get("_src", i) in allowed:
            flags.append({"path": path, "type": NOT_IN_SOURCE})
        else:
            blocked.append(NIS_ACTIVITY_BLOCK)

    by_src = {p.get("_src", i): i for i, p in enumerate(places)}
    for m in masked or []:
        if m.get("src") is None:
            flags.append({"path": m["field"], "type": PRIVACY})
        elif m["src"] in by_src:  # 가린 뒤 빠진 장소는 버린다
            flags.append({"path": f"places[{by_src[m['src']]}].{m['field']}", "type": PRIVACY})
    return sort_flags(flags), list(dict.fromkeys(blocked))
