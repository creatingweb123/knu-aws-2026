"""5단계 로컬 통합 테스트: 사진 파이프라인 (docker compose 환경, `pytest -m local`).

브라우저 대신 presigned URL(localhost:4566)로 직접 PUT하고, 어댑터의 SQS 폴러가 처리 Lambda 핸들러를 부른다.
상태는 DynamoDB를 직접 읽어 확인한다(200ms 간격, 최대 20초). 흐름·조건식 확인용이고 T8–T11·T15 판정 근거가 아니다(BE-Q15).

조건부 사례는 compose를 띄운 셸과 같은 환경 변수로 pytest를 실행할 때만 돈다.
- 스위치 켜짐: `PHOTO_UPLOAD_IF_NONE_MATCH=true docker compose up -d --force-recreate` 뒤 업로드 헤더로 판단
- `FAULT_INJECT=photo-slow`: PROCESSING 관측 뒤 TEXT_ONLY 완료·교체 경합
- `FAULT_INJECT=photo PHOTO_QUEUE_VISIBILITY_S=2`: redrive(maxReceiveCount 3) → DLQ, FAILED RETRY_EXHAUSTED

Validates: spec backend-stage5-photo-pipeline Requirement 14.3 · BE-Q64
"""

from __future__ import annotations

import io
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

import pytest
from PIL import Image

from tests.local.conftest import boto, call, dev_token
from tests.local.test_local_flow import plan_body

pytestmark = pytest.mark.local

TABLE = os.environ.get("TABLE_NAME", "HaruTable")
BUCKET = os.environ.get("PHOTO_BUCKET", "haru-photos-local")
FAULT = os.environ.get("FAULT_INJECT", "")

# Floci 2.5.0-compat에서 확인한 결과로 정한 "로컬 미지원" 항목(BE-Q64). AWS 판정 항목으로 넘긴다.
LOCAL_UNSUPPORTED = {
    "lifecycle_expiry": "수명 주기 설정은 수락하지만 실제 7일 만료는 로컬에서 확인할 수 없다",
    "browser_cors": "버킷 CORS 설정은 수락하지만 브라우저 preflight·오류 응답의 CORS 헤더는 AWS에서 확인한다",
    "bucket_policy": "버킷 정책은 수락하지만 강제하지 않는다(Deny PutObject 정책에도 PUT 200). TLS·s3:if-none-match 강제는 AWS에서 확인한다",
    "esm_and_lambda": "실제 SQS 이벤트 소스 매핑·Lambda 강제 종료·DLQ 알람은 어댑터 폴러로 대신할 수 없다",
}


# ------------------------------------------------------------------ 도우미


def jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (800, 600), (40, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "LocalCam"  # Make
    exif[0x8825] = {1: "N", 2: (37.0, 33.0, 0.0), 3: "E", 4: (126.0, 58.0, 0.0)}  # GPSInfo
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def _ddb():
    return boto("dynamodb")


def _plain(item: dict[str, Any]) -> dict[str, Any]:
    from boto3.dynamodb.types import TypeDeserializer

    d = TypeDeserializer()
    return {k: d.deserialize(v) for k, v in item.items()}


def record(pid: str, cid: str) -> dict[str, Any] | None:
    resp = _ddb().get_item(TableName=TABLE, Key={"PK": {"S": f"PLAN#{pid}"}, "SK": {"S": f"RECORD#{cid}"}}, ConsistentRead=True)
    return _plain(resp["Item"]) if "Item" in resp else None


def inbox_count(owner_id: str, cid: str) -> int:
    resp = _ddb().get_item(TableName=TABLE, Key={"PK": {"S": f"USER#{owner_id}"}, "SK": {"S": f"INBOX#{cid}"}}, ConsistentRead=True)
    return 1 if "Item" in resp else 0


def wait_record(pid: str, cid: str, pred, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    rec = None
    while time.monotonic() < deadline:
        rec = record(pid, cid)
        if rec is not None and pred(rec):
            return rec
        time.sleep(0.2)
    raise AssertionError(f"timeout: photoStatus={rec and rec.get('photoStatus')} delivered={bool(rec and rec.get('deliveredAt'))}")


def processed_keys(cid: str) -> list[str]:
    resp = boto("s3").list_objects_v2(Bucket=BUCKET, Prefix=f"photos/processed/{cid}/")
    return [o["Key"] for o in resp.get("Contents", [])]


def put(upload: dict[str, Any], body: bytes) -> int:
    req = urllib.request.Request(upload["url"], data=body, method=upload["method"], headers=dict(upload["headers"]))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def get_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read()


def claimed():
    """(owner token, owner id, runner token, planId, claimId)."""
    owner_id = f"u-{uuid.uuid4()}"
    owner, runner = dev_token(owner_id, "지연"), dev_token(f"u-{uuid.uuid4()}", "수현")
    status, _, body = call("POST", "/plans", token=owner, body=plan_body(), headers={"Idempotency-Key": str(uuid.uuid4())})
    assert status == 201, body
    pid = body["plan"]["planId"]
    status, _, body = call("POST", f"/plans/{pid}/claims", token=runner)
    assert status == 201, body
    return owner, owner_id, runner, pid, body["claim"]["claimId"]


def put_record_with_photo(runner: str, cid: str, data: bytes, ct: str = "image/jpeg", size: int | None = None) -> dict[str, Any]:
    status, _, body = call(
        "PUT", f"/claims/{cid}/record", token=runner, body={"letter": "소금빵을 샀어요", "photo": {"contentType": ct, "size": size or len(data)}}
    )
    assert status == 200, body
    assert body["upload"] and body["upload"]["method"] == "PUT"
    assert body["upload"]["url"].startswith("http://localhost:4566/")
    return body["upload"]


def delivered(rec: dict[str, Any]) -> bool:
    return bool(rec.get("deliveredAt"))


# ------------------------------------------------------------------ 기본 사례


def test_photo_happy_path_strips_metadata():
    owner, owner_id, runner, pid, cid = claimed()
    data = jpeg_with_gps()
    assert Image.open(io.BytesIO(data)).getexif().get(0x8825)  # 원본에는 GPS가 있다
    upload = put_record_with_photo(runner, cid, data)
    assert put(upload, data) == 200

    rec = wait_record(pid, cid, delivered)
    assert rec["photoStatus"] == "READY" and rec["processedKey"].startswith(f"photos/processed/{cid}/")
    assert processed_keys(cid) == [rec["processedKey"]]
    assert inbox_count(owner_id, cid) == 1

    status, _, detail = call("GET", f"/inbox/{cid}", token=owner)
    assert status == 200
    assert detail["item"]["hasPhoto"] is True
    assert detail["record"]["photoCaption"] == "출근길 빵집에서"
    url = detail["record"]["photoUrl"]
    assert url.startswith("http://localhost:4566/")
    img = Image.open(io.BytesIO(get_bytes(url)))
    assert img.format == "JPEG"
    assert len(img.getexif()) == 0 and "exif" not in img.info and "icc_profile" not in img.info

    status, _, body = call("POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    assert status == 200 and body["delivered"] is True and body["hasPhoto"] is True  # 멱등 응답


def test_corrupt_photo_fails_then_text_only():
    _, owner_id, runner, pid, cid = claimed()
    data = b"\xff\xd8\xff not really a jpeg" * 10
    upload = put_record_with_photo(runner, cid, data)
    assert put(upload, data) == 200

    rec = wait_record(pid, cid, lambda r: r.get("photoStatus") == "FAILED")
    assert rec["photoError"] == "CORRUPT_IMAGE" and not rec.get("deliveredAt")
    assert processed_keys(cid) == []

    status, _, body = call("POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    assert status == 200 and body["delivered"] is True and body["hasPhoto"] is False
    assert inbox_count(owner_id, cid) == 1


def test_replace_before_upload_uses_new_photo_only():
    _, owner_id, runner, pid, cid = claimed()
    first = jpeg_with_gps()
    old = put_record_with_photo(runner, cid, first)
    old_key = record(pid, cid)["photoKey"]

    second = jpeg_with_gps()
    status, _, body = call("POST", f"/claims/{cid}/record/photo", token=runner, body={"contentType": "image/jpeg", "size": len(second)})
    assert status == 200, body
    new_key = record(pid, cid)["photoKey"]
    assert new_key != old_key

    assert put(body["upload"], second) == 200
    rec = wait_record(pid, cid, delivered)
    assert rec["photoKey"] == new_key

    assert put(old, first) == 200  # 이전 키에서 오는 처리 결과는 무시된다
    time.sleep(3)
    rec = record(pid, cid)
    assert rec["photoKey"] == new_key and processed_keys(cid) == [rec["processedKey"]]
    assert inbox_count(owner_id, cid) == 1


def test_wrong_content_length_rejected_by_signature():
    _, _, runner, pid, cid = claimed()
    data = jpeg_with_gps()
    upload = put_record_with_photo(runner, cid, data)
    assert put(upload, data + b"\x00") == 403  # 서명한 ContentLength와 다르다(FLOCI_AUTH_VALIDATE_SIGNATURES=true)
    time.sleep(1)
    assert record(pid, cid)["photoStatus"] == "UPLOAD_PENDING"


def test_reupload_same_url_switch_off_delivers_once():
    _, owner_id, runner, pid, cid = claimed()
    data = jpeg_with_gps()
    upload = put_record_with_photo(runner, cid, data)
    if "If-None-Match" in upload["headers"]:
        pytest.skip("스위치 켜짐(PHOTO_UPLOAD_IF_NONE_MATCH=true) 환경: test_reupload_switch_on_412가 대신 돈다")
    assert put(upload, data) == 200
    wait_record(pid, cid, delivered)
    assert put(upload, data) == 200  # 스위치 꺼짐 동안의 한계: 같은 URL로 덮어쓸 수 있다(BE-Q65)
    time.sleep(3)
    rec = record(pid, cid)
    assert processed_keys(cid) == [rec["processedKey"]]
    assert inbox_count(owner_id, cid) == 1


def test_reupload_switch_on_412():
    _, _, runner, pid, cid = claimed()
    data = jpeg_with_gps()
    upload = put_record_with_photo(runner, cid, data)
    if upload["headers"].get("If-None-Match") != "*":
        pytest.skip("스위치 꺼짐 환경: PHOTO_UPLOAD_IF_NONE_MATCH=true로 다시 띄웠을 때만 확인한다")
    assert put(upload, data) == 200
    assert put(upload, data) == 412
    wait_record(pid, cid, delivered)


# ------------------------------------------------------------------ 장애·지연 주입 (로컬 확인용)


@pytest.mark.skipif(FAULT != "photo-slow", reason="FAULT_INJECT=photo-slow로 띄웠을 때만 돈다")
def test_slow_processing_then_text_only_discards():
    _, owner_id, runner, pid, cid = claimed()
    data = jpeg_with_gps()
    assert put(put_record_with_photo(runner, cid, data), data) == 200
    wait_record(pid, cid, lambda r: r.get("photoStatus") == "PROCESSING")

    status, _, body = call("POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    assert status == 200 and body["hasPhoto"] is False
    time.sleep(8)  # 지연(기본 5초) 뒤 처리 Lambda가 not_delivered로 끝나고 자기 처리본을 지운다
    rec = record(pid, cid)
    assert rec["photoStatus"] == "DISCARDED" and not rec.get("processedKey")
    assert processed_keys(cid) == []
    assert inbox_count(owner_id, cid) == 1


@pytest.mark.skipif(FAULT != "photo-slow", reason="FAULT_INJECT=photo-slow로 띄웠을 때만 돈다")
def test_slow_processing_replace_race():
    _, owner_id, runner, pid, cid = claimed()
    first = jpeg_with_gps()
    assert put(put_record_with_photo(runner, cid, first), first) == 200
    wait_record(pid, cid, lambda r: r.get("photoStatus") == "PROCESSING")

    second = jpeg_with_gps()
    status, _, body = call("POST", f"/claims/{cid}/record/photo", token=runner, body={"contentType": "image/jpeg", "size": len(second)})
    assert status == 200
    new_key = record(pid, cid)["photoKey"]
    assert put(body["upload"], second) == 200
    rec = wait_record(pid, cid, delivered, timeout=30)
    assert rec["photoKey"] == new_key
    time.sleep(3)
    assert processed_keys(cid) == [record(pid, cid)["processedKey"]]
    assert inbox_count(owner_id, cid) == 1


@pytest.mark.skipif(FAULT != "photo", reason="FAULT_INJECT=photo PHOTO_QUEUE_VISIBILITY_S=2로 띄웠을 때만 돈다")
def test_redrive_to_dlq_marks_retry_exhausted():
    sqs = boto("sqs")
    dlq = sqs.get_queue_url(QueueName="haru-photo-dlq")["QueueUrl"]
    _, owner_id, runner, pid, cid = claimed()
    data = jpeg_with_gps()
    assert put(put_record_with_photo(runner, cid, data), data) == 200
    rec = wait_record(pid, cid, lambda r: r.get("photoStatus") == "FAILED", timeout=60)
    assert rec["photoError"] == "RETRY_EXHAUSTED" and not rec.get("deliveredAt")

    found = False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not found:
        for m in sqs.receive_message(QueueUrl=dlq, WaitTimeSeconds=2, MaxNumberOfMessages=10).get("Messages", []):
            if cid in m["Body"]:
                found = True
                sqs.delete_message(QueueUrl=dlq, ReceiptHandle=m["ReceiptHandle"])  # 이 테스트가 만든 메시지만 지운다
    assert found, "DLQ로 옮겨지지 않았다"
    assert processed_keys(cid) == [] and inbox_count(owner_id, cid) == 0

    status, _, body = call("POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    assert status == 200 and body["hasPhoto"] is False


# ------------------------------------------------------------------ 로컬 미지원


@pytest.mark.parametrize("item", sorted(LOCAL_UNSUPPORTED))
def test_local_unsupported(item):
    pytest.skip(f"로컬 미지원({item}): {LOCAL_UNSUPPORTED[item]}")


# ------------------------------------------------------------------ GET /claims/{claimId}/record 폴링 (작업 A·B-1)

ORDER = ["NONE", "UPLOAD_PENDING", "PROCESSING", "READY"]


def poll_record(token: str, cid: str, pred, timeout: float = 20.0) -> tuple[dict[str, Any], list[str]]:
    """GET /record를 200ms 간격으로 부르며 관측한 photoStatus 순서와 마지막 본문을 돌려준다."""
    seen: list[str] = []
    deadline = time.monotonic() + timeout
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, _, body = call("GET", f"/claims/{cid}/record", token=token)
        assert status == 200, body
        assert set(body) == {"record", "claimStatus", "delivered", "photoStatus"}
        if not seen or seen[-1] != body["photoStatus"]:
            seen.append(body["photoStatus"])
        if pred(body):
            return body, seen
        time.sleep(0.2)
    raise AssertionError(f"timeout: seen={seen}")


def test_poll_record_no_record_and_authorization():
    owner, _, runner, pid, cid = claimed()
    status, _, body = call("GET", f"/claims/{cid}/record", token=runner)
    assert (status, body) == (200, {"record": None, "claimStatus": "ACTIVE", "delivered": False, "photoStatus": "NONE"})
    assert call("GET", f"/claims/{cid}/record", token=owner)[0] == 403  # 계획자도 실행자가 아니다(BE-Q1)
    assert call("GET", f"/claims/{cid}/record", token=dev_token(f"u-{uuid.uuid4()}", "민준"))[0] == 403
    assert call("GET", "/claims/clm_nonexistent/record", token=runner)[0] == 404
    assert call("GET", f"/claims/{cid}/record")[0] == 401


def test_poll_record_photo_flow_reaches_ready_and_completed():
    _, _, runner, pid, cid = claimed()
    data = jpeg_with_gps()
    upload = put_record_with_photo(runner, cid, data)
    status, _, first = call("GET", f"/claims/{cid}/record", token=runner)
    assert first["photoStatus"] == "UPLOAD_PENDING" and first["record"]["photoStatus"] == "UPLOAD_PENDING" and first["delivered"] is False
    assert "photoKey" not in str(first) and "processedKey" not in str(first)
    assert put(upload, data) == 200
    body, seen = poll_record(runner, cid, lambda b: b["delivered"])
    assert body["photoStatus"] == "READY" and body["claimStatus"] == "COMPLETED" and body["record"]["deliveredAt"]
    assert seen == [s for s in ORDER if s in seen] and seen[0] == "UPLOAD_PENDING" and seen[-1] == "READY"  # 되돌아가지 않는다


def test_poll_record_failed_then_text_only_is_discarded():
    _, _, runner, pid, cid = claimed()
    data = b"\xff\xd8\xff not really a jpeg" * 10
    assert put(put_record_with_photo(runner, cid, data), data) == 200
    body, _ = poll_record(runner, cid, lambda b: b["photoStatus"] == "FAILED")
    assert body["delivered"] is False and body["claimStatus"] == "ACTIVE"
    status, _, done = call("POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    assert status == 200 and done["hasPhoto"] is False
    _, _, after = call("GET", f"/claims/{cid}/record", token=runner)
    assert after["claimStatus"] == "COMPLETED" and after["delivered"] is True and after["photoStatus"] == "DISCARDED"


def test_poll_record_abandon_keeps_readable_and_text_only_without_photo():
    _, _, runner, pid, cid = claimed()
    call("PUT", f"/claims/{cid}/record", token=runner, body={"letter": "글만"})
    status, _, body = call("GET", f"/claims/{cid}/record", token=runner)
    assert body["photoStatus"] == "NONE" and body["record"]["letter"] == "글만"
    assert call("POST", f"/claims/{cid}/abandon", token=runner)[0] == 200
    _, _, after = call("GET", f"/claims/{cid}/record", token=runner)
    assert after["claimStatus"] == "ABANDONED" and after["delivered"] is False
