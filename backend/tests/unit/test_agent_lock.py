"""6b 턴 잠금·커밋·중단 해제 (작업 1.7, design §5, moto). 실제 조건식을 moto에서 확인한다."""

from datetime import datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from domain import ai_session_service as svc
from tests.unit.moto_table import haru_table, set_env

NOW = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
SID = "ais_01ABCDEFGHJKMNPQRSTVWXYZ00"


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as t:
        yield t


def put_agent(table, **over):
    item = svc.build_agent_session_item(session_id=SID, owner_id="u1", story="출근길 빵집", created_at=NOW, lock_token="t0",
                                        lock_now_ms=NOW_MS, prompt_version="v", llm_mode="fake", llm_provider_label=None)
    item.update(over)
    for k in [k for k, v in over.items() if v is ...]:
        item.pop(k)
    item = {k: v for k, v in item.items() if v is not ...}
    table.put_item(Item=item)
    return item


QUESTION = {"questionId": "q1", "path": "estimatedMinutes", "text": "얼마나 걸릴까요?", "reason": "사연에 없어요.",
            "options": ["30분", "45분"], "allowFreeText": True}


def lock(_table, **kw):
    args = dict(owner_id="u1", expected_turn=1, token="t1", now_utc=NOW, now_ms_value=NOW_MS)
    args.update(kw)
    return svc.acquire_lock(SID, **args)


def asking(table, **over):
    base = dict(turn=1, status="ASKING", question=QUESTION, lockToken=..., lockedUntil=..., lockedAt=..., turnAttempts=0, turnRuns=[])
    base.update(over)
    return put_agent(table, **base)


def test_agent_item_shape():
    item = svc.build_agent_session_item(session_id=SID, owner_id="u1", story="s", created_at=NOW, lock_token="t0",
                                        lock_now_ms=NOW_MS, prompt_version="v", llm_mode="fake", llm_provider_label="L")
    assert (item["turn"], item["status"], item["agentMode"], item["lockToken"], item["turnRuns"], item["turnAttempts"]) == (0, "WORKING", "AGENT", "t0", ["t0"], 1)
    assert item["lockedUntil"] == NOW_MS + 30_000 and item["modelCallsReserved"] == 0 and item["ttl"] == int((NOW + timedelta(days=30)).timestamp())
    view = svc.serialize_session_view(item)
    assert view["status"] == "WORKING" and view["turn"] == 0 and view["question"] is None


def test_lock_ok_sets_working_and_run(table):
    asking(table)
    res, item = lock(table, resume={"resumeId": "r1-q1", "questionId": "q1", "choice": "45분"}, resume_question_id="q1")
    assert res == "OK" and item["status"] == "WORKING" and item["lockToken"] == "t1" and item["lockedUntil"] == NOW_MS + 30_000
    assert item["turnRuns"] == ["t1"] and int(item["turnAttempts"]) == 1 and item["pendingResume"]["choice"] == "45분"


@pytest.mark.parametrize(("over", "kw"), [
    ({"ownerId": "u2"}, {}),
    ({"turn": 2}, {}),
    ({"status": "READY"}, {}),
    ({"status": "FAILED"}, {}),
    ({"ttl": int(NOW.timestamp())}, {}),            # 만료(ttl ≤ now)
    ({"lockedUntil": NOW_MS}, {}),                  # 경계: lockedUntil = now는 잠금 중
    ({"lockedUntil": NOW_MS + 1}, {}),
])
def test_lock_conditions(table, over, kw):
    asking(table, **over)
    assert lock(table, **kw) == ("CONDITION", None)


def test_lock_missing_item(table):
    assert lock(table) == ("CONDITION", None)


def test_lock_expired_lock_is_taken(table):
    asking(table, lockedUntil=NOW_MS - 1, lockToken="old", turnRuns=["old"], turnAttempts=1)
    res, item = lock(table)
    assert res == "OK" and item["turnRuns"] == ["old", "t1"] and int(item["turnAttempts"]) == 2 and item["lockToken"] == "t1"


def test_answer_conditions(table):
    asking(table)
    # 다른 질문 id
    assert lock(table, resume={"resumeId": "r1-q9", "questionId": "q9", "choice": "x"}, resume_question_id="q9")[0] == "CONDITION"


def test_pending_resume_first_answer_wins(table):
    asking(table, lockedUntil=NOW_MS - 1, lockToken="old", pendingResume={"resumeId": "r1-q1", "questionId": "q1", "choice": "30분"},
           status="WORKING")
    res, item = lock(table, resume={"resumeId": "r1-q1", "questionId": "q1", "choice": "45분"}, resume_question_id="q1")
    assert res == "OK" and item["pendingResume"]["choice"] == "30분"  # BE-Q118


def test_finish_sets_flag(table):
    put_agent(table, turn=1, status="WORKING", lockToken=..., lockedUntil=..., lockedAt=..., turnAttempts=0, turnRuns=[])
    res, item = lock(table, finish=True)
    assert res == "OK" and item["finishRequested"] is True


