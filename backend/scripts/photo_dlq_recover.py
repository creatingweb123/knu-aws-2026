"""PhotoDLQ 운영자 복구 (BE-Q68, design "운영자 복구 절차"). 기본은 dry-run이다.

  python scripts/photo_dlq_recover.py --stack haru-dev                                   # 판정만 출력(DynamoDB에 쓰지 않음)
  python scripts/photo_dlq_recover.py --stack haru-dev --apply --confirm-stack haru-dev  # 안전 확인을 모두 통과하면 복구

- DLQ 메시지는 ReceiveMessage(VisibilityTimeout=60)로 읽는다. 삭제·redrive·ChangeMessageVisibility는 하지 않는다
  (운영자가 판정을 확인한 뒤 콘솔·CLI로 직접 한다). **dry-run도 ReceiveMessage를 부르므로** 읽은 메시지는 60초 동안
  다른 소비자에게 보이지 않고 수신 횟수(ApproximateReceiveCount)가 1 오른다. DLQ에는 소비자가 없으므로 데이터에는
  영향이 없지만, 그 60초 동안 콘솔의 "메시지 폴링"·redrive에서 그 메시지가 빠져 보인다.
- `--apply`는 아래 안전 확인을 **모두** 통과해야 DLQ를 읽고 쓴다. 하나라도 실패하면 DLQ를 읽지 않고 아무것도 쓰지 않고
  종료 코드 2로 끝난다. 확인을 건너뛰는 옵션은 없다.
  1. `--confirm-stack`이 `--stack`과 같다(다른 스택에 쓰는 실수 방지).
  2. 처리 함수의 이벤트 소스 매핑이 모두 `Disabled`이고, 마지막 변경 뒤 `MAPPING_QUIET_S`(60초, 함수 타임아웃 30초의 2배) 이상 지났다.
  3. PhotoQueue의 처리 중 메시지(ApproximateNumberOfMessagesNotVisible)가 `QUEUE_SAMPLES`번(간격 `QUEUE_SAMPLE_INTERVAL_S`초) 모두 0.
     값이 근사값이라 한 번만 보지 않는다. 대기 중 메시지(Visible)는 매핑이 꺼져 있으면 처리되지 않으므로 막지 않는다.
  4. 처리 함수의 CloudWatch `ConcurrentExecutions`(함수 차원)를 읽을 수 있고, 매핑을 끈 시각 + 함수 타임아웃 이후 최대값이 0.
     권한이 없거나 조회에 실패하면 통과로 보지 않는다.
- 쓰기 조건: photoKey = 그 메시지의 키 AND photoStatus = PROCESSING AND attribute_not_exists(deliveredAt).
- SQS 메시지 수는 근사값이다. 처리 중 실행이 없다는 것을 확실히 하려면 런북의 이벤트 소스 매핑 끄기 절차를 먼저 한다.
- 출력에는 키·사용자 ID·URL을 남기지 않는다(claimId 앞 8자만).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import boto3  # noqa: E402

from common import ddb, s3  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from domain.photo_image import RETRY_EXHAUSTED  # noqa: E402
from domain.plan_service import _get  # noqa: E402

RECOVER, ALREADY_FAILED, STALE, UPLOAD_PENDING, ABNORMAL, UNPARSEABLE = (
    "recover", "already_failed", "stale_message", "upload_pending", "abnormal_ready", "unparseable",
)
APPLIED, CHANGED = "applied", "changed_meanwhile"

FUNCTION_TIMEOUT_S = 30  # template.yaml PhotoProcessorFunction Timeout
MAPPING_QUIET_S = 2 * FUNCTION_TIMEOUT_S
QUEUE_SAMPLES = 3
QUEUE_SAMPLE_INTERVAL_S = 5
DLQ_VISIBILITY_S = 60
EXIT_BLOCKED = 2


class ApplyBlocked(Exception):
    """--apply 안전 확인 실패. 사유 목록을 담는다."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def resolve(stack: str, region: str | None) -> dict[str, str]:
    cfn = boto3.client("cloudformation", region_name=region)

    def phys(logical: str) -> str:
        return cfn.describe_stack_resource(StackName=stack, LogicalResourceId=logical)["StackResourceDetail"]["PhysicalResourceId"]

    return {
        "dlq_url": phys("PhotoDLQ"),  # SQS 큐의 물리 ID는 큐 URL이다
        "queue_url": phys("PhotoQueue"),
        "table": phys("HaruTable"),
        "function": phys("PhotoProcessorFunction"),
        "mapping": phys("PhotoProcessorQueueMapping"),  # 이벤트 소스 매핑의 물리 ID는 UUID다
    }


