# Implementation Plan: backend-stage1-2-foundation

## Overview

백엔드 1단계(SAM 골격, 인증, 단일 테이블, 로컬 환경, `GET /me`)와 2단계(계획 생성·목록·상세, 멱등 키, `find_not_in_source`, `scan_privacy`)를 `backend/` 아래에 Python 3.12로 구현한다. 문서의 `src/...`, `tests/...` 경로는 모두 `backend/` 기준이다. 순서는 공통 모듈 → 순수 도메인 함수 → 직렬화 → 서비스 → 핸들러 → SAM → 로컬 환경 → 배포 스택 검증이다.

- 범위 밖(3단계 이후): 이어받기·포기·완료 트랜잭션, 방문 기록, 사진, 수신함, `/ai/*`, LangGraph, CloudFront, 알람, `seed.py`·`report.py`. 이 단계는 G1–G4를 증명하지 않는다(요구사항 14.7).
- T1(`tests/integration/test_authz.py`)과 T13(`tests/integration/test_idempotency.py`)의 합격은 AWS `dev` 스택에서만 판정한다(BE-Q15, 요구사항 14.6). 로컬 Docker 결과는 합격 근거가 아니다.
- 미결 항목은 요구사항이 정한 임시 기본안으로 구현하고 코드 주석과 PR에 질문 번호를 남긴다: BE-Q3(`limit` 최대 50, `nextCursor: null`), BE-Q17, BE-Q22(`PLATE`·`LOT`·`PRIVATE_PLACE`는 `MEDIUM`), BE-Q23(500 코드 `INTERNAL_ERROR` 임시), BE-Q24(멱등 재요청 201), BE-Q25(토큰별 조사 제거 + 부분 문자열), BE-Q26(`PERSON_NAME` 빈 결과), BE-Q27, BE-Q28, BE-Q29(`details` 키 `Idempotency-Key`), BE-Q30(`unreadInboxCount` 0 고정), BE-Q31(`durationMs` 상한 없음), BE-Q32(`limit` 비정상 값은 20/50으로 보정), BE-Q33(`currentClaimId` 응답에 내보내지 않음). 모두 `docs/08-open-questions.md` §8.1에 등록되어 있다.
- `*` 표시 하위 작업은 선택(테스트)이다. T1·T13 통합 테스트는 완료 기준이므로 선택이 아니다.

## Tasks

- [x] 1. 프로젝트 골격과 테스트 설정
  - `backend/` 아래에 `src/common`, `src/handlers`, `src/domain`, `local/init`, `local/adapter`, `tests/unit`, `tests/local`, `tests/integration`, `tests/fixtures` 디렉터리와 `__init__.py`를 만든다(`metrics.py`, `agent/`, `workers/`, `layers/`는 만들지 않는다).
  - `requirements.txt`(pydantic v2, ULID 생성 라이브러리)와 `requirements-dev.txt`(pytest, hypothesis, botocore Stubber용 boto3, PyJWT, cryptography)를 만든다. langgraph·langchain·Pillow는 넣지 않는다(요구사항 12.9).
  - `pytest.ini`(pythonpath `src`, 마커 `local`, `integration`), `.env.example`(로컬 전용 예시 시드 사용자 값, 실제 계정 아님), `.gitignore`(`.env`, `.aws-sam`)를 만든다.
  - _Requirements: 12.9, 13.11_

