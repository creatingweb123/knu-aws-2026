"""로컬 HTTP 어댑터 (BE-INFRA-08, 요구사항 13.4–13.8, docs/02 §2.4.1).

API Gateway HTTP API + JWT authorizer 대신 쓴다. 하는 일:
1. 요청을 payload 2.0 이벤트로 바꿔 Lambda와 같은 핸들러(src/handlers)를 호출한다. 경로 목록은 routes.py.
2. Authorization의 ID 토큰을 검증한다(서명, iss, aud = 클라이언트 ID, exp, token_use=id). 실패하면 핸들러를
   부르지 않고 계약 형식의 401 UNAUTHORIZED. 신뢰하는 키는 Floci User Pool JWKS와(STAGE=local일 때) dev JWT 공개키.
3. STAGE=local에서만 POST /dev/token {userId, nickname} → {idToken} (자동화 테스트·프론트 dev-jwt 모드용).
4. CORS: 허용 Origin(기본 http://localhost:5173)의 preflight OPTIONS는 인증 없이 204.

이 파일은 SAM 배포물에 들어가지 않는다(template.yaml CodeUri는 src/). 실제 API Gateway의 401 본문 형식은
여기와 다르다(§2.4.4 1항). 토큰·본문은 로그에 남기지 않는다.
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from common.errors import NOT_FOUND, UNAUTHORIZED, VALIDATION_ERROR, ApiError
from common.responses import error_body
from handlers.routes import ROUTES

log = logging.getLogger("haru.adapter")

DEV_KID = "haru-local-dev-jwt"
DEV_TOKEN_TTL_SECONDS = 3600
LAMBDA_TIMEOUT_MS = 27_000  # 남은 실행 시간 흉내(12초 규칙 확인용)
CORS_ALLOW_HEADERS = "Authorization,Content-Type,Idempotency-Key"
CORS_ALLOW_METHODS = "GET,POST,PUT,OPTIONS"


@dataclass
class Config:
    stage: str = "local"
    issuer: str = "http://localhost:4566/ap-northeast-2_haruLocal"
    jwks_url: str = "http://aws:4566/ap-northeast-2_haruLocal/.well-known/jwks.json"
    client_id: str = "haruLocalWebClient"
    cors_origin: str = "http://localhost:5173"
    port: int = 3000

    @classmethod
    def from_env(cls) -> Config:
        d = cls()
        return cls(
            stage=os.environ.get("STAGE", d.stage),
            issuer=os.environ.get("LOCAL_JWT_ISSUER", d.issuer),
            jwks_url=os.environ.get("LOCAL_JWKS_URL", d.jwks_url),
            client_id=os.environ.get("LOCAL_USER_POOL_CLIENT_ID", d.client_id),
            cors_origin=os.environ.get("CORS_ALLOWED_ORIGIN", d.cors_origin),
            port=int(os.environ.get("PORT", d.port)),
        )


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


class FakeContext:
    """Lambda context 중 핸들러가 쓰는 부분."""

    def __init__(self, remaining_ms: int = LAMBDA_TIMEOUT_MS) -> None:
        self._deadline = time.monotonic() + remaining_ms / 1000
        self.aws_request_id = str(uuid.uuid4())
        self.function_name = "local-adapter"

    def get_remaining_time_in_millis(self) -> int:
        return max(0, int((self._deadline - time.monotonic()) * 1000))


def _compile_routes(routes: dict[str, str]) -> list[tuple[str, re.Pattern[str], str, str]]:
    compiled = []
    for route_key, target in routes.items():
        method, path = route_key.split(" ", 1)
        pattern = "^" + re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", re.escape(path)) + "$"
        compiled.append((method, re.compile(pattern), route_key, target))
    return compiled


def _load_handler(target: str) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    module, func = target.rsplit(".", 1)
    return getattr(importlib.import_module(module), func)


def _claim_str(v: Any) -> str:
    """API Gateway JWT authorizer는 클레임 값을 문자열로 넘긴다(배열은 "[a b]")."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + " ".join(_claim_str(x) for x in v) + "]"
    return str(v)


def _json(status: int, body: dict[str, Any]) -> Response:
    return Response(status, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(body, ensure_ascii=False).encode("utf-8"))


def _error(code: str, details: dict[str, str] | None = None) -> Response:
    e = ApiError(code, details=details)
    return _json(e.status, error_body(e))


