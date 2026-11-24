# Requirements Document

## Introduction

이 문서는 백엔드 1단계(SAM 골격, 인증, 단일 테이블, 로컬 환경, `GET /me`)와 2단계(계획 생성·목록·상세, 멱등 키, `find_not_in_source`, `privacy.py`)의 요구사항이다. 기준은 `docs/06-requirements.md`의 BE-* 요구사항, `docs/03-api-contract.md` §3.1·§3.3, `docs/07-development-plan.md` §7.3 1·2단계이며, 기존 `design.md`에서 도출했다.

- 범위 밖(3단계 이후): 이어받기·포기·완료 트랜잭션, 방문 기록, 사진 파이프라인, 수신함·답장, `/ai/card-sessions*`, LangGraph 에이전트, CloudFront·웹 버킷, 알람·대시보드, `seed.py`·`report.py`. 이 단계는 보장 G5(권한 검사)의 일부만 다루고 G1–G4는 3단계에서 증명한다.
- 문서에 없는 결정은 새로 만들지 않는다. 임시 기본안으로 구현하는 항목은 각 기준에 BE-Q* 번호를 달고 마지막 "미결 사항"에 모았다.
- 각 기준 뒤의 `[BE-*]`는 `docs/06-requirements.md`의 원 요구사항 ID다.

## Glossary

- **Backend**: `backend/` 아래의 Python 3.12 Lambda 코드와 SAM 템플릿 전체.
- **Api**: JWT authorizer가 붙은 API Gateway HTTP API(스테이지 `$default`).
- **Authorizer**: Cognito User Pool ID 토큰을 검증하는 HTTP API JWT authorizer. audience는 User Pool App Client ID다.
- **UserPool**: 이메일을 사용자 이름으로 쓰는 Cognito User Pool.
- **PreSignUp_Function**: Cognito PreSignUp 트리거 Lambda(`pre_signup.py`).
- **Me_Function**: `GET /me`를 처리하는 Lambda.
- **Plans_Function**: `POST /plans`, `GET /plans`, `GET /plans/{planId}`를 처리하는 Lambda.
- **Plan_Service**: `plan_service.py`. 계획 생성·목록·상세 로직.
- **Fidelity_Checker**: `fidelity.py`의 `find_not_in_source`.
- **Privacy_Scanner**: `privacy.py`의 `scan_privacy`와 `mask`.
- **Validator**: `validation.py`의 pydantic 모델과 `to_details`.
- **Serializer**: `responses.py`의 `serialize_plan`, `serialize_plan_summary`, `serialize_claim`.
- **Error_Handler**: 핸들러 공통의 에러 응답 변환 로직(`errors.py`, `responses.py`).
- **HaruTable**: 단일 DynamoDB 테이블(PK/SK, GSI1, GSI2, TTL 속성 `ttl`).
- **Idempotency_Key_Item**: `IDEM#{userId}#{key}` / `META` 항목. TTL 24시간.
- **Local_Env**: docker compose로 뜨는 로컬 개발 환경(에뮬레이터 `aws`, HTTP 어댑터 `api`, init 스크립트).
- **Local_Adapter**: 로컬 HTTP 어댑터. payload 2.0 이벤트 변환과 JWT 검증을 한다.
- **Dev_Stack**: 실제 AWS에 SAM으로 배포한 `dev` 스택. T 시나리오의 합격 판정은 이 스택에서만 한다.
- **Plan**: 하루 계획. 이번 범위에서는 `OPEN` 상태로만 생성된다.
- **PlanSummary**: `planId, title, summary, estimatedMinutes, placeCount, status, ownerNickname, createdAt`.
- **Allowlist**: 응답에 내보내도 되는 필드 이름의 허용 목록.
- **Shown_Status**: 요청자에게 보여 주는 계획 상태. 기한 지난 `CLAIMED`는 현재 실행자가 아니면 `OPEN`으로 표시한다.
- **HIGH**: `scan_privacy` 심각도. 연락처(`PHONE`, `EMAIL`, `RRN`)와 동·호수(`UNIT`).

## Requirements

### Requirement 1: 가입·로그인과 API 보호

**User Story:** As a 사용자, I want 이메일과 닉네임으로 가입하고 곧바로 로그인하고 싶다, so that 인증 코드 단계 없이 서비스를 쓸 수 있다.

#### Acceptance Criteria

1. THE UserPool SHALL 이메일 주소를 사용자 이름으로 사용하고 `nickname`을 필수 속성으로 요구하며, 비밀번호 정책은 Cognito 기본 정책을 따른다. [BE-AUTH-01, BE-Q27]
2. THE UserPoolClient SHALL 클라이언트 시크릿 없이 생성되고, `ALLOW_USER_PASSWORD_AUTH`, `ALLOW_USER_SRP_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH` 인증 흐름을 허용한다. [BE-AUTH-01]
3. IF 가입 요청에 `nickname`이 없으면, THEN THE UserPool SHALL 가입을 거부하고 사용자를 생성하지 않는다. [BE-AUTH-01]
4. WHEN Cognito가 PreSignUp 이벤트를 전달하면, THE PreSignUp_Function SHALL 응답의 `autoConfirmUser`와 `autoVerifyEmail`을 `true`로 설정하고, 이 두 필드 외에는 입력 이벤트의 값을 바꾸지 않고 반환한다. [BE-AUTH-02]
5. WHEN 사용자가 이메일, 비밀번호, `nickname`으로 가입을 마치면, THE UserPool SHALL 인증 코드 입력 없이 같은 자격 증명으로 로그인(`InitiateAuth`)을 허용하고 ID 토큰을 발급한다. [BE-AUTH-02]
6. THE Authorizer SHALL 등록된 모든 API 경로(`GET /me`, `POST /plans`, `GET /plans`, `GET /plans/{planId}`)를 기본 authorizer로 보호하며, 인증 없이 호출할 수 있는 경로를 두지 않는다. [BE-AUTH-03]
7. IF 요청에 `Authorization` 토큰이 없거나, 만료되었거나, 서명·audience 검증에 실패하면, THEN THE Api SHALL 요청을 Lambda에 전달하지 않고 HTTP 401로 응답한다. [BE-AUTH-03, T1]
   - API Gateway JWT authorizer가 거부한 401의 본문은 `{"message":"Unauthorized"}`이고 계약의 에러 형식(`{"error":{"code":"UNAUTHORIZED",...}}`)이 아니다. T1은 상태 코드로만 판정한다. 로컬 어댑터와 Lambda 핸들러(`sub` 없음, 2.3)의 401은 계약 형식이다. 프론트는 401을 상태 코드로 처리한다(FE-COM-03). 계약 변경 리뷰 대상이다(docs/03 §3.6).

