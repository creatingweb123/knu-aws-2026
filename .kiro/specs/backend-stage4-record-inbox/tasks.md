# Implementation Plan: backend-stage4-record-inbox

## Overview

백엔드 4단계(수신함 4종, `unreadInboxCount`, `InboxFunction`, 방문 기록 조회)를 1–3단계 코드 위에 `backend/` 아래 Python 3.12로 더한다.

작업은 design.md "구현 순서와 BE-Q46 분리"대로 두 묶음으로 나눈다.
- **묶음 A (작업 1–12, 계약 변경 없음)**: 공통 모듈 → 수신함 서비스·핸들러·`GET /me` → 라우트 → 단위 Checkpoint → SAM 템플릿 → SAM Checkpoint → 로컬 통합 테스트 → 로컬 Checkpoint → AWS 대상 테스트 작성 → 회귀 Checkpoint → 인계 문서 → 묶음 A 커밋.
- **묶음 B (작업 13–19, `GET /claims/{claimId}/record`, BE-Q46)**: 스냅샷 읽기 헬퍼 → 기록 조회 → 단위·SAM Checkpoint → 로컬 → AWS 대상 테스트 → 회귀·문서 → 묶음 B 커밋. A의 커밋 뒤에 별도 커밋으로 두고, BE-Q46 승인 전에는 PR에 넣지 않는다.
- **작업 20 (승인 대기)**: docs/03 §3.4 계약 변경과 그 뒤 반영.

공통 규칙
- 3단계 트랜잭션(`claim_plan`, `abandon`, `put_record`, `complete_claim`, `complete_by_user`)과 `common/ddb.py`의 `transact_with_retry`·`BACKOFF_SECONDS`·`ConditionFailed`·`_cancellation_codes`는 바꾸지 않는다(Requirement 10.4, G1–G4).
- API 계약(docs/03)과 키 설계(docs/02 §2.6)는 바꾸지 않는다. docs/03 §3.4에 503 `TRY_AGAIN`을 명시하는 수정은 프론트엔드 담당 승인 전에는 하지 않는다(작업 20, BE-Q46, docs/07 §7.2).
- AWS 리소스 생성, `sam deploy`, AWS 통합 테스트 실행, 실제 AWS 데이터 삭제는 하지 않는다. AWS 검증 항목은 통합 테스트 코드로 작성하고, T1·T2·T17과 `GET /record` 동시 조회 판정은 AWS 담당이 Dev_Stack(`haru-dev`)에서 한다(BE-Q15, docs/07 §7.5·§7.8). 로컬 결과는 T 판정 근거가 아니다.
- SAM CLI가 없으면 공식 설치 방법(AWS SAM CLI Linux x86_64 설치 프로그램)으로 설치하고 `sam --version`으로 확인한 뒤 `sam validate --lint`·`sam build`를 실행한다.
- Docker Compose 로컬 환경은 직접 띄워(`docker compose up -d --build`) 로컬 통합 테스트를 실행한다.
- 속성 기반 테스트(Property 16–24)는 필수다. Hypothesis 최소 100회, 태그 `Feature: backend-stage4-record-inbox, Property {n}`.
- 작업 그룹마다 테스트를 실행하고, 실패하면 원인을 고친 뒤 다음 그룹으로 넘어간다.
- 프론트엔드 작업 트리(`/home/hwkim/knu-aws-2026`)는 읽기만 한다.
- 미결 항목은 requirements·design의 임시 결정으로 구현하고 코드 주석과 PR에 번호를 남긴다: BE-Q1, BE-Q17, BE-Q23, BE-Q30(앞부분 해소), BE-Q34, BE-Q42–BE-Q48.
- 원격 push와 PR 생성은 최종 검토 뒤 사용자 확인을 받고 한다.
- 의존성은 각 그룹 머리의 `선행:` 줄과 끝의 Task Dependency Graph로 적는다.

## Tasks

> 이 브랜치(`feat/be-4-inbox`)는 묶음 A(작업 1–12)만 완료·검증한 상태다. 작업 13–19(`GET /record`)는 `feat/be-4-record-inbox`의 `f3626c0`에 구현돼 있고 여기서는 미완료로 둔다. 작업 20은 승인 대기다.

### 묶음 A: 수신함·미확인 수 (계약 변경 없음)

