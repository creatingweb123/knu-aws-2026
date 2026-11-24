# Design Document: backend-stage3-claim

## Overview

이어받기·포기·완료를 DynamoDB TransactWriteItems로 구현해 G1–G4를 보장한다. 모든 정합성 로직은 `src/domain/claim_service.py` 한 곳에 둔다(docs/07 §7.1 원칙 2). 1·2단계의 `transact_with_retry`, `plan_update`, `serialize_claim`, `iso_utc`를 재사용한다.

요구사항 매핑: BE-CLAIM-01–07, BE-REC-01·03·05–10, BE-OBS-01(3종), G1–G4, T3–T7·T14·T16.

## Architecture

```mermaid
graph LR
  P[PlansFunction<br/>POST /plans/{planId}/claims] --> S[claim_service]
  C[ClaimsFunction<br/>abandon · record PUT · complete] --> S
  M[MeFunction<br/>GET /me/claims] --> S
  S --> T[(HaruTable)]
  S --> E[metrics.emit → stdout EMF]
  PH[5단계 PhotoProcessor] -. complete_claim(WITH_PHOTO) .-> S
```

## 저장 항목 (§2.5·§2.6, 이번 단계에서 새로 쓰는 것)

| 항목 | PK / SK | 속성 |
|---|---|---|
| Claim | `PLAN#{planId}` / `CLAIM#{claimId}` | `claimId`, `planId`, `claimerId`, `claimerNickname`, `status`, `claimedAt`, `dueAt`, `completedAt`?, `late`?, `GSI2PK=USER#{claimerId}`, `GSI2SK=CLAIM#{claimedAt}` |
| ClaimLookup | `CLAIM#{claimId}` / `META` | `claimId`, `planId`, `claimerId` |
| Record | `PLAN#{planId}` / `RECORD#{claimId}` | `claimId`, `planId`, `authorId`, `letter`, `photoStatus`, `updatedAt`, `deliveredAt`?, (5단계) `photoKey`, `processedKey`, `photoError` |
| InboxItem | `USER#{ownerId}` / `INBOX#{claimId}` | `ownerId`, `itemId`, `planId`, `planTitle`, `claimerNickname`, `hasPhoto`, `read=false`, `createdAt`. `reply`는 쓰지 않는다 |

값이 없는 속성은 쓰지 않는다(`null` 저장 금지, `attribute_not_exists` 조건과 일관). `claimId = "clm_" + ULID`(BE-Q36).

## Components and Interfaces

### `common/errors.py` (추가)
`FORBIDDEN`(403), `ALREADY_CLAIMED`·`CANNOT_CLAIM_OWN_PLAN`·`CLAIM_NOT_ACTIVE`(409), `RECORD_REQUIRED`(400). 코드·상태 조합은 docs/03 §3.6과 같다.

### `common/ids.py` (추가)
`new_claim_id() -> "clm_" + ULID`.

### `common/metrics.py` (새로)
```python
def emit(name: str, value: int = 1) -> None   # EMF 한 줄을 print. 네임스페이스 Haru, 단위 Count, 차원 없음(BE-Q37)
```
로컬에서는 같은 줄이 stdout에 찍힌다(`AWS_EMF_ENVIRONMENT=Local`과 무관하게 형식이 같다).

### `domain/plan_service.plan_update` (확장)
조건식에서 이름 자리표시자를 쓸 수 있게 `condition_names: dict[str, str] | None`을 받는다. 기존 동작은 바꾸지 않는다.

### `domain/claim_service.py`
```python
def claim_plan(plan_id, user, now=None) -> tuple[dict, bool]        # (Claim 항목, 새로 만들었는지)
def abandon(claim_id, user, now=None) -> dict                        # Claim 항목
def put_record(claim_id, user, letter, now=None) -> dict             # Record 항목(트랜잭션 뒤 ConsistentRead로 다시 읽은 값)
def complete_claim(claim_id, mode, key=None, processed_key=None, now=None) -> dict   # {claim, delivered, hasPhoto}
def complete_by_user(claim_id, user, mode, now=None) -> dict         # 실행자 확인 후 complete_claim
def list_my_claims(user, status, now=None) -> list[dict]             # [{claim, plan, record|null}] (직렬화 완료)
```

### `common/responses.serialize_record` (새로)
허용 목록 `claimId, planId, letter, photoStatus, updatedAt, deliveredAt`. 값이 없으면 `deliveredAt: null`.