def test_lock_uncertain(table, monkeypatch):
    asking(table)

    def boom(**kw):
        raise ReadTimeoutError(endpoint_url="https://x.invalid")

    monkeypatch.setattr(table, "update_item", boom)
    assert lock(table, table=table) == ("UNCERTAIN", None)


@pytest.mark.parametrize(("over", "expected"), [
    (None, "NOT_FOUND"), ({"ownerId": "u2"}, "NOT_FOUND"), ({"ttl": 1}, "NOT_FOUND"),
    ({"turn": 2}, "TURN_MISMATCH"), ({"status": "READY"}, "CLOSED"), ({"status": "FAILED"}, "CLOSED"),
    ({"lockedUntil": NOW_MS + 5}, "BUSY"), ({}, "CHANGED"),
])
def test_lock_failure_order(over, expected):
    item = None if over is None else {"ownerId": "u1", "turn": 1, "status": "ASKING", "ttl": int(NOW.timestamp()) + 10, **over}
    assert svc.lock_failure(item, owner_id="u1", expected_turn=1, now_utc=NOW, now_ms_value=NOW_MS) == expected


def commit(_table, **kw):
    args = dict(token="t1", expected_turn=1, updates={"status": "READY", "checkpointId": "c9"})
    args.update(kw)
    return svc.commit_turn(SID, **args)


def test_commit_ok_and_clears_lock(table):
    asking(table)
    lock(table, resume={"resumeId": "r1-q1", "questionId": "q1", "choice": "45분"}, resume_question_id="q1")
    assert commit(table, append_answers=[{"questionId": "q1", "choice": "45분"}], token_correction=7, recoveries=1,
                  if_absent={"firstReport": {"x": 1}}) == "OK"
    got = table.get_item(Key=svc.session_key(SID))["Item"]
    assert got["turn"] == 2 and got["status"] == "READY" and got["checkpointId"] == "c9"
    assert not {"lockToken", "lockedUntil", "lockedAt", "pendingResume"} & set(got)
    assert got["turnRuns"] == [] and got["turnAttempts"] == 0 and got["tokenCharged"] == 7 and got["recoveries"] == 1
    assert got["answers"] == [{"questionId": "q1", "choice": "45분"}] and got["firstReport"] == {"x": 1}
    assert svc.commit_landed(got, expected_turn=1, checkpoint_id="c9")


def test_commit_if_absent_keeps_first(table):
    put_agent(table, firstReport={"first": True})
    svc.commit_turn(SID, token="t0", expected_turn=0, updates={"status": "ASKING"}, if_absent={"firstReport": {"second": True}})
    assert table.get_item(Key=svc.session_key(SID))["Item"]["firstReport"] == {"first": True}


def test_commit_wrong_token_or_turn(table):
    asking(table)
    lock(table)
    assert commit(table, token="other") == "CONDITION"
    assert commit(table, expected_turn=2) == "CONDITION"
    assert commit(table) == "OK"
    assert commit(table) == "CONDITION"  # 같은 커밋 두 번 → 두 번째는 실패(중복 커밋 방지)


def test_commit_uncertain(table, monkeypatch):
    asking(table)
    lock(table)

    def boom(**kw):
        raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "UpdateItem")

    monkeypatch.setattr(table, "update_item", boom)
    assert commit(table, table=table) == "UNCERTAIN"


def test_release_lock(table):
    asking(table)
    lock(table, resume={"resumeId": "r1-q1", "questionId": "q1", "choice": "45분"}, resume_question_id="q1")
    assert svc.release_lock(SID, token="other") is False
    assert svc.release_lock(SID, token="t1") is True
    got = table.get_item(Key=svc.session_key(SID))["Item"]
    assert "lockToken" not in got and got["turn"] == 1 and got["status"] == "WORKING"
    assert got["pendingResume"]["choice"] == "45분" and got["turnAttempts"] == 1 and got["turnRuns"] == ["t1"]
    res, item = lock(table, token="t2")  # 바로 다시 잡을 수 있다
    assert res == "OK" and int(item["turnAttempts"]) == 2 and item["turnRuns"] == ["t1", "t2"]


def test_session_view_question_only_when_asking():
    base = {"sessionId": "s", "turn": 1, "question": QUESTION}
    assert svc.serialize_session_view({**base, "status": "ASKING"})["question"] == QUESTION
    assert svc.serialize_session_view({**base, "status": "WORKING"})["question"] is None
    assert svc.serialize_session_view({**base, "status": "ASKING", "question": "x"})["question"] is None


def test_pipeline_item_unchanged():
    item = svc.build_session_item(session_id=SID, owner_id="u", story="s", status="READY", created_at=NOW)
    assert "lockToken" not in item and item["agentMode"] == "PIPELINE" and not svc.is_agent_session(item)
    assert not svc.is_agent_session({k: v for k, v in item.items() if k != "agentMode"})
