"""Cognito PreSignUp 트리거 (BE-AUTH-02). 인증 코드 없이 가입 직후 로그인할 수 있게 한다.

autoConfirmUser·autoVerifyEmail만 true로 바꾸고 나머지는 그대로 돌려준다.
"""

from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    response = event.get("response")
    if not isinstance(response, dict):
        response = {}
        event["response"] = response
    response["autoConfirmUser"] = True
    response["autoVerifyEmail"] = True
    return event
