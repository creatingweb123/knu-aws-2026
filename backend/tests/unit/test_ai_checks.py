"""카드 파싱·check_draft·Gate·규칙 노드·Fallback·Final_Check·인덱스 (design §8.2, §9, §10).

Validates: Requirements 4.5, 4.7, 4.8, 9.3, 9.4, 11.1–11.9 · BE-Q88, BE-Q91
"""

import pytest

from agent import repair, tools
from agent.card import NOT_JSON, SCHEMA, parse_card

STORY = "이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요."
SOURCES = [STORY]


def place(name, activity="벤치에 앉아 쉬기", why="저녁마다 걷던 길이에요."):
    return {"name": name, "activity": activity, "whyChosen": why}


def card(*places, **over):
    base = {"title": "이사 전, 마지막 동네 산책", "summary": "출근길 빵집에 들르고 싶었어요.", "reason": "이삿짐 정리가 길어졌어요.",
            "estimatedMinutes": 45, "places": list(places), "question": "벤치에서 무엇이 보였나요?"}
    base.update(over)
    return base


def level0(candidate):
    """레벨 0 순서: rules → gate(다시 검사) → (거부 시) fallback → final_check."""
    work = repair.with_src(candidate)
    work, notes = repair.apply_rules(work)
    report = tools.check_draft(work, SOURCES)
    masked, allowed, degraded = [], set(), False
    if not tools.gate_verdict(report):
        work, more, masked, allowed = repair.apply_fallback(work, SOURCES)
        notes += more
        degraded = True
    flags, blocked = tools.final_check(work, SOURCES, masked=masked, allowed_nis_activities=allowed)
    return tools.public_card(work), flags, notes, blocked, degraded


# 파싱 ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        '{"title": "산책"}',
        '```json\n{"title": "산책"}\n```',
        '여기 카드예요:\n{"title": "산책"}\n도움이 되길 바라요.',
        [{"type": "text", "text": '{"title": '}, {"type": "text", "text": '"산책"}'}],
        '{"title": "산책"} {"title": "두 번째"}',
    ],
)
def test_parse_ok(content):
    r = parse_card(content)
    assert r.ok and r.card["title"] == "산책" and r.card["places"] == []


@pytest.mark.parametrize("content", ["카드를 만들 수 없어요", '["title"]', '{"title": "산책"', "", None, 3])
def test_parse_not_json(content):
    r = parse_card(content)
    assert r.kind == NOT_JSON and r.card is None and r.paths == ()


def test_parse_schema_paths_without_text():
    r = parse_card('{"title": "' + "가" * 41 + '", "estimatedMinutes": "45", "places": [{"name": 3}]}')
    assert r.kind == SCHEMA and set(r.paths) == {"title", "estimatedMinutes", "places[0].name"}
    assert "가" * 41 not in repr(r)


# check_draft ------------------------------------------------------------------


def test_check_draft_report():
    c = repair.with_src(card(place("출근길 빵집", "들러서 빵 사기"), place("골목 빵집", "커피 마시기", None), title=None,
                             summary="연락처 010-1234-5678", question=None))
    r = tools.check_draft(c, SOURCES)
    assert r["schemaErrors"] == []
    assert r["notInSource"] == ["places[1].name", "places[1].activity"]
    assert r["privacy"] == [{"path": "summary", "kind": "PHONE", "severity": "HIGH"}]
    assert r["missing"] == ["title", "question"]  # whyChosen null은 MISSING 아님


def test_check_draft_missing_places_and_subfields():
    r = tools.check_draft(repair.with_src(card()), SOURCES)
    assert "places" in r["missing"]
    r = tools.check_draft(repair.with_src(card(place(None, None))), SOURCES)
    assert {"places[0].name", "places[0].activity"} <= set(r["missing"])