- [x] 2. 공통 모듈 (`src/common`)
  - [x] 2.1 에러·응답·ID 모듈 구현
    - `errors.py`: `ApiError(code, status, message, details)`. 이번 범위 코드는 `VALIDATION_ERROR`(400), `UNAUTHORIZED`(401), `NOT_FOUND`(404), `IDEMPOTENCY_CONFLICT`(409), `TRY_AGAIN`(503), 임시 `INTERNAL_ERROR`(500, BE-Q23).
    - `responses.py`: `ok(status, body)`(payload 2.0 응답), `error_response(e)`(`{"error":{"code","message","details"?}}`, `details`는 `VALIDATION_ERROR`에만). 시간 값은 ISO 8601 UTC 문자열.
    - `ids.py`: `planId = "pln_" + ULID` 생성기.
    - 예외 메시지·스택·내부 식별자를 응답에 담지 않는다. 로그에는 예외 유형만 남긴다.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 4.2_

  - [x] 2.2 요청 검증 모듈 구현
    - `validation.py`: `PlaceIn`, `AuthoringIn`, `PlanCreate` pydantic 모델을 요구사항 3.1–3.3의 범위(양 끝 포함)로 정의한다. `authoring.story`는 두 모드 모두 필수(1–1000자). `durationMs`는 0 이상 정수(상한 없음, BE-Q31).
    - `to_details(err)`: pydantic 오류 위치를 `places[0].name` 표기의 `dict[str, str]`로 변환한다.
    - `aiSessionId`는 문자열 여부만 확인한다.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6_

  - [x] 2.3 JWT 사용자 식별 구현
    - `auth.py`: `get_user(event)`가 `requestContext.authorizer.jwt.claims`에서 `(sub, nickname)`만 읽는다. 본문·쿼리·헤더의 사용자 ID는 읽지 않는다. `sub`가 없으면 `ApiError("UNAUTHORIZED", 401)`이며 DB를 읽지 않는다.
    - 닉네임 클레임이 없을 때의 응답은 BE-Q17·BE-Q30 미결로 두고 `nickname = None`으로 처리한다.
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 2.4 DynamoDB 접근 모듈 구현
    - `ddb.py`: `table()`(엔드포인트는 SDK의 `AWS_ENDPOINT_URL`에 맡기고 앱 코드에서 직접 다루지 않음), `ConditionFailed(reasons)`, `transact_with_retry(items)`.
    - `TransactionConflict`는 50·100·200ms 백오프로 최대 3회 재시도 후 `ApiError("TRY_AGAIN", 503)`. `ConditionalCheckFailed`가 취소 사유에 있으면 재시도 없이 `ConditionFailed`를 올린다.
    - _Requirements: 4.9, 4.10, 4.11_

  - [x]* 2.5 Write property test for 입력 검증 경계
    - **Property 5: 검증 경계에서 유효 범위만 통과하고 실패 `details` 키는 `places[0].name` 표기**
    - Hypothesis로 `title` 40/41자, `estimatedMinutes` 9/10/240/241, `places` 0/1/3/4개, `story` 0/1/1000/1001자 경계를 생성한다.
    - **Validates: Requirements 3.1, 3.2, 3.4**

  - [x]* 2.6 Write property test for 에러 응답 형식
    - **Property 10: 모든 4xx/5xx 본문이 `{error:{code,message,details?}}`이고 `details`는 `VALIDATION_ERROR`에만 있다**
    - **Validates: Requirements 11.1, 11.2, 11.3**

  - [x]* 2.7 Write unit tests for auth·ddb
    - Property 3: 본문·쿼리에 다른 사용자 ID를 넣어도 `get_user` 결과가 JWT `sub`로 고정됨을 생성기로 확인한다. **Validates: Requirements 2.1**
    - Stubber로 `TransactionConflict` 3회 재시도 후 503 `TRY_AGAIN`, `ConditionalCheckFailed` 무재시도 `ConditionFailed`를 확인한다.
    - _Requirements: 2.1, 2.3, 4.9, 4.10, 4.11_

