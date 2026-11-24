"""POST /claims/{claimId}/abandon, PUT /claims/{claimId}/record, POST /claims/{claimId}/complete.

BE-CLAIM-06, BE-REC-01·03·06–10 (3단계). `GET /claims/{claimId}/record`와 사진은 4·5단계다.
"""

from __future__ import annotations

from typing import Any

from common.auth import get_user
from common.errors import VALIDATION_ERROR, ApiError
from common.responses import api_handler, ok, serialize_claim, serialize_record
from common.validation import CompleteIn, RecordPut
from domain import claim_service
from handlers._http import dispatch, json_body, path_param


def _abandon(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    claim = claim_service.abandon(path_param(event, "claimId"), user)
    return ok(200, {"claim": serialize_claim(claim)})


def _put_record(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    claim_id = path_param(event, "claimId")
    body = json_body(event)
    if isinstance(body, dict) and body.get("photo") is not None:
        # BE-Q34: 사진은 5단계에서 계약대로(업로드 URL 발급) 구현한다.
        raise ApiError(VALIDATION_ERROR, details={"photo": "사진은 아직 보낼 수 없어요. 글만 저장해 주세요."})
    data = RecordPut.model_validate({k: v for k, v in (body or {}).items() if k != "photo"} if isinstance(body, dict) else body)
    record = claim_service.put_record(claim_id, user, data.letter)
    return ok(200, {"record": serialize_record(record), "upload": None})


def _complete(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    claim_id = path_param(event, "claimId")
    data = CompleteIn.model_validate(json_body(event))
    result = claim_service.complete_by_user(claim_id, user, data.mode)
    return ok(200, {"claim": serialize_claim(result["claim"]), "delivered": True, "hasPhoto": result["hasPhoto"]})


ROUTES = {
    "POST /claims/{claimId}/abandon": _abandon,
    "PUT /claims/{claimId}/record": _put_record,
    "POST /claims/{claimId}/complete": _complete,
}


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return dispatch(ROUTES, event)