def safety_check(sqs: Any, cw: Any, queue_url: str, function: str | None) -> dict[str, Any]:
    attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    out: dict[str, Any] = {"queue_visible": int(attrs.get("ApproximateNumberOfMessages", 0)), "queue_in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)), "concurrent_executions_max_5m": None}
    if cw is not None and function:
        try:
            now = datetime.now(timezone.utc)
            points = cw.get_metric_statistics(Namespace="AWS/Lambda", MetricName="ConcurrentExecutions", Dimensions=[{"Name": "FunctionName", "Value": function}],
                                              StartTime=now - timedelta(minutes=5), EndTime=now, Period=60, Statistics=["Maximum"])["Datapoints"]
            out["concurrent_executions_max_5m"] = max((p["Maximum"] for p in points), default=0)
        except Exception as e:  # noqa: BLE001  권한이 없으면 "확인 못 함"
            out["concurrent_executions_max_5m"] = f"unavailable:{type(e).__name__}"
    return out


def _utc(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, timezone.utc)
    return None


def mapping_check(lam: Any, function: str, mapping: str | None, now: datetime) -> tuple[list[str], dict[str, Any]]:
    """처리 함수의 이벤트 소스 매핑이 모두 Disabled이고 충분히 오래 꺼져 있는지. (실패 사유, 관측값)."""
    reasons: list[str] = []
    seen: dict[str, Any] = {"mappings": [], "disabled_since": None}
    try:
        items = lam.list_event_source_mappings(FunctionName=function).get("EventSourceMappings", [])
    except Exception as e:  # noqa: BLE001
        return [f"mapping_unavailable:{type(e).__name__}"], seen
    if mapping and mapping not in {m.get("UUID") for m in items}:
        reasons.append("mapping_not_found")
    if not items:
        reasons.append("mapping_not_found")
    latest: datetime | None = None
    for m in items:
        state = m.get("State")
        changed = _utc(m.get("LastModified"))
        seen["mappings"].append({"state": state, "lastModified": changed.isoformat() if changed else None})
        if state != "Disabled":
            reasons.append(f"mapping_not_disabled:{state}")
        if changed is None:
            reasons.append("mapping_last_modified_unknown")
        elif latest is None or changed > latest:
            latest = changed
    seen["disabled_since"] = latest
    if latest is not None and (now - latest).total_seconds() < MAPPING_QUIET_S:
        reasons.append(f"mapping_disabled_less_than_{MAPPING_QUIET_S}s")
    return sorted(set(reasons)), seen


def in_flight_check(sqs: Any, queue_url: str, sleep: Callable[[float], None]) -> tuple[list[str], list[int]]:
    samples: list[int] = []
    for i in range(QUEUE_SAMPLES):
        if i:
            sleep(QUEUE_SAMPLE_INTERVAL_S)
        attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessagesNotVisible"])["Attributes"]
        samples.append(int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)))
    return (["queue_in_flight_not_zero"] if any(samples) else []), samples


