# Requirements Document

## Introduction

백엔드 4단계(방문 기록(글)과 수신함)의 요구사항이다. 기준은 `docs/07-development-plan.md` §7.3 4단계("`PUT /claims/{claimId}/record`(글만), `GET /claims/{claimId}/record`, 수신함 4종, `unreadInboxCount`, 통합 테스트 T2, T17"), `docs/03-api-contract.md` §3.1·§3.4·§3.5·§3.6, `docs/02-architecture.md` §2.3·§2.5·§2.6·§2.8·§2.10, `docs/06-requirements.md` BE-REC-01·03·05, BE-INBOX-01–04, BE-AUTH-05, BE-INFRA-06, BE-NFR-02·05·07이다. 이 단계가 끝나면 프론트 연동 지점 S2(글 경로 전체를 실제 API로 전환)가 열린다.

- 1·2단계(`backend-stage1-2-foundation`)와 3단계(`backend-stage3-claim`)의 공통 모듈·서비스·템플릿을 그대로 쓴다. 불필요한 리팩터링은 하지 않는다. 기존 함수는 이번 범위에 필요한 만큼만 고친다.
- 3단계에서 이미 구현한 것: `PUT /claims/{claimId}/record`(글만, 최소 구현, `claim_service.put_record`), `POST /claims/{claimId}/complete`(`TEXT_ONLY`, `claim_service.complete_claim`·`complete_by_user`), 완료 트랜잭션의 InboxItem 생성. docs/07 §7.3은 완료를 3단계 작업으로 둔다. 그래서 이번 단계는 완료 트랜잭션을 새로 만들거나 고치지 않고, 회귀 테스트로 G2–G4가 유지되는지만 확인한다. `PUT /record`는 3단계 구현을 이어받아 계약(§3.4)과 맞는지 확인하고 `GET /record`와 함께 완성한다.
- 이번 단계에서 새로 만드는 것: `GET /claims/{claimId}/record`, `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply`, `GET /me`의 `unreadInboxCount` 계산, `InboxFunction`과 IAM 권한, 단위·로컬 통합 테스트, AWS 스택 대상 T2·T17 테스트.
- 범위 밖: 사진(`PUT /record`의 `photo` 처리와 presigned PUT, `POST /claims/{claimId}/record/photo`, 사진 버킷·SQS·사진 처리 Lambda, `photoUrl` presigned GET 발급, 5단계), AI(`/ai/card-sessions*`, 6단계), CloudFront·알람·`seed.py`(7단계), P1 기능(`GET /me/claims`의 `reply`, `GET /me/plans`). 계약상 사진 관련 응답 필드(`upload`, `photoStatus`, `photoUrl`, `photoCaption`, `hasPhoto`)는 계약 형태대로 내보내고, 이번 단계의 값은 아래 각 기준과 BE-Q34·BE-Q42를 따른다.
- AWS 배포는 하지 않는다. `sam validate --lint`와 `sam build`까지만 하고, T2·T17은 테스트 코드만 작성한다. 실행·판정은 AWS 담당이 한다(docs/07 §7.8, BE-Q15).
- **기준 브랜치**: 백엔드 작업은 `feat/be-4-record-inbox`에서 한다. 이 브랜치는 `fix/be-3-local-verify`의 최신 커밋 `8fcf239`를 포함한다. 여기에는 `common/auth.py`의 `token_use == "id"` 검사(`2d98ac8`), AWS 판정 기록(`e80b890`), 통합 테스트 정리 `_cleanup` 보완(`33cba6b`), 로컬 첫 구동 기록(`8fcf239`)이 들어 있다. 프론트엔드 작업 트리(`feat/fe-4-record-inbox`)는 이번 작업에서 바꾸지 않는다. 프론트 타입(`frontend/src/api/types.ts`)은 대조용으로 읽기만 한다.
- **시작 조건(충족)**: docs/07 §7.2는 "3단계 통합 테스트(G1–G4)가 통과하기 전에는 4단계로 넘어가지 않는다"고 정한다. 2026-11-25 AWS 담당이 `haru-dev` 스택에서 AWS 통합 테스트 15건(T1·T13·T3·T4·T5·T6·T7·T14·T16, 가입 확인 포함)을 모두 통과시켰다(`backend/README.md` §1·§3.1). T3–T7이 AWS에서 통과했으므로 4단계 시작 조건은 충족됐다(Requirement 11.5).
- **로컬 환경**: docker compose 로컬 환경은 2026-11-25 첫 구동에 성공했고 `pytest -m local tests/local` 16건이 통과했다(`backend/README.md` §5.1). 4단계 로컬 통합 테스트도 이 환경에서 실행한다(Requirement 11.2). 로컬 결과는 T 시나리오 합격 근거가 아니다(BE-Q15).
- 문서에 없는 결정은 임시 기본안으로 적고 BE-Q 번호를 붙였다(마지막 "미결 사항"). 기존 질문은 docs/08 번호를 그대로 쓰고, 새 질문은 BE-Q42부터다.

## Glossary