참고: PreSignUp 자동 확인은 로컬 에뮬레이터에서 동작하지 않는다. 확인은 PreSignUp 핸들러 단위 테스트와 `Dev_Stack`에서 한다. [§2.4]

### Requirement 2: 사용자 식별과 내 정보

**User Story:** As a 사용자, I want 내 닉네임과 미확인 수신함 수를 조회하고 싶다, so that 헤더에 내 정보를 표시할 수 있다.

#### Acceptance Criteria

1. THE Backend SHALL 사용자 ID를 요청 컨텍스트의 JWT `sub`에서만 읽고, 요청 본문·쿼리·헤더에 사용자 ID 값이 있어도 권한 판단과 응답 생성에 사용하지 않는다. [BE-AUTH-04, BE-NFR-02, G5]
2. THE Backend SHALL 닉네임을 Cognito ID 토큰의 `nickname` 클레임에서 읽고, 액세스 토큰은 닉네임 출처로 쓰지 않는다. [BE-AUTH-04]
3. IF 요청 컨텍스트에 `sub`가 없으면, THEN THE Backend SHALL 401 `UNAUTHORIZED` 에러 형식으로 응답하고 HaruTable을 읽거나 쓰지 않는다. [BE-AUTH-04]
4. WHEN 인증된 사용자가 `GET /me`를 호출하면, THE Me_Function SHALL 200과 `userId`(JWT `sub`), `nickname`(ID 토큰 `nickname`), `unreadInboxCount`(0 이상 정수)를 반환한다. [BE-AUTH-05]
5. WHILE 4단계(수신함) 구현이 완료되기 전이면, THE Me_Function SHALL `unreadInboxCount`를 항상 `0`으로 반환한다. [BE-AUTH-05, BE-Q30]
6. WHERE 4단계(수신함)가 구현되면, THE Me_Function SHALL 같은 배포부터 `unreadInboxCount`를 요청자의 `read = false`인 InboxItem 수로 계산해 반환한다. 이 기준은 4단계에서 구현·검증하며 1·2단계 완료 판정에 포함하지 않는다. [BE-AUTH-05, BE-Q30]
7. WHILE 4단계(수신함) 구현이 완료되기 전이면, THE Me_Function SHALL `GET /me` 처리에서 HaruTable을 읽거나 쓰지 않는다. [BE-AUTH-05, BE-Q30]

### Requirement 3: 계획 입력 검증

**User Story:** As a 계획자, I want 잘못된 입력에 필드별 사유를 받고 싶다, so that 폼의 해당 칸에서 바로 고칠 수 있다.

#### Acceptance Criteria

1. THE Validator SHALL 요청 본문의 각 필드가 다음 범위(양 끝 값 포함)를 모두 만족할 때만 통과시킨다. [BE-PLAN-02]
   - `title` 1–40자
   - `summary` 1–120자
   - `reason` 1–300자
   - `estimatedMinutes` 10–240
   - `places` 1–3개
   - `places[].name` 1–30자
   - `places[].activity` 1–60자
   - `places[].whyChosen` 0–120자
   - `question` 1–80자
2. THE Validator SHALL `authoring.story`를 `MANUAL`과 `AI_EDITED` 두 모드 모두에서 필수로 요구하고, 1–1,000자인 값만 통과시킨다. [BE-PLAN-02]
3. THE Validator SHALL `authoring.mode`가 `MANUAL` 또는 `AI_EDITED`인 값만, `authoring.durationMs`가 0 이상의 정수인 값만 통과시킨다. [BE-PLAN-02, BE-PLAN-03]
4. IF 요청 본문이 검증에 실패하면, THEN THE Plans_Function SHALL 400 `VALIDATION_ERROR`로 응답하고, `details`에 실패한 필드마다 요청 본문 경로(`places[0].name` 형식)를 키로, 사유 메시지를 값으로 담고, Plan과 Idempotency_Key_Item을 저장하지 않는다. [BE-PLAN-02, BE-NFR-05]
5. IF `POST /plans` 요청에 `Idempotency-Key` 헤더가 없으면, THEN THE Plans_Function SHALL 400 `VALIDATION_ERROR`로 응답하고, `details`의 키로 헤더 이름 `Idempotency-Key`를 쓰고, Plan을 저장하지 않는다. [BE-PLAN-01, BE-Q29]
6. WHERE `authoring.aiSessionId`가 전달되면, THE Validator SHALL 값이 문자열인지만 확인하고 AI 세션의 존재 여부는 확인하지 않는다. [BE-PLAN-03]

### Requirement 4: 계획 생성과 멱등 키

**User Story:** As a 계획자, I want 같은 공개 요청을 재시도해도 계획이 한 건만 만들어지길 원한다, so that 네트워크 오류 후 재전송해도 중복 공개가 생기지 않는다.

