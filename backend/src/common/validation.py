"""요청 본문 검증 모델과 에러 경로 변환 (BE-PLAN-02, §3 공통 규칙).

문자열 길이는 양 끝 값을 포함한다. 타입은 strict로 검사해 "45" 같은 문자열 숫자나 true/1.5를
정수로 받아들이지 않는다(요구사항 3.3).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_STRICT = ConfigDict(strict=True)


class PlaceIn(BaseModel):
    model_config = _STRICT

    name: Annotated[str, Field(min_length=1, max_length=30)]
    activity: Annotated[str, Field(min_length=1, max_length=60)]
    whyChosen: Annotated[str, Field(min_length=0, max_length=120)]


class AuthoringIn(BaseModel):
    model_config = _STRICT

    mode: Literal["MANUAL", "AI_EDITED"]
    durationMs: Annotated[int, Field(ge=0)]  # 상한 없음(BE-Q31)
    aiSessionId: str | None = None  # 문자열 여부만 본다. 세션 존재는 확인하지 않는다(요구사항 3.6)
    story: Annotated[str, Field(min_length=1, max_length=1000)]  # 두 모드 모두 필수


class PlanCreate(BaseModel):
    model_config = _STRICT

    title: Annotated[str, Field(min_length=1, max_length=40)]
    summary: Annotated[str, Field(min_length=1, max_length=120)]
    reason: Annotated[str, Field(min_length=1, max_length=300)]
    estimatedMinutes: Annotated[int, Field(ge=10, le=240)]
    places: Annotated[list[PlaceIn], Field(min_length=1, max_length=3)]
    question: Annotated[str, Field(min_length=1, max_length=80)]
    authoring: AuthoringIn


class RecordPut(BaseModel):
    """PUT /claims/{claimId}/record (3단계: 글만). `photo`는 핸들러가 따로 거부한다(BE-Q34)."""

    model_config = _STRICT

    letter: Annotated[str, Field(min_length=1, max_length=1000)]


class CompleteIn(BaseModel):
    """POST /claims/{claimId}/complete. 클라이언트가 보내는 완료는 TEXT_ONLY뿐이다(§3.4)."""

    model_config = _STRICT

    mode: Literal["TEXT_ONLY"]


# ---------------------------------------------------------------------------
# AI 하루 카드 (6a, docs/03 §3.2). AI 패키지 없이 import된다(PlansFunction도 쓴다).
# ---------------------------------------------------------------------------

_DRAFT = ConfigDict(strict=True, extra="ignore")


class AiPlaceDraft(BaseModel):
    """카드 초안의 장소. 값이 있으면 PlaceIn과 같은 길이 규칙, 없으면 null(MISSING)."""

    model_config = _DRAFT

    name: Annotated[str, Field(min_length=1, max_length=30)] | None = None
    activity: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    whyChosen: Annotated[str, Field(min_length=0, max_length=120)] | None = None


class AiCardDraft(BaseModel):
    """Card_Schema(design §3.1). Plan_Create_Schema(PlanCreate)와 달리 모든 값이 null일 수 있다."""

    model_config = _DRAFT

    title: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    summary: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    reason: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    estimatedMinutes: Annotated[int, Field(ge=10, le=240)] | None = None
    places: Annotated[list[AiPlaceDraft], Field(max_length=3)] = []
    question: Annotated[str, Field(min_length=1, max_length=80)] | None = None


CARD_SCALAR_FIELDS = ("title", "summary", "reason", "estimatedMinutes", "question")
PLACE_DRAFT_FIELDS = ("name", "activity", "whyChosen")
CARD_LIMITS: dict[str, int] = {
    "title": 40, "summary": 120, "reason": 300, "question": 80, "name": 30, "activity": 60, "whyChosen": 120,
}


def _norm_str(value: Any, keep_empty: bool) -> Any:
    if not isinstance(value, str):
        return value
    value = value.strip()
    return value if (value or keep_empty) else None


def normalize_card_payload(obj: dict[str, Any]) -> dict[str, Any]:
    """검증 전 정규화(BE-Q91). 정상적인 빈 값만 null로 바꾸고 위반은 고치지 않는다.

    - 알려진 키만 남기고 없는 키는 null. places가 없거나 null이면 [].
    - 문자열은 앞뒤 공백을 지우고 빈 문자열은 null(whyChosen만 ""를 그대로 둔다. Plan이 0자를 허용한다).
    - 타입·길이·범위·개수 위반, places가 배열이 아니거나 원소가 객체가 아닌 것은 그대로 둬 스키마 오류가 되게 한다.
    """
    out: dict[str, Any] = {k: _norm_str(obj.get(k), keep_empty=False) for k in CARD_SCALAR_FIELDS}
    places = obj.get("places")
    if places is None:
        out["places"] = []
    elif isinstance(places, list):
        out["places"] = [
            {k: _norm_str(p.get(k), keep_empty=(k == "whyChosen")) for k in PLACE_DRAFT_FIELDS} if isinstance(p, dict) else p
            for p in places
        ]
    else:
        out["places"] = places
    return out


class AiSessionCreate(BaseModel):
    """POST /ai/card-sessions."""

    model_config = _STRICT

    story: Annotated[str, Field(min_length=1, max_length=1000)]


class AiAnswer(BaseModel):
    """turns의 answer. choice·text·skipped 중 정확히 하나(§3.2). 세션 상태와의 대조는 핸들러가 한다."""

    model_config = _STRICT

    questionId: Annotated[str, Field(min_length=1, max_length=64)]
    choice: Annotated[str, Field(min_length=1, max_length=15)] | None = None
    text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    skipped: Literal[True] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "AiAnswer":
        if sum(v is not None for v in (self.choice, self.text, self.skipped)) != 1:
            raise ValueError("choice, text, skipped 중 하나만 보내 주세요.")
        return self


class AiTurn(BaseModel):
    """POST /ai/card-sessions/{sessionId}/turns."""

    model_config = _STRICT

    expectedTurn: Annotated[int, Field(ge=1)]
    answer: AiAnswer | None = None
    finish: bool | None = None
class Reply(BaseModel):
    """POST /inbox/{itemId}/reply (BE-INBOX-04). 길이는 코드 포인트 수, 앞뒤 공백은 자르지 않는다(FE-Q19)."""

    model_config = _STRICT

    text: Annotated[str, Field(min_length=1, max_length=100)]


# 필드 이름(경로의 마지막 이름 요소)별 사유 메시지
_FIELD_MESSAGES: dict[str, str] = {
    "title": "1–40자로 입력해 주세요.",
    "summary": "1–120자로 입력해 주세요.",
    "reason": "1–300자로 입력해 주세요.",
    "estimatedMinutes": "10–240 사이의 정수로 입력해 주세요.",
    "places": "장소는 1–3곳이어야 해요.",
    "name": "1–30자로 입력해 주세요.",
    "activity": "1–60자로 입력해 주세요.",
    "whyChosen": "0–120자로 입력해 주세요.",
    "question": "1–80자로 입력해 주세요.",
    "authoring": "작성 정보가 올바르지 않아요.",
    "mode": "MANUAL 또는 AI_EDITED여야 해요.",
    "durationMs": "0 이상의 정수로 입력해 주세요.",
    "aiSessionId": "문자열이어야 해요.",
    "story": "1–1000자로 입력해 주세요.",
    "letter": "1–1000자로 입력해 주세요.",
    "expectedTurn": "1 이상의 정수로 입력해 주세요.",
    "answer": "choice, text, skipped 중 하나만 보내 주세요.",
    "questionId": "1–64자로 입력해 주세요.",
    "choice": "1–15자로 입력해 주세요.",
    "text": "1–100자로 입력해 주세요.",
    "skipped": "true만 보낼 수 있어요.",
    "finish": "true 또는 false여야 해요.",
}
# 같은 필드 이름이 모델마다 뜻이 다를 때는 전체 경로로 먼저 찾는다.
_PATH_MESSAGES: dict[str, str] = {
    "mode": "TEXT_ONLY여야 해요.",  # POST /claims/{claimId}/complete
}
_REQUIRED_MESSAGE = "필수 항목이에요."
_GENERIC_MESSAGE = "형식이 올바르지 않아요."
ROOT_PATH = "body"


def loc_to_path(loc: tuple[int | str, ...]) -> str:
    """('places', 0, 'name') → 'places[0].name'. 빈 경로(본문 자체 오류)는 'body'."""
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or ROOT_PATH


def _message(loc: tuple[int | str, ...], err_type: str) -> str:
    if err_type == "missing":
        return _REQUIRED_MESSAGE
    if loc_to_path(loc) in _PATH_MESSAGES:
        return _PATH_MESSAGES[loc_to_path(loc)]
    names = [p for p in loc if isinstance(p, str)]
    if names and names[-1] in _FIELD_MESSAGES:
        return _FIELD_MESSAGES[names[-1]]
    return _GENERIC_MESSAGE


def to_details(err: ValidationError) -> dict[str, str]:
    """pydantic 오류를 `{"places[0].name": "사유"}` 형태로 바꾼다. 같은 경로는 첫 오류만 남긴다."""
    details: dict[str, str] = {}
    for e in err.errors():
        loc = tuple(e["loc"])
        path = loc_to_path(loc)
        details.setdefault(path, _message(loc, e["type"]))
    return details