@pytest.mark.parametrize(
    ("c", "ok"),
    [
        (card(place("출근길 빵집", "들러서 빵 사기")), True),
        (card(place("골목 빵집", "들러서 빵 사기")), False),            # 장소 이름 원문 없음
        (card(place("출근길 빵집", "커피 마시기")), False),             # 활동 원문 없음
        (card(place("출근길 빵집"), summary="101동 1203호 앞"), False),  # HIGH
        (card(place("출근길 빵집"), title="가" * 41), False),          # 스키마 오류
        (card(place("출근길 빵집"), summary="12가 3456 차 옆"), True),   # MEDIUM은 막지 않는다(BE-Q22)
    ],
)
def test_gate_verdict(c, ok):
    assert tools.gate_verdict(tools.check_draft(repair.with_src(c), SOURCES)) is ok


# 규칙 노드 --------------------------------------------------------------------


def test_rules_remove_private_place_with_candidate_index():
    work, notes = repair.apply_rules(repair.with_src(card(place("출근길 빵집"), place("민지네 집", "놀러 가기"), place("하천 벤치", "우리 집 앞 걷기"))))
    assert [p["name"] for p in work["places"]] == ["출근길 빵집"]
    assert notes == [
        {"path": "places[1].name", "action": "REMOVED", "reason": repair.REASON_PRIVATE, "source": "STORY"},
        {"path": "places[2].activity", "action": "REMOVED", "reason": repair.REASON_PRIVATE, "source": "STORY"},
    ]


def test_rules_keep_private_place_outside_places():
    work, notes = repair.apply_rules(repair.with_src(card(place("출근길 빵집", why="우리 집 근처라서"), title="우리 집 앞 산책")))
    assert notes == [] and len(work["places"]) == 1
    flags, blocked = tools.final_check(work, SOURCES)
    assert blocked == [] and {"path": "places[0].whyChosen", "type": "PRIVACY"} in flags and {"path": "title", "type": "PRIVACY"} in flags


# Fallback ----------------------------------------------------------------------


def test_fallback_phone_in_name_is_masked_then_removed():
    out, flags, notes, blocked, degraded = level0(card(place("010-1234-5678 빵집"), place("출근길 빵집", "들러서 빵 사기")))
    assert degraded and blocked == []
    assert [p["name"] for p in out["places"]] == ["출근길 빵집"]
    assert {"path": "places[0].name", "action": "REMOVED", "reason": repair.REASON_NOT_IN_SOURCE, "source": "STORY"} in notes


def test_fallback_phone_in_activity_masked_and_kept_flagged():
    out, flags, notes, blocked, degraded = level0(card(place("출근길 빵집", "010-1234-5678 로 전화하기")))
    assert degraded and blocked == [] and out["places"][0]["activity"].startswith("***")
    assert {"path": "places[0].activity", "type": "PRIVACY"} in flags
    assert {"path": "places[0].activity", "type": "NOT_IN_SOURCE"} in flags
    assert [n["action"] for n in notes] == ["KEPT_FLAGGED"]


def test_fallback_high_in_scalar_masked():
    out, flags, notes, blocked, degraded = level0(card(place("출근길 빵집", "들러서 빵 사기"), summary="a@b.co 로 연락 주세요", reason="101동 1203호 이사"))
    assert degraded and blocked == [] and "a@b.co" not in out["summary"] and "1203호" not in out["reason"]
    assert {"path": "summary", "type": "PRIVACY"} in flags and {"path": "reason", "type": "PRIVACY"} in flags


def test_fallback_all_places_removed():
    out, flags, notes, blocked, degraded = level0(card(place("골목 빵집"), place("카페 거리", "커피 마시기")))
    assert degraded and blocked == [] and out["places"] == []
    assert {"path": "places", "type": "MISSING"} in flags
    assert [n["path"] for n in notes] == ["places[0].name", "places[1].name"]


def test_fallback_mask_growth_truncated_to_limit():
    title = "가" * 38 + "1호"  # 40자, 가리면 41자 → 40자로 자름
    out, flags, notes, blocked, degraded = level0(card(place("출근길 빵집", "들러서 빵 사기"), title=title))
    assert blocked == [] and len(out["title"]) == 40 and "1호" not in out["title"]


