"""API 에러 코드와 예외 (docs/03-api-contract.md §3.6).

핸들러와 서비스는 ApiError를 던지기만 하고, responses.error_response가 에러 형식으로 바꾼다.
"""

from __future__ import annotations

VALIDATION_ERROR = "VALIDATION_ERROR"
UNAUTHORIZED = "UNAUTHORIZED"
NOT_FOUND = "NOT_FOUND"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
TRY_AGAIN = "TRY_AGAIN"
# BE-Q23: 예기치 못한 서버 오류의 코드가 §3.6에 없다. 확정 전까지 임시로 쓴다.
INTERNAL_ERROR = "INTERNAL_ERROR"

# 이번 범위(1·2단계)에서 쓰는 코드와 HTTP 상태. §3.6과 같은 조합만 쓴다(요구사항 11.7).
CODE_STATUS: dict[str, int] = {
    VALIDATION_ERROR: 400,
    UNAUTHORIZED: 401,
    NOT_FOUND: 404,
    IDEMPOTENCY_CONFLICT: 409,
    TRY_AGAIN: 503,
    INTERNAL_ERROR: 500,
}

DEFAULT_MESSAGES: dict[str, str] = {
    VALIDATION_ERROR: "입력값을 확인해 주세요.",
    UNAUTHORIZED: "로그인이 필요해요.",
    NOT_FOUND: "찾을 수 없어요.",
    IDEMPOTENCY_CONFLICT: "같은 요청 키로 다른 내용을 보냈어요.",
    TRY_AGAIN: "잠시 후 다시 시도해 주세요.",
    INTERNAL_ERROR: "일시적인 오류가 발생했어요.",
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