- **Backend**: `backend/` 아래의 Python 3.12 Lambda 코드와 SAM 템플릿 전체.
- **Claim_Service**: `src/domain/claim_service.py`. 이어받기·포기·기록·완료 로직(3단계). 이번 단계에서 기록 조회를 더한다.
- **Inbox_Service**: `src/domain/inbox_service.py`(docs/02 §2.10). 수신함 목록·상세·읽음·답장·미확인 수 로직.
- **Claims_Function**: `/claims/*` 경로를 처리하는 Lambda(`handlers.claims.handler`).
- **Inbox_Function**: `/inbox*` 경로를 처리하는 Lambda(`handlers.inbox.handler`, docs/02 §2.3). 이번 단계에서 새로 만든다.
- **Me_Function**: `GET /me`, `GET /me/claims`를 처리하는 Lambda(`handlers.me.handler`).
- **Claim**: 한 번의 이어받기 시도. `PLAN#{planId}` / `CLAIM#{claimId}`. 상태 `ACTIVE`·`COMPLETED`·`ABANDONED`·`EXPIRED`.
- **Claim_Lookup**: `CLAIM#{claimId}` / `META`. `claimId`로 `planId`와 실행자(`claimerId`)를 찾는 항목.
- **Claimer**: Claim의 실행자. Claim_Lookup의 `claimerId`가 요청자 JWT `sub`와 같은 사용자.
- **Record**: Claim당 1개인 방문 기록. `PLAN#{planId}` / `RECORD#{claimId}`. 속성 `claimId`, `planId`, `authorId`, `letter`, `photoStatus`, `photoKey`, `processedKey`, `photoError`, `updatedAt`, `deliveredAt`.
- **Inbox_Item**: 계획자 수신함 항목. `USER#{ownerId}` / `INBOX#{claimId}`, `itemId = claimId`. 완료 트랜잭션(3단계)이 만들고 `reply` 속성은 생성 시 쓰지 않는다(§2.5).
- **Owner**: Inbox_Item의 `ownerId`(= 계획 소유자)가 요청자 JWT `sub`와 같은 사용자.
- **Planner**: Plan의 `ownerId`가 요청자 JWT `sub`와 같은 사용자(계획자). 그 Plan에서 생긴 Inbox_Item의 Owner이기도 하다.
- **Third_Party**: 해당 Plan의 Planner도 해당 Claim의 Claimer도 아닌 인증된 사용자(권한 없는 제3자).
- **Auth_Guard**: `src/common/auth.py`의 `get_user()`. JWT 클레임의 `token_use`가 `"id"`이고 `sub`가 비어 있지 않은 문자열일 때만 요청자를 돌려주고, 아니면 401 `UNAUTHORIZED`(계약 에러 형식)를 낸다.
- **Authorizer**: HTTP API의 기본 JWT authorizer(`CognitoJwt`). 토큰이 없거나 만료·서명 오류이면 Lambda를 부르지 않고 본문 `{"message":"Unauthorized"}`로 401을 낸다(docs/03 §3.6 401 행).
- **Reply**: Inbox_Item의 `reply` 속성 `{ text, sentAt }`. Inbox_Item당 최대 1개.
- **Unread_Inbox_Count**: 요청자의 Inbox_Item 중 `read = false`인 항목 수.
- **Allowlist**: 응답에 내보내도 되는 필드 이름의 허용 목록(BE-PLAN-08). `src/common/responses.py`의 직렬화 함수가 적용한다.
- **Transaction**: `common.ddb.transact_with_retry`로 실행하는 TransactWriteItems. 실패 처리는 docs/02 §2.6 공통 규칙(BE-REC-10).
- **Dev_Stack**: 실제 AWS에 SAM으로 배포한 `dev` 스택. T 시나리오의 합격 판정은 이 스택에서만 한다.
- **Local_Env**: docker compose 로컬 개발 환경(에뮬레이터, HTTP 어댑터). 조건식 로직 확인용이고 T 시나리오 판정에는 쓰지 않는다.

## Requirements

### Requirement 1: 방문 기록 저장 (글만, 3단계 구현 유지) [BE-REC-01, BE-REC-03, G3]

**User Story:** As a 실행자, I want 다녀온 이야기를 글로 저장하고 고쳐 쓰고 싶다, so that 완료하기 전까지 글을 다듬을 수 있다.

#### Acceptance Criteria

1. WHEN Claimer가 `PUT /claims/{claimId}/record { letter }`(1–1,000자)를 호출하고 Plan의 `currentClaimId = claimId`, Plan `status = CLAIMED`, Claim `status = ACTIVE`이면, THE Claim_Service SHALL 하나의 Transaction으로 Record의 `letter`와 `updatedAt`을 쓰고 200 `{ record, upload: null }`을 반환한다. [BE-REC-01, §3.4]
2. WHEN Record를 처음 만들면, THE Claim_Service SHALL `photoStatus`를 `NONE`으로 저장한다. WHEN 이미 있는 Record의 글을 덮어쓰면, THE Claim_Service SHALL 기존 `photoStatus`·`photoKey`를 바꾸지 않는다. [BE-REC-03]
3. IF Record에 `deliveredAt`이 있으면, THEN THE Claim_Service SHALL Record를 바꾸지 않고 409 `CLAIM_NOT_ACTIVE`로 응답한다. [BE-REC-01, 3단계 요구사항 3.2]
4. IF Claim_Lookup이 없으면, THEN THE Claim_Service SHALL 404 `NOT_FOUND`로 응답한다. IF 요청자가 Claimer가 아니면, THEN THE Claim_Service SHALL 403 `FORBIDDEN`으로 응답한다. [BE-REC-01, G5]
5. IF Claim이 `ACTIVE`가 아니거나 Plan의 `currentClaimId`가 `claimId`가 아니면, THEN THE Claim_Service SHALL 409 `CLAIM_NOT_ACTIVE`로 응답하고 EMF 지표 `StaleRequestRejected`를 1 기록한다. [BE-REC-01, BE-OBS-01, T6]
6. IF `letter`가 없거나 문자열이 아니거나 길이가 1–1,000자 밖이면, THEN THE Claims_Function SHALL 400 `VALIDATION_ERROR`(`details` 키 `letter`)로 응답한다. 앞뒤 공백은 자르지 않고 길이만 본다. [BE-REC-01, FE-Q19]
7. WHILE 사진 기능이 5단계 전이면, IF 요청 본문에 `photo`가 있으면, THEN THE Claims_Function SHALL 400 `VALIDATION_ERROR`(`details` 키 `photo`)로 응답한다. [BE-Q34]
8. THE 응답의 `record` SHALL Transaction 뒤 Record를 `ConsistentRead`로 다시 읽어 만든다. [3단계 요구사항 3.5]

### Requirement 2: 방문 기록 조회 [BE-REC-05]

**User Story:** As a 실행자, I want 저장한 글과 이어받기 상태를 다시 보고 싶다, so that 새로고침이나 다른 기기에서도 이어서 쓰고 종료 여부를 알 수 있다.

#### Acceptance Criteria

