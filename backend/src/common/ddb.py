"""DynamoDB 접근과 트랜잭션 공통 실패 처리 (§2.6, BE-REC-10).

엔드포인트는 SDK 표준 변수 AWS_ENDPOINT_URL에 맡기고 앱 코드에서 다루지 않는다.
트랜잭션은 리소스 클라이언트(table().meta.client)로 보내므로 항목 값은 파이썬 기본 타입으로 쓴다.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import ClientError

from common.errors import TRY_AGAIN, ApiError

BACKOFF_SECONDS = (0.05, 0.1, 0.2)  # 최대 3회 재시도

_table: Any = None


def table() -> Any:
    """HaruTable 리소스. 같은 실행 환경에서 재사용한다."""
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


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