- [x] 3. 순수 도메인 함수 (`src/domain`)
  - [x] 3.1 원문 충실도 판정 구현
    - `fidelity.py`: `normalize`, `find_not_in_source(sources, targets)`. 토큰별 말미 조사 제거 후 근거 텍스트(공백 제거)의 부분 문자열 일치, 모든 토큰이 일치해야 통과(BE-Q25).
    - `null`·빈·공백 target은 판정하지 않고, `sources`가 비었으면 나머지 target을 모두 hit로 반환한다. hit는 입력 순서, `path`·`text`는 입력 그대로. 순수 함수(입력 불변, LLM·DB 없음).
    - `tests/fixtures/normalization.json`(동의어 사전)을 만들고 사전에 있는 동의어만 같은 표현으로 인정한다.
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8, 9.10_

  - [x] 3.2 개인정보 탐지 구현
    - `privacy.py`: `PrivacyHit(path, kind, severity)`, `scan_privacy(texts)`, `mask(text)`. `PHONE`, `EMAIL`, `RRN`, `UNIT`은 `HIGH`, `PLATE`, `LOT`, `PRIVATE_PLACE`(사전 + "~네 집" 정규식)는 `MEDIUM`(BE-Q22). `PERSON_NAME`은 구현하지 않고 항상 빈 결과(BE-Q26).
    - 빈 입력·`null`은 예외 없이 빈 목록. `mask`는 `HIGH` 부분만 가리고 재스캔 시 `HIGH` 0건.
    - 로그에는 `kind`별 개수만 남기는 헬퍼를 둔다(원문·일치 문자열 금지).
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6, 10.7_

  - [x]* 3.3 Write property test for find_not_in_source
    - **Property 8: `S ⊆ S'`이면 `hits(S') ⊆ hits(S)`(단조성), 같은 입력은 같은 결과, 입력 불변**
    - 단위 테스트: 데모 사연 기준 "골목 빵집"은 hit, "출근길 빵집"은 통과(9.9), 빈 `sources`(9.5), 빈 target(9.4), 픽스처 동의어(9.8).
    - **Validates: Requirements 9.1, 9.4, 9.5, 9.7, 9.9**

  - [x]* 3.4 Write property test for scan_privacy·mask
    - **Property 9: 전화·이메일·주민번호·동/호수 샘플은 `HIGH`, 데모 사연은 0건, `mask` 후 재스캔 시 `HIGH` 0건**
    - 단위 테스트: 차량번호·번지·비공개 장소 사전, 음성 사례, 빈 입력.
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**

- [x] 4. 응답 직렬화
  - [x] 4.1 직렬화 함수 구현
    - `responses.py`에 `serialize_plan(item, is_owner, status_override)`, `serialize_plan_summary(item, status_override)`, `serialize_claim(item)`을 추가한다. 허용 목록 방식이며 `PK`, `SK`, `claimerId`, `currentClaimId`, `dueAt`, `GSI*`, `version`, `ttl`은 어느 깊이에도 내보내지 않는다(`currentClaimId`는 내보내지 않는다, BE-Q33).
    - `metrics`는 소유자에게만. `owner`는 `{userId, nickname}`, 값이 없는 `completedAt`은 `null`로 직렬화. `PlanSummary`는 여덟 필드만(소유자여도 `metrics` 없음).
    - `serialize_claim`은 `claimId, planId, claimer{userId,nickname}, status, claimedAt, dueAt, completedAt, late` 허용 목록만 구현한다(이번 범위에서 Claim은 쓰지 않음).
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.8, 7.6_

  - [x]* 4.2 Write property test for 직렬화 허용 목록
    - **Property 4: 출력 키 집합이 허용 목록의 부분집합이고 비소유자 응답에 `metrics`가 없다**
    - **Validates: Requirements 7.6, 8.1, 8.2, 8.3, 8.8**

