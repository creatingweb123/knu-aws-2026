"""PUT /claims/{claimId}/record(photo), POST /claims/{claimId}/record/photo (moto DynamoDB, presign 스파이).

Validates: spec backend-stage5-photo-pipeline Requirements 2.1–2.10, 3.1–3.6, 14.1 (BE-Q34 해소, BE-Q50–BE-Q52)
"""

import json
from datetime import timedelta

import pytest

pytest.importorskip("moto")

from common import ddb, s3  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from handlers import claims, plans  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

OWNER = {"sub": "u-owner", "nickname": "지연"}
SUHYUN = {"sub": "u-suhyun", "nickname": "수현"}
MINJUN = {"sub": "u-minjun", "nickname": "민준"}
PLAN = {
    "title": "이사 전, 마지막 동네 산책", "summary": "출근길 빵집", "reason": "이삿짐", "estimatedMinutes": 45,
    "places": [{"name": "출근길 빵집", "activity": "빵 사기", "whyChosen": ""}], "question": "q",
    "authoring": {"mode": "MANUAL", "durationMs": 1, "story": "출근길 빵집에 들러 빵을 사요"},
}
JPEG = {"contentType": "image/jpeg", "size": 2_480_000}


@pytest.fixture
def table(monkeypatch):
    set_env(monkeypatch)
    monkeypatch.setenv("PHOTO_BUCKET", "haru-photos-test")
    monkeypatch.delenv("PHOTO_UPLOAD_IF_NONE_MATCH", raising=False)
    monkeypatch.setattr(s3, "_presign_client", None)
    with haru_table() as t:
        yield t


@pytest.fixture
def presigns(monkeypatch):
    calls = []
    real = s3.presign_put

    def spy(key, content_type, size, now=None):
        calls.append({"key": key, "contentType": content_type, "size": size})
        return real(key, content_type, size, now)

    monkeypatch.setattr(s3, "presign_put", spy)
    return calls


def ev(route, who=None, body=None, path=None, raw=None, claims_=None):
    c = claims_ if claims_ is not None else ({"token_use": "id", **who} if who else None)
    return {
        "version": "2.0", "routeKey": route, "headers": {"idempotency-key": "k1"}, "pathParameters": path,
        "queryStringParameters": None, "isBase64Encoded": False,
        "body": raw if raw is not None else (json.dumps(body, ensure_ascii=False) if body is not None else None),
        "requestContext": {"authorizer": {"jwt": {"claims": c}}} if c is not None else {},
    }


def call(handler, route, who=None, **kw):
    resp = handler(ev(route, who, **kw), None)
    return resp["statusCode"], json.loads(resp["body"]) if resp.get("body") else None


def claimed():
    status, body = call(plans.handler, "POST /plans", OWNER, body=PLAN)
    assert status == 201
    pid = body["plan"]["planId"]
    _, b = call(plans.handler, "POST /plans/{planId}/claims", SUHYUN, path={"planId": pid})
    return pid, b["claim"]["claimId"]


def record(table, pid, cid):
    return table.get_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, ConsistentRead=True).get("Item")


def put(cid, who=SUHYUN, photo=JPEG, letter="소금빵을 샀어요"):
    body = {"letter": letter} if photo is None else {"letter": letter, "photo": photo}
    return call(claims.handler, "PUT /claims/{claimId}/record", who, body=body, path={"claimId": cid})


def replace(cid, who=SUHYUN, photo=JPEG):
    return call(claims.handler, "POST /claims/{claimId}/record/photo", who, body=photo, path={"claimId": cid})


# ------------------------------------------------------------------ PUT /record + photo


def test_put_with_photo_issues_upload(table, presigns):
    pid, cid = claimed()
    status, body = put(cid)
    assert status == 200 and set(body) == {"record", "upload"}
    up = body["upload"]
    assert set(up) == {"url", "method", "headers", "expiresAt"} and up["method"] == "PUT"
    assert up["headers"] == {"Content-Type": "image/jpeg"} and up["expiresAt"].endswith("Z") and len(up["expiresAt"]) == 24
    rec = record(table, pid, cid)
    assert rec["photoStatus"] == "UPLOAD_PENDING" and s3.parse_original_key(rec["photoKey"])[0] == cid
    assert "processedKey" not in rec and "photoError" not in rec
    assert presigns == [{"key": rec["photoKey"], "contentType": "image/jpeg", "size": 2_480_000}]
    assert body["record"]["photoStatus"] == "UPLOAD_PENDING" and "photoKey" not in body["record"]