#### Acceptance Criteria

1. WHEN 인증된 사용자가 유효한 본문과 `Idempotency-Key`로 `POST /plans`를 호출하면, THE Plan_Service SHALL Plan 항목과 Idempotency_Key_Item을 하나의 TransactWriteItems로 저장하고 201 `{ plan }`을 반환한다. [BE-PLAN-01, §3.3]
2. THE Plan_Service SHALL 새 Plan을 `status = OPEN`, `ownerId = JWT sub`, `ownerNickname = ID 토큰 nickname`, `areaId = default`, `version = 1`, `planId = pln_ + ULID`로 만든다. [BE-PLAN-01, BE-PLAN-09]
3. THE Plan_Service SHALL Idempotency_Key_Item의 키를 `IDEM#{userId}#{key}`로 만들어 같은 `Idempotency-Key`라도 사용자별로 구분한다. [BE-PLAN-01]
4. THE Plan_Service SHALL Idempotency_Key_Item에 본문 해시(`bodyHash`), `planId`, 생성 시각 + 24시간의 `ttl`을 저장한다. [BE-PLAN-01]
5. WHEN 같은 사용자가 같은 `Idempotency-Key`와 같은 본문으로 `POST /plans`를 다시 호출하면, THE Plan_Service SHALL 처음 생성한 Plan을 반환하고 새 Plan을 만들지 않는다. [BE-PLAN-01, T13]
6. THE Plan_Service SHALL 멱등 재요청에도 처음 응답과 같은 201을 반환한다. [BE-PLAN-01, BE-Q24]
7. IF 같은 사용자가 같은 `Idempotency-Key`와 다른 본문으로 `POST /plans`를 호출하면, THEN THE Plan_Service SHALL 새 Plan을 만들지 않고 409 `IDEMPOTENCY_CONFLICT`로 응답한다. [BE-PLAN-01]
8. WHEN 같은 사용자가 같은 `Idempotency-Key`와 같은 본문으로 `POST /plans`를 동시에 호출하면, THE Plan_Service SHALL Plan 항목을 정확히 1건만 남기고 성공한 모든 응답에 같은 `planId`를 반환한다. [BE-PLAN-01, T13]
9. IF 트랜잭션이 `TransactionConflict`로 취소되면, THEN THE Plan_Service SHALL 50·100·200ms 간격으로 최대 3회 재시도한다. [BE-REC-10, §2.6]
10. IF `TransactionConflict` 재시도 3회가 모두 실패하면, THEN THE Plan_Service SHALL 503 `TRY_AGAIN`으로 응답하고 Plan과 Idempotency_Key_Item을 남기지 않는다. [BE-REC-10, §3.6]
11. IF 트랜잭션이 `ConditionalCheckFailed`로 취소되면, THEN THE Plan_Service SHALL 재시도 없이 Idempotency_Key_Item을 `ConsistentRead`로 다시 읽어 `bodyHash`를 비교하고, 같으면 기존 Plan을 반환하고 다르면 409 `IDEMPOTENCY_CONFLICT`로 응답한다. [BE-PLAN-01, BE-REC-10]
12. IF 취소 원인을 재조회로도 판정할 수 없으면(Idempotency_Key_Item이 없는 경우 등), THEN THE Plan_Service SHALL 503 `TRY_AGAIN`으로 응답한다. [BE-REC-10]

### Requirement 5: 작성 지표 저장

**User Story:** As a 운영 담당자, I want 계획마다 작성 소요 시간과 원문 충실도 지표를 남기고 싶다, so that 직접 작성과 AI 초안 편집을 비교할 수 있다.

#### Acceptance Criteria

1. WHEN 유효한 `POST /plans` 요청으로 새 Plan이 만들어지면, THE Plan_Service SHALL 그 Plan에 `metrics.authoringMode`(요청 `authoring.mode` 값), `metrics.durationMs`(요청 `authoring.durationMs` 값), `metrics.addedNotInSource`, `metrics.privacyInPublished`를 두 모드 모두에 저장한다. [BE-PLAN-03]
2. THE Plan_Service SHALL `metrics.addedNotInSource`를 `find_not_in_source([story], 최종 places의 name·activity)`가 돌려준 개수(0 이상의 정수)로 계산한다. 근거 텍스트는 `authoring.story` 하나뿐이다. [BE-PLAN-03, BE-AI-06]
3. THE Plan_Service SHALL `metrics.privacyInPublished`를 최종 Plan 텍스트(`title`, `summary`, `reason`, `question`, `places[].name/activity/whyChosen`)에 대한 `scan_privacy` 탐지 수(0 이상의 정수)로 계산한다. [BE-PLAN-03, BE-AI-06]
4. THE Plan_Service SHALL 이번 범위에서 `metrics`에 위 네 값만 저장한다. `authoring.aiSessionId`가 있어도 AI 세션을 읽지 않고 AI 세션 기반 지표(`addedNotInSourceOrAnswers`, `firstProposalNotInSource` 등)를 계산하거나 저장하지 않으며, 이 요청을 `aiSessionId` 때문에 거부하지 않는다. [BE-PLAN-03]
5. THE Plan_Service SHALL `authoring.story` 원문을 Plan 항목(`metrics` 포함)에 저장하지 않는다. [BE-PLAN-03, §2.5]
6. WHEN 같은 `Idempotency-Key`와 같은 본문으로 `POST /plans`가 다시 오면, THE Plan_Service SHALL 처음 만든 Plan을 그대로 반환하고 `metrics`를 다시 계산하거나 덮어쓰지 않는다. [BE-PLAN-01, BE-PLAN-03, T13]

### Requirement 6: 둘러보기 목록

**User Story:** As a 실행자, I want 이어받을 수 있는 하루 목록을 최신순으로 보고 싶다, so that 둘러보고 하나를 고를 수 있다.

