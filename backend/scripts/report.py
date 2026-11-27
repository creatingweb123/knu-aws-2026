"""시범 운영 성과 집계 (BE-OBS-04, docs/02 §2.9 "시범 운영 지표"). 읽기 전용이다.

  python scripts/report.py --local                                  # 로컬(Floci) 대상 콘솔 출력
  python scripts/report.py --stack haru-demo                        # AWS 스택 대상(CloudFormation으로 테이블 이름만 읽고 DynamoDB Scan)
  python scripts/report.py --local --json out.json --csv out.csv    # 파일 출력(- 는 표준 출력)
  python scripts/report.py --local --llm fake                       # Fake 모델 데이터만(형식 검증용, 성과 근거 아님)
  python scripts/report.py --local --check-invariants               # 전달 불변식 감사

대상은 `--local` 또는 `--stack` 중 하나를 명시한다. 테이블에는 **쓰지 않는다**. Scan은 필요한 속성만 ProjectionExpression으로 읽고
(사연·글 본문·답장 본문·닉네임·계획 제목은 읽지 않는다) LastEvaluatedKey로 끝까지 이어 읽는다.

지표 정의 (분모·제외·누락값)
- 기본으로 시드 데이터(`Plan.seed` 태그)와 그 Claim·Record·InboxItem은 뺀다. `--include-seed`로 넣는다.
- 생성된 계획 수: Plan 수. 분모 없음.
- 이어받기 건수: Claim 수(상태별 분해 포함)와 이어받은 계획 수.
- 확정 Claim: 상태가 COMPLETED·ABANDONED·EXPIRED이거나, ACTIVE인데 dueAt이 기준 시각(--now, 기본 현재)보다 이른 것.
  기한이 남은 ACTIVE는 미확정(pending)이라 비율의 분모에서 뺀다. `--exclude-abandoned`면 ABANDONED도 뺀다(팀 결정 전이라 기본은 포함).
- 방문 기록 완료율: COMPLETED / 확정 Claim. 분모 0이면 null.
- 기한 내 방문 기록: 확정 Claim 중 claimedAt 오름차순 처음 N개(`--first-n`, 기본 5)에서 COMPLETED이면서 late가 false인 수 / N. 확정 Claim이 N개보다 적으면
  분모는 가진 수이고 `complete=false`로 표시한다(목표 "3/5"는 5건이 찬 뒤에만 판정). 전체 기한 내 비율(COMPLETED & !late / 확정 Claim)도 같이 낸다.
- 답장률: reply가 있는 InboxItem / InboxItem(전달된 기록) 수. 분모 0이면 null.
- 작성 시간 중앙값: Plan.metrics.authoringMode(MANUAL·AI_EDITED)별 durationMs 중앙값. AI_EDITED는 agentWaitMs·answerWaitMs·editMs 중앙값도 낸다
  (그 값이 있는 Plan만. 없는 Plan은 n에서 빠지고 `missing`으로 센다).
- 원문 충실도·AI 지표: addedNotInSource(모드별 합·평균, MANUAL과 비교 가능한 사연 기준), addedNotInSourceOrAnswers, firstProposalNotInSource,
  deliveredNotInSource(DEGRADED 제외 합과 0이 아닌 Plan 수), agentSelfRepairs, questionsAsked·questionsSkipped(건너뜀 비율),
  privacyDetected·privacyInPublished(합, 목표 0), modelCalls(합·평균), fieldsEditedAfterHandoff(평균).
- AI 대기 시간 = agentWaitMs, 사용자 편집 시간 = editMs, 질문 응답 시간 = answerWaitMs. 모두 Plan.metrics에 저장된 값이다.
  턴 응답 시간 p95(AgentTurnMs)는 DynamoDB가 아니라 CloudWatch에서 본다(대시보드).
- agentMode별 비교(PIPELINE·AGENT·DEGRADED): Plan 수, 중앙값(durationMs·agentWaitMs·editMs), 평균(위 지표).
- 값이 없는 지표는 0으로 채우지 않는다. 그 지표의 n에서 빠지고 missing으로 센다. 계산할 데이터가 없으면 값은 null이다.

Fake 모델 데이터와 실제 모델 데이터는 섞지 않는다
- AI 지표는 Plan.metrics.llmMode(AiSession의 공급자)로 나눈다: real(bedrock·openai_compat), fake, unknown(값 없음).
  `--llm`(기본 real)이 고른 한 묶음만 AI 지표에 들어간다. 다른 묶음의 Plan 수는 `aiDatasets`에 따로 보인다.
  MANUAL Plan은 사람이 쓴 데이터라 어느 묶음을 골라도 들어간다. Fake 묶음은 성과 근거가 아니라 형식 검증용이다.

출력에는 계획·글·사연·답장 원문, 사용자 ID, 이메일을 넣지 않는다(불변식 위반의 Plan ID는 앞 8자만).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SEED_TAG = "demo-v1"
REAL_MODES = {"bedrock", "openai_compat"}
DEGRADED = "DEGRADED"
AGENT_MODES = ("PIPELINE", "AGENT", DEGRADED)
# 속성 이름은 모두 자리표시자로 쓴다(metrics·status 등 DynamoDB 예약어와 겹친다). 본문·닉네임·제목·키 값은 읽지 않는다.
_ATTRS = ("PK", "SK", "planId", "claimId", "itemId", "status", "createdAt", "completedAt", "claimedAt", "dueAt", "late", "deliveredAt",
          "photoStatus", "seed", "metrics", "areaId")
PROJECTION_NAMES = {f"#a{i}": n for i, n in enumerate(_ATTRS)} | {"#reply": "reply", "#sentAt": "sentAt"}
PROJECTION = ", ".join([*(f"#a{i}" for i in range(len(_ATTRS))), "#reply.#sentAt"])


def plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    return v


def parse_ts(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def rate(num: int, den: int) -> float | None:
    return round(100 * num / den, 1) if den else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def llm_dataset(metrics: dict[str, Any]) -> str:
    mode = metrics.get("llmMode")
    if mode == "fake":
        return "fake"
    return "real" if mode in REAL_MODES else "unknown"


@dataclass
class Options:
    now: datetime
    first_n: int = 5
    exclude_abandoned: bool = False
    llm: str = "real"
    include_seed: bool = False
    check_invariants: bool = False


def scan_items(table: Any) -> list[dict[str, Any]]:
    """필요한 속성만 읽고 LastEvaluatedKey로 끝까지 이어 읽는다."""
    from boto3.dynamodb.conditions import Attr

    # Plan(PLAN#/META)·Claim·Record(PLAN#/CLAIM#·RECORD#)·InboxItem(USER#/INBOX#)만 읽는다. IDEM#·AISESSION#·AIQUOTA#·CLAIM#(Lookup)·SEED#는 읽지 않는다.
    flt = (Attr("PK").begins_with("PLAN#") & (Attr("SK").eq("META") | Attr("SK").begins_with("CLAIM#") | Attr("SK").begins_with("RECORD#"))) | (
        Attr("PK").begins_with("USER#") & Attr("SK").begins_with("INBOX#"))
    items: list[dict[str, Any]] = []
    start = None
    while True:
        kw: dict[str, Any] = {"FilterExpression": flt, "ProjectionExpression": PROJECTION, "ExpressionAttributeNames": PROJECTION_NAMES, "ConsistentRead": True}
        if start:
            kw["ExclusiveStartKey"] = start
        resp = table.scan(**kw)
        items += [plain(i) for i in resp.get("Items", [])]
        start = resp.get("LastEvaluatedKey")
        if not start:
            return items


def split(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"plans": [], "claims": [], "records": [], "inbox": []}
    for i in items:
        pk, sk = str(i.get("PK", "")), str(i.get("SK", ""))
        if pk.startswith("PLAN#") and sk == "META":
            out["plans"].append(i)
        elif pk.startswith("PLAN#") and sk.startswith("CLAIM#"):
            out["claims"].append(i)
        elif pk.startswith("PLAN#") and sk.startswith("RECORD#"):
            out["records"].append(i)
        elif pk.startswith("USER#") and sk.startswith("INBOX#"):
            out["inbox"].append(i)
    return out


def _stat(values: list[float], fn: Any) -> dict[str, Any]:
    return {"n": len(values), "value": fn(values)}


def _num(m: dict[str, Any], key: str) -> float | None:
    v = m.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def compute(items: list[dict[str, Any]], opts: Options) -> dict[str, Any]:
    parts = split(items)
    plans, claims, records, inbox = parts["plans"], parts["claims"], parts["records"], parts["inbox"]
    seed_ids = {p["planId"] for p in plans if p.get("seed") == SEED_TAG}
    excluded_seed = 0
    if not opts.include_seed:
        excluded_seed = len(seed_ids)
        plans = [p for p in plans if p["planId"] not in seed_ids]
        claims = [c for c in claims if c.get("planId") not in seed_ids]
        records = [r for r in records if r.get("planId") not in seed_ids]
        inbox = [i for i in inbox if i.get("planId") not in seed_ids]

    result: dict[str, Any] = {"generatedAt": opts.now.isoformat(), "options": {"firstN": opts.first_n, "excludeAbandoned": opts.exclude_abandoned,
                                                                              "llm": opts.llm, "includeSeed": opts.include_seed}}
    result["excludedSeedPlans"] = excluded_seed

    # --- 계획·이어받기
    by_status: dict[str, int] = {}
    for c in claims:
        by_status[c.get("status") or "UNKNOWN"] = by_status.get(c.get("status") or "UNKNOWN", 0) + 1
    result["plansCreated"] = len(plans)
    result["claims"] = {"total": len(claims), "byStatus": dict(sorted(by_status.items())), "plansClaimed": len({c.get("planId") for c in claims})}

    # --- 확정 Claim
    def decided(c: dict[str, Any]) -> bool:
        st = c.get("status")
        if st == "ABANDONED" and opts.exclude_abandoned:
            return False
        if st in ("COMPLETED", "ABANDONED", "EXPIRED"):
            return True
        due = parse_ts(c.get("dueAt"))
        return st == "ACTIVE" and due is not None and due < opts.now

    det = [c for c in claims if decided(c)]
    pending = sum(1 for c in claims if c.get("status") == "ACTIVE" and not decided(c))
    completed = [c for c in det if c.get("status") == "COMPLETED"]
    on_time_all = [c for c in completed if c.get("late") is False]
    first = sorted(det, key=lambda c: c.get("claimedAt") or "")[: opts.first_n]
    first_on_time = sum(1 for c in first if c.get("status") == "COMPLETED" and c.get("late") is False)
    result["recordCompletion"] = {"numerator": len(completed), "denominator": len(det), "ratePct": rate(len(completed), len(det)), "pendingExcluded": pending}
    result["onTimeRecord"] = {
        "firstN": {"n": opts.first_n, "numerator": first_on_time, "denominator": len(first), "complete": len(first) >= opts.first_n, "target": "3 of 5", "ratePct": rate(first_on_time, len(first))},
        "overall": {"numerator": len(on_time_all), "denominator": len(det), "ratePct": rate(len(on_time_all), len(det))},
    }

    # --- 답장률
    replied = sum(1 for i in inbox if isinstance(i.get("reply"), dict))
    result["replyRate"] = {"numerator": replied, "denominator": len(inbox), "ratePct": rate(replied, len(inbox)), "target": "2 or more"}

    # --- Plan.metrics
    mets = [(p, p.get("metrics") if isinstance(p.get("metrics"), dict) else {}) for p in plans]
    result["missingMetrics"] = sum(1 for _, m in mets if not m)
    datasets = {"real": 0, "fake": 0, "unknown": 0}
    ai_plans: list[dict[str, Any]] = []
    for _, m in mets:
        if m.get("authoringMode") == "AI_EDITED":
            ds = llm_dataset(m)
            datasets[ds] += 1
            if ds == opts.llm and "agentMode" in m:
                ai_plans.append(m)
    result["aiDatasets"] = {**datasets, "selected": opts.llm, "note": "AI 지표는 selected 묶음만 집계한다. 묶음을 섞지 않는다(fake는 형식 검증용)."}
    manual = [m for _, m in mets if m.get("authoringMode") == "MANUAL"]
    ai_all_selected = [m for _, m in mets if m.get("authoringMode") == "AI_EDITED" and llm_dataset(m) == opts.llm]

    def per_mode(group: list[dict[str, Any]], key: str) -> list[float]:
        return [v for m in group if (v := _num(m, key)) is not None]

    modes = {"MANUAL": manual, "AI_EDITED": ai_all_selected}
    result["authoringTimeMs"] = {name: {"plans": len(g), **{"durationMsMedian": _stat(per_mode(g, "durationMs"), median)}, "missing": len(g) - len(per_mode(g, "durationMs"))} for name, g in modes.items()}
    for key in ("agentWaitMs", "answerWaitMs", "editMs"):
        result["authoringTimeMs"]["AI_EDITED"][f"{key}Median"] = _stat(per_mode(ai_all_selected, key), median)
    result["addedNotInSource"] = {name: {"plans": len(g), "sum": sum(per_mode(g, "addedNotInSource")), "mean": mean(per_mode(g, "addedNotInSource")), "n": len(per_mode(g, "addedNotInSource"))} for name, g in modes.items()}
    result["addedNotInSourceOrAnswers"] = {"AI_EDITED": {"n": len(per_mode(ai_plans, "addedNotInSourceOrAnswers")), "sum": sum(per_mode(ai_plans, "addedNotInSourceOrAnswers")), "mean": mean(per_mode(ai_plans, "addedNotInSourceOrAnswers"))}}

    nondeg = [m for m in ai_plans if m.get("agentMode") != DEGRADED]
    delivered = per_mode(nondeg, "deliveredNotInSource")
    asked, skipped = sum(per_mode(ai_plans, "questionsAsked")), sum(per_mode(ai_plans, "questionsSkipped"))
    result["aiQuality"] = {
        "aiPlans": len(ai_plans),
        "firstProposalNotInSource": {"n": len(per_mode(ai_plans, "firstProposalNotInSource")), "sum": sum(per_mode(ai_plans, "firstProposalNotInSource"))},
        "deliveredNotInSourceExcludingDegraded": {"n": len(delivered), "sum": sum(delivered), "plansNonZero": sum(1 for v in delivered if v > 0), "target": 0},
        "agentSelfRepairs": {"n": len(per_mode(ai_plans, "agentSelfRepairs")), "sum": sum(per_mode(ai_plans, "agentSelfRepairs"))},
        "missingFirstToDelivered": {"first": sum(per_mode(ai_plans, "missingFirst")), "delivered": sum(per_mode(ai_plans, "missingDelivered"))},
        "questions": {"asked": asked, "skipped": skipped, "skipRatePct": rate(int(skipped), int(asked))},
        "modelCalls": {"n": len(per_mode(ai_plans, "modelCalls")), "sum": sum(per_mode(ai_plans, "modelCalls")), "mean": mean(per_mode(ai_plans, "modelCalls"))},
        "fieldsEditedAfterHandoff": {"n": len(per_mode(ai_plans, "fieldsEditedAfterHandoff")), "mean": mean(per_mode(ai_plans, "fieldsEditedAfterHandoff"))},
    }
    # privacyInPublished는 사람이 쓴 계획도 검사한 값이다(privacyDetected는 AI 세션 값)
    pub = [*manual, *ai_all_selected]  # 선택한 AI 묶음과 사람이 쓴 계획만(묶음을 섞지 않는다)
    result["privacy"] = {"privacyInPublished": {"n": len(per_mode(pub, "privacyInPublished")), "sum": sum(per_mode(pub, "privacyInPublished")), "target": 0},
                         "privacyDetected": {"n": len(per_mode(ai_plans, "privacyDetected")), "sum": sum(per_mode(ai_plans, "privacyDetected"))}}

    cmp: dict[str, Any] = {}
    for mode in AGENT_MODES:
        g = [m for m in ai_plans if m.get("agentMode") == mode]
        cmp[mode] = {"plans": len(g), "durationMsMedian": median(per_mode(g, "durationMs")), "agentWaitMsMedian": median(per_mode(g, "agentWaitMs")), "editMsMedian": median(per_mode(g, "editMs")),
                     "addedNotInSourceMean": mean(per_mode(g, "addedNotInSource")), "deliveredNotInSourceMean": mean(per_mode(g, "deliveredNotInSource")),
                     "modelCallsMean": mean(per_mode(g, "modelCalls")), "questionsAskedMean": mean(per_mode(g, "questionsAsked")),
                     "fieldsEditedAfterHandoffMean": mean(per_mode(g, "fieldsEditedAfterHandoff"))}
    result["byAgentMode"] = cmp

    if opts.check_invariants:
        result["invariants"] = check_invariants(plans, claims, records, inbox)
    return result


def check_invariants(plans: list[dict[str, Any]], claims: list[dict[str, Any]], records: list[dict[str, Any]], inbox: list[dict[str, Any]]) -> dict[str, Any]:
    """Plan COMPLETED ↔ Claim COMPLETED ↔ Record deliveredAt ↔ InboxItem 1건 (정확히 한 번 전달의 운영 데이터 근거)."""
    claims_by_plan: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        claims_by_plan.setdefault(c.get("planId"), []).append(c)
    rec = {r.get("claimId"): r for r in records}
    inbox_by_claim: dict[str, int] = {}
    for i in inbox:
        inbox_by_claim[i.get("itemId")] = inbox_by_claim.get(i.get("itemId"), 0) + 1
    violations: list[dict[str, str]] = []

    def v(kind: str, pid: Any) -> None:
        violations.append({"kind": kind, "plan": str(pid)[:8]})

    for p in plans:
        pid = p["planId"]
        done = [c for c in claims_by_plan.get(pid, []) if c.get("status") == "COMPLETED"]
        if p.get("status") == "COMPLETED":
            if len(done) != 1:
                v("PLAN_COMPLETED_CLAIM_COUNT", pid)
        elif done:
            v("CLAIM_COMPLETED_PLAN_NOT", pid)
        for c in done:
            r = rec.get(c.get("claimId"))
            if r is None or not r.get("deliveredAt"):
                v("CLAIM_COMPLETED_RECORD_NOT_DELIVERED", pid)
            if inbox_by_claim.get(c.get("claimId"), 0) != 1:
                v("CLAIM_COMPLETED_INBOX_COUNT", pid)
    for c in claims:
        r = rec.get(c.get("claimId"))
        if c.get("status") != "COMPLETED" and r is not None and r.get("deliveredAt"):
            v("RECORD_DELIVERED_CLAIM_NOT_COMPLETED", c.get("planId"))
    known_plans = {p["planId"] for p in plans}
    for i in inbox:
        if i.get("planId") in known_plans and not any(c.get("claimId") == i.get("itemId") and c.get("status") == "COMPLETED" for c in claims_by_plan.get(i.get("planId"), [])):
            v("INBOX_WITHOUT_COMPLETED_CLAIM", i.get("planId"))
    return {"violations": len(violations), "details": violations[:50], "ok": not violations}


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------


def flat_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        else:
            rows.append({"metric": prefix, "value": "" if node is None else node})

    walk("", {k: v for k, v in result.items() if k not in ("generatedAt",)})
    return rows


def to_csv(result: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["metric", "value"], lineterminator="\n")
    w.writeheader()
    w.writerows(flat_rows(result))
    return buf.getvalue()


def _fmt(v: Any) -> str:
    return "—" if v is None else str(v)


def to_text(r: dict[str, Any]) -> str:
    L: list[str] = []
    o = r["options"]
    L.append(f"성과 집계 ({r['generatedAt']}) — AI 묶음: {o['llm']}, 시드 포함: {o['includeSeed']}, 시드 제외 Plan: {r['excludedSeedPlans']}")
    L.append(f"생성된 계획 {r['plansCreated']}건, 이어받기 {r['claims']['total']}건({r['claims']['byStatus']}), 이어받은 계획 {r['claims']['plansClaimed']}건")
    rc, ot, rr = r["recordCompletion"], r["onTimeRecord"], r["replyRate"]
    L.append(f"방문 기록 완료율: {rc['numerator']}/{rc['denominator']} = {_fmt(rc['ratePct'])}% (기한 남은 진행 중 {rc['pendingExcluded']}건 제외)")
    f = ot["firstN"]
    L.append(f"기한 내 방문 기록(처음 {f['n']}건): {f['numerator']}/{f['denominator']} = {_fmt(f['ratePct'])}% {'(판정 가능)' if f['complete'] else '(건수 부족, 판정 보류)'} / 전체 {ot['overall']['numerator']}/{ot['overall']['denominator']}")
    L.append(f"답장률: {rr['numerator']}/{rr['denominator']} = {_fmt(rr['ratePct'])}%")
    d = r["aiDatasets"]
    L.append(f"AI 묶음별 Plan 수: real {d['real']}, fake {d['fake']}, unknown {d['unknown']} (집계 대상: {d['selected']})")
    t = r["authoringTimeMs"]
    L.append(f"작성 시간 중앙값(ms): MANUAL {_fmt(t['MANUAL']['durationMsMedian']['value'])}(n={t['MANUAL']['durationMsMedian']['n']}), AI_EDITED {_fmt(t['AI_EDITED']['durationMsMedian']['value'])}(n={t['AI_EDITED']['durationMsMedian']['n']})")
    L.append(f"  AI_EDITED 구성: 에이전트 대기 {_fmt(t['AI_EDITED']['agentWaitMsMedian']['value'])}, 질문 응답 {_fmt(t['AI_EDITED']['answerWaitMsMedian']['value'])}, 편집 {_fmt(t['AI_EDITED']['editMsMedian']['value'])}")
    a = r["addedNotInSource"]
    L.append(f"addedNotInSource: MANUAL 합 {a['MANUAL']['sum']}(평균 {_fmt(a['MANUAL']['mean'])}), AI_EDITED 합 {a['AI_EDITED']['sum']}(평균 {_fmt(a['AI_EDITED']['mean'])})")
    q = r["aiQuality"]
    L.append(f"AI 품질(AI Plan {q['aiPlans']}건): firstProposalNotInSource 합 {q['firstProposalNotInSource']['sum']}, deliveredNotInSource(DEGRADED 제외) 합 {q['deliveredNotInSourceExcludingDegraded']['sum']}, 자체 수정 {q['agentSelfRepairs']['sum']}회")
    L.append(f"  질문 {q['questions']['asked']}회(건너뜀 {q['questions']['skipped']}, {_fmt(q['questions']['skipRatePct'])}%), 모델 호출 합 {q['modelCalls']['sum']}(평균 {_fmt(q['modelCalls']['mean'])}), 인계 뒤 수정 평균 {_fmt(q['fieldsEditedAfterHandoff']['mean'])}")
    p = r["privacy"]
    L.append(f"개인정보: privacyInPublished 합 {p['privacyInPublished']['sum']}(목표 0), privacyDetected 합 {p['privacyDetected']['sum']}")
    L.append("모드별 비교:")
    for mode, row in r["byAgentMode"].items():
        L.append(f"  {mode}: Plan {row['plans']}, 작성 중앙값 {_fmt(row['durationMsMedian'])}, 대기 {_fmt(row['agentWaitMsMedian'])}, 편집 {_fmt(row['editMsMedian'])}, 호출 평균 {_fmt(row['modelCallsMean'])}")
    if "invariants" in r:
        inv = r["invariants"]
        L.append(f"전달 불변식: {'위반 없음' if inv['ok'] else str(inv['violations']) + '건 위반'}")
        for x in inv["details"][:10]:
            L.append(f"  - {x['kind']} (plan {x['plan']})")
    if r["missingMetrics"]:
        L.append(f"주의: metrics가 없는 Plan {r['missingMetrics']}건(지표에서 제외, 0으로 채우지 않음)")
    return "\n".join(L)


def _write(dest: str, text: str) -> None:
    if dest == "-":
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    else:
        Path(dest).write_text(text, encoding="utf-8")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="시범 운영 성과 집계(읽기 전용).", formatter_class=argparse.RawDescriptionHelpFormatter)
    tgt = ap.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--local", action="store_true")
    tgt.add_argument("--stack")
    ap.add_argument("--json", dest="json_out", metavar="PATH", help="JSON 출력 파일(- 는 표준 출력)")
    ap.add_argument("--csv", dest="csv_out", metavar="PATH", help="CSV 출력 파일(- 는 표준 출력)")
    ap.add_argument("--first-n", type=int, default=5)
    ap.add_argument("--exclude-abandoned", action="store_true")
    ap.add_argument("--llm", choices=("real", "fake", "unknown"), default="real")
    ap.add_argument("--include-seed", action="store_true")
    ap.add_argument("--check-invariants", action="store_true")
    ap.add_argument("--now", help="기준 시각(ISO, 테스트·재현용)")
    ap.add_argument("--region", default=None)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    import boto3

    try:
        if args.local:
            from seed import SeedError, check_local_endpoint  # noqa: F401

            endpoint = check_local_endpoint(os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566"))
            os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
            os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
            session = boto3.session.Session(region_name=args.region or os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-2"))
            table_name, kw = os.environ.get("TABLE_NAME", "HaruTable"), {"endpoint_url": endpoint}
        else:
            if os.environ.get("AWS_ENDPOINT_URL"):
                raise RuntimeError("AWS_ENDPOINT_URL이 설정돼 있다. --stack은 실제 스택 대상이라 에뮬레이터 설정과 같이 쓰지 않는다.")
            session = boto3.session.Session(region_name=args.region)
            table_name = session.client("cloudformation").describe_stack_resource(StackName=args.stack, LogicalResourceId="HaruTable")["StackResourceDetail"]["PhysicalResourceId"]
            kw = {}
        table = session.resource("dynamodb", **kw).Table(table_name)
        now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)
        if now is None:
            raise RuntimeError("--now는 ISO 8601 형식이어야 한다.")
        result = compute(scan_items(table), Options(now=now, first_n=args.first_n, exclude_abandoned=args.exclude_abandoned, llm=args.llm,
                                                    include_seed=args.include_seed, check_invariants=args.check_invariants))
    except Exception as e:  # noqa: BLE001 - 대상 오류는 메시지만(값·키는 담지 않는다)
        if type(e).__name__ in ("RuntimeError", "SeedError"):
            print(f"오류: {e}", file=sys.stderr)
            return 1
        raise
    wrote_stdout = False
    if args.json_out:
        _write(args.json_out, json.dumps(result, ensure_ascii=False, indent=2))
        wrote_stdout |= args.json_out == "-"
    if args.csv_out:
        _write(args.csv_out, to_csv(result))
        wrote_stdout |= args.csv_out == "-"
    if not wrote_stdout:
        print(to_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
