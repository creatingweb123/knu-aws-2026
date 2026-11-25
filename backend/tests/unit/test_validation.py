"""Property 5: 검증 경계에서 유효 범위만 통과하고 실패 details 키는 places[0].name 표기.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.6
"""

import copy

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from common.validation import PlanCreate, Reply, loc_to_path, to_details


def valid_body() -> dict:
    return {
        "title": "이사 전, 마지막 동네 산책",
        "summary": "출근길 빵집에 들르고 하천 벤치에 앉아 쉬고 싶었어요.",
        "reason": "이삿짐 정리가 길어져 마지막 산책을 하지 못했어요.",
        "estimatedMinutes": 45,
        "places": [{"name": "출근길 빵집", "activity": "들러서 빵 사기", "whyChosen": "출근길에 지나치던 곳이에요."}],
        "question": "벤치에 앉았을 때 어떤 소리가 들렸나요?",
        "authoring": {"mode": "MANUAL", "durationMs": 183000, "story": "사연 원문"},
    }


def set_path(body: dict, path: tuple, value) -> dict:
    node = body
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    return body


def check(body: dict, ok: bool, expected_key: str) -> None:
    if ok:
        PlanCreate.model_validate(body)
        return
    with pytest.raises(ValidationError) as exc:
        PlanCreate.model_validate(body)
    details = to_details(exc.value)
    assert expected_key in details
    assert all(isinstance(v, str) and v for v in details.values())


# (본문 경로, details 키, 최소, 최대)
TEXT_FIELDS = [
    (("title",), "title", 1, 40),
    (("summary",), "summary", 1, 120),
    (("reason",), "reason", 1, 300),
    (("question",), "question", 1, 80),
    (("places", 0, "name"), "places[0].name", 1, 30),
    (("places", 0, "activity"), "places[0].activity", 1, 60),
    (("places", 0, "whyChosen"), "places[0].whyChosen", 0, 120),
    (("authoring", "story"), "authoring.story", 1, 1000),
]


@pytest.mark.parametrize("path,key,lo,hi", TEXT_FIELDS)
@given(data=st.data())
def test_text_length_boundaries(path, key, lo, hi, data):
    n = data.draw(st.sampled_from(sorted({max(lo - 1, 0), lo, hi, hi + 1})) | st.integers(0, hi + 5))
    body = set_path(copy.deepcopy(valid_body()), path, "가" * n)
    check(body, lo <= n <= hi, key)


@given(n=st.integers(-5, 300))
def test_estimated_minutes_range(n):
    body = set_path(valid_body(), ("estimatedMinutes",), n)
    check(body, 10 <= n <= 240, "estimatedMinutes")


@pytest.mark.parametrize("n", [9, 10, 240, 241])
def test_estimated_minutes_edges(n):
    check(set_path(valid_body(), ("estimatedMinutes",), n), 10 <= n <= 240, "estimatedMinutes")


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4])
def test_places_count(count):
    place = valid_body()["places"][0]
    body = set_path(valid_body(), ("places",), [dict(place) for _ in range(count)])
    check(body, 1 <= count <= 3, "places")


@given(n=st.integers(-10, 10**9))
def test_duration_ms_non_negative(n):
    check(set_path(valid_body(), ("authoring", "durationMs"), n), n >= 0, "authoring.durationMs")


@pytest.mark.parametrize("value", ["45", 45.0, True, None])
def test_estimated_minutes_must_be_int(value):
    check(set_path(valid_body(), ("estimatedMinutes",), value), False, "estimatedMinutes")


@pytest.mark.parametrize("mode,ok", [("MANUAL", True), ("AI_EDITED", True), ("manual", False), ("AI", False)])
def test_authoring_mode(mode, ok):
    check(set_path(valid_body(), ("authoring", "mode"), mode), ok, "authoring.mode")


@pytest.mark.parametrize("mode", ["MANUAL", "AI_EDITED"])
def test_story_required_in_both_modes(mode):
    body = valid_body()
    body["authoring"]["mode"] = mode
    del body["authoring"]["story"]
    check(body, False, "authoring.story")


def test_ai_session_id_only_type_checked():
    body = set_path(valid_body(), ("authoring", "aiSessionId"), "ais_does_not_exist")
    check(body, True, "")
    check(set_path(valid_body(), ("authoring", "aiSessionId"), 123), False, "authoring.aiSessionId")