1. WHEN Claimer가 `GET /claims/{claimId}/record`를 호출하면, THE Claim_Service SHALL 200 `{ record, claimStatus, delivered, photoStatus }`를 반환한다. `claimStatus`는 Claim의 `status`, `delivered`는 Record에 `deliveredAt`이 있는지, `photoStatus`는 Record의 `photoStatus`다. [BE-REC-05, §3.4]
2. IF Record가 없으면, THEN THE Claim_Service SHALL 200 `{ record: null, claimStatus, delivered: false, photoStatus: "NONE" }`을 반환한다. [BE-REC-05]
3. WHILE Claim이 `ABANDONED`·`EXPIRED`·`COMPLETED`이면, THE Claim_Service SHALL Claimer에게 같은 형식의 200 응답을 반환한다. [BE-REC-05, §3.4]
4. IF Claim_Lookup 또는 Claim이 없으면, THEN THE Claim_Service SHALL 404 `NOT_FOUND`로 응답한다. [§3.6]
5. IF 요청자가 Claimer가 아니면, THEN THE Claim_Service SHALL 403 `FORBIDDEN`으로 응답하고 Record·Claim 내용을 담지 않는다. [BE-Q1, BE-NFR-02, T2]
6. THE Claim_Service SHALL Claim과 Record를 커밋된 최신 값으로 읽는다(강한 일관성 GetItem 또는 TransactGetItems). 완료·포기 직후의 조회가 이전 상태를 돌려주지 않게 하려는 것이다. [§2.6]
   - 알려진 한계: Claim과 Record를 서로 다른 GetItem 두 번으로 읽으면, 두 읽기 사이에 완료·포기·기록 갱신 Transaction이 끝날 수 있다. 이때 한 응답 안에서 `claimStatus`(Claim 기준)와 `delivered`·`photoStatus`·`record`(Record 기준)가 서로 다른 시점의 값이 된다. 예: `claimStatus = ACTIVE`인데 `delivered = true`, 또는 `claimStatus = COMPLETED`인데 `delivered = false`.
   - 읽기 방식은 design.md가 검토했고 BE-Q46으로 남아 있다. 권장안은 TransactGetItems 한 번으로 두 항목을 한 시점의 스냅샷으로 읽는 것이다(TransactGetItems에는 `ConsistentRead` 파라미터가 없지만 커밋된 최신 값을 읽는다). 대안 A는 `ConsistentRead` GetItem 두 번(불일치 허용)이다. 어느 쪽이든 각 필드의 값은 Requirement 2.1의 출처(Claim 또는 Record)에서만 가져온다.
   - 권장안의 503 `TRY_AGAIN`(충돌 재시도 소진)과 500 `INTERNAL_ERROR`(충돌 외 취소 사유) 응답은 docs/03 §3.4 계약 변경 승인(BE-Q46) 뒤 이 Requirement에 추가한다.
7. THE `record` SHALL 3단계 `serialize_record` Allowlist(`claimId`, `planId`, `letter`, `photoStatus`, `updatedAt`, `deliveredAt`)로 직렬화하고 `photoKey`·`processedKey`·`photoError`·`authorId`·키 속성을 내보내지 않는다. [§2.5, BE-PLAN-08]
8. THE Claim_Service SHALL 기록 조회에서 아무것도 쓰지 않는다.

### Requirement 3: 수신함 목록 [BE-INBOX-01]

**User Story:** As a 계획자, I want 돌아온 하루 목록을 보고 싶다, so that 새 편지와 읽은 기록을 구분해 확인할 수 있다.

#### Acceptance Criteria

1. WHEN 인증된 사용자가 `GET /inbox`를 호출하면, THE Inbox_Service SHALL `PK = USER#{요청자 sub}`, `SK` 접두사 `INBOX#`로 Query한 Inbox_Item을 `createdAt` 역순으로 정렬해 200 `{ items: [InboxItem] }`으로 반환한다. [BE-INBOX-01, §2.6, §3.5]
2. THE Inbox_Service SHALL Query 결과가 여러 페이지면(`LastEvaluatedKey`) 모든 페이지를 읽어 합친다. [§2.6 "Query 후 Lambda에서 정렬"]
3. WHEN 요청자의 Inbox_Item이 없으면, THE Inbox_Service SHALL 200 `{ items: [] }`를 반환한다.
4. THE Inbox_Service SHALL 요청자 외 사용자의 Inbox_Item을 목록에 넣지 않는다. 사용자 ID는 JWT `sub`에서만 읽는다. [BE-NFR-02, BE-AUTH-04, T2]
5. THE Inbox_Service SHALL Query로 읽은 각 Inbox_Item의 저장된 `ownerId`가 요청자 `sub`와 같은지 확인하고, 다른 항목은 목록에서 뺀다. 키 설계상 `USER#{sub}` 파티션에는 요청자의 항목만 있으므로 정상 경로에서는 빠지는 항목이 없다. 키와 속성이 어긋난 데이터가 남의 목록에 노출되지 않게 하는 방어다. [§2.8 "모든 판단은 JWT `sub`와 저장된 `ownerId` 비교", T2]

### Requirement 4: 돌아온 하루 상세 [BE-INBOX-02]

**User Story:** As a 계획자, I want 내 계획과 실행자의 방문 기록을 나란히 보고 싶다, so that 이어받은 사람이 다녀온 이야기를 읽을 수 있다.

#### Acceptance Criteria

1. WHEN Owner가 `GET /inbox/{itemId}`를 호출하면, THE Inbox_Service SHALL 200 `{ item, plan, record: { letter, deliveredAt, photoUrl, photoCaption } }`을 반환한다. [BE-INBOX-02, §3.5]
2. THE Inbox_Service SHALL Inbox_Item을 키 `USER#{요청자 sub}` / `INBOX#{itemId}`로 `ConsistentRead` 조회한다. [BE-INBOX-02, §2.6]
3. IF 조회한 Inbox_Item이 없거나, 저장된 Inbox_Item의 `ownerId`가 요청자 `sub`와 다르면, THEN THE Inbox_Service SHALL 404 `NOT_FOUND`로 응답하고 `item`·`plan`·`record` 내용을 담지 않는다. 남의 항목과 없는 항목은 같은 응답이다. [BE-INBOX-02, §3.5 "`ownerId = 요청자`만 조회 가능. 아니면 404", §2.8, T2]
4. THE `plan` SHALL Inbox_Item의 `planId`로 읽은 Plan을 1·2단계 `serialize_plan`(요청자가 소유자이므로 `metrics` 포함)으로 직렬화한다. [BE-PLAN-08, §2.5]
5. THE `record.letter`와 `record.deliveredAt` SHALL `PLAN#{planId}` / `RECORD#{itemId}` Record에서 읽는다. [§2.8 Record 읽기 권한 "전달 후 계획 소유자"]
6. WHILE 사진 기능이 5단계 전이면, THE Inbox_Service SHALL `record.photoUrl`과 `record.photoCaption`을 `null`로 반환한다. [BE-Q42, docs/07 §7.3 5단계 "`GET /inbox/{itemId}`의 `photoUrl`(15분), `photoCaption`"]
7. THE Inbox_Service SHALL 상세 조회에서 `read`를 바꾸지 않는다. 읽음 처리는 `POST /inbox/{itemId}/read`로만 한다. [§3.5]
8. IF Inbox_Item은 있는데 Plan 또는 Record가 없으면, THEN THE Inbox_Service SHALL 500 `INTERNAL_ERROR`로 응답하고 로그에 예외 유형만 남긴다. 완료 Transaction이 넷을 함께 쓰므로 정상 경로에서는 생기지 않는다. [G4, BE-Q23]