### 핸들러
- `handlers/plans.py`: `POST /plans/{planId}/claims` → 새로 만들면 201, 기존 Claim이면 200.
- `handlers/claims.py`(새): `POST /claims/{claimId}/abandon`, `PUT /claims/{claimId}/record`, `POST /claims/{claimId}/complete`. `GET /claims/{claimId}/record`는 4단계(docs/07 §7.3).
- `handlers/me.py`: `routeKey`로 나누는 구조로 바꾼다. `GET /me`(그대로, DB 미사용), `GET /me/claims`.
- `handlers/routes.py`: 위 5개 경로 추가. 공통 헬퍼(`_header`, `_json_body`)는 `handlers/_http.py`로 옮겨 함께 쓴다.

## Algorithmic Pseudocode

### 이어받기 (G1)

```python
def claim_plan(plan_id, user, now):
    for attempt in range(3):
        plan = get(PLAN#id, META, consistent)             ; 없으면 404
        decided = _decide(plan, user, now)                # 아래 판정. None이면 이어받을 수 있다
        if decided: return decided                        # (기존 Claim, False) 또는 예외
        claim_id = new_claim_id(); due = now + CLAIM_DURATION_DAYS
        items = [
          plan_update(id, new_status=CLAIMED, set={currentClaimId, claimerId: me, dueAt: due},
                      condition="#owner <> :me AND (#st = :open OR (#st = :claimed AND #due < :now))"),
          Put(Claim, cond attribute_not_exists(PK)),
          Put(ClaimLookup, cond attribute_not_exists(PK)),
        ]
        if plan.status == CLAIMED:                        # 기한 지난 대체 (T14)
            items.append(Update(PLAN#id / CLAIM#{plan.currentClaimId}, SET status=EXPIRED, cond status = ACTIVE))
        try: transact_with_retry(items); return claim_item, True
        except (ConditionFailed, ApiError(TRY_AGAIN)): continue   # 다시 읽어 판정(§2.6 공통 3·4번)
    raise TRY_AGAIN

def _decide(plan, user, now):
    if plan.ownerId == me: raise CANNOT_CLAIM_OWN_PLAN
    if (c := _active_claim_of(plan, user)): return c, False       # 200. 기한이 지났어도 본인이면 그대로(늦은 완료 허용)
    if plan.status == COMPLETED or (plan.status == CLAIMED and plan.dueAt >= now):
        emit("ClaimConflict"); raise ALREADY_CLAIMED
    return None                                                    # OPEN 또는 기한 지난 CLAIMED
```
- 읽은 시점과 트랜잭션 사이에 상태가 바뀌어도 Plan 조건이 막는다. 대체 대상 Claim의 `status = ACTIVE` 조건이 실패하는 경우(그사이 포기되어 Plan이 OPEN이 됨)는 다시 읽으면 이어받을 수 있는 상태이므로 새로 시도한다. 3번을 다 쓰면 503.
- 같은 사용자의 동시 요청(T4): 하나만 트랜잭션에 성공하고 나머지는 조건 실패 → 다시 읽으면 본인 `ACTIVE` Claim → 200. Claim 1건.
- 서로 다른 사용자 10명(T3): 승자 외에는 조건 실패 또는 `TransactionConflict` 소진 → 다시 읽으면 남의 기한 내 `CLAIMED` → 409. 503은 다시 읽어도 판정할 수 없을 때만 나간다.

### 포기 (G3)

```python
def abandon(claim_id, user, now):
    lookup = get(CLAIM#id, META, consistent)              ; 없으면 404
    if lookup.claimerId != me: raise FORBIDDEN
    claim = get(PLAN#pid, CLAIM#id, consistent)
    if claim.status != ACTIVE: emit("StaleRequestRejected"); raise CLAIM_NOT_ACTIVE
    record = get(PLAN#pid, RECORD#id, consistent)
    items = [
      plan_update(pid, new_status=OPEN, remove=[currentClaimId, claimerId, dueAt],
                  condition="#cur = :cid AND #st = :claimed AND #claimer = :me"),
      Update(Claim, SET status=ABANDONED, cond status = ACTIVE),
    ] + ([Update(Record, SET photoStatus=DISCARDED, cond attribute_exists(PK))] if record else [])
    try: transact_with_retry(items)
    except ConditionFailed: emit("StaleRequestRejected"); raise CLAIM_NOT_ACTIVE
    return claim | {status: ABANDONED}
```
- 5단계 주의: 포기 트랜잭션 직전에 Record가 새로 생기면(읽은 뒤 `put_record`가 먼저 커밋) 그 Record는 `DISCARDED`가 되지 않는다. 기한 지난 대체(`EXPIRED`)도 Record를 바꾸지 않는다. 3단계(글만)에서는 문제가 없고, 5단계 사진 처리는 Claim 상태를 확인하므로(docs/02 §2.7 1·6단계) 전달되지 않는다.