- [x] 1. 공통 모듈 확장 (`src/common`)
  - 선행: 없음
  - [x] 1.1 `errors.py`에 `REPLY_ALREADY_SENT`, `validation.py`에 `Reply` 추가
    - `errors.py`: `REPLY_ALREADY_SENT`(409), 기본 메시지 "이미 답장을 보냈어요."(프론트 MSW와 같은 문구). 기존 코드·상태 조합은 바꾸지 않는다.
    - `validation.py`: `class Reply(BaseModel)`(`_STRICT`, `text` 1–100자, 앞뒤 공백 자르지 않음, 코드 포인트 길이). `_FIELD_MESSAGES["text"] = "1–100자로 입력해 주세요."`. `RecordPut`·`CompleteIn`은 그대로 둔다.
    - _Requirements: 6.4, 10.2 · BE-INBOX-04, docs/03 §3.6, FE-Q19_

  - [x] 1.2 `responses.py`에 수신함 직렬화 추가
    - `INBOX_FIELDS`, `serialize_reply`, `serialize_inbox_item`, `serialize_inbox_record(record)`를 design "Components and Interfaces"대로 추가한다. `serialize_record_view`는 묶음 B(14.1)에서 추가한다.
    - `serialize_inbox_item`: `PK`·`SK`·`ownerId`를 내보내지 않음(BE-Q43), `claimerNickname`·`reply` 없으면 `null`(BE-Q17·BE-Q45), `hasPhoto`·`read`는 `bool`.
    - `serialize_inbox_record`: `{letter, deliveredAt, photoUrl: None, photoCaption: None}`(BE-Q42).
    - _Requirements: 4.6, 7.1, 7.2, 7.3, 7.4 · BE-PLAN-08, BE-Q17, BE-Q42, BE-Q43, BE-Q45_

  - [x] 1.3 에러·검증·직렬화 단위 테스트
    - `tests/unit/test_errors.py`: `REPLY_ALREADY_SENT`가 docs/03 §3.6과 같은 409, 기존 코드 표 불변.
    - `tests/unit/test_validation.py`: `Reply` 경계 0/1/100/101자, 비문자열, `text` 없음, 앞뒤 공백 유지, `details` 키 `text`, 본문이 객체가 아니면 `body`.
    - `tests/unit/test_serialization.py`: InboxItem 응답에 `PK`·`SK`·`ownerId` 없음(BE-Q43), `reply` 없으면 `null`·있으면 `{text, sentAt}`만, `claimerNickname` 없으면 `null`(BE-Q17·BE-Q45), 상세 `record`의 `photoUrl`·`photoCaption` null(BE-Q42), `sentAt`·`createdAt`·`deliveredAt`이 밀리초 3자리 UTC.
    - _Requirements: 4.6, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 10.2 · BE-Q17, BE-Q42, BE-Q43, BE-Q45, FE-Q19_

  - [x] 1.4 Write property test for 수신함 직렬화 (`tests/unit/test_serialization.py`)
    - **Property 22: 수신함·기록 직렬화는 허용 목록을 벗어나지 않고 round-trip이 안정하다**
    - 생성기: 선택적 `reply`·`claimerNickname`, 임의 추가 속성을 가진 InboxItem. 출력 키 ⊆ 허용 목록, 불리언 타입, null 규칙, `json.loads(json.dumps(x)) == x`, 상세 `record` 사진 필드 null.
    - **Validates: Requirements 4.6, 7.1, 7.2, 7.3, 7.4, 7.5**

