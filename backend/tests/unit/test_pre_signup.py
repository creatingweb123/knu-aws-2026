"""PreSignUp 닉네임 검사 (BE-AUTH-02, FE-Q26 프론트 사전 검사와 같은 1–20자 규칙).

회귀 기록: 프론트는 닉네임 1–20자를 먼저 검사하지만 백엔드 트리거는 길이를 보지 않았다.
"""

import pytest

from handlers import pre_signup


def _event(nickname):
    attrs = {"email": "minsu@example.com"}
    if nickname is not None:
        attrs["nickname"] = nickname
    return {"triggerSource": "PreSignUp_SignUp", "request": {"userAttributes": attrs}, "response": {}}


@pytest.mark.parametrize("nickname", ["지연", "a", "가" * 20, "  수현  ", "🙂" * 20])
def test_valid_nickname_is_confirmed(nickname):
    out = pre_signup.handler(_event(nickname), None)
    assert out["response"] == {"autoConfirmUser": True, "autoVerifyEmail": True}


@pytest.mark.parametrize("nickname", ["", "   ", "가" * 21, "🙂" * 21, 123, ["x"]])
def test_invalid_nickname_is_rejected(nickname):
    with pytest.raises(pre_signup.SignUpRejected) as err:
        pre_signup.handler(_event(nickname), None)
    assert str(err.value) == "닉네임은 1–20자로 입력해 주세요."


def test_missing_nickname_attribute_is_left_to_user_pool_required_setting():
    """Required 속성이라 Cognito가 먼저 막는다. 트리거는 속성이 없을 때 검사하지 않는다."""
    out = pre_signup.handler(_event(None), None)
    assert out["response"]["autoConfirmUser"] is True


def test_event_without_request_keeps_old_behaviour():
    out = pre_signup.handler({"response": {}}, None)
    assert out["response"] == {"autoConfirmUser": True, "autoVerifyEmail": True}