- [ ] 5. 계획 서비스 (`src/domain/plan_service.py`)
  - [ ] 5.1 `create_plan` 구현
    - `Idempotency-Key` 없으면 400 `VALIDATION_ERROR`(`details` 키 `Idempotency-Key`, BE-Q29). 본문 해시는 키 정렬·공백 없는 JSON의 SHA-256.
    - 키 항목이 이미 있으면(ConsistentRead) 재생: 해시 같으면 기존 Plan, 다르면 409 `IDEMPOTENCY_CONFLICT`.
    - 없으면 Plan(`attribute_not_exists(PK)`)과 Idempotency_Key_Item(`IDEM#{userId}#{key}`, `bodyHash`, `planId`, `ttl`=+24h, `attribute_not_exists(PK)`)을 `transact_with_retry` 한 번으로 저장한다. `ConditionFailed`는 키 항목을 다시 읽어 해시 비교 후 재생, 키 항목이 없으면 503 `TRY_AGAIN`.
    - 신규·재요청 모두 201(BE-Q24). Plan은 `status=OPEN`, `ownerId`=sub, `ownerNickname`, `areaId=default`, `version=1`, GSI1/GSI2 키 포함. `currentClaimId`, `claimerId`, `dueAt`, `completedAt`은 속성 자체를 쓰지 않는다. `story` 원문은 저장하지 않는다.
    - `metrics`는 `authoringMode`, `durationMs`, `addedNotInSource`(`find_not_in_source([story], places의 name·activity)`), `privacyInPublished`(Plan 텍스트 전체 `scan_privacy` 수)만 저장하고 `aiSessionId`로 AI 세션을 읽지 않는다. 재요청 시 `metrics`를 다시 계산하지 않는다.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.11, 4.12, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 3.5, 8.5_

  - [ ] 5.2 `list_plans`, `get_plan` 구현
    - `list_plans(status, limit, now)`: `status != OPEN`이면 400 `VALIDATION_ERROR`. `GSI1PK = AREA#default#STATUS#OPEN` 조회와 `STATUS#CLAIMED` 중 `dueAt < now` 항목을 합쳐 `createdAt` 내림차순, 기본 20, 최대 50(BE-Q3), 모든 `status`를 `OPEN`으로, `nextCursor: null`. `limit`이 숫자가 아니거나 범위 밖이면 20/50으로 보정한다(BE-Q32).
    - `get_plan(plan_id, user, now)`: ConsistentRead GetItem, 없으면 404. 요청자 Claim(`ACTIVE`·`COMPLETED`만)을 `myClaim`으로. `COMPLETED` 계획은 소유자·해당 실행자 외 404. 기한 지난 `CLAIMED`는 현재 실행자가 아니면 `OPEN`, 기한 내 `CLAIMED`는 실행자 정보 숨김. `claimable = !isOwner && myClaim == null && 표시 status == OPEN`.
    - Plan 갱신 헬퍼는 `version`을 정확히 1 올리고 `status` 변경 시 `GSI1PK`를 같은 쓰기에서 바꾼다(3단계가 재사용).
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 8.6, 8.7_

  - [ ]* 5.3 Write unit tests for 멱등 분기
    - Stubber 또는 로컬 에뮬레이터로 같은 키·같은 본문, 같은 키·다른 본문(409), 새 키, 동시 선점 패배(`ConditionFailed` → 재생), `TransactionConflict` 주입(재시도·503), 키 항목 없는 취소(503)를 확인한다. 헤더 누락 400(3.5)과 `metrics` 저장(5.1–5.6)도 포함한다.
    - 인메모리 가짜 테이블에 대해 Hypothesis로 임의 `(b, k)`를 n회 호출해도 Plan이 1건이고 `planId`가 같음을 확인한다(Property 2의 서비스 수준 확인, T13 판정은 11.2에서).
    - _Requirements: 4.5, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 5.6_

  - [ ]* 5.4 Write property test for 목록 정렬·필터
    - **Property 6: `list_plans`는 `createdAt` 내림차순이고 모든 `status`가 `OPEN`이며 기한 지난 `CLAIMED`는 포함, 기한 내 `CLAIMED`는 제외**
    - **Validates: Requirements 6.3, 6.4, 6.5**

  - [ ]* 5.5 Write property test for 상세 상태 규칙
    - **Property 7: `claimable = !isOwner ∧ myClaim = null ∧ shown = OPEN`, `COMPLETED` 계획은 소유자·실행자 외 404, `ABANDONED`·`EXPIRED` Claim만 있으면 `myClaim = null`**
    - **Validates: Requirements 7.4, 7.5, 7.7, 7.8, 7.10, 7.11**

