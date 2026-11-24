# Requirements Document

## Introduction

백엔드 3단계(이어받기·포기·완료 트랜잭션)의 요구사항이다. 이 단계가 프로젝트의 핵심 검증 대상인 보장 G1–G4를 구현한다. 기준은 `docs/02-architecture.md` §2.5·§2.6, `docs/03-api-contract.md` §3.1·§3.3·§3.4, `docs/06-requirements.md` BE-CLAIM-01–07·BE-REC-01·03·05–10·BE-OBS-01, `docs/07-development-plan.md` §7.3 3단계다.

- 1·2단계(`backend-stage1-2-foundation`)의 공통 모듈·계획 서비스·템플릿을 그대로 쓴다.
- 범위 밖: 사진(업로드 URL, `photo` 필드, 사진 교체, 사진 처리 Lambda, 5단계), `GET /claims/{claimId}/record`와 수신함 조회·읽음·답장(4단계), `unreadInboxCount` 계산(4단계), AI(6단계). 완료 트랜잭션은 수신함 항목을 **만들기만** 한다.
- `PUT /claims/{claimId}/record`(글만)는 docs/07 §7.3 3단계 비고("4단계의 `PUT /record`를 먼저 최소 구현하거나 테스트 픽스처로 Record를 직접 넣는다")에 따라 최소로 먼저 구현한다. T6·T7을 AWS에서 판정하려면 API가 있어야 하기 때문이다. 4단계는 이 구현을 이어받아 `GET /record`와 함께 완성한다.
- 문서에 없는 결정은 임시 기본안으로 정하고 BE-Q 번호를 붙였다(마지막 "미결 사항"). 새 질문은 BE-Q34부터다.
- 판정: G1–G4(T3–T7, T14, T16)는 AWS 스택에서만 판정한다(BE-Q15). 개발 담당은 AWS 계정이 없으므로 moto(인프로세스 DynamoDB 흉내)로 조건식·갱신식 로직을 확인하고, 판정은 AWS 담당이 `tests/integration`으로 한다(docs/07 §7.8).

## Glossary

- **Claim_Service**: `src/domain/claim_service.py`. 이어받기·포기·완료·기록 저장·내 이어받기 목록.
- **Claim**: 한 번의 이어받기 시도. `PLAN#{planId}` / `CLAIM#{claimId}`. 상태 `ACTIVE` → `COMPLETED` / `ABANDONED` / `EXPIRED`.
- **Claim_Lookup**: `CLAIM#{claimId}` / `META`. `claimId`만으로 `planId`·실행자를 찾는 항목.
- **Record**: Claim당 1개인 방문 기록. `PLAN#{planId}` / `RECORD#{claimId}`. 이번 단계는 글만 다룬다.
- **Inbox_Item**: 계획자 수신함 항목. `USER#{ownerId}` / `INBOX#{claimId}`. Claim당 최대 1개.
- **Current_Claim**: Plan의 `currentClaimId`가 가리키는 Claim.
- **Expired_Claimed_Plan**: `status = CLAIMED`이고 `dueAt < now`인 Plan.
- **Transaction**: `common.ddb.transact_with_retry`로 실행하는 TransactWriteItems. 실패 처리는 docs/02 §2.6 공통 규칙.

## Requirements

### Requirement 1: 이어받기 (G1)

**User Story:** As a 실행자, I want 남이 남긴 하루를 이어받고 싶다, so that 그 계획대로 다녀올 수 있다. 여러 명이 동시에 눌러도 한 명만 확정되어야 한다.

#### Acceptance Criteria

