"""체크포인트 저장소, 울타리, 계보 선택, 재개 입력 분류 (design §6, §6.7, BE-Q19·94·95·103·104·105·119·125·126).

- 공유 DynamoDBSaver를 콜드 스타트 때 한 번 만들고(체크포인트 전용 SDK 설정: connect 1초·read 1초·시도 1회),
  실행마다 얕게 복사해 울타리·TTL·크기 측정 같은 실행별 상태를 둔다(BE-Q119: 라이브러리 내부 속성 repo·storage·ttl_seconds).
- 비동기 메서드를 이벤트 루프에서 동기 메서드로 바로 실행한다. 라이브러리 기본(스레드 실행기)은 취소·동결 뒤에도
  스레드가 남아 다음 호출에서 늦게 쓸 수 있다. durability="sync"라 쓰기를 어차피 기다리므로 지연 차이는 없다(V13).
- 울타리는 쓰기의 **시작**만 막는다. 이미 보낸 쓰기가 잠금 만료 뒤에 반영되는 것은 막지 못한다(§6.7).
  정합성은 select_tip의 계보·표지 검사가 지킨다.
- 로그에는 사유 코드와 개수만 남긴다. 체크포인트 내용(사연·대화)은 남기지 않는다.
"""

from __future__ import annotations

import copy
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from botocore.config import Config
from langgraph_checkpoint_aws import DynamoDBSaver

_log = logging.getLogger("haru.ai")

FENCE_MS = 24_000            # BE-Q125: 잠금 성공 뒤 이 시간이 지나면 새 쓰기를 시작하지 않는다
COMMIT_RESERVE_MS = 2_500    # 이보다 적게 남으면 쓰기를 시작하지 않는다(커밋 시간)
MIN_TTL_S = 60
TTL_MARGIN_S = 60
MAX_CHAIN = 64
LARGE_BYTES = 200_000


class CheckpointFenceError(Exception):
    """울타리가 닫혀 체크포인트 쓰기를 시작하지 않았다(체크포인트는 마지막 성공 지점 그대로)."""


def checkpoint_sdk_config() -> Config:
    return Config(connect_timeout=1, read_timeout=1, retries={"mode": "standard", "total_max_attempts": 1})


class FencedSaver(DynamoDBSaver):
    """실행별 상태를 갖는 DynamoDBSaver. 비동기 메서드는 동기 메서드를 직접 부른다."""

    fence_deadline: float | None = None
    remaining_ms: Callable[[], float] | None = None
    hook: Callable[[str], None] | None = None
    max_payload: int = 0
    last_config: dict[str, Any] | None = None
    writes: int = 0

    def _guard(self, kind: str) -> None:
        if self.fence_deadline is not None and time.monotonic() >= self.fence_deadline:
            raise CheckpointFenceError("FENCE_TIME")
        if self.remaining_ms is not None and self.remaining_ms() < COMMIT_RESERVE_MS:
            raise CheckpointFenceError("FENCE_RESERVE")
        if self.hook:
            self.hook(f"ckpt_{kind}")
        self.writes += 1

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        self._guard("put")
        try:
            _, data, _ = self.serializer.serialize({"checkpoint": checkpoint, "metadata": metadata})
            self.max_payload = max(self.max_payload, len(data))
        except Exception:  # noqa: BLE001 - 크기 측정 실패는 쓰기를 막지 않는다
            pass
        result = self.put(config, checkpoint, metadata, new_versions)
        self.last_config = result
        return result

    async def aput_writes(self, config: Any, writes: Any, task_id: str, task_path: str = "") -> None:
        self._guard("writes")
        self.put_writes(config, writes, task_id, task_path)

    async def aget_tuple(self, config: Any) -> Any:
        return self.get_tuple(config)

    async def alist(self, config: Any, *, filter: Any = None, before: Any = None, limit: Any = None) -> AsyncIterator[Any]:  # noqa: A002
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)


