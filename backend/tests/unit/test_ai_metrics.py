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
from tests.unit.agent_handler_util import agent_env  # noqa: F401
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


# ---------------------------------------------------------------- PlansFunction의 AiSession 읽기와 SDK DEBUG 로그


SECRET_ANSWER = "답변 비밀 문장 010-2222-3333"


def test_session_read_does_not_leak_into_sdk_debug_logs(table, caplog):
    """PlansFunction 로그 수준이 DEBUG여도 AiSession 조회의 botocore 응답 본문(사연·카드·답변)이 로그에 남지 않는다.
    다른 함수의 SDK 로그 수준은 바꾸지 않는다(읽는 동안만 올렸다가 되돌린다)."""
    sid = put_session(created_at=NOW - timedelta(minutes=2))
    table.update_item(Key=ai_session_service.session_key(sid), UpdateExpression="SET answers = :a",
                      ExpressionAttributeValues={":a": [{"questionId": "q1", "text": SECRET_ANSWER}]})
    before = {n: logging.getLogger(n).level for n in ("boto3", "botocore", "urllib3")}
    caplog.set_level(logging.DEBUG)
    for n in before:
        logging.getLogger(n).setLevel(logging.NOTSET)  # 루트(DEBUG)를 따르게 해 최악의 설정을 만든다
    try:
        plan, _ = plan_service.create_plan(OWNER, "k-debug", plan_body(sid=sid), NOW)
        assert "agentMode" in plan["metrics"]
        text = caplog.text
        for secret in (STORY, "하천 벤치에 앉아", CARD["title"], CARD["places"][1]["whyChosen"], SECRET_ANSWER, "010-2222-3333"):
            if secret == CARD["title"]:
                continue  # 공개되는 Plan 본문(같은 제목)은 PutItem 로그에 나올 수 있다. 세션 응답만 본다
            assert secret not in text, secret
        assert "botocore" in text or "boto3" in text  # 대조: SDK DEBUG 로그 자체는 켜져 있었다
        assert all(logging.getLogger(n).level == logging.NOTSET for n in before)  # 읽기 뒤 원래 수준으로 되돌림
    finally:
        for n, lv in before.items():
            logging.getLogger(n).setLevel(lv)


# ---------------------------------------------------------------- 6b 에이전트 세션 (작업 11.2, design §17)


def _agent_plan(agent_table, view, sid, story):
    from tests.unit.agent_handler_util import session as get_item

    card = view["card"]
    data = {k: card[k] for k in ai_metrics.SCALARS} | {"places": [dict(p, whyChosen=p["whyChosen"] or "") for p in card["places"]]}
    for k, v in {"estimatedMinutes": 45, "question": "무엇이 보였나요?", "title": "산책", "summary": "산책", "reason": "못 갔어요"}.items():
        data[k] = data[k] if data[k] is not None else v  # 빈칸은 계획자가 폼에서 채운다
    data["authoring"] = {"mode": "AI_EDITED", "durationMs": 1500, "story": story, "aiSessionId": sid}
    plan, _ = plan_service.create_plan(OWNER, f"k-{sid}", PlanCreate.model_validate(data), datetime.now(timezone.utc))
    return plan["metrics"], get_item(agent_table, sid)


def test_agent_session_metrics_after_question(agent_env, monkeypatch):
    from tests.unit.agent_handler_util import STORY as A_STORY
    from tests.unit.agent_handler_util import body_of, create, turns

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    sid = body_of(create())["sessionId"]
    view = body_of(turns(sid, {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "45분"}}))
    m, item = _agent_plan(agent_env, view, sid, A_STORY)
    [a] = item["answers"]
    assert {"askedAt", "answeredAt", "choice", "questionId", "path"} <= set(a) and a["askedAt"] <= a["answeredAt"]
    assert m["agentMode"] == "AGENT" and m["questionsAsked"] == 1 and m["questionsSkipped"] == 0
    assert m["modelCalls"] == int(item["modelCalls"]) == 4 and m["answerWaitMs"] >= 0
    assert m["missingFirst"] == len(item["firstReport"]["missing"]) and m["firstProposalNotInSource"] == len(item["firstReport"]["notInSource"])
    assert m["privacyDetected"] == int(item["privacyDetected"])


def test_agent_session_metrics_skipped_and_degraded(agent_env, monkeypatch):
    from tests.unit.agent_handler_util import STORY as A_STORY
    from tests.unit.agent_handler_util import body_of, create, turns

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    sid = body_of(create())["sessionId"]
    monkeypatch.setenv("AGENT_MODE", "pipeline")  # 모드 전환 → 결정적 폐쇄(degraded)
    view = body_of(turns(sid, {"expectedTurn": 1, "finish": True}))
    assert view["degraded"] is True
    m, item = _agent_plan(agent_env, view, sid, A_STORY)
    assert m["agentMode"] == "DEGRADED" and m["modelCalls"] == int(item.get("modelCalls") or 0)
    assert m["fieldsEditedAfterHandoff"] == sum(1 for k in ai_metrics.SCALARS if view["card"][k] is None)


def test_agent_session_privacy_answer_not_a_source(agent_env, monkeypatch):
    from tests.unit.agent_handler_util import STORY as A_STORY
    from tests.unit.agent_handler_util import body_of, create, turns

    monkeypatch.setenv("FAKE_LLM_SCENARIO", "ask_once")
    sid = body_of(create())["sessionId"]
    view = body_of(turns(sid, {"expectedTurn": 1, "answer": {"questionId": "q1", "text": "골목 카페 010-1234-5678"}}))
    m, item = _agent_plan(agent_env, view, sid, A_STORY)
    assert item["answers"][0]["privacy"] is True and m["privacyDetected"] >= 1
    assert ai_metrics.answer_sources(item["answers"]) == []


def test_session_metrics_never_carry_internal_llm_attributes():
    """6a design §15.1·정확성 13: llmMode 같은 AiSession 내부 속성은 Plan metrics에 넣지 않는다(승인 없이 응답·저장 모양을 바꾸지 않는다)."""
    m = ai_metrics.session_metrics(session(llmMode="fake", llmProviderLabel="x"), final(), STORY, "2026-11-26T03:00:00.000Z")
    assert "llmMode" not in m and "llmProviderLabel" not in m