- [ ] 6. Lambda 핸들러와 라우트 (`src/handlers`)
  - [ ] 6.1 `me.py`, `pre_signup.py` 구현
    - `me.py`: `GET /me`가 `{userId, nickname, unreadInboxCount: 0}`을 반환한다. HaruTable을 읽지 않는다(BE-Q30). `ApiError`·`ValidationError`·예상치 못한 예외를 에러 형식으로 변환한다.
    - `pre_signup.py`: `autoConfirmUser`, `autoVerifyEmail`만 `true`로 바꾸고 나머지 이벤트를 그대로 반환한다.
    - _Requirements: 2.4, 2.5, 2.7, 1.4, 11.1, 11.4_

  - [ ] 6.2 `plans.py`와 라우트 목록 구현
    - `plans.py`: `POST /plans`(헤더 `Idempotency-Key`, pydantic 검증 실패는 `to_details`로 400), `GET /plans`(`status`, `limit` 쿼리), `GET /plans/{planId}`를 라우팅하고 서비스를 호출한다. 예외는 에러 형식으로 변환한다.
    - `src/handlers/routes.py`에 경로 목록을 한 곳에 둔다(`GET /me`, `POST /plans`, `GET /plans`, `GET /plans/{planId}`). 클레임·AI·수신함 경로는 넣지 않는다.
    - _Requirements: 3.4, 3.5, 4.1, 6.1, 7.1, 11.1, 12.8_

  - [ ]* 6.3 Write tests for 핸들러
    - **Property 11: PreSignUp 출력은 두 플래그 `true`이고 나머지 필드가 입력과 같다. Validates: Requirements 1.4**
    - `GET /me`가 DB를 호출하지 않음, `sub` 없는 이벤트 401, 예상치 못한 예외가 500 `INTERNAL_ERROR`이고 응답에 예외 메시지가 없음, 핸들러 응답 시간 값이 ISO 8601 UTC임을 확인한다.
    - _Requirements: 1.4, 2.3, 2.7, 11.4, 11.5, 11.6_

- [ ] 7. Checkpoint - 단위 테스트 통과 확인
  - `pytest tests/unit`을 실행해 모두 통과하는지 확인하고, 질문이 있으면 사용자에게 묻는다.

- [ ] 8. SAM 템플릿 (`template.yaml`, `samconfig.toml`)
  - [ ] 8.1 `template.yaml` 작성
    - `Globals.Function`: Python 3.12, VPC 밖, 환경 변수 `TABLE_NAME`, `AREA_ID=default`, `CLAIM_DURATION_DAYS=3`, `LANGSMITH_TRACING=false`, `LANGCHAIN_TRACING_V2=false`. `AWS_ENDPOINT_URL`, `AWS_EMF_ENVIRONMENT`은 정의하지 않는다.
    - `HaruTable`(PK/SK, GSI1, GSI2, TTL `ttl`, on-demand), `UserPool`(이메일 사용자 이름, `nickname` 필수, Cognito 기본 비밀번호 정책 BE-Q27, PreSignUp 트리거), `UserPoolClient`(시크릿 없음, `ALLOW_USER_PASSWORD_AUTH`·`ALLOW_USER_SRP_AUTH`·`ALLOW_REFRESH_TOKEN_AUTH`).
    - `HttpApi`: 스테이지 `$default`, 기본 JWT authorizer(issuer, audience = ClientId, `Authorization` 헤더), CORS(`AllowedOrigins` 파라미터 기본 `http://localhost:5173`, 헤더 `Authorization`·`Content-Type`·`Idempotency-Key`, 메서드 `GET`·`POST`·`PUT`·`OPTIONS`).
    - `MeFunction`(DynamoDB 권한 없음), `PlansFunction`(`HaruTable`과 `index/*`에 `GetItem`·`PutItem`·`Query`만), `PreSignUpFunction`과 Cognito 호출 권한. 순환 참조는 `SourceArn` 와일드카드로 끊는다. 이벤트 경로는 `routes.py`와 같다.
    - Outputs: `ApiUrl`, `UserPoolId`, `UserPoolClientId`. `AiCardFunction` 등 3단계 이후 리소스, CloudFront, 웹 버킷은 만들지 않는다.
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 12.1, 12.2, 12.3, 12.4, 12.5, 12.8, 12.9_

  - [ ] 8.2 `samconfig.toml`과 템플릿 검증
    - `dev`, `demo` 환경을 두고 `AllowedOrigins`를 환경별로 지정한다(CloudFront 도메인 없음).
    - `sam validate --lint`를 실행해 종료 코드 0을 확인하고, `sam build` 산출물에 langgraph·langchain·Pillow가 없는지 확인한다.
    - _Requirements: 12.6, 12.7, 12.9_