1. WHEN 인증된 사용자가 소유자가 아닌 `OPEN` Plan에 `POST /plans/{planId}/claims`를 호출하면, THE Claim_Service SHALL 하나의 Transaction으로 Plan을 `CLAIMED`로 바꾸고(`currentClaimId`, `claimerId`, `dueAt`, `GSI1PK`, `version + 1`), Claim과 Claim_Lookup을 만들고, 201 `{ claim }`을 반환한다. [BE-CLAIM-01, §2.6]
2. THE Transaction SHALL Plan 갱신에 조건 `ownerId <> :me AND (status = 'OPEN' OR (status = 'CLAIMED' AND dueAt < :now))`, Claim·Claim_Lookup 생성에 `attribute_not_exists(PK)`를 건다. [§2.6, G1]
3. WHEN 같은 Plan에 서로 다른 사용자의 이어받기가 동시에 들어오면, THE Claim_Service SHALL 정확히 한 요청만 성공시키고 나머지에 409 `ALREADY_CLAIMED`를 반환하며, Plan의 `currentClaimId`는 성공한 Claim을 가리킨다. [BE-CLAIM-02, G1, T3]
4. WHEN 현재 실행자 본인이 같은 Plan에 다시 이어받기를 요청하면, THE Claim_Service SHALL 새 Claim을 만들지 않고 기존 `ACTIVE` Claim을 200 `{ claim }`으로 반환한다. 동시에 여러 번 요청해도 Claim은 1건이다. [BE-CLAIM-03, T4]
5. IF 소유자가 자기 Plan에 이어받기를 요청하면, THEN THE Claim_Service SHALL 409 `CANNOT_CLAIM_OWN_PLAN`으로 응답하고 아무것도 쓰지 않는다. [BE-CLAIM-04]
6. THE Claim_Service SHALL `dueAt = claimedAt + CLAIM_DURATION_DAYS`(환경 변수, 기본 3일)로 정한다. [BE-CLAIM-05]
7. WHEN 다른 사용자가 Expired_Claimed_Plan을 이어받으면, THE Claim_Service SHALL 같은 Transaction 안에서 이전 Current_Claim을 조건 `status = 'ACTIVE'`로 `EXPIRED`로 바꾸고 새 Claim을 확정한다. [BE-CLAIM-05, T14]
8. IF Plan이 없으면, THEN THE Claim_Service SHALL 404 `NOT_FOUND`로 응답한다. IF 다른 사람이 기한 안에 이어받은 상태면, THEN 409 `ALREADY_CLAIMED`로 응답한다. IF Plan이 `COMPLETED`면, THEN 409 `ALREADY_CLAIMED`로 응답한다. [§3.3, BE-Q39]
9. IF Transaction이 조건 실패로 취소되면, THEN THE Claim_Service SHALL Plan을 `ConsistentRead`로 다시 읽어 docs/02 §2.6 순서(본인의 `ACTIVE` Claim이면 200, 소유자면 `CANNOT_CLAIM_OWN_PLAN`)로 응답한다. 다시 읽은 Plan이 이어받을 수 있는 상태(`OPEN`이거나 기한 지난 `CLAIMED`, 예: 대체 대상 Claim이 그사이 포기됨)면 새로 다시 시도하고(최대 3회), 그 밖에는 `ALREADY_CLAIMED`로 응답한다. 3회를 다 쓰면 503 `TRY_AGAIN`. [§2.6]
10. IF `TransactionConflict` 재시도를 다 써서 `transact_with_retry`가 503 `TRY_AGAIN`을 올리면, THEN THE Claim_Service SHALL 503을 내보내기 전에 Plan을 `ConsistentRead`로 다시 읽어 9번과 같이 판정하고, 판정할 수 없을 때만 503 `TRY_AGAIN`으로 응답한다. 동시 경합에서 승자가 이미 커밋했으면 패자는 409(또는 본인이면 200)를 받는다. [§2.6 공통 4번 "재시도를 다 써도 판정할 수 없으면 503", T3, T4]
11. WHEN 409 `ALREADY_CLAIMED`로 응답하면, THE Claim_Service SHALL EMF 지표 `ClaimConflict`를 1 기록한다. [BE-OBS-01]

### Requirement 2: 포기 (G3)

**User Story:** As a 실행자, I want 다녀오기 어려워진 하루를 포기하고 싶다, so that 다른 사람이 이어받을 수 있다.

#### Acceptance Criteria

