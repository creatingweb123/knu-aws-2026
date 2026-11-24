"""리소스 ID 생성기."""

from __future__ import annotations

from ulid import ULID

PLAN_PREFIX = "pln_"


def new_plan_id() -> str:
    """planId = "pln_" + ULID (§2.5)."""
    return PLAN_PREFIX + str(ULID())