class CheckpointStore:
    def __init__(self, table_name: str, *, region_name: str | None = None, endpoint_url: str | None = None,
                 boto_config: Config | None = None, saver: FencedSaver | None = None) -> None:
        self.shared = saver or FencedSaver(table_name=table_name, region_name=region_name, endpoint_url=endpoint_url or None,
                                           boto_config=boto_config or checkpoint_sdk_config(), ttl_seconds=30 * 86400,
                                           consistent_read=True)

    def for_run(self, *, session_ttl: int, now_epoch: float | None = None, fence_deadline: float | None = None,
                remaining_ms: Callable[[], float] | None = None, hook: Callable[[str], None] | None = None) -> FencedSaver:
        """실행 전용 saver. ttl_seconds = 세션 ttl − now − 60초(최소 60초)라 체크포인트가 세션보다 늦게 만료되지 않는다(BE-Q104)."""
        now_epoch = time.time() if now_epoch is None else now_epoch
        ttl_s = max(MIN_TTL_S, int(session_ttl - now_epoch - TTL_MARGIN_S))
        run = copy.copy(self.shared)
        run.storage = copy.copy(self.shared.storage)
        run.storage.ttl_seconds = ttl_s
        run.repo = copy.copy(self.shared.repo)
        run.repo.storage = run.storage
        run.repo.ttl_seconds = ttl_s
        run.fence_deadline = fence_deadline
        run.remaining_ms = remaining_ms
        run.hook = hook
        run.max_payload = 0
        run.last_config = None
        run.writes = 0
        return run


def checkpoint_id_of(config: Any) -> str | None:
    return ((config or {}).get("configurable") or {}).get("checkpoint_id")


# ---------------------------------------------------------------------------
# 계보 선택 (design §6.2)
# ---------------------------------------------------------------------------


@dataclass
class TipChoice:
    kind: str                       # NEW(처음 실행) | TIP | MISSING(기준 없음)
    checkpoint_id: str | None = None
    rejected: int = 0
    candidates: list[str] = field(default_factory=list)


def _parent(t: Any) -> str | None:
    return checkpoint_id_of(t.parent_config)


def select_tip(hist: list[Any], *, base: str | None, run_turn: int, turn_runs: list[str], my_run_id: str,
               known_resume_ids: set[str]) -> TipChoice:
    """커밋된 기준(base)의 자손 중 표지가 맞는 가지에서 이어 갈 지점을 고른다.

    통과 조건: 기준까지의 사슬 전체가 이번 턴(runTurn), turnRuns에 있는 실행(runId·runAttempt 일치)이고,
    소비한 resumeId가 모두 알려진 것. 더 큰 시도 번호의 가지가 우선, 같은 시도 안에서는 가장 최근(uuid6).
    base=None(생성 턴 재시도)이면 사슬이 뿌리(부모 없음)에 닿아야 한다.
    """
    by_id = {checkpoint_id_of(t.config): t for t in hist}
    legit = {rid: i + 1 for i, rid in enumerate(turn_runs) if rid != my_run_id}
    if base is not None and base not in by_id:
        return TipChoice("MISSING")
    ok: dict[str, bool] = {}

    def node_ok(t: Any) -> bool:
        md = t.metadata or {}
        if md.get("runTurn") != run_turn:
            return False
        rid = md.get("runId")
        if rid not in legit or md.get("runAttempt") != legit[rid]:
            return False
        consumed = set(((t.checkpoint or {}).get("channel_values") or {}).get("consumed_resume_ids") or [])
        return consumed <= known_resume_ids

    def chain_ok(cid: str) -> bool:
        path = []
        cur = cid
        for _ in range(MAX_CHAIN):
            if cur == base:
                break
            if cur is None:
                if base is None:
                    break
                return False
            if cur in ok:
                if not ok[cur]:
                    return False
                break
            t = by_id.get(cur)
            if t is None or not node_ok(t):
                for p in path + [cur]:
                    ok[p] = False
                return False
            path.append(cur)
            cur = _parent(t)
        else:
            return False
        for p in path:
            ok[p] = True
        return True

    passed, rejected = [], 0
    for cid, t in by_id.items():
        if cid == base:
            continue
        if chain_ok(cid):
            passed.append(t)
        else:
            rejected += 1
    if not passed:
        if base is None:
            return TipChoice("NEW", None, rejected)
        return TipChoice("TIP", base, rejected)
    best = max(passed, key=lambda t: ((t.metadata or {}).get("runAttempt", 0), checkpoint_id_of(t.config)))
    if rejected:
        _log.info("ai_ckpt reason=CHECKPOINT_BRANCH_REJECTED count=%d", rejected)
    return TipChoice("TIP", checkpoint_id_of(best.config), rejected, [checkpoint_id_of(t.config) for t in passed])