#### Acceptance Criteria

1. WHEN 인증된 사용자가 `GET /plans?status=OPEN`을 호출하면, THE Plans_Function SHALL 200으로 `items`(PlanSummary 배열)와 `nextCursor`(값 `null`)를 반환한다. [BE-PLAN-04, BE-Q3]
2. IF `status` 쿼리가 `OPEN`이 아니면, THEN THE Plans_Function SHALL 400 `VALIDATION_ERROR`로 응답하고 목록을 조회하지 않는다. [BE-PLAN-04]
3. THE Plan_Service SHALL 모든 항목의 `status`를 `OPEN`으로 내려주고, 항목을 `createdAt` 내림차순(최신 먼저)으로 정렬한다. [BE-PLAN-04, T16]
4. THE Plan_Service SHALL `GSI1PK = AREA#default#STATUS#OPEN` 조회 결과와 `STATUS#CLAIMED` 조회 결과 중 `dueAt`이 현재 시각보다 이른 항목을 합쳐 반환하고, `dueAt`이 현재 시각 이후인 `CLAIMED` 항목은 제외한다. [BE-PLAN-04, T16]
5. WHEN 요청에 `limit`이 없으면, THE Plan_Service SHALL 최대 20개를 반환한다. [BE-PLAN-04, BE-Q3]
6. THE Plan_Service SHALL 정렬이 끝난 합친 목록에서 앞쪽 `limit`개만 반환하며, `limit`의 최댓값은 50이다. [BE-PLAN-04, BE-Q3]
7. WHEN 조건에 맞는 계획이 없으면, THE Plans_Function SHALL 200으로 빈 `items` 배열과 `nextCursor: null`을 반환한다. [BE-PLAN-04]

### Requirement 7: 하루 상세

**User Story:** As a 사용자, I want 한 하루의 상세와 내가 이어받을 수 있는지를 보고 싶다, so that 이어받기 버튼 노출을 서버 판단에 맡길 수 있다.

#### Acceptance Criteria

1. WHEN 인증된 사용자가 존재하는 계획에 대해 `GET /plans/{planId}`를 호출하면, THE Plan_Service SHALL 200 `{ plan, isOwner, myClaim, claimable }`을 반환한다. `isOwner`와 `claimable`은 불리언이고 `myClaim`은 Claim 또는 `null`이다. [BE-PLAN-05]
2. IF `GET /plans/{planId}` 요청에 유효한 토큰이 없거나 토큰이 만료되었으면, THEN THE Api SHALL 요청을 Lambda에 전달하지 않고 계획 데이터 없이 401 `UNAUTHORIZED`로 응답한다. [BE-AUTH-03, T1]
3. IF 요청한 `planId`의 계획이 존재하지 않으면, THEN THE Plan_Service SHALL 404 `NOT_FOUND`로 응답한다. [BE-PLAN-05]
4. IF `COMPLETED` 계획을 소유자도 해당 실행자도 아닌 사용자가 조회하면, THEN THE Plan_Service SHALL 계획이 없을 때와 같은 404 `NOT_FOUND`로 응답한다. [BE-PLAN-07, G5]
5. WHILE 계획이 `CLAIMED`이고 `dueAt < now`이면, THE Plan_Service SHALL 현재 실행자가 아닌 요청자에게 `status: "OPEN"`으로 내려주고, 현재 실행자 본인에게는 `status: "CLAIMED"`와 `myClaim`을 내려준다. [BE-PLAN-06]
6. WHILE 계획이 `CLAIMED`이고 `dueAt >= now`이면, THE Plan_Service SHALL `status: "CLAIMED"`를 내려주고, 현재 실행자가 아닌 요청자에게는 실행자 정보를 응답에서 제외한다. [BE-PLAN-06]
7. THE Plan_Service SHALL `myClaim`에 요청자의 Claim 중 `ACTIVE` 또는 `COMPLETED`인 것만 담고, 해당하는 Claim이 없거나 `ABANDONED`·`EXPIRED` Claim만 있으면 `null`로 내려준다. [BE-PLAN-05]
8. THE Plan_Service SHALL `claimable`을 `!isOwner && myClaim == null && 응답에 내려준 status == "OPEN"`으로 계산한다. [BE-PLAN-05]
9. THE Plan_Service SHALL 단건 계획 조회에 `ConsistentRead` GetItem을 사용한다. [BE-PLAN-05]
10. IF 요청자의 Claim 항목이 하나도 없으면, THEN THE Plan_Service SHALL `myClaim`을 `null`로 반환한다. [BE-PLAN-05]
11. WHEN 요청자의 Claim 항목이 있으면, THE Plan_Service SHALL 그중 `ACTIVE` 또는 `COMPLETED`인 Claim을 읽어 `myClaim`으로 직렬화하고, `ABANDONED`·`EXPIRED` Claim만 있을 때의 `null` 반환은 7.7을 따른다. 이번 범위에서 Claim 항목은 쓰지 않는다. [BE-PLAN-05]

참고: 인증되지 않은 `GET /plans/{planId}` 요청에는 403 `FORBIDDEN`을 쓰지 않는다. `docs/03-api-contract.md` §3.6은 토큰 없음·만료를 401 `UNAUTHORIZED`로, 403은 남의 Claim/Record에 대한 쓰기 시도로 정의하며 후자는 이번 범위 밖이다.

### Requirement 8: 응답 직렬화와 계획 갱신 규칙

**User Story:** As a 보안 담당자, I want 내부 속성과 소유자 전용 지표가 응답에 새지 않길 원한다, so that 다른 사용자에게 내부 데이터가 노출되지 않는다.

#### Acceptance Criteria

