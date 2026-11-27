"""`POST /plans`의 AI 세션 지표 (docs/03 §3.3, design §16.2, BE-Q79).

순수 함수다. AI 패키지(langgraph·langchain·openai)를 import하지 않는다(PlansFunction 산출물에는 없다).
세션 선택(없음·만료·소유자·상태)은 plan_service가 하고, 여기서는 유효한 READY 세션만 받는다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from common.responses import parse_iso
from domain.fidelity import Target, find_not_in_source
from domain.privacy import scan_privacy

SCALARS = ("title", "summary", "reason", "estimatedMinutes", "question")
PLACE_FIELDS = ("name", "activity", "whyChosen")
SELF_REPAIR_ACTIONS = ("REWRITTEN", "REMOVED")


def _n(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _ms(iso: Any) -> int | None:
    if not isinstance(iso, str):
        return None
    try:
        return int(parse_iso(iso).timestamp() * 1000)
    except ValueError:
        return None


def place_targets(places: list[dict[str, Any]]) -> list[Target]:
    targets: list[Target] = []
    for i, p in enumerate(places):
        targets += [Target(f"places[{i}].name", p.get("name")), Target(f"places[{i}].activity", p.get("activity"))]
    return targets


def answer_sources(answers: list[dict[str, Any]]) -> list[str]:
    """계획자가 직접 입력한 답변(choice·text) 중 개인정보가 없는 것만 근거로 쓴다(docs/03 §3.2). 레벨 0은 빈 목록."""
    out = []
    for a in answers or []:
        if not isinstance(a, dict) or a.get("skipped"):
            continue
        text = a.get("text") if a.get("text") is not None else a.get("choice")
        if isinstance(text, str) and text and not scan_privacy({"answer": text}):
            out.append(text)
    return out


def answer_wait_ms(answers: list[dict[str, Any]]) -> int:
    total = 0
    for a in answers or []:
        asked, answered = _ms((a or {}).get("askedAt")), _ms((a or {}).get("answeredAt"))
        if asked is not None and answered is not None:
            total += max(0, answered - asked)
    return total


def _same(field: str, a: Any, b: Any) -> bool:
    a, b = _n(a), _n(b)
    if field == "whyChosen":  # 프론트가 null을 빈칸으로 보여 주므로 null과 ""를 같게 본다
        a, b = a or "", b or ""
    return a == b


def fields_edited(card: dict[str, Any] | None, final: dict[str, Any]) -> int:
    """READY 카드와 최종 요청 본문이 다른 비교 단위 수(스칼라 5개 + 장소마다 3개). 한쪽에 없는 장소의 값은 null."""
    card = card if isinstance(card, dict) else {}
    edited = sum(0 if _same(k, card.get(k), final.get(k)) else 1 for k in SCALARS)
    a_places = [p for p in card.get("places") or [] if isinstance(p, dict)]
    b_places = [p for p in final.get("places") or [] if isinstance(p, dict)]
    for i in range(max(len(a_places), len(b_places))):
        a = a_places[i] if i < len(a_places) else {}
        b = b_places[i] if i < len(b_places) else {}
        edited += sum(0 if _same(k, a.get(k), b.get(k)) else 1 for k in PLACE_FIELDS)
    return edited


def agent_mode(session: dict[str, Any]) -> str:
    if session.get("agentMode") == "AGENT":
        return "DEGRADED" if session.get("degraded") else "AGENT"
    return "PIPELINE"


def session_metrics(session: dict[str, Any], final: dict[str, Any], story: str, plan_created_at: str) -> dict[str, Any]:
    """유효한 READY 세션의 AI 지표. final은 POST /plans 요청 본문(title…question, places[]) 딕셔너리."""
    answers = [a for a in session.get("answers") or [] if isinstance(a, dict)]
    first_report = session.get("firstReport") if isinstance(session.get("firstReport"), dict) else {}
    flags = [f for f in session.get("flags") or [] if isinstance(f, dict)]
    notes = [n for n in session.get("notes") or [] if isinstance(n, dict)]
    targets = place_targets(final.get("places") or [])
    wait = answer_wait_ms(answers)
    created, ready, plan_ms = _ms(session.get("createdAt")), _ms(session.get("readyAt")), _ms(plan_created_at)
    out = {
        "agentMode": agent_mode(session),
        "addedNotInSourceOrAnswers": len(find_not_in_source([story, *answer_sources(answers)], targets)),
        "firstProposalNotInSource": len(first_report.get("notInSource") or []),
        "deliveredNotInSource": sum(1 for f in flags if f.get("type") == "NOT_IN_SOURCE"),
        "agentSelfRepairs": sum(1 for n in notes if n.get("action") in SELF_REPAIR_ACTIONS),
        "missingFirst": len(first_report.get("missing") or []),
        "missingDelivered": sum(1 for f in flags if f.get("type") == "MISSING"),
        "questionsAsked": len(answers),
        "questionsSkipped": sum(1 for a in answers if a.get("skipped")),
        "privacyDetected": int(_n(session.get("privacyDetected") or 0)),
        "agentWaitMs": max(0, ready - created - wait) if created is not None and ready is not None else 0,
        "answerWaitMs": wait,
        "editMs": max(0, plan_ms - ready) if plan_ms is not None and ready is not None else 0,
        "fieldsEditedAfterHandoff": fields_edited(session.get("card"), final),
        "modelCalls": int(_n(session.get("modelCalls") or 0)),
    }
    # 공급자 구분(fake·bedrock·openai_compat). 저장만 하고 API 응답 허용 목록(METRIC_FIELDS)에는 넣지 않는다.
    # scripts/report.py가 Fake 모델 데이터와 실제 모델 데이터를 섞지 않으려고 쓴다(BE-OBS-04).
    if isinstance(session.get("llmMode"), str) and session["llmMode"]:
        out["llmMode"] = session["llmMode"]
    return out
