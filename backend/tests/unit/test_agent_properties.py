"""6b 속성 기반 테스트 (Property 37–48). 태그: Feature: backend-stage6b-ai-agent, Property {n}.

장애 주입·상태 기계 속성은 실행 비용이 커서 max_examples 50 + 고정 @example을 쓴다(tasks.md 공통 규칙).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest
from botocore.exceptions import ReadTimeoutError
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from agent import budget as b
from domain import ai_session_service as svc

NOW = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
PROPS = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
HEAVY = settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])


# ---------------------------------------------------------------- P37: 예약 상한

op_st = st.lists(st.tuples(st.sampled_from(["reserve", "reserve", "reserve", "uncertain_landed", "uncertain_lost", "relock", "steal"]),
                           st.integers(0, 9_000)), max_size=30)


# Feature: backend-stage6b-ai-agent, Property 37
@PROPS
@given(ops=op_st)
@example(ops=[("reserve", 5000)] * 10)
@example(ops=[("uncertain_landed", 1)] * 8 + [("reserve", 1)])
def test_property_37_reservation_cap(ops):
    """Property 37: 임의의 예약·불확실·잠금 교체 열에서 modelCallsReserved ≤ 6, 실제 호출 ≤ 예약, tokenCharged ≤ 30,000,
    카운터는 줄지 않는다. Validates: Requirements 11.1, 11.4, 11.8 · BE-Q97"""
    from moto import mock_aws

    from tests.unit.moto_table import _shared_table, create_haru_table

    sid = "ais_01ABCDEFGHJKMNPQRSTVWXYZ00"
    with mock_aws():
        t = _shared_table()
        create_haru_table(t.meta.client)
        t.put_item(Item=svc.build_agent_session_item(session_id=sid, owner_id="u", story="s", created_at=NOW, lock_token="L0",
                                                     lock_now_ms=NOW_MS, prompt_version=None, llm_mode="fake", llm_provider_label=None))
        token, run = "L0", 0
        svc_ = b.BudgetService(sid, token, reserved=0, charged=0, table=t)
        calls, last = 0, (0, 0)
        real = t.update_item
        for op, est in ops:
            if op in ("relock", "steal"):
                run += 1
                token = f"L{run}"
                t.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockToken = :t", ExpressionAttributeValues={":t": token})
                if op == "relock":  # 새 실행이 잠금 시점 값을 모른다고 가정(reserved=0)해도 DB가 상한을 지킨다
                    svc_ = b.BudgetService(sid, token, reserved=0, charged=0, table=t)
                continue
            if op.startswith("uncertain"):
                def flaky(_landed=(op == "uncertain_landed"), **kw):
                    if _landed:
                        real(**kw)
                    raise ReadTimeoutError(endpoint_url="https://x.invalid")
                t.update_item = flaky
            try:
                svc_.reserve(est)
                calls += 1  # 예약이 확정됐을 때만 호출한다
            except (b.BudgetExhausted, b.ReservationUncertain, b.FenceLost):
                pass
            finally:
                t.update_item = real
            item = t.get_item(Key=svc.session_key(sid))["Item"]
            now = (int(item["modelCallsReserved"]), int(item["tokenCharged"]))
            assert now[0] <= b.MAX_MODEL_CALLS and now[1] <= b.MAX_INPUT_TOKENS
            assert calls <= now[0]
            assert now[0] >= last[0] and now[1] >= last[1]
            last = now


# ---------------------------------------------------------------- P46: 계보 선택과 TTL

run_kind = st.sampled_from(["legit", "late_unknown", "wrong_turn", "bad_resume", "late_prev_attempt"])


# Feature: backend-stage6b-ai-agent, Property 46
@HEAVY
@given(kinds=st.lists(run_kind, min_size=1, max_size=4), ttl_left=st.integers(120, 30 * 86400))
@example(kinds=["legit", "late_unknown"], ttl_left=3600)
@example(kinds=["legit", "legit", "late_prev_attempt"], ttl_left=3600)
@example(kinds=["bad_resume", "legit", "legit"], ttl_left=120)
def test_property_46_tip_selection_and_ttl(kinds, ttl_left):
    """Property 46: 체크포인트 ttl ≤ AiSession ttl. 임의의 늦은 쓰기·포크·표지 오염에서 tip은 커밋 기준의 자손이고
    조상은 이번 턴·turnRuns 실행·알려진 resumeId만 담으며, 더 큰 시도 가지가 있으면 그 가지에서 고른다.
    Validates: Requirements 6.3, 7.1 · BE-Q94, BE-Q104"""
    import time

    import boto3
    from langgraph.types import Command
    from moto import mock_aws

    from agent import checkpoint as ck
    from tests.unit.test_agent_checkpoint import ANS, TABLE, create_table, graph, hist, run

    with mock_aws():
        c = boto3.client("dynamodb", region_name="ap-northeast-2")
        create_table(c)
        store = ck.CheckpointStore(TABLE, region_name="ap-northeast-2")
        now = time.time()
        session_ttl = int(now) + ttl_left
        saver = store.for_run(session_ttl=session_ttl, now_epoch=now)
        app = graph(saver)
        run(app, {"log": []}, "p", 1, "R1", 1)
        base = ck.checkpoint_id_of(saver.last_config)
        turn_runs, legit_attempts = [], []
        for i, k in enumerate(kinds):
            rid = f"X{i}"
            if k == "legit":
                turn_runs.append(rid)
                run(app, Command(resume=ANS), "p", 2, rid, len(turn_runs), ckpt=base, resume_id="r1-q1")
                legit_attempts.append(len(turn_runs))
            elif k == "late_unknown":
                run(app, Command(resume=ANS), "p", 2, rid, 1, ckpt=base)
            elif k == "wrong_turn":
                run(app, Command(resume=ANS), "p", 1, rid, 1, ckpt=base)
            elif k == "bad_resume":
                run(app, Command(resume=dict(ANS, resumeId="r9-zz")), "p", 2, rid, 1, ckpt=base)
            elif k == "late_prev_attempt" and turn_runs:  # 이전 시도의 늦은 쓰기(같은 runId·attempt)
                prev = turn_runs[0]
                run(app, Command(resume=ANS), "p", 2, prev, 1, ckpt=base, resume_id="r1-q1")
        h = hist(saver, "p")
        me = "ME"
        tip = ck.select_tip(h, base=base, run_turn=2, turn_runs=turn_runs + [me], my_run_id=me, known_resume_ids={"r1-q1"})
        by = {ck.checkpoint_id_of(t.config): t for t in h}
        assert tip.kind == "TIP"
        cur, seen = tip.checkpoint_id, 0
        while cur != base:  # 조상 사슬이 모두 정당
            t = by[cur]
            assert t.metadata["runTurn"] == 2 and t.metadata["runId"] in turn_runs
            assert turn_runs.index(t.metadata["runId"]) + 1 == t.metadata["runAttempt"]
            cur = ck.checkpoint_id_of(t.parent_config)
            seen += 1
            assert seen < 64
        # 기대값을 따로 계산: 정당한 시도 중 가지 전체가 알려진 resumeId만 소비한 시도의 최댓값
        # (앞선 실행이 기준에 남긴 RESUME 쓰기가 먼저 적용되면 그 시도의 가지도 오염된다, V7)
        def clean(attempt):
            rid = turn_runs[attempt - 1]
            mine = [t for t in h if (t.metadata or {}).get("runId") == rid and t.metadata.get("runAttempt") == attempt]
            return mine and all(set((t.checkpoint.get("channel_values") or {}).get("consumed_resume_ids") or []) <= {"r1-q1"} for t in mine)
        good = [a for a in legit_attempts if clean(a)]
        if good:
            assert by[tip.checkpoint_id].metadata["runAttempt"] == max(good)
        else:
            assert tip.checkpoint_id == base
        items = [i for i in c.scan(TableName=TABLE)["Items"] if "p" in i["PK"]["S"]]
        assert all(int(i["ttl"]["N"]) <= session_ttl for i in items if "ttl" in i)


# ---------------------------------------------------------------- P40·P41: 도구 호출 묶음, 질문 규칙

name_st = st.sampled_from(["check_draft", "ask_planner", "submit_card", "search_map", ""])
args_st = st.one_of(st.just({}), st.just({"card": {"title": "t"}}),
                    st.fixed_dictionaries({"path": st.sampled_from(["estimatedMinutes", "title", 3]), "question": st.text(max_size=70),
                                           "reason": st.text(max_size=10)}))


# Feature: backend-stage6b-ai-agent, Property 40
@PROPS
@given(valid=st.lists(st.tuples(name_st, args_st), max_size=4), invalid=st.lists(name_st, max_size=3))
def test_property_40_one_tool_per_response(valid, invalid):
    """Property 40: 임의의 Tool_Call 묶음에서 실행 도구 ≤ 1, 모든 tool_call_id에 ToolMessage가 정확히 1개.
    Validates: Requirements 8.3, 8.4"""
    from langchain_core.messages import AIMessage
    from langchain_core.messages.tool import invalid_tool_call, tool_call

    from agent import agent_tools as at

    calls = [tool_call(name=n, args=a, id=f"v{i}") for i, (n, a) in enumerate(valid)]
    bad = [invalid_tool_call(name=n, args="{", id=f"x{i}", error="e") for i, n in enumerate(invalid)]
    chosen, errors = at.split_tool_calls(AIMessage(content="", tool_calls=calls, invalid_tool_calls=bad))
    ids = [c["id"] for c in calls] + [c["id"] for c in bad]
    answered = [e.tool_call_id for e in errors] + ([chosen["id"]] if chosen else [])
    assert sorted(answered) == sorted(ids)  # 모든 id에 정확히 하나(실행 호출은 도구 노드가 붙인다)
    assert chosen is None or (chosen["name"] in at.TOOL_NAMES and chosen["id"] == ids[0])


q_text = st.one_of(st.text(max_size=70), st.sampled_from(["010-1234-5678 맞나요?", "a@b.co로 보내요", "101동 1203호 앞인가요?"]))


# Feature: backend-stage6b-ai-agent, Property 41
@PROPS
@given(path=st.sampled_from(["estimatedMinutes", "places", "question", "title", "places[0].name", "places[3].activity", "x"]),
       question=q_text, reason=st.text(max_size=90), options=st.lists(st.text(max_size=18), max_size=6), free=st.booleans(),
       asked=st.lists(st.sampled_from(["estimatedMinutes", "places", "question"]), max_size=2), questions=st.integers(0, 3),
       finish=st.booleans())
def test_property_41_accepted_questions_follow_rules(path, question, reason, options, free, asked, questions, finish):
    """Property 41: 수락된 질문은 길이·개수·path 중복·허용 경로·개인정보 규칙을 모두 지킨다. Validates: Requirements 9.1–9.4"""
    from agent import agent_tools as at
    from agent.fake_llm import GOOD
    from domain.privacy import scan_privacy

    args = at.AskPlannerArgs(path=path, question=question, reason=reason, options=options, allowFreeText=free)
    why = at.validate_question(args, asked_paths=asked, questions=questions, finish_requested=finish, card=GOOD)
    if why is None:
        q = at.accepted_question(args, number=questions + 1, report=None)
        assert questions < 2 and not finish and path not in asked and at.allowed_path(path, GOOD)
        assert 1 <= len(q["text"]) <= 60 and len(q["options"]) <= 4 and all(1 <= len(o) <= 15 for o in q["options"])
        assert q["options"] or q["allowFreeText"]
        assert not scan_privacy({"q": q["text"], "r": q["reason"], **{str(i): o for i, o in enumerate(q["options"])}})
        assert q["questionId"] == f"q{questions + 1}"


# Feature: backend-stage6b-ai-agent, Property 32 (에이전트 메시지 확장)
@PROPS
@given(parts=st.lists(st.one_of(st.text(max_size=20), st.sampled_from(["<story>", "</story>", "<answer>", "</ANSWER >", "< /answer>"])), max_size=10))
def test_property_32_agent_blocks(parts):
    """6a P32를 에이전트 초안 메시지와 <answer> 블록에도 적용한다. Validates: Requirements 10.6, 16.2"""
    import re

    from agent.prompt import FULLWIDTH_LT, agent_draft_messages, answer_block

    text = "".join(parts)
    for msg, tag in ((agent_draft_messages(text)[1].content, "story"), (answer_block(text), "answer")):
        assert msg.startswith(f"<{tag}>\n") and msg.endswith(f"\n</{tag}>")
        inner = msg[len(tag) + 3: -(len(tag) + 4)]
        assert not re.search(r"<\s*/?\s*(story|answer)\b", inner, re.I)
        assert all(a == b or (a == "<" and b == FULLWIDTH_LT) for a, b in zip(text, inner, strict=True))


# ---------------------------------------------------------------- P39·P43: 그래프 경로

from agent.fake_llm import AGENT_SCENARIOS  # noqa: E402

scenario_st = st.sampled_from(sorted(AGENT_SCENARIOS))
answer_st = st.sampled_from([{"choice": "45분"}, {"skipped": True}, {"text": "동네 공원"}, {"text": "010-1234-5678"},
                             {"choice": "동선에서 빼기"}])


def _run_graph(scenario, max_calls, finish, answer, story):
    import asyncio

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agent.agent_nodes import initial_agent_state
    from agent.budget import NoopBudget
    from agent.graph import build_agent_graph
    from tests.unit.agent_util import caller, config

    app = build_agent_graph(InMemorySaver())
    c = caller(scenario, budget=NoopBudget(max_calls=max_calls))
    r = asyncio.run(app.ainvoke(initial_agent_state(story), config(c, finish=finish)))
    turn = 1
    while "__interrupt__" in r and turn < 6:
        turn += 1
        it = r["__interrupt__"][0]
        v = "continue" if it.value.get("kind") == "continue" else {"questionId": it.value["questionId"], "resumeId": f"r{turn}", **answer}
        r = asyncio.run(app.ainvoke(Command(resume={it.id: v}), config(c, run_turn=turn, finish=finish)))
    return r, c


# Feature: backend-stage6b-ai-agent, Property 39
@PROPS
@given(scenario=scenario_st, max_calls=st.integers(1, 6), finish=st.booleans(), answer=answer_st)
def test_property_39_ask_planner_dropped(scenario, max_calls, finish, answer):
    """Property 39: 마지막 호출·finishRequested·질문 2개일 때 decide에 전달된 도구 목록에 ask_planner가 없다.
    Validates: Requirements 8.2"""
    from agent import agent_tools as at
    from tests.unit.agent_util import STORY

    seen = []
    real = at.tools_for

    def spy(*, questions, finish_requested, last_call):
        out = real(questions=questions, finish_requested=finish_requested, last_call=last_call)
        seen.append((questions, finish_requested, last_call, out))
        return out

    at.tools_for = spy
    try:
        _, c = _run_graph(scenario, max_calls, finish, answer, STORY)
    finally:
        at.tools_for = real
    decide_calls = [call for call in c.fake.calls if call["tools"]]
    assert len(decide_calls) <= len(seen)
    for questions, fin, last, out in seen:
        if questions >= 2 or fin or last:
            assert "ask_planner" not in out
    for call, (_, _, _, out) in zip(decide_calls, seen, strict=False):
        assert call["tools"] == list(out)
    assert len(c.fake.calls) <= max_calls  # 예산 상한(P37의 그래프 수준 확인)


# Feature: backend-stage6b-ai-agent, Property 43
@PROPS
@given(scenario=scenario_st, max_calls=st.integers(1, 6), finish=st.booleans(), answer=answer_st,
       extra=st.sampled_from(["", " 연락처는 010-2222-3333이에요.", " 민지네 집에도 들르고 싶었어요.", " 골목 카페도 있어요."]))
def test_property_43_ready_card_has_no_block(scenario, max_calls, finish, answer, extra):
    """Property 43: 어떤 경로로 끝나도 READY 카드는 Final_Check 차단 조건이 없다(6a P29 확장). Validates: Requirements 1.4"""
    from agent import repair, tools
    from domain.privacy import HIGH
    from tests.unit.agent_util import STORY

    r, _ = _run_graph(scenario, max_calls, finish, answer, STORY + extra)
    if r.get("outcome") != "READY":
        assert r.get("final_card") is None
        return
    card = repair.with_src(r["final_card"])
    rep = tools.check_draft(card, r["sources"])
    assert rep["schemaErrors"] == [] and not [h for h in rep["privacy"] if h["severity"] == HIGH]
    assert not [h for h in rep["privacy"] if h["kind"] == tools.PRIVATE_PLACE and tools.place_index(h["path"]) is not None
                and tools.field_of(h["path"]) in ("name", "activity")]
    assert not [p for p in rep["notInSource"] if tools.field_of(p) == "name"]
    flagged = {f["path"] for f in r["flags"] if f["type"] == "NOT_IN_SOURCE"}
    assert all(p in flagged for p in rep["notInSource"]) and r["blocked"] == []


# ---------------------------------------------------------------- 핸들러 수준 속성 공통 (P38·P45·P47·P48)

FLOW = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
ANSWER_1 = {"expectedTurn": 1, "answer": {"questionId": "q1", "choice": "45분"}}


class _Crash(BaseException):
    pass


def _world(**env):
    import contextlib

    from tests.unit.agent_handler_util import agent_world

    @contextlib.contextmanager
    def cm():
        with pytest.MonkeyPatch.context() as mp, agent_world(mp, **env) as t:
            yield t, mp

    return cm()


def _expire(table, sid):
    table.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockedUntil = :p", ExpressionAttributeValues={":p": 1})


class _Injector:
    """장애 하나를 훅으로 건다. 'post'는 모델 응답 뒤 체크포인트 put 전에 걸렸는지(P45 상한 계산)."""

    def __init__(self, fault):
        from agent import checkpoint as ck

        self.kind, self.point, self.n = fault
        self.seen, self.fired, self.post, self.pending = 0, False, False, False
        self._fence_exc = ck.CheckpointFenceError

    def __call__(self, p):
        hit = False
        if self.kind == "fence":
            if p == "ckpt_writes":
                self.seen += 1
            hit = self.seen >= self.n and p in ("ckpt_writes", "ckpt_put")
        elif not self.fired and p == self.point:
            self.seen += 1
            hit = self.seen == self.n
        if hit:
            if not self.fired:
                self.post = self.pending or p == "model_response"
            self.fired = True
            raise self._fence_exc("FENCE_TIME") if self.kind == "fence" else _Crash()
        if p == "model_response":
            self.pending = True
        elif p == "ckpt_put":
            self.pending = False


crash_point_st = st.one_of(
    st.tuples(st.just("crash"), st.sampled_from(["lock_after", "model_response", "before_commit"]), st.just(1)),
    st.tuples(st.just("crash"), st.sampled_from(["ckpt_writes", "ckpt_put"]), st.integers(1, 5)),
    st.tuples(st.just("fence"), st.just("ckpt_writes"), st.integers(1, 5)),
)


# Feature: backend-stage6b-ai-agent, Property 38
@FLOW
@given(ops=st.lists(st.tuples(st.sampled_from(["current", "dup", "stale", "future", "other_choice"]),
                              st.sampled_from([None, "lock_after", "model_response", "before_commit"])), min_size=1, max_size=5),
       scenario=st.sampled_from(["ask_once", "ask_twice"]))
@example(ops=[("current", "model_response"), ("dup", None)], scenario="ask_once")
def test_property_38_commit_once_per_lock(ops, scenario):
    """Property 38: 임의의 동시·중복 턴 요청 순서에서 커밋은 lockToken당 최대 1회, turn은 커밋마다 정확히 1 오르고,
    한 resumeId는 answers에 최대 한 번. 동시 요청은 처리 중(훅 지점)에 같은 세션으로 끼어든 요청으로 만든다.
    Validates: Requirements 4, 5 · BE-Q96, BE-Q118"""
    from agent import hooks
    from tests.unit.agent_handler_util import body_of, create, get, session, turns

    with _world(FAKE_LLM_SCENARIO=scenario) as (t, mp):
        commits = []
        real = svc.commit_turn

        def spy(sid, **k):
            before = int(session(t, sid)["turn"])
            res = real(sid, **k)
            after = int(session(t, sid)["turn"])
            commits.append((k["token"], k["expected_turn"], res, before, after))
            return res

        mp.setattr(svc, "commit_turn", spy)
        sid = body_of(create())["sessionId"]
        last = None
        for kind, nested_at in ops:
            v = body_of(get(sid))
            if v["status"] in ("READY", "FAILED"):
                break
            q = v["question"]
            if kind == "dup" and last is not None:
                body = last
            else:
                body = {"expectedTurn": v["turn"] + {"stale": -1, "future": 1}.get(kind, 0)}
                if q and q["options"]:
                    choice = q["options"][-1] if kind == "other_choice" else q["options"][0]
                    body["answer"] = {"questionId": q["questionId"], "choice": choice}
                elif q:
                    body["answer"] = {"questionId": q["questionId"], "text": "다른 답" if kind == "other_choice" else "하천 산책로"}
            last = body
            fired = {"done": False}

            def nested(p, body=body, at=nested_at, fired=fired):
                if p == at and not fired["done"]:
                    fired["done"] = True
                    r = turns(sid, body)  # 처리 중인 같은 세션에 끼어든 요청
                    assert r["statusCode"] in (200, 409), r["body"]

            hooks.HOOK = nested if nested_at else None
            try:
                r = turns(sid, body)
            finally:
                hooks.HOOK = None
            assert r["statusCode"] in (200, 400, 409), r["body"]
        ok = [c for c in commits if c[2] == svc.OK]
        assert len({c[0] for c in ok}) == len(ok)                       # lockToken당 최대 1회
        assert all(c[4] == c[3] + 1 == c[1] + 1 for c in ok)             # 커밋마다 turn +1, 기대 turn에서
        item = session(t, sid)
        assert int(item["turn"]) == len(ok)
        rids = [a.get("resumeId") for a in item.get("answers") or []]
        assert len(rids) == len(set(rids)) and len(rids) <= 2
        qids = [a.get("questionId") for a in item.get("answers") or []]
        assert len(qids) == len(set(qids))


# Feature: backend-stage6b-ai-agent, Property 44
@PROPS
@given(status=st.sampled_from(["READY", "FAILED", "WORKING", "ASKING", "BOGUS"]),
       question=st.none() | st.fixed_dictionaries({"questionId": st.text(max_size=4), "path": st.text(max_size=8), "text": st.text(max_size=20),
                                                    "reason": st.text(max_size=20), "options": st.lists(st.text(max_size=5), max_size=4),
                                                    "allowFreeText": st.booleans()}, optional={"secret": st.text(max_size=3)}),
       missing_key=st.none() | st.sampled_from(["questionId", "path", "text", "reason", "options", "allowFreeText"]),
       card=st.none() | st.fixed_dictionaries({"title": st.text(max_size=5)}),
       extra=st.dictionaries(st.sampled_from(["lockToken", "pendingResume", "turnRuns", "checkpointId", "bestCard", "askedPaths",
                                              "modelCallsReserved", "story", "answers"]), st.text(max_size=5)))
def test_property_44_session_view_agent(status, question, missing_key, card, extra):
    """Property 44: SessionView는 상태별 규칙을 지키고 ASKING일 때만 question이 있다(6a P31 확장). 내부 속성은 나가지 않는다.
    Validates: Requirements 14"""
    q = dict(question) if question else None
    if q and missing_key:
        q.pop(missing_key)
    item = {"sessionId": "ais_x", "status": status, "turn": 2, "question": q, "card": card, "flags": [], "notes": [], "trace": [], **extra}
    view = svc.serialize_session_view(item)
    assert list(view) == list(svc.VIEW_KEYS)
    if status == "ASKING" and q and not missing_key:
        assert list(view["question"]) == list(svc.QUESTION_KEYS)
        assert all(isinstance(o, str) for o in view["question"]["options"]) and isinstance(view["question"]["allowFreeText"], bool)
    else:
        assert view["question"] is None
    if status != "READY":
        assert view["card"] is None and view["flags"] == [] and view["notes"] == [] and view["degraded"] is False
    flat = repr(view)
    assert all(k not in flat for k in ("lockToken", "pendingResume", "turnRuns", "checkpointId", "bestCard", "secret"))


_BASELINE: dict[str, Any] = {}


def _baseline_card():
    if "card" not in _BASELINE:
        from tests.unit.agent_handler_util import body_of, create, turns

        with _world(FAKE_LLM_SCENARIO="ask_once") as (t, _):
            sid = body_of(create())["sessionId"]
            v = body_of(turns(sid, ANSWER_1))
            _BASELINE.update(card=v["card"], flags=v["flags"], degraded=v["degraded"])
    return _BASELINE


# Feature: backend-stage6b-ai-agent, Property 45
@FLOW
@given(faults=st.lists(crash_point_st, max_size=2))
@example(faults=[("crash", "ckpt_put", 3), ("crash", "model_response", 1)])
@example(faults=[("fence", "ckpt_writes", 3), ("crash", "before_commit", 1)])
@example(faults=[("crash", "ckpt_writes", 5), ("fence", "ckpt_writes", 1)])
def test_property_45_recovery_equals_clean_run(faults):
    """Property 45: 한 턴 안의 임의 장애 지점(강제 종료·울타리, 최대 2개 + 깨끗한 시도 1회)에서 복구한 결과는 장애 없는 실행과
    같은 outcome·카드이고, 추가 모델 호출 수 ≤ '모델 응답 뒤 결과 저장 전' 장애 수. Validates: Requirements 7 · design §7"""
    from agent import hooks
    from tests.unit.agent_handler_util import body_of, create, session, turns

    base = _baseline_card()
    with _world(FAKE_LLM_SCENARIO="ask_once") as (t, _):
        sid = body_of(create())["sessionId"]
        reserved0 = int(session(t, sid)["modelCallsReserved"])
        post, view = 0, None
        for f in faults + [None]:
            inj = _Injector(f) if f else None
            hooks.HOOK = inj
            try:
                r = turns(sid, ANSWER_1)
            except _Crash:
                r = None
            finally:
                hooks.HOOK = None
            post += int(bool(inj and inj.fired and inj.post))
            _expire(t, sid)
            if r is not None and r["statusCode"] == 200 and body_of(r)["status"] == "READY":
                view = body_of(r)
                break
        assert view is not None
        item = session(t, sid)
        assert view["card"] == base["card"] and view["degraded"] is base["degraded"] and view["flags"] == base["flags"]
        assert item["turn"] == 2 and len(item["answers"]) == 1 and item["answers"][0]["choice"] == "45분"
        extra = int(item["modelCallsReserved"]) - reserved0 - 1  # 장애 없는 답변 턴은 예약 1(submit)
        assert 0 <= extra <= post and int(item["modelCallsReserved"]) <= 6


# Feature: backend-stage6b-ai-agent, Property 47
@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(kind=st.sampled_from(["asking", "working_no_candidate", "working_after_fence", "pipeline_working"]),
       body_kind=st.sampled_from(["answer", "finish", "none"]))
def test_property_47_mode_switch(kind, body_kind):
    """Property 47: pipeline 모드에서 비종료 에이전트 세션은 한 번의 잠금 요청으로 종료 상태가 되고 모델 호출 0.
    PIPELINE 비종료 세션은 500이고 바뀌지 않는다. Validates: Requirements 15 · BE-Q101"""
    from agent import hooks
    from tests.unit.agent_handler_util import body_of, create, session, turns
    from tests.unit.agent_util import Ctx
    from tests.unit.test_agent_recovery import Fence

    scenario = {"asking": "ask_once", "working_no_candidate": "slow_agent", "working_after_fence": "ask_once"}.get(kind, "happy")
    with _world(FAKE_LLM_SCENARIO=scenario) as (t, mp):
        if kind == "pipeline_working":
            item = svc.build_session_item(session_id="ais_01ABCDEFGHJKMNPQRSTVWXYZ00", owner_id="u-owner", story="s", status="WORKING",
                                          created_at=datetime.now(timezone.utc))
            svc.put_session(item)
            sid = item["sessionId"]
        elif kind == "working_no_candidate":
            sid = body_of(create(ctx=Ctx(11_000)))["sessionId"]
        else:
            sid = body_of(create())["sessionId"]
            if kind == "working_after_fence":
                hooks.HOOK = Fence(3)
                try:
                    assert body_of(turns(sid, ANSWER_1))["status"] == "WORKING"
                finally:
                    hooks.HOOK = None
        before = session(t, sid)
        mp.setenv("AGENT_MODE", "pipeline")
        reserves = []
        hooks.HOOK = lambda p: reserves.append(p) if p == "reserve" else None
        v = None
        try:
            if before["status"] == "ASKING":
                body = {"answer": ANSWER_1["answer"]} if body_kind == "answer" else {"finish": True}
            else:
                body = {"finish": True} if body_kind == "finish" else {}
            r = turns(sid, {"expectedTurn": int(before["turn"]), **body})
        finally:
            hooks.HOOK = None
        after = session(t, sid)
        if kind == "pipeline_working":
            assert r["statusCode"] == 500 and after == before
            return
        assert reserves == [] and int(after["modelCallsReserved"]) == int(before["modelCallsReserved"])
        assert after["status"] in ("READY", "FAILED") and int(after["turn"]) == int(before["turn"]) + 1
        v = json.loads(r["body"])
        if after["status"] == "READY":
            assert r["statusCode"] == 200 and v["degraded"] is True
        else:
            assert r["statusCode"] == 503 and v["error"]["code"] == "AI_UNAVAILABLE"


fault_st = st.one_of(st.just(("none", None, 0)), crash_point_st, st.just(("uncertain", "reserve", 1)), st.just(("busy", None, 0)))


# Feature: backend-stage6b-ai-agent, Property 48
@FLOW
@given(scenario=st.sampled_from(["happy", "ask_once", "ask_twice", "private_place_ask", "gate_reject_twice"]),
       faults=st.lists(fault_st, max_size=6))
@example(scenario="ask_twice", faults=[("fence", "ckpt_writes", 1)] * 6)
@example(scenario="ask_once", faults=[("busy", None, 0), ("uncertain", "reserve", 1), ("crash", "model_response", 1)])
@example(scenario="ask_once", faults=[("crash", "lock_after", 1)] * 4)
def test_property_48_frontend_terminates(scenario, faults):
    """Property 48: docs/03 규칙대로 움직이는 프론트 모형과 임의 장애(울타리 닫힘·예약 불확실·강제 종료·동시 요청)에서 세션은
    정해진 요청 수 안에 종료 상태가 되거나 오류로 끝나고, 같은 턴 시도는 4를 넘지 않는다.
    '시도'는 잠금을 잡은 실행이다. 그래프를 돌리는 시도는 턴당 3번까지이고 4번째는 모델 없이 결정적으로 닫는다(BE-Q113).
    닫는 시도 자체가 강제 종료되면 그 종료마다 잠금이 한 번 더 잡힌다(닫기만 다시 한다). 그래서 잠금 수 ≤ 4 + (닫기 중 종료 수).
    Validates: Requirements 12.4 · BE-Q121"""
    from collections import Counter

    from agent import budget as bmod
    from agent import hooks
    from tests.unit.agent_handler_util import create, get, session, turns
    from tests.unit.frontend_sim import FrontendSim, handler_transport

    with _world(FAKE_LLM_SCENARIO=scenario) as (t, mp):
        locks: Counter = Counter()
        real_lock = svc.acquire_lock

        def spy_lock(sid, **k):
            res, item = real_lock(sid, **k)
            if res == svc.OK:
                locks[k["expected_turn"]] += 1
            return res, item

        mp.setattr(svc, "acquire_lock", spy_lock)
        from handlers import ai_agent

        runs: Counter = Counter()
        closing_kills: Counter = Counter()
        real_run = ai_agent._run_graph

        def spy_run(session_, **k):
            runs[k["expected_turn"]] += 1
            return real_run(session_, **k)

        mp.setattr(ai_agent, "_run_graph", spy_run)
        queue = list(faults)
        state = {"sid": None}

        def faulty_turns(sid, body):
            state["sid"] = sid
            kind, point, n = queue.pop(0) if queue else ("none", None, 0)
            if kind == "busy":
                t.update_item(Key=svc.session_key(sid), UpdateExpression="SET lockToken = :o, lockedUntil = :u",
                              ExpressionAttributeValues={":o": "other", ":u": svc.now_ms() + 20_000})
            elif kind == "uncertain":
                def unc(p):
                    if p == "reserve":
                        hooks.HOOK = None
                        raise bmod.ReservationUncertain()
                hooks.HOOK = unc
            elif kind in ("crash", "fence"):
                hooks.HOOK = _Injector((kind, point, n))
            before = session(t, sid)
            closing = int(before.get("turnAttempts") or 0) >= svc.MAX_TURN_ATTEMPTS  # 이번 잠금이 닫는 시도
            try:
                return turns(sid, body)
            except _Crash:
                if closing:
                    closing_kills[int(before["turn"])] += 1
                raise
            finally:
                hooks.HOOK = None

        tr = handler_transport(create, faulty_turns, get, on_crash=lambda sid: _expire(t, sid), crash_types=(_Crash,))
        res = FrontendSim(**tr, sleep=lambda s: _expire(t, state["sid"]), max_requests=30).run("이사 전에 출근길 빵집에 들러 빵을 사고 하천 벤치에 앉아 쉬려고 했어요.")
        assert res.outcome in ("READY", "DIRECT_WRITE"), (res.outcome, res.requests)
        assert res.request_count <= 30
        assert all(v <= svc.MAX_TURN_ATTEMPTS for v in runs.values()), runs
        assert all(v <= 4 + closing_kills[k] for k, v in locks.items()), (locks, closing_kills)
        if state["sid"]:
            item = session(t, state["sid"])
            assert "lockToken" not in item or item.get("status") not in ("READY", "FAILED")
            assert int(item["modelCallsReserved"]) <= 6
