"""프론트 모형 (작업 10.9, docs/03 §3.2 규칙, BE-Q121). 테스트 전용.

docs/03 규칙만 따른다.
- `WORKING`이면 `answer` 없이 같은 `turn`으로 이어서 보낸다. 연속 2회 `WORKING`이면 `finish: true`, 그 뒤로는 계속 `finish: true`.
  같은 `turn`의 `WORKING`(BE-Q121, 울타리·중단 해제)도 같은 규칙이다.
- `ASKING`이면 답한다(자동 답 규칙: 첫 선택지, 선택지가 없으면 건너뛰기).
- 409 `AI_SESSION_BUSY` → 2초 기다린 뒤 `GET`으로 다시 맞춘다. 409 `AI_SESSION_CLOSED` → `GET` 후 그 상태를 보여 준다.
- 503 `AI_UNAVAILABLE`·502 `AI_INVALID_OUTPUT`·429 `AI_QUOTA_EXCEEDED`·404 `NOT_FOUND` → 사연을 유지한 채 직접 작성(종료).
- 코드 없는 500(Lambda 강제 종료 등)은 docs/03에 규칙이 없다. 모형은 사용자의 새로고침으로 보고 `GET`으로 다시 맞춘 뒤
  같은 규칙으로 이어 간다(`refresh_limit`번까지). 넘으면 오류로 끝난다.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

TERMINAL = ("READY", "FAILED")
DIRECT_WRITE_CODES = ("AI_UNAVAILABLE", "AI_INVALID_OUTPUT", "AI_QUOTA_EXCEEDED", "NOT_FOUND")

Response = tuple[int, Any]  # (statusCode, body dict)


def auto_answer(question: dict[str, Any]) -> dict[str, Any]:
    if question.get("options"):
        return {"questionId": question["questionId"], "choice": question["options"][0]}
    return {"questionId": question["questionId"], "skipped": True}


@dataclass
class SimResult:
    outcome: str  # READY | FAILED | DIRECT_WRITE | ERROR | LIMIT
    view: dict[str, Any] | None = None
    code: str | None = None
    requests: list[tuple[str, int, str | None]] = field(default_factory=list)  # (종류, HTTP, 상태 또는 오류 코드)
    turn_requests: Counter = field(default_factory=Counter)  # expectedTurn별 turns 요청 수
    sent: list[dict[str, Any]] = field(default_factory=list)  # 보낸 turns 본문
    waits_s: float = 0.0

    @property
    def request_count(self) -> int:
        return len(self.requests)


class FrontendSim:
    def __init__(self, *, create: Callable[[str], Response], turns: Callable[[str, dict[str, Any]], Response],
                 get: Callable[[str], Response], sleep: Callable[[float], None] = lambda s: None,
                 answer: Callable[[dict[str, Any]], dict[str, Any]] = auto_answer, max_requests: int = 40, refresh_limit: int = 4) -> None:
        self._create, self._turns, self._get, self._sleep = create, turns, get, sleep
        self.answer, self.max_requests, self.refresh_limit = answer, max_requests, refresh_limit

    def run(self, story: str) -> SimResult:
        res = SimResult(outcome="ERROR")
        code, body = self._create(story)
        res.requests.append(("create", code, _label(code, body)))
        if code != 200:
            return self._error_end(res, code, body)
        view = body
        sid = view["sessionId"]
        working_in_row = 1 if view["status"] == "WORKING" else 0
        finish = False
        refreshes = 0
        while True:
            if view["status"] in TERMINAL:
                res.outcome, res.view = view["status"], view
                if view["status"] == "FAILED":
                    res.outcome = "DIRECT_WRITE"
                return res
            if res.request_count >= self.max_requests:
                res.outcome, res.view = "LIMIT", view
                return res
            req: dict[str, Any] = {"expectedTurn": view["turn"]}
            if view["status"] == "ASKING":
                req["answer"] = self.answer(view["question"])
            if finish or working_in_row >= 2:
                finish = True
                req["finish"] = True
            res.turn_requests[view["turn"]] += 1
            res.sent.append(req)
            code, body = self._turns(sid, req)
            res.requests.append(("turns", code, _label(code, body)))
            if code == 200:
                view = body
                working_in_row = working_in_row + 1 if view["status"] == "WORKING" else 0
                continue
            err = _code(body)
            if code == 409 and err == "AI_SESSION_BUSY":
                self._sleep(2.0)
                res.waits_s += 2.0
                view = self._resync(sid, res)
            elif code == 409 and err == "AI_SESSION_CLOSED":
                view = self._resync(sid, res)
            elif code >= 500 and err is None:
                refreshes += 1
                if refreshes > self.refresh_limit:
                    return self._error_end(res, code, body)
                view = self._resync(sid, res)
            else:
                return self._error_end(res, code, body)
            if view is None:
                return res

    def _resync(self, sid: str, res: SimResult) -> dict[str, Any] | None:
        code, body = self._get(sid)
        res.requests.append(("get", code, _label(code, body)))
        if code != 200:
            self._error_end(res, code, body)
            return None
        return body

    @staticmethod
    def _error_end(res: SimResult, code: int, body: Any) -> SimResult:
        err = _code(body)
        res.code = err
        res.outcome = "DIRECT_WRITE" if err in DIRECT_WRITE_CODES else "ERROR"
        return res


def _code(body: Any) -> str | None:
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body["error"].get("code")
    return None


def _label(code: int, body: Any) -> str | None:
    if code == 200 and isinstance(body, dict):
        return body.get("status")
    return _code(body)


def handler_transport(create, turns, get, *, on_crash: Callable[[str | None], None] | None = None,
                      crash_types: tuple[type[BaseException], ...] = ()) -> dict[str, Callable[..., Response]]:
    """tests/unit 핸들러 함수(create·turns·get, Lambda 응답 dict)를 모형 전송으로 감싼다.
    crash_types 예외(강제 종료 흉내)는 코드 없는 500으로 바꾸고 on_crash(sessionId)를 부른다(잠금 만료 흉내)."""

    def wrap(fn, sid_of):
        def call(*a):
            try:
                r = fn(*a)
            except crash_types:
                if on_crash:
                    on_crash(sid_of(a))
                return 500, {"message": "Internal Server Error"}
            return r["statusCode"], json.loads(r["body"]) if r.get("body") else None
        return call

    return {"create": wrap(create, lambda a: None), "turns": wrap(turns, lambda a: a[0]), "get": wrap(get, lambda a: a[0])}
