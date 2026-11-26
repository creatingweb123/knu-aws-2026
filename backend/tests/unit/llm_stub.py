"""OpenAI 호환 /v1/chat/completions 로컬 스텁 (design §11.5, Requirement 8.4).

테스트 프로세스 안 127.0.0.1에서만 듣는다(외부 네트워크 없음). 실제 ChatOpenAI의 요청 직렬화·응답 파싱·예외 변환·
취소를 확인하는 데 쓴다. 키는 앞부분 일치만 비교하고 원문을 저장하지 않는다.

모드: ok, no_usage, fenced, prose, status:<code>, drip(바이트를 drip_interval마다 하나), hang(헤더 뒤 멈춤), close(응답 없이 끊기)
"""

from __future__ import annotations

import json
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_CARD = {
    "title": "이사 전, 마지막 동네 산책", "summary": "출근길 빵집에 들르고 싶었어요.", "reason": "이삿짐 정리가 길어졌어요.",
    "estimatedMinutes": 45, "places": [{"name": "출근길 빵집", "activity": "들러서 빵 사기", "whyChosen": "출근길에 지나치던 곳이에요."}],
    "question": "빵집에서 무엇을 샀나요?",
}


class LlmStub:
    def __init__(self) -> None:
        self.mode = "ok"
        self.content: str | list[str] = json.dumps(DEFAULT_CARD, ensure_ascii=False)
        # 6b: 응답 메시지를 직접 정한다(도구 호출). 원소는 assistant message dict(content·tool_calls). 지정하면 content보다 우선
        self.messages: list[dict[str, Any]] | None = None
        self.drip_interval = 0.2
        self.requests: list[dict[str, Any]] = []
        self.closed_early = 0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                auth = self.headers.get("Authorization", "")
                stub.requests.append({"path": self.path, "body": body, "auth_prefix": auth[:10]})
                stub._respond(self, len(stub.requests) - 1)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self.url = f"http://127.0.0.1:{self._server.server_port}/v1"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> LlmStub:
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _content_for(self, n: int) -> str:
        if isinstance(self.content, list):
            return self.content[min(n, len(self.content) - 1)]
        return self.content

    def _respond(self, h: BaseHTTPRequestHandler, n: int) -> None:
        mode = self.mode
        if mode.startswith("status:"):
            code = int(mode.split(":")[1])
            data = json.dumps({"error": {"message": "stub error with echo of request", "type": "stub"}}).encode()
            return self._send(h, code, data)
        if mode == "close":
            h.connection.shutdown(socket.SHUT_RDWR)
            self.closed_early += 1
            return None
        text = self._content_for(n)
        if mode == "fenced":
            text = "```json\n" + text + "\n```"
        elif mode == "prose":
            text = "카드를 정리했어요.\n" + text + "\n확인해 주세요."
        message: dict[str, Any] = {"role": "assistant", "content": text}
        finish = "stop"
        if self.messages:
            message = {"role": "assistant", **self.messages[min(n, len(self.messages) - 1)]}
            if message.get("tool_calls"):
                finish = "tool_calls"
        msg: dict[str, Any] = {
            "id": "stub-1", "object": "chat.completion", "created": 1, "model": "stub-model",
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
        }
        if mode not in ("no_usage",):
            msg["usage"] = {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180}
        data = json.dumps(msg, ensure_ascii=False).encode()
        if mode == "hang":
            h.send_response(200)
            h.send_header("Content-Type", "application/json")
            h.send_header("Content-Length", str(len(data)))
            h.end_headers()
            h.wfile.flush()
            # 클라이언트가 연결을 닫을 때까지(최대 60초) 기다린다. 닫히면 바로 끝나 서버 쪽 소켓을 놓는다.
            conn = h.connection
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                ready, _, _ = select.select([conn], [], [], 0.05)
                if ready:
                    try:
                        if not conn.recv(1, socket.MSG_PEEK):
                            self.closed_early += 1
                            break
                    except OSError:
                        self.closed_early += 1
                        break
            return None
        if mode == "drip":
            h.send_response(200)
            h.send_header("Content-Type", "application/json")
            h.send_header("Content-Length", str(len(data)))
            h.end_headers()
            try:
                for b in data:
                    h.wfile.write(bytes([b]))
                    h.wfile.flush()
                    time.sleep(self.drip_interval)
            except OSError:
                self.closed_early += 1
            return None
        return self._send(h, 200, data)

    @staticmethod
    def _send(h: BaseHTTPRequestHandler, code: int, data: bytes) -> None:
        h.send_response(code)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)


def tool_message(*calls: tuple[str, Any], content: str | None = None) -> dict[str, Any]:
    """OpenAI 형식 tool_calls. 인자가 str이면 원문 그대로(잘못된 JSON 시험용), dict면 JSON 문자열."""
    return {"content": content, "tool_calls": [
        {"id": f"call_{i}", "type": "function",
         "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)}}
        for i, (name, args) in enumerate(calls)]}
