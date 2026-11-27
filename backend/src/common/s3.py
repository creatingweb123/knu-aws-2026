"""사진 버킷 키 규칙과 presigned URL (5단계, docs/02 §2.7, spec backend-stage5-photo-pipeline).

- 원본: photos/original/{claimId}/{uuid}.{jpg|png}  — 실행자가 presigned PUT으로만 쓴다.
- 처리본: photos/processed/{claimId}/{attemptUuid}.jpg — 처리 Lambda가 처리 시도마다 새 키로 쓴다(BE-Q57).

presign은 네트워크를 쓰지 않는 로컬 계산이다. 로컬에서는 브라우저가 닿는 PUBLIC_S3_ENDPOINT(http://localhost:4566)와
경로 방식 주소로 서명한다(host도 서명에 들어간다). AWS에서는 PUBLIC_S3_ENDPOINT가 빈 값이라 기본 엔드포인트를 쓴다.
URL·서명은 로그에 남기지 않는다(BE-NFR-03).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import boto3
from botocore.config import Config

from common.responses import iso_utc, utc_now

ORIGINAL_PREFIX = "photos/original/"
PROCESSED_PREFIX = "photos/processed/"
EXT = {"image/jpeg": "jpg", "image/png": "png"}
PUT_EXPIRES_S = 600   # docs/03 §3.4 "presigned PUT URL 유효 10분"
GET_EXPIRES_S = 900   # docs/03 §3.5 "presigned GET (15분)"
_ORIGINAL_RE = re.compile(r"^photos/original/(clm_[0-9A-Z]{26})/([0-9a-f]{32})\.(jpg|png)$")

_presign_client: Any = None


def photo_bucket() -> str:
    return os.environ["PHOTO_BUCKET"]


def upload_if_none_match() -> bool:
    """BE-Q65 스위치. 프론트 승인 전에는 꺼 둔다(템플릿 UploadIfNoneMatch 기본 false)."""
    return os.environ.get("PHOTO_UPLOAD_IF_NONE_MATCH", "false").lower() == "true"


def new_original_key(claim_id: str, content_type: str) -> str:
    return f"{ORIGINAL_PREFIX}{claim_id}/{uuid.uuid4().hex}.{EXT[content_type]}"


def parse_original_key(key: str) -> tuple[str, str] | None:
    """(claimId, uuid). 원본 키 형식이 아니면 None(BE-Q54)."""
    m = _ORIGINAL_RE.match(key)
    return (m.group(1), m.group(2)) if m else None


def new_processed_key(claim_id: str) -> str:
    """처리 시도마다 새 attemptUuid(BE-Q57). 같은 원본이라도 시도가 다르면 키가 다르다."""
    return f"{PROCESSED_PREFIX}{claim_id}/{uuid.uuid4().hex}.jpg"


def quote_etag(etag: str) -> str:
    """S3 이벤트의 eTag는 따옴표가 없다. IfMatch에는 따옴표 붙은 값을 넘긴다."""
    return etag if etag.startswith('"') else f'"{etag}"'


def _client() -> Any:
    global _presign_client
    if _presign_client is None:
        endpoint = os.environ.get("PUBLIC_S3_ENDPOINT") or None
        _presign_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path" if endpoint else "virtual"}),
        )
    return _presign_client


def presign_put(key: str, content_type: str, size: int, now: datetime | None = None) -> dict[str, Any]:
    """Upload_Descriptor {url, method, headers, expiresAt}. ContentType·ContentLength를 서명한다(docs/03 §3.4).

    Content-Length는 서명되지만 headers에 넣지 않는다. 브라우저가 본문 길이로 자동으로 보내고 스크립트가 정할 수 없다.
    스위치가 켜지면 If-None-Match: *를 서명하고 headers에도 넣는다(같은 URL로 다시 올리면 412).
    """
    params: dict[str, Any] = {"Bucket": photo_bucket(), "Key": key, "ContentType": content_type, "ContentLength": size}
    headers = {"Content-Type": content_type}
    if upload_if_none_match():
        params["IfNoneMatch"] = "*"
        headers["If-None-Match"] = "*"
    url = _client().generate_presigned_url("put_object", Params=params, ExpiresIn=PUT_EXPIRES_S)
    expires = (now or utc_now()) + timedelta(seconds=PUT_EXPIRES_S)
    return {"url": url, "method": "PUT", "headers": headers, "expiresAt": iso_utc(expires)}


def presign_get(key: str, expires: int = GET_EXPIRES_S) -> str:
    return _client().generate_presigned_url("get_object", Params={"Bucket": photo_bucket(), "Key": key}, ExpiresIn=expires)