1. THE Serializer SHALL 허용 목록에 등록된 필드만 Plan 응답에 담고, 허용 목록에 없는 저장 속성(`PK`, `SK`, `claimerId`, `currentClaimId`, `dueAt`, `GSI*`, `version`, `ttl` 포함)은 응답 본문의 어느 깊이에도 포함하지 않는다. [BE-PLAN-08]
2. WHEN 요청자의 `userId`가 계획의 `ownerId`와 같으면, THE Serializer SHALL Plan 응답에 `metrics` 객체를 포함한다. [BE-PLAN-08]
3. WHEN 요청자의 `userId`가 계획의 `ownerId`와 다르면, THE Serializer SHALL Plan 응답에서 `metrics` 키와 그 하위 필드를 모두 제외한다. [BE-PLAN-08, §2.5]
4. THE Serializer SHALL Plan 응답의 `owner`를 `userId`와 `nickname` 두 필드만 가진 객체로 만들고, 저장된 값이 없는 `completedAt`을 키를 생략하지 않고 `null`로 직렬화한다. [BE-PLAN-08, §2.5]
5. THE Plan_Service SHALL `status`가 `OPEN`인 Plan 항목에 `currentClaimId`, `claimerId`, `dueAt`, `completedAt` 속성을 저장하지 않는다(`null` 값으로도 쓰지 않는다). [§2.5]
6. WHEN Plan 항목을 갱신하면, THE Plan_Service SHALL `version`을 갱신 전 값보다 정확히 1 올린다. [BE-PLAN-09, §2.6]
7. WHEN Plan 갱신으로 `status`가 바뀌면, THE Plan_Service SHALL 같은 쓰기 안에서 `GSI1PK`를 새 `status`에 맞는 값으로 함께 바꾼다. [BE-PLAN-09, §2.6]
8. THE Serializer SHALL `PlanSummary`를 `planId`, `title`, `summary`, `estimatedMinutes`, `placeCount`, `status`, `ownerNickname`, `createdAt` 여덟 필드로만 구성하며, 요청자가 소유자여도 `metrics`와 그 밖의 필드를 포함하지 않는다. [§3.3, BE-PLAN-04]

### Requirement 9: 원문 충실도 판정 함수

**User Story:** As a 개발자, I want 계획의 장소·활동이 사연에 근거하는지 판정하는 순수 함수를 원하고 싶다, so that 지표 계산과 이후 AI 게이트가 같은 기준을 쓴다.

#### Acceptance Criteria

1. WHEN `find_not_in_source(sources, targets)`가 호출되면, THE Fidelity_Checker SHALL 정규화(공백·조사 제거)한 핵심 토큰 중 하나라도 근거 텍스트에 없는 target을 `NotInSourceHit(path, text)`로 반환하고, 모든 토큰이 근거 텍스트에 있는 target은 반환하지 않는다. [BE-AI-06]
2. THE Fidelity_Checker SHALL `sources`를 사연과 계획자가 직접 입력한 답변의 텍스트 목록으로 받고, 모델이 만든 문장은 근거로 취급하지 않는다. [BE-AI-06]
3. THE Fidelity_Checker SHALL 반환하는 각 `NotInSourceHit`의 `path`와 `text`에 입력 target의 값을 그대로 담고, hit를 입력 target 순서대로 반환한다. [BE-AI-06, §3.2]
4. IF target의 `text`가 `null`, 빈 문자열 또는 공백뿐이면, THEN THE Fidelity_Checker SHALL 그 target을 `NotInSourceHit`으로 반환하지 않는다. [BE-AI-06]
5. IF `sources`가 빈 목록이거나 모든 항목이 빈 문자열이면, THEN THE Fidelity_Checker SHALL 4번에 해당하지 않는 모든 target을 `NotInSourceHit`으로 반환한다. [BE-AI-06]
6. THE Fidelity_Checker SHALL 같은 입력에 항상 같은 결과를 반환하고, `sources`와 `targets`를 변경하지 않으며, LLM 호출과 DB 접근을 하지 않는다. [BE-AI-06, G6]
7. WHEN `sources`에 문장이 추가되어 호출되면, THE Fidelity_Checker SHALL 추가 전보다 적거나 같은 수의 hit를 반환한다. [BE-AI-06]
8. THE Fidelity_Checker SHALL 정규화 사전(`src/domain/normalization.json`, 서비스 코드와 테스트가 공유)에 등록된 동의어만 같은 표현으로 인정하고, 사전에 없는 표현은 서로 다른 표현으로 판정한다. [BE-AI-06, §7.3]
9. WHEN 데모 사연(§3.2 예시)을 근거로 호출되면, THE Fidelity_Checker SHALL "골목 빵집"을 `NotInSourceHit`으로 반환하고 "출근길 빵집"은 반환하지 않는다. [BE-AI-06, T18]
10. THE Fidelity_Checker SHALL target 텍스트를 공백으로 나눈 토큰마다 말미 조사를 제거하고, 제거한 토큰이 근거 텍스트(공백 제거)에 부분 문자열로 있으면 일치로 보며, 모든 토큰이 일치해야 통과로 판정한다. 활동(`places[].activity`)은 서술어 꼴 토큰(끝이 -기, -고, -서, -며)을 빼고 남은 토큰만 대조하며, 남는 토큰이 없으면 판정하지 않는다. 조사 사전의 항목은 2단계 단위 테스트로 확정한다. [BE-AI-06, BE-Q25]

### Requirement 10: 개인정보 탐지 함수

**User Story:** As a 계획자, I want 공개할 계획에 연락처나 집 주소가 남았는지 점검되길 원한다, so that 개인정보가 공개 계획에 노출되지 않는다.

#### Acceptance Criteria