### 기록 저장 (글만)

```python
def put_record(claim_id, user, letter, now):
    lookup → 404 / 403
    items = [
      ConditionCheck(PLAN#pid/META, "#cur = :cid AND #st = :claimed"),
      ConditionCheck(PLAN#pid/CLAIM#id, "#st = :active"),
      Update(PLAN#pid/RECORD#id,
             SET letter, updatedAt, claimId, planId, authorId = :me,
                 photoStatus = if_not_exists(photoStatus, :none),
             cond attribute_not_exists(deliveredAt)),
    ]
    except ConditionFailed: emit("StaleRequestRejected"); raise CLAIM_NOT_ACTIVE
```
- `letter`는 pydantic(`RecordPut`, 1–1,000자, `photo` 금지 BE-Q34)으로 검증한다.

### 완료 (G2·G3·G4)

```python
def complete_claim(claim_id, mode, key=None, processed_key=None, now=None):
    for attempt in range(3):
        lookup = get(CLAIM#id)                      ; 없으면 404
        claim = get(PLAN#pid/CLAIM#id, consistent)
        if claim.status == COMPLETED: return _done(claim, duplicate=True)
        if claim.status != ACTIVE: emit Stale; raise CLAIM_NOT_ACTIVE
        plan = get(PLAN#pid/META, consistent)
        if plan.currentClaimId != claim_id or plan.status != CLAIMED: emit Stale; raise CLAIM_NOT_ACTIVE
        record = get(PLAN#pid/RECORD#id, consistent)
        if not record or not record.letter: raise RECORD_REQUIRED
        prev = record.photoStatus or NONE
        new_photo = READY if mode == WITH_PHOTO else (NONE if prev == NONE else DISCARDED)
        rec_cond = "attribute_exists(letter) AND attribute_not_exists(deliveredAt) AND #ps = :prev"
        if mode == WITH_PHOTO: rec_cond += " AND #pk = :key AND #ps = :processing"
        items = [
          plan_update(pid, new_status=COMPLETED, set={completedAt: now}, condition="#cur = :cid AND #st = :claimed"),
          Update(Claim, SET status=COMPLETED, completedAt=now, late=(now > dueAt), cond status = ACTIVE),
          Update(Record, SET deliveredAt=now, photoStatus=new_photo [, processedKey], cond rec_cond),
          Put(InboxItem{..., hasPhoto: mode == WITH_PHOTO}, cond attribute_not_exists(PK)),
        ]
        try: transact_with_retry(items); return {claim(COMPLETED), delivered: True, hasPhoto}
        except (ConditionFailed, ApiError(TRY_AGAIN)): continue   # 다시 읽어 위 분기로 판정
    raise TRY_AGAIN
```
- Record의 `attribute_not_exists(deliveredAt)`와 `#ps = :prev`는 docs/02 §2.6에 더한 방어 조건이다(BE-Q40). 실패하면 다시 읽어 판정하므로 응답은 문서와 같다.
- `_done(claim, duplicate)`: `hasPhoto`는 Record의 `photoStatus == READY`(또는 InboxItem `hasPhoto`). `duplicate`면 `CompleteDuplicate`.
- 동시 완료 10회(T5): 하나만 성공하고 나머지는 조건 실패 → 다시 읽으면 Claim이 `COMPLETED` → 200 멱등. InboxItem은 `attribute_not_exists(PK)`로 1건만.
- Record가 아예 없는 상태에서는 트랜잭션 전 `RECORD_REQUIRED`. Record의 `photoStatus` 속성이 없을 수 있는 과거 데이터는 `:prev`를 쓰지 않고 `attribute_not_exists(photoStatus)`로 건다.

### 내 이어받기 목록

```python
def list_my_claims(user, status, now):
    if status not in (ACTIVE, COMPLETED): raise VALIDATION_ERROR {"status"}
    claims = query(GSI2, GSI2PK = USER#me, GSI2SK begins_with CLAIM#, desc, 페이지 끝까지) → status 필터
    for c in claims: plan = get(PLAN#c.planId/META); record = get(PLAN#.../RECORD#c.claimId)
       → {claim: serialize_claim(c), plan: serialize_plan(plan, is_owner=False, shown_status(plan, me, now)), record: serialize_record(record)}
```
- GSI2는 최종 일관성이라 방금 이어받은 Claim이 잠깐 안 보일 수 있다(BE-Q41, MVP 허용). Plan·Record는 ConsistentRead.