# ---------------------------------------------------------------------------
# 재개 입력 분류 (design §6.3)
# ---------------------------------------------------------------------------

RESUME_ANSWER, RESUME_CONTINUE, CONTINUE_NONE, COMMIT_AS_IS, ANOMALY = (
    "RESUME_ANSWER", "RESUME_CONTINUE", "CONTINUE_NONE", "COMMIT_AS_IS", "ANOMALY")
TERMINAL_OUTCOMES = ("READY", "FAILED")


@dataclass
class ResumeDecision:
    kind: str
    interrupt_id: str | None = None
    value: Any = None
    resume_id: str | None = None
    reason: str | None = None


def pending_interrupts(snapshot: Any) -> list[tuple[str, Any]]:
    return [(i.id, i.value) for t in (snapshot.tasks or ()) for i in (t.interrupts or ())]


def classify_resume(snapshot: Any, *, pending_resume: dict[str, Any] | None, run_turn: int) -> ResumeDecision:
    values = snapshot.values or {}
    consumed = set(values.get("consumed_resume_ids") or [])
    done_this_turn = values.get("outcome_turn") == run_turn
    pr = pending_resume if isinstance(pending_resume, dict) else None
    pr_open = bool(pr) and pr.get("resumeId") not in consumed
    ints = pending_interrupts(snapshot)
    if ints:
        iid, payload = ints[0]
        kind = (payload or {}).get("kind") if isinstance(payload, dict) else None
        if kind == "question":
            if pr_open and pr.get("questionId") == payload.get("questionId"):
                return ResumeDecision(RESUME_ANSWER, iid, resume_value(pr), pr.get("resumeId"))
            if done_this_turn:
                return ResumeDecision(COMMIT_AS_IS)
            return ResumeDecision(ANOMALY, reason="RESUME_STATE_MISMATCH")
        if kind == "continue":
            if done_this_turn:
                return ResumeDecision(COMMIT_AS_IS)
            return ResumeDecision(RESUME_CONTINUE, iid, "continue")
        return ResumeDecision(ANOMALY, reason="UNKNOWN_INTERRUPT")
    if done_this_turn and values.get("outcome") in TERMINAL_OUTCOMES:
        return ResumeDecision(COMMIT_AS_IS)
    if values.get("outcome") in TERMINAL_OUTCOMES and not done_this_turn:
        return ResumeDecision(ANOMALY, reason="TERMINAL_CHECKPOINT")
    if pr_open and "ask" not in (snapshot.next or ()):
        return ResumeDecision(ANOMALY, reason="RESUME_STATE_MISMATCH")
    return ResumeDecision(CONTINUE_NONE)


def resume_value(pr: dict[str, Any]) -> dict[str, Any]:
    out = {"questionId": pr.get("questionId"), "resumeId": pr.get("resumeId")}
    for k in ("choice", "text", "skipped"):
        if pr.get(k) is not None:
            out[k] = pr[k]
    if pr.get("viaFinish"):
        out["viaFinish"] = True
    return out
