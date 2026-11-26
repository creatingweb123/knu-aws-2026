"""리소스 ID 생성기."""

from __future__ import annotations

import re

from ulid import ULID

PLAN_PREFIX = "pln_"
CLAIM_PREFIX = "clm_"
SESSION_PREFIX = "ais_"
_SESSION_RX = re.compile(r"^ais_[0-9A-HJKMNP-TV-Z]{26}$")  # Crockford base32 ULID


def new_plan_id() -> str:
    """planId = "pln_" + ULID (§2.5)."""
    return PLAN_PREFIX + str(ULID())


def new_claim_id() -> str:
    """claimId = "clm_" + ULID (BE-Q36, planId와 같은 패턴)."""
    return CLAIM_PREFIX + str(ULID())


def new_session_id() -> str:
    """sessionId = "ais_" + ULID (docs/03 §3.2 예시)."""
    return SESSION_PREFIX + str(ULID())


def is_session_id(value: object) -> bool:
    """형식이 틀린 ID는 DB를 읽지 않고 없는 세션과 같게 다룬다(BE-Q77)."""
    return isinstance(value, str) and bool(_SESSION_RX.match(value))