def test_gate_pass_path_also_final_checked():
    out, flags, notes, blocked, degraded = level0(card(place("출근길 빵집", "들러서 빵 사기"), question=None))
    assert not degraded and blocked == [] and flags == [{"path": "question", "type": "MISSING"}]


# Final_Check 차단·허용 (BE-Q88) --------------------------------------------------


def wc(*places, **over):
    return repair.with_src(card(*places, **over))


@pytest.mark.parametrize(
    ("work", "kwargs", "reason"),
    [
        (wc(place("출근길 빵집"), title="가" * 41), {}, tools.SCHEMA_BLOCK),
        (wc(place("출근길 빵집"), summary="010-1234-5678"), {}, tools.HIGH_BLOCK),
        (wc(place("민지네 집")), {}, tools.PRIVATE_BLOCK),
        (wc(place("골목 빵집")), {}, tools.NIS_NAME_BLOCK),
        (wc(place("출근길 빵집", "커피 마시기")), {}, tools.NIS_ACTIVITY_BLOCK),
    ],
)
def test_final_check_blocks(work, kwargs, reason):
    _, blocked = tools.final_check(work, SOURCES, **kwargs)
    assert reason in blocked


def test_final_check_allows_flagged_activity_missing_and_medium():
    work = wc(place("출근길 빵집", "커피 마시기"), summary="12가 3456 옆", question=None)
    flags, blocked = tools.final_check(work, SOURCES, allowed_nis_activities={0})
    assert blocked == []
    assert flags == [
        {"path": "summary", "type": "PRIVACY"},
        {"path": "places[0].activity", "type": "NOT_IN_SOURCE"},
        {"path": "question", "type": "MISSING"},
    ]


def test_final_check_allowed_set_is_by_src_not_position():
    work = wc(place("출근길 빵집", "들러서 빵 사기"), place("하천 벤치", "커피 마시기"))
    work["places"] = work["places"][1:]  # _src=1인 장소가 이제 0번
    _, blocked = tools.final_check(work, SOURCES, allowed_nis_activities={0})
    assert tools.NIS_ACTIVITY_BLOCK in blocked
    flags, blocked = tools.final_check(work, SOURCES, allowed_nis_activities={1})
    assert blocked == [] and {"path": "places[0].activity", "type": "NOT_IN_SOURCE"} in flags


# 인덱스 (design §10.3) ---------------------------------------------------------


def test_design_index_example():
    candidate = card(place("출근길 빵집", "들러서 빵 사기"), place("민지네 집", "놀러 가기"), place("골목 빵집"), place("하천 벤치", "커피 마시기"))
    out, flags, notes, blocked, degraded = level0(candidate)
    assert blocked == [] and degraded
    assert [p["name"] for p in out["places"]] == ["출근길 빵집", "하천 벤치"]
    assert [(n["path"], n["action"]) for n in notes] == [
        ("places[1].name", "REMOVED"), ("places[2].name", "REMOVED"), ("places[1].activity", "KEPT_FLAGGED"),
    ]
    assert {"path": "places[1].activity", "type": "NOT_IN_SOURCE"} in flags
    assert all(tools.place_index(f["path"]) in (None, 0, 1) for f in flags)


def test_masked_path_of_removed_place_dropped():
    work = wc(place("010-1234-5678 빵집"), place("출근길 빵집", "들러서 빵 사기"))
    work, notes, masked, allowed = repair.apply_fallback(work, SOURCES)
    assert masked == [{"src": 0, "field": "name"}]
    flags, blocked = tools.final_check(work, SOURCES, masked=masked, allowed_nis_activities=allowed)
    assert blocked == [] and not any(f["type"] == "PRIVACY" for f in flags)


def test_public_card_strips_src_and_keeps_order():
    pub = tools.public_card(wc(place("출근길 빵집")))
    assert list(pub) == list(tools.CARD_ORDER) and "_src" not in pub["places"][0]
