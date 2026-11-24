"""요청 본문 검증 모델과 에러 경로 변환 (BE-PLAN-02, §3 공통 규칙).

문자열 길이는 양 끝 값을 포함한다. 타입은 strict로 검사해 "45" 같은 문자열 숫자나 true/1.5를
정수로 받아들이지 않는다(요구사항 3.3).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