- [x] 2. 수신함 서비스·핸들러와 `GET /me` 미확인 수
  - 선행: 1.1, 1.2
  - [x] 2.1 `domain/inbox_service.py` 구현
    - `_inbox_key`, `_query_mine`(기본 테이블 Query, `PK = USER#{sub}`, `SK begins_with INBOX#`, `ConsistentRead=True`, `LastEvaluatedKey` 끝까지, `ownerId == sub`만 남김), `list_items`(`createdAt` 역순), `unread_count`(`read is False`만 셈), `get_detail`, `mark_read`, `reply`, `InboxIntegrityError`를 design 의사코드대로 만든다. `FilterExpression`·`Select=COUNT`·GSI는 쓰지 않는다.
    - `get_detail`: InboxItem ConsistentRead GetItem, 없거나 `ownerId ≠ sub`면 404. Plan·Record는 `plan_service._get`(ConsistentRead) 재사용. Plan·Record가 없거나 Record에 `deliveredAt`이 없으면 `InboxIntegrityError`(500, BE-Q47). `read`를 바꾸지 않는다.
    - `mark_read`: `SET #read = :true`, 조건 `attribute_exists(PK) AND #owner = :me`. `ConditionalCheckFailedException`이면 재조회 없이 404. 이미 읽음이어도 204(BE-Q44).
    - `reply`: `SET #reply = :reply`(`{text, sentAt: iso_utc}`), 조건 `#owner = :me AND attribute_not_exists(#reply)`. 실패하면 ConsistentRead 재조회로 없음·남의 것 → 404, `reply` 있음 → 409 `REPLY_ALREADY_SENT`, 원인 불명 → `InboxIntegrityError`.
    - Plan·Claim·Record에는 쓰지 않는다. 로그에 본문·사용자 ID를 남기지 않는다.
    - _Requirements: 3.1–3.5, 4.2, 4.3, 4.5, 4.7, 4.8, 5.1–5.4, 6.1–6.3, 6.5, 6.6, 8.2, 8.3, 8.7, 10.3, 10.7, 10.8 · BE-INBOX-01–04, BE-AUTH-05, G4, BE-Q23, BE-Q44, BE-Q47, T17_

  - [x] 2.2 `handlers/inbox.py` 구현
    - `_list`, `_detail`, `_read`(본문 읽지 않음, `ok(204, None)`), `_reply`(`Reply.model_validate`를 DB 접근 전에, 201 `{reply}`), 모듈 `ROUTES`, `@api_handler handler`. 모든 함수 첫 줄 `get_user(event)`.
    - `_detail`의 `plan`은 `serialize_plan(plan, is_owner=plan.get("ownerId") == user.id)`, `item`은 `serialize_inbox_item`, `record`는 `serialize_inbox_record`.
    - _Requirements: 3.1, 4.1, 4.4, 4.6, 5.1, 6.1, 6.4, 7.1, 9.6, 10.1 · BE-INBOX-01–04, BE-AUTH-04, BE-NFR-05_

  - [x] 2.3 `handlers/me.py`의 `unreadInboxCount` 계산
    - `_me`가 `inbox_service.unread_count(user)`를 쓴다. 머리말의 "unreadInboxCount는 0 고정" 문장을 지운다(BE-Q30 앞부분 해소). `GET /me/claims`와 `routeKey` 없는 이전 이벤트 처리는 그대로 둔다.
    - _Requirements: 8.1, 8.3–8.6 · BE-AUTH-05, BE-CLAIM-07, BE-Q17, BE-Q30_

  - [x] 2.4 수신함 서비스 단위 테스트 (`tests/unit/test_inbox_service.py`, 신규)
    - moto를 쓴다(조건식을 실제로 평가). 3단계 완료 트랜잭션이 만든 InboxItem을 쓰는 사례를 하나 이상 둔다.
    - 목록: `createdAt` 역순, 빈 목록, 다른 사용자 항목 제외, 키와 `ownerId`가 어긋난 항목 제외, 여러 페이지 합치기.
    - 상세: 200 형태, InboxItem GetItem에 `ConsistentRead=True`(스파이), `plan`에 소유자 `metrics`, `record`가 Record에서 옴, 없음·`ownerId` 불일치 각각 404, Plan 또는 Record 없음 → `InboxIntegrityError`, 조회 뒤 `read` 불변.
    - 읽음: 204·`read = true`, 없음·`ownerId` 불일치 404이고 항목을 만들지 않음, 재요청 204, `reply` 불변, `UpdateItem` 인자의 `ConditionExpression`·`UpdateExpression`(스파이) 단언.
    - 답장: 201 `{text, sentAt}`(밀리초 3자리), 두 번째 409 `REPLY_ALREADY_SENT`, 없음·`ownerId` 불일치 404(남의 항목에 답장이 있어도 404), 조건식 단언, `read` 불변, 저장 값이 첫 요청 값.
    - 미확인 수: Query에 `ConsistentRead=True`(스파이), `read is False`만 셈(속성 없음·비불리언 제외), 다른 사용자·어긋난 `ownerId` 제외, 여러 페이지, 읽음 뒤 1 감소.
    - _Requirements: 3.1–3.5, 4.1–4.5, 4.7, 4.8, 5.1–5.4, 6.1–6.3, 6.5, 6.6, 8.2–8.4, 8.7, 10.7, 11.1 · BE-INBOX-01–04, BE-AUTH-05, BE-Q44, BE-Q47, T17_

  - [x] 2.5 수신함·`GET /me` 핸들러 단위 테스트 (`tests/unit/test_handlers_inbox.py`, 신규)
    - 4개 경로 응답 형태와 상태(200·204 본문 없음·201), 답장 검증 실패가 DB 접근 전 400(`details.text`/`body`), `REPLY_ALREADY_SENT` 에러 본문 형식, `InboxIntegrityError` → 500 `INTERNAL_ERROR`이고 응답·로그에 메시지·본문 없음.
    - 인증: 수신함 4개 경로와 `GET /me`에 `token_use != "id"` 이벤트(액세스 토큰 모양)와 `sub` 없는 이벤트를 넣으면 DB 호출 없이 401 `UNAUTHORIZED`(계약 에러 형식).
    - `GET /me`: `unreadInboxCount`가 계산 값, `userId`·`nickname`은 JWT에서, 본문의 다른 `userId` 무시.
    - _Requirements: 4.1, 4.8, 6.4, 8.1, 8.5, 9.6, 10.1, 10.8, 11.1 · BE-AUTH-03, BE-AUTH-04, BE-Q23, T1_

  - [x] 2.6 `unreadInboxCount == 0` 단언 회귀 수정
    - `tests/unit/test_handlers.py` `test_me_returns_claims_without_db`, `tests/unit/test_handlers_claims.py` `test_me_still_reads_no_db`, `tests/unit/test_adapter.py`의 `GET /me` 사례, `tests/local/test_local_flow.py` `test_me_with_dev_jwt`.
    - `GET /me`가 이제 Query를 부르므로 DB 금지 픽스처 대신 빈 테이블 픽스처를 쓰고, 수신함이 빈 사용자의 기대값 `unreadInboxCount == 0`을 유지한다. 테스트 이름에 "without_db"·"no_db"가 남으면 실제 동작에 맞게 바꾼다. `routeKey` 없는 이전 이벤트 사례는 유지한다.
    - `test_local_flow.py`는 8번 Checkpoint에서 실행해 확인한다.
    - _Requirements: 8.1, 8.6, 11.1, 11.2 · BE-AUTH-05, BE-Q30_

  - [x] 2.7 Write property test for 수신함 목록 (`tests/unit/test_inbox_properties.py`, 신규)
    - **Property 18: 수신함 목록은 요청자 항목만 createdAt 역순으로 돌려준다**
    - FakeTable(임의 `page_size`) + 여러 owner·어긋난 `ownerId`·임의 `createdAt`의 InboxItem 집합.
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

  - [x] 2.8 Write property test for 수신함 단건 접근 (`tests/unit/test_inbox_properties.py`)
    - **Property 19: 수신함 단건 접근은 소유자에게만 허용되고 조회는 쓰지 않는다**
    - **Validates: Requirements 4.3, 4.7, 5.2, 6.2**

  - [x] 2.9 Write property test for 읽음 멱등 (`tests/unit/test_inbox_properties.py`)
    - **Property 20: 읽음 처리는 멱등하고 read만 바꾼다**
    - **Validates: Requirements 5.1, 5.3, 5.4, 10.7**

  - [x] 2.10 Write property test for 답장 1회 (`tests/unit/test_inbox_properties.py`)
    - **Property 21: 답장은 최대 한 번만 저장되고 reply만 바꾼다**
    - 유효·무효 `text` 열. 첫 유효 호출만 201, 이후 409, 무효는 400이고 불변. 핸들러 경유로 검증 경로까지 확인한다.
    - **Validates: Requirements 6.1, 6.3, 6.4, 6.6, 10.7**

  - [x] 2.11 Write property test for 미확인 수 (`tests/unit/test_inbox_properties.py`)
    - **Property 23: 미확인 수는 요청자의 안 읽은 항목 수와 같다**
    - **Validates: Requirements 8.1, 8.2, 8.7**