1. WHEN `scan_privacy(texts)`가 경로별 텍스트 목록과 함께 호출되면, THE Privacy_Scanner SHALL 전화(`PHONE`), 이메일(`EMAIL`), 주민번호(`RRN`), 차량번호(`PLATE`), 동/호수(`UNIT`), 번지(`LOT`) 정규식과 비공개 장소 사전(`PRIVATE_PLACE`)에 일치하는 모든 탐지를 입력 경로별로 `PrivacyHit(path, kind, severity)`로 반환한다. [BE-AI-06]
2. IF 입력이 빈 목록이거나 모든 텍스트가 빈 문자열 또는 `null`이면, THEN THE Privacy_Scanner SHALL 예외 없이 빈 목록을 반환한다. [BE-AI-06]
3. THE Privacy_Scanner SHALL `PHONE`, `EMAIL`, `RRN`, `UNIT` 탐지를 `HIGH`로, `PLATE`, `LOT`, `PRIVATE_PLACE` 탐지를 `MEDIUM`으로 분류한다. [BE-AI-06, BE-Q22]
4. WHEN `mask(text)`가 호출되면, THE Privacy_Scanner SHALL `HIGH` 탐지 부분의 원래 값이 남지 않게 마스킹한 텍스트를 반환하고 `HIGH`가 아닌 부분은 바꾸지 않으며, 반환된 텍스트를 다시 스캔하면 `HIGH` 탐지가 0건이다. [BE-AI-06]
5. WHEN 개인정보가 없는 데모 사연(§3.2 예시)이 입력되면, THE Privacy_Scanner SHALL 탐지 0건을 반환한다. [BE-AI-06]
6. THE Privacy_Scanner SHALL 제3자 실명 후보(`PERSON_NAME`) 판정을 구현하지 않고 어떤 입력에도 `PERSON_NAME` 탐지를 반환하지 않는다. [BE-AI-06, BE-Q26]
7. WHEN 개인정보 탐지 결과를 로그에 기록하면, THE Backend SHALL `kind`별 개수만 기록하고 입력 원문, 일치한 문자열, 마스킹 전후 텍스트는 기록하지 않는다. [BE-NFR-03]

### Requirement 11: 오류 응답 형식

**User Story:** As a 프론트엔드 개발자, I want 모든 오류가 같은 형식으로 오길 원한다, so that 공통 클라이언트에서 코드별로 분기할 수 있다.

#### Acceptance Criteria

1. IF 요청 처리 결과가 4xx 또는 5xx이면, THEN THE Error_Handler SHALL 응답 본문을 `{ "error": { "code", "message", "details"? } }` 형식으로 만들고 `code`와 `message`를 비어 있지 않은 문자열로 채운다. [BE-NFR-05]
2. IF 응답 코드가 `VALIDATION_ERROR`이면, THEN THE Error_Handler SHALL `details`에 요청 본문 경로를 키로, 필드별 사유를 값으로 담는다. [BE-NFR-05, §3]
3. IF 응답 코드가 `VALIDATION_ERROR`가 아니면, THEN THE Error_Handler SHALL 응답 본문에 `details`를 포함하지 않는다. [BE-NFR-05, §3]
4. IF 핸들러에서 예상하지 못한 예외가 발생하면, THEN THE Error_Handler SHALL HTTP 500과 에러 형식 본문으로 응답하며, 응답 본문에 예외 메시지·스택 트레이스·내부 식별자를 담지 않는다. 이때 `code`는 BE-Q23이 확정될 때까지 `INTERNAL_ERROR`를 임시로 쓴다. [BE-NFR-05, BE-Q23]
5. IF 핸들러에서 예상하지 못한 예외가 발생하면, THEN THE Error_Handler SHALL 로그에 예외 유형만 남기고 토큰·사연 원문·사진 URL을 남기지 않는다. [BE-NFR-03]
6. THE Backend SHALL 응답 본문의 모든 시간 값을 밀리초 3자리를 고정한 ISO 8601 UTC 문자열(`2026-11-17T09:00:00.000Z`)로 반환한다. [BE-NFR-05, §3 공통 규칙]
7. THE Backend SHALL 이번 범위에서 `VALIDATION_ERROR`(400), `UNAUTHORIZED`(401), `NOT_FOUND`(404), `IDEMPOTENCY_CONFLICT`(409), `TRY_AGAIN`(503)을 `docs/03-api-contract.md` §3.6에 적힌 코드 문자열·HTTP 상태와 같은 조합으로만 사용한다. [BE-NFR-07]

### Requirement 12: SAM 템플릿과 배포 설정

**User Story:** As a 백엔드 개발자, I want 처음부터 배포 가능한 SAM 골격을 원한다, so that 매 단계 끝에 `dev` 스택에 배포해 검증할 수 있다.

#### Acceptance Criteria

