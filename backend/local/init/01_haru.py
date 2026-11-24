#!/usr/bin/env python3
"""로컬 에뮬레이터(Floci) 초기화 (BE-INFRA-08, 요구사항 13.2, 13.3).

Floci compat 이미지의 ready 단계에서 실행된다(/etc/floci/init/ready.d). boto3는 이미지에서
http://localhost:4566 으로 미리 설정되어 있다. FLOCI_STORAGE_MODE=hybrid라 재시작해도 데이터가 남으므로,
모든 단계는 이미 있으면 건너뛴다. 한 단계라도 실패하면 단계 이름을 출력하고 종료 코드 1로 끝난다
(Floci는 ready 훅이 실패하면 종료한다).

시드 사용자 값은 로컬 전용 예시 값이며 실제 계정 정보가 아니다(BE-Q28). .env.example과 같은 기본값을 쓴다.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

TABLE_NAME = os.environ.get("TABLE_NAME", "HaruTable")
CHECKPOINT_TABLE = os.environ.get("CHECKPOINT_TABLE", "HaruAgentCheckpoints")
POOL_NAME = "haru-local"
# Floci 전용 태그로 ID를 고정해 .env 값을 매번 바꾸지 않게 한다(앱 코드·SAM 템플릿에는 쓰지 않는다).
POOL_ID = os.environ.get("LOCAL_USER_POOL_ID", "ap-northeast-2_haruLocal")
CLIENT_NAME = os.environ.get("LOCAL_USER_POOL_CLIENT_ID", "haruLocalWebClient")
# 토큰 iss는 FLOCI_BASE_URL(브라우저 기준 주소) + 풀 ID, JWKS는 컨테이너 사이 주소로 받는다.
PUBLIC_BASE = os.environ.get("FLOCI_BASE_URL", "http://localhost:4566").rstrip("/")
INTERNAL_BASE = os.environ.get("LOCAL_INTERNAL_BASE_URL", "http://aws:4566").rstrip("/")
DONE_MARKER = Path(os.environ.get("HARU_INIT_DONE_MARKER", "/tmp/haru-init-done"))

SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "LocalOnly-Passw0rd!")
SEED_USERS = [
    (os.environ.get("SEED_JIYEON_EMAIL", "jiyeon@example.com"), os.environ.get("SEED_JIYEON_NICKNAME", "지연")),
    (os.environ.get("SEED_SUHYUN_EMAIL", "suhyun@example.com"), os.environ.get("SEED_SUHYUN_NICKNAME", "수현")),
    (os.environ.get("SEED_MINJUN_EMAIL", "minjun@example.com"), os.environ.get("SEED_MINJUN_NICKNAME", "민준")),
]


def log(msg: str) -> None:
    print(f"[haru-init] {msg}", flush=True)


def _code(e: Exception) -> str:
    return getattr(e, "response", {}).get("Error", {}).get("Code", "")


def _key(name: str, kind: str) -> dict[str, str]:
    return {"AttributeName": name, "KeyType": kind}


def _attr(name: str) -> dict[str, str]:
    return {"AttributeName": name, "AttributeType": "S"}


def _wait_active(ddb: Any, name: str, timeout: float = 30.0, sleep: Callable[[float], None] = time.sleep) -> None:
    deadline = time.monotonic() + timeout
    while ddb.describe_table(TableName=name)["Table"].get("TableStatus") != "ACTIVE":
        if time.monotonic() > deadline:
            raise TimeoutError(f"{name} not ACTIVE")
        sleep(0.5)


def _table_exists(ddb: Any, name: str) -> bool:
    try:
        ddb.describe_table(TableName=name)
        return True
    except Exception as e:  # noqa: BLE001
        if _code(e) == "ResourceNotFoundException":
            return False
        raise


def _ensure_ttl(ddb: Any, name: str) -> None:
    status = ddb.describe_time_to_live(TableName=name).get("TimeToLiveDescription", {}).get("TimeToLiveStatus")
    if status in ("ENABLED", "ENABLING"):
        return
    ddb.update_time_to_live(TableName=name, TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"})


def create_haru_table(ddb: Any) -> str:
    """HaruTable: PK/SK, GSI1, GSI2, TTL ttl. 인덱스 이름은 template.yaml과 같다."""
    if _table_exists(ddb, TABLE_NAME):
        _ensure_ttl(ddb, TABLE_NAME)
        return "exists"
    ddb.create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[_attr(a) for a in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")],
        KeySchema=[_key("PK", "HASH"), _key("SK", "RANGE")],
        GlobalSecondaryIndexes=[
            {"IndexName": "GSI1", "KeySchema": [_key("GSI1PK", "HASH"), _key("GSI1SK", "RANGE")], "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "GSI2", "KeySchema": [_key("GSI2PK", "HASH"), _key("GSI2SK", "RANGE")], "Projection": {"ProjectionType": "ALL"}},
        ],
    )
    _wait_active(ddb, TABLE_NAME)
    _ensure_ttl(ddb, TABLE_NAME)
    return "created"


def create_checkpoint_table(ddb: Any) -> str:
    """HaruAgentCheckpoints: PK/SK, TTL ttl. 1단계는 테이블만 만든다(DynamoDBSaver 연결 확인은 6a, BE-Q21)."""
    if _table_exists(ddb, CHECKPOINT_TABLE):
        _ensure_ttl(ddb, CHECKPOINT_TABLE)
        return "exists"
    ddb.create_table(
        TableName=CHECKPOINT_TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[_attr("PK"), _attr("SK")],
        KeySchema=[_key("PK", "HASH"), _key("SK", "RANGE")],
    )
    _wait_active(ddb, CHECKPOINT_TABLE)
    _ensure_ttl(ddb, CHECKPOINT_TABLE)
    return "created"


def ensure_user_pool(idp: Any) -> str:
    """유저 풀(이메일 사용자 이름, nickname 필수). 생성된 풀 ID를 돌려준다."""
    try:
        idp.describe_user_pool(UserPoolId=POOL_ID)
        return POOL_ID
    except Exception as e:  # noqa: BLE001
        if _code(e) != "ResourceNotFoundException":
            raise
    for pool in idp.list_user_pools(MaxResults=60).get("UserPools", []):
        if pool.get("Name") == POOL_NAME:  # 고정 ID가 적용되지 않은 이전 실행에서 만든 풀
            return pool["Id"]
    resp = idp.create_user_pool(
        PoolName=POOL_NAME,
        UsernameAttributes=["email"],
        Schema=[{"Name": "nickname", "AttributeDataType": "String", "Mutable": True, "Required": True}],
        UserPoolTags={"floci:override-id": POOL_ID, "floci:override-cognito-client-id": "use-name"},
    )
    return resp["UserPool"]["Id"]


def ensure_client(idp: Any, pool_id: str) -> str:
    """앱 클라이언트(시크릿 없음). 클라이언트 ID를 돌려준다."""
    for c in idp.list_user_pool_clients(UserPoolId=pool_id, MaxResults=60).get("UserPoolClients", []):
        if c.get("ClientName") == CLIENT_NAME:
            return c["ClientId"]
    resp = idp.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=CLIENT_NAME,
        GenerateSecret=False,
        ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
    )
    return resp["UserPoolClient"]["ClientId"]


def ensure_seed_users(idp: Any, pool_id: str) -> int:
    """시드 사용자 3명(지연, 수현, 민준). 비밀번호는 매번 영구 비밀번호로 다시 설정한다."""
    created = 0
    for email, nickname in SEED_USERS:
        try:
            idp.admin_get_user(UserPoolId=pool_id, Username=email)
        except Exception as e:  # noqa: BLE001
            if _code(e) != "UserNotFoundException":
                raise
            idp.admin_create_user(
                UserPoolId=pool_id,
                Username=email,
                MessageAction="SUPPRESS",
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "nickname", "Value": nickname},
                ],
            )
            created += 1
        idp.admin_set_user_password(UserPoolId=pool_id, Username=email, Password=SEED_PASSWORD, Permanent=True)
    return created


def run_step(name: str, fn: Callable[[], Any]) -> Any:
    try:
        result = fn()
    except Exception as e:  # noqa: BLE001
        log(f"FAILED step={name} error={type(e).__name__}: {e}")
        sys.exit(1)
    log(f"ok step={name} result={result}")
    return result


def main(ddb: Any = None, idp: Any = None) -> dict[str, str]:
    if ddb is None or idp is None:
        import boto3

        ddb = ddb or boto3.client("dynamodb")
        idp = idp or boto3.client("cognito-idp")
    DONE_MARKER.unlink(missing_ok=True)
    run_step("create_haru_table", lambda: create_haru_table(ddb))
    run_step("create_checkpoint_table", lambda: create_checkpoint_table(ddb))
    pool_id = run_step("ensure_user_pool", lambda: ensure_user_pool(idp))
    client_id = run_step("ensure_user_pool_client", lambda: ensure_client(idp, pool_id))
    run_step("ensure_seed_users", lambda: ensure_seed_users(idp, pool_id))

    values = {
        "LOCAL_USER_POOL_ID": pool_id,
        "LOCAL_USER_POOL_CLIENT_ID": client_id,
        "LOCAL_JWT_ISSUER": f"{PUBLIC_BASE}/{pool_id}",
        "LOCAL_JWKS_URL": f"{INTERNAL_BASE}/{pool_id}/.well-known/jwks.json",
    }
    for k, v in values.items():
        print(f"{k}={v}", flush=True)
    if pool_id != POOL_ID or client_id != CLIENT_NAME:
        log("WARNING 고정 ID가 적용되지 않았다. 위 값을 backend/.env에 넣어야 한다.")
    DONE_MARKER.write_text("ok", encoding="utf-8")
    return values


if __name__ == "__main__":
    main()