- [x] 3. 라우트와 로컬 어댑터 (수신함 경로 4개)
  - 선행: 2.2, 2.6
  - [x] 3.1 `handlers/routes.py`에 수신함 경로 4개 추가
    - `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply` → `handlers.inbox.handler`. 머리말을 지금까지 구현한 경로에 맞게 고친다(`GET /claims/{claimId}/record`는 BE-Q46 묶음).
    - `tests/unit/test_handlers.py`: 경로 집합 테스트에 4개를 더한다. `test_missing_sub_is_401_without_db` 매개변수에 수신함 핸들러를 더한다.
    - _Requirements: 9.1, 9.5, 9.6 · docs/02 §2.3, BE-AUTH-03, T1_

  - [x] 3.2 로컬 어댑터 경로 확인 (`tests/unit/test_adapter.py`)
    - `local/adapter/app.py`는 `ROUTES`에서 경로 표를 만들므로 고치지 않는다.
    - `test_routes_come_from_routes_py`가 새 경로까지 일치. `POST /inbox/x/read`가 `GET /inbox/{itemId}`로 가지 않음, `/inbox/x`와 `/inbox/x/read` 구분 사례를 더한다.
    - _Requirements: 9.1_

- [x] 4. Checkpoint - 묶음 A 단위 테스트
  - `pytest tests/unit` 전체 실패 0건. 3단계 G1–G4 관련 테스트(`test_claim_service_moto.py`, `test_claim_properties.py`의 Property 13–15, `test_ddb.py`), `test_auth.py`, `test_integration_cleanup.py` 포함.
  - _Requirements: 10.4–10.6, 11.1 · G1–G4_

- [x] 5. SAM 템플릿 (`InboxFunction`)
  - 선행: 3.1, 4
  - [x] 5.1 `template.yaml` 변경
    - `InboxFunction` 신규: `Handler: handlers.inbox.handler`, 정책 한 문장 `dynamodb:GetItem`·`Query`·`UpdateItem`, `Resource: !GetAtt HaruTable.Arn`(`index/*` 없음). 이벤트 `ListInbox`, `GetInboxItem`, `ReadInboxItem`, `ReplyInboxItem`. 이벤트에 `Auth`를 두지 않는다.
    - `MeFunction`: 권한·이벤트 불변, 주석을 "GET /me는 HaruTable 기본 테이블 Query로 미확인 수를 센다"로 고친다. `Description`을 지금까지의 범위로 고친다.
    - Globals·CORS·Outputs·테이블·`src/requirements.txt`는 바꾸지 않는다.
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 9.7, 10.3 · BE-INFRA-06, BE-Q30_

  - [x] 5.2 `tests/unit/test_template.py` 단언 추가
    - `test_iam_least_privilege`에 `InboxFunction`의 `Action` = `{GetItem, Query, UpdateItem}`, `Resource` = `HaruTable.Arn`만을 더한다. 기존 함수 권한 단언은 그대로 두어 불변을 확인한다.
    - _Requirements: 9.1–9.5, 9.7 · BE-INFRA-06_

  - [x] 5.3 SAM CLI 설치 확인과 템플릿 검사·빌드
    - `sam --version`이 없으면 공식 설치 프로그램(`aws-sam-cli-linux-x86_64.zip`, 체크섬 확인, `./sam-installation/install`)으로 설치하고 버전을 확인한다. 루트 권한이 없으면 같은 설치 프로그램의 `--install-dir`·`--bin-dir`로 사용자 디렉터리에 설치한다.
    - `cfn-lint template.yaml`, `sam validate --lint`, `sam build`를 실행한다. 빌드 산출물에 langgraph·langchain·Pillow가 없는지 본다. `sam deploy`는 실행하지 않는다.
    - _Requirements: 9.7, 9.8_

- [x] 6. Checkpoint - SAM 검증
  - `cfn-lint` 0건, `sam validate --lint` 통과, `sam build` 성공, `pytest tests/unit/test_template.py` 통과.
  - _Requirements: 9.8_

- [x] 7. 로컬 통합 테스트 작성 (수신함 흐름)
  - 선행: 3.1, 6
  - [x] 7.1 `tests/local/test_local_inbox.py` 작성 (마커 `local`)
    - 흐름: 계획자 계획 생성 → 실행자 이어받기 → 글 저장 → 완료 → 계획자 `GET /me` 미확인 1 → `GET /inbox` 1건 → 상세(사진 필드 null) → 읽음 204 → `GET /me` 미확인 0 → 답장 201 → 두 번째 답장 409 `REPLY_ALREADY_SENT`. 실행자의 `GET /inbox/{itemId}` 404도 확인한다. `GET /record` 단계는 묶음 B(16.1)에서 더한다.
    - 기존 `tests/local/conftest.py`의 `call()`(3개 값 반환)·`dev_token`을 쓴다.
    - _Requirements: 11.2 · BE-Q15_

