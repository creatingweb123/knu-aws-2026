"""Property 9: 전화·이메일·주민번호·동/호수 샘플은 HIGH, 데모 사연은 0건, mask 후 재스캔 시 HIGH 0건.

Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7
"""

import logging

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.privacy import HIGH, MEDIUM, PrivacyHit, count_by_kind, log_privacy_counts, mask, scan_privacy

DEMO_STORY = (
    "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, "
    "저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
)

d = st.integers(0, 9).map(str)


def digits(n):
    return st.lists(d, min_size=n, max_size=n).map("".join)


sep = st.sampled_from(["-", "", " ", "."])
phone = st.builds(lambda p, a, b, s: f"{p}{s}{a}{s}{b}", st.sampled_from(["010", "011", "016", "02", "031"]), digits(4), digits(4), sep)
email = st.builds(lambda u, h: f"{u}@{h}.com", st.text("abcxyz019._", min_size=1, max_size=10), st.text("abcxyz", min_size=1, max_size=8))
rrn = st.builds(lambda a, g, b: f"{a}-{g}{b}", digits(6), st.sampled_from("1234"), digits(6))
unit = st.builds(lambda a, b: f"{int(a) + 1}동 {int(b) + 1}호", digits(3), digits(3)) | st.builds(lambda b: f"{int(b) + 1}호", digits(3))
high_sample = st.one_of(
    phone.map(lambda v: ("PHONE", v)), email.map(lambda v: ("EMAIL", v)), rrn.map(lambda v: ("RRN", v)), unit.map(lambda v: ("UNIT", v))
)
filler = st.text(alphabet=st.sampled_from(list("가나다라마빵집하천 ")), max_size=15)


@given(sample=high_sample, pre=filler, post=filler)
def test_high_samples_detected_and_masked(sample, pre, post):
    kind, value = sample
    text = f"{pre} {value} {post}"
    hits = scan_privacy({"story": text})
    assert PrivacyHit("story", kind, HIGH) in hits
    masked = mask(text)
    assert value not in masked
    assert [h for h in scan_privacy({"story": masked}) if h.severity == HIGH] == []


def test_demo_story_has_no_hits():
    assert scan_privacy({"story": DEMO_STORY}) == []


@pytest.mark.parametrize(
    "text,kind",
    [
        ("주차된 12가 3456 차량", "PLATE"),
        ("123나4567", "PLATE"),
        ("역삼동 123-4번지 근처", "LOT"),
        ("우리 집 앞 놀이터", "PRIVATE_PLACE"),
        ("우리집", "PRIVATE_PLACE"),
        ("민수네 집에서 놀았어요", "PRIVATE_PLACE"),
    ],
)
def test_medium_kinds(text, kind):
    hits = scan_privacy({"p": text})
    assert PrivacyHit("p", kind, MEDIUM) in hits
    assert all(h.severity == MEDIUM for h in hits)


@pytest.mark.parametrize(
    "text",
    ["2호선 타고 갔어요", "1호점 빵집", "호수공원 산책", "45분 걸었어요", "2026년 11월 17일", "출근길 빵집", "5년 살던 동네"],
)
def test_negative_samples(text):
    assert scan_privacy({"p": text}) == []


@pytest.mark.parametrize("texts", [None, {}, {"a": ""}, {"a": None, "b": ""}])
def test_empty_inputs(texts):
    assert scan_privacy(texts) == []


def test_unit_combined_counts_once():
    assert scan_privacy({"p": "101동 1203호"}) == [PrivacyHit("p", "UNIT", HIGH)]


def test_mask_keeps_non_high_parts():
    assert mask("우리 집 010-1234-5678 12가 3456") == "우리 집 *** 12가 3456"
    assert mask("") == "" and mask(None) is None


def test_hits_keep_path():
    hits = scan_privacy({"title": "연락은 010-1234-5678", "places[0].name": "a@b.com"})
    assert {(h.path, h.kind) for h in hits} == {("title", "PHONE"), ("places[0].name", "EMAIL")}


def test_person_name_never_reported():
    assert all(h.kind != "PERSON_NAME" for h in scan_privacy({"p": "김민수 씨와 이지연 씨를 만났어요"}))


def test_log_counts_only(caplog):
    text = "연락처 010-1234-5678"
    hits = scan_privacy({"story": text})
    with caplog.at_level(logging.INFO):
        log_privacy_counts(hits)
    assert count_by_kind(hits) == {"PHONE": 1}
    assert "010-1234-5678" not in caplog.text and "연락처" not in caplog.text
    assert "PHONE" in caplog.text
