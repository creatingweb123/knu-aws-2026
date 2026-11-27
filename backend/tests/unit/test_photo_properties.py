"""Property 25–28 (spec backend-stage5-photo-pipeline). 최소 100회.

- P25·P26: 이미지 순수 함수.
- P27: 처리 Lambda와 3단계 완료 트랜잭션의 전달 불변식(moto 상태 기계).
- P28: 업로드 URL 발급·교체(moto).
"""

import io
import warnings

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from PIL import Image

from domain import photo_image as pi

PBT = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow, HealthCheck.data_too_large])


# ------------------------------------------------------------------ P25


@st.composite
def source_images(draw):
    w = draw(st.integers(1, 4000))
    h = draw(st.integers(1, 4000))
    if w * h > 6_000_000:  # 테스트 시간을 위해 큰 이미지는 한 변을 줄인다(1600 경계는 그대로 넘는다)
        h = max(1, 6_000_000 // w)
    mode = draw(st.sampled_from(["RGB", "RGBA", "L", "P"]))
    fmt = "PNG" if mode in ("RGBA", "P") else draw(st.sampled_from(["JPEG", "PNG"]))
    orientation = draw(st.integers(1, 8))
    with_gps = draw(st.booleans())
    im = Image.new(mode, (w, h), draw(st.integers(0, 255)) if mode in ("L", "P") else tuple(draw(st.integers(0, 255)) for _ in mode))
    exif = Image.Exif()
    exif[0x0112] = orientation
    if with_gps:
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2] = "N", (37.0, 33.0, 59.0)
    buf = io.BytesIO()
    im.save(buf, fmt, exif=exif)
    return buf.getvalue(), (w, h), orientation


@PBT
@given(src=source_images())
def test_property25_processed_image_rules(src):
    """Feature: backend-stage5-photo-pipeline, Property 25: 처리본은 크기·형식 규칙을 지키고 메타데이터가 없다.

    Validates: Requirements 7.4, 7.5, 7.6
    """
    data, (w, h), orientation = src
    out = pi.process_image(data)
    im = Image.open(io.BytesIO(out.data))
    assert im.format == "JPEG" and im.mode == "RGB"
    assert max(im.size) <= 1600 and im.size == (out.width, out.height)
    ew, eh = (h, w) if orientation in (5, 6, 7, 8) else (w, h)  # JPEG·PNG 모두 EXIF 방향을 반영한다
    if max(ew, eh) <= 1600:
        assert im.size == (ew, eh)
    else:
        scale = 1600 / max(ew, eh)
        assert abs(im.size[0] - ew * scale) <= 1 and abs(im.size[1] - eh * scale) <= 1
    assert len(im.getexif()) == 0
    for k in ("exif", "icc_profile", "xmp", "comment"):
        assert k not in im.info


# ------------------------------------------------------------------ P26


def _valid(fmt):
    buf = io.BytesIO()
    Image.effect_noise((64, 48), 30).convert("RGB").save(buf, fmt)
    return buf.getvalue()


