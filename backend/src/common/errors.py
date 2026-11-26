"""API 에러 코드와 예외 (docs/03-api-contract.md §3.6).

핸들러와 서비스는 ApiError를 던지기만 하고, responses.error_response가 에러 형식으로 바꾼다.
"""

from __future__ import annotations

VALIDATION_ERROR = "VALIDATION_ERROR"
UNAUTHORIZED = "UNAUTHORIZED"
NOT_FOUND = "NOT_FOUND"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
TRY_AGAIN = "TRY_AGAIN"
# 3단계(이어받기·포기·완료)
FORBIDDEN = "FORBIDDEN"
ALREADY_CLAIMED = "ALREADY_CLAIMED"
CANNOT_CLAIM_OWN_PLAN = "CANNOT_CLAIM_OWN_PLAN"
CLAIM_NOT_ACTIVE = "CLAIM_NOT_ACTIVE"
RECORD_REQUIRED = "RECORD_REQUIRED"
# 6a단계(AI 하루 카드, §3.2). AI_SESSION_BUSY는 6b 턴 잠금용이라 6a에서는 쓰지 않는다.
AI_QUOTA_EXCEEDED = "AI_QUOTA_EXCEEDED"
AI_SESSION_CLOSED = "AI_SESSION_CLOSED"
AI_SESSION_BUSY = "AI_SESSION_BUSY"
AI_INVALID_OUTPUT = "AI_INVALID_OUTPUT"
AI_UNAVAILABLE = "AI_UNAVAILABLE"
# BE-Q23: 예기치 못한 서버 오류의 코드가 §3.6에 없다. 확정 전까지 임시로 쓴다.
INTERNAL_ERROR = "INTERNAL_ERROR"

# 지금까지 구현한 단계에서 쓰는 코드와 HTTP 상태. §3.6과 같은 조합만 쓴다(요구사항(1·2단계) 11.7).
CODE_STATUS: dict[str, int] = {
    VALIDATION_ERROR: 400,
    RECORD_REQUIRED: 400,
    UNAUTHORIZED: 401,
    FORBIDDEN: 403,
    NOT_FOUND: 404,
    ALREADY_CLAIMED: 409,
    CANNOT_CLAIM_OWN_PLAN: 409,
    CLAIM_NOT_ACTIVE: 409,
    IDEMPOTENCY_CONFLICT: 409,
    TRY_AGAIN: 503,
    INTERNAL_ERROR: 500,
    AI_QUOTA_EXCEEDED: 429,
    AI_SESSION_CLOSED: 409,
    AI_SESSION_BUSY: 409,
    AI_INVALID_OUTPUT: 502,
    AI_UNAVAILABLE: 503,
}

DEFAULT_MESSAGES: dict[str, str] = {
    VALIDATION_ERROR: "입력값을 확인해 주세요.",
    RECORD_REQUIRED: "먼저 방문 기록을 저장해 주세요.",
    UNAUTHORIZED: "로그인이 필요해요.",
    FORBIDDEN: "이 요청을 할 권한이 없어요.",
    NOT_FOUND: "찾을 수 없어요.",
    ALREADY_CLAIMED: "이미 다른 사람이 이어받았어요.",
    CANNOT_CLAIM_OWN_PLAN: "내가 남긴 하루는 이어받을 수 없어요.",
    CLAIM_NOT_ACTIVE: "이미 종료된 이어받기예요.",
    IDEMPOTENCY_CONFLICT: "같은 요청 키로 다른 내용을 보냈어요.",
    TRY_AGAIN: "잠시 후 다시 시도해 주세요.",
    INTERNAL_ERROR: "일시적인 오류가 발생했어요.",
    AI_QUOTA_EXCEEDED: "오늘 AI 정리 횟수를 모두 썼어요. 직접 정리해 주세요.",
    AI_SESSION_CLOSED: "이미 끝난 AI 정리예요.",
    AI_SESSION_BUSY: "AI가 아직 정리하고 있어요.",
    AI_INVALID_OUTPUT: "AI 카드를 만들지 못했어요. 직접 정리해 주세요.",
    AI_UNAVAILABLE: "AI 카드를 만들지 못했어요. 직접 정리해 주세요.",
}


class ApiError(Exception):
    """계약에 정의된 에러. details는 VALIDATION_ERROR에서만 응답에 나간다."""

    def __init__(
        self,
        code: str,
        status: int | None = None,
        message: str | None = None,
        details: dict[str, str] | None = None,
    ) -> None:
        if code not in CODE_STATUS:
            raise ValueError(f"unknown error code: {code}")
        expected = CODE_STATUS[code]
        if status is not None and status != expected:
            raise ValueError(f"{code} must use HTTP {expected}, got {status}")
        self.code = code
        self.status = expected
        self.message = message or DEFAULT_MESSAGES[code]
        self.details = details
        super().__init__(code)
