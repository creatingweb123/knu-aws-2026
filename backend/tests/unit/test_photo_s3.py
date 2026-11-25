"""common/s3.py: 키 규칙, presign 인자, BE-Q65 스위치, 그리고 moto의 S3 조건부 요청 지원 확인.

Validates: spec backend-stage5-photo-pipeline Requirements 2.2, 2.3, 2.5, 5.4, 5.9, 7.5, 10.1, 13.3
"""

import re
import urllib.parse as up
from datetime import datetime, timezone

import boto3
import pytest
from botocore.exceptions import ClientError

from common import s3

CLAIM = "clm_01JABCDEFGHJKMNPQRSTVWXYZ0"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("PHOTO_BUCKET", "haru-photos-test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.delenv("PUBLIC_S3_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOTO_UPLOAD_IF_NONE_MATCH", raising=False)
    monkeypatch.setattr(s3, "_presign_client", None)


def test_original_key_roundtrip():
    for ct, ext in (("image/jpeg", "jpg"), ("image/png", "png")):
        key = s3.new_original_key(CLAIM, ct)
        assert re.fullmatch(rf"photos/original/{CLAIM}/[0-9a-f]{{32}}\.{ext}", key)
        assert s3.parse_original_key(key) == (CLAIM, key.split("/")[-1].split(".")[0])
    assert s3.new_original_key(CLAIM, "image/jpeg") != s3.new_original_key(CLAIM, "image/jpeg")


@pytest.mark.parametrize(
    "key",
    [
        f"photos/processed/{CLAIM}/{'a' * 32}.jpg",
        f"photos/original/pln_01JABCDEFGHJKMNPQRSTVWXYZ0/{'a' * 32}.jpg",
        f"photos/original/{CLAIM}/{'a' * 31}.jpg",
        f"photos/original/{CLAIM}/{'A' * 32}.jpg",
        f"photos/original/{CLAIM}/{'a' * 32}.gif",
        f"photos/original/{CLAIM}/x/{'a' * 32}.jpg",
        "photos/original/",
        "",
    ],
)
def test_parse_rejects_other_keys(key):
    assert s3.parse_original_key(key) is None  # BE-Q54


def test_processed_key_is_unique_per_attempt():
    a, b = s3.new_processed_key(CLAIM), s3.new_processed_key(CLAIM)
    assert a != b and re.fullmatch(rf"photos/processed/{CLAIM}/[0-9a-f]{{32}}\.jpg", a)  # BE-Q57


def test_quote_etag():
    assert s3.quote_etag("abc") == '"abc"' and s3.quote_etag('"abc"') == '"abc"'


def _query(url):
    return dict(up.parse_qsl(up.urlparse(url).query))


def test_presign_put_default_switch_off():
    up_ = s3.presign_put(f"photos/original/{CLAIM}/{'a' * 32}.jpg", "image/jpeg", 2480000, NOW)
    assert set(up_) == {"url", "method", "headers", "expiresAt"}
    assert up_["method"] == "PUT" and up_["headers"] == {"Content-Type": "image/jpeg"}
    assert up_["expiresAt"] == "2026-11-20T12:10:00.000Z"
    q = _query(up_["url"])
    assert q["X-Amz-SignedHeaders"] == "content-length;content-type;host" and q["X-Amz-Expires"] == "600"


def test_presign_put_switch_on_signs_if_none_match(monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_IF_NONE_MATCH", "true")
    up_ = s3.presign_put(f"photos/original/{CLAIM}/{'a' * 32}.png", "image/png", 10, NOW)
    assert up_["headers"] == {"Content-Type": "image/png", "If-None-Match": "*"}
    assert _query(up_["url"])["X-Amz-SignedHeaders"] == "content-length;content-type;host;if-none-match"


def test_presign_uses_public_endpoint_with_path_style(monkeypatch):
    monkeypatch.setenv("PUBLIC_S3_ENDPOINT", "http://localhost:4566")
    url = s3.presign_put(f"photos/original/{CLAIM}/{'a' * 32}.jpg", "image/jpeg", 10, NOW)["url"]
    assert url.startswith(f"http://localhost:4566/haru-photos-test/photos/original/{CLAIM}/")


def test_presign_get_15_minutes():
    q = _query(s3.presign_get(f"photos/processed/{CLAIM}/{'b' * 32}.jpg"))
    assert q["X-Amz-Expires"] == "900"


def test_presign_args(monkeypatch):
    calls = []

    class Fake:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            calls.append((op, Params, ExpiresIn))
            return "https://example/x"

    monkeypatch.setattr(s3, "_presign_client", Fake())
    s3.presign_put("k", "image/jpeg", 123, NOW)
    s3.presign_get("p")
    assert calls[0] == ("put_object", {"Bucket": "haru-photos-test", "Key": "k", "ContentType": "image/jpeg", "ContentLength": 123}, 600)
    assert calls[1] == ("get_object", {"Bucket": "haru-photos-test", "Key": "p"}, 900)


# ---------------------------------------------------------------- moto의 S3 조건부 요청 지원 확인


@pytest.fixture
def bucket():
    from moto import mock_aws

    with mock_aws():
        c = boto3.client("s3", region_name="ap-northeast-2")
        c.create_bucket(Bucket="haru-photos-test", CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"})
        yield c


def test_moto_put_if_none_match_412(bucket):
    bucket.put_object(Bucket="haru-photos-test", Key="k", Body=b"1", IfNoneMatch="*")
    with pytest.raises(ClientError) as e:
        bucket.put_object(Bucket="haru-photos-test", Key="k", Body=b"2", IfNoneMatch="*")
    assert e.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412


def test_moto_get_and_head_if_match(bucket):
    etag = bucket.put_object(Bucket="haru-photos-test", Key="k", Body=b"1")["ETag"]
    assert bucket.get_object(Bucket="haru-photos-test", Key="k", IfMatch=etag)["Body"].read() == b"1"
    assert bucket.head_object(Bucket="haru-photos-test", Key="k", IfMatch=etag)["ContentLength"] == 1
    for call in (bucket.get_object, bucket.head_object):
        with pytest.raises(ClientError) as e:
            call(Bucket="haru-photos-test", Key="k", IfMatch='"deadbeef"')
        assert e.value.response["ResponseMetadata"]["HTTPStatusCode"] == 412
