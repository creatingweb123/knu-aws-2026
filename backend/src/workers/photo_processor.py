"""사진 처리 Lambda (SQS, batch 1) — BE-PHOTO-01–07, spec backend-stage5-photo-pipeline design "처리 Lambda 알고리즘".

한 S3 레코드(원본 업로드 1건)를 처리 시도(Attempt) 하나로 다룬다.
  해석·무시 조건 → HeadObject(IfMatch=eTag) → PROCESSING 조건부 전환 → (주입) → GetObject(IfMatch) → process_image
  → 처리본 PutObject(IfNoneMatch=*, 시도별 attemptUuid 키) → complete_claim(WITH_PHOTO) → ConsistentRead 재조회로 판정
  → 전달됨이면 지표 / 확실히 미전달이면 이 시도가 만든 처리본만 삭제 / 불확실이면 보존하고 예외(SQS 재시도).

정확히 한 번 전달은 3단계 complete_claim(바꾸지 않음)이 지킨다. 이 모듈은 그 앞뒤에서 처리해도 되는지 거르고
자기 처리본만 정리한다. 로그에는 결과·사유 코드만 남긴다(키·claimId·사용자 ID·URL 없음, BE-NFR-03).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from common import ddb, metrics, s3
from common.errors import CLAIM_NOT_ACTIVE, NOT_FOUND, RECORD_REQUIRED, TRY_AGAIN, ApiError
from domain import claim_service as cs
from domain import photo_image
from domain.plan_service import _get

_log = logging.getLogger(__name__)

DEV_STACK = "haru-dev"  # samconfig.toml dev stack_name과 같아야 한다(BE-Q59)
FAULT_PHOTO, FAULT_SLOW = "photo", "photo-slow"


class TimeBudgetExceeded(Exception):
    """남은 실행 시간이 부족해 단계를 시작하지 않았다(재시도 대상)."""


class PhotoOutcomeUncertain(Exception):
    """완료 트랜잭션이 커밋됐는지 확정하지 못했다. 처리본은 보존한다(재시도 대상)."""


class FaultInjected(Exception):
    """FAULT_INJECT=photo (dev·로컬 전용)."""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def sdk_config() -> Config:
    """이 함수만의 SDK 설정(BE-Q71 초기값). 공통 설정(BE-Q48)은 바꾸지 않는다."""
    return Config(
        connect_timeout=_env_float("PHOTO_SDK_CONNECT_TIMEOUT_S", 2),
        read_timeout=_env_float("PHOTO_SDK_READ_TIMEOUT_S", 5),
        retries={"mode": "standard", "total_max_attempts": _env_int("PHOTO_SDK_MAX_ATTEMPTS", 2)},
    )


_s3: Any = None
_ready = False
_fault_block_logged = False


def _init_once() -> None:
    """콜드 스타트 초기화. 이 함수의 S3 클라이언트와 HaruTable 리소스에만 짧은 SDK 설정을 쓴다."""
    global _s3, _ready
    if _ready:
        return
    cfg = sdk_config()
    if _s3 is None:
        _s3 = boto3.client("s3", config=cfg)
    ddb.use_table(boto3.resource("dynamodb", config=cfg).Table(os.environ["TABLE_NAME"]))
    _ready = True


def fault_mode() -> str:
    """허용된 경우에만 FAULT_INJECT 값을 돌려준다(BE-Q59의 런타임 검증).

    허용 조건: FAULT_INJECT_ALLOWED == "true" 이고, Lambda 런타임의 실제 함수 이름이 `haru-dev-`로 시작하거나
    (AWS가 아닌) 로컬이면 STAGE == "local". 하나라도 아니면 무시하고 경고를 한 번 남긴다.
    """
    global _fault_block_logged
    mode = os.environ.get("FAULT_INJECT", "")
    if mode not in (FAULT_PHOTO, FAULT_SLOW):
        return ""
    fn = os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    allowed = os.environ.get("FAULT_INJECT_ALLOWED") == "true" and (
        (fn is not None and fn.startswith(f"{DEV_STACK}-")) or (fn is None and os.environ.get("STAGE") == "local")
    )
    if not allowed:
        if not _fault_block_logged:
            _log.warning("fault_inject_blocked")
            _fault_block_logged = True
        return ""
    return mode


def _status(e: ClientError) -> int:
    return int(e.response.get("ResponseMetadata", {}).get("HTTPStatusCode") or 0)


def _code(e: ClientError) -> str:
    return str(e.response.get("Error", {}).get("Code", ""))


def _precondition_failed(e: ClientError) -> bool:
    return _status(e) == 412 or _code(e) in ("PreconditionFailed", "412")


def _not_found(e: ClientError) -> bool:
    return _status(e) == 404 or _code(e) in ("NoSuchKey", "404", "NotFound")


def settle(original_key: str, attempt_key: str, rec_after: dict[str, Any] | None, claim_after: dict[str, Any] | None) -> str:
    """완료 호출 뒤 재조회 결과로 이 시도의 처리본 전달 여부를 정한다: delivered | not_delivered | uncertain.

    Record의 processedKey는 완료 트랜잭션만 쓰므로, Record가 이 키를 가리키지 않는 확정 상태면 미전달이다.
    """
    if rec_after is None:  # Record가 없으면 이 처리본을 가리킬 수 있는 항목이 없다(읽기 실패는 예외로 올라와 여기 오지 않는다)
        return "not_delivered"
    if rec_after.get("deliveredAt"):
        return "delivered" if rec_after.get("processedKey") == attempt_key else "not_delivered"
    if rec_after.get("photoKey") != original_key or rec_after.get("photoStatus") == cs.PHOTO_DISCARDED:
        return "not_delivered"
    if claim_after is not None and claim_after.get("status") in (cs.ABANDONED, cs.EXPIRED):
        return "not_delivered"
    return "uncertain"  # 아직 PROCESSING·미전달: 커밋 여부를 알 수 없다


class Attempt:
    """S3 레코드 1건의 처리 시도 1회. steps()는 단계 사이에서 yield한다(속성 테스트가 끼어들 수 있게)."""

    def __init__(self, rec: dict[str, Any], context: Any = None) -> None:
        obj = (rec.get("s3") or {}).get("object") or {}
        self.key = unquote_plus(str(obj.get("key", "")))
        self.etag = obj.get("eTag")
        self.context = context
        self.claim_id: str | None = None
        self.plan_id: str | None = None
        self.attempt_key: str | None = None
        self.created = False
        self.result: str | None = None  # ignored | failed | delivered | not_delivered

    # ----------------------------------------------------------------- 보조

    def _remaining_ms(self) -> float:
        fn = getattr(self.context, "get_remaining_time_in_millis", None)
        return fn() if fn else float("inf")

    def _guard(self, env_name: str, default_ms: int) -> None:
        need = _env_int(env_name, default_ms) + _env_int("PHOTO_RESERVE_MS", 5_000)
        if self._remaining_ms() < need:
            _log.warning("photo_retry reason=time_budget step=%s", env_name)
            raise TimeBudgetExceeded(env_name)

    def _ignore(self, reason: str) -> None:
        self.result = "ignored"
        _log.info("photo_ignored reason=%s", reason)

    def _fail(self, code: str) -> None:
        written = cs.photo_status_update(self.plan_id, self.claim_id, key=self.key, to=cs.PHOTO_FAILED,
                                         allowed_from=(cs.PHOTO_PROCESSING,), error=code)
        if written:
            metrics.emit(metrics.PHOTO_FAILED)
        self.result = "failed"
        _log.info("photo_failed code=%s written=%s", code, written)

    def _delete_own(self, reason: str) -> None:
        """이 시도가 PutObject 200으로 만든 처리본만 지운다. 실패해도 예외로 올리지 않는다(판정은 끝났다)."""
        if not (self.created and self.attempt_key):
            return
        try:
            _s3.delete_object(Bucket=s3.photo_bucket(), Key=self.attempt_key)
        except (ClientError, BotoCoreError):
            _log.warning("photo_cleanup_failed reason=%s", reason)

    def _if_match(self) -> dict[str, str]:
        return {"IfMatch": s3.quote_etag(self.etag)} if self.etag else {}

    # ----------------------------------------------------------------- 단계

    def steps(self) -> Iterator[str]:
        parsed = s3.parse_original_key(self.key)
        if parsed is None:
            self._ignore("bad_key")
            return
        self.claim_id = parsed[0]
        lookup = _get(f"CLAIM#{self.claim_id}")
        if lookup is None:
            self._ignore("no_lookup")
            return
        self.plan_id = lookup["planId"]
        record = _get(f"PLAN#{self.plan_id}", f"RECORD#{self.claim_id}")
        if record is None:
            self._ignore("no_record")
            return
        if record.get("deliveredAt"):
            self._ignore("delivered")
            return
        if record.get("photoStatus") == cs.PHOTO_DISCARDED:
            self._ignore("discarded")
            return
        if record.get("photoKey") != self.key:
            self._ignore("stale_key")
            return
        if record.get("photoStatus") == cs.PHOTO_READY:
            _log.warning("photo_unexpected_ready")  # BE-Q66: 완료 트랜잭션만 READY를 deliveredAt과 함께 쓴다
            self.result = "ignored"
            return

        self._guard("PRE_READ_MS", 7_000)
        try:
            head = _s3.head_object(Bucket=s3.photo_bucket(), Key=self.key, **self._if_match())
        except ClientError as e:
            if _precondition_failed(e):
                self._ignore("etag_changed")
                return
            if _not_found(e):
                self._ignore("gone")
                return
            raise  # 403 등은 권한 결함일 수 있으므로 숨기지 않는다(BE-Q70)
        yield "checked"

        if not cs.photo_status_update(self.plan_id, self.claim_id, key=self.key, to=cs.PHOTO_PROCESSING,
                                      allowed_from=(cs.PHOTO_UPLOAD_PENDING, cs.PHOTO_PROCESSING)):
            self._ignore("state_changed")
            return
        mode = fault_mode()
        if mode == FAULT_PHOTO:
            raise FaultInjected()
        if mode == FAULT_SLOW:
            time.sleep(min(max(_env_float("FAULT_DELAY_S", 5), 1), 10))
        yield "processing"

        if int(head.get("ContentLength") or 0) > photo_image.MAX_BYTES:
            self._fail(photo_image.TOO_LARGE)
            return
        self._guard("PRE_PROCESS_MS", 12_000)
        started = time.monotonic()
        try:
            obj = _s3.get_object(Bucket=s3.photo_bucket(), Key=self.key, **self._if_match())
        except ClientError as e:
            if _precondition_failed(e):
                self._ignore("etag_changed")
                return
            if _not_found(e):
                self._ignore("gone")
                return
            raise
        data = obj["Body"].read(photo_image.MAX_BYTES + 1)
        try:
            image = photo_image.process_image(data)
        except photo_image.PhotoRejected as r:
            self._fail(r.code)
            return

        self._guard("PRE_UPLOAD_MS", 7_000)
        for _ in range(2):
            candidate = s3.new_processed_key(self.claim_id)
            try:
                _s3.put_object(Bucket=s3.photo_bucket(), Key=candidate, Body=image.data, ContentType="image/jpeg", IfNoneMatch="*")
            except ClientError as e:
                if _precondition_failed(e):
                    continue  # 그 키에 남의 객체가 있다. 자기 것이 아니므로 건드리지 않는다
                raise  # 생성 여부를 모른다: created=False, 완료·삭제 없이 재시도
            self.attempt_key, self.created = candidate, True
            break
        else:
            raise RuntimeError("processed_key_conflict")
        yield "uploaded"

        if self._remaining_ms() < _env_int("PRE_COMPLETE_MS", 10_000) + _env_int("PHOTO_RESERVE_MS", 5_000):
            self._delete_own("time_budget")  # 완료를 부르지 않았으므로 확실히 미전달
            _log.warning("photo_retry reason=time_budget step=PRE_COMPLETE_MS")
            raise TimeBudgetExceeded("PRE_COMPLETE_MS")
        call_unknown = False
        try:
            cs.complete_claim(self.claim_id, cs.WITH_PHOTO, key=self.key, processed_key=self.attempt_key)
        except ApiError as e:
            if e.code == TRY_AGAIN:
                call_unknown = True
            elif e.code not in (CLAIM_NOT_ACTIVE, RECORD_REQUIRED, NOT_FOUND):
                raise
        except (ClientError, BotoCoreError):
            call_unknown = True  # 커밋 여부를 모른다. 재조회로 판정한다
        yield "completed"

        rec_after = _get(f"PLAN#{self.plan_id}", f"RECORD#{self.claim_id}")  # 실패하면 예외 → 삭제 없이 재시도
        claim_after = _get(f"PLAN#{self.plan_id}", f"CLAIM#{self.claim_id}")
        outcome = settle(self.key, self.attempt_key, rec_after, claim_after)
        if outcome == "delivered":
            self.result = "delivered"
            metrics.emit(metrics.PHOTO_PROCESSING_MS, round((time.monotonic() - started) * 1000), unit="Milliseconds")
            _log.info("photo_delivered")
        elif outcome == "not_delivered":
            self.result = "not_delivered"
            self._delete_own("not_delivered")
            _log.info("photo_not_delivered call_unknown=%s", call_unknown)
        else:
            _log.warning("photo_retry reason=outcome_uncertain")
            raise PhotoOutcomeUncertain()

    # ----------------------------------------------------------------- 실행

    def run(self, receive_count: int) -> str | None:
        try:
            for _ in self.steps():
                pass
        except Exception:
            if receive_count >= 3 and self.plan_id and self.claim_id:
                self.mark_retry_exhausted()
            raise
        return self.result

    def mark_retry_exhausted(self) -> None:
        """3번째 수신에서 실패하면 예외 전에 FAILED RETRY_EXHAUSTED를 조건부로 쓴다. 쓰기 실패는 삼킨다(원래 예외가 우선)."""
        try:
            if cs.photo_status_update(self.plan_id, self.claim_id, key=self.key, to=cs.PHOTO_FAILED,
                                      allowed_from=(cs.PHOTO_UPLOAD_PENDING, cs.PHOTO_PROCESSING),
                                      error=photo_image.RETRY_EXHAUSTED):
                metrics.emit(metrics.PHOTO_FAILED)
                _log.info("photo_failed code=RETRY_EXHAUSTED written=True")
        except Exception:  # noqa: BLE001
            _log.warning("photo_retry_exhausted_write_failed")


def _parse(body: Any) -> dict[str, Any] | None:
    try:
        doc = json.loads(body) if isinstance(body, str) else body
    except (TypeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def handler(event: dict[str, Any], context: Any) -> None:
    _init_once()
    for msg in event.get("Records") or []:
        receive_count = int((msg.get("attributes") or {}).get("ApproximateReceiveCount", "1"))
        doc = _parse(msg.get("body"))
        if doc is None or doc.get("Event") == "s3:TestEvent" or not isinstance(doc.get("Records"), list):
            _log.info("photo_ignored reason=not_s3_record")
            continue
        for rec in doc["Records"]:
            Attempt(rec, context).run(receive_count)  # 예외는 그대로 올라가 메시지가 남는다(SQS 재시도)