class Adapter:
    def __init__(
        self,
        config: Config,
        *,
        jwks_key_resolver: Callable[[str], Any] | None = None,
        routes: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.routes = _compile_routes(routes or ROUTES)
        self._dev_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._jwks_resolver = jwks_key_resolver or self._default_jwks_resolver()

    # ------------------------------------------------------------------ 토큰

    def _default_jwks_resolver(self) -> Callable[[str], Any]:
        client = jwt.PyJWKClient(self.config.jwks_url, cache_keys=True, lifespan=300)
        return lambda token: client.get_signing_key_from_jwt(token).key

    @property
    def dev_enabled(self) -> bool:
        return self.config.stage == "local"

    def issue_dev_token(self, user_id: str, nickname: str | None) -> str:
        now = int(time.time())
        claims = {
            "sub": user_id,
            "aud": self.config.client_id,
            "iss": self.config.issuer,
            "token_use": "id",
            "iat": now,
            "exp": now + DEV_TOKEN_TTL_SECONDS,
        }
        if nickname:
            claims["nickname"] = nickname
        return jwt.encode(claims, self._dev_key, algorithm="RS256", headers={"kid": DEV_KID})

    def verify(self, authorization: str | None) -> dict[str, str] | None:
        """검증에 성공하면 문자열 클레임, 실패하면 None."""
        if not authorization:
            return None
        token = authorization.strip()
        if token[:7].lower() == "bearer ":
            token = token[7:].strip()
        if not token:
            return None
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            if kid == DEV_KID:
                if not self.dev_enabled:
                    return None
                key = self._dev_key.public_key()
            else:
                key = self._jwks_resolver(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.config.client_id,
                issuer=self.config.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception as e:  # noqa: BLE001 - 어떤 검증 실패도 401
            log.info("auth_failed type=%s", type(e).__name__)
            return None
        if claims.get("token_use") != "id":
            log.info("auth_failed type=token_use")
            return None
        return {k: _claim_str(v) for k, v in claims.items()}

    # ----------------------------------------------------------------- 처리

    def _cors(self, headers: dict[str, str]) -> dict[str, str]:
        origin = headers.get("origin")
        if origin and origin == self.config.cors_origin:
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        return {}

    def _match(self, method: str, path: str) -> tuple[str, str, dict[str, str]] | None:
        for m, rx, route_key, target in self.routes:
            if m == method:
                found = rx.match(path)
                if found:
                    return route_key, target, found.groupdict()
        return None

    def build_event(
        self, method: str, raw_path: str, query: str, headers: dict[str, str], body: bytes, route_key: str, path_params: dict[str, str]
    ) -> dict[str, Any]:
        qs: dict[str, str] = {}
        for k, v in parse_qsl(query, keep_blank_values=True):
            qs[k] = f"{qs[k]},{v}" if k in qs else v  # API Gateway는 같은 키를 쉼표로 합친다
        try:
            text, is_b64 = body.decode("utf-8"), False
        except UnicodeDecodeError:
            text, is_b64 = base64.b64encode(body).decode("ascii"), True
        return {
            "version": "2.0",
            "routeKey": route_key,
            "rawPath": raw_path,
            "rawQueryString": query,
            "headers": headers,
            "queryStringParameters": qs or None,
            "pathParameters": path_params or None,
            "body": text if body else None,
            "isBase64Encoded": is_b64,
            "requestContext": {
                "routeKey": route_key,
                "stage": "$default",
                "requestId": str(uuid.uuid4()),
                "timeEpoch": int(time.time() * 1000),
                "http": {"method": method, "path": raw_path, "protocol": "HTTP/1.1", "sourceIp": "127.0.0.1", "userAgent": headers.get("user-agent", "")},
            },
        }

    def dispatch(self, method: str, url: str, headers: dict[str, str], body: bytes = b"") -> Response:
        headers = {k.lower(): v for k, v in headers.items()}
        parts = urlsplit(url)
        path, query = parts.path or "/", parts.query
        cors = self._cors(headers)

        if method == "OPTIONS":
            if not cors:
                return Response(403)
            return Response(
                204,
                {**cors, "Access-Control-Allow-Headers": CORS_ALLOW_HEADERS, "Access-Control-Allow-Methods": CORS_ALLOW_METHODS, "Access-Control-Max-Age": "600"},
            )

        if method == "POST" and path == "/dev/token" and self.dev_enabled:
            resp = self._dev_token(body)
        else:
            resp = self._route(method, path, query, headers, body)
        resp.headers.update(cors)
        return resp

    def _dev_token(self, body: bytes) -> Response:
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return _error(VALIDATION_ERROR, {"body": "JSON 형식이 아니에요."})
        user_id = data.get("userId") if isinstance(data, dict) else None
        nickname = data.get("nickname") if isinstance(data, dict) else None
        details = {}
        if not isinstance(user_id, str) or not user_id.strip():
            details["userId"] = "필수 항목이에요."
        if nickname is not None and not isinstance(nickname, str):
            details["nickname"] = "문자열이어야 해요."
        if details:
            return _error(VALIDATION_ERROR, details)
        return _json(200, {"idToken": self.issue_dev_token(user_id, nickname)})

    def _route(self, method: str, path: str, query: str, headers: dict[str, str], body: bytes) -> Response:
        matched = self._match(method, path)
        if matched is None:
            return _error(NOT_FOUND)
        route_key, target, path_params = matched
        claims = self.verify(headers.get("authorization"))
        if claims is None:
            return _error(UNAUTHORIZED)  # 핸들러를 호출하지 않는다
        event = self.build_event(method, path, query, headers, body, route_key, path_params)
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims, "scopes": None}}
        result = _load_handler(target)(event, FakeContext())
        out_headers = {str(k): str(v) for k, v in (result.get("headers") or {}).items()}
        raw = result.get("body")
        if raw is None:
            data = b""
        elif result.get("isBase64Encoded"):
            data = base64.b64decode(raw)
        else:
            data = str(raw).encode("utf-8")
        return Response(int(result.get("statusCode", 200)), out_headers, data)


def make_server(adapter: Adapter, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            hdrs: dict[str, str] = {}
            for k, v in self.headers.items():
                k = k.lower()
                hdrs[k] = f"{hdrs[k]},{v}" if k in hdrs else v
            try:
                resp = adapter.dispatch(self.command, self.path, hdrs, body)
            except Exception as e:  # noqa: BLE001
                log.error("adapter_error type=%s", type(e).__name__)
                resp = _error("INTERNAL_ERROR")
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp.body)))
            self.end_headers()
            if resp.body:
                self.wfile.write(resp.body)
            log.info("%s %s %s", self.command, urlsplit(self.path).path, resp.status)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _handle

        def log_message(self, format: str, *args: Any) -> None:  # 기본 접근 로그(쿼리 포함)는 끈다
            pass

    return ThreadingHTTPServer((host, adapter.config.port), Handler)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stdout)
    config = Config.from_env()
    server = make_server(Adapter(config))
    log.info("listening port=%s stage=%s dev_token=%s", config.port, config.stage, config.stage == "local")
    server.serve_forever()


if __name__ == "__main__":
    main()
