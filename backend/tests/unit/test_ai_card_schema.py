"""Card_Schema(AiCardDraft)와 검증 전 정규화 (design §3.1, BE-Q91).

정상적인 빈 값(null)은 통과하고, 실제 스키마 위반만 오류다.
Validates: Requirements 4.4, 9.3, 9.4
"""

import pytest
from pydantic import ValidationError

from common.validation import AiCardDraft, loc_to_path, normalize_card_payload


def validate(obj):
    return AiCardDraft.model_validate(normalize_card_payload(obj))


def error_paths(obj):
    with pytest.raises(ValidationError) as e:
        validate(obj)
    return {loc_to_path(tuple(x["loc"])) for x in e.value.errors()}


# 정상 null ---------------------------------------------------------------


@pytest.mark.parametrize("obj", [{}, {"title": None}, {"title": "   "}, {"title": ""}, {"places": None}, {"places": []}])
def test_valid_nulls(obj):
    card = validate(obj)
    assert card.title is None and card.places == []


def test_place_subfields_may_be_null_and_whychosen_keeps_empty():
    card = validate({"places": [{"name": None, "activity": " ", "whyChosen": ""}, {"name": "빵집"}]})
    assert card.places[0].model_dump() == {"name": None, "activity": None, "whyChosen": ""}
    assert card.places[1].model_dump() == {"name": "빵집", "activity": None, "whyChosen": None}


def test_strings_are_stripped_and_unknown_keys_ignored():
    card = validate({"title": "  산책  ", "extra": 1, "places": [{"name": " 빵집 ", "foo": "bar"}]})
    assert card.title == "산책" and card.places[0].name == "빵집"


@pytest.mark.parametrize(
    ("field", "lo", "hi"), [("title", 1, 40), ("summary", 1, 120), ("reason", 1, 300), ("question", 1, 80)]
)
def test_scalar_length_bounds(field, lo, hi):
    assert getattr(validate({field: "가" * lo}), field) == "가" * lo
    assert getattr(validate({field: "가" * hi}), field) == "가" * hi
    assert error_paths({field: "가" * (hi + 1)}) == {field}


@pytest.mark.parametrize(("field", "hi"), [("name", 30), ("activity", 60), ("whyChosen", 120)])
def test_place_length_bounds(field, hi):
    assert validate({"places": [{field: "가" * hi}]}).places[0].model_dump()[field] == "가" * hi
    assert error_paths({"places": [{field: "가" * (hi + 1)}]}) == {f"places[0].{field}"}


@pytest.mark.parametrize("value", [10, 45, 240])
def test_minutes_valid(value):
    assert validate({"estimatedMinutes": value}).estimatedMinutes == value


# 스키마 위반 -------------------------------------------------------------


@pytest.mark.parametrize("value", [9, 241, "45", 45.5, 45.0, True, False, [45], {"m": 45}])
def test_minutes_violations(value):
    assert error_paths({"estimatedMinutes": value}) == {"estimatedMinutes"}


@pytest.mark.parametrize("value", [1, True, ["a"], {"a": 1}])
def test_string_field_wrong_type(value):
    assert error_paths({"title": value}) == {"title"}


def test_places_violations():
    assert error_paths({"places": "빵집"}) == {"places"}
    assert error_paths({"places": {"name": "빵집"}}) == {"places"}
    assert error_paths({"places": [{"name": "a"}] * 4}) == {"places"}
    assert error_paths({"places": ["빵집"]}) == {"places[0]"}
    assert error_paths({"places": [{"name": 3}]}) == {"places[0].name"}


def test_normalize_does_not_fix_violations():
    assert normalize_card_payload({"title": "가" * 41})["title"] == "가" * 41
    assert normalize_card_payload({"places": "x"})["places"] == "x"
