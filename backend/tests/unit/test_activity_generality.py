"""서비스 본질은 '실현하지 못한 하루의 양도와 반환'이다. 산책이 아닌 활동(전시회·카페·서점·공원 사진)도 같은 흐름·검증을 지난다.

카테고리 필드나 이동 경로 개념 없이 places 1~3곳·estimatedMinutes 등 기존 규칙만으로 동작함을 확인한다.
동시 이어받기 단일 확정(G1)·완료 멱등(G2)·포기 후 이전 요청 거부(G3·G4)를 전시회 계획으로 다시 확인한다.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("moto")

from pydantic import ValidationError  # noqa: E402

from common import ddb  # noqa: E402
from common.auth import User  # noqa: E402
from common.errors import ApiError  # noqa: E402
from common.validation import PlanCreate  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from domain import inbox_service as inbox  # noqa: E402
from domain import plan_service as ps  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

NOW = datetime(2026, 11, 27, 3, 0, tzinfo=timezone.utc)
OWNER = User("u-owner", "지연")
SUHYUN = User("u-suhyun", "수현")
MINJUN = User("u-minjun", "민준")

# (제목, 요약, 장소 목록, 질문) - 산책이 아닌 대표 활동 사례
ACTIVITIES = {
    "exhibition": ("일정이 바뀌어 못 간 전시회", "끝나기 전에 사진 전시를 대신 보고 와 주세요.",
                   [("시립 미술관 사진 전시", "전시 둘러보기", "이번 주에 끝나요")], "가장 오래 머문 작품은 무엇이었나요?"),
    "cafe": ("가 보려던 골목 카페", "창가 자리에서 커피 한 잔을 마셔 봐 주세요.",
             [("골목 카페", "커피 마시기", "")], "커피 맛은 어땠나요?"),
    "bookstore": ("추억이 담긴 서점 방문", "대학 시절 가던 서점을 둘러봐 주세요.",
                  [("대학가 서점", "책장 둘러보기", ""), ("서점 옆 문구점", "엽서 보기", "")], "서점은 어떤 분위기였나요?"),
    "park_photo": ("공원에서 사진 찍고 쉬기", "단풍 사진을 한 장 남겨 주세요.",
                   [("시민공원 단풍길", "사진 찍기", ""), ("공원 벤치", "쉬기", ""), ("공원 매점", "차 마시기", "")], "공원은 어떤 모습이었나요?"),
}


def body_of(kind: str, places=None) -> PlanCreate:
    title, summary, plist, question = ACTIVITIES[kind]
    plist = plist if places is None else places
    return PlanCreate.model_validate({
        "title": title, "summary": summary, "reason": "일정이 바뀌어 직접 가지 못했어요.", "estimatedMinutes": 60,
        "places": [{"name": n, "activity": a, "whyChosen": w} for n, a, w in plist], "question": question,
        "authoring": {"mode": "MANUAL", "durationMs": 1000, "story": f"{title}을 못 하게 되어 대신 경험해 줄 분을 찾아요."},
    })


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


def new_plan(kind: str, key: str | None = None) -> str:
    plan, _ = ps.create_plan(OWNER, key or f"k-{kind}", body_of(kind), NOW)
    return plan["planId"]


def code_of(fn):
    with pytest.raises(ApiError) as exc:
        fn()
    return exc.value.code


@pytest.mark.parametrize("kind", sorted(ACTIVITIES))
def test_full_flow_for_non_walk_activity(table, kind):
    """계획 → 공개 목록 → 이어받기 → 경험 기록 → 완료 → 수신함 → 답장."""
    pid = new_plan(kind)
    assert [p["planId"] for p in ps.list_plans("OPEN", None, NOW)] == [pid]
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    assert ps.get_plan(pid, SUHYUN, NOW)["plan"]["status"] == "CLAIMED"
    cs.put_record(c["claimId"], SUHYUN, "직접 다녀와서 느낀 점을 적어요.", NOW + timedelta(hours=1))
    res = cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW + timedelta(hours=2))
    assert res["delivered"] is True and res["claim"]["status"] == "COMPLETED"
    (item,) = [i for i in inbox.list_items(OWNER)]
    assert item["itemId"] == c["claimId"] and item["planTitle"] == ACTIVITIES[kind][0]
    assert inbox.get_detail(c["claimId"], OWNER)["record"]["letter"] == "직접 다녀와서 느낀 점을 적어요."
    inbox.reply(c["claimId"], OWNER, "대신 다녀와 줘서 고마워요.", NOW + timedelta(hours=3))
    assert "대신 다녀와 줘서 고마워요." in str(inbox.get_detail(c["claimId"], OWNER)["item"]["reply"])


def test_single_place_plan_is_valid_and_saved(table):
    pid = new_plan("exhibition")
    plan = ps.get_plan(pid, SUHYUN, NOW)["plan"]
    assert len(plan["places"]) == 1 and plan["status"] == "OPEN"


@pytest.mark.parametrize("count", [0, 4])
def test_place_count_outside_1_to_3_rejected(count):
    places = [(f"장소{i}", "둘러보기", "") for i in range(count)]
    with pytest.raises(ValidationError) as e:
        body_of("exhibition", places)
    assert "places" in str(e.value)


def test_no_route_or_category_concept_in_plan(table):
    """이동·경로·카테고리 필드 없이 저장된다. 장소는 이름·활동·이유·표시 순서뿐이다."""
    plan = ps.get_plan(new_plan("cafe"), SUHYUN, NOW)["plan"]
    assert set(plan["places"][0]) == {"name", "activity", "whyChosen", "order"}  # order는 입력 순서일 뿐 경로가 아니다
    stored = table.scan()["Items"]
    for item in stored:
        assert not {"category", "route", "distance", "walkMinutes"} & set(item)


def test_concurrent_claim_on_exhibition_plan_single_winner(table, monkeypatch):
    """G1 순차판: 패자가 읽은 뒤 승자가 먼저 커밋해도 확정은 한 명이다."""
    pid = new_plan("exhibition")
    real = ddb.transact_with_retry
    state = {"raced": False}

    def racing(items):
        if not state["raced"]:
            state["raced"] = True
            cs.claim_plan(pid, SUHYUN, NOW)
        return real(items)

    monkeypatch.setattr(ddb, "transact_with_retry", racing)
    assert code_of(lambda: cs.claim_plan(pid, MINJUN, NOW)) == "ALREADY_CLAIMED"
    monkeypatch.setattr(ddb, "transact_with_retry", real)
    claims = [i for i in table.scan()["Items"] if i["PK"] == f"PLAN#{pid}" and i["SK"].startswith("CLAIM#")]
    assert len(claims) == 1 and claims[0]["claimerId"] == "u-suhyun"


def test_complete_is_idempotent_for_bookstore_plan(table):
    """G2: 같은 완료를 다시 보내도 수신함은 하나다."""
    pid = new_plan("bookstore")
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "서점은 그대로였어요.", NOW)
    cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW + timedelta(hours=1))
    again = cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW + timedelta(hours=2))
    assert again["claim"]["status"] == "COMPLETED"
    assert len(inbox.list_items(OWNER)) == 1


def test_abandon_then_old_claim_requests_rejected_for_park_plan(table):
    """G3·G4: 포기하면 계획이 다시 열리고, 이전 요청(기록·완료)은 거부된다."""
    pid = new_plan("park_photo")
    c, _ = cs.claim_plan(pid, SUHYUN, NOW)
    cs.put_record(c["claimId"], SUHYUN, "쓰던 글", NOW)
    cs.abandon(c["claimId"], SUHYUN, NOW + timedelta(hours=1))
    assert ps.get_plan(pid, MINJUN, NOW)["plan"]["status"] == "OPEN"
    assert code_of(lambda: cs.put_record(c["claimId"], SUHYUN, "늦게 쓴 글", NOW + timedelta(hours=2)))
    assert code_of(lambda: cs.complete_by_user(c["claimId"], SUHYUN, "TEXT_ONLY", NOW + timedelta(hours=2)))
    c2, _ = cs.claim_plan(pid, MINJUN, NOW + timedelta(hours=3))
    assert c2["claimerId"] == "u-minjun"