1. WHEN 현재 실행자가 `POST /claims/{claimId}/abandon`을 호출하면, THE Claim_Service SHALL 하나의 Transaction으로 Plan을 `OPEN`으로 되돌리고(`GSI1PK`, `version + 1`, `currentClaimId`·`claimerId`·`dueAt` 제거), Claim을 `ABANDONED`로, Record가 있으면 `photoStatus = DISCARDED`로 바꾸고, 200 `{ claim }`을 반환한다. [BE-CLAIM-06, §2.6]
2. THE Transaction SHALL Plan 갱신에 조건 `currentClaimId = :claimId AND status = 'CLAIMED' AND claimerId = :me`, Claim 갱신에 `status = 'ACTIVE'`를 건다. Record가 없으면 Record 항목은 Transaction에서 뺀다. [§2.6]
3. IF Claim이 없으면, THEN 404 `NOT_FOUND`. IF 요청자가 Claim의 실행자가 아니면, THEN 403 `FORBIDDEN`. [BE-CLAIM-06, G5]
4. IF Claim이 이미 `ACTIVE`가 아니거나 조건이 실패하면, THEN THE Claim_Service SHALL 409 `CLAIM_NOT_ACTIVE`로 응답하고 EMF 지표 `StaleRequestRejected`를 1 기록한다. [BE-CLAIM-06, BE-OBS-01, T6]
5. WHEN 포기가 끝나면, THE Plan SHALL `GET /plans?status=OPEN` 목록에 다시 나타난다. [T16]

### Requirement 3: 방문 기록 저장 (글만, 최소 구현, G3)

**User Story:** As a 실행자, I want 다녀온 이야기를 글로 저장하고 싶다, so that 완료 전에 고쳐 쓰고 완료할 수 있다.

#### Acceptance Criteria

1. WHEN 현재 실행자가 `PUT /claims/{claimId}/record { letter }`(1–1,000자)를 호출하면, THE Claim_Service SHALL Plan `currentClaimId = :claimId AND status = 'CLAIMED'`와 Claim `status = 'ACTIVE'`를 조건으로 확인하는 Transaction 안에서 Record의 `letter`, `updatedAt`을 쓰고 200 `{ record, upload: null }`을 반환한다. 처음 쓸 때 `photoStatus`는 `NONE`이다. [BE-REC-01, G3]
2. THE Claim_Service SHALL 완료 전까지 `letter`를 덮어쓸 수 있게 하고, 이미 전달된 Record(`deliveredAt` 있음)는 바꾸지 않는다. [BE-REC-01, BE-REC-03]
3. IF 요청자가 실행자가 아니면 403 `FORBIDDEN`, IF Claim이 없으면 404, IF Claim이 `ACTIVE`가 아니거나 Plan의 Current_Claim이 아니면 409 `CLAIM_NOT_ACTIVE`(+`StaleRequestRejected`), IF `letter`가 범위 밖이면 400 `VALIDATION_ERROR`. [BE-REC-01, T6, T7]
4. IF 요청 본문에 `photo`가 있으면, THEN 이번 단계에서는 400 `VALIDATION_ERROR`(`details` 키 `photo`)로 응답한다. 사진은 5단계에서 계약대로 구현한다. [BE-Q34]
5. THE 응답의 `record` SHALL 트랜잭션 뒤 Record를 `ConsistentRead`로 다시 읽어 만든다(TransactWriteItems는 갱신된 값을 돌려주지 않는다).

### Requirement 4: 완료 (G2, G3, G4)

**User Story:** As a 실행자, I want 기록을 보내 이어받기를 완료하고 싶다, so that 계획자 수신함에 정확히 한 번 도착한다.

#### Acceptance Criteria

