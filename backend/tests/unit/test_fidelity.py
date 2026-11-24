"""Property 8: S ⊆ S'이면 hits(S') ⊆ hits(S), 같은 입력은 같은 결과, 입력 불변.

Validates: Requirements 9.1, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10
"""

import copy
import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.fidelity import NotInSourceHit, Target, find_not_in_source, normalize, strip_particle

DEMO_STORY = (
    "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, "
    "저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
)
SYNONYMS = json.loads((Path(__file__).parents[1] / "fixtures" / "normalization.json").read_text(encoding="utf-8"))[
    "synonyms"
]

korean = st.text(alphabet=st.sampled_from(list("가나다빵집하천벤치골목출근길에를은 ")), max_size=25)
sources_st = st.lists(korean, max_size=4)
targets_st = st.lists(st.tuples(st.sampled_from(["places[0].name", "places[1].activity", "x"]), st.none() | korean), max_size=5)


def as_set(hits):
    return {(h.path, h.text) for h in hits}


@given(s=sources_st, extra=sources_st, targets=targets_st)
def test_monotonic_when_sources_added(s, extra, targets):
    assert as_set(find_not_in_source(s + extra, targets)) <= as_set(find_not_in_source(s, targets))


@given(s=sources_st, targets=targets_st)
def test_deterministic_and_pure(s, targets):
    s_copy, t_copy = copy.deepcopy(s), copy.deepcopy(targets)
    first = find_not_in_source(s, targets, SYNONYMS)
    assert first == find_not_in_source(s, targets, SYNONYMS)
    assert s == s_copy and targets == t_copy


@given(s=sources_st, targets=targets_st)
def test_hits_keep_input_order_and_values(s, targets):
    hits = find_not_in_source(s, targets)
    indexes = []
    for h in hits:
        i = next(i for i, t in enumerate(targets) if i not in indexes and (t[0], t[1]) == (h.path, h.text))
        indexes.append(i)
    assert indexes == sorted(indexes)


def test_demo_story_rewritten_place():
    hits = find_not_in_source([DEMO_STORY], [Target("places[0].name", "골목 빵집"), Target("places[1].name", "출근길 빵집")])
    assert hits == [NotInSourceHit("places[0].name", "골목 빵집")]


def test_particles_are_stripped():
    assert find_not_in_source([DEMO_STORY], [Target("a", "하천 벤치에서"), Target("b", "출근길에")]) == []


def test_blank_targets_are_skipped():
    targets = [Target("a", None), Target("b", ""), Target("c", "   ")]
    assert find_not_in_source([DEMO_STORY], targets) == []
    assert find_not_in_source([], targets) == []


@pytest.mark.parametrize("sources", [[], [""], ["  ", None]])
def test_empty_sources_hit_every_non_blank_target(sources):
    targets = [Target("a", "출근길 빵집"), Target("b", None), Target("c", "빵")]
    assert find_not_in_source(sources, targets) == [NotInSourceHit("a", "출근길 빵집"), NotInSourceHit("c", "빵")]


def test_all_tokens_must_match():
    assert find_not_in_source(["골목에 있는 카페"], [Target("a", "골목 빵집")]) == [NotInSourceHit("a", "골목 빵집")]


def test_synonyms_only_from_fixture():
    story = ["출근길 빵 가게에 들렀어요"]
    target = [Target("places[0].name", "출근길 빵집")]
    assert find_not_in_source(story, target) == [NotInSourceHit("places[0].name", "출근길 빵집")]
    assert find_not_in_source(story, target, SYNONYMS) == []
    # 픽스처에 없는 표현은 다른 표현으로 본다
    assert find_not_in_source(["출근길 빵 상점"], target, SYNONYMS) == [NotInSourceHit("places[0].name", "출근길 빵집")]


def test_sources_are_matched_separately():
    # 두 근거를 이어 붙여 생기는 부분 문자열은 일치로 보지 않는다
    assert find_not_in_source(["하천 벤", "치 앞"], [Target("a", "벤치")]) == [NotInSourceHit("a", "벤치")]


def test_known_limit_noun_ending_like_particle():
    # BE-Q25 기본안의 한계: 조사처럼 끝나는 명사("산책로"의 "로")도 조사를 떼므로 "산책"만 있어도 통과한다.
    assert find_not_in_source(["하천 산책"], [Target("a", "산책로")]) == []


def test_normalize_and_strip():
    assert normalize("출근길 빵집, 하천!") == "출근길빵집하천"
    assert strip_particle("벤치에서") == "벤치"
    assert strip_particle("빵을") == "빵을"  # 남는 글자가 1자면 떼지 않는다
