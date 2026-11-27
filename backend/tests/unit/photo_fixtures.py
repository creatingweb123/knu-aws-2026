"""사진 처리 테스트 공통 픽스처: moto DynamoDB(HaruTable) + S3 버킷, 이어받은 Claim, 원본 업로드, S3 이벤트.

moto는 S3 조건부 요청(IfNoneMatch·IfMatch)을 지원한다(test_photo_s3.py에서 확인).
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime, timezone
from typing import Any

import boto3
from PIL import Image

from common import s3
from common.auth import User
from common.validation import PhotoIn, PlanCreate
from domain import claim_service as cs
from domain import plan_service as ps
from tests.unit.moto_table import haru_table, set_env
from workers import photo_processor as pp

BUCKET = "haru-photos-test"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
OWNER = User("u-owner", "지연")
SUHYUN = User("u-suhyun", "수현")
MINJUN = User("u-minjun", "민준")
PLAN = {
    "title": "이사 전, 마지막 동네 산책", "summary": "출근길 빵집", "reason": "이삿짐", "estimatedMinutes": 45,
    "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}], "question": "q",
    "authoring": {"mode": "MANUAL", "durationMs": 1, "story": "출근길 빵집에 들러 빵을 사요"},
}

_s3_client = None


def _shared_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name="ap-northeast-2", aws_access_key_id="test", aws_secret_access_key="test")
    return _s3_client


@contextlib.contextmanager
def photo_env(monkeypatch):
    """moto HaruTable + 사진 버킷. 처리 Lambda가 테스트용 클라이언트를 쓰게 한다."""
    set_env(monkeypatch)
    monkeypatch.setenv("PHOTO_BUCKET", BUCKET)
    for name in ("FAULT_INJECT", "FAULT_INJECT_ALLOWED", "AWS_LAMBDA_FUNCTION_NAME", "STAGE", "PHOTO_UPLOAD_IF_NONE_MATCH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(s3, "_presign_client", None)
    with haru_table() as table:
        client = _shared_s3()
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
        monkeypatch.setattr(pp, "_s3", client)
        monkeypatch.setattr(pp, "_ready", True)
        monkeypatch.setattr(pp, "_fault_block_logged", False)
        yield table, client


def jpeg(color=(200, 30, 30), size=(640, 480), exif=None) -> bytes:
    out = io.BytesIO()
    kw = {"exif": exif} if exif is not None else {}
    Image.new("RGB", size, color).save(out, "JPEG", **kw)
    return out.getvalue()


def claimed(owner=OWNER, claimer=SUHYUN, key="k1"):
    plan = ps.create_plan(owner, key, PlanCreate.model_validate(PLAN), NOW)[0]
    claim, _ = cs.claim_plan(plan["planId"], claimer, NOW)
    return plan["planId"], claim["claimId"]


def with_photo(pid, cid, who=SUHYUN, ct="image/jpeg", letter="사진과 글"):
    """PUT /record(photo)와 같은 효과. 원본 키를 돌려준다."""
    cs.put_record_with_photo(cid, who, letter, PhotoIn(contentType=ct, size=100), NOW)
    return record(pid, cid)["photoKey"]


def upload(client, key, body: bytes) -> str:
    """브라우저 업로드 대신 SDK로 올린다. 이벤트용 eTag(따옴표 없음)를 돌려준다."""
    return client.put_object(Bucket=BUCKET, Key=key, Body=body)["ETag"].strip('"')


def s3_record(key: str, etag: str | None) -> dict[str, Any]:
    obj: dict[str, Any] = {"key": key.replace(" ", "+"), "size": 1}
    if etag is not None:
        obj["eTag"] = etag
    return {"eventSource": "aws:s3", "eventName": "ObjectCreated:Put", "s3": {"bucket": {"name": BUCKET}, "object": obj}}


def sqs_event(records: list[dict[str, Any]] | None = None, *, body: Any = None, receive_count: int = 1) -> dict[str, Any]:
    raw = body if body is not None else json.dumps({"Records": records})
    return {"Records": [{"messageId": "m1", "body": raw if isinstance(raw, str) else json.dumps(raw),
                         "attributes": {"ApproximateReceiveCount": str(receive_count)}, "eventSource": "aws:sqs"}]}


def record(pid, cid):
    from common import ddb

    return ddb.table().get_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, ConsistentRead=True).get("Item")


def claim_item(pid, cid):
    from common import ddb

    return ddb.table().get_item(Key={"PK": f"PLAN#{pid}", "SK": f"CLAIM#{cid}"}, ConsistentRead=True).get("Item")


def inbox_items():
    from common import ddb

    return [i for i in ddb.table().scan(ConsistentRead=True)["Items"] if i["SK"].startswith("INBOX#")]


def processed_keys(client, cid) -> list[str]:
    resp = client.list_objects_v2(Bucket=BUCKET, Prefix=f"{s3.PROCESSED_PREFIX}{cid}/")
    return sorted(o["Key"] for o in resp.get("Contents", []))


class Ctx:
    """get_remaining_time_in_millis를 정해진 값 열로 돌려주는 가짜 Lambda context."""

    def __init__(self, *remaining: float) -> None:
        self.values = list(remaining) or [30_000.0]

    def get_remaining_time_in_millis(self) -> float:
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]