### Requirement 5: 읽음 처리 [BE-INBOX-03]

**User Story:** As a 계획자, I want 돌아온 하루를 열면 읽음으로 표시되길 원한다, so that 미확인 표시와 헤더 배지가 사라진다.

#### Acceptance Criteria

1. WHEN Owner가 `POST /inbox/{itemId}/read`를 호출하면, THE Inbox_Service SHALL 키 `USER#{요청자 sub}` / `INBOX#{itemId}`의 Inbox_Item에 조건 `attribute_exists(PK) AND ownerId = :me`(`:me` = 요청자 `sub`)로 `read = true`를 쓰고 본문 없이 204를 반환한다. 존재 확인과 소유자 확인은 이 조건부 갱신 한 번으로 원자적으로 한다(먼저 읽고 나중에 쓰는 방식으로 판정하지 않는다). [BE-INBOX-03, §3.5, §2.8]
2. IF 조건이 실패하면(항목 없음 또는 저장된 `ownerId`가 요청자 `sub`와 다름), THEN THE Inbox_Service SHALL 404 `NOT_FOUND`로 응답하고 아무 항목도 만들거나 바꾸지 않는다. [§3.5, T2]
3. WHEN 이미 `read = true`인 Inbox_Item에 읽음 요청이 오면, THE Inbox_Service SHALL 204를 반환하고 `read = true`를 유지한다. [BE-Q44]
4. THE Inbox_Service SHALL 읽음 처리에서 `read` 외의 속성(`reply` 포함)을 바꾸지 않는다.

### Requirement 6: 한 줄 답장 [BE-INBOX-04, T17]

**User Story:** As a 계획자, I want 돌아온 하루에 한 줄 답장을 한 번 남기고 싶다, so that 다녀온 사람에게 고마움을 전할 수 있다.

#### Acceptance Criteria

1. WHEN Owner가 `POST /inbox/{itemId}/reply { text }`(1–100자)를 호출하면, THE Inbox_Service SHALL 키 `USER#{요청자 sub}` / `INBOX#{itemId}`의 Inbox_Item에 조건 `ownerId = :me AND attribute_not_exists(reply)`(`:me` = 요청자 `sub`)로 `reply = { text, sentAt }`을 쓰고 201 `{ reply: { text, sentAt } }`을 반환한다. 소유자 확인과 중복 확인은 이 조건부 갱신 한 번으로 원자적으로 한다. 항목이 없으면 `ownerId = :me`가 거짓이므로 같은 조건이 존재 확인도 겸한다. [BE-INBOX-04, §3.5, §2.8]
2. IF 조건이 실패하면, THEN THE Inbox_Service SHALL Inbox_Item을 `ConsistentRead`로 다시 읽어, 항목이 없거나 저장된 `ownerId`가 요청자 `sub`와 다르면 404 `NOT_FOUND`, Owner의 항목에 `reply`가 있으면 409 `REPLY_ALREADY_SENT`로 응답한다. 404 응답은 남의 항목에 답장이 있는지를 드러내지 않는다. [BE-INBOX-04, §3.6, T2]
3. WHEN 같은 Inbox_Item에 답장이 여러 번(동시 포함) 들어오면, THE Inbox_Service SHALL 정확히 한 요청만 201로 저장하고 나머지에 409 `REPLY_ALREADY_SENT`를 반환하며, 저장된 `reply`는 201을 받은 요청의 값이다. [T17]
4. IF `text`가 없거나 문자열이 아니거나 길이가 1–100자 밖이면, THEN THE Inbox_Function SHALL 아무것도 쓰지 않고 400 `VALIDATION_ERROR`(`details` 키 `text`)로 응답한다. 앞뒤 공백은 자르지 않고 길이만 본다. [§3.5, FE-Q19]
5. THE `sentAt` SHALL `iso_utc`(밀리초 고정 UTC) 문자열이다. [docs/03 공통 규칙]
6. THE Inbox_Service SHALL 답장 저장에서 `reply` 외의 속성을 바꾸지 않는다.

### Requirement 7: 수신함 직렬화 [§2.5, BE-PLAN-08]

**User Story:** As a 프론트엔드 개발 담당, I want 수신함 응답이 계약과 같은 필드만 담기를 원한다, so that MSW 목업과 실제 API가 같은 타입으로 동작하고 내부 속성이 노출되지 않는다.

#### Acceptance Criteria

1. THE InboxItem 응답 SHALL Allowlist `itemId`, `planId`, `planTitle`, `claimerNickname`, `hasPhoto`, `read`, `createdAt`, `reply`만 담고 `PK`·`SK`·`ownerId`를 내보내지 않는다. [§2.5, BE-PLAN-08, BE-Q43]
2. IF 저장된 Inbox_Item에 `reply` 속성이 없으면, THEN THE InboxItem 응답 SHALL `reply: null`을 담는다. IF `reply`가 있으면, THEN THE InboxItem 응답 SHALL `reply: { text, sentAt }`만 담는다. [§2.5, BE-INBOX-04]
3. IF 저장된 Inbox_Item에 `claimerNickname`이 없으면(ID 토큰에 `nickname` 클레임이 없던 경우), THEN THE InboxItem 응답 SHALL `claimerNickname: null`을 담는다. 프론트 타입(`claimerNickname: string`)과의 불일치는 미결이다. [BE-Q17, BE-Q45]
4. THE `hasPhoto`와 `read` SHALL JSON 불리언으로 내보낸다.
5. FOR ALL 저장 가능한 Inbox_Item, THE InboxItem 직렬화 결과 SHALL Allowlist 밖의 키를 담지 않고, 직렬화 결과를 JSON으로 인코딩한 뒤 디코딩해도 같은 값이다(직렬화 round-trip).

### Requirement 8: 내 정보의 미확인 수 [BE-AUTH-05]

**User Story:** As a 계획자, I want 헤더에서 읽지 않은 돌아온 하루가 있는지 보고 싶다, so that 수신함을 열어야 할 때를 알 수 있다.

