"""이어받기·포기·기록(글)·완료 트랜잭션 (G1–G4, docs/02 §2.6, spec backend-stage3-claim).

정합성 로직은 이 파일에만 둔다(docs/07 §7.1 원칙 2). API 완료와 5단계 사진 처리 Lambda는 같은
complete_claim()을 쓴다. 트랜잭션 실패는 docs/02 §2.6 공통 규칙을 따른다:
- TransactionConflict는 transact_with_retry가 50·100·200ms로 재시도한다.
- 조건 실패(ConditionFailed)나 재시도 소진(503 TRY_AGAIN)이면 ConsistentRead로 다시 읽어 판정한다.
- 다시 읽어도 판정할 수 없으면(최대 MAX_ATTEMPTS번) 503 TRY_AGAIN.

반환값은 저장 항목(dict)이며, 응답 직렬화는 핸들러가 한다. list_my_claims만 직렬화까지 한다.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from boto3.dynamodb.conditions import Key

from common import ddb, metrics
from common.auth import User
from common.errors import (
    ALREADY_CLAIMED,
    CANNOT_CLAIM_OWN_PLAN,
    CLAIM_NOT_ACTIVE,
    FORBIDDEN,
    NOT_FOUND,
    RECORD_REQUIRED,
    TRY_AGAIN,
    VALIDATION_ERROR,
    ApiError,
)
from common.ids import new_claim_id
from common.responses import iso_utc, serialize_claim, serialize_plan, serialize_record, utc_now
from domain.plan_service import CLAIMED, COMPLETED, OPEN, _get, plan_update, shown_status

ACTIVE, ABANDONED, EXPIRED = "ACTIVE", "ABANDONED", "EXPIRED"
TEXT_ONLY, WITH_PHOTO = "TEXT_ONLY", "WITH_PHOTO"
PHOTO_NONE, PHOTO_PROCESSING, PHOTO_READY, PHOTO_DISCARDED = "NONE", "PROCESSING", "READY", "DISCARDED"
MAX_ATTEMPTS = 3
GSI2 = "GSI2"


def claim_days() -> int:
    return int(os.environ.get("CLAIM_DURATION_DAYS", "3"))


def _table_name() -> str:
    return ddb.table().name


def _claim_key(plan_id: str, claim_id: str) -> dict[str, str]:
    return {"PK": f"PLAN#{plan_id}", "SK": f"CLAIM#{claim_id}"}


def _record_key(plan_id: str, claim_id: str) -> dict[str, str]:
    return {"PK": f"PLAN#{plan_id}", "SK": f"RECORD#{claim_id}"}


def _lookup(claim_id: str, user: User) -> dict[str, Any]:
    """ClaimLookup으로 planId를 찾고 요청자가 실행자인지 확인한다. 없으면 404, 남이면 403."""
    item = _get(f"CLAIM#{claim_id}")
    if item is None:
        raise ApiError(NOT_FOUND)
    if item.get("claimerId") != user.id:
        raise ApiError(FORBIDDEN)
    return item


def _stale() -> ApiError:
    metrics.emit(metrics.STALE_REQUEST_REJECTED)
    return ApiError(CLAIM_NOT_ACTIVE)


def _is_try_again(e: ApiError) -> bool:
    return e.code == TRY_AGAIN


# ---------------------------------------------------------------------------
# 이어받기 (G1)
# ---------------------------------------------------------------------------


def _decide_claim(plan: dict[str, Any], user: User, now_iso: str) -> dict[str, Any] | None:
    """다시 읽은 Plan으로 판정한다. 본인의 ACTIVE Claim이면 그 Claim, 이어받을 수 있으면 None, 아니면 예외."""
    if plan.get("ownerId") == user.id:
        raise ApiError(CANNOT_CLAIM_OWN_PLAN)
    status = plan.get("status")
    if status == CLAIMED and plan.get("claimerId") == user.id and plan.get("currentClaimId"):
        mine = _get(f"PLAN#{plan['planId']}", f"CLAIM#{plan['currentClaimId']}")
        if mine is not None and mine.get("status") == ACTIVE:
            return mine  # 기한이 지났어도 본인이면 그대로 돌려준다(늦은 완료 허용, §2.5)
    if status == OPEN:
        return None
    if status == CLAIMED and plan.get("dueAt", "") < now_iso:
        return None
    metrics.emit(metrics.CLAIM_CONFLICT)
    raise ApiError(ALREADY_CLAIMED)


def claim_plan(plan_id: str, user: User, now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    """(Claim 항목, 새로 만들었는지). 새로 만들면 201, 본인의 기존 Claim이면 200."""
    now = now or utc_now()
    now_iso = iso_utc(now)
    for attempt in range(MAX_ATTEMPTS + 1):
        plan = _get(f"PLAN#{plan_id}")
        if plan is None:
            raise ApiError(NOT_FOUND)
        existing = _decide_claim(plan, user, now_iso)
        if existing is not None:
            return existing, False
        if attempt == MAX_ATTEMPTS:
            break
        claim_id = new_claim_id()
        due_iso = iso_utc(now + timedelta(days=claim_days()))
        claim_item: dict[str, Any] = {
            **_claim_key(plan_id, claim_id),
            "claimId": claim_id,
            "planId": plan_id,
            "claimerId": user.id,
            "status": ACTIVE,
            "claimedAt": now_iso,
            "dueAt": due_iso,
            "GSI2PK": f"USER#{user.id}",
            "GSI2SK": f"CLAIM#{now_iso}",
        }
        if user.nickname is not None:
            claim_item["claimerNickname"] = user.nickname
        lookup = {"PK": f"CLAIM#{claim_id}", "SK": "META", "claimId": claim_id, "planId": plan_id, "claimerId": user.id}
        table = _table_name()
        items: list[dict[str, Any]] = [
            plan_update(
                plan_id,
                new_status=CLAIMED,
                set_values={"currentClaimId": claim_id, "claimerId": user.id, "dueAt": due_iso},
                condition="#owner <> :me AND (#st = :open OR (#st = :claimed AND #due < :now))",
                condition_names={"#owner": "ownerId", "#st": "status", "#due": "dueAt"},
                condition_values={":me": user.id, ":open": OPEN, ":claimed": CLAIMED, ":now": now_iso},
            ),
            {"Put": {"TableName": table, "Item": claim_item, "ConditionExpression": "attribute_not_exists(PK)"}},
            {"Put": {"TableName": table, "Item": lookup, "ConditionExpression": "attribute_not_exists(PK)"}},
        ]
        if plan.get("status") == CLAIMED and plan.get("currentClaimId"):
            # 기한 지난 대체(T14): 이전 Claim을 같은 트랜잭션에서 EXPIRED로 바꾼다.
            items.append(
                {
                    "Update": {
                        "TableName": table,
                        "Key": _claim_key(plan_id, plan["currentClaimId"]),
                        "UpdateExpression": "SET #st = :expired",
                        "ConditionExpression": "#st = :active",
                        "ExpressionAttributeNames": {"#st": "status"},
                        "ExpressionAttributeValues": {":expired": EXPIRED, ":active": ACTIVE},
                    }
                }
            )
        try:
            ddb.transact_with_retry(items)
            return claim_item, True
        except ddb.ConditionFailed:
            continue  # 다시 읽어 판정한다(§2.6 공통 3번)
        except ApiError as e:
            if not _is_try_again(e):
                raise
            continue  # 재시도 소진도 다시 읽어 판정한다(§2.6 공통 4번)
    raise ApiError(TRY_AGAIN)


# ---------------------------------------------------------------------------
# 포기 (G3)
# ---------------------------------------------------------------------------


def abandon(claim_id: str, user: User, now: datetime | None = None) -> dict[str, Any]:
    lookup = _lookup(claim_id, user)
    plan_id = lookup["planId"]
    claim = _get(f"PLAN#{plan_id}", f"CLAIM#{claim_id}")
    if claim is None or claim.get("status") != ACTIVE:
        raise _stale()
    record = _get(f"PLAN#{plan_id}", f"RECORD#{claim_id}")
    table = _table_name()
    items: list[dict[str, Any]] = [
        plan_update(
            plan_id,
            new_status=OPEN,
            remove=["currentClaimId", "claimerId", "dueAt"],
            condition="#cur = :cid AND #st = :claimed AND #claimer = :me",
            condition_names={"#cur": "currentClaimId", "#st": "status", "#claimer": "claimerId"},
            condition_values={":cid": claim_id, ":claimed": CLAIMED, ":me": user.id},
        ),
        {
            "Update": {
                "TableName": table,
                "Key": _claim_key(plan_id, claim_id),
                "UpdateExpression": "SET #st = :abandoned",
                "ConditionExpression": "#st = :active",
                "ExpressionAttributeNames": {"#st": "status"},
                "ExpressionAttributeValues": {":abandoned": ABANDONED, ":active": ACTIVE},
            }
        },
    ]
    if record is not None:
        items.append(
            {
                "Update": {
                    "TableName": table,
                    "Key": _record_key(plan_id, claim_id),
                    "UpdateExpression": "SET #ps = :discarded",
                    "ConditionExpression": "attribute_exists(PK)",
                    "ExpressionAttributeNames": {"#ps": "photoStatus"},
                    "ExpressionAttributeValues": {":discarded": PHOTO_DISCARDED},
                }
            }
        )
    try:
        ddb.transact_with_retry(items)
    except ddb.ConditionFailed:
        raise _stale() from None
    return {**claim, "status": ABANDONED}


# ---------------------------------------------------------------------------
# 방문 기록 저장 (글만, 3단계 최소 구현)
# ---------------------------------------------------------------------------


def put_record(claim_id: str, user: User, letter: str, now: datetime | None = None) -> dict[str, Any]:
    """Current_Claim이고 ACTIVE일 때만 글을 쓴다. 완료 전까지 덮어쓸 수 있다."""
    now_iso = iso_utc(now or utc_now())
    lookup = _lookup(claim_id, user)
    plan_id = lookup["planId"]
    table = _table_name()
    items = [
        {
            "ConditionCheck": {
                "TableName": table,
                "Key": {"PK": f"PLAN#{plan_id}", "SK": "META"},
                "ConditionExpression": "#cur = :cid AND #st = :claimed",
                "ExpressionAttributeNames": {"#cur": "currentClaimId", "#st": "status"},
                "ExpressionAttributeValues": {":cid": claim_id, ":claimed": CLAIMED},
            }
        },
        {
            "ConditionCheck": {
                "TableName": table,
                "Key": _claim_key(plan_id, claim_id),
                "ConditionExpression": "#st = :active",
                "ExpressionAttributeNames": {"#st": "status"},
                "ExpressionAttributeValues": {":active": ACTIVE},
            }
        },
        {
            "Update": {
                "TableName": table,
                "Key": _record_key(plan_id, claim_id),
                "UpdateExpression": (
                    "SET #letter = :letter, #upd = :now, #cid = :cid, #pid = :pid, #author = :me,"
                    " #ps = if_not_exists(#ps, :none)"
                ),
                "ConditionExpression": "attribute_not_exists(#delivered)",
                "ExpressionAttributeNames": {
                    "#letter": "letter",
                    "#upd": "updatedAt",
                    "#cid": "claimId",
                    "#pid": "planId",
                    "#author": "authorId",
                    "#ps": "photoStatus",
                    "#delivered": "deliveredAt",
                },
                "ExpressionAttributeValues": {
                    ":letter": letter,
                    ":now": now_iso,
                    ":cid": claim_id,
                    ":pid": plan_id,
                    ":me": user.id,
                    ":none": PHOTO_NONE,
                },
            }
        },
    ]
    try:
        ddb.transact_with_retry(items)
    except ddb.ConditionFailed:
        raise _stale() from None
    record = _get(f"PLAN#{plan_id}", f"RECORD#{claim_id}")
    if record is None:  # 방금 썼으므로 생기지 않아야 한다
        raise ApiError(TRY_AGAIN)
    return record


# ---------------------------------------------------------------------------
# 완료 (G2, G3, G4)
# ---------------------------------------------------------------------------


def _completed_result(claim: dict[str, Any], plan_id: str, claim_id: str) -> dict[str, Any]:
    record = _get(f"PLAN#{plan_id}", f"RECORD#{claim_id}") or {}
    return {"claim": claim, "delivered": True, "hasPhoto": record.get("photoStatus") == PHOTO_READY}


def complete_claim(
    claim_id: str,
    mode: str,
    key: str | None = None,
    processed_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """{claim, delivered: True, hasPhoto}. 같은 Claim에 몇 번을 불러도 InboxItem은 1건이다.

    실행자 확인은 하지 않는다(API는 complete_by_user, 사진 처리 Lambda는 이 함수를 직접 부른다).
    WITH_PHOTO에서 사진 키가 다르거나 PROCESSING이 아니면 CLAIM_NOT_ACTIVE로 거부한다(5단계 호출자가 무시 처리).
    """
    if mode not in (TEXT_ONLY, WITH_PHOTO):
        raise ApiError(VALIDATION_ERROR, details={"mode": "TEXT_ONLY여야 해요."})
    now_iso = iso_utc(now or utc_now())
    for attempt in range(MAX_ATTEMPTS + 1):
        lookup = _get(f"CLAIM#{claim_id}")
        if lookup is None:
            raise ApiError(NOT_FOUND)
        plan_id = lookup["planId"]
        claim = _get(f"PLAN#{plan_id}", f"CLAIM#{claim_id}")
        if claim is None:
            raise ApiError(NOT_FOUND)
        if claim.get("status") == COMPLETED:
            metrics.emit(metrics.COMPLETE_DUPLICATE)
            return _completed_result(claim, plan_id, claim_id)
        if claim.get("status") != ACTIVE:
            raise _stale()
        plan = _get(f"PLAN#{plan_id}")
        if plan is None or plan.get("status") != CLAIMED or plan.get("currentClaimId") != claim_id:
            raise _stale()
        record = _get(f"PLAN#{plan_id}", f"RECORD#{claim_id}")
        if record is None or not record.get("letter"):
            raise ApiError(RECORD_REQUIRED)
        prev = record.get("photoStatus")
        if mode == WITH_PHOTO and (record.get("photoKey") != key or prev != PHOTO_PROCESSING):
            raise ApiError(CLAIM_NOT_ACTIVE)
        if attempt == MAX_ATTEMPTS:
            break

        has_photo = mode == WITH_PHOTO
        new_photo = PHOTO_READY if has_photo else (PHOTO_NONE if prev in (None, PHOTO_NONE) else PHOTO_DISCARDED)
        rec_names = {"#letter": "letter", "#delivered": "deliveredAt", "#ps": "photoStatus"}
        rec_values: dict[str, Any] = {":now": now_iso, ":newps": new_photo}
        rec_cond = "attribute_exists(#letter) AND attribute_not_exists(#delivered)"  # 뒤 조건은 방어(BE-Q40)
        if prev is None:
            rec_cond += " AND attribute_not_exists(#ps)"
        else:
            rec_cond += " AND #ps = :prev"
            rec_values[":prev"] = prev
        rec_set = "SET #delivered = :now, #ps = :newps"
        if has_photo:
            rec_cond += " AND #pkey = :key"
            rec_names["#pkey"] = "photoKey"
            rec_values[":key"] = key
            rec_set += ", #proc = :processed"
            rec_names["#proc"] = "processedKey"
            rec_values[":processed"] = processed_key
        late = now_iso > claim.get("dueAt", now_iso)
        inbox: dict[str, Any] = {
            "PK": f"USER#{plan['ownerId']}",
            "SK": f"INBOX#{claim_id}",
            "ownerId": plan["ownerId"],
            "itemId": claim_id,
            "planId": plan_id,
            "planTitle": plan.get("title"),
            "hasPhoto": has_photo,
            "read": False,
            "createdAt": now_iso,
            # reply는 쓰지 않는다(§2.5: NULL로 쓰면 attribute_not_exists(reply)가 항상 거짓)
        }
        if claim.get("claimerNickname") is not None:
            inbox["claimerNickname"] = claim["claimerNickname"]
        table = _table_name()
        items = [
            plan_update(
                plan_id,
                new_status=COMPLETED,
                set_values={"completedAt": now_iso},
                condition="#cur = :cid AND #st = :claimed",
                condition_names={"#cur": "currentClaimId", "#st": "status"},
                condition_values={":cid": claim_id, ":claimed": CLAIMED},
            ),
            {
                "Update": {
                    "TableName": table,
                    "Key": _claim_key(plan_id, claim_id),
                    "UpdateExpression": "SET #st = :completed, #comp = :now, #late = :late",
                    "ConditionExpression": "#st = :active",
                    "ExpressionAttributeNames": {"#st": "status", "#comp": "completedAt", "#late": "late"},
                    "ExpressionAttributeValues": {":completed": COMPLETED, ":now": now_iso, ":late": late, ":active": ACTIVE},
                }
            },
            {
                "Update": {
                    "TableName": table,
                    "Key": _record_key(plan_id, claim_id),
                    "UpdateExpression": rec_set,
                    "ConditionExpression": rec_cond,
                    "ExpressionAttributeNames": rec_names,
                    "ExpressionAttributeValues": rec_values,
                }
            },
            {"Put": {"TableName": table, "Item": inbox, "ConditionExpression": "attribute_not_exists(PK)"}},
        ]
        try:
            ddb.transact_with_retry(items)
        except ddb.ConditionFailed:
            continue  # 다시 읽어 판정한다(COMPLETED면 멱등 200)
        except ApiError as e:
            if not _is_try_again(e):
                raise
            continue
        done = {**claim, "status": COMPLETED, "completedAt": now_iso, "late": late}
        return {"claim": done, "delivered": True, "hasPhoto": has_photo}
    raise ApiError(TRY_AGAIN)


def complete_by_user(claim_id: str, user: User, mode: str, now: datetime | None = None) -> dict[str, Any]:
    """POST /claims/{claimId}/complete: 트랜잭션 전에 실행자인지 확인한다(아니면 403)."""
    _lookup(claim_id, user)
    return complete_claim(claim_id, mode, now=now)


# ---------------------------------------------------------------------------
# 내 이어받기 목록
# ---------------------------------------------------------------------------


def list_my_claims(user: User, status: str | None, now: datetime | None = None) -> list[dict[str, Any]]:
    """[{claim, plan, record|null}] (직렬화 완료). claimedAt 최신순."""
    if status not in (ACTIVE, COMPLETED):
        raise ApiError(VALIDATION_ERROR, details={"status": "ACTIVE 또는 COMPLETED여야 해요."})  # BE-Q35
    now = now or utc_now()
    claims: list[dict[str, Any]] = []
    start: dict[str, Any] | None = None
    while True:
        args: dict[str, Any] = {
            "IndexName": GSI2,
            "KeyConditionExpression": Key("GSI2PK").eq(f"USER#{user.id}") & Key("GSI2SK").begins_with("CLAIM#"),
            "ScanIndexForward": False,
        }
        if start:
            args["ExclusiveStartKey"] = start
        resp = ddb.table().query(**args)
        claims += [c for c in resp.get("Items", []) if c.get("status") == status]
        start = resp.get("LastEvaluatedKey")
        if not start:
            break
    out = []
    for c in claims:
        plan = _get(f"PLAN#{c['planId']}")
        if plan is None:
            continue
        record = _get(f"PLAN#{c['planId']}", f"RECORD#{c['claimId']}")
        out.append(
            {
                "claim": serialize_claim(c),
                "plan": serialize_plan(plan, is_owner=plan.get("ownerId") == user.id, status_override=shown_status(plan, user.id, now)),
                "record": serialize_record(record),
            }
        )
    return out