- [x] 8. Checkpoint - 로컬 통합 테스트 (묶음 A)
  - `backend/`에서 `docker compose up -d --build`로 Local_Env를 직접 띄우고 `pytest -m local tests/local`을 실행해 기존 16건(2.6에서 고친 `test_local_flow.py` 포함)과 추가분이 모두 통과하는지 확인한다. 실패하면 원인을 고친 뒤 다시 실행한다. 건수·날짜·기준 커밋을 기록한다. T 판정 근거는 아니다(BE-Q15).
  - _Requirements: 11.2 · BE-Q15_

- [x] 9. AWS 스택 대상 테스트 작성 (묶음 A, 실행·배포는 AWS 담당)
  - 선행: 3.1, 8
  - [x] 9.1 T1 확장 (`tests/integration/test_authz.py`)
    - `_concrete`가 `{itemId}`도 없는 값으로 바꾸게 한다. `test_all_routes_reject_missing_or_bad_tokens`는 `ROUTES`를 돌므로 수신함 경로가 자동으로 포함된다(상태 401만).
    - `test_access_token_is_rejected`를 `GET /me` 외에 `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply`로 넓혀 모두 401 `UNAUTHORIZED`(계약 에러 형식)인지 확인한다(`GET /record`는 17.1).
    - _Requirements: 9.5, 9.6, 10.1, 11.8 · T1_

  - [x] 9.2 T2 역할별 권한 테스트 (`tests/integration/test_authz.py`)
    - requirements "T2 역할별 기대 결과" 표 중 `GET /claims/{claimId}/record` 행을 뺀 칸을 Planner(A)·Claimer(C)·Third_Party(B)로 확인한다(`GET /record` 행은 17.2). 포기 200은 별도 Claim으로 확인한다. 없는 `claimId`·`itemId`는 모든 역할에서 404.
    - 403·404 본문에 A의 `letter`·`reply.text`·Plan 필드, C의 글이 없음. 403 뒤 Claim `status`·Record `letter`·`deliveredAt` 불변, 404 뒤 InboxItem `read`·`reply` 불변을 ConsistentRead(BE-Q38)로 확인한다. 결과는 `save_result`로 남긴다.
    - _Requirements: 3.4, 3.5, 4.3, 5.2, 6.2, 8.7, 11.3 · T2, BE-NFR-02, G5, BE-Q38_

  - [x] 9.3 T17 답장 테스트 (`tests/integration/test_inbox.py`, 신규)
    - 첫 답장 201, 두 번째 409 `REPLY_ALREADY_SENT`. 별도 InboxItem에 10스레드 동시 답장에서 201 정확히 1건·나머지 409, 저장 `reply`가 201 응답 값(ConsistentRead 조회). `save_result`로 남긴다.
    - _Requirements: 6.1, 6.3, 11.3 · T17, BE-Q38_

  - [x] 9.4 `_cleanup` 재사용 확인
    - 9.1–9.3이 만든 사용자·계획·멱등 키·수신함 파티션이 `created_users`·`created_subs`·`created_plan_ids`·`created_idem_pks`로 등록되는지 코드로 확인한다. `_cleanup`은 고치지 않는 것이 기본이다.
    - `pytest tests/unit/test_integration_cleanup.py` 통과, `pytest -m integration tests/integration --collect-only`로 수집 오류만 확인한다(실행하지 않는다).
    - _Requirements: 11.4_

- [x] 10. Checkpoint - 묶음 A 회귀
  - `pytest tests/unit` 실패 0건, 8번 로컬 결과 유지, 통합 테스트 수집 성공. 3단계 트랜잭션 함수와 `transact_with_retry`에 diff가 없는지 `git diff`로 본다.
  - _Requirements: 10.1, 10.3–10.6, 11.1 · G1–G4, T5, T6_

- [x] 11. 인계 문서 갱신 (묶음 A)
  - 선행: 10
  - [x] 11.1 `backend/README.md` 4단계 반영
    - §1 현황표, 실행 방법(단위·로컬·AWS), §5 로컬 결과(건수·날짜·기준 커밋, BE-Q15 주의), §3 판정 실행표(T1 확장, T2 역할별 표, T17, 4단계 이후 PR마다 `test_concurrency.py` 재실행 규칙), §6 IAM 표(`InboxFunction`, `MeFunction`의 Query), §7 미결 질문(BE-Q1, BE-Q30 해소, BE-Q42–BE-Q48), S2에 넘길 경로 목록. `GET /record`는 BE-Q46 승인 대기로 적는다.
    - _Requirements: 11.2, 11.5, 11.6 · docs/07 §7.2·§7.8, S2_

  - [x] 11.2 `docs/08-open-questions.md` 갱신
    - §8.1에 BE-Q42–BE-Q48을 requirements·design의 내용과 임시 결정 그대로 추가한다. BE-Q30 앞부분 해소, 뒷부분은 BE-Q17로 넘긴다. §8.3 결정 시점 표에 4단계 행을 더한다.
    - _Requirements: 11.7_

  - [x] 11.3 BE-Q46 리뷰 요청과 프론트 담당 전달 항목 (`backend/README.md` §8)
    - 리뷰 필요 항목: docs/03 §3.4 `GET /record`에 503 `TRY_AGAIN` 명시(BE-Q46), 스로틀링·섞인 사유를 503으로 볼지, 거부 시 대안 A. 프론트 담당 전달 항목(design "프론트엔드 연동 주의사항 (S2)" 요약), InboxItem `claimerNickname` null 가능(BE-Q45).
    - _Requirements: 11.6 · BE-Q45, BE-Q46, S2_