1. THE Claim_Service SHALL 완료를 공통 함수 `complete_claim(claim_id, mode, key=None, processed_key=None)` 하나로 처리하고, API(`TEXT_ONLY`)와 5단계 사진 처리 Lambda(`WITH_PHOTO`)가 같은 함수를 쓴다. [BE-REC-06, §2.6]
2. THE `complete_claim` SHALL 하나의 Transaction으로 Plan을 `COMPLETED`(`completedAt`, `GSI1PK`, `version + 1`), Claim을 `COMPLETED`(`completedAt`, `late = now > dueAt`), Record에 `deliveredAt`과 `photoStatus`를 쓰고, Inbox_Item을 `attribute_not_exists(PK)` 조건으로 만든다. [BE-REC-06, G4]
3. THE Transaction SHALL Plan에 `currentClaimId = :claimId AND status = 'CLAIMED'`, Claim에 `status = 'ACTIVE'`, Record에 `attribute_exists(letter)`를 조건으로 건다(`WITH_PHOTO`면 `AND photoKey = :key AND photoStatus = 'PROCESSING'`). [§2.6] 여기에 방어 조건 두 가지를 더한다: Record `attribute_not_exists(deliveredAt)`, 읽은 시점의 `photoStatus` 일치. 5단계에서 사진 처리와 글로 완료가 경합할 때 4번 규칙이 오래된 값으로 계산되지 않게 하려는 것이다. 이 조건이 실패하면 6번대로 다시 읽어 판정한다. [BE-Q40]
4. THE Record의 `photoStatus` SHALL `WITH_PHOTO`면 `READY` + `processedKey`, `TEXT_ONLY`이고 사진이 없었으면 `NONE`, `TEXT_ONLY`이고 `UPLOAD_PENDING`·`PROCESSING`·`FAILED`·미전달 `READY`였으면 `DISCARDED`가 된다. [BE-REC-08]
5. WHEN 같은 Claim에 완료가 여러 번(동시 포함) 들어오면, THE Claim_Service SHALL Inbox_Item과 Record 전달을 1건만 남기고 모든 요청에 200 `{ claim, delivered: true, hasPhoto }`를 반환하며, 두 번째 이후 요청마다 EMF 지표 `CompleteDuplicate`를 1 기록한다. [BE-REC-07, G2, T5]
6. IF Transaction이 조건 실패로 취소되거나 `TransactionConflict` 재시도를 다 쓰면(503), THEN THE Claim_Service SHALL Claim을 `ConsistentRead`로 다시 읽어 `COMPLETED`면 200 멱등 응답, `ABANDONED`·`EXPIRED`이거나 Plan의 Current_Claim이 아니면 409 `CLAIM_NOT_ACTIVE`, 글이 없으면 400 `RECORD_REQUIRED`로 응답한다. 그 밖의 원인(사진 상태가 바뀐 경우)은 다시 읽어 최대 3번 다시 시도하고, 그래도 판정할 수 없으면 503 `TRY_AGAIN`. [BE-REC-09, §2.6]
7. WHEN 클라이언트가 `POST /claims/{claimId}/complete { mode: "TEXT_ONLY" }`를 호출하면, THE Claim_Service SHALL Transaction 전에 요청자가 실행자인지 확인하고 아니면 403 `FORBIDDEN`으로 응답한다. `mode`가 `TEXT_ONLY`가 아니면 400 `VALIDATION_ERROR`. [BE-REC-06, §3.4]
8. IF 이미 사진과 함께 완료된 Claim에 `TEXT_ONLY` 완료가 오면, THEN THE Claim_Service SHALL 200, `hasPhoto: true`로 응답한다. [BE-REC-08]
9. WHEN 포기 후 이전 `claimId`로 기록 저장·완료를 요청하면, THE Claim_Service SHALL 409 `CLAIM_NOT_ACTIVE`로 응답하고 Inbox_Item을 만들지 않는다. [T6]
10. WHEN 포기 후 다른 사용자가 이어받은 뒤 첫 실행자의 늦은 완료가 오면, THE Claim_Service SHALL 409 `CLAIM_NOT_ACTIVE`로 거부하고 두 번째 실행자의 완료는 정상 처리한다. [T7, G3]
11. THE Inbox_Item SHALL `ownerId`, `itemId = claimId`, `planId`, `planTitle`, `claimerNickname`, `hasPhoto`, `read = false`, `createdAt`을 가지며 `reply` 속성은 쓰지 않는다. [§2.5]

