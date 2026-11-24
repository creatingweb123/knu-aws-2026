"""리소스 ID 생성기."""

from __future__ import annotations

from ulid import ULID

PLAN_PREFIX = "pln_"
CLAIM_PREFIX = "clm_"


def new_plan_id() -> str:
    """planId = "pln_" + ULID (§2.5)."""
    return PLAN_PREFIX + str(ULID())


def new_claim_id() -> str:
    """claimId = "clm_" + ULID (BE-Q36, planId와 같은 패턴)."""
    return CLAIM_PREFIX + str(ULID())