- [x] 12. 묶음 A 커밋
  - 선행: 11
  - 변경을 의미 단위로 커밋한다(push 안 함). `git status`로 프론트 트리와 무관한 파일만 들어갔는지 확인한다.

### 묶음 B: 방문 기록 조회 `GET /claims/{claimId}/record` (BE-Q46, A 커밋 뒤 별도 커밋)

- [ ] 13. 스냅샷 읽기 헬퍼 (`common/ddb.py`)
  - 선행: 12
  - [ ] 13.1 `transact_get_with_retry` 추가
    - 시그니처: `transact_get_with_retry(keys, *, client=None, sleep=time.sleep, rand=random.random) -> list[dict | None]`. `transact_get_items(TransactItems=[{"Get": {"TableName", "Key"}} ...])`를 부르고, `Responses[i]`에 `Item`이 없으면 `None`.
    - 재시도: 실패 사유(`_cancellation_codes`에서 `"None"` 제외)가 `TransactionConflict`뿐이고 1개 이상일 때만. 최초 호출 1회 + 재시도 최대 `len(BACKOFF_SECONDS)` = 3회(호출 최대 4회). i번째 대기는 `cap = BACKOFF_SECONDS[i]`에 대해 `cap/2 + rand()*cap/2`(equal jitter, 재시도 3회 누적 175–350ms, **임시 기본값**). 4회 모두 충돌이면 `ApiError(TRY_AGAIN)` 503.
    - `TransactionConflict`에 다른 사유가 섞인 취소, 다른 사유만 있는 취소(사유 없음·전부 `"None"` 포함), `TransactionCanceledException` 외 예외는 재시도·대기 없이 원래 예외를 올린다(`api_handler`가 500, BE-Q23). `ConditionFailed`로 바꾸지 않는다. GetItem 폴백 없음.
    - 로그: 재시도·소진·비충돌 취소 때 사유 코드 목록만 한 줄(`transact_get_conflict attempt=n`, `transact_get_try_again`, `transact_get_canceled reasons=...`). 키·`claimId`·사용자 ID·본문 없음.
    - _Requirements: 2.4, 2.6, 2.8, 10.4, 10.8 · BE-REC-10, BE-NFR-03, BE-Q23, BE-Q46_

  - [ ] 13.2 `transact_get_with_retry` 단위 테스트 (`tests/unit/test_ddb.py`)
    - Stubber로 주입한다. `sleep=sleeps.append`라 실제 대기가 없다.
    - 재시도 횟수: 첫 시도 성공(항목·`None` 순서, 대기 0), 충돌 2회 뒤 성공(호출 3·대기 2), 충돌 4회 → 503(호출 4·대기 3).
    - 대기 범위: `rand=1.0` → `[0.05, 0.1, 0.2]`(합 0.35), `rand=0.0` → `[0.025, 0.05, 0.1]`(합 0.175).
    - 실패 사유별: `TransactionConflict`+`"None"`은 재시도. `TransactionConflict`+`ThrottlingError`, `TransactionConflict`+`ValidationError`는 재시도 없이 원래 `ClientError`(호출 1). 충돌 뒤 섞인 사유는 호출 2·대기 1 뒤 원래 예외. 비충돌 사유 6종·사유 없음·전부 `"None"`은 원래 `ClientError`·호출 1·대기 0·`ConditionFailed` 아님. 비트랜잭션 예외 4종 재시도 없음.
    - 로그(`caplog`): 사유 코드만 있고 키·`claimId`·사용자 ID 없음. 3단계 `transact_with_retry` 테스트 그대로 통과.
    - _Requirements: 2.4, 2.6, 10.4, 10.8, 11.1 · BE-REC-10, BE-Q23, BE-Q46_

  - [ ] 13.3 Write property test for 스냅샷 읽기 재시도 (`tests/unit/test_ddb.py`)
    - **Property 24: 스냅샷 읽기는 TransactionConflict만 유한하게 재시도하고, 대기는 상한 안에 있다**
    - 생성기: 시도별 결과 열(성공 / 임의 사유 코드 목록의 `TransactionCanceledException` / 다른 `ClientError` 코드), `rand` 값 열 ∈ [0, 1). 가짜 클라이언트를 `client=`로 넘기고 `get_item`이 불리면 실패하게 둔다.
    - 확인: 호출 수 ≤ 4, 재시도는 실패 사유가 `TransactionConflict`뿐인 시도 뒤에만, 재시도 수 = 대기 수, 각 대기 ∈ [cap/2, cap], 재시도 3회면 합 ∈ [0.175, 0.35], 4회 모두 충돌이면 503, 그 밖에는 원래 예외 즉시, `get_item` 0회.
    - **Validates: Requirements 2.4, 2.6, 2.8**

