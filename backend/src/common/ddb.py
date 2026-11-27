"""DynamoDB 접근과 트랜잭션 공통 실패 처리 (§2.6, BE-REC-10).

엔드포인트는 SDK 표준 변수 AWS_ENDPOINT_URL에 맡기고 앱 코드에서 다루지 않는다.
트랜잭션은 리소스 클라이언트(table().meta.client)로 보내므로 항목 값은 파이썬 기본 타입으로 쓴다.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import ClientError

from common.errors import TRY_AGAIN, ApiError

BACKOFF_SECONDS = (0.05, 0.1, 0.2)  # 최대 3회 재시도

_log = logging.getLogger(__name__)

_table: Any = None


def table() -> Any:
    """HaruTable 리소스. 같은 실행 환경에서 재사용한다."""
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def use_table(t: Any) -> None:
    """이 실행 환경의 HaruTable 리소스를 바꾼다.

    AiCardFunction(짧은 타임아웃·제한된 재시도, BE-Q85)과 사진 처리 Lambda(design "처리 Lambda 알고리즘")가
    자기 SDK 설정의 리소스를 꽂을 때만 쓴다.
    다른 함수는 부르지 않으므로 기본 SDK 설정 그대로다(BE-Q48 미결 유지).
    """
    global _table
    _table = t


class ConditionFailed(Exception):
    """모든 실패 사유가 ConditionalCheckFailed인 트랜잭션 취소. 서비스 계층이 재조회해 분기한다."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("ConditionalCheckFailed")


def _cancellation_codes(e: ClientError) -> list[str]:
    reasons = e.response.get("CancellationReasons") or []
    return [r.get("Code", "None") for r in reasons]


def transact_with_retry(
    items: list[dict[str, Any]],
    *,
    client: Any = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """TransactWriteItems를 실행한다.

    - 취소 사유에 TransactionConflict가 하나라도 있으면 50·100·200ms 백오프로 최대 3회 재시도하고,
      모두 실패하면 503 TRY_AGAIN.
    - 그 밖의 실패 사유가 모두 ConditionalCheckFailed면 재시도 없이 ConditionFailed.
      (사유 목록의 "None"은 실패하지 않은 항목이다.)
    - 그 외 오류는 그대로 올린다(핸들러가 500으로 처리).
    """
    client = client or table().meta.client
    for attempt in range(len(BACKOFF_SECONDS) + 1):
        try:
            client.transact_write_items(TransactItems=items)
            return
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "TransactionCanceledException":
                raise
            codes = _cancellation_codes(e)
            if "TransactionConflict" in codes:
                if attempt < len(BACKOFF_SECONDS):
                    sleep(BACKOFF_SECONDS[attempt])
                    continue
                raise ApiError(TRY_AGAIN) from None
            failed = [c for c in codes if c != "None"]
            if failed and all(c == "ConditionalCheckFailed" for c in failed):
                raise ConditionFailed(codes) from None
            raise


def transact_get_with_retry(
    keys: list[dict[str, str]],
    *,
    client: Any = None,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> list[dict[str, Any] | None]:
    """TransactGetItems로 여러 항목을 한 시점의 스냅샷으로 읽는다(BE-Q46 권장안). 순서대로 항목 또는 None.

    - 취소 사유가 TransactionConflict와 "None"(실패하지 않은 항목)만이고 TransactionConflict가 하나 이상일 때만
      재시도한다. 최초 1회 + 재시도 최대 3회. i번째 재시도 전 대기는 cap = BACKOFF_SECONDS[i]에 대해
      cap/2 + rand()*cap/2 (equal jitter, 누적 175–350ms, 임시 기본값). 모두 충돌이면 503 TRY_AGAIN.
    - 다른 사유가 섞이거나 다른 사유만 있는 취소, TransactionCanceledException 외 예외는 재시도 없이 그대로 올린다
      (api_handler가 500, BE-Q23). GetItem으로 폴백하지 않는다.
    - 로그에는 취소 사유 코드 목록만 남긴다(키·사용자 ID·본문 없음).
    """
    client = client or table().meta.client
    name = table().name
    request = [{"Get": {"TableName": name, "Key": k}} for k in keys]
    for attempt in range(len(BACKOFF_SECONDS) + 1):
        try:
            resp = client.transact_get_items(TransactItems=request)
            return [r.get("Item") for r in resp.get("Responses", [])]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "TransactionCanceledException":
                raise
            codes = _cancellation_codes(e)
            failed = [c for c in codes if c != "None"]
            if failed and all(c == "TransactionConflict" for c in failed):
                if attempt < len(BACKOFF_SECONDS):
                    _log.info("transact_get_conflict attempt=%d", attempt + 1)
                    cap = BACKOFF_SECONDS[attempt]
                    sleep(cap / 2 + rand() * cap / 2)
                    continue
                _log.warning("transact_get_try_again")
                raise ApiError(TRY_AGAIN) from None
            _log.warning("transact_get_canceled reasons=%s", ",".join(codes))
            raise
    raise ApiError(TRY_AGAIN)  # 도달하지 않는다