- [ ] 9. 로컬 개발 환경 (`docker-compose.yml`, `local/`)
  - [ ] 9.1 docker compose와 init 스크립트 작성
    - `docker-compose.yml`: `aws`(`floci/floci:2.5.0-compat` 태그 고정, 4566, init 마운트 `./local/init:/etc/floci/init/ready.d`), `api`(`./local/adapter` 빌드, 3000, `.env`). `LANGSMITH_TRACING=false`, `LANGCHAIN_TRACING_V2=false` 명시. SQS·S3·ollama는 넣지 않는다.
    - init: `HaruTable`(GSI1·GSI2·TTL `ttl`), `HaruAgentCheckpoints`(PK/SK, TTL `ttl`, 테이블만), 유저 풀·앱 클라이언트, 시드 사용자 3명(지연, 수현, 민준: 로컬 전용 예시 값, BE-Q28), 마지막에 `LOCAL_JWT_ISSUER`, `LOCAL_JWKS_URL`, 풀 ID, 클라이언트 ID 출력. 단계 실패 시 단계 이름을 출력하고 0이 아닌 코드로 종료.
    - _Requirements: 13.1, 13.2, 13.3, 13.10, 13.11_

  - [ ] 9.2 로컬 HTTP 어댑터 구현
    - `local/adapter/Dockerfile`, `app.py`: 요청을 payload 2.0 이벤트로 변환하고 ID 토큰의 `iss`, `aud`, `exp`, `token_use=id`, 서명을 검증한 뒤 `requestContext.authorizer.jwt.claims`를 주입해 같은 핸들러를 호출(`FakeContext(remaining_ms=27000)`). 실패 시 핸들러 호출 없이 에러 형식 401 `UNAUTHORIZED`.
    - `STAGE=local`에서만 `POST /dev/token {userId, nickname}` → `{idToken}`을 등록하고, 그 외에는 등록하지 않는다. CORS preflight `OPTIONS`는 인증 없이 `http://localhost:5173`에 204. 라우팅은 `routes.py`를 사용한다. SQS 폴러는 넣지 않는다. 어댑터는 SAM 배포물에 포함하지 않는다.
    - _Requirements: 13.4, 13.5, 13.6, 13.7, 13.8_

  - [ ]* 9.3 Write test for 라우트 목록 일치
    - `template.yaml`의 이벤트 경로와 어댑터가 쓰는 `routes.py` 목록이 한쪽에만 있는 경로 없이 일치하는지 단위 테스트한다. 한쪽에만 있으면 실패해야 한다.
    - _Requirements: 13.9_

- [ ] 10. 로컬 통합 테스트
  - [ ]* 10.1 Write local integration tests (`tests/local/`)
    - 시드 사용자 토큰(또는 dev JWT)으로 `GET /me` 닉네임이 시드 값과 같은지 확인한다(BE-Q17, 결과는 PR에 기록).
    - `POST /plans` → `GET /plans/{id}` → `GET /plans`, 같은 키 3회 호출 시 Plan 1건. 어댑터 401 경로와 `/dev/token`, preflight 204. `HaruAgentCheckpoints` 테이블 존재와 TTL만 확인한다.
    - 이 결과는 T 시나리오 합격 근거로 쓰지 않는다(BE-Q15).
    - _Requirements: 13.12, 13.13, 2.4, 4.5, 13.5, 13.8_

- [ ] 11. 배포 스택 통합 테스트 (`tests/integration/`)
  - [ ] 11.1 T1 권한 테스트 작성 (`test_authz.py`)
    - 환경 변수(`API_URL` 등)로 `dev` 스택을 가리키고, `GET /me`, `POST /plans`, `GET /plans`, `GET /plans/{planId}`를 `Authorization` 없이 호출해 모두 401 `UNAUTHORIZED`이고 실패 0건임을 확인한다. 만료·잘못된 토큰 사례도 포함한다.
    - **Property 1: 등록된 모든 경로가 인증 없이 401. 판정은 AWS 스택에서만 한다. Validates: Requirements 1.6, 1.7, 7.2, 14.1**
    - _Requirements: 1.6, 1.7, 7.2, 14.1, 14.6_

  - [ ] 11.2 T13 멱등 테스트와 가입 직후 로그인 테스트 작성 (`test_idempotency.py`)
    - `AdminCreateUser`로 테스트 사용자를 만들고 ID 토큰을 발급해, 같은 `Idempotency-Key`·같은 본문 `POST /plans` 3회가 모두 같은 `planId`를 반환하고 `GET /plans/{id}`와 DynamoDB 항목 수로 Plan 1건임을 확인한다. 같은 키·다른 본문은 409 `IDEMPOTENCY_CONFLICT`이고 처음 Plan이 변하지 않음을 확인한다. 동시 호출 사례도 포함한다.
    - `SignUp`(이메일, 비밀번호, `nickname`) 후 인증 코드 없이 `InitiateAuth`가 성공하고 ID 토큰 `nickname`이 가입 값과 같은지 확인한다. 테스트가 만든 사용자·항목은 정리한다.
    - **Property 2: 임의 유효 본문·키에 대해 n회 호출해도 Plan 1건, 다른 본문은 409. Validates: Requirements 4.5, 4.7, 4.8, 14.2, 14.3**
    - _Requirements: 1.5, 4.5, 4.7, 4.8, 14.2, 14.3, 14.4, 14.6_