#### Acceptance Criteria

1. WHEN 인증된 사용자가 `GET /me`를 호출하면, THE Me_Function SHALL 200 `{ userId, nickname, unreadInboxCount }`를 반환하고 `unreadInboxCount`는 요청자의 Unread_Inbox_Count다. [BE-AUTH-05, §3.1]
2. THE Unread_Inbox_Count SHALL `PK = USER#{요청자 sub}`, `SK` 접두사 `INBOX#`인 항목 중 `read = false`인 항목 수이고, 결과가 여러 페이지면 모든 페이지를 센다. [§2.6]
3. THE Me_Function SHALL Unread_Inbox_Count를 HaruTable 기본 테이블 Query에 `ConsistentRead=True`를 지정해 계산한다. docs/02 §2.6에서 Inbox_Item의 키는 기본 테이블의 `USER#{ownerId}` / `INBOX#{claimId}`이고 GSI 속성이 없으므로, 이 조회는 GSI를 쓰지 않고 강한 일관성 읽기가 가능하다. 완료 Transaction 직후나 읽음 처리 직후의 `GET /me`가 이전 값을 돌려주지 않게 하려는 것이다. [§2.6, FE-COM-02]
4. WHEN `POST /inbox/{itemId}/read`가 204를 반환한 뒤 같은 사용자가 `GET /me`를 호출하면, THE Me_Function SHALL 그 항목을 Unread_Inbox_Count에서 뺀다. [§3.5, FE-INB-02]
5. THE `userId`와 `nickname` SHALL 1·2단계와 같이 JWT `sub`와 ID 토큰 `nickname` 클레임에서 읽는다. `nickname` 클레임이 없을 때의 응답은 BE-Q17 결과를 따른다. [BE-AUTH-04, BE-Q30 뒷부분]
6. THE Me_Function SHALL `GET /me/claims`의 3단계 동작을 바꾸지 않는다. [BE-CLAIM-07]
7. THE Me_Function SHALL 요청자의 Inbox_Item만 센다. Query로 읽은 항목 중 저장된 `ownerId`가 요청자 `sub`와 다른 항목은 세지 않는다(Requirement 3.5와 같은 방어). [§2.8]

### Requirement 9: 라우트·템플릿·IAM [docs/02 §2.3, BE-INFRA-06]

**User Story:** As a AWS 담당, I want 새 경로와 함수 권한이 템플릿에 최소 권한으로 정의되길 원한다, so that 배포 후 바로 판정할 수 있고 함수가 필요 이상의 데이터에 쓰지 못한다.

#### Acceptance Criteria

1. THE Backend SHALL `src/handlers/routes.py`에 `GET /claims/{claimId}/record`(Claims_Function), `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply`(Inbox_Function)를 추가하고, `template.yaml`의 HttpApi 이벤트와 로컬 어댑터 경로가 이 목록과 일치한다. [docs/02 §2.3, 1·2단계 요구사항 13.9]
2. THE Inbox_Function SHALL `HaruTable`에 `dynamodb:GetItem`, `dynamodb:Query`, `dynamodb:UpdateItem`만 갖는다. GSI는 쓰지 않으므로 `index/*` 권한을 두지 않는다. [BE-INFRA-06]
3. THE Claims_Function SHALL 3단계 권한(`GetItem`, `PutItem`, `UpdateItem`, `ConditionCheckItem`)을 그대로 유지한다. `GET /claims/{claimId}/record`는 `GetItem`만 쓴다. [BE-INFRA-06]
4. THE Me_Function SHALL 3단계 권한(`HaruTable`과 `index/*`에 `GetItem`, `Query`)을 그대로 유지한다. `unreadInboxCount`는 테이블 `Query`로 계산한다. [BE-INFRA-06, BE-Q30]
5. THE 새 경로 SHALL 1단계 HttpApi의 기본 Authorizer(`CognitoJwt`)로 보호된다. 토큰이 없거나 만료·서명 오류이면 401이다. [BE-AUTH-03, T1]
6. THE 새 경로의 핸들러(`GET /claims/{claimId}/record`, `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply`)와 `GET /me` SHALL 요청자를 Auth_Guard로만 얻는다. IF JWT 클레임의 `token_use`가 `"id"`가 아니면(Cognito 액세스 토큰 등), THEN THE Auth_Guard SHALL DB를 읽거나 쓰기 전에 401 `UNAUTHORIZED`로 응답한다. Auth_Guard의 검사 내용(`token_use == "id"`, 비어 있지 않은 `sub`)은 바꾸지 않는다. [BE-AUTH-04, docs/02 §2.4, docs/03 §3.6 401 행, 커밋 `2d98ac8`]
7. THE 의존성 SHALL 1–3단계와 같다(LangGraph·LangChain·Pillow 없음). [1·2단계 요구사항 12.9]
8. THE Backend SHALL `sam validate --lint`와 `sam build`를 통과한다. `sam deploy`는 이번 작업에서 실행하지 않는다.

### Requirement 10: 계약·데이터 설계·정합성 유지 (회귀)

**User Story:** As a 개발 담당, I want 4단계를 더해도 기존 계약과 트랜잭션 보장이 그대로이길 원한다, so that 3단계에서 증명한 G1–G4와 프론트 목업 계약이 깨지지 않는다.

#### Acceptance Criteria

1. THE Backend SHALL docs/03 §3.1·§3.4·§3.5의 요청·응답 필드 이름, HTTP 상태, 에러 코드를 바꾸지 않는다. Lambda 핸들러가 내는 에러 본문은 `{ "error": { "code", "message", "details"? } }`이고 `details`는 `VALIDATION_ERROR`에서만 담는다. Auth_Guard가 내는 401 `UNAUTHORIZED`(`token_use` 불일치, `sub` 없음)도 이 형식을 따른다. [BE-NFR-05, BE-NFR-07]
   - 예외: Authorizer가 거부한 401(토큰 없음·만료·서명 오류)은 Lambda를 거치지 않으므로 본문이 `{"message":"Unauthorized"}`이고 이 형식이 아니다. Backend는 이 본문을 바꾸지 않으며, 테스트는 이 경우 상태 코드 401만 확인한다. [docs/03 §3.6 401 행, `backend/README.md` §4 1항]
