"""전달되지 않은 처리본(고아 후보) 점검. **읽기 전용**이다 (B-4, BE-PHOTO-05·07).

  python scripts/photo_orphans.py --stack haru-dev
  python scripts/photo_orphans.py --stack haru-dev --min-age-minutes 120 --json out.json

처리 Lambda는 처리본을 `photos/processed/{claimId}/{attemptUuid}.jpg`에 쓰고, 전달 트랜잭션이 Record.processedKey로 그 키를 가리킨다.
정상 경로는 미전달이 확정되면 자기 처리본을 지우지만, Lambda 강제 종료·삭제 실패가 겹치면 어디서도 가리키지 않는 처리본이 남을 수 있다.
이 스크립트는 그런 후보를 **찾기만 한다**. 삭제·이동·태그 변경은 하지 않는다(삭제 권한도 필요 없다). 정상적으로 전달된 사진을 지울 위험이 있는
자동 정리는 두지 않는다. 지울지는 운영자가 아래 분류를 보고 정한다.

분류 (S3 객체마다)
- `delivered`: Record.processedKey가 이 키이고 deliveredAt이 있다. 정상이다.
- `referenced_undelivered`: Record.processedKey가 이 키인데 deliveredAt이 없다. 일어나지 않아야 한다(전달 트랜잭션이 둘을 같이 쓴다). 조사 대상이다.
- `orphan_candidate`: Record가 이 키를 가리키지 않고, 마지막 수정이 `--min-age-minutes`(기본 60)보다 오래됐다. 처리 중인 시도의 처리본이 아님을 시간으로 거른다.
- `too_new`: 가리키지 않지만 아직 새로워 처리 중일 수 있다. 건드리지 않는다.
- `unparseable_key`: 키 형식이 맞지 않는다.
Record가 아예 없으면(`no_record`) Claim 조회도 없는 것이고 후보로 센다.

출력에는 claimId 앞 8자와 개수만 남긴다(전체 키·URL·사용자 ID 없음). 필요한 권한: s3:ListBucket(processed/ 접두), dynamodb:GetItem.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROCESSED_PREFIX = "photos/processed/"
KEY_RE = re.compile(r"^photos/processed/(clm_[0-9A-Z]{26})/([0-9a-f]{32})\.jpg$")


def classify(key: str, last_modified: datetime, record: dict[str, Any] | None, now: datetime, min_age: timedelta) -> str:
    if not KEY_RE.match(key):
        return "unparseable_key"
    if record is not None and record.get("processedKey") == key:
        return "delivered" if record.get("deliveredAt") else "referenced_undelivered"
    if now - last_modified < min_age:
        return "too_new"
    return "orphan_candidate" if record is not None else "no_record"


def iter_processed(s3: Any, bucket: str):
    token = None
    while True:
        kw: dict[str, Any] = {"Bucket": bucket, "Prefix": PROCESSED_PREFIX}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        yield from page.get("Contents", [])
        if not page.get("IsTruncated"):
            return
        token = page["NextContinuationToken"]


def lookup_record(table: Any, claim_id: str, cache: dict[str, dict[str, Any] | None]) -> dict[str, Any] | None:
    if claim_id not in cache:
        lk = table.get_item(Key={"PK": f"CLAIM#{claim_id}", "SK": "META"}, ConsistentRead=True).get("Item")
        cache[claim_id] = None if lk is None else table.get_item(Key={"PK": f"PLAN#{lk['planId']}", "SK": f"RECORD#{claim_id}"}, ConsistentRead=True).get("Item")
    return cache[claim_id]


def scan(s3: Any, table: Any, bucket: str, *, now: datetime | None = None, min_age_minutes: int = 60) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    min_age = timedelta(minutes=min_age_minutes)
    counts: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any] | None] = {}
    for obj in iter_processed(s3, bucket):
        m = KEY_RE.match(obj["Key"])
        record = lookup_record(table, m.group(1), cache) if m else None
        kind = classify(obj["Key"], obj["LastModified"], record, now, min_age)
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("orphan_candidate", "no_record", "referenced_undelivered"):
            candidates.append({"kind": kind, "claim": (m.group(1)[:12] if m else "?"), "ageMinutes": int((now - obj["LastModified"]).total_seconds() // 60), "bytes": obj["Size"]})
    return {"counts": dict(sorted(counts.items())), "candidates": candidates[:200], "minAgeMinutes": min_age_minutes, "note": "읽기 전용. 아무것도 삭제하지 않았다."}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="전달되지 않은 처리본 점검(읽기 전용).", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stack", required=True)
    ap.add_argument("--region")
    ap.add_argument("--min-age-minutes", type=int, default=60)
    ap.add_argument("--json", dest="json_out", metavar="PATH")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import boto3

    session = boto3.session.Session(region_name=args.region)
    cfn = session.client("cloudformation")
    table_name = cfn.describe_stack_resource(StackName=args.stack, LogicalResourceId="HaruTable")["StackResourceDetail"]["PhysicalResourceId"]
    bucket = cfn.describe_stack_resource(StackName=args.stack, LogicalResourceId="PhotoBucket")["StackResourceDetail"]["PhysicalResourceId"]
    result = scan(session.client("s3"), session.resource("dynamodb").Table(table_name), bucket, min_age_minutes=args.min_age_minutes)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"처리본 분류: {result['counts']}")
    for c in result["candidates"][:20]:
        print(f"  {c['kind']} claim={c['claim']} age={c['ageMinutes']}분 bytes={c['bytes']}")
    print(result["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