- [ ] 14. 방문 기록 조회
  - 선행: 13.1
  - [ ] 14.1 `responses.py`에 `serialize_record_view` 추가
    - `claimStatus`는 Claim에서만, `record`·`delivered`·`photoStatus`는 Record에서만(Record 없으면 `null`·`false`·`"NONE"`). 기존 `serialize_record`를 재사용한다.
    - _Requirements: 2.1, 2.2, 2.7_

  - [ ] 14.2 `claim_service.get_record` 구현
    - `_lookup`(없으면 404, 실행자 아니면 403) 뒤 `transact_get_with_retry([_claim_key, _record_key])`. Claim이 `None`이면 404. 쓰기 없음. 403은 TransactGetItems 전에 낸다(BE-Q1). 기존 함수는 바꾸지 않는다.
    - _Requirements: 2.1, 2.3–2.6, 2.8 · BE-REC-05, G5, BE-Q1, BE-Q46_

  - [ ] 14.3 핸들러·경로·템플릿 이벤트
    - `handlers/claims.py`에 `_get_record`(첫 줄 `get_user`), `ROUTES`에 `GET /claims/{claimId}/record`. `handlers/routes.py`에 같은 경로, `template.yaml` `ClaimsFunction`에 이벤트 `GetRecord`(정책 불변, 주석 "TransactGetItems는 GetItem 권한으로 실행된다").
    - `test_handlers.py` 경로 집합, `test_adapter.py`의 `GET`/`PUT /claims/x/record` 구분 사례, `test_template.py`(기존 `ClaimsFunction` 권한 단언이 그대로 통과).
    - _Requirements: 2.1, 2.2, 9.1, 9.3, 9.6_

  - [ ] 14.4 기록 조회 단위 테스트 (`tests/unit/test_claim_service_moto.py`, `tests/unit/test_handlers_claims.py`)
    - moto 테이블 + `transact_get_items` monkeypatch 충돌 주입. 성공 형태와 키 순서, Record 없음, `ABANDONED`(`DISCARDED`)·`EXPIRED`·`COMPLETED`(`delivered: true`) 200, Claim 없음 404, Lookup 없음 404(트랜잭션 호출 없음), 제3자·계획자 403(본문 에러 형식만, 트랜잭션 호출 없음), 충돌 2회 후 200, 충돌 4회 → 503 `TRY_AGAIN`(호출 4, Claim·Record GetItem 0), 비충돌·섞인 사유 → 500(503 아님, 응답에 사유 없음), 조회 전후 테이블 불변, `token_use != "id"` → 401.
    - _Requirements: 2.1–2.8, 9.6, 10.4, 11.1 · BE-REC-05, BE-Q1, BE-Q23, BE-Q46, T2_

  - [ ] 14.5 Write property test for 기록 조회 일치 (`tests/unit/test_claim_properties.py`)
    - **Property 16: 기록 조회는 저장 항목과 일치하고 아무것도 바꾸지 않는다**
    - **Validates: Requirements 1.1, 2.1, 2.2, 2.3, 2.6, 2.8**

  - [ ] 14.6 Write property test for 기록 조회 권한 (`tests/unit/test_claim_properties.py`)
    - **Property 17: 기록 조회는 실행자에게만 내용을 준다**
    - **Validates: Requirements 2.5**

- [ ] 15. Checkpoint - 묶음 B 단위 테스트와 SAM
  - `pytest tests/unit` 실패 0건, `cfn-lint`, `sam validate --lint`, `sam build` 통과.
  - _Requirements: 9.8, 10.4, 11.1_

- [ ] 16. 로컬 통합 테스트 (묶음 B)
  - 선행: 15
  - [ ] 16.1 `tests/local/test_local_inbox.py`에 `GET /record` 확인 추가
    - 글 저장 뒤 `GET /record`(ACTIVE, record 있음), 완료 뒤 `GET /record`(COMPLETED, `delivered: true`), 계획자의 `GET /record` 403, 기록 없는 Claim의 `record: null`. Floci에서 TransactGetItems가 처음 도는 테스트다.
    - _Requirements: 11.2 · BE-Q15_
  - [ ] 16.2 Local_Env에서 `pytest -m local tests/local` 재실행, 전부 통과 확인과 결과 기록.
    - _Requirements: 11.2_

- [ ] 17. AWS 스택 대상 테스트 (묶음 B, 실행은 AWS 담당)
  - 선행: 16
  - [ ] 17.1 T1: `test_access_token_is_rejected`에 `GET /claims/{claimId}/record` 추가.
    - _Requirements: 11.8 · T1_
  - [ ] 17.2 T2: `GET /claims/{claimId}/record` 행(A 403, C 200, B 403, 없는 ID 404, 403 뒤 불변).
    - _Requirements: 2.5, 11.3 · T2, BE-Q1_
  - [ ] 17.3 `tests/integration/test_concurrency.py`에 `test_get_record_snapshot_during_writes`
    - design "AWS 통합 테스트: `GET /record` 스냅샷 읽기" 2·3번. 합격 기준은 응답 정합성(`GET /record`는 200 또는 `TRY_AGAIN` 503, 200마다 `COMPLETED ⇔ delivered ⇔ deliveredAt`, 쓰기 응답은 계약 코드, 끝난 뒤 InboxItem 1건·전달·Plan `COMPLETED`). 충돌·503 발생은 조건이 아니며 수만 기록한다. `ClaimsFunction` 설정과 소요 시간 최대값을 기록한다(권한 없으면 오류 코드만 기록).
    - _Requirements: 2.6, 10.5, 11.3 · BE-Q46, BE-Q48, G2–G4_
  - [ ] 17.4 `pytest -m integration tests/integration --collect-only` 수집 확인.

- [ ] 18. Checkpoint - 묶음 B 회귀와 문서
  - `pytest tests/unit` 실패 0건, 로컬 결과 유지, 통합 테스트 수집, 3단계 트랜잭션 diff 없음. README의 `GET /record` 상태(구현됨, BE-Q46 승인 전 PR 제외), 판정 실행표(T1·T2 `GET /record`, 동시 조회 테스트), IAM 주석을 갱신한다.
  - _Requirements: 10.1, 10.4, 11.1, 11.6_

