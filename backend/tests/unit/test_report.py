"""scripts/report.py: 손으로 계산한 값과 비교한다(분모·제외·누락값). 로컬 DynamoDB 흉내(moto)로 Scan 페이지네이션과 개인정보 비포함을 확인한다."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import report as rp  # noqa: E402

NOW = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)


def opts(**kw):
    return rp.Options(now=kw.pop("now", NOW), **kw)


def plan(pid, status="OPEN", metrics=None, seed=None):
    p = {"PK": f"PLAN#{pid}", "SK": "META", "planId": pid, "status": status}
    if metrics is not None:
        p["metrics"] = metrics
    if seed:
        p["seed"] = seed
    return p


def claim(cid, pid, status, claimed="2026-11-20T00:00:00.000Z", due="2026-11-23T00:00:00.000Z", late=None):
    c = {"PK": f"PLAN#{pid}", "SK": f"CLAIM#{cid}", "claimId": cid, "planId": pid, "status": status, "claimedAt": claimed, "dueAt": due}
    if late is not None:
        c["late"] = late
    return c


def record(cid, pid, delivered=True):
    r = {"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}", "claimId": cid, "planId": pid}
    if delivered:
        r["deliveredAt"] = "2026-11-21T00:00:00.000Z"
    return r


def inbox(cid, pid, owner="o", reply=False):
    i = {"PK": f"USER#{owner}", "SK": f"INBOX#{cid}", "itemId": cid, "planId": pid}
    if reply:
        i["reply"] = {"sentAt": "2026-11-22T00:00:00.000Z"}
    return i


MANUAL = {"authoringMode": "MANUAL", "durationMs": 100_000, "addedNotInSource": 1, "privacyInPublished": 0}


def ai(mode="PIPELINE", llm="bedrock", **kw):
    m = {"authoringMode": "AI_EDITED", "durationMs": 60_000, "addedNotInSource": 0, "privacyInPublished": 0, "agentMode": mode,
         "addedNotInSourceOrAnswers": 0, "firstProposalNotInSource": 2, "deliveredNotInSource": 0, "agentSelfRepairs": 1,
         "missingFirst": 1, "missingDelivered": 0, "questionsAsked": 2, "questionsSkipped": 1, "privacyDetected": 0,
         "agentWaitMs": 5_000, "answerWaitMs": 4_000, "editMs": 30_000, "fieldsEditedAfterHandoff": 2, "modelCalls": 3}
    if llm:
        m["llmMode"] = llm
    m.update(kw)
    return m


def dataset():
    items = [
        plan("p1", "COMPLETED", MANUAL), plan("p2", "COMPLETED", ai("AGENT", durationMs=80_000)), plan("p3", "OPEN", MANUAL | {"durationMs": 300_000}),
        plan("p4", "CLAIMED", ai("DEGRADED", deliveredNotInSource=1)), plan("p5", "CLAIMED"),
        plan("p6", "OPEN", ai("AGENT", llm="fake")), plan("s1", "OPEN", MANUAL, seed="demo-v1"),
        # Claim: 5개(처음 5개) — c1 COMPLETED 정시, c2 COMPLETED 지연, c3 ABANDONED, c4 ACTIVE 기한 지남(=확정), c5 ACTIVE 기한 남음(미확정)
        claim("c1", "p1", "COMPLETED", "2026-11-10T00:00:00.000Z", late=False), claim("c2", "p2", "COMPLETED", "2026-11-11T00:00:00.000Z", late=True),
        claim("c3", "p3", "ABANDONED", "2026-11-12T00:00:00.000Z"), claim("c4", "p4", "ACTIVE", "2026-11-13T00:00:00.000Z", "2026-11-16T00:00:00.000Z"),
        claim("c5", "p5", "ACTIVE", "2026-11-26T00:00:00.000Z", "2026-11-29T00:00:00.000Z"),
        claim("cs", "s1", "COMPLETED", late=False),  # 시드 Plan의 Claim
        record("c1", "p1"), record("c2", "p2"), record("cs", "s1"),
        inbox("c1", "p1", reply=True), inbox("c2", "p2"), inbox("cs", "s1", reply=True),
    ]
    return items


def test_counts_and_rates():
    r = rp.compute(dataset(), opts())
    assert r["excludedSeedPlans"] == 1 and r["plansCreated"] == 6
    assert r["claims"] == {"total": 5, "byStatus": {"ABANDONED": 1, "ACTIVE": 2, "COMPLETED": 2}, "plansClaimed": 5}
    # 확정 Claim = c1,c2,c3,c4 (c5는 기한이 남아 미확정). 완료 = c1,c2
    assert r["recordCompletion"] == {"numerator": 2, "denominator": 4, "ratePct": 50.0, "pendingExcluded": 1}
    f = r["onTimeRecord"]["firstN"]
    assert (f["numerator"], f["denominator"], f["complete"], f["ratePct"]) == (1, 4, False, 25.0)  # 4건뿐이라 5건 판정 보류
    assert r["onTimeRecord"]["overall"] == {"numerator": 1, "denominator": 4, "ratePct": 25.0}
    assert r["replyRate"] == {"numerator": 1, "denominator": 2, "ratePct": 50.0, "target": "2 or more"}  # 시드 InboxItem 제외


def test_exclude_abandoned_changes_denominator_only():
    r = rp.compute(dataset(), opts(exclude_abandoned=True))
    assert r["recordCompletion"]["denominator"] == 3 and r["recordCompletion"]["numerator"] == 2


def test_first_n_uses_claimed_order_and_complete_flag():
    r = rp.compute(dataset(), opts(first_n=2))
    f = r["onTimeRecord"]["firstN"]
    assert (f["numerator"], f["denominator"], f["complete"]) == (1, 2, True)  # c1(정시), c2(지연)


def test_include_seed_adds_seed_data():
    r = rp.compute(dataset(), opts(include_seed=True))
    assert r["plansCreated"] == 7 and r["claims"]["total"] == 6 and r["replyRate"]["denominator"] == 3 and r["excludedSeedPlans"] == 0


def test_authoring_medians_and_missing():
    r = rp.compute(dataset() + [plan("p7", "OPEN", {"authoringMode": "MANUAL"})], opts())
    t = r["authoringTimeMs"]
    assert t["MANUAL"]["plans"] == 3 and t["MANUAL"]["durationMsMedian"] == {"n": 2, "value": 200_000.0} and t["MANUAL"]["missing"] == 1  # 100000·300000의 중앙값
    # real 묶음 AI_EDITED = p2(AGENT), p4(DEGRADED). p6(fake)는 빠진다
    assert t["AI_EDITED"]["plans"] == 2 and t["AI_EDITED"]["durationMsMedian"]["value"] == 70_000.0
    assert t["AI_EDITED"]["agentWaitMsMedian"] == {"n": 2, "value": 5000.0} and t["AI_EDITED"]["editMsMedian"]["value"] == 30000.0


def test_fake_and_real_are_never_mixed():
    real = rp.compute(dataset(), opts(llm="real"))
    fake = rp.compute(dataset(), opts(llm="fake"))
    assert real["aiDatasets"]["real"] == 2 and real["aiDatasets"]["fake"] == 1 and real["aiQuality"]["aiPlans"] == 2
    assert fake["aiQuality"]["aiPlans"] == 1 and fake["byAgentMode"]["AGENT"]["plans"] == 1 and real["byAgentMode"]["AGENT"]["plans"] == 1
    # 같은 Plan이 두 묶음 집계에 동시에 들어가지 않는다
    assert real["aiQuality"]["modelCalls"]["sum"] == 6 and fake["aiQuality"]["modelCalls"]["sum"] == 3
    unknown = rp.compute([plan("u1", "OPEN", ai(llm=None))], opts(llm="unknown"))
    assert unknown["aiQuality"]["aiPlans"] == 1
    assert rp.compute([plan("u1", "OPEN", ai(llm=None))], opts(llm="real"))["aiQuality"]["aiPlans"] == 0  # llmMode 없으면 실제 모델로 치지 않는다


def test_ai_quality_excludes_degraded_for_delivered():
    r = rp.compute(dataset(), opts())["aiQuality"]
    # p4는 DEGRADED(deliveredNotInSource=1)라 합에서 빠진다
    assert r["deliveredNotInSourceExcludingDegraded"] == {"n": 1, "sum": 0, "plansNonZero": 0, "target": 0}
    assert r["questions"] == {"asked": 4, "skipped": 2, "skipRatePct": 50.0}
    assert r["agentSelfRepairs"]["sum"] == 2 and r["fieldsEditedAfterHandoff"]["mean"] == 2.0


def test_mode_comparison():
    c = rp.compute(dataset(), opts())["byAgentMode"]
    assert c["PIPELINE"]["plans"] == 0 and c["PIPELINE"]["durationMsMedian"] is None  # 데이터 없음은 null
    assert c["AGENT"]["durationMsMedian"] == 80_000 and c["DEGRADED"]["modelCallsMean"] == 3.0


def test_added_not_in_source_by_mode_and_privacy():
    r = rp.compute(dataset(), opts())
    assert r["addedNotInSource"]["MANUAL"] == {"plans": 2, "sum": 2, "mean": 1.0, "n": 2}
    assert r["privacy"]["privacyInPublished"]["sum"] == 0 and r["privacy"]["privacyInPublished"]["n"] == 4


def test_empty_dataset_is_null_not_zero():
    r = rp.compute([], opts())
    assert r["plansCreated"] == 0 and r["recordCompletion"]["ratePct"] is None and r["replyRate"]["ratePct"] is None
    assert r["authoringTimeMs"]["MANUAL"]["durationMsMedian"] == {"n": 0, "value": None}
    assert r["byAgentMode"]["AGENT"]["plans"] == 0
    assert "성과 집계" in rp.to_text(r)  # 빈 데이터도 출력된다
    assert rp.to_csv(r).startswith("metric,value")


def test_invariants_ok_and_violations():
    ok = rp.compute(dataset(), opts(check_invariants=True))["invariants"]
    assert ok["ok"] is True
    broken = dataset()
    broken = [i for i in broken if not (i["SK"] == "INBOX#c2")]  # 완료됐는데 InboxItem 없음
    broken.append(record("c4", "p4"))  # 완료되지 않은 Claim인데 Record가 전달됨
    inv = rp.compute(broken, opts(check_invariants=True))["invariants"]
    kinds = {v["kind"] for v in inv["details"]}
    assert not inv["ok"] and {"CLAIM_COMPLETED_INBOX_COUNT", "RECORD_DELIVERED_CLAIM_NOT_COMPLETED"} <= kinds
    assert all(len(v["plan"]) <= 8 for v in inv["details"])


def test_outputs_have_no_identifiers_or_text():
    r = rp.compute(dataset(), opts(check_invariants=True))
    blob = json.dumps(r, ensure_ascii=False) + rp.to_csv(r) + rp.to_text(r)
    for secret in ("PLAN#", "USER#", "p1\"", "c1\"", "claimerId", "ownerId"):
        assert secret not in blob


def test_csv_rows_flat():
    rows = rp.flat_rows(rp.compute(dataset(), opts()))
    names = {r["metric"] for r in rows}
    assert "recordCompletion.ratePct" in names and "aiQuality.questions.skipRatePct" in names and "generatedAt" not in names


# ---------------------------------------------------------------- Scan (moto)


@pytest.fixture
def table(monkeypatch):
    pytest.importorskip("moto")
    from tests.unit.moto_table import haru_table, set_env

    set_env(monkeypatch)
    with haru_table() as t:
        yield t


class Paged:
    """Scan을 2개씩 끊어 LastEvaluatedKey 페이지네이션을 강제한다."""

    def __init__(self, table):
        self.t, self.calls = table, 0

    def scan(self, **kw):
        self.calls += 1
        return self.t.scan(Limit=2, **kw)


def test_scan_paginates_and_never_reads_text(table):
    for i in range(7):
        table.put_item(Item={"PK": f"PLAN#p{i}", "SK": "META", "planId": f"p{i}", "status": "OPEN", "title": "비밀 제목", "ownerNickname": "닉네임", "ownerId": "u1",
                             "metrics": {"authoringMode": "MANUAL", "durationMs": 1000 * (i + 1), "addedNotInSource": 0, "privacyInPublished": 0}})
    table.put_item(Item={"PK": "PLAN#p0", "SK": "RECORD#c0", "claimId": "c0", "planId": "p0", "letter": "비밀 글", "deliveredAt": "2026-11-21T00:00:00.000Z", "photoKey": "k"})
    table.put_item(Item={"PK": "USER#u1", "SK": "INBOX#c0", "itemId": "c0", "planId": "p0", "ownerId": "u1", "planTitle": "비밀 제목", "reply": {"text": "비밀 답장", "sentAt": "2026-11-22T00:00:00.000Z"}})
    table.put_item(Item={"PK": "IDEM#u1#k", "SK": "META", "bodyHash": "x"})
    table.put_item(Item={"PK": "AISESSION#s", "SK": "META", "story": "비밀 사연"})
    paged = Paged(table)
    items = rp.scan_items(paged)
    assert paged.calls >= 3
    plans = [i for i in items if i["SK"] == "META"]
    assert len(plans) == 7 and len(items) == 9  # 계획 7 + 기록 1 + 수신함 1 (멱등 키·AI 세션은 읽지 않는다)
    blob = json.dumps(items, ensure_ascii=False)
    for text in ("비밀 제목", "비밀 글", "비밀 답장", "비밀 사연", "닉네임", "photoKey", "ownerId"):
        assert text not in blob
    inbox_item = next(i for i in items if i["SK"].startswith("INBOX#"))
    assert inbox_item["reply"] == {"sentAt": "2026-11-22T00:00:00.000Z"}
    r = rp.compute(items, opts())
    assert r["plansCreated"] == 7 and r["authoringTimeMs"]["MANUAL"]["durationMsMedian"]["value"] == 4000


def test_scan_empty_table(table):
    assert rp.scan_items(table) == []


def test_main_requires_target_and_guards_endpoint(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        rp.main([])
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    assert rp.main(["--stack", "haru-demo"]) == 1
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://dynamodb.ap-northeast-2.amazonaws.com")
    assert rp.main(["--local"]) == 1
