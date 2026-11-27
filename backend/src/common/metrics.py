"""운영 지표를 CloudWatch EMF(Embedded Metric Format) 한 줄로 남긴다 (BE-OBS-01, BE-Q37).

Lambda에서는 표준 출력의 EMF 줄을 CloudWatch Logs가 지표로 추출한다. 로컬에서는 같은 줄이 stdout에 남는다.
그래서 AWS_EMF_ENVIRONMENT 값과 무관하게 형식이 같고 외부 라이브러리를 쓰지 않는다.
네임스페이스 Haru, 차원 없음, 단위 기본 Count(시간 지표 AiLatencyMs·PhotoProcessingMs만 Milliseconds, BE-Q37). 사용자 ID·본문·토큰은 담지 않는다(BE-NFR-03).
"""

from __future__ import annotations

import json
import sys
import time

NAMESPACE = "Haru"
CLAIM_CONFLICT = "ClaimConflict"
COMPLETE_DUPLICATE = "CompleteDuplicate"
STALE_REQUEST_REJECTED = "StaleRequestRejected"
# 6a(AI 레벨 0). 분류 코드는 로그 필드로만 남기고 차원으로 쓰지 않는다(Requirement 18.3).
AI_LATENCY_MS = "AiLatencyMs"
AI_FAILURE = "AiFailure"
AI_INVALID_OUTPUT = "AiInvalidOutput"
# 5단계(사진)
PHOTO_PROCESSING_MS = "PhotoProcessingMs"  # unit="Milliseconds"
PHOTO_FAILED = "PhotoFailed"


def emf_line(name: str, value: int | float = 1, timestamp_ms: int | None = None, unit: str = "Count") -> str:
    doc = {
        "_aws": {
            "Timestamp": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
            "CloudWatchMetrics": [{"Namespace": NAMESPACE, "Dimensions": [[]], "Metrics": [{"Name": name, "Unit": unit}]}],
        },
        name: value,
    }
    return json.dumps(doc, separators=(",", ":"))


def emit(name: str, value: int | float = 1, unit: str = "Count") -> None:
    sys.stdout.write(emf_line(name, value, unit=unit) + "\n")
    sys.stdout.flush()