2. THE Backend SHALL `src/common/errors.py`에 `REPLY_ALREADY_SENT`(409)를 docs/03 §3.6과 같은 상태 코드로 추가하고, 기존 코드와 상태의 조합은 바꾸지 않는다. [§3.6]
3. THE Backend SHALL docs/02 §2.6의 키 설계(Plan, Claim, Record, Claim_Lookup, Inbox_Item의 PK·SK, GSI1·GSI2)를 바꾸지 않고 새 테이블·GSI를 만들지 않는다. [§2.6]
4. THE Claim_Service SHALL 이어받기·포기·완료 Transaction(`claim_plan`, `abandon`, `complete_claim`, `complete_by_user`)의 조건식, 갱신식, 실패 분기를 바꾸지 않는다. [G1–G4, BE-REC-06–10]
5. WHEN 같은 Claim에 `POST /claims/{claimId}/complete`가 여러 번 들어오면, THE Claim_Service SHALL 3단계와 같이 Inbox_Item과 Record 전달을 1건만 남기고 모두 200을 반환한다. 4단계 수신함 API로 확인한 Inbox_Item 수도 1건이다. [G2, T5]
6. WHEN 포기된 Claim의 `claimId`로 기록 저장·완료를 요청하면, THE Claim_Service SHALL 409 `CLAIM_NOT_ACTIVE`로 응답하고, 계획자의 `GET /inbox`에 그 Claim의 Inbox_Item이 나타나지 않는다. [G3, T6]
7. THE 읽음·답장 쓰기 SHALL Inbox_Item 한 항목의 조건부 갱신이고, Plan·Claim·Record를 바꾸지 않는다. [G4]
8. THE 로그와 EMF 지표 SHALL 사용자 ID, 글·답장 본문, 토큰을 담지 않는다. [BE-NFR-03]

### Requirement 11: 테스트와 완료 기준

**User Story:** As a 개발 담당, I want 4단계의 테스트와 인계 기준이 정해져 있길 원한다, so that AWS 담당이 T2·T17을 판정하고 프론트가 S2에서 실제 API로 전환할 수 있다.

#### Acceptance Criteria

1. WHEN 단위 테스트(`pytest tests/unit`)를 실행하면, THE Backend SHALL 다음을 실패 0건으로 통과한다: moto 대상 기록 조회 분기(실행자·남·없음·기록 없음·종료된 Claim), 수신함 목록 정렬·빈 목록·남의 항목 제외(키와 `ownerId`가 어긋난 항목 포함), 상세 404(없음·`ownerId` 불일치)·사진 필드 `null`, 읽음 204·404(없음·`ownerId` 불일치)·재요청, 답장 201·409·404(없음·`ownerId` 불일치)·검증, `unreadInboxCount` 계산(`ConsistentRead=True` 지정 포함)과 읽음 후 감소, 직렬화 Allowlist와 round-trip 속성 테스트, 기록 조회 스냅샷 읽기 헬퍼(`transact_get_with_retry`)의 재시도 테스트(moto가 `TransactionConflict`를 재현하지 못하므로 botocore Stubber·가짜 클라이언트·moto 위 monkeypatch로 주입: 재시도 횟수(최초 1회 + 재시도 최대 3회), 대기 시간 범위(회차별 `[cap/2, cap]`, 재시도 3회 누적 175–350ms), 실패 사유별 처리(`TransactionConflict`만이면 재시도, 다른 사유가 섞이거나 다른 사유만이면 재시도 없이 500), 재시도 소진 시 503 `TRY_AGAIN`, GetItem 폴백 없음), design.md의 Property 16–24 속성 기반 테스트(필수), 핸들러·라우트·템플릿 테스트, 새 핸들러에 `token_use`가 `"id"`가 아닌 이벤트를 넣으면 DB 호출 없이 401 `UNAUTHORIZED`(계약 에러 형식)인지 확인하는 테스트, 1–3단계 기존 단위 테스트 전체(회귀, `tests/unit/test_auth.py`·`tests/unit/test_integration_cleanup.py` 포함).
2. THE Backend SHALL `tests/local/`에 Local_Env 대상 테스트를 두어 이어받기 → 글 저장 → `GET /record` → 완료 → 계획자 `GET /me` 미확인 1 → `GET /inbox` → 상세 → 읽음 → 미확인 0 → 답장 201 → 두 번째 답장 409 흐름을 확인한다. [`backend/README.md` §5.1·§5.3]
   - 4단계 완료 조건: `docker compose up -d --build`로 띄운 Local_Env에서 `pytest -m local tests/local`을 실행해 기존 16건과 4단계 추가분이 모두 통과한다. 실행 결과(건수, 날짜, 기준 커밋)를 `backend/README.md` §5에 적는다.
   - 이 결과는 조건식·흐름 확인용이고 T 시나리오(T2·T17 포함)의 합격 근거가 아니다. 합격 판정은 Dev_Stack에서만 한다. [BE-Q15, docs/07 §7.5]
