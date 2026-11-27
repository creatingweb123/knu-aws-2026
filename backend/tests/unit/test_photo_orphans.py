"""scripts/photo_orphans.py: 분류와 읽기 전용 보장."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import pytest

pytest.importorskip("moto")
from moto import mock_aws  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import photo_orphans as po  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

NOW = datetime.now(timezone.utc)
CID = lambda c: "clm_" + c * 26  # noqa: E731
HEX = lambda c: c * 32  # noqa: E731


def key(c, h):
    return f"photos/processed/{CID(c)}/{HEX(h)}.jpg"


@pytest.fixture
def env(monkeypatch):
    set_env(monkeypatch)
    with haru_table() as table, mock_aws():
        s3 = boto3.client("s3", region_name="ap-northeast-2")
        s3.create_bucket(Bucket="orphan-bucket", CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
        yield s3, table


def seed_claim(table, c, processed=None, delivered=False):
    table.put_item(Item={"PK": f"CLAIM#{CID(c)}", "SK": "META", "planId": "p" + c})
    rec = {"PK": f"PLAN#p{c}", "SK": f"RECORD#{CID(c)}"}
    if processed:
        rec["processedKey"] = processed
    if delivered:
        rec["deliveredAt"] = "2026-11-27T00:00:00.000Z"
    table.put_item(Item=rec)


def test_classification(env):
    s3, table = env
    for k in (key("A", "a"), key("A", "b"), key("B", "c"), key("C", "d"), key("D", "e")):
        s3.put_object(Bucket="orphan-bucket", Key=k, Body=b"x")
    s3.put_object(Bucket="orphan-bucket", Key="photos/processed/not-a-claim/x.jpg", Body=b"x")
    s3.put_object(Bucket="orphan-bucket", Key="photos/original/untouched.jpg", Body=b"x")  # 원본은 보지 않는다
    seed_claim(table, "A", processed=key("A", "a"), delivered=True)   # A/a 전달됨, A/b 고아 후보
    seed_claim(table, "B", processed=key("B", "c"))                    # 가리키는데 미전달
    seed_claim(table, "C")                                             # C/d 가리키지 않음
    # D는 Claim 조회 없음 → no_record
    later = NOW + timedelta(hours=2)
    r = po.scan(s3, table, "orphan-bucket", now=later, min_age_minutes=60)
    assert r["counts"] == {"delivered": 1, "orphan_candidate": 2, "referenced_undelivered": 1, "no_record": 1, "unparseable_key": 1}
    assert {c["kind"] for c in r["candidates"]} == {"orphan_candidate", "referenced_undelivered", "no_record"}
    assert all(len(c["claim"]) <= 12 and "photos/" not in str(c) for c in r["candidates"])


def test_recent_unreferenced_is_too_new_not_candidate(env):
    s3, table = env
    s3.put_object(Bucket="orphan-bucket", Key=key("C", "d"), Body=b"x")
    seed_claim(table, "C")
    r = po.scan(s3, table, "orphan-bucket", now=NOW + timedelta(minutes=5), min_age_minutes=60)
    assert r["counts"] == {"too_new": 1} and r["candidates"] == []


def test_never_modifies_anything(env):
    s3, table = env
    s3.put_object(Bucket="orphan-bucket", Key=key("C", "d"), Body=b"x")
    seed_claim(table, "C")
    before = sorted(map(str, table.scan()["Items"]))
    po.scan(s3, table, "orphan-bucket", now=NOW + timedelta(days=3))
    assert [o["Key"] for o in s3.list_objects_v2(Bucket="orphan-bucket")["Contents"]] == [key("C", "d")]
    assert sorted(map(str, table.scan()["Items"])) == before
    assert "delete_object" not in Path(po.__file__).read_text(encoding="utf-8").replace("삭제 권한", "")


def test_empty_bucket(env):
    s3, table = env
    assert po.scan(s3, table, "orphan-bucket")["counts"] == {}
