"""5단계 사진 파이프라인 AWS 판정 테스트 (T8·T9·T10·T11·T15, 재업로드, IAM·CORS, 주입 차단).

실행·판정은 AWS 담당이 한다(backend/README.md 판정 실행표). 상태는 DynamoDB ConsistentRead로 직접 확인한다(BE-Q38).
- 기본 배포: `pytest -m "integration and not fault" tests/integration/test_photo.py`
- 지연 주입 배포(`FaultInject=photo-slow`): `pytest -m "integration and fault" -k with_delay`
- 장애 주입 배포(`FaultInject=photo`): `pytest -m "integration and fault" -k T9`

T10·T15 판정 규칙: `PROCESSING`을 관측하지 못하면 결과 파일에 `"verdict": "unverified"`와 관측한 상태 열을 남기고
사유 있는 skip으로 끝낸다. 관측했어도 경쟁 요청이 사진 전달 뒤에 도착했으면(TEXT_ONLY 응답 `hasPhoto: true`, 교체 409)
경합을 만들지 못한 것이므로 같은 방식으로 미검증(`reason: race_lost`)이다. xfail·통과로 처리하지 않는다. 미검증은 재시험 대상이다.

Validates: spec backend-stage5-photo-pipeline Requirements 9.4, 9.5, 14.5 · T8, T9, T10, T11, T15
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

import pytest
from PIL import Image

from tests.integration.conftest import (
    REGION,
    STACK_NAME,
    _boto,
    call,
    create_plan,
    create_user,
    fetch,
    get_item,
    photo_record,
    photo_resources,
    processed_keys,
    register_photo_claim,
    save_result,
    upload_photo,
    wait_photo_settled,
    wait_record,
)

pytestmark = pytest.mark.integration

ORIGIN = "http://localhost:5173"
DEV_STACK = "haru-dev"
RED, BLUE = (220, 30, 30), (30, 60, 220)
UNVERIFIED = "PROCESSING 미관측 또는 경합 미발생, 미검증, 재시험 필요"


# ------------------------------------------------------------------ 이미지


def solid_jpeg(color: tuple[int, int, int], *, gps: bool = False, size=(1200, 900)) -> bytes:
    img = Image.new("RGB", size, color)
    out = io.BytesIO()
    if gps:
        exif = Image.Exif()
        exif[0x010F] = "HaruTestCam"  # Make
        exif[0x8825] = {1: "N", 2: (37.0, 33.0, 0.0), 3: "E", 4: (126.0, 58.0, 0.0)}  # GPSInfo
        img.save(out, "JPEG", quality=90, exif=exif)
    else:
        img.save(out, "JPEG", quality=90)
    return out.getvalue()


def mean_color(data: bytes) -> tuple[int, int, int]:
    img = Image.open(io.BytesIO(data)).convert("RGB").resize((16, 16))
    px = list(img.getdata())
    return tuple(sum(p[i] for p in px) // len(px) for i in range(3))  # type: ignore[return-value]


def close(a, b, tol=40) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def metadata_report(data: bytes) -> dict[str, Any]:
    """처리본 메타데이터 검사. exiftool이 있으면 쓰고, 없으면 Pillow와 바이트 표지로 본다. 도구 이름을 남긴다."""
    if shutil.which("exiftool"):
        out = subprocess.run(["exiftool", "-G", "-a", "-j", "-"], input=data, capture_output=True, check=True).stdout
        tags = json.loads(out)[0]
        groups = {k.split(":", 1)[0] for k in tags if ":" in k}
        bad = sorted(k for k in tags if k.split(":", 1)[0] in ("EXIF", "XMP", "IPTC", "ICC_Profile", "Photoshop") or "GPS" in k)
        return {"tool": "exiftool", "groups": sorted(groups), "found": bad}
    img = Image.open(io.BytesIO(data))
    found = []
    if len(img.getexif()):
        found.append("EXIF")
    for key in ("exif", "icc_profile", "xmp", "XML:com.adobe.xmp", "photoshop", "comment"):
        if key in img.info:
            found.append(key)
    for marker, name in ((b"Exif\x00\x00", "APP1-Exif"), (b"http://ns.adobe.com/xap", "APP1-XMP"), (b"ICC_PROFILE", "APP2-ICC")):
        if marker in data:
            found.append(name)
    return {"tool": f"Pillow {Image.__version__}", "format": img.format, "found": found}


# ------------------------------------------------------------------ 흐름 도우미


def claimed(stack, label: str) -> tuple[str, str, str, str, str]:
    """(owner sub, owner token, runner token, planId, claimId)."""
    owner_sub, owner = create_user(stack, f"{label}지연")
    _, runner = create_user(stack, f"{label}수현")
    pid = create_plan(stack, owner, f"{label} 사진")
    status, body = call(stack, "POST", f"/plans/{pid}/claims", token=runner)
    assert status == 201, body
    return owner_sub, owner, runner, pid, body["claim"]["claimId"]


def record_with_photo(stack, runner: str, cid: str, data: bytes) -> dict[str, Any]:
    register_photo_claim(stack, cid)  # 업로드 전에 등록
    status, body = call(stack, "PUT", f"/claims/{cid}/record", token=runner,
                        body={"letter": "사진과 함께 보내요", "photo": {"contentType": "image/jpeg", "size": len(data)}})
    assert status == 200, body
    assert body["upload"] and body["upload"]["method"] == "PUT"
    return body["upload"]


def inbox_item(stack, owner_sub: str, cid: str) -> dict[str, Any] | None:
    return get_item(stack, f"USER#{owner_sub}", f"INBOX#{cid}")


def delivered(rec) -> bool:
    return bool(rec.get("deliveredAt"))


def processing(rec) -> bool:
    return rec.get("photoStatus") == "PROCESSING" or bool(rec.get("deliveredAt")) or rec.get("photoStatus") == "FAILED"


def function_env(stack) -> dict[str, str]:
    fn = photo_resources(stack)["function"]
    return _boto("lambda").get_function_configuration(FunctionName=fn).get("Environment", {}).get("Variables", {})


def require_fault(stack, expected: str) -> None:
    """잘못된 배포에서 판정하지 않는다."""
    env = function_env(stack)
    if env.get("FAULT_INJECT") != expected or env.get("FAULT_INJECT_ALLOWED") != "true":
        pytest.skip(f"함수 FAULT_INJECT={env.get('FAULT_INJECT')!r}, 기대값 {expected!r}인 dev 배포에서만 판정한다")


# ------------------------------------------------------------------ T10·T15 본문 (기본·지연 주입 공통)


def run_T10(stack, label: str) -> dict[str, Any]:
    owner_sub, _, runner, pid, cid = claimed(stack, label)
    data = solid_jpeg(RED)
    assert upload_photo(record_with_photo(stack, runner, cid, data), data)[0] == 200
    rec, seen = wait_record(stack, pid, cid, processing, timeout=60, interval=0.1)
    result: dict[str, Any] = {"claimId": cid, "observed": seen}
    if rec is None or rec.get("photoStatus") != "PROCESSING":
        wait_photo_settled(stack, pid, cid)
        return {**result, "verdict": "unverified", "reason": "processing_not_observed"}

    status, body = call(stack, "POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    result["complete"] = {"status": status, "body": body}
    if status == 200 and body.get("hasPhoto") is True:  # 사진 완료가 먼저 끝났다. 경합을 만들지 못했으므로 판정하지 않는다
        wait_photo_settled(stack, pid, cid)
        return {**result, "verdict": "unverified", "reason": "race_lost"}
    wait_photo_settled(stack, pid, cid, stable_s=30, timeout_s=120)
    after = photo_record(stack, pid, cid) or {}
    item = inbox_item(stack, owner_sub, cid) or {}
    result.update({
        "photoStatus": after.get("photoStatus"),
        "processedKey": after.get("processedKey"),
        "processedObjects": len(processed_keys(stack, cid)),
        "inboxHasPhoto": item.get("hasPhoto"),
    })
    ok = (status == 200 and body.get("hasPhoto") is False and after.get("photoStatus") == "DISCARDED"
          and not after.get("processedKey") and result["processedObjects"] == 0 and item.get("hasPhoto") is False)
    return {**result, "verdict": "pass" if ok else "fail"}


def run_T15(stack, label: str) -> dict[str, Any]:
    owner_sub, owner, runner, pid, cid = claimed(stack, label)
    first, second = solid_jpeg(RED), solid_jpeg(BLUE)
    assert upload_photo(record_with_photo(stack, runner, cid, first), first)[0] == 200
    rec, seen = wait_record(stack, pid, cid, processing, timeout=60, interval=0.1)
    result: dict[str, Any] = {"claimId": cid, "observed": seen}
    if rec is None or rec.get("photoStatus") != "PROCESSING":
        wait_photo_settled(stack, pid, cid)
        return {**result, "verdict": "unverified", "reason": "processing_not_observed"}

    status, body = call(stack, "POST", f"/claims/{cid}/record/photo", token=runner, body={"contentType": "image/jpeg", "size": len(second)})
    result["replace"] = {"status": status, "code": (body or {}).get("error", {}).get("code")}
    if status == 409 and result["replace"]["code"] == "CLAIM_NOT_ACTIVE":  # 첫 사진 전달이 먼저 끝났다
        wait_photo_settled(stack, pid, cid)
        return {**result, "verdict": "unverified", "reason": "race_lost"}
    assert status == 200, body
    up = body["upload"]
    new_key = (photo_record(stack, pid, cid) or {}).get("photoKey")
    assert upload_photo(up, second)[0] == 200
    done, seen2 = wait_record(stack, pid, cid, delivered, timeout=90)
    result["observedAfterReplace"] = seen2
    wait_photo_settled(stack, pid, cid)
    after = photo_record(stack, pid, cid) or {}
    status, detail = call(stack, "GET", f"/inbox/{cid}", token=owner)
    url = (detail or {}).get("record", {}).get("photoUrl") if status == 200 else None
    color = mean_color(fetch(url)) if url else None
    keys = processed_keys(stack, cid)
    result.update({
        "delivered": done is not None,
        "photoKeyIsReplacement": after.get("photoKey") == new_key,
        "processedObjects": len(keys),
        "deliveredColor": color,
        "inboxHasPhoto": (inbox_item(stack, owner_sub, cid) or {}).get("hasPhoto"),
    })
    ok = (done is not None and after.get("photoKey") == new_key and keys == [after.get("processedKey")]
          and color is not None and close(color, BLUE) and result["inboxHasPhoto"] is True)
    return {**result, "verdict": "pass" if ok else "fail"}


def judge(name: str, result: dict[str, Any]) -> None:
    log = save_result(name, result)
    if result["verdict"] == "unverified":
        pytest.skip(f"{name}: {UNVERIFIED} (사유 {result.get('reason')}, 관측 {result['observed']}, 로그: {log})")
    assert result["verdict"] == "pass", f"{name} 불합격 (로그: {log})"


# ------------------------------------------------------------------ 기본 배포


def test_T8_corrupt_image(stack):
    owner_sub, _, runner, pid, cid = claimed(stack, "T8")
    whole = solid_jpeg(RED)
    data = whole[: len(whole) // 3]  # 잘린 JPEG
    assert upload_photo(record_with_photo(stack, runner, cid, data), data)[0] == 200
    rec, seen = wait_record(stack, pid, cid, lambda r: r.get("photoStatus") == "FAILED", timeout=120)
    status, body = call(stack, "POST", f"/claims/{cid}/complete", token=runner, body={"mode": "TEXT_ONLY"})
    wait_photo_settled(stack, pid, cid)
    item = inbox_item(stack, owner_sub, cid) or {}
    log = save_result("T8-corrupt-image", {"claimId": cid, "observed": seen, "photoError": (rec or {}).get("photoError"),
                                           "complete": {"status": status, "body": body}, "inboxHasPhoto": item.get("hasPhoto")})
    assert rec is not None, f"FAILED가 되지 않았다 (로그: {log})"
    assert rec["photoError"] == "CORRUPT_IMAGE" and rec["letter"] == "사진과 함께 보내요", f"(로그: {log})"
    assert status == 200 and body["hasPhoto"] is False, f"(로그: {log})"
    assert item.get("hasPhoto") is False and processed_keys(stack, cid) == [], f"(로그: {log})"


def test_T11_gps_stripped(stack):
    owner_sub, owner, runner, pid, cid = claimed(stack, "T11")
    data = solid_jpeg(RED, gps=True)
    assert Image.open(io.BytesIO(data)).getexif().get(0x8825), "원본에는 GPS가 있어야 한다"
    assert upload_photo(record_with_photo(stack, runner, cid, data), data)[0] == 200
    rec, seen = wait_record(stack, pid, cid, delivered, timeout=120)
    status, detail = call(stack, "GET", f"/inbox/{cid}", token=owner)
    report: dict[str, Any] = {"claimId": cid, "observed": seen, "inboxStatus": status}
    if status == 200 and detail["record"]["photoUrl"]:
        report["metadata"] = metadata_report(fetch(detail["record"]["photoUrl"]))
        report["photoCaption"] = detail["record"]["photoCaption"]
    wait_photo_settled(stack, pid, cid)
    log = save_result("T11-gps-stripped", report)
    assert rec is not None and status == 200, f"(로그: {log})"
    assert detail["item"]["hasPhoto"] is True and "metadata" in report, f"(로그: {log})"
    assert report["metadata"]["found"] == [], f"메타데이터가 남았다 (로그: {log})"
    assert (inbox_item(stack, owner_sub, cid) or {}).get("hasPhoto") is True


def test_T10_text_only_during_processing(stack):
    judge("T10-text-only-during-processing", run_T10(stack, "T10"))


def test_T15_replace_during_processing(stack):
    judge("T15-replace-during-processing", run_T15(stack, "T15"))


def test_photo_reupload(stack):
    owner_sub, _, runner, pid, cid = claimed(stack, "재업로드")
    data = solid_jpeg(RED)
    up = record_with_photo(stack, runner, cid, data)
    switch_on = up["headers"].get("If-None-Match") == "*"
    first = upload_photo(up, data)[0]
    second_status, _, second_code = upload_photo(up, data)
    rec, seen = wait_record(stack, pid, cid, delivered, timeout=120)
    wait_photo_settled(stack, pid, cid)
    keys = processed_keys(stack, cid)
    after = photo_record(stack, pid, cid) or {}
    log = save_result("photo-reupload", {"claimId": cid, "switchOn": switch_on, "puts": [first, second_status], "secondCode": second_code,
                                         "observed": seen, "processedObjects": len(keys), "inboxItem": bool(inbox_item(stack, owner_sub, cid))})
    assert first == 200, f"(로그: {log})"
    assert second_status == (412 if switch_on else 200), f"(로그: {log})"
    assert rec is not None and keys == [after.get("processedKey")], f"전달 1회·처리본 1개 (로그: {log})"
    assert inbox_item(stack, owner_sub, cid) is not None


def _preflight(url: str) -> tuple[int, dict[str, str]]:
    req = urllib.request.Request(url, method="OPTIONS", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "content-type"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


def test_photo_iam_and_cors(stack):
    _, owner, runner, pid, cid = claimed(stack, "권한")
    data = solid_jpeg(BLUE)
    up = record_with_photo(stack, runner, cid, data)
    pre_status, pre_headers = _preflight(up["url"])
    bad_status, bad_headers, bad_code = upload_photo(up, data + b"\x00", origin=ORIGIN)  # 서명한 ContentLength와 다름

    # 만료 URL: 테스트 실행자 자격 증명으로 1초짜리 presigned PUT을 같은 Claim prefix 아래에 만든다
    bucket = photo_resources(stack)["bucket"]
    expired_url = _boto("s3").generate_presigned_url(
        "put_object", Params={"Bucket": bucket, "Key": f"photos/original/{cid}/expired.jpg", "ContentType": "image/jpeg"}, ExpiresIn=1)
    time.sleep(2)
    exp_status, exp_headers, exp_code = upload_photo({"url": expired_url, "method": "PUT", "headers": {"Content-Type": "image/jpeg"}},
                                                     data, origin=ORIGIN)

    ok_status = upload_photo(up, data, origin=ORIGIN)[0]
    rec, seen = wait_record(stack, pid, cid, delivered, timeout=120)
    status, detail = call(stack, "GET", f"/inbox/{cid}", token=owner)
    got = fetch(detail["record"]["photoUrl"]) if status == 200 and detail["record"]["photoUrl"] else b""
    wait_photo_settled(stack, pid, cid)

    log = save_result("photo-iam-and-cors", {
        "claimId": cid,
        "preflight": {"status": pre_status, "allowOrigin": pre_headers.get("access-control-allow-origin"),
                      "allowMethods": pre_headers.get("access-control-allow-methods"),
                      "allowHeaders": pre_headers.get("access-control-allow-headers")},
        "wrongLength": {"status": bad_status, "code": bad_code, "allowOrigin": bad_headers.get("access-control-allow-origin")},
        "expired": {"status": exp_status, "code": exp_code, "allowOrigin": exp_headers.get("access-control-allow-origin")},
        "upload": ok_status, "observed": seen, "presignedGetBytes": len(got),
    })
    assert pre_status == 200 and pre_headers.get("access-control-allow-origin") == ORIGIN, f"(로그: {log})"
    assert "PUT" in (pre_headers.get("access-control-allow-methods") or ""), f"(로그: {log})"
    assert bad_status == 403 and exp_status == 403, f"(로그: {log})"
    assert ok_status == 200 and rec is not None and len(got) > 0, f"presigned PUT·GET 권한 (로그: {log})"


def test_photo_fault_blocked(stack):
    """주입 차단의 읽기 전용 확인(BE-Q59). 변경 세트 시도는 AWS 담당이 수동으로 한다."""
    fn = photo_resources(stack)["function"]
    env = function_env(stack)
    cfn = _boto("cloudformation")
    body = cfn.get_template(StackName=STACK_NAME, TemplateStage="Processed")["TemplateBody"]
    text = body if isinstance(body, str) else json.dumps(body)
    log = save_result("photo-fault-blocked", {
        "stack": STACK_NAME, "region": REGION, "function": fn,
        "env": {k: env.get(k) for k in ("FAULT_INJECT", "FAULT_INJECT_ALLOWED", "STAGE")},
        "processedTemplateHasFaultAllowed": "FaultAllowed" in text, "processedTemplateHasRule": "FaultInjectOnlyInDev" in text,
    })
    assert fn.startswith(f"{STACK_NAME}-"), f"함수 이름 접두사 (로그: {log})"
    assert "FaultAllowed" in text and "AWS::StackName" in text and DEV_STACK in text, f"(로그: {log})"
    if STACK_NAME != DEV_STACK:
        assert env.get("FAULT_INJECT", "") == "" and env.get("FAULT_INJECT_ALLOWED") == "false", f"dev 외 스택에 주입 값 (로그: {log})"


# ------------------------------------------------------------------ 장애·지연 주입 배포 (dev만)


@pytest.mark.fault
def test_T10_T15_with_delay(stack):
    """FaultInject=photo-slow 배포에서의 T10·T15. 이 결과가 최종 판정 근거다."""
    require_fault(stack, "photo-slow")
    results = {"T10": run_T10(stack, "T10지연"), "T15": run_T15(stack, "T15지연")}
    log = save_result("T10-T15-with-delay", results)
    unverified = [k for k, r in results.items() if r["verdict"] == "unverified"]
    failed = [k for k, r in results.items() if r["verdict"] == "fail"]
    assert not failed, f"불합격 {failed} (로그: {log})"
    if unverified:
        pytest.skip(f"{unverified}: {UNVERIFIED} (로그: {log})")


@pytest.mark.fault
def test_T9_dlq(stack):
    """FaultInject=photo 배포: 3번째 수신에서 FAILED RETRY_EXHAUSTED → DLQ → PhotoDLQNotEmpty ALARM."""
    require_fault(stack, "photo")
    res = photo_resources(stack)
    _, _, runner, pid, cid = claimed(stack, "T9")
    data = solid_jpeg(RED)
    assert upload_photo(record_with_photo(stack, runner, cid, data), data)[0] == 200
    rec, seen = wait_record(stack, pid, cid, lambda r: r.get("photoStatus") == "FAILED", timeout=600, interval=5)

    sqs = _boto("sqs")

    def find(visibility: int) -> list[dict[str, Any]]:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            msgs = sqs.receive_message(QueueUrl=res["dlq_url"], MaxNumberOfMessages=10, WaitTimeSeconds=5,
                                       VisibilityTimeout=visibility).get("Messages", [])
            mine = [m for m in msgs if f"photos/original/{cid}/" in m["Body"]]
            if mine:
                return mine
        return []

    in_dlq = bool(find(0))  # 확인만 하고 바로 다시 보이게 둔다(알람 지표에 영향 없게)
    cw = _boto("cloudwatch")
    alarm_state, deadline = None, time.monotonic() + 300
    while time.monotonic() < deadline:
        alarm_state = cw.describe_alarms(AlarmNames=[res["alarm"]])["MetricAlarms"][0]["StateValue"]
        if alarm_state == "ALARM":
            break
        time.sleep(15)
    deleted = 0
    for m in find(30):  # 이 테스트가 만든 메시지만 지운다
        sqs.delete_message(QueueUrl=res["dlq_url"], ReceiptHandle=m["ReceiptHandle"])
        deleted += 1
    wait_photo_settled(stack, pid, cid)
    log = save_result("T9-dlq", {"claimId": cid, "observed": seen, "photoError": (rec or {}).get("photoError"),
                                 "inDlq": in_dlq, "alarmState": alarm_state, "deletedMessages": deleted})
    assert rec is not None and rec["photoError"] == "RETRY_EXHAUSTED" and not rec.get("deliveredAt"), f"(로그: {log})"
    assert in_dlq and deleted >= 1, f"DLQ 메시지 (로그: {log})"
    assert alarm_state == "ALARM", f"PhotoDLQNotEmpty (로그: {log})"
