"""계획 생성·목록·상세 (BE-PLAN-01–09, docs/03-api-contract.md §3.3).

반환값은 저장 항목(dict)이며, 응답 직렬화는 핸들러가 common.responses로 한다.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Any

from boto3.dynamodb.conditions import Attr, Key

from common import ddb
from common.auth import User
from common.errors import IDEMPOTENCY_CONFLICT, NOT_FOUND, TRY_AGAIN, VALIDATION_ERROR, ApiError
from common.ids import new_plan_id
from common.responses import iso_utc, parse_iso, serialize_claim, serialize_plan, serialize_plan_summary, utc_now
from common.validation import PlanCreate
from domain.fidelity import Target, find_not_in_source
from domain.privacy import scan_privacy

IDEMPOTENCY_TTL = timedelta(hours=24)
GSI1 = "GSI1"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50  # BE-Q3
OPEN, CLAIMED, COMPLETED = "OPEN", "CLAIMED", "COMPLETED"
ACTIVE = "ACTIVE"


def area_id() -> str:
    return os.environ.get("AREA_ID", "default")


def gsi1_pk(status: str) -> str:
    return f"AREA#{area_id()}#STATUS#{status}"


def body_hash(body: PlanCreate) -> str:
    """검증된 본문의 키 정렬·공백 없는 JSON의 SHA-256."""
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# POST /plans
# ---------------------------------------------------------------------------


def compute_metrics(body: PlanCreate) -> dict[str, Any]:
    """이번 범위의 네 지표만 계산한다(요구사항 5.1–5.4). AI 세션은 읽지 않는다."""
    targets: list[Target] = []
    for i, p in enumerate(body.places):
        targets += [Target(f"places[{i}].name", p.name), Target(f"places[{i}].activity", p.activity)]
    texts = {"title": body.title, "summary": body.summary, "reason": body.reason, "question": body.question}
    for i, p in enumerate(body.places):
        texts |= {f"places[{i}].name": p.name, f"places[{i}].activity": p.activity, f"places[{i}].whyChosen": p.whyChosen}
    return {
        "authoringMode": body.authoring.mode,
        "durationMs": body.authoring.durationMs,
        "addedNotInSource": len(find_not_in_source([body.authoring.story], targets)),
        "privacyInPublished": len(scan_privacy(texts)),
    }


def build_plan(user: User, body: PlanCreate, now: datetime) -> dict[str, Any]:
    plan_id = new_plan_id()
    created = iso_utc(now)
    item: dict[str, Any] = {
        "PK": f"PLAN#{plan_id}",
        "SK": "META",
        "planId": plan_id,
        "areaId": area_id(),
        "ownerId": user.id,
        "title": body.title,
        "summary": body.summary,
        "reason": body.reason,
        "estimatedMinutes": body.estimatedMinutes,
        "places": [
            {"order": i + 1, "name": p.name, "activity": p.activity, "whyChosen": p.whyChosen}
            for i, p in enumerate(body.places)
        ],
        "question": body.question,
        "status": OPEN,
        "createdAt": created,
        "version": 1,
        "metrics": compute_metrics(body),
        "GSI1PK": gsi1_pk(OPEN),
        "GSI1SK": created,
        "GSI2PK": f"USER#{user.id}",
        "GSI2SK": f"PLAN#{created}",
    }
    if user.nickname is not None:
        item["ownerNickname"] = user.nickname
    # OPEN 계획에는 currentClaimId·claimerId·dueAt·completedAt을 쓰지 않는다(요구사항 8.5).
    # 사연 원문(authoring.story)은 저장하지 않는다(요구사항 5.5).
    return item


def _get(pk: str, sk: str = "META") -> dict[str, Any] | None:
    return ddb.table().get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")


def _replay(key_item: dict[str, Any], digest: str) -> tuple[dict[str, Any], bool]:
    if key_item.get("bodyHash") != digest:
        raise ApiError(IDEMPOTENCY_CONFLICT)
    plan = _get(f"PLAN#{key_item['planId']}")
    if plan is None:  # 한 트랜잭션으로 썼으므로 생기지 않아야 한다
        raise ApiError(TRY_AGAIN)
    return plan, False


def create_plan(
    user: User, idem_key: str | None, body: PlanCreate, now: datetime | None = None
) -> tuple[dict[str, Any], bool]:
    """(Plan 항목, 새로 만들었는지). 재요청도 핸들러는 201로 응답한다(BE-Q24)."""
    if not idem_key or not idem_key.strip():
        # BE-Q29: details 키는 헤더 이름 그대로
        raise ApiError(VALIDATION_ERROR, details={"Idempotency-Key": "필수 헤더예요."})
    now = now or utc_now()
    digest = body_hash(body)
    key_pk = f"IDEM#{user.id}#{idem_key}"

    existing = _get(key_pk)
    if existing is not None:
        return _replay(existing, digest)

    plan = build_plan(user, body, now)
    table_name = ddb.table().name
    key_item = {
        "PK": key_pk,
        "SK": "META",
        "bodyHash": digest,
        "planId": plan["planId"],
        "ttl": int((now + IDEMPOTENCY_TTL).timestamp()),
    }
    try:
        ddb.transact_with_retry(
            [
                {"Put": {"TableName": table_name, "Item": plan, "ConditionExpression": "attribute_not_exists(PK)"}},
                {"Put": {"TableName": table_name, "Item": key_item, "ConditionExpression": "attribute_not_exists(PK)"}},
            ]
        )
    except ddb.ConditionFailed:
        # 같은 키를 다른 요청이 먼저 커밋했다. 키 항목을 다시 읽어 재생한다.
        existing = _get(key_pk)
        if existing is None:
            raise ApiError(TRY_AGAIN) from None  # 요구사항 4.12
        return _replay(existing, digest)
    return plan, True


# ---------------------------------------------------------------------------
# GET /plans
# ---------------------------------------------------------------------------


def normalize_limit(raw: Any) -> int:
    """BE-Q32: 숫자가 아니거나 1 미만이면 20, 50 초과면 50."""
    try:
        n = int(str(raw).strip()) if raw is not None else DEFAULT_LIMIT
    except ValueError:
        return DEFAULT_LIMIT
    if n < 1:
        return DEFAULT_LIMIT
    return min(n, MAX_LIMIT)


def _query_all(limit: int, **kwargs: Any) -> list[dict[str, Any]]:
    """필터 뒤 limit개가 모일 때까지 페이지를 이어 읽는다."""
    items: list[dict[str, Any]] = []
    start: dict[str, Any] | None = None
    while len(items) < limit:
        args = dict(kwargs, Limit=limit)
        if start:
            args["ExclusiveStartKey"] = start
        resp = ddb.table().query(**args)
        items += resp.get("Items", [])
        start = resp.get("LastEvaluatedKey")
        if not start:
            break
    return items[:limit]


def list_plans(status: str | None, limit: Any, now: datetime | None = None) -> list[dict[str, Any]]:
    """PlanSummary 목록. OPEN과 기한 지난 CLAIMED를 합쳐 createdAt 내림차순(nextCursor는 null, BE-Q3)."""
    if status != OPEN:
        raise ApiError(VALIDATION_ERROR, details={"status": "OPEN만 조회할 수 있어요."})
    n = normalize_limit(limit)
    now_iso = iso_utc(now or utc_now())
    open_items = _query_all(n, IndexName=GSI1, KeyConditionExpression=Key("GSI1PK").eq(gsi1_pk(OPEN)), ScanIndexForward=False)
    expired = _query_all(
        n,
        IndexName=GSI1,
        KeyConditionExpression=Key("GSI1PK").eq(gsi1_pk(CLAIMED)),
        FilterExpression=Attr("dueAt").lt(now_iso),
        ScanIndexForward=False,
    )
    merged = sorted(open_items + expired, key=lambda p: p["createdAt"], reverse=True)[:n]
    return [serialize_plan_summary(p, status_override=OPEN) for p in merged]


# ---------------------------------------------------------------------------
# GET /plans/{planId}
# ---------------------------------------------------------------------------


def _my_claim(plan_id: str, user_id: str) -> dict[str, Any] | None:
    """요청자의 Claim 중 ACTIVE(우선) 또는 COMPLETED. ABANDONED·EXPIRED만 있으면 None."""
    claims: list[dict[str, Any]] = []
    start: dict[str, Any] | None = None
    while True:
        args: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(f"PLAN#{plan_id}") & Key("SK").begins_with("CLAIM#"),
            "ConsistentRead": True,
        }
        if start:
            args["ExclusiveStartKey"] = start
        resp = ddb.table().query(**args)
        claims += [c for c in resp.get("Items", []) if c.get("claimerId") == user_id]
        start = resp.get("LastEvaluatedKey")
        if not start:
            break
    for wanted in (ACTIVE, COMPLETED):
        for c in claims:
            if c.get("status") == wanted:
                return c
    return None


def shown_status(plan: dict[str, Any], user_id: str, now: datetime) -> str:
    """기한 지난 CLAIMED는 현재 실행자가 아니면 OPEN으로 보인다(BE-PLAN-06)."""
    status = plan["status"]
    if status == CLAIMED and plan.get("dueAt") and parse_iso(plan["dueAt"]) < now and plan.get("claimerId") != user_id:
        return OPEN
    return status


def get_plan(plan_id: str, user: User, now: datetime | None = None) -> dict[str, Any]:
    """{plan, isOwner, myClaim, claimable} (직렬화까지 마친 응답 본문)."""
    now = now or utc_now()
    plan = _get(f"PLAN#{plan_id}")
    if plan is None:
        raise ApiError(NOT_FOUND)
    is_owner = plan.get("ownerId") == user.id
    my_claim = _my_claim(plan_id, user.id)
    if plan["status"] == COMPLETED and not (is_owner or my_claim):
        raise ApiError(NOT_FOUND)  # 소유자·해당 실행자 외에는 없는 계획과 같게(BE-PLAN-07)
    shown = shown_status(plan, user.id, now)
    return {
        "plan": serialize_plan(plan, is_owner=is_owner, status_override=shown),
        "isOwner": is_owner,
        "myClaim": serialize_claim(my_claim),
        "claimable": (not is_owner) and my_claim is None and shown == OPEN,
    }


# ---------------------------------------------------------------------------
# Plan 갱신 헬퍼 (BE-PLAN-09, 3단계 트랜잭션이 재사용)
# ---------------------------------------------------------------------------


def plan_update(
    plan_id: str,
    *,
    set_values: dict[str, Any] | None = None,
    remove: list[str] | None = None,
    new_status: str | None = None,
    condition: str | None = None,
    condition_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """TransactWriteItems의 Update 항목. version을 정확히 1 올리고, status를 바꾸면 GSI1PK도 같은 쓰기에서 바꾼다."""
    values: dict[str, Any] = {":one": 1}
    names: dict[str, str] = {}
    sets = ["#version = #version + :one"]
    names["#version"] = "version"
    fields = dict(set_values or {})
    if new_status is not None:
        fields["status"] = new_status
        fields["GSI1PK"] = gsi1_pk(new_status)
    for i, (k, v) in enumerate(fields.items()):
        names[f"#s{i}"] = k
        values[f":s{i}"] = v
        sets.append(f"#s{i} = :s{i}")
    expr = "SET " + ", ".join(sets)
    if remove:
        for i, k in enumerate(remove):
            names[f"#r{i}"] = k
        expr += " REMOVE " + ", ".join(f"#r{i}" for i in range(len(remove)))
    update: dict[str, Any] = {
        "TableName": ddb.table().name,
        "Key": {"PK": f"PLAN#{plan_id}", "SK": "META"},
        "UpdateExpression": expr,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values | dict(condition_values or {}),
    }
    if condition:
        update["ConditionExpression"] = condition
    return {"Update": update}