1. THE Backend SHALL `template.yaml`에 `HaruTable`(PK/SK, GSI1, GSI2, TTL 속성 `ttl`, on-demand 과금), `UserPool`, `UserPoolClient`, `HttpApi`, `MeFunction`, `PlansFunction`, `PreSignUpFunction`을 정의하고, 모든 Lambda를 Python 3.12 런타임으로 VPC 밖에 둔다. [BE-INFRA-01, §2.6]
2. THE HttpApi SHALL CORS를 허용 Origin = `AllowedOrigins` 파라미터 값(기본 `http://localhost:5173`), 허용 헤더 `Authorization`·`Content-Type`·`Idempotency-Key`, 허용 메서드 `GET`·`POST`·`PUT`·`OPTIONS`로 설정하고 이 목록 밖의 값은 허용하지 않는다. [BE-INFRA-03]
3. THE Backend SHALL 스택 출력값 `ApiUrl`, `UserPoolId`, `UserPoolClientId`를 내보내고 각 값은 배포된 리소스의 실제 값과 일치한다. [BE-INFRA-04]
4. THE Backend SHALL 모든 Lambda의 Globals 환경 변수에 `TABLE_NAME`, `AREA_ID=default`, `CLAIM_DURATION_DAYS=3`, `LANGSMITH_TRACING=false`, `LANGCHAIN_TRACING_V2=false`를 설정하고, SDK 표준 변수 `AWS_ENDPOINT_URL`과 `AWS_EMF_ENVIRONMENT`는 정의하지 않는다. [BE-INFRA-05, BE-AI-15]
5. THE Backend SHALL `PlansFunction`에 `HaruTable`과 그 인덱스에 대한 `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:Query` 권한만 부여하고, `MeFunction`에는 DynamoDB 권한을 부여하지 않는다. [BE-INFRA-06] (3단계에서 `GET /me/claims`가 추가되어 `MeFunction`에 `GetItem`·`Query`, `PlansFunction`에 `UpdateItem`이 붙었다. spec `backend-stage3-claim` 요구사항 7)
6. THE Backend SHALL `samconfig.toml`에 `dev`, `demo` 환경을 두고 `AllowedOrigins`를 환경별로 지정하며, 이번 범위에서는 CloudFront 도메인을 넣지 않는다. [BE-INFRA-01, BE-INFRA-03]
7. WHEN `sam validate --lint`를 실행하면, THE Backend SHALL 종료 코드 0으로 끝나고 오류를 0건 보고하는 템플릿을 제공한다. [BE-INFRA-01]
8. THE Backend SHALL 이번 범위에서 `POST /plans/{planId}/claims`, `GET /me/claims`, `GET /me/plans`와 AI·Claim·Inbox 관련 경로를 `HttpApi`에 등록하지 않는다. [BE-INFRA-01]
9. THE Backend SHALL 이번 범위에서 LangGraph·LangChain·Pillow 의존성을 어떤 Lambda의 의존성 파일과 `sam build` 산출물에도 포함하지 않는다. [BE-INFRA-05]

### Requirement 13: 로컬 개발 환경

**User Story:** As a 백엔드 개발자, I want docker compose 한 번으로 로컬 환경을 띄우고 싶다, so that AWS 비용 없이 개발과 단위·로컬 통합 테스트를 할 수 있다.

#### Acceptance Criteria

1. WHEN `docker compose up`을 실행하면, THE Local_Env SHALL 태그가 고정된 에뮬레이터(`floci/floci:2.5.0-compat`)와 Local_Adapter를 시작한다. [BE-INFRA-08]
2. WHEN 에뮬레이터가 요청을 받을 수 있는 상태가 되면, THE Local_Env SHALL init 스크립트로 `HaruTable`(GSI1·GSI2·TTL `ttl`), `HaruAgentCheckpoints`(PK/SK, TTL `ttl`), 유저 풀, 앱 클라이언트, 시드 사용자 3명(지연, 수현, 민준)을 만들고 `LOCAL_JWT_ISSUER`, `LOCAL_JWKS_URL`, 풀 ID, 클라이언트 ID를 표준 출력에 출력한다. [BE-INFRA-08]
3. IF init 스크립트의 리소스 생성 단계가 하나라도 실패하면, THEN THE Local_Env SHALL 실패한 단계 이름을 출력하고 0이 아닌 종료 코드로 끝난다. [BE-INFRA-08]
4. WHEN Local_Adapter가 요청을 받으면, THE Local_Adapter SHALL 요청을 payload 2.0 이벤트로 변환하고, ID 토큰의 `iss`, `aud`, `exp`, `token_use=id`를 검증한 뒤 `requestContext.authorizer.jwt.claims`를 주입해 같은 Lambda 핸들러를 호출한다. [BE-INFRA-08]
5. IF 토큰이 없거나, 만료되었거나, `iss`·`aud`가 맞지 않거나, `token_use`가 `id`가 아니거나, 서명 검증에 실패하면, THEN THE Local_Adapter SHALL 핸들러를 호출하지 않고 계약의 에러 형식으로 401 `UNAUTHORIZED`를 반환한다. [BE-INFRA-08]
6. WHERE `STAGE=local`이면, THE Local_Adapter SHALL `POST /dev/token { userId, nickname }` 요청에 `{ idToken }`을 응답하는 dev JWT 발급 경로를 제공한다. [BE-INFRA-08]
7. WHERE `STAGE`가 `local`이 아니면, THE Local_Adapter SHALL `POST /dev/token` 경로를 등록하지 않는다. [BE-INFRA-08]
8. WHEN CORS preflight `OPTIONS` 요청이 오면, THE Local_Adapter SHALL 토큰 검증 없이 허용 Origin `http://localhost:5173`에 대해 204로 응답한다. [BE-INFRA-03, BE-INFRA-08]
9. THE Local_Env SHALL 어댑터의 라우트 목록과 `template.yaml`의 이벤트 경로가 일치하는지 단위 테스트로 확인하고, 한쪽에만 있는 경로가 있으면 그 테스트가 실패한다. [BE-INFRA-08]
10. THE Local_Env SHALL docker compose에 `LANGSMITH_TRACING=false`와 `LANGCHAIN_TRACING_V2=false`를 명시한다. [BE-AI-15]
11. THE Local_Env SHALL 시드 사용자의 이메일·비밀번호를 로컬 전용 예시 값으로 `.env.example`과 init 스크립트에만 두고 `.env`를 저장소에 올리지 않는다. [BE-INFRA-08, BE-Q28]
12. THE Local_Env SHALL 로컬 통합 테스트 결과를 T 시나리오(T1–T22) 합격 근거로 사용하지 않는다. [BE-INFRA-08, BE-Q15]
13. WHEN 로컬 통합 테스트가 시드 사용자 토큰으로 `GET /me`를 호출하면, THE Local_Env SHALL 응답의 `nickname`이 시드 값과 같은지 확인한다. [BE-AUTH-05, BE-Q17]