3. THE Backend SHALL AWS 스택 대상 테스트를 제공한다. 실행·판정은 AWS 담당이 한다. [docs/07 §7.5·§7.6]
   - `tests/integration/test_authz.py`에 T2: 아래 "T2 역할별 기대 결과" 표의 각 칸을 확인한다.
   - `tests/integration/test_inbox.py`에 T17: 첫 답장 201, 두 번째 답장 409 `REPLY_ALREADY_SENT`, 동시 답장에서 201 정확히 1건.
   - `tests/integration/test_concurrency.py`에 `GET /claims/{claimId}/record` 스냅샷 읽기 검증(BE-Q46 묶음): 같은 Claim에 기록 저장·완료를 보내는 동안 실행자가 `GET /record`를 반복 호출한다. 합격 기준은 응답 정합성이다. `GET /record`는 200 또는 503 `TRY_AGAIN`뿐이고, 200마다 `claimStatus = COMPLETED ⇔ delivered`이며, 쓰기 응답은 계약 코드뿐이고, 끝난 뒤 InboxItem 1건·Record 전달·Plan `COMPLETED`다. 충돌·재시도·503이 실제로 일어나는 것은 합격 조건이 아니며 발생 수는 기록만 한다. `ClaimsFunction` 설정(`Timeout` 등)과 요청별 소요 시간 최대값도 기록한다(BE-Q48).
   - T2 테스트는 docs/07 §7.6 T2("사용자 B가 사용자 A의 수신함/Record/Claim 접근 → 404 또는 403, 데이터 노출 없음")를 다음 세 역할로 나눠 확인한다. 준비: Planner(A)가 Plan을 만들고 Claimer(C)가 이어받는다. Claim 경로는 Claim이 `ACTIVE`일 때 Planner·Third_Party(B)로 먼저 확인하고, 그 뒤 C가 글을 저장하고 완료해 Inbox_Item을 만든 다음 수신함 경로를 확인한다. [T2, §2.8, §3.4, §3.5, BE-Q1]

   T2 역할별 기대 결과

   | 경로 | Planner(A, Plan·Inbox_Item 소유자) | Claimer(C) | Third_Party(B) |
   |---|---|---|---|
   | `GET /claims/{claimId}/record` | 403 `FORBIDDEN` | 200 | 403 `FORBIDDEN` |
   | `PUT /claims/{claimId}/record` | 403 `FORBIDDEN` | 200 (Claim `ACTIVE`) | 403 `FORBIDDEN` |
   | `POST /claims/{claimId}/abandon` | 403 `FORBIDDEN` | 200 (Claim `ACTIVE`, 별도 Claim으로 확인) | 403 `FORBIDDEN` |
   | `POST /claims/{claimId}/complete` | 403 `FORBIDDEN` | 200 | 403 `FORBIDDEN` |
   | `GET /inbox` | 200, 해당 Inbox_Item 포함 | 200, A의 Inbox_Item 없음 | 200, A의 Inbox_Item 없음 |
   | `GET /inbox/{itemId}` | 200 | 404 `NOT_FOUND` | 404 `NOT_FOUND` |
   | `POST /inbox/{itemId}/read` | 204 | 404 `NOT_FOUND` | 404 `NOT_FOUND` |
   | `POST /inbox/{itemId}/reply` | 201 | 404 `NOT_FOUND` | 404 `NOT_FOUND` |
   | `GET /me` | 200, A의 미확인 Inbox_Item을 셈 | 200, A의 Inbox_Item을 세지 않음 | 200, A의 Inbox_Item을 세지 않음 |

   - Planner가 `GET /claims/{claimId}/record`에서 403인 근거는 docs/03 §3.4 "요청자 = claimer만 조회 가능"과 BE-Q1이다. Planner는 전달된 기록을 `GET /inbox/{itemId}`로 읽는다(docs/02 §2.8 "전달 후 계획 소유자").
   - Claimer는 `itemId`(= `claimId`)를 알고 있으므로 Claimer의 수신함 경로 404를 반드시 확인한다.
   - 없는 `claimId`·`itemId`는 모든 역할에서 404 `NOT_FOUND`다.
   - 403·404 응답 본문은 에러 형식만 담고, A의 `letter`·`reply.text`·Plan 필드, C의 글을 담지 않는다.
   - Planner·Third_Party의 403 요청 뒤 Claim `status`, Record `letter`·`deliveredAt`이 바뀌지 않았는지 확인한다. Claimer·Third_Party의 404 요청 뒤 Inbox_Item의 `read`·`reply`가 바뀌지 않았는지 확인한다(조회는 BE-Q38과 같이 DynamoDB `ConsistentRead`).
4. THE 통합 테스트 정리(`tests/integration/conftest.py`의 `_cleanup`) SHALL 3단계 보완(커밋 `33cba6b`, `backend/README.md` §3.2) 로직을 그대로 재사용하고, 4단계 테스트가 만든 데이터도 같은 방식으로 지운다. [3단계 요구사항 9.2, `backend/README.md` §3.2]
   - 정리 대상: Cognito 사용자(`created_users`), `PLAN#{planId}` 파티션 전체(Plan·Claim·Record)와 그 안의 Claim마다 짝인 Claim_Lookup(`CLAIM#{claimId}` / `META`), 테스트 사용자마다 `USER#{sub}` 파티션 전체(Inbox_Item. `reply`는 Inbox_Item의 속성이므로 항목과 함께 지워진다), 멱등 키 `IDEM#{sub}#{key}` / `META`(`created_idem_pks`).
   - 등록 방식: 테스트가 등록한 대상만 지운다(테이블 스캔·일괄 삭제 없음). 4단계 테스트는 계획을 `create_plan`으로 만들거나 `POST /plans` 요청 **전에** `register_idem_key`로 멱등 키를 등록하고, 사용자는 `create_user`로 만든다(`created_subs`에 `sub`가 등록되어 수신함 파티션이 정리된다). `create_user`를 거치지 않는 사용자는 직접 `created_users`에 등록한다(T1 액세스 토큰 테스트가 이미 그렇게 한다). 그 사용자가 DB에 항목을 만들면 `created_subs`에도 `sub`를 등록한다.
   - 실패 처리: 대상마다 따로 시도해 하나가 실패해도 나머지를 계속한다. 실패는 삼키지 않고 `test-results/cleanup-failures-*.json`(종류, 대상, 오류 코드)에 남긴 뒤 세션 teardown에서 `RuntimeError`로 알린다. `UserNotFoundException`은 이미 정리된 것으로 본다. 정리용 클라이언트는 adaptive 재시도 10회로 스로틀을 흡수한다. 파티션 조회는 `ConsistentRead`와 `LastEvaluatedKey` 페이지 이어 읽기를 쓴다.
   - 이 로직을 바꾸면 `tests/unit/test_integration_cleanup.py` 회귀 테스트를 함께 고치고 통과시킨다.
