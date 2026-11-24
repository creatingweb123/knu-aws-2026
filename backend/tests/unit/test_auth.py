"""Property 3: 본문·쿼리·헤더에 다른 사용자 ID가 있어도 get_user 결과는 JWT sub로 고정된다.

Validates: Requirements 2.1, 2.2, 2.3
"""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from common.auth import User, get_user
from common.errors import ApiError

ids = st.text(min_size=1, max_size=40)


def event(claims, body=None, query=None, headers=None):
    return {
        "headers": headers or {},
        "queryStringParameters": query,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"jwt": {"claims": claims}}},
    }


@given(sub=ids, nickname=st.text(min_size=1, max_size=20), other=ids)
def test_user_comes_from_sub_only(sub, nickname, other):
    ev = event(
        {"sub": sub, "nickname": nickname},
        body={"userId": other, "ownerId": other, "sub": other},
        query={"userId": other},
        headers={"x-user-id": other, "userid": other},
    )
    assert get_user(ev) == User(sub, nickname)


@pytest.mark.parametrize(
    "ev",
    [
        {},
        {"requestContext": {}},
        {"requestContext": {"authorizer": None}},
        event({}),
        event({"sub": ""}),
        event({"sub": 123}),
        event({"nickname": "지연"}, body={"userId": "u1"}),
    ],
)
def test_missing_sub_is_unauthorized(ev):
    with pytest.raises(ApiError) as exc:
        get_user(ev)
    assert exc.value.code == "UNAUTHORIZED" and exc.value.status == 401


def test_missing_nickname_is_none():
    assert get_user(event({"sub": "u1"})) == User("u1", None)