def executions_check(cw: Any, function: str, since: datetime | None, now: datetime) -> tuple[list[str], Any]:
    """매핑을 끈 뒤(+함수 타임아웃) 실행이 없었는지. 지표가 없으면(호출 없음) 0으로 본다. 조회 실패는 실패다."""
    if cw is None:
        return ["executions_unavailable:no_client"], None
    start = max((since or now) + timedelta(seconds=FUNCTION_TIMEOUT_S), now - timedelta(minutes=10))
    if start >= now:
        start = now - timedelta(seconds=60)
    try:
        points = cw.get_metric_statistics(Namespace="AWS/Lambda", MetricName="ConcurrentExecutions",
                                          Dimensions=[{"Name": "FunctionName", "Value": function}],
                                          StartTime=start, EndTime=now, Period=60, Statistics=["Maximum"])["Datapoints"]
    except Exception as e:  # noqa: BLE001
        return [f"executions_unavailable:{type(e).__name__}"], None
    peak = max((p["Maximum"] for p in points), default=0)
    return (["executions_after_disable"] if peak else []), peak


def apply_gate(*, stack: str, confirm_stack: str | None, sqs: Any, cw: Any, lam: Any, queue_url: str, function: str | None,
               mapping: str | None, now: datetime, sleep: Callable[[float], None]) -> dict[str, Any]:
    """--apply 전 안전 확인. 하나라도 실패하면 ApplyBlocked. 통과하면 관측값을 돌려준다."""
    reasons: list[str] = []
    if confirm_stack != stack:
        reasons.append("confirm_stack_mismatch")
    if not function or lam is None:
        reasons.append("function_unknown")
        raise ApplyBlocked(reasons)
    m_reasons, m_seen = mapping_check(lam, function, mapping, now)
    q_reasons, samples = in_flight_check(sqs, queue_url, sleep)
    e_reasons, peak = executions_check(cw, function, m_seen["disabled_since"], now)
    reasons += m_reasons + q_reasons + e_reasons
    if reasons:
        raise ApplyBlocked(reasons)
    return {"mappings": m_seen["mappings"], "in_flight_samples": samples, "executions_peak": peak}


def read_dlq(sqs: Any, dlq_url: str, limit: int) -> list[str]:
    bodies: list[str] = []
    while len(bodies) < limit:
        msgs = sqs.receive_message(QueueUrl=dlq_url, MaxNumberOfMessages=min(10, limit - len(bodies)), VisibilityTimeout=DLQ_VISIBILITY_S, WaitTimeSeconds=1).get("Messages", [])
        if not msgs:
            break
        bodies += [m["Body"] for m in msgs]
    return bodies


def keys_of(body: str) -> list[str]:
    try:
        doc = json.loads(body)
    except ValueError:
        return []
    return [unquote_plus(r.get("s3", {}).get("object", {}).get("key", "")) for r in doc.get("Records", []) if isinstance(r, dict)]


def judge(key: str) -> tuple[str, str | None, str | None]:
    parsed = s3.parse_original_key(key)
    if parsed is None:
        return UNPARSEABLE, None, None
    claim_id = parsed[0]
    lookup = _get(f"CLAIM#{claim_id}")
    if lookup is None:
        return STALE, None, claim_id
    plan_id = lookup["planId"]
    rec = _get(f"PLAN#{plan_id}", f"RECORD#{claim_id}")
    if rec is None or rec.get("deliveredAt") or rec.get("photoStatus") == cs.PHOTO_DISCARDED or rec.get("photoKey") != key:
        return STALE, plan_id, claim_id
    status = rec.get("photoStatus")
    if status == cs.PHOTO_PROCESSING:
        return RECOVER, plan_id, claim_id
    if status == cs.PHOTO_FAILED:
        return ALREADY_FAILED, plan_id, claim_id
    if status == cs.PHOTO_UPLOAD_PENDING:
        return UPLOAD_PENDING, plan_id, claim_id
    return ABNORMAL, plan_id, claim_id  # READY 미전달 등(BE-Q66)