5. THE 4단계 시작 조건 SHALL 충족된 것으로 기록한다: 2026-11-25 Dev_Stack(`haru-dev`)에서 AWS 통합 테스트 15건(T1 3건, T13 3건, 가입 확인 2건, T3·T4·T5·T14, T6·T7·T16)이 통과했고, 이로써 docs/07 §7.2의 조건(T3–T7 AWS 통과)이 충족됐다. 4단계 이후 PR마다 `test_concurrency.py`를 다시 돌린다는 docs/07 §7.2 규칙을 `backend/README.md` 인계 문서에 적는다. [docs/07 §7.2, `backend/README.md` §1·§3.1]
6. THE `backend/README.md` SHALL 4단계 판정 실행표(T2 역할별 표, T17, 액세스 토큰 경로를 넓힌 T1), 함수별 IAM 표(Inbox_Function 추가, Me_Function의 `GET /me` DB 읽기 반영), 미결 질문(BE-Q1, BE-Q42–BE-Q48), S2 연동에 넘길 경로 목록, 4단계 로컬 통합 테스트 결과를 담는다. [docs/07 §7.8]
7. THE `docs/08-open-questions.md` SHALL BE-Q42–BE-Q48을 추가하고, BE-Q30의 앞부분("4단계 전 `unreadInboxCount` 0 고정")은 이번 단계에서 BE-AUTH-05대로 계산하므로 해소로 정리하며, 뒷부분(`nickname` 클레임이 없을 때)은 BE-Q17에 남긴다. [docs/08 머리말 "결정하면 해당 명세를 고치고 이 문서에서 지운다"]
8. THE T1 회귀 테스트 SHALL 새 경로를 포함한다. [T1, docs/03 §3.6 401 행, `backend/README.md` §3.1]
   - 토큰 없음·잘못된 토큰: `test_all_routes_reject_missing_or_bad_tokens`가 `handlers.routes.ROUTES` 전체를 돈다. 새 경로 5개를 `ROUTES`에 넣으면 같은 테스트가 새 경로에서 401을 확인한다. 이 경우 본문은 Authorizer 형식이므로 상태 코드만 본다.
   - 액세스 토큰: `test_access_token_is_rejected`가 지금은 `GET /me`만 확인한다. Cognito 액세스 토큰으로 `GET /claims/{claimId}/record`, `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply`를 호출해 모두 401 `UNAUTHORIZED`(계약 에러 형식)인지 확인하도록 넓힌다. Auth_Guard가 DB 조회 전에 거부하므로 경로의 ID는 없는 값이어도 된다.

## 미결 사항

`docs/08-open-questions.md` §8.1에 추가하거나 기존 번호를 적용한다. 임시 결정은 구현에 쓰고, 팀 결정이 다르면 해당 기준을 고친다.

| # | 내용 | 임시 결정 |
|---|---|---|
| BE-Q1 (기존) | `GET /claims/{claimId}/record`를 실행자가 아닌 사람이 호출할 때의 코드 | docs/08 제안대로 403 `FORBIDDEN`(Requirement 2.5). 프론트는 403·404·409를 모두 "종료된 이어받기"로 처리한다 |
| BE-Q17 (기존) | ID 토큰에 `nickname` 클레임이 없을 때 | 바꾸지 않는다. Inbox_Item의 `claimerNickname`이 없으면 응답 `null`(Requirement 7.3). 프론트 타입과의 불일치는 BE-Q45 |
| BE-Q23 (기존) | 예기치 못한 서버 오류 코드 | `INTERNAL_ERROR` 임시 사용을 유지한다(Requirement 4.8) |
| BE-Q30 (기존) | 4단계 전 `unreadInboxCount` 0 고정 | 이번 단계에서 BE-AUTH-05대로 계산하므로 앞부분은 해소한다. 닉네임 부분은 BE-Q17로 남긴다(Requirement 11.7) |
| BE-Q34 (기존) | 4단계에서도 `PUT /record`에 `photo`가 오면 | 5단계 전까지 400 `VALIDATION_ERROR`(`details.photo`)를 유지한다(Requirement 1.7). docs/08은 "5단계에서 계약대로 구현할 때까지만"이라 적었으므로 4단계에도 그대로 적용된다 |
| BE-Q42 (신규) | 4단계 `GET /inbox/{itemId}`의 `photoUrl`·`photoCaption`. docs/07은 둘을 5단계 작업으로 두고, 4단계에는 사진과 함께 완료(`WITH_PHOTO`)하는 경로가 없어 `hasPhoto = true` 항목이 생기지 않는다 | 4단계는 둘 다 `null`. 5단계에서 §3.5대로(15분 presigned GET, 마지막 장소 이름 + "에서") 구현한다 |
| BE-Q43 (신규) | InboxItem 응답의 필드 목록. §2.5는 저장 속성으로 `ownerId`를 적었고, 프론트 `types.ts`의 `InboxItem`에는 `ownerId`가 없다 | 응답에 `ownerId`를 내보내지 않는다(요청자 본인이고, BE-PLAN-08 허용 목록 원칙). 내보내기로 하면 §3.5에 필드를 적고 프론트 타입을 함께 고친다 |
| BE-Q44 (신규) | 이미 읽은 항목에 `POST /inbox/{itemId}/read`가 다시 올 때. §3.5는 "204, `read = true`"만 적었다 | 204(멱등). 프론트는 `read === false`일 때만 보내지만 재전송·두 탭에서 409를 주지 않는다 |
| BE-Q45 (신규) | InboxItem 응답의 `claimerNickname`이 `null`일 수 있는데 프론트 타입은 `null`을 허용하지 않는다. 완료 Transaction(3단계 `claim_service.py`)은 Claim에 `claimerNickname`이 있을 때만 Inbox_Item에 쓰고, Claim은 이어받기 때 ID 토큰 `nickname` 클레임이 있을 때만 그 값을 저장한다. 그래서 클레임이 없던 경우 응답은 `claimerNickname: null`이다(BE-Q17 임시 기본값, Requirement 7.3). 프론트 `frontend/src/api/types.ts`(`feat/fe-4-record-inbox` 트리)의 선언은 `export interface InboxItem { … claimerNickname: string; … }`이다. docs/03 §3.5는 InboxItem 필드의 null 허용 여부를 적지 않았고, docs/08에 대응하는 FE-Q 항목은 없다 | 계약(docs/03)과 프론트 타입은 이번 작업에서 바꾸지 않는다. 백엔드는 Requirement 7.3대로 `null`을 내보낸다. 2026-11-25 AWS·Floci 실측에서는 ID 토큰에 `nickname`이 있어(BE-Q17) 정상 경로에서는 `null`이 나오지 않는다. 프론트가 `string | null`로 바꿀지, 백엔드가 빈 문자열 등 기본값을 넣을지는 팀이 정한다. 정하면 docs/03 §3.5에 적고 프론트 담당 리뷰를 받는다(docs/07 §7.2). 같은 성격의 필드(`Me.nickname`, `UserRef.nickname`, `PlanSummary.ownerNickname`)도 프론트 타입은 `string`이다. docs/08에 추가할 때 FE 쪽 질문 번호를 함께 만들지 프론트 담당과 정한다 |
| BE-Q46–BE-Q48 (신규, design.md) | `GET /record` 읽기 방식과 503 `TRY_AGAIN`(BE-Q46), 정상 경로에 없는 상태의 500(BE-Q47), botocore `Config`와 Lambda 타임아웃(BE-Q48) | design.md "미결 사항"의 임시 결정을 따른다. BE-Q46은 계약 변경 승인 대기다 |
