"""6b 도구 정의·검증·모델용 보고서 (design §10.4–§10.6, §11, BE-Q115·BE-Q116·BE-Q123).

순수 함수다. 6a tools.py(check_draft·gate_verdict·final_check)를 그대로 쓰고 바꾸지 않는다.
모델에게 돌려주는 ToolMessage에는 경로·유형·개수만 넣고 사연·카드 문자열을 되풀이하지 않는다(Req 8.8).
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, ValidationError

from agent import tools
from agent.card import validate_card
from domain.privacy import scan_privacy

CHECK, ASK, SUBMIT = "check_draft", "ask_planner", "submit_card"
TOOL_NAMES = (CHECK, ASK, SUBMIT)
MAX_QUESTIONS = 2
MAX_CHECKS = 4          # 최초 자동 검사 + 모델 요청 검사(BE-Q98)
MAX_GATE_REJECTS = 2    # 세 번째 거부 → fallback
Q_TEXT_MAX, Q_REASON_MAX, OPT_MAX, OPTS_MAX = 60, 80, 15, 4
PRIVATE_OPTION = "장소에서 빼기"
NOTE_REASON_MAX = 60
SAFE_NOTE_REASON = "카드를 원문에 맞게 고쳤어요."

# Tool_Error 코드
ONE_TOOL_PER_TURN, INVALID_ARGS, UNKNOWN_TOOL = "ONE_TOOL_PER_TURN", "INVALID_ARGS", "UNKNOWN_TOOL"
QUESTION_REJECTED, GATE_REJECTED, CHECK_LIMIT = "QUESTION_REJECTED", "GATE_REJECTED", "CHECK_LIMIT"


class CheckDraftArgs(BaseModel):
    """카드 초안을 결정적으로 검사한다. 원문에 없는 장소·활동, 개인정보, 빈칸, 형식 오류 경로를 돌려준다."""

    card: dict[str, Any] = Field(description="title, summary, reason, estimatedMinutes, places, question")


class AskPlannerArgs(BaseModel):
    """계획자에게 꼭 필요한 빈칸 하나를 객관식으로 묻는다. 이번 턴이 끝난다."""

    path: str = Field(description="카드 필드 경로. 예: estimatedMinutes, places, places[0].name")
    question: str = Field(description="60자 이하 질문")
    reason: str = Field(description="왜 묻는지 한 문장")
    options: list[str] = Field(default_factory=list, description="0–4개, 각 15자 이하")
    allowFreeText: bool = Field(default=True, description="직접 입력 허용 여부")


class SubmitCardArgs(BaseModel):
    """정리가 끝난 카드를 제출한다. 서버가 다시 검사해 위반이 남으면 거절한다."""

    card: dict[str, Any]
    notes: list[dict[str, Any]] = Field(default_factory=list)


ARGS = {CHECK: CheckDraftArgs, ASK: AskPlannerArgs, SUBMIT: SubmitCardArgs}


def tool_specs(names: tuple[str, ...] | list[str] = TOOL_NAMES) -> list[dict[str, Any]]:
    out = []
    for n in names:
        spec = convert_to_openai_tool(ARGS[n])
        spec["function"]["name"] = n
        out.append(spec)
    return out


def tools_for(*, questions: int, finish_requested: bool, last_call: bool) -> tuple[str, ...]:
    """질문 2개·finish·마지막 호출이면 ask_planner를 뺀다(Req 8.2, P39)."""
    if questions >= MAX_QUESTIONS or finish_requested or last_call:
        return (CHECK, SUBMIT)
    return TOOL_NAMES


def tool_error(code: str, **extra: Any) -> str:
    return json.dumps({"error": code, **extra}, ensure_ascii=False)


def parse_args(name: str, args: Any) -> tuple[Any, str | None]:
    if name not in ARGS:
        return None, UNKNOWN_TOOL
    try:
        return ARGS[name].model_validate(args if isinstance(args, dict) else {}), None
    except ValidationError:
        return None, INVALID_ARGS


# ---------------------------------------------------------------------------
# 검사 보고서 (모델용)
# ---------------------------------------------------------------------------


def report_for_model(report: dict[str, Any]) -> str:
    """경로·유형만 담은 JSON(BE-Q115). 개인정보는 유형 이름만."""
    return json.dumps({
        "schemaErrors": list(report.get("schemaErrors") or []),
        "notInSource": list(report.get("notInSource") or []),
        "privacy": [{"path": h["path"], "kind": h["kind"], "severity": h["severity"]} for h in report.get("privacy") or []],
        "missing": list(report.get("missing") or []),
    }, ensure_ascii=False)


def valid_candidate(card: Any) -> dict[str, Any] | None:
    """Card_Schema를 통과하고 정보가 하나라도 있는 카드(BE-Q99·BE-Q122). 정보 없는 카드(전 필드 null, 장소 0)는 None.

    places만 빈 카드는 유효하다(6a와 같이 MISSING(places)).
    """
    if not isinstance(card, dict):
        return None
    r = validate_card(card)
    if not r.ok:
        return None
    c = r.card
    has_scalar = any(c.get(k) is not None for k in ("title", "summary", "reason", "estimatedMinutes", "question"))
    if not has_scalar and not c.get("places"):
        return None
    return c


EMPTY_CARD = {"title": None, "summary": None, "reason": None, "estimatedMinutes": None, "places": [], "question": None}


# ---------------------------------------------------------------------------
# 질문 검증 (design §11.1, BE-Q123)
# ---------------------------------------------------------------------------

_PLACE_PATH = re.compile(r"^places\[(\d+)\]\.(name|activity)$")


def allowed_path(path: str, card: dict[str, Any] | None) -> bool:
    if path in ("estimatedMinutes", "places", "question"):
        return True
    m = _PLACE_PATH.match(path)
    if not m:
        return False
    return int(m.group(1)) < len((card or {}).get("places") or [])


def validate_question(args: AskPlannerArgs, *, asked_paths: list[str], questions: int, finish_requested: bool,
                      card: dict[str, Any] | None) -> str | None:
    """거부 사유 코드 또는 None(수락)."""
    if finish_requested:
        return "FINISH_REQUESTED"
    if questions >= MAX_QUESTIONS:
        return "QUESTION_LIMIT"
    if args.path in asked_paths:
        return "SAME_PATH"
    if not allowed_path(args.path, card):
        return "PATH_NOT_ALLOWED"
    if not (1 <= len(args.question) <= Q_TEXT_MAX):
        return "QUESTION_LENGTH"
    if not (1 <= len(args.reason) <= Q_REASON_MAX):
        return "REASON_LENGTH"
    if len(args.options) > OPTS_MAX or any(not (1 <= len(o) <= OPT_MAX) for o in args.options):
        return "OPTIONS"
    if not args.options and not args.allowFreeText:
        return "NO_ANSWER_POSSIBLE"
    texts = {"question": args.question, "reason": args.reason, **{f"options[{i}]": o for i, o in enumerate(args.options)}}
    if scan_privacy(texts):
        return "PRIVACY"
    return None


def accepted_question(args: AskPlannerArgs, *, number: int, report: dict[str, Any] | None) -> dict[str, Any]:
    """서버가 questionId를 매기고(q1, q2) 비공개 장소 질문의 선택지를 고정한다(BE-Q116)."""
    q = {"questionId": f"q{number}", "path": args.path, "text": args.question, "reason": args.reason,
         "options": list(args.options), "allowFreeText": bool(args.allowFreeText)}
    if is_private_place_path(args.path, report):
        q["options"] = [PRIVATE_OPTION]
        q["allowFreeText"] = True
    return q


def is_private_place_path(path: str, report: dict[str, Any] | None) -> bool:
    m = _PLACE_PATH.match(path)
    if not m or m.group(2) != "name":
        return False
    return any(h["kind"] == tools.PRIVATE_PLACE and tools.place_index(h["path"]) == int(m.group(1))
               for h in (report or {}).get("privacy") or [])


# ---------------------------------------------------------------------------
# 답변 (design §11.2–§11.3)
# ---------------------------------------------------------------------------


def answer_text(answer: dict[str, Any]) -> str | None:
    if answer.get("skipped"):
        return None
    v = answer.get("text") if answer.get("text") is not None else answer.get("choice")
    return v if isinstance(v, str) and v else None


def answer_has_privacy(answer: dict[str, Any]) -> bool:
    t = answer_text(answer)
    return bool(t and scan_privacy({"answer": t}))


def sources_for(story: str, answers: list[dict[str, Any]]) -> list[str]:
    """사연 + 개인정보 없는 답변(6a ai_metrics.answer_sources와 같은 규칙)."""
    out = [story]
    for a in answers:
        t = answer_text(a)
        if t and not a.get("privacy"):
            out.append(t)
    return out


def answer_for_model(answer: dict[str, Any], question: dict[str, Any]) -> str:
    if answer.get("privacy"):
        return json.dumps({"questionId": question["questionId"], "path": question["path"], "withheld": True,
                           "note": "이 답변에는 개인정보가 있어 쓰지 말 것. 해당 값은 null로 둔다."}, ensure_ascii=False)
    if answer.get("skipped"):
        return json.dumps({"questionId": question["questionId"], "path": question["path"], "skipped": True,
                           "note": "건너뛰었다. 해당 값은 null(MISSING)로 둔다."}, ensure_ascii=False)
    from agent.prompt import answer_block

    return json.dumps({"questionId": question["questionId"], "path": question["path"], "usable": True,
                       "answer": answer_block(answer_text(answer) or "")}, ensure_ascii=False)


def apply_private_place_answer(card: dict[str, Any] | None, question: dict[str, Any], answer: dict[str, Any]
                               ) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """비공개 장소 질문의 답을 결정적으로 반영한다(BE-Q116). (새 카드, 메모) — 해당 없으면 (card, None)."""
    m = _PLACE_PATH.match(question.get("path", ""))
    if not card or not m or question.get("options") != [PRIVATE_OPTION]:
        return card, None
    i = int(m.group(1))
    places = list(card.get("places") or [])
    if i >= len(places):
        return card, None
    if answer.get("choice") == PRIVATE_OPTION:
        new = dict(card, places=places[:i] + places[i + 1:])
        return new, {"path": f"places[{i}].name", "action": "REMOVED", "reason": "계획자가 장소에서 뺐어요.", "source": "ANSWER"}
    t = answer.get("text")
    if isinstance(t, str) and t and not answer.get("privacy") and len(t) <= 30:
        places[i] = dict(places[i], name=t)
        return dict(card, places=places), {"path": f"places[{i}].name", "action": "REWRITTEN",
                                           "reason": "계획자 답변으로 장소 이름을 바꿨어요.", "source": "ANSWER"}
    return card, None


# ---------------------------------------------------------------------------
# notes 검증 (design §10.6)
# ---------------------------------------------------------------------------


def clean_model_notes(notes: list[Any], card: dict[str, Any], answers: list[dict[str, Any]]) -> list[dict[str, str]]:
    """모델 메모는 REWRITTEN·ASKED이고 경로가 최종 카드에 있을 때만 남긴다. source는 서버가 다시 정한다."""
    answer_texts = [answer_text(a) for a in answers if not a.get("privacy")]
    answer_texts = [t for t in answer_texts if t]
    fields = tools.text_fields(card)
    out = []
    for n in notes or []:
        if not isinstance(n, dict) or n.get("action") not in ("REWRITTEN", "ASKED"):
            continue
        path = n.get("path")
        if not isinstance(path, str) or not _path_exists(path, card):
            continue
        value = fields.get(path) if path in fields else (None if path != "estimatedMinutes" else str(card.get(path)))
        source = "ANSWER" if value and any(t in value or value in t for t in answer_texts) else "STORY"
        reason = n.get("reason") if isinstance(n.get("reason"), str) else ""
        reason = reason[:NOTE_REASON_MAX] or SAFE_NOTE_REASON
        if scan_privacy({"reason": reason}):
            reason = SAFE_NOTE_REASON
        out.append({"path": path, "action": n["action"], "reason": reason, "source": source})
    return out


def _path_exists(path: str, card: dict[str, Any]) -> bool:
    if path in ("title", "summary", "reason", "estimatedMinutes", "question", "places"):
        return True
    m = re.match(r"^places\[(\d+)\]\.(name|activity|whyChosen)$", path)
    return bool(m) and int(m.group(1)) < len(card.get("places") or [])


# ---------------------------------------------------------------------------
# 한 응답의 도구 호출 처리 (design §10.4)
# ---------------------------------------------------------------------------


def split_tool_calls(msg: Any) -> tuple[dict[str, Any] | None, list[Any]]:
    """(실행할 호출 하나 또는 None, 오류 ToolMessage 목록).

    응답의 호출 순서(tool_calls 다음 invalid_tool_calls)에서 첫 번째만 후보다. 첫 번째가 형식 오류·모르는 도구·인자 오류면
    그것도 Tool_Error다. 나머지 tool_call_id마다 ONE_TOOL_PER_TURN을 붙인다. 실행할 호출의 ToolMessage는 도구 노드가 붙인다.
    그래서 모든 tool_call_id에 ToolMessage가 정확히 하나다(P40).
    """
    from langchain_core.messages import ToolMessage

    entries: list[tuple[str, str, Any, bool]] = []  # (id, name, args, valid_json)
    for c in getattr(msg, "tool_calls", None) or []:
        entries.append((c.get("id") or "", c.get("name") or "", c.get("args"), True))
    for c in getattr(msg, "invalid_tool_calls", None) or []:
        entries.append((c.get("id") or "", c.get("name") or "", None, False))
    errors: list[Any] = []
    chosen = None
    for i, (cid, name, args, valid) in enumerate(entries):
        if i > 0:
            errors.append(ToolMessage(content=tool_error(ONE_TOOL_PER_TURN), tool_call_id=cid, name=name or "unknown"))
            continue
        if not valid:
            errors.append(ToolMessage(content=tool_error(INVALID_ARGS, hint="JSON 인자로 다시 호출하라"), tool_call_id=cid, name=name or "unknown"))
            continue
        parsed, err = parse_args(name, args)
        if err:
            hint = "허용된 도구는 check_draft, ask_planner, submit_card다" if err == UNKNOWN_TOOL else "인자 형식을 확인하라"
            errors.append(ToolMessage(content=tool_error(err, hint=hint), tool_call_id=cid, name=name or "unknown"))
            continue
        chosen = {"id": cid, "name": name, "args": parsed.model_dump()}
    return chosen, errors
