"""Cognito PreSignUp 트리거 (BE-AUTH-02). 인증 코드 없이 가입 직후 로그인할 수 있게 한다.

autoConfirmUser·autoVerifyEmail만 true로 바꾸고 나머지는 그대로 돌려준다.
닉네임 길이(1–20자, 앞뒤 공백 제외, 코드 포인트 기준)는 프론트 사전 검사(FE-Q26)와 같은 규칙으로 여기서도 검사한다.
User Pool 스키마는 만든 뒤 바꿀 수 없어 길이 제한을 스키마에 둘 수 없다(BE-Q45 관련 정책 결정은 docs/08 참고).
요청에 nickname 속성이 없으면 검사하지 않는다(User Pool의 Required 설정이 가입 자체를 막는다).
"""

from typing import Any

NICKNAME_MAX = 20
NICKNAME_MESSAGE = f"닉네임은 1–{NICKNAME_MAX}자로 입력해 주세요."


class SignUpRejected(Exception):
    """Cognito가 `UserLambdaValidationException`으로 바꿔 클라이언트에 돌려주는 사유 메시지."""


def _check_nickname(event: dict[str, Any]) -> None:
    request = event.get("request")
    attrs = request.get("userAttributes") if isinstance(request, dict) else None
    if not isinstance(attrs, dict) or "nickname" not in attrs:
        return
    nickname = attrs["nickname"]
    if not isinstance(nickname, str) or not (1 <= len(nickname.strip()) <= NICKNAME_MAX):
        raise SignUpRejected(NICKNAME_MESSAGE)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    _check_nickname(event)
    response = event.get("response")
    if not isinstance(response, dict):
        response = {}
        event["response"] = response
    response["autoConfirmUser"] = True
    response["autoVerifyEmail"] = True
    return event