- [ ] 12. Checkpoint - 배포 전 전체 테스트 확인
  - `pytest tests/unit`과 `sam validate --lint`가 통과하는지 확인하고, 로컬 환경을 쓰는 경우 `tests/local`도 확인한다. 질문이 있으면 사용자에게 묻는다.

- [ ] 13. Checkpoint - dev 스택 배포와 T1·T13 판정 (사용자 승인 필요)
  - 배포는 되돌리기 어려운 작업이므로 에이전트가 임의로 실행하지 않는다. 사용자에게 `sam build`, `sam deploy --config-env dev` 실행(또는 승인)을 요청하고, 사용자가 AWS 자격 증명과 대상 계정·리전을 확인한 뒤 진행한다.
  - 배포 후 `ApiUrl`, `UserPoolId`, `UserPoolClientId` 출력이 실제 리소스와 일치하는지 확인한다(12.3).
  - 사용자가 실행한 `tests/integration/test_authz.py`(T1)와 `tests/integration/test_idempotency.py`(T13) 결과가 모두 통과하는지 확인한다. 통과 결과는 `dev` 스택 기준으로만 인정한다(BE-Q15).
  - `docs/08-open-questions.md`에 등록된 BE-Q22–BE-Q33 중 이번 구현으로 확정할 항목이 있는지 사용자에게 확인한다. 계약 변경(BE-Q23, BE-Q24, BE-Q29, BE-Q33)은 §7.2 절차(프론트엔드 리뷰)를 따른다.
  - _Requirements: 12.3, 14.1, 14.2, 14.3, 14.4, 14.6, 14.7_

## Notes

- `*` 표시 하위 작업은 선택이며 MVP에서 건너뛸 수 있다. T1·T13 통합 테스트(11.1, 11.2)와 배포 확인(13)은 완료 기준이라 선택이 아니다.
- 각 작업은 요구사항 번호로 추적한다. 속성 기반 테스트는 설계의 Correctness Properties(P1–P11)와 일대일로 연결한다(P1·P2는 11.1·11.2의 dev 스택 테스트, P3는 2.7, P4는 4.2, P5는 2.5, P6은 5.4, P7은 5.5, P8은 3.3, P9는 3.4, P10은 2.6, P11은 6.3).
- 로컬(Floci) 테스트는 개발 편의용이며 T1·T13 합격 근거가 아니다. PreSignUp 자동 확인은 로컬 에뮬레이터에서 동작하지 않으므로 핸들러 단위 테스트와 `dev` 스택에서 확인한다.
- 장기 실행 프로세스(`docker compose up`)는 에이전트가 실행하지 않고 사용자가 직접 실행한다.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "3.1", "3.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "2.5", "3.3", "3.4", "4.1"] },
    { "id": 3, "tasks": ["2.6", "2.7", "4.2", "5.1", "8.1", "9.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "6.1", "8.2"] },
    { "id": 5, "tasks": ["5.4", "5.5", "6.2"] },
    { "id": 6, "tasks": ["6.3", "9.2"] },
    { "id": 7, "tasks": ["7"] },
    { "id": 8, "tasks": ["9.3", "10.1", "11.1", "11.2"] },
    { "id": 9, "tasks": ["12"] },
    { "id": 10, "tasks": ["13"] }
  ]
}
```
