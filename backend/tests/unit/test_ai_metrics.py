"""`POST /plans` AI 세션 지표 (작업 11.3, design §16, Requirement 14.1–14.8, 19.7 · BE-Q79)."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from common.auth import User
from common.ids import new_session_id
from common.responses import iso_utc
from common.validation import PlanCreate
from domain import ai_metrics, ai_session_service, plan_service
from tests.unit.moto_table import haru_table, set_env

NOW = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)
OWNER = User("u-owner", "지연")
STORY = "이사 전에 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했어요."
CARD = {
    "title": "이사 전, 마지막 동네 산책", "summary": "출근길 빵집에 들르고 싶었어요.", "reason": "이삿짐 정리가 길어졌어요.",
    "estimatedMinutes": 45, "question": "벤치에서 무엇이 보였나요?",
    "places": [{"name": "출근길 빵집", "activity": "들러서 빵 사기", "whyChosen": None},
               {"name": "하천 벤치", "activity": "앉아 쉬기", "whyChosen": "저녁마다 걷던 길이에요."}],
}


def session(**over):
    s = {
        "sessionId": "ais_x", "ownerId": "u-owner", "status": "READY", "agentMode": "PIPELINE", "degraded": False,
        "answers": [], "card": CARD, "modelCalls": 2, "privacyDetected": 3,
        "flags": [{"path": "places[1].activity", "type": "NOT_IN_SOURCE"}, {"path": "question", "type": "MISSING"}],
        "notes": [{"path": "places[0].name", "action": "REMOVED"}, {"path": "places[1].activity", "action": "KEPT_FLAGGED"}],
        "firstReport": {"notInSource": ["places[0].name", "places[1].activity"], "missing": ["question", "estimatedMinutes"], "privacy": []},
        "createdAt": "2026-11-26T02:59:00.000Z", "readyAt": "2026-11-26T02:59:04.500Z",
    }
    s.update(over)
    return s


def final(**over):
    f = {k: CARD[k] for k in ai_metrics.SCALARS} | {"places": [dict(p) for p in CARD["places"]]}
    f.update(over)
    return f


# ---------------------------------------------------------------- 계산식


def test_session_metrics_values():
    m = ai_metrics.session_metrics(session(), final(), STORY, "2026-11-26T03:00:00.000Z")
    assert m == {
        "agentMode": "PIPELINE", "addedNotInSourceOrAnswers": 0, "firstProposalNotInSource": 2, "deliveredNotInSource": 1,
        "agentSelfRepairs": 1, "missingFirst": 2, "missingDelivered": 1, "questionsAsked": 0, "questionsSkipped": 0,
        "privacyDetected": 3, "agentWaitMs": 4500, "answerWaitMs": 0, "editMs": 55500, "fieldsEditedAfterHandoff": 0, "modelCalls": 2,
    }


def test_answers_metrics_and_sources():
    answers = [
        {"questionId": "q1", "choice": "45분", "askedAt": "2026-11-26T02:59:01.000Z", "answeredAt": "2026-11-26T02:59:03.000Z"},
        {"questionId": "q2", "skipped": True, "askedAt": "2026-11-26T02:59:03.000Z", "answeredAt": "2026-11-26T02:59:03.500Z"},
    ]
    m = ai_metrics.session_metrics(session(answers=answers), final(), STORY, "2026-11-26T03:00:00.000Z")
    assert (m["questionsAsked"], m["questionsSkipped"], m["answerWaitMs"], m["agentWaitMs"]) == (2, 1, 2500, 2000)
    places = [{"name": "골목 카페", "activity": "커피 마시기", "whyChosen": ""}]
    with_answer = [{"questionId": "q1", "text": "골목 카페에서 커피 마시기"}]
    leaked = [{"questionId": "q1", "text": "골목 카페 010-1234-5678"}]
    assert ai_metrics.session_metrics(session(answers=with_answer), final(places=places), STORY, iso_utc(NOW))["addedNotInSourceOrAnswers"] == 0
    assert ai_metrics.session_metrics(session(answers=leaked), final(places=places), STORY, iso_utc(NOW))["addedNotInSourceOrAnswers"] == 2


def test_fields_edited_example_from_design():
    """카드 장소 2개 → 1개를 지우고 제목만 고침 → 제목 1 + 지운 장소 3 = 4."""
    f = final(title="새 제목", places=[dict(CARD["places"][0])])
    assert ai_metrics.fields_edited(CARD, f) == 4


def test_fields_edited_rules():
    assert ai_metrics.fields_edited(CARD, final()) == 0
    f = final(places=[dict(CARD["places"][0], whyChosen=""), dict(CARD["places"][1])])
    assert ai_metrics.fields_edited(CARD, f) == 0  # whyChosen null = ""
    assert ai_metrics.fields_edited(CARD, final(summary=CARD["summary"] + " ")) == 1  # 공백도 다름
    assert ai_metrics.fields_edited(dict(CARD, estimatedMinutes=None), final()) == 1  # null과 값은 다름
    extra = final(places=[*final()["places"], {"name": "공원", "activity": "걷기", "whyChosen": ""}])
    assert ai_metrics.fields_edited(CARD, extra) == 2  # 새 장소: name·activity 다름, whyChosen ""=null
    assert ai_metrics.fields_edited(None, final()) == 5 + 2 * 3 - 1  # 카드 없음: whyChosen 하나만 같음(null="")


def test_edit_ms_negative_clock_is_zero():
    m = ai_metrics.session_metrics(session(readyAt="2026-11-26T03:00:05.000Z"), final(), STORY, "2026-11-26T03:00:00.000Z")
    assert m["editMs"] == 0 and m["agentWaitMs"] == 65000


@pytest.mark.parametrize(("mode", "degraded", "expected"), [("PIPELINE", True, "PIPELINE"), ("AGENT", False, "AGENT"), ("AGENT", True, "DEGRADED")])
def test_agent_mode(mode, degraded, expected):
    assert ai_metrics.agent_mode({"agentMode": mode, "degraded": degraded}) == expected


# ---------------------------------------------------------------- plan_service 연동 (moto)


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


def put_session(**over):
    sid = over.pop("sessionId", None) or new_session_id()
    created = over.pop("created_at", NOW - timedelta(minutes=2))
    item = ai_session_service.build_session_item(session_id=sid, owner_id=over.pop("owner_id", "u-owner"), story=STORY,
                                                 status=over.pop("status", "READY"), created_at=created,
                                                 ready_at=created + timedelta(seconds=4), card=CARD, flags=session()["flags"],
                                                 notes=session()["notes"], first_report=session()["firstReport"], model_calls=1,
                                                 privacy_detected=0, **over)
    ai_session_service.put_session(item)
    return sid


def plan_body(mode="AI_EDITED", sid=None, **over):
    data = final() | {"places": [dict(p, whyChosen=p["whyChosen"] or "") for p in CARD["places"]]}
    data["authoring"] = {"mode": mode, "durationMs": 1200, "story": STORY, **({"aiSessionId": sid} if sid else {})}
    data.update(over)
    return PlanCreate.model_validate(data)


@pytest.fixture
def reads(monkeypatch):
    calls = []
    real = ai_session_service.get_session

    def spy(sid, **k):
        calls.append(sid)
        return real(sid, **k)

    monkeypatch.setattr(ai_session_service, "get_session", spy)
    return calls


BASE_KEYS = {"authoringMode", "durationMs", "addedNotInSource", "privacyInPublished"}


def test_ai_edited_valid_session_adds_metrics(table, reads):
    sid = put_session()
    plan, created = plan_service.create_plan(OWNER, "k1", plan_body(sid=sid), NOW)
    m = plan["metrics"]
    assert created and reads == [sid]
    assert set(m) == BASE_KEYS | {"agentMode", "addedNotInSourceOrAnswers", "firstProposalNotInSource", "deliveredNotInSource",
                                  "agentSelfRepairs", "missingFirst", "missingDelivered", "questionsAsked", "questionsSkipped",
                                  "privacyDetected", "agentWaitMs", "answerWaitMs", "editMs", "fieldsEditedAfterHandoff", "modelCalls"}
    assert m["agentMode"] == "PIPELINE" and m["modelCalls"] == 1 and m["agentWaitMs"] == 4000 and m["editMs"] == 116000
    assert m["addedNotInSourceOrAnswers"] == m["addedNotInSource"]  # 레벨 0은 답변이 없다
    assert m["fieldsEditedAfterHandoff"] == 0
    stored = table.get_item(Key={"PK": plan["PK"], "SK": "META"})["Item"]["metrics"]
    assert set(stored) == set(m)


def _expired():
    return put_session(created_at=NOW - timedelta(days=31))


@pytest.mark.parametrize(("make", "reason"), [
    (lambda: new_session_id(), "AI_METRICS_SESSION_NOT_FOUND"),
    (_expired, "AI_METRICS_SESSION_EXPIRED"),
    (lambda: put_session(owner_id="u-other"), "AI_METRICS_OWNER_MISMATCH"),
    (lambda: put_session(status="FAILED"), "AI_METRICS_NOT_READY"),
    (lambda: "ais_not-a-ulid", "AI_METRICS_SESSION_ID_INVALID"),
])
def test_excluded_sessions_still_create_plan(table, caplog, make, reason):
    caplog.set_level(logging.INFO, "haru.ai")
    sid = make()
    plan, created = plan_service.create_plan(OWNER, "k1", plan_body(sid=sid), NOW)
    assert created and set(plan["metrics"]) == BASE_KEYS
    assert reason in caplog.text and STORY[:6] not in caplog.text


@pytest.mark.parametrize("err", [ReadTimeoutError(endpoint_url="https://x.invalid"),
                                 ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "GetItem")])
def test_read_failure_still_creates_plan(table, monkeypatch, caplog, err):
    sid = put_session()
    monkeypatch.setattr(ai_session_service, "get_session", lambda *a, **k: (_ for _ in ()).throw(err))
    plan, created = plan_service.create_plan(OWNER, "k1", plan_body(sid=sid), NOW)
    assert created and set(plan["metrics"]) == BASE_KEYS and "AI_METRICS_READ_FAILED" in caplog.text


def test_compute_failure_still_creates_plan(table, monkeypatch, caplog):
    sid = put_session()
    monkeypatch.setattr(ai_metrics, "session_metrics", lambda *a, **k: 1 / 0)
    plan, _ = plan_service.create_plan(OWNER, "k1", plan_body(sid=sid), NOW)
    assert set(plan["metrics"]) == BASE_KEYS and "AI_METRICS_COMPUTE_FAILED type=ZeroDivisionError" in caplog.text


def test_manual_never_reads_session(table, reads):
    sid = put_session()
    plan, _ = plan_service.create_plan(OWNER, "k1", plan_body("MANUAL", sid=sid), NOW)
    plan2, _ = plan_service.create_plan(OWNER, "k2", plan_body("MANUAL"), NOW)
    assert reads == [] and set(plan["metrics"]) == BASE_KEYS == set(plan2["metrics"])


def test_ai_edited_without_session_id_no_read(table, reads):
    plan, _ = plan_service.create_plan(OWNER, "k1", plan_body(), NOW)
    assert reads == [] and set(plan["metrics"]) == BASE_KEYS


def test_idempotent_replay_keeps_metrics_and_skips_read(table, reads):
    sid = put_session()
    first, _ = plan_service.create_plan(OWNER, "k1", plan_body(sid=sid), NOW)
    table.delete_item(Key=ai_session_service.session_key(sid))  # 세션이 사라져도 재요청 지표는 처음 그대로
    again, created = plan_service.create_plan(OWNER, "k1", plan_body(sid=sid), NOW + timedelta(minutes=1))
    assert not created and again["metrics"] == first["metrics"] and again["planId"] == first["planId"]
    assert reads == [sid]


def test_body_hash_unchanged_by_metrics():
    b = plan_body(sid="ais_01ABCDEFGHJKMNPQRSTVWXYZ00")
    assert plan_service.body_hash(b) == plan_service.body_hash(PlanCreate.model_validate(b.model_dump(mode="json")))


def test_manual_item_same_as_before_6a(table):
    """MANUAL 요청의 저장 항목이 6a 전(compute_metrics만)과 같다: 지표 키·값과 나머지 속성."""
    b = plan_body("MANUAL")
    plan, _ = plan_service.create_plan(OWNER, "k1", b, NOW)
    assert plan["metrics"] == plan_service.compute_metrics(b)
    assert set(plan) == {"PK", "SK", "planId", "areaId", "ownerId", "title", "summary", "reason", "estimatedMinutes", "places",
                         "question", "status", "createdAt", "version", "metrics", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "ownerNickname"}