def run(*, sqs: Any, cw: Any, dlq_url: str, queue_url: str, function: str | None, apply: bool, limit: int = 100, out=print,
        lam: Any = None, mapping: str | None = None, stack: str = "", confirm_stack: str | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc), sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    safety = safety_check(sqs, cw, queue_url, function)
    out(f"safety queue_visible={safety['queue_visible']} queue_in_flight={safety['queue_in_flight']} concurrent_executions_max_5m={safety['concurrent_executions_max_5m']}")
    if safety["queue_in_flight"] or safety["queue_visible"]:
        out("WARNING PhotoQueue에 처리 중이거나 대기 중인 메시지가 있다. 같은 사진을 처리하는 실행이 있을 수 있다(런북 참고).")
    gate: dict[str, Any] | None = None
    if apply:
        try:
            gate = apply_gate(stack=stack, confirm_stack=confirm_stack, sqs=sqs, cw=cw, lam=lam, queue_url=queue_url,
                              function=function, mapping=mapping, now=now(), sleep=sleep)
        except ApplyBlocked as e:
            out("BLOCKED --apply 안전 확인 실패: " + " ".join(e.reasons))
            out("DLQ를 읽지 않았고 아무것도 쓰지 않았다. 런북(backend/README.md 10.3절)의 매핑 끄기·실행 종료 확인 뒤 다시 실행한다.")
            return {"safety": safety, "counts": {}, "blocked": e.reasons}
        out(f"apply_gate ok in_flight_samples={gate['in_flight_samples']} executions_peak={gate['executions_peak']}")
    else:
        out(f"NOTE dry-run도 ReceiveMessage를 부른다. 읽은 DLQ 메시지는 {DLQ_VISIBILITY_S}초 동안 보이지 않고 수신 횟수가 1 오른다.")
    counts: dict[str, int] = {}
    for body in read_dlq(sqs, dlq_url, limit):
        for key in keys_of(body) or [""]:
            verdict, plan_id, claim_id = judge(key)
            action = "-"
            if verdict == RECOVER and apply:
                written = cs.photo_status_update(plan_id, claim_id, key=key, to=cs.PHOTO_FAILED, allowed_from=(cs.PHOTO_PROCESSING,), error=RETRY_EXHAUSTED)
                action = APPLIED if written else CHANGED
                counts[action] = counts.get(action, 0) + 1
            counts[verdict] = counts.get(verdict, 0) + 1
            out(f"{verdict:<16} claim={(claim_id or '-')[:8]}… action={action}")
    out(f"summary mode={'apply' if apply else 'dry-run'} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if apply:
        m_after, _ = mapping_check(lam, function or "", mapping, now())
        if any(r.startswith(("mapping_not_disabled", "mapping_unavailable")) for r in m_after):
            out("WARNING 실행 중에 매핑 상태가 바뀌었다. 쓴 항목은 조건부라 깨지지 않지만 결과를 다시 확인한다: " + " ".join(m_after))
        out("NEXT 판정을 확인한 뒤 이벤트 소스 매핑을 다시 켠다(update-event-source-mapping --enabled). 스크립트는 매핑을 바꾸지 않는다.")
    return {"safety": safety, "counts": counts, "gate": gate}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stack", required=True)
    p.add_argument("--region")
    p.add_argument("--apply", action="store_true", help="복구 대상만 조건부로 FAILED RETRY_EXHAUSTED를 쓴다(기본은 dry-run). 안전 확인을 모두 통과해야 한다")
    p.add_argument("--confirm-stack", help="--apply 때 필수. --stack과 같은 값을 다시 적는다")
    p.add_argument("--limit", type=int, default=100)
    a = p.parse_args(argv)
    res = resolve(a.stack, a.region)
    ddb.use_table(boto3.resource("dynamodb", region_name=a.region).Table(res["table"]))
    result = run(sqs=boto3.client("sqs", region_name=a.region), cw=boto3.client("cloudwatch", region_name=a.region),
                 lam=boto3.client("lambda", region_name=a.region), mapping=res.get("mapping"), stack=a.stack, confirm_stack=a.confirm_stack,
                 dlq_url=res["dlq_url"], queue_url=res["queue_url"], function=res["function"], apply=a.apply, limit=a.limit)
    return EXIT_BLOCKED if result.get("blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