### Requirement 5: 내 이어받기 목록

**User Story:** As a 실행자, I want 내가 이어받은 하루와 기한을 보고 싶다, so that 다녀올 하루를 관리할 수 있다.

#### Acceptance Criteria

1. WHEN 인증된 사용자가 `GET /me/claims?status=ACTIVE|COMPLETED`를 호출하면, THE Claim_Service SHALL GSI2(`USER#{me}`, `CLAIM#` 접두사)로 요청자의 Claim을 찾아 그 `status`인 것만 `claimedAt` 최신순으로 `{ items: [{ claim, plan, record|null }] }`로 반환한다. GSI2는 최종 일관성이라 방금 이어받은 Claim이 잠깐 빠질 수 있다. [BE-CLAIM-07, §3.1, BE-Q41]
2. IF `status`가 `ACTIVE`·`COMPLETED`가 아니거나 없으면, THEN 400 `VALIDATION_ERROR`(`details` 키 `status`). [BE-Q35]
3. THE `plan` SHALL 요청자 기준 상태 표시 규칙(1·2단계 `get_plan`과 같음)과 허용 목록 직렬화를 따른다. 요청자가 소유자가 아니므로 `metrics`는 없다. [BE-PLAN-06, BE-PLAN-08]

### Requirement 6: 직렬화와 저장 형식

#### Acceptance Criteria

1. THE Claim SHALL `claimId`(`clm_` + ULID), `planId`, `claimerId`, `claimerNickname`, `status`, `claimedAt`, `dueAt`, `completedAt`, `late`, `GSI2PK = USER#{claimerId}`, `GSI2SK = CLAIM#{claimedAt}`로 저장한다. 응답은 1·2단계 `serialize_claim` 허용 목록을 쓴다. [§2.5, BE-Q36]
2. THE Record 응답 SHALL `claimId`, `planId`, `letter`, `photoStatus`, `updatedAt`, `deliveredAt`만 담고 `photoKey`·`processedKey`·`photoError`·`authorId`·키 속성은 내보내지 않는다. [§2.5, BE-PLAN-08]
3. THE Claim_Service SHALL 모든 Plan 갱신에서 `version`을 정확히 1 올리고 `status`가 바뀌면 `GSI1PK`를 같은 쓰기에서 바꾼다. [BE-PLAN-09]
4. THE 시간 값 SHALL `iso_utc`(밀리초 고정 UTC)로 저장하고 반환한다. `dueAt` 비교는 이 문자열 비교에 기대므로 다른 형식을 섞지 않는다. [docs/03 공통 규칙]

### Requirement 7: 템플릿과 권한

#### Acceptance Criteria

1. THE Backend SHALL `routes.py`에 `POST /plans/{planId}/claims`(PlansFunction), `GET /me/claims`(MeFunction), `POST /claims/{claimId}/abandon`, `PUT /claims/{claimId}/record`, `POST /claims/{claimId}/complete`(새 ClaimsFunction)를 추가하고, `template.yaml` 이벤트와 일치시킨다. [docs/02 §2.3, 요구사항(1·2단계) 13.9]
2. THE PlansFunction SHALL `GetItem`, `PutItem`, `UpdateItem`, `Query`만, ClaimsFunction은 `GetItem`, `PutItem`, `UpdateItem`, `ConditionCheckItem`만, MeFunction은 `GetItem`, `Query`만 `HaruTable`(과 필요한 경우 `index/*`)에 갖는다. `GET /me`는 계속 DB를 읽지 않는다. [BE-INFRA-06, BE-Q30]
3. THE 의존성 SHALL 1·2단계와 같다(LangGraph·LangChain·Pillow 없음). [요구사항(1·2단계) 12.9]

### Requirement 8: 지표 (EMF)

