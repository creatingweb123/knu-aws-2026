"""PhotoDLQ 운영자 복구 (BE-Q68, design "운영자 복구 절차"). 기본은 dry-run이다.

  python scripts/photo_dlq_recover.py --stack haru-dev            # 판정만 출력(아무것도 쓰지 않음)
  python scripts/photo_dlq_recover.py --stack haru-dev --apply    # 복구 대상만 조건부로 FAILED RETRY_EXHAUSTED

- DLQ 메시지는 ReceiveMessage(VisibilityTimeout=60)로 읽기만 한다. 삭제·redrive·가시성 변경은 하지 않는다
  (운영자가 판정을 확인한 뒤 콘솔·CLI로 직접 한다).
- 쓰기 조건: photoKey = 그 메시지의 키 AND photoStatus = PROCESSING AND attribute_not_exists(deliveredAt).
- SQS 메시지 수는 근사값이다. 처리 중 실행이 없다는 것을 확실히 하려면 런북의 이벤트 소스 매핑 끄기 절차를 먼저 한다.
- 출력에는 키·사용자 ID·URL을 남기지 않는다(claimId 앞 8자만).
"""

from __future__ import annotations

import argparse
import json
import sys
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


def resolve(stack: str, region: str | None) -> dict[str, str]:
    cfn = boto3.client("cloudformation", region_name=region)

    def phys(logical: str) -> str:
        return cfn.describe_stack_resource(StackName=stack, LogicalResourceId=logical)["StackResourceDetail"]["PhysicalResourceId"]

    return {
        "dlq_url": phys("PhotoDLQ"),  # SQS 큐의 물리 ID는 큐 URL이다
        "queue_url": phys("PhotoQueue"),
        "table": phys("HaruTable"),
        "function": phys("PhotoProcessorFunction"),
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


def read_dlq(sqs: Any, dlq_url: str, limit: int) -> list[str]:
    bodies: list[str] = []
    while len(bodies) < limit:
        msgs = sqs.receive_message(QueueUrl=dlq_url, MaxNumberOfMessages=min(10, limit - len(bodies)), VisibilityTimeout=60, WaitTimeSeconds=1).get("Messages", [])
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


def run(*, sqs: Any, cw: Any, dlq_url: str, queue_url: str, function: str | None, apply: bool, limit: int = 100, out=print) -> dict[str, Any]:
    safety = safety_check(sqs, cw, queue_url, function)
    out(f"safety queue_visible={safety['queue_visible']} queue_in_flight={safety['queue_in_flight']} concurrent_executions_max_5m={safety['concurrent_executions_max_5m']}")
    if safety["queue_in_flight"] or safety["queue_visible"]:
        out("WARNING PhotoQueue에 처리 중이거나 대기 중인 메시지가 있다. 같은 사진을 처리하는 실행이 있을 수 있다(런북 참고).")
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
    return {"safety": safety, "counts": counts}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stack", required=True)
    p.add_argument("--region")
    p.add_argument("--apply", action="store_true", help="복구 대상만 조건부로 FAILED RETRY_EXHAUSTED를 쓴다(기본은 dry-run)")
    p.add_argument("--limit", type=int, default=100)
    a = p.parse_args(argv)
    res = resolve(a.stack, a.region)
    ddb.use_table(boto3.resource("dynamodb", region_name=a.region).Table(res["table"]))
    run(sqs=boto3.client("sqs", region_name=a.region), cw=boto3.client("cloudwatch", region_name=a.region),
        dlq_url=res["dlq_url"], queue_url=res["queue_url"], function=res["function"], apply=a.apply, limit=a.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
