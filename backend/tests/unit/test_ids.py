"""ID 생성기 (sessionId 형식, BE-Q77)."""

import pytest

from common.ids import is_session_id, new_claim_id, new_plan_id, new_session_id


def test_new_session_id_format():
    sid = new_session_id()
    assert sid.startswith("ais_") and len(sid) == 30 and is_session_id(sid)
    assert new_session_id() != sid


@pytest.mark.parametrize(
    "value",
    ["", "ais_", "ais_123", "pln_01JDZ0000000000000000000000", new_plan_id(), new_claim_id(), "AIS_01JDZ00000000000000000000",
     "ais_" + "0" * 25 + "I", "ais_" + "0" * 25, "ais_" + "0" * 27, None, 123, "ais_" + "0" * 22 + "abcd"],
)
def test_is_session_id_rejects(value):
    assert is_session_id(value) is False