1. THE Backend SHALL `src/common/metrics.py`로 CloudWatch EMF 형식 JSON 한 줄을 표준 출력에 남긴다. 네임스페이스 `Haru`, 단위 `Count`, 차원 없음. Lambda는 표준 출력의 EMF 줄을 CloudWatch Logs가 지표로 추출하고, 로컬은 같은 줄이 stdout에 남는다. 그래서 `AWS_EMF_ENVIRONMENT`(값 `Local`)와 무관하게 출력이 같고, 외부 라이브러리(aws-embedded-metrics)를 쓰지 않는다. [BE-OBS-01, docs/02 §2.4, BE-Q37]
2. THE 지표 로그 SHALL 사용자 ID·본문·토큰을 담지 않는다. [BE-NFR-03]

### Requirement 9: 완료 기준

1. WHEN 단위 테스트를 실행하면, THE Backend SHALL moto 대상 Claim_Service 테스트(이어받기·포기·기록·완료의 모든 분기, 기한 지난 대체, 멱등), Stubber 대상 재시도, 상태 전이 속성 테스트, 핸들러·템플릿 테스트를 실패 0건으로 통과한다.
2. THE Backend SHALL AWS 스택 대상 테스트 `tests/integration/test_concurrency.py`(T3, T4, T5, T14)와 `test_claim_lifecycle.py`(T6, T7, T16)를 제공한다. 실행·판정은 AWS 담당이 한다. T3·T5는 결과 로그를 `test-results/`에 남긴다. 수신함 API는 4단계이므로 InboxItem·Record·Claim 건수는 테스트가 DynamoDB를 직접 조회해 확인한다(BE-Q38).
3. THE Backend SHALL `sam validate --lint`와 `sam build`를 통과한다.
4. THE 4단계 SHALL AWS에서 T3–T7이 통과하기 전에는 시작하지 않는다(docs/07 §7.2). 이 기준은 인계 문서에 적는다.

## 미결 사항

`docs/08-open-questions.md` §8.1에 추가한다.

| # | 내용 | 임시 결정 |
|---|---|---|
| BE-Q34 | 3단계의 `PUT /record`에 `photo`가 오면 | 400 `VALIDATION_ERROR`, `details` 키 `photo`. 5단계에서 계약대로(업로드 URL 발급) 구현할 때까지만 |
| BE-Q35 | `GET /me/claims`의 `status` 누락·잘못된 값 | 400 `VALIDATION_ERROR`(`details` 키 `status`). 프론트는 항상 보낸다 |
| BE-Q36 | `claimId` 형식 | `clm_` + ULID(`planId`와 같은 패턴). 실행자 닉네임 속성 `claimerNickname`은 1·2단계 `serialize_claim`이 이미 쓰는 이름 |
| BE-Q37 | EMF 구현 방식·네임스페이스·차원 | 라이브러리 없이 EMF JSON을 직접 출력, `AWS_EMF_ENVIRONMENT`와 무관하게 같은 형식, 네임스페이스 `Haru`, 차원 없음 |
| BE-Q38 | AWS 판정에서 기한 3일을 기다릴 수 없음(T14), 수신함 API가 4단계라 건수를 API로 볼 수 없음(T5·T6) | 테스트가 테스트 실행자 자격 증명으로 DynamoDB를 직접 조회·갱신한다(T14는 Plan·Claim `dueAt`을 과거로 바꾼다). 필요한 IAM: 대상 테이블 `GetItem`·`Query`·`UpdateItem`·`DeleteItem` |
| BE-Q39 | `COMPLETED` Plan에 이어받기 요청 시 코드 | 409 `ALREADY_CLAIMED`. 상세 조회는 남에게 404를 주므로, 이 응답으로 완료된 계획의 존재가 드러난다(MVP 허용) |
| BE-Q40 | 완료 Record 조건에 docs/02 §2.6보다 더한 방어 조건(`attribute_not_exists(deliveredAt)`, 읽은 `photoStatus` 일치) | 둔다. 실패하면 다시 읽어 판정하므로 결과(200·409·400)는 문서와 같다 |
| BE-Q41 | `GET /me/claims`가 GSI2(최종 일관성)라 방금 이어받은 Claim이 잠깐 빠질 수 있다 | MVP 허용. 프론트는 이어받기 응답의 `claim`으로 화면을 먼저 그린다(FE 확인 필요) |