def test_put_with_photo_twice_new_key_and_png(table, presigns):
    pid, cid = claimed()
    put(cid)
    first = record(table, pid, cid)["photoKey"]
    put(cid, photo={"contentType": "image/png", "size": 1})
    second = record(table, pid, cid)["photoKey"]
    assert first != second and second.endswith(".png")


def test_put_with_photo_clears_previous_failure(table, presigns):
    pid, cid = claimed()
    put(cid)
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :f, photoError = :e, processedKey = :p",
                      ExpressionAttributeValues={":f": "FAILED", ":e": "CORRUPT_IMAGE", ":p": "photos/processed/x/y.jpg"})
    put(cid, letter="다시 쓴 글")
    rec = record(table, pid, cid)
    assert rec["photoStatus"] == "UPLOAD_PENDING" and "photoError" not in rec and "processedKey" not in rec and rec["letter"] == "다시 쓴 글"


@pytest.mark.parametrize("state", ["UPLOAD_PENDING", "PROCESSING", "FAILED"])
def test_put_without_photo_keeps_photo_state(table, presigns, state):
    pid, cid = claimed()
    put(cid)
    key = record(table, pid, cid)["photoKey"]
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :s, photoError = :e",
                      ExpressionAttributeValues={":s": state, ":e": "X"})
    status, body = put(cid, photo=None, letter="글만 고침")
    rec = record(table, pid, cid)
    assert status == 200 and body["upload"] is None and len(presigns) == 1
    assert rec["photoStatus"] == state and rec["photoKey"] == key and rec["photoError"] == "X" and rec["letter"] == "글만 고침"


@pytest.mark.parametrize(
    "photo,key",
    [
        ({"contentType": "image/gif", "size": 10}, "photo.contentType"),
        ({"contentType": "image/jpeg", "size": 0}, "photo.size"),
        ({"contentType": "image/jpeg", "size": 10_485_761}, "photo.size"),
        ({"contentType": "image/jpeg", "size": True}, "photo.size"),
        ({"contentType": "image/jpeg", "size": 1.5}, "photo.size"),
        ("x", "photo"),
    ],
)
def test_put_photo_validation_before_db(table, presigns, monkeypatch, photo, key):
    _, cid = claimed()
    monkeypatch.setattr(ddb, "table", lambda: (_ for _ in ()).throw(AssertionError("DB 접근 금지")))
    status, body = put(cid, photo=photo)
    assert status == 400 and key in body["error"]["details"] and presigns == []


def test_put_photo_boundary_size_ok(table, presigns):
    _, cid = claimed()
    assert put(cid, photo={"contentType": "image/jpeg", "size": 10_485_760})[0] == 200
    assert put(cid, photo={"contentType": "image/jpeg", "size": 1})[0] == 200


def test_put_photo_failures_do_not_presign(table, presigns):
    pid, cid = claimed()
    assert put(cid, who=MINJUN)[0] == 403
    assert put("clm_none")[0] == 404
    call(claims.handler, "POST /claims/{claimId}/abandon", SUHYUN, path={"claimId": cid})
    status, body = put(cid)
    assert status == 409 and body["error"]["code"] == "CLAIM_NOT_ACTIVE"
    assert presigns == []


def test_put_photo_after_delivery_rejected(table, presigns):
    pid, cid = claimed()
    put(cid, photo=None)
    call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
    status, body = put(cid)
    assert status == 409 and presigns == []


def test_put_photo_try_again_does_not_presign(table, presigns, monkeypatch):
    from common.errors import TRY_AGAIN, ApiError

    _, cid = claimed()
    monkeypatch.setattr(ddb, "transact_with_retry", lambda items: (_ for _ in ()).throw(ApiError(TRY_AGAIN)))
    assert put(cid)[0] == 503 and presigns == []


def test_put_photo_switch_on_headers(table, presigns, monkeypatch):
    monkeypatch.setenv("PHOTO_UPLOAD_IF_NONE_MATCH", "true")
    _, cid = claimed()
    assert put(cid)[1]["upload"]["headers"] == {"Content-Type": "image/jpeg", "If-None-Match": "*"}


@pytest.mark.parametrize("route", ["PUT /claims/{claimId}/record", "POST /claims/{claimId}/record/photo"])
def test_access_token_401_without_db(table, presigns, monkeypatch, route):
    monkeypatch.setattr(ddb, "table", lambda: (_ for _ in ()).throw(AssertionError("DB 접근 금지")))
    resp = claims.handler(ev(route, body={"letter": "x", "photo": JPEG, **JPEG}, path={"claimId": "c"}, claims_={"token_use": "access", "sub": "u-suhyun"}), None)
    assert resp["statusCode"] == 401 and json.loads(resp["body"])["error"]["code"] == "UNAUTHORIZED" and presigns == []


