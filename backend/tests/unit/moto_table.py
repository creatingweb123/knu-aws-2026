"""moto(인프로세스 DynamoDB 흉내) 테스트 공통: HaruTable 생성과 환경 변수."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import boto3

from common import ddb


def create_haru_table(client) -> None:
    def key(n, t):
        return {"AttributeName": n, "KeyType": t}

    client.create_table(
        TableName="HaruTable",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")],
        KeySchema=[key("PK", "HASH"), key("SK", "RANGE")],
        GlobalSecondaryIndexes=[
            {"IndexName": "GSI1", "KeySchema": [key("GSI1PK", "HASH"), key("GSI1SK", "RANGE")], "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "GSI2", "KeySchema": [key("GSI2PK", "HASH"), key("GSI2SK", "RANGE")], "Projection": {"ProjectionType": "ALL"}},
        ],
    )


def set_env(monkeypatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("TABLE_NAME", "HaruTable")
    monkeypatch.setenv("CLAIM_DURATION_DAYS", "3")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)


_cached_table = None


def _shared_table():
    """boto3 리소스를 테스트 사이에 재사용한다.

    클라이언트 생성이 이 개발 PC에서 회당 수 초 걸려 테스트마다 만들면 전체가 수십 분이 된다.
    moto는 요청을 보낼 때 가로채므로, 먼저 만든 리소스도 새 mock_aws 안에서는 새(빈) 백엔드로 간다.
    """
    global _cached_table
    if _cached_table is None:
        _cached_table = boto3.resource(
            "dynamodb", region_name="ap-northeast-2", aws_access_key_id="test", aws_secret_access_key="test"
        ).Table("HaruTable")
    return _cached_table


@contextlib.contextmanager
def haru_table() -> Iterator:
    """mock_aws 안에서 새 HaruTable을 만들고 common.ddb가 그 테이블을 쓰게 한다."""
    from moto import mock_aws

    with mock_aws():
        t = _shared_table()
        create_haru_table(t.meta.client)
        ddb._table = t
        try:
            yield t
        finally:
            ddb._table = None