### Requirement 14: 단계 완료 기준

**User Story:** As a 팀원, I want 1·2단계 완료를 판정할 객관적 기준을 원한다, so that 3단계로 넘어갈 시점을 합의할 수 있다.

#### Acceptance Criteria

1. WHEN `Dev_Stack`에 등록된 모든 경로(`GET /me`, `POST /plans`, `GET /plans`, `GET /plans/{planId}`)를 `Authorization` 헤더 없이 한 번씩 호출하면, THE Api SHALL 모든 호출에 401 `UNAUTHORIZED`로 응답하고, 이 결과가 `tests/integration/test_authz.py`에서 실패 0건으로 통과한다. [T1, BE-AUTH-03]
2. WHEN 같은 `Idempotency-Key`와 같은 본문으로 `Dev_Stack`에 `POST /plans`를 3회 호출하면, THE Backend SHALL 저장된 Plan을 1건으로 유지하고 3회 응답 모두에 같은 `planId`를 반환하며, 이 결과가 `tests/integration/test_idempotency.py`에서 통과한다. [T13, BE-PLAN-01, BE-Q24]
3. IF 이미 사용된 `Idempotency-Key`로 본문을 바꿔 `Dev_Stack`에 `POST /plans`를 호출하면, THEN THE Backend SHALL 409 `IDEMPOTENCY_CONFLICT`로 응답하고 새 Plan을 만들지 않으며 처음 저장된 Plan을 변경하지 않는다. [T13, BE-PLAN-01]
4. WHEN 테스트 사용자가 이메일과 `nickname`으로 `Dev_Stack`에 가입하면, THE UserPool SHALL 인증 코드 입력 없이 가입 직후 로그인을 허용하고, 로그인으로 받은 ID 토큰의 `nickname` 클레임이 가입 때 입력한 값과 같다. [BE-AUTH-01, BE-AUTH-02]
5. WHEN 2단계 단위 테스트를 실행하면, THE Backend SHALL 검증 경계값, `find_not_in_source`(정규화 사전 포함), `scan_privacy`, 응답 직렬화 허용 목록, 상태 표시 규칙, 멱등 분기(같은 키·같은 본문, 같은 키·다른 본문, 새 키), PreSignUp 핸들러의 모든 테스트 케이스를 실패 0건으로 통과한다. [§7.3 2단계, BE-PLAN-02, BE-Q25]
6. THE Backend SHALL T1과 T13의 합격 여부를 `Dev_Stack`에서 실행한 결과로만 판정하고 로컬 Docker 환경의 통과 결과는 합격으로 인정하지 않는다. [BE-NFR-01, BE-Q15]
7. THE Backend SHALL 1·2단계 완료 판정에 G1–G4의 구현과 T3–T7 통과를 요구하지 않으며, 이 항목은 3단계 완료 기준에서 판정한다. [§7.3 3단계]
## 미결 사항

`docs/08-open-questions.md` §8.1의 번호와 연결한다. 이 spec이 새로 찾은 BE-Q22–BE-Q33은 해당 문서에 추가되어 있다.

| # | 영향받는 기준 | 임시 기본안 |
|---|---|---|
| BE-Q3 | 6.1, 6.5 | `limit` 최대 50, `nextCursor: null` 고정 |
| BE-Q15 | 13.12, 14.6 | T 판정은 AWS 스택에서만 |
| BE-Q17 | 2.2, 13.13 | Floci ID 토큰에 `nickname` 클레임이 있는지 로컬 통합 테스트로 확인, 없으면 dev JWT 사용 |
| BE-Q22 | 10.3 | `PLATE`·`LOT`·`PRIVATE_PLACE`는 `MEDIUM`, 탐지만 하고 차단하지 않음 |
| BE-Q23 | 11.4 | 500의 에러 코드. 확정 전 `INTERNAL_ERROR` 임시 사용 후 계약에 반영 |
| BE-Q24 | 4.6 | 멱등 재요청도 201 |
| BE-Q25 | 9.10 | 토큰별 말미 조사 제거 + 부분 문자열 일치 |
| BE-Q26 | 10.6 | 이번에는 사전 항목만, `PERSON_NAME` 빈 결과 |
| BE-Q27 | 1.1 | 비밀번호 정책은 Cognito 기본 |
| BE-Q28 | 13.11 | 로컬 전용 예시 값을 `.env.example`에 둔다 |
| BE-Q29 | 3.5 | `details` 키는 헤더 이름 그대로 |
| BE-Q30 | 2.5, 2.6, 2.7 | 4단계 전까지 `unreadInboxCount` 0 고정(HaruTable 미접근), 4단계 구현 배포부터 `read = false` InboxItem 수로 계산(2.6). 닉네임 클레임 없음 처리는 BE-Q17 결과에 따름 |
| BE-Q31 | 3.3 | `authoring.durationMs` 상한이 `docs/`에 없어 제한하지 않음 |
| BE-Q32 | 6.5, 6.6 | `limit`이 숫자가 아니거나 범위 밖이면 기본 20 / 최대 50으로 보정 |
| BE-Q33 | 8.1, 8.4 | `currentClaimId`는 응답에 내보내지 않음(BE-PLAN-08 우선). §2.5 Plan 예시의 `currentClaimId: null`은 확정 시 정리 |
| BE-Q17, BE-Q30 | 2.2 | ID 토큰에 `nickname` 클레임이 없을 때의 응답 형태는 미정 |

계약 변경(BE-Q23, BE-Q24, BE-Q29)은 `docs/07-development-plan.md` §7.2의 계약 변경 절차(프론트엔드 리뷰)를 따른다.