# ------------------------------------------------------------------ POST /record/photo


@pytest.mark.parametrize("state", ["NONE", "UPLOAD_PENDING", "PROCESSING", "FAILED"])
def test_replace_photo(table, presigns, state):
    pid, cid = claimed()
    put(cid, photo=None)
    before = record(table, pid, cid)
    table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :s, photoError = :e, photoKey = :k",
                      ExpressionAttributeValues={":s": state, ":e": "CORRUPT_IMAGE", ":k": "photos/original/old.jpg"})
    status, body = replace(cid)
    assert status == 200 and set(body) == {"upload"}  # BE-Q51 권장안
    rec = record(table, pid, cid)
    assert rec["photoStatus"] == "UPLOAD_PENDING" and rec["photoKey"] != "photos/original/old.jpg" and "photoError" not in rec
    assert rec["letter"] == before["letter"] and rec["updatedAt"] == before["updatedAt"]  # 글 보존
    assert presigns[-1]["key"] == rec["photoKey"]


def test_replace_without_record_is_400(table, presigns):
    _, cid = claimed()
    status, body = replace(cid)
    assert status == 400 and body["error"]["code"] == "RECORD_REQUIRED" and presigns == []  # BE-Q52 권장안


def test_replace_finished_claim_409_before_record_check(table, presigns):
    _, cid = claimed()
    call(claims.handler, "POST /claims/{claimId}/abandon", SUHYUN, path={"claimId": cid})
    status, body = replace(cid)  # Record도 없지만 끝난 이어받기가 먼저
    assert status == 409 and body["error"]["code"] == "CLAIM_NOT_ACTIVE"


def test_replace_delivered_409(table, presigns):
    _, cid = claimed()
    put(cid, photo=None)
    call(claims.handler, "POST /claims/{claimId}/complete", SUHYUN, body={"mode": "TEXT_ONLY"}, path={"claimId": cid})
    assert replace(cid)[0] == 409 and presigns == []


def test_replace_auth_and_validation(table, presigns):
    _, cid = claimed()
    put(cid, photo=None)
    assert replace(cid, who=MINJUN)[0] == 403
    assert replace(cid, who=OWNER)[0] == 403
    assert replace("clm_none")[0] == 404
    for body, key in [({"contentType": "image/gif", "size": 1}, "contentType"), ({"contentType": "image/png", "size": 0}, "size")]:
        status, b = replace(cid, photo=body)
        assert status == 400 and key in b["error"]["details"]
    status, b = call(claims.handler, "POST /claims/{claimId}/record/photo", SUHYUN, raw="[]", path={"claimId": cid})
    assert status == 400 and "body" in b["error"]["details"]
    assert presigns == []


def test_photo_status_update_helper(table, presigns):
    pid, cid = claimed()
    put(cid)
    key = record(table, pid, cid)["photoKey"]
    assert cs.photo_status_update(pid, cid, key=key, to="PROCESSING", allowed_from=("UPLOAD_PENDING", "PROCESSING")) is True
    assert cs.photo_status_update(pid, cid, key="other", to="FAILED", allowed_from=("PROCESSING",), error="X") is False
    assert cs.photo_status_update(pid, cid, key=key, to="FAILED", allowed_from=("PROCESSING",), error="CORRUPT_IMAGE") is True
    rec = record(table, pid, cid)
    assert rec["photoStatus"] == "FAILED" and rec["photoError"] == "CORRUPT_IMAGE"
    assert cs.photo_status_update(pid, cid, key=key, to="PROCESSING", allowed_from=("UPLOAD_PENDING", "PROCESSING")) is False


def test_text_only_put_record_signature_unchanged(table, presigns):
    """3단계 시그니처(위치 인자 now)와 dict 반환이 그대로다."""
    from datetime import datetime, timezone

    from common.auth import User

    pid, cid = claimed()
    rec = cs.put_record(cid, User("u-suhyun", "수현"), "글", datetime(2026, 11, 20, tzinfo=timezone.utc) + timedelta(hours=1))
    assert isinstance(rec, dict) and rec["updatedAt"] == "2026-11-20T01:00:00.000Z" and rec["photoStatus"] == "NONE"
