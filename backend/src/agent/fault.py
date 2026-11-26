"""dev 전용 장애 주입 `ai-slow` (T21, design §18.3, BE-Q107·BE-Q108).

세 겹 차단의 런타임 부분: FAULT_INJECT=ai-slow이고 FAULT_INJECT_ALLOWED=true이며, 함수 이름이 haru-dev-로 시작하거나
(함수 이름 없이) STAGE=local일 때만 켠다. 켜지면 예약 뒤 호출 직전에 9초를 기다린다. 이 대기도 호출 deadline 안이라 취소된다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

AI_SLOW = "ai-slow"
SLOW_S = 9.0  # 임시(BE-Q108)


def slow_delay_s(env: Mapping[str, str] | None = None) -> float:
    env = os.environ if env is None else env
    if env.get("FAULT_INJECT") != AI_SLOW or env.get("FAULT_INJECT_ALLOWED") != "true":
        return 0.0
    fn = env.get("AWS_LAMBDA_FUNCTION_NAME")
    if fn is not None:
        return SLOW_S if fn.startswith("haru-dev-") else 0.0
    return SLOW_S if env.get("STAGE") == "local" else 0.0
