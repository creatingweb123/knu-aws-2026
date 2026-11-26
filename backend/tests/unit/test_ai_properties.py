"""6a 속성 기반 테스트 (Property 29–36). 태그: Feature: backend-stage6a-ai-pipeline, Property {n}."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from domain import ai_session_service as svc

UTC = timezone.utc
PROPS = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])

text_or_none = st.none() | st.text(max_size=50)
place_st = st.fixed_dictionaries({"name": text_or_none, "activity": text_or_none, "whyChosen": text_or_none, "_src": st.integers(0, 2)})
card_st = st.fixed_dictionaries(
    {"title": text_or_none, "summary": text_or_none, "reason": text_or_none,
     "estimatedMinutes": st.none() | st.integers(10, 240), "places": st.lists(place_st, max_size=3), "question": text_or_none}
)
entry_st = st.dictionaries(st.sampled_from(["path", "type", "action", "reason", "source", "secret", "step", "tool", "summary"]), st.text(max_size=10))


# Feature: backend-stage6a-ai-pipeline, Property 31
@PROPS
@given(
    status=st.sampled_from(["READY", "FAILED", "WORKING", "ASKING", "BOGUS"]),
    card=st.none() | card_st,
    flags=st.lists(entry_st, max_size=4),
    notes=st.lists(entry_st, max_size=4),
    trace=st.lists(entry_st, max_size=4),
    degraded=st.booleans(),
    extra=st.dictionaries(st.sampled_from(["ownerId", "story", "llmMode", "firstProposal", "firstReport", "ttl", "PK", "answers", "question"]), st.text(max_size=5)),
)
def test_property_31_session_view(status, card, flags, notes, trace, degraded, extra):
    """Property 31: SessionView는 상태별 규칙을 지키고 허용 목록 밖 키가 없다. Validates: Requirements 4.1–4.4"""
    item = {"sessionId": "ais_x", "status": status, "turn": 1, "card": card, "flags": flags, "notes": notes, "trace": trace, "degraded": degraded, **extra}
    view = svc.serialize_session_view(item)
    assert list(view) == list(svc.VIEW_KEYS)
    assert view["question"] is None
    if status == "READY":
        if card is not None:
            assert set(view["card"]) == set(svc.CARD_KEYS) and isinstance(view["card"]["places"], list)
            assert all(set(p) == set(svc.PLACE_KEYS) for p in view["card"]["places"])
        assert all(set(f) == {"path", "type"} for f in view["flags"])
        assert all(set(n) == {"path", "action", "reason", "source"} for n in view["notes"])
        assert view["degraded"] is degraded
    else:
        assert view["card"] is None and view["flags"] == [] and view["notes"] == [] and view["degraded"] is False
    assert all(set(t) == {"step", "tool", "summary"} for t in view["trace"])


# Feature: backend-stage6a-ai-pipeline, Property 33
def test_property_33_quota(monkeypatch):
    """Property 33: 하루 성공한 세션 생성 수 ≤ 한도, 성공 수 = 모델을 부를 수 있었던 세션 수. Validates: Requirements 6.1, 6.3, 6.4, 6.5"""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from common.errors import ApiError
    from tests.unit.moto_table import haru_table, set_env

    set_env(monkeypatch)
    ran = {"n": 0}
    with haru_table():

        @PROPS
        @given(limit=st.integers(1, 20), requests=st.integers(0, 30), users=st.integers(1, 3), concurrent=st.booleans(),
               minute=st.integers(-3, 3))
        def check(limit, requests, users, concurrent, minute):
            ran["n"] += 1
            monkeypatch.setenv("AI_DAILY_SESSION_LIMIT", str(limit))
            base = datetime(2026, 11, 26, 15, 0, tzinfo=UTC) + timedelta(minutes=minute)  # KST 자정 근처
            names = [f"u-{uuid.uuid4()}" for _ in range(users)]
            calls = {n: 0 for n in names}
            lock = threading.Lock()

            def one(i):
                n = names[i % users]
                try:
                    svc.consume_quota(n, base)
                except ApiError as e:
                    assert e.code == "AI_QUOTA_EXCEEDED"
                    return
                with lock:
                    calls[n] += 1  # 할당량을 얻은 요청만 모델을 부른다

            if concurrent:
                with ThreadPoolExecutor(8) as ex:
                    list(ex.map(one, range(requests)))
            else:
                for i in range(requests):
                    one(i)
            for n in names:
                per_user = len(range(names.index(n), requests, users))
                assert calls[n] == min(per_user, limit)
                stored = svc.ddb.table().get_item(Key=svc.quota_key(n, base)).get("Item")
                assert (stored or {}).get("sessions", 0) == calls[n] <= limit

        check()
    assert ran["n"] >= 100, ran  # 중첩 @given은 통계에 안 나오므로 실행 횟수를 직접 확인한다


# ---------------------------------------------------------------- P29·P30: 검사·수리 불변식

from agent import repair, tools  # noqa: E402
from common.validation import AiCardDraft  # noqa: E402
from domain.privacy import HIGH  # noqa: E402

NOUNS = ["출근길", "빵집", "하천", "벤치", "동네", "골목", "카페", "공원", "서점", "시장", "다리", "산책로", "빵", "커피"]
PRIVACY = ["010-1234-5678", "a@b.co", "900101-1234567", "101동 1203호", "1호", "12가 3456", "3-1번지", "우리 집", "민지네 집", "사무실 안"]
PREDICATES = ["사기", "보기", "걷기", "쉬기", "마시기", "앉아", "들러서"]
word = st.sampled_from(NOUNS + PRIVACY)


def phrase(max_words, extra=()):
    return st.lists(st.sampled_from(NOUNS + PRIVACY + list(extra)), min_size=1, max_size=max_words).map(" ".join)


def bounded(strategy, limit):
    return st.none() | strategy.filter(lambda s: len(s) <= limit)


candidate_place = st.fixed_dictionaries({
    "name": bounded(phrase(3), 30),
    "activity": bounded(phrase(3, PREDICATES), 60),
    "whyChosen": st.none() | st.just("") | phrase(4).filter(lambda s: len(s) <= 120),
})
candidate_st = st.fixed_dictionaries({
    "title": bounded(phrase(4), 40), "summary": bounded(phrase(6), 120), "reason": bounded(phrase(6), 300),
    "estimatedMinutes": st.none() | st.integers(10, 240), "places": st.lists(candidate_place, max_size=3), "question": bounded(phrase(4), 80),
})
story_st = st.lists(st.sampled_from(NOUNS + PRIVACY), min_size=1, max_size=12).map(lambda ws: " ".join(ws) + "에 가고 싶었어요.")


def run_level0(candidate, sources):
    AiCardDraft.model_validate(candidate)  # 생성기가 유효한 Candidate만 만드는지
    work = repair.with_src(candidate)
    work, notes = repair.apply_rules(work)
    masked, allowed = [], set()
    if not tools.gate_verdict(tools.check_draft(work, sources)):
        work, more, masked, allowed = repair.apply_fallback(work, sources)
        notes += more
    flags, blocked = tools.final_check(work, sources, masked=masked, allowed_nis_activities=allowed)
    return work, flags, notes, blocked


# Feature: backend-stage6a-ai-pipeline, Property 29
@PROPS
@given(candidate=candidate_st, story=story_st)
def test_property_29_final_check_invariant(candidate, story):
    """Property 29: 규칙 노드·Fallback·Final_Check를 거친 카드는 차단 조건이 없다. Validates: Requirements 11.4–11.9"""
    sources = [story]
    work, flags, notes, blocked = run_level0(candidate, sources)
    assert blocked == []
    report = tools.check_draft(work, sources)
    assert report["schemaErrors"] == []
    assert not [h for h in report["privacy"] if h["severity"] == HIGH]
    assert not [h for h in report["privacy"] if h["kind"] == tools.PRIVATE_PLACE and tools.place_index(h["path"]) is not None
                and tools.field_of(h["path"]) in ("name", "activity")]
    assert not [p for p in report["notInSource"] if tools.field_of(p) == "name"]
    kept_paths = {n["path"] for n in notes if n["action"] == "KEPT_FLAGGED"}
    nis_flags = {f["path"] for f in flags if f["type"] == "NOT_IN_SOURCE"}
    for p in report["notInSource"]:  # 남은 활동 NOT_IN_SOURCE는 메모와 플래그가 모두 있다
        assert p in kept_paths and p in nis_flags


# Feature: backend-stage6a-ai-pipeline, Property 30
@PROPS
@given(candidate=candidate_st, story=story_st)
def test_property_30_path_bases(candidate, story):
    """Property 30: flags는 최종 카드 경로, REMOVED는 Candidate 경로, KEPT_FLAGGED는 최종 카드 경로. Validates: Requirements 4.6–4.8"""
    work, flags, notes, _ = run_level0(candidate, [story])
    final_n, cand_n = len(work["places"]), len(candidate["places"])

    def exists(path, n):
        i = tools.place_index(path)
        return i is None or i < n

    for f in flags:
        assert exists(f["path"], final_n), f
        if f["path"] != "places" and tools.place_index(f["path"]) is None:
            assert f["path"] in ("title", "summary", "reason", "estimatedMinutes", "question")
    for n in notes:
        if n["action"] == "REMOVED":
            assert tools.place_index(n["path"]) < cand_n and tools.field_of(n["path"]) in ("name", "activity")
        else:
            assert n["action"] == "KEPT_FLAGGED" and tools.place_index(n["path"]) < final_n
    removed = [tools.place_index(n["path"]) for n in notes if n["action"] == "REMOVED"]
    assert len(removed) == len(set(removed)) == cand_n - final_n  # 뺀 장소마다 REMOVED 메모 하나


# ---------------------------------------------------------------- P32: 데이터 블록

import re as _re  # noqa: E402

from agent.prompt import FULLWIDTH_LT, user_message  # noqa: E402

TAG_PIECES = ["<story>", "</story>", "<STORY>", "< / story >", "<answer>", "</answer>", "<Story attr>", "<", ">", "/", "story"]


# Feature: backend-stage6a-ai-pipeline, Property 32
@PROPS
@given(parts=st.lists(st.one_of(st.text(max_size=20), st.sampled_from(TAG_PIECES)), max_size=12))
def test_property_32_single_data_block(parts):
    """Property 32: 사용자 메시지의 데이터 블록은 하나이고 닫히지 않으며, 태그의 '<' 외 글자는 원문과 같다.
    Validates: Requirements 10.2, 10.3"""
    story = "".join(parts)
    msg = user_message(story)
    assert msg.startswith("<story>\n") and msg.endswith("\n</story>")
    inner = msg[len("<story>\n"): -len("\n</story>")]
    assert not _re.search(r"<\s*/?\s*(story|answer)\b", inner, _re.I)
    assert len(inner) == len(story)
    assert all(a == b or (a == "<" and b == FULLWIDTH_LT) for a, b in zip(story, inner, strict=True))


# ---------------------------------------------------------------- P35·P36: 레벨 0 그래프

import asyncio as _asyncio  # noqa: E402
import json as _json  # noqa: E402

from agent import graph as _graph  # noqa: E402
from agent import llm as _llm  # noqa: E402
from agent import nodes as _nodes  # noqa: E402
from agent.card import parse_card as _parse_card  # noqa: E402
from agent.fake_llm import FakeScenarioChatModel as _Fake  # noqa: E402
from agent.state import INVALID_OUTPUT as _INVALID, LLM_ERROR as _LLM_ERROR  # noqa: E402

_OK_CARD = _json.dumps({"title": "동네 산책", "summary": None, "reason": None, "estimatedMinutes": 45,
                        "places": [{"name": "빵집", "activity": "빵 사기", "whyChosen": None}], "question": None}, ensure_ascii=False)
_OUTPUTS = {"ok": _OK_CARD, "not_json": "카드를 못 만들었어요.", "schema": _OK_CARD.replace("45", "999")}
_ERRORS = ["TIMEOUT", "CONNECTION", "HTTP_400", "HTTP_429", "HTTP_5XX"]


class _ScriptedCaller:
    def __init__(self, results):
        self.results, self.calls = list(results), 0
        self.settings = _llm.load_settings({"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local"})

    async def ainvoke(self, messages, deadline_s):
        r = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if r in _OUTPUTS:
            from langchain_core.messages import AIMessage

            return AIMessage(content=_OUTPUTS[r])
        raise _llm.LlmError(r, called=True)


class _ScriptedBudget:
    """draft는 시도마다 remaining_ms를 한 번 읽는다. 그 값을 차례로 돌려준다."""

    def __init__(self, remaining):
        self.remaining, self.reads = list(remaining), 0

    def remaining_ms(self):
        v = self.remaining[min(self.reads, len(self.remaining) - 1)]
        self.reads += 1
        return v

    def call_deadline_s(self, max_s):
        return 5.0


# Feature: backend-stage6a-ai-pipeline, Property 35
@PROPS
@given(results=st.lists(st.sampled_from(list(_OUTPUTS) + _ERRORS), min_size=2, max_size=2),
       remaining=st.lists(st.sampled_from([0, 11_999, 12_000, 20_000]), min_size=2, max_size=2))
def test_property_35_draft_attempts(results, remaining):
    """Property 35: draft 호출은 0–2회, 2회째는 첫 시도가 검증 실패이고 그때 남은 시간이 12초 이상일 때만. LLM_Error 뒤 재시도 없음.
    Validates: Requirements 9.4, 9.5, 9.6"""
    caller = _ScriptedCaller(results)
    out = _asyncio.run(_nodes.draft({"story": "빵집", "trace": []}, {"configurable": {"llm": caller, "deadline": _ScriptedBudget(remaining)}}))
    first_ok = remaining[0] >= 12_000
    expected = 0 if not first_ok else 2 if results[0] in ("not_json", "schema") and remaining[1] >= 12_000 else 1
    assert caller.calls == out["model_calls"] == expected
    if expected == 0:
        assert out["llm_error"] == _llm.TIME_BUDGET and out["last_failure"] == _LLM_ERROR
    last = results[expected - 1] if expected else None
    if last in _ERRORS:
        assert out["last_failure"] == _LLM_ERROR and out["llm_error"] == last and out["candidate"] is None
    elif last in ("not_json", "schema"):
        assert out["last_failure"] == _INVALID and out["candidate"] is None and len(out["invalid_kinds"]) == expected
    elif last == "ok":
        assert out["last_failure"] is None and out["candidate"] is not None


# Feature: backend-stage6a-ai-pipeline, Property 36
@PROPS
@given(candidate=candidate_st, story=story_st)
def test_property_36_first_proposal_preserved(candidate, story):
    """Property 36: firstProposal·firstReport는 그래프가 끝난 뒤에도 첫 check_draft의 입력·출력과 같다(Gate 통과·거부 모두).
    Validates: Requirements 5.2"""
    text = _json.dumps(candidate, ensure_ascii=False)
    parsed = _parse_card(text)
    assert parsed.ok
    fake = _Fake(scenario="prop", steps=[{"kind": "content", "text": text, "usage": True, "sleep": 0.0}])
    env = {"LLM_PROVIDER": "fake", "FAKE_LLM_ALLOWED": "true", "STAGE": "local"}
    caller = _llm.LlmCaller(_llm.load_settings(env), fake=fake, env=env)
    state = _graph.initial_state(story)
    budget = _ScriptedBudget([25_000])
    final = _asyncio.run(_graph.pipeline_graph().ainvoke(state, config={"configurable": {"llm": caller, "deadline": budget}}))
    work = repair.with_src(parsed.card)
    assert final["first_proposal"] == tools.public_card(work)
    assert final["first_report"] == tools.check_draft(work, [story])


# ---------------------------------------------------------------- P34: 유출 방지

import logging as _logging  # noqa: E402
import re as _re2  # noqa: E402

from agent import fake_llm as _fake_llm  # noqa: E402
from tests.unit.ai_handler_util import ai_env, create as _create, sessions as _sessions  # noqa: E402,F401

_HANGUL = _re2.compile(r"[\uac00-\ud7a3]")


def _windows(text, n=4):
    """4자 이상 부분 문자열 중 한글이 든 것(숫자·영문만인 창은 sessionId·시간 값과 우연히 겹칠 수 있어 따로 본다)."""
    return {text[i:i + n] for i in range(len(text) - n + 1) if _HANGUL.search(text[i:i + n]) and text[i:i + n].strip() == text[i:i + n]}


def _card_strings(card):
    out = [card.get(k) for k in ("title", "summary", "reason", "question")]
    for p in card.get("places") or []:
        out += [p.get("name"), p.get("activity"), p.get("whyChosen")]
    return [s for s in out if s]


_P34_MODES = ["card", "echo_then_card", "echo_twice", "http_401", "timeout"]


# Feature: backend-stage6a-ai-pipeline, Property 34
@PROPS
@given(story=story_st, candidate=candidate_st, mode=st.sampled_from(_P34_MODES))
def test_property_34_no_leak(ai_env, monkeypatch, caplog, capsys, story, candidate, mode):
    """Property 34: 어떤 사연·카드·시나리오에서도 로그와 trace에 사연·카드 문자열(4자 이상 부분 문자열)이 나오지 않는다.
    Validates: Requirements 4.9, 13.1, 13.2, 13.8"""
    monkeypatch.setenv("AI_DAILY_SESSION_LIMIT", "100000")
    monkeypatch.setenv("FAKE_LLM_SCENARIO", "p34")
    card_json = _json.dumps(candidate, ensure_ascii=False)
    echo = f"사연을 정리하지 못했어요: {story} / {card_json[:200]}"  # 모델이 원문을 되풀이한 응답(JSON 아님)
    steps = {
        "card": [{"kind": "content", "text": card_json, "usage": True, "sleep": 0.0}],
        "echo_then_card": [{"kind": "content", "text": echo, "usage": True, "sleep": 0.0}, {"kind": "content", "text": card_json, "usage": True, "sleep": 0.0}],
        "echo_twice": [{"kind": "content", "text": echo, "usage": True, "sleep": 0.0}],
        "http_401": [{"kind": "raise", "error": "http_401"}],
        "timeout": [{"kind": "raise", "error": "timeout"}],
    }[mode]
    monkeypatch.setitem(_fake_llm.SCENARIOS, "p34", steps)
    saved = []
    real_put = svc.put_session
    monkeypatch.setattr(svc, "put_session", lambda item, **k: (saved.append(item), real_put(item, **k)))
    caplog.clear()
    capsys.readouterr()
    with caplog.at_level(_logging.DEBUG):
        _llm.quiet_library_loggers()
        resp = _create(story)
    out = capsys.readouterr()
    assert resp["statusCode"] in (200, 502, 503) and len(saved) == 1
    item = saved[0]
    trace_text = " ".join(t["summary"] + " " + t["tool"] for t in item["trace"])
    logs = caplog.text + out.out + out.err
    secrets = _windows(story)
    for s in _card_strings(candidate):
        secrets |= _windows(s)
    for w in secrets:
        assert w not in logs, w
        assert w not in trace_text, w
    for exact in ("010-1234-5678", "a@b.co", "900101-1234567"):
        assert exact not in logs and exact not in trace_text
