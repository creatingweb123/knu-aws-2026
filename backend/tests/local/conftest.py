"""docker compose 로컬 환경 대상 테스트 공통 (실행: `pytest -m local`).

환경이 떠 있지 않으면 모든 테스트를 건너뛴다. 결과는 T 시나리오 합격 근거가 아니다(BE-Q15).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import pytest

API = os.environ.get("LOCAL_API_URL", "http://localhost:3000").rstrip("/")
AWS = os.environ.get("LOCAL_AWS_URL", "http://localhost:4566").rstrip("/")
POOL_ID = os.environ.get("LOCAL_USER_POOL_ID", "ap-northeast-2_haruLocal")
CLIENT_ID = os.environ.get("LOCAL_USER_POOL_CLIENT_ID", "haruLocalWebClient")
SEED_EMAIL = os.environ.get("SEED_JIYEON_EMAIL", "jiyeon@example.com")
SEED_NICKNAME = os.environ.get("SEED_JIYEON_NICKNAME", "지연")
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "LocalOnly-Passw0rd!")


def call(method: str, path: str, *, token: str | None = None, body: Any = None, headers: dict[str, str] | None = None):
    """(status, headers, json 또는 None)."""
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw, status, hdrs = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw, status, hdrs = e.read(), e.code, dict(e.headers)
    return status, hdrs, (json.loads(raw) if raw else None)


def boto(service: str):
    import boto3

    return boto3.client(
        service, endpoint_url=AWS, region_name="ap-northeast-2", aws_access_key_id="test", aws_secret_access_key="test"
    )


def dev_token(user_id: str, nickname: str | None = None) -> str:
    status, _, body = call("POST", "/dev/token", body={"userId": user_id, "nickname": nickname})
    assert status == 200, body
    return body["idToken"]


@pytest.fixture(scope="session", autouse=True)
def require_local_env():
    try:
        urllib.request.urlopen(API + "/me", timeout=3)
    except urllib.error.HTTPError:
        return  # 401이면 어댑터가 떠 있다
    except Exception:  # noqa: BLE001
        pytest.skip(f"로컬 환경이 떠 있지 않다({API}). backend/에서 docker compose up -d --build")