- [ ] 19. 묶음 B 커밋과 최종 확인
  - 선행: 18
  - 묶음 A 커밋 뒤에 별도 커밋으로 남긴다(push 안 함). 프론트 트리(`/home/hwkim/knu-aws-2026`)와 docs/03에 변경이 없는지 확인한다. push·PR은 사용자 최종 검토 뒤에 한다.

### 승인 대기

- [ ] 20. API 계약 변경 (BE-Q46) **[승인 대기: 프론트엔드 담당 리뷰·승인 전에는 실행하지 않는다]**
  - 선행: 11.3, 19, 그리고 프론트엔드 담당의 BE-Q46 리뷰 결과
  - 순서는 docs/07 §7.2 계약 변경 절차를 따른다: ① docs/03 수정 PR → ② 프론트엔드 담당 승인 → ③ 백엔드 구현 PR(묶음 B).
  - [ ] 20.1 docs/03 §3.4 `GET /claims/{claimId}/record`에 503 `TRY_AGAIN` 추가 **[승인 대기]**
    - 승인되면 §3.4 `GET /record` 절에 "Claim·Record를 한 시점으로 읽는 트랜잭션 조회가 충돌 재시도를 모두 소진하면 503 `TRY_AGAIN`"을 적는다. 리뷰에서 스로틀링·섞인 사유도 503으로 정하면 13.1·13.2·13.3과 design 표를 함께 고친다.
    - _Requirements: 2.4, 10.1 · BE-Q46_
  - [ ] 20.2 requirements.md 갱신 **[승인 대기: 20.1 또는 20.3 결정 뒤]**
    - 남은 차이 1건(design "requirements와의 차이 정리" 2번)만 반영한다: Requirement 2에 503 `TRY_AGAIN`·500 `INTERNAL_ERROR` 응답 추가(대안 A면 불필요). 나머지 3건(2.6 문구, 11.1 테스트 목록, 11.3 AWS 테스트)은 2026-11-25 구현 전에 반영했다.
    - _Requirements: 2.6 · BE-Q46_
  - [ ] 20.3 대안 A로 교체 **[조건부: 프론트엔드 담당이 계약 변경을 거부한 경우에만]**
    - `get_record`를 ConsistentRead GetItem 2회(Claim → Record)로 바꾸고 `transact_get_with_retry`를 쓰지 않는다. 14.4의 충돌·소진 사례와 14.5의 `COMPLETED ⇔ delivered`, 17.3의 스냅샷 단언을 빼고 README·docs/08 BE-Q46을 고친다.
    - _Requirements: 2.6 · BE-Q46_
  - [ ] 20.4 묶음 B PR 반영 **[승인 대기, 사용자 확인 필요]**
    - PR 본문에 BE-Q 번호, T1·T2·T17 미판정, `GET /record` 동시 조회 테스트, S2 전달 항목을 적는다.
    - _Requirements: 11.6 · docs/07 §7.2, S2_

## Notes

- 속성과 작업: P22 → 1.4, P18 → 2.7, P19 → 2.8, P20 → 2.9, P21 → 2.10, P23 → 2.11, P24 → 13.3, P16 → 14.5, P17 → 14.6. 모두 필수다. 3단계 Property 12–15(G1–G4)는 Checkpoint에서 회귀로만 확인한다.
- 새 테스트 파일 이름: `test_inbox_service.py`, `test_handlers_inbox.py`, `test_inbox_properties.py`, `test_local_inbox.py`, `test_inbox.py`. `GET /record` 동시 조회는 기존 `test_concurrency.py`에 둔다.
- T1·T2·T17과 `GET /record` 동시 조회의 판정은 Dev_Stack에서만 한다. 로컬(Floci)·moto 결과는 판정 근거가 아니다(BE-Q15).
- 작업 20은 프론트엔드 담당 승인 전에는 시작하지 않는다. 20.1과 20.3은 리뷰 결과에 따라 둘 중 하나만 한다.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["2.5", "2.6", "2.7", "2.8", "2.9", "2.10", "2.11"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.2"] },
    { "id": 6, "tasks": ["4"] },
    { "id": 7, "tasks": ["5.1"] },
    { "id": 8, "tasks": ["5.2", "5.3"] },
    { "id": 9, "tasks": ["6"] },
    { "id": 10, "tasks": ["7.1"] },
    { "id": 11, "tasks": ["8"] },
    { "id": 12, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 13, "tasks": ["9.4"] },
    { "id": 14, "tasks": ["10"] },
    { "id": 15, "tasks": ["11.1", "11.2"] },
    { "id": 16, "tasks": ["11.3"] },
    { "id": 17, "tasks": ["12"] },
    { "id": 18, "tasks": ["13.1"] },
    { "id": 19, "tasks": ["13.2", "13.3", "14.1", "14.2"] },
    { "id": 20, "tasks": ["14.3"] },
    { "id": 21, "tasks": ["14.4", "14.5", "14.6"] },
    { "id": 22, "tasks": ["15"] },
    { "id": 23, "tasks": ["16.1"] },
    { "id": 24, "tasks": ["16.2"] },
    { "id": 25, "tasks": ["17.1", "17.2", "17.3"] },
    { "id": 26, "tasks": ["17.4"] },
    { "id": 27, "tasks": ["18"] },
    { "id": 28, "tasks": ["19"] },
    { "id": 29, "tasks": ["20.1", "20.3"] },
    { "id": 30, "tasks": ["20.2"] },
    { "id": 31, "tasks": ["20.4"] }
  ]
}
```
