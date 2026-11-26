"""장애 주입 지점 (테스트·로컬 전용, design §7.2, tasks 10.8·16.2).

- 단위 테스트는 HOOK에 함수를 넣어 지점마다 예외를 던진다(강제 종료 흉내).
- 로컬 통합은 STAGE=local, AGENT_TEST_HOOKS=true이고 Lambda가 아닐 때만 AGENT_CRASH_AT=<지점>:<n>으로
  n번째 지점에서 프로세스를 끝낸다(os._exit). AWS에서는 켜지지 않는다.
지점: lock_after, reserve, model_response, ckpt_put, ckpt_writes, before_commit, after_commit, before_delete.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable

HOOK: Callable[[str], None] | None = None
_counts: Counter[str] = Counter()


def local_crash_enabled() -> bool:
    return (os.environ.get("STAGE") == "local" and os.environ.get("AGENT_TEST_HOOKS") == "true"
            and "AWS_LAMBDA_FUNCTION_NAME" not in os.environ)


def fire(point: str) -> None:
    if HOOK is not None:
        HOOK(point)
    if local_crash_enabled():
        spec = os.environ.get("AGENT_CRASH_AT", "")
        if ":" in spec:
            name, n = spec.split(":", 1)
            if name == point:
                _counts[point] += 1
                if _counts[point] == int(n):
                    os._exit(9)