## SAM 템플릿 변경

| 리소스 | 변경 |
|---|---|
| `PlansFunction` | 이벤트 `POST /plans/{planId}/claims` 추가, 권한에 `dynamodb:UpdateItem` 추가 |
| `ClaimsFunction`(새) | `handlers.claims.handler`, 이벤트 3개, 권한 `GetItem`·`PutItem`·`UpdateItem`·`ConditionCheckItem`(`HaruTable`만) |
| `MeFunction` | 이벤트 `GET /me/claims` 추가, 권한 `GetItem`·`Query`(`HaruTable`, `index/*`) |

## Correctness Properties

### Property 12: 이어받기 단일 확정 (G1, T3)
같은 Plan에 대한 이어받기 요청 집합에서 성공(201)은 최대 1건이고, 성공이 있으면 Plan `currentClaimId`는 그 Claim이다. 나머지는 200(본인) 또는 409.
**Validates: Requirements 1.2, 1.3, 1.4**

### Property 13: 상태 일관성 불변식 (G2–G4)
무작위 순서의 이어받기·포기·기록·완료 연산 뒤에 항상:
- Plan `CLAIMED` ⇔ `currentClaimId`가 가리키는 Claim이 `ACTIVE`(또는 기한 지난 대체 직전)
- Plan당 `ACTIVE` Claim은 최대 1건
- Plan `COMPLETED` ⇔ 정확히 하나의 Claim이 `COMPLETED` ⇔ 그 Record에 `deliveredAt` ⇔ InboxItem 1건
- `version`은 Plan 갱신 횟수 + 1
**Validates: Requirements 2.1, 4.2, 4.5, 6.3**

### Property 14: 완료 멱등 (G2, T5)
같은 Claim에 완료를 n회 호출하면 InboxItem 1건, 모든 응답 `delivered: true`, `CompleteDuplicate`는 n−1회.
**Validates: Requirements 4.5**

### Property 15: 끝난 이어받기 쓰기 거부 (G3, T6·T7)
`ABANDONED`·`EXPIRED`이거나 Current_Claim이 아닌 Claim으로의 기록 저장·완료·포기는 모두 409이고 Plan·Record·InboxItem을 바꾸지 않는다.
**Validates: Requirements 2.4, 3.3, 4.9, 4.10**

## Testing Strategy

| 수준 | 도구 | 대상 |
|---|---|---|
| 단위(moto) | moto `mock_aws` + 실제 boto3 | Claim_Service 전 분기, Property 13·14·15(Hypothesis로 연산 순서 생성), 기한 지난 대체 |
| 단위(Stubber) | botocore Stubber | `TransactionConflict` 재시도는 1·2단계 `test_ddb.py`가 이미 확인. 완료의 3회 재판정 후 503 |
| 단위(핸들러) | 가짜 이벤트 | 라우팅, 상태 코드(201/200), 403/404/409, 검증 오류 |
| 템플릿 | `test_template.py` | 경로 일치, 함수별 권한 |
| AWS | `tests/integration` | T3(10명 동시), T4(본인 5회), T5(완료 10회), T14(`dueAt` 직접 변경), T6, T7, T16. 수신함·Record·Claim 건수는 DynamoDB 직접 조회(BE-Q38) |

moto와 Floci는 실제 병렬성·`TransactionConflict`를 재현하지 않는다. Property 12는 moto에서 순차 경합(읽기 뒤 다른 요청 커밋)으로 확인하고, 실제 동시성 판정은 AWS(T3–T5)에서 한다.

## Error Handling

| 상황 | 응답 |
|---|---|
| Plan·Claim 없음 | 404 `NOT_FOUND` |
| 실행자 아님(포기·기록·완료·기록 조회) | 403 `FORBIDDEN` |
| 다른 사람이 확정 / COMPLETED | 409 `ALREADY_CLAIMED` |
| 자기 계획 | 409 `CANNOT_CLAIM_OWN_PLAN` |
| 끝났거나 Current_Claim 아님 | 409 `CLAIM_NOT_ACTIVE` |
| 글 없이 완료 | 400 `RECORD_REQUIRED` |
| 재시도·재판정 소진 | 503 `TRY_AGAIN` |

## 미결·유예

requirements의 "미결 사항"(BE-Q34–BE-Q41)과 같다. BE-Q1(`GET /record` 403)은 4단계에서 다룬다. 사진 경로(`photo`, 업로드 URL, `WITH_PHOTO` 호출자)는 5단계에서 이 설계의 `complete_claim`을 그대로 쓴다.