corrupt_inputs = st.one_of(
    st.binary(max_size=2048),
    st.tuples(st.sampled_from(["JPEG", "PNG"]), st.floats(0, 0.99)).map(lambda t: _valid(t[0])[: int(len(_valid(t[0])) * t[1])]),
    st.tuples(st.sampled_from(["JPEG", "PNG"]), st.binary(min_size=1, max_size=8)).map(lambda t: t[1] + _valid(t[0])[len(t[1]) :]),
    st.tuples(st.sampled_from([b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"]), st.binary(max_size=512)).map(lambda t: t[0] + t[1]),
    st.tuples(st.integers(1, 20_000), st.integers(1, 20_000)).filter(lambda t: t[0] * t[1] > pi.MAX_PIXELS).map(
        lambda t: _bomb_header(*t)
    ),
)


def _bomb_header(w, h):
    """IHDR만 큰 PNG 헤더(픽셀 데이터 없음)."""
    import struct
    import zlib

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk + struct.pack(">I", zlib.crc32(chunk))


@PBT
@given(data=corrupt_inputs)
def test_property26_rejections_are_typed(data):
    """Feature: backend-stage5-photo-pipeline, Property 26: 거부 사유는 입력 결함과 일치하고 예외가 새지 않는다.

    Validates: Requirements 7.1, 7.2, 7.3
    """
    old_max = Image.MAX_IMAGE_PIXELS
    filters_before = list(warnings.filters)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            out = pi.process_image(data)
            assert isinstance(out, pi.ProcessedImage)
        except pi.PhotoRejected as e:
            assert e.code in ("UNSUPPORTED_FORMAT", "TOO_LARGE", "TOO_MANY_PIXELS", "CORRUPT_IMAGE")
            if data[:8] != b"\x89PNG\r\n\x1a\n" and data[:3] != b"\xff\xd8\xff":
                assert e.code == "UNSUPPORTED_FORMAT"
    assert caught == [], [str(w.message) for w in caught]
    assert Image.MAX_IMAGE_PIXELS == old_max and warnings.filters == filters_before


# ------------------------------------------------------------------ P28

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402

from common import s3  # noqa: E402
from common.auth import User  # noqa: E402
from common.errors import ApiError  # noqa: E402
from common.validation import PhotoIn, PlanCreate  # noqa: E402
from domain import claim_service as cs  # noqa: E402
from domain import plan_service as ps  # noqa: E402
from tests.unit.moto_table import haru_table, set_env  # noqa: E402

START = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
P_OWNER = User("u-owner", "지연")
P_USERS = [User("u-a", "가"), User("u-b", "나")]
REQUESTERS = [P_OWNER, *P_USERS]
PHOTO = PhotoIn(contentType="image/jpeg", size=100)

p28_op = st.one_of(
    st.tuples(st.just("claim"), st.integers(0, 1)),
    st.tuples(st.just("abandon"), st.integers(0, 1)),
    st.tuples(st.just("record"), st.integers(0, 1)),
    st.tuples(st.just("complete"), st.integers(0, 1)),
    st.tuples(st.just("advance"), st.integers(1, 4)),
    st.tuples(st.just("photo_put"), st.integers(0, 2)),
    st.tuples(st.just("photo_replace"), st.integers(0, 2)),
    st.tuples(st.just("mark"), st.sampled_from(["PROCESSING", "FAILED"])),
)


def _record(table, pid, cid):
    return table.get_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, ConsistentRead=True).get("Item")


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(ops=st.lists(p28_op, min_size=1, max_size=12))
def test_property28_upload_url_and_replace(monkeypatch, ops):
    """Feature: backend-stage5-photo-pipeline, Property 28: 업로드 URL 발급·교체는 글과 전달 상태를 지킨다.

    Validates: Requirements 2, 3
    """
    set_env(monkeypatch)
    monkeypatch.setenv("PHOTO_BUCKET", "haru-photos-test")
    monkeypatch.setattr(s3, "_presign_client", None)
    presigned = []
    real = s3.presign_put
    monkeypatch.setattr(s3, "presign_put", lambda key, ct, size, now=None: presigned.append(key) or real(key, ct, size, now))
    with haru_table() as table:
        body = PlanCreate.model_validate({
            "title": "속성", "summary": "s", "reason": "r", "estimatedMinutes": 30,
            "places": [{"name": "빵집", "activity": "빵 사기", "whyChosen": ""}], "question": "q",
            "authoring": {"mode": "MANUAL", "durationMs": 1, "story": "빵집에서 빵을 사요"},
        })
        pid = ps.create_plan(P_OWNER, "k", body, START)[0]["planId"]
        now, latest = START, {}
        for name, arg in ops:
            if name == "advance":
                now += timedelta(days=arg)
                continue
            if name == "mark":  # 처리 Lambda가 바꾸는 상태를 흉내 낸다
                for cid in latest.values():
                    rec = _record(table, pid, cid)
                    if rec and "deliveredAt" not in rec and rec.get("photoKey"):
                        table.update_item(Key={"PK": f"PLAN#{pid}", "SK": f"RECORD#{cid}"}, UpdateExpression="SET photoStatus = :s, photoError = :e",
                                          ExpressionAttributeValues={":s": arg, ":e": "CORRUPT_IMAGE"})
                continue
            if name in ("claim", "abandon", "record", "complete"):
                user = P_USERS[arg]
                try:
                    if name == "claim":
                        latest[user.id] = cs.claim_plan(pid, user, now)[0]["claimId"]
                    elif user.id in latest:
                        {"abandon": lambda: cs.abandon(latest[user.id], user, now),
                         "record": lambda: cs.put_record(latest[user.id], user, f"{user.nickname}의 글", now),
                         "complete": lambda: cs.complete_by_user(latest[user.id], user, "TEXT_ONLY", now)}[name]()
                except ApiError:
                    pass
                continue
            # 사진 요청: 임의 요청자가 어떤 Claim에든 보낸다
            who = REQUESTERS[arg]
            targets = list(latest.values()) or ["clm_none"]
            cid = targets[arg % len(targets)]
            before = _record(table, pid, cid)
            n_presign = len(presigned)
            try:
                if name == "photo_put":
                    rec, up = cs.put_record_with_photo(cid, who, "사진과 글", PHOTO, now)
                else:
                    up = cs.replace_photo(cid, who, PHOTO, now)
                    rec = _record(table, pid, cid)
                ok = True
            except ApiError as e:
                ok = False
                code = e.code
            after = _record(table, pid, cid)
            if ok:
                assert after["photoStatus"] == "UPLOAD_PENDING" and "processedKey" not in after and "photoError" not in after
                assert before is None or after["photoKey"] != before.get("photoKey")
                assert presigned[-1] == after["photoKey"] and len(presigned) == n_presign + 1
                assert before is None or "deliveredAt" not in before  # 전달된 Record에는 성공하지 않는다
                if name == "photo_replace":
                    assert after["letter"] == before["letter"] and after["updatedAt"] == before["updatedAt"]
                else:
                    assert after["letter"] == "사진과 글"
            else:
                assert code in {"NOT_FOUND", "FORBIDDEN", "CLAIM_NOT_ACTIVE", "RECORD_REQUIRED"}
                assert after == before and len(presigned) == n_presign  # 실패는 아무것도 바꾸지 않고 presign하지 않는다


# ------------------------------------------------------------------ P27

import hashlib  # noqa: E402

from botocore.exceptions import ReadTimeoutError  # noqa: E402

from common.errors import TRY_AGAIN  # noqa: E402
from tests.unit.photo_fixtures import BUCKET, jpeg, photo_env, s3_record  # noqa: E402
from workers import photo_processor as pp  # noqa: E402

COLORS = [(255, 0, 0), (0, 200, 0), (0, 0, 255), (240, 240, 0)]
p27_pipeline = st.one_of(  # 시도 진행·중복 전달 연산은 자주 나오게 따로 둔다
    st.tuples(st.just("deliver"), st.integers(0, 5)),
    st.tuples(st.just("dup"), st.integers(0, 5)),
    st.tuples(st.just("step"), st.integers(0, 5)),
    st.tuples(st.just("step"), st.integers(0, 5)),
)
p27_op = st.one_of(
    p27_pipeline,
    p27_pipeline,
    st.tuples(st.just("claim"), st.integers(0, 1)),
    st.tuples(st.just("text"), st.integers(0, 1)),
    st.tuples(st.just("photo"), st.integers(0, 1), st.integers(0, 3)),
    st.tuples(st.just("reupload"), st.integers(0, 1), st.integers(0, 3)),
    st.tuples(st.just("replace"), st.integers(0, 1), st.integers(0, 3)),
    st.tuples(st.just("deliver"), st.integers(0, 5)),
    st.tuples(st.just("dup"), st.integers(0, 5)),
    st.tuples(st.just("step"), st.integers(0, 5)),
    st.tuples(st.just("flaky"), st.sampled_from(["try_again", "commit_timeout"])),
    st.tuples(st.just("complete_text"), st.integers(0, 1)),
    st.tuples(st.just("abandon"), st.integers(0, 1)),
    st.tuples(st.just("expire"), st.integers(0, 1)),
)


def _color_of(data):
    px = Image.open(io.BytesIO(data)).convert("RGB").getpixel((3, 3))
    return min(range(len(COLORS)), key=lambda i: sum((a - b) ** 2 for a, b in zip(px, COLORS[i])))


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow, HealthCheck.data_too_large])
@given(first=st.integers(0, 3), ops=st.lists(p27_op, min_size=1, max_size=25))
def test_property27_single_delivery_of_current_photo(monkeypatch, first, ops):
    """Feature: backend-stage5-photo-pipeline, Property 27: 사진 전달은 최대 한 번이고 전달된 사진은 그 시점의 현재 사진이다.

    Validates: Requirements 5, 6, 8, 9.7, 14.2
    """
    with photo_env(monkeypatch) as (table, client):
        body = PlanCreate.model_validate({
            "title": "속성", "summary": "s", "reason": "r", "estimatedMinutes": 30,
            "places": [{"name": "빵집", "activity": "빵 사기", "whyChosen": ""}], "question": "q",
            "authoring": {"mode": "MANUAL", "durationMs": 1, "story": "빵집에서 빵을 사요"},
        })
        pid = ps.create_plan(P_OWNER, "k", body, START)[0]["planId"]
        state = {"now": START, "latest": {}, "flaky": None}
        queue: list[dict] = []            # SQS 메시지(S3 레코드)
        running: list[tuple] = []         # (Attempt, generator, message)
        made_from: dict[str, tuple] = {}  # 처리본 키 → (원본 키, eTag)
        etag_color: dict[tuple, int] = {}
        preserved: set[str] = set()       # 불확실 등으로 끝나 보존된 처리본
        delivered_hash: dict[str, str] = {}
        real_complete = cs.complete_claim

        def flaky_complete(*a, **k):
            if a[1] != "WITH_PHOTO":  # 사용자의 글로 완료(complete_by_user)에는 주입하지 않는다
                return real_complete(*a, **k)
            mode, state["flaky"] = state["flaky"], None
            if mode == "try_again":
                raise ApiError(TRY_AGAIN)  # 커밋 없이 불확실
            result = real_complete(*a, **k)
            if mode == "commit_timeout":
                raise ReadTimeoutError(endpoint_url="dynamodb")  # 커밋했지만 응답을 못 받음
            return result

        monkeypatch.setattr(cs, "complete_claim", flaky_complete)

        def rec_of(cid):
            return _record(table, pid, cid)

        def put_original(key, color):
            etag = client.put_object(Bucket=BUCKET, Key=key, Body=jpeg(COLORS[color], size=(32, 24)))["ETag"].strip('"')
            etag_color[(key, etag)] = color
            queue.append(s3_record(key, etag))

        def advance(idx):
            if not running:
                return
            att, gen, msg = running[idx % len(running)]
            try:
                label = next(gen)
                if label == "uploaded":
                    made_from[att.attempt_key] = (att.key, att.etag)
            except StopIteration:
                running.remove((att, gen, msg))
            except Exception:  # noqa: BLE001  재시도 대상: 메시지를 다시 넣는다(SQS 재전달)
                running.remove((att, gen, msg))
                if att.created:
                    preserved.add(att.attempt_key)
                queue.append(msg)

        def observe_delivery():
            for cid in set(state["latest"].values()):
                rec = rec_of(cid)
                if rec and rec.get("processedKey") and rec["processedKey"] not in delivered_hash:
                    data = client.get_object(Bucket=BUCKET, Key=rec["processedKey"])["Body"].read()
                    delivered_hash[rec["processedKey"]] = hashlib.sha256(data).hexdigest()

        ops = [("claim", 0), ("photo", 0, first)] + list(ops)  # 늘 사진 1건으로 시작한다
        for op in ops:
            name, arg = op[0], op[1]
            user = P_USERS[arg] if name not in ("deliver", "dup", "step", "flaky") else None
            cid = state["latest"].get(user.id) if user else None
            try:
                if name == "claim":
                    state["latest"][user.id] = cs.claim_plan(pid, user, state["now"])[0]["claimId"]
                elif name == "expire":
                    state["now"] += timedelta(days=4)
                    state["latest"][user.id] = cs.claim_plan(pid, user, state["now"])[0]["claimId"]
                elif name == "text" and cid:
                    cs.put_record(cid, user, "글", state["now"])
                elif name == "photo" and cid:
                    cs.put_record_with_photo(cid, user, "사진과 글", PHOTO, state["now"])
                    put_original(rec_of(cid)["photoKey"], op[2])
                elif name == "reupload" and cid and rec_of(cid) and rec_of(cid).get("photoKey"):
                    put_original(rec_of(cid)["photoKey"], op[2])  # 같은 키에 다른 내용(스위치 꺼짐)
                elif name == "replace" and cid:
                    cs.replace_photo(cid, user, PHOTO, state["now"])
                    put_original(rec_of(cid)["photoKey"], op[2])
                elif name == "complete_text" and cid:
                    cs.complete_by_user(cid, user, "TEXT_ONLY", state["now"])
                elif name == "abandon" and cid:
                    cs.abandon(cid, user, state["now"])
                elif name == "deliver" and queue:
                    msg = queue.pop(arg % len(queue))
                    att = pp.Attempt(msg)
                    running.append((att, att.steps(), msg))
                elif name == "dup" and queue:
                    queue.append(queue[arg % len(queue)])
                elif name == "step":
                    advance(arg)
                elif name == "flaky":
                    state["flaky"] = arg
            except ApiError:
                pass
            observe_delivery()

        # 남은 시도와 메시지를 모두 처리한다(불확실 주입은 끈다)
        state["flaky"] = None
        for _ in range(200):
            if running:
                advance(0)
            elif queue:
                msg = queue.pop(0)
                att = pp.Attempt(msg)
                running.append((att, att.steps(), msg))
            else:
                break
            observe_delivery()
        assert not running and not queue

        items = [i for i in table.scan(ConsistentRead=True)["Items"]]
        inbox = [i for i in items if i["SK"].startswith("INBOX#")]
        records = [i for i in items if i["SK"].startswith("RECORD#")]
        delivered = [r for r in records if r.get("deliveredAt")]
        assert len(inbox) <= 1 and len(inbox) == len(delivered)  # 전달 1회 ⇔ InboxItem 1건
        listed = {o["Key"] for o in client.list_objects_v2(Bucket=BUCKET, Prefix="photos/processed/").get("Contents", [])}
        for r in records:
            has = bool(r.get("processedKey"))
            assert has == (r.get("photoStatus") == "READY")
            if r.get("deliveredAt"):
                (item,) = [i for i in inbox if i["itemId"] == r["claimId"]]
                assert item["hasPhoto"] is has
            else:
                assert not has
            if has:
                pk = r["processedKey"]
                assert pk in listed
                orig_key, etag = made_from[pk]
                assert orig_key == r["photoKey"]  # 지난 사진이 아니다
                data = client.get_object(Bucket=BUCKET, Key=pk)["Body"].read()
                assert _color_of(data) == etag_color[(orig_key, etag)]  # 그 ETag의 객체에서 만들었다
                assert hashlib.sha256(data).hexdigest() == delivered_hash[pk]  # 전달 뒤 바뀌거나 지워지지 않았다
        referenced = {r["processedKey"] for r in records if r.get("processedKey")}
        assert listed <= referenced | preserved  # 확실히 미전달인 시도의 처리본은 남지 않는다
        event(f"photo_delivered={bool(referenced)}")
        event(f"processed_objects_made={'2+' if len(made_from) >= 2 else len(made_from)}")
        event(f"preserved={bool(preserved)}")
        event(f"text_delivered={any(r.get('deliveredAt') and not r.get('processedKey') for r in records)}")
