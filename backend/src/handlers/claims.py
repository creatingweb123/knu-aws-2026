"""POST /claims/{claimId}/abandon, PUT /claims/{claimId}/record, POST /claims/{claimId}/record/photo,
POST /claims/{claimId}/complete.

BE-CLAIM-06, BE-REC-01–04·06–10 (3·5단계). `GET /claims/{claimId}/record`는 4단계 묶음 B(BE-Q46)에 있다.
"""

from __future__ import annotations

from typing import Any

from common.auth import get_user
from common.responses import api_handler, ok, serialize_claim, serialize_record
from common.validation import CompleteIn, PhotoRequest, RecordPut
from domain import claim_service
from handlers._http import dispatch, json_body, path_param


def _abandon(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    claim = claim_service.abandon(path_param(event, "claimId"), user)
    return ok(200, {"claim": serialize_claim(claim)})


def _put_record(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    claim_id = path_param(event, "claimId")
    data = RecordPut.model_validate(json_body(event))  # photo도 검증한다(BE-Q34 해소)
    if data.photo is None:
        return ok(200, {"record": serialize_record(claim_service.put_record(claim_id, user, data.letter)), "upload": None})
    record, upload = claim_service.put_record_with_photo(claim_id, user, data.letter, data.photo)
    return ok(200, {"record": serialize_record(record), "upload": upload})


def _replace_photo(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    claim_id = path_param(event, "claimId")
    data = PhotoRequest.model_validate(json_body(event))
    return ok(200, {"upload": claim_service.replace_photo(claim_id, user, data)})  # BE-Q51 권장안 {upload}


def _complete(event: dict[str, Any]) -> dict[str, Any]:
    user = get_user(event)
    claim_id = path_param(event, "claimId")
    data = CompleteIn.model_validate(json_body(event))
    result = claim_service.complete_by_user(claim_id, user, data.mode)
    return ok(200, {"claim": serialize_claim(result["claim"]), "delivered": True, "hasPhoto": result["hasPhoto"]})


ROUTES = {
    "POST /claims/{claimId}/abandon": _abandon,
    "PUT /claims/{claimId}/record": _put_record,
    "POST /claims/{claimId}/record/photo": _replace_photo,
    "POST /claims/{claimId}/complete": _complete,
}


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return dispatch(ROUTES, event)