def test_details_uses_index_path_for_second_place():
    body = valid_body()
    body["places"].append({"name": "", "activity": "벤치에 앉기", "whyChosen": ""})
    check(body, False, "places[1].name")


def test_missing_field_reports_required():
    body = valid_body()
    del body["title"]
    with pytest.raises(ValidationError) as exc:
        PlanCreate.model_validate(body)
    assert to_details(exc.value)["title"] == "필수 항목이에요."


def test_non_object_body_reports_root():
    with pytest.raises(ValidationError) as exc:
        PlanCreate.model_validate(["not", "an", "object"])
    assert "body" in to_details(exc.value)


def test_loc_to_path():
    assert loc_to_path(("places", 0, "name")) == "places[0].name"
    assert loc_to_path(("authoring", "story")) == "authoring.story"
    assert loc_to_path(()) == "body"


# ---------------------------------------------------------------- 답장 (4단계, Requirement 6.4)


def reply_details(body):
    with pytest.raises(ValidationError) as exc:
        Reply.model_validate(body)
    return to_details(exc.value)


@pytest.mark.parametrize("n,ok", [(0, False), (1, True), (100, True), (101, False)])
def test_reply_text_length(n, ok):
    body = {"text": "가" * n}
    if ok:
        assert Reply.model_validate(body).text == "가" * n
    else:
        assert reply_details(body) == {"text": "1–100자로 입력해 주세요."}


def test_reply_length_counts_code_points():
    assert Reply.model_validate({"text": "😀" * 100}).text == "😀" * 100  # 프론트 [...text].length와 같은 기준
    assert set(reply_details({"text": "😀" * 101})) == {"text"}


def test_reply_keeps_surrounding_spaces():
    assert Reply.model_validate({"text": "  고마워요  "}).text == "  고마워요  "  # FE-Q19
    assert Reply.model_validate({"text": " "}).text == " "


@pytest.mark.parametrize("body,key,message", [({}, "text", "필수 항목이에요."), ({"text": 5}, "text", None), ({"text": None}, "text", None), (None, "body", None), ([], "body", None), ("글", "body", None)])
def test_reply_invalid(body, key, message):
    details = reply_details(body)
    assert set(details) == {key}
    if message:
        assert details[key] == message


# ---------------------------------------------------------------- 사진 (5단계, Requirement 2.6, 3.5, BE-Q50)

from common.validation import PhotoRequest, RecordPut  # noqa: E402


@pytest.mark.parametrize("ct", ["image/jpeg", "image/png"])
@pytest.mark.parametrize("size", [1, 10_485_760])
def test_photo_valid(ct, size):
    assert RecordPut.model_validate({"letter": "글", "photo": {"contentType": ct, "size": size}}).photo.size == size
    assert PhotoRequest.model_validate({"contentType": ct, "size": size}).contentType == ct


@pytest.mark.parametrize(
    "photo,key",
    [
        ({"contentType": "image/gif", "size": 10}, "photo.contentType"),
        ({"contentType": "image/jpeg", "size": 0}, "photo.size"),
        ({"contentType": "image/jpeg", "size": 10_485_761}, "photo.size"),
        ({"contentType": "image/jpeg", "size": True}, "photo.size"),
        ({"contentType": "image/jpeg", "size": 1.5}, "photo.size"),
        ({"contentType": "image/jpeg", "size": "10"}, "photo.size"),
        ({"contentType": "image/jpeg"}, "photo.size"),
        ("사진", "photo"),
        ([], "photo"),
    ],
)
def test_record_put_photo_invalid(photo, key):
    with pytest.raises(ValidationError) as exc:
        RecordPut.model_validate({"letter": "글", "photo": photo})
    assert key in to_details(exc.value)


def test_record_put_photo_null_is_text_only():
    assert RecordPut.model_validate({"letter": "글", "photo": None}).photo is None
    assert RecordPut.model_validate({"letter": "글"}).photo is None


@pytest.mark.parametrize(
    "body,key",
    [({"contentType": "text/plain", "size": 1}, "contentType"), ({"contentType": "image/png", "size": -1}, "size"), (None, "body"), ([], "body")],
)
def test_photo_request_invalid(body, key):
    with pytest.raises(ValidationError) as exc:
        PhotoRequest.model_validate(body)
    assert key in to_details(exc.value)
