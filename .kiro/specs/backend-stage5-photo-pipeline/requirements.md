# Requirements Document

## Introduction

백엔드 5단계(사진 파이프라인)의 요구사항이다. 기준은 `docs/07-development-plan.md` §7.3 5단계, `docs/03-api-contract.md` §3.4·§3.5·§3.6, `docs/02-architecture.md` §2.4·§2.5·§2.6·§2.7·§2.8·§2.9·§2.10, `docs/06-requirements.md`의 BE-REC-02·03·04, BE-PHOTO-01–09, BE-INBOX-02, BE-OBS-01·02, BE-INFRA-06·08, BE-NFR-02·03·05·07, 검증 시나리오 T8·T9·T10·T11·T15다. 이 단계가 끝나면 프론트 연동 지점 S3(실제 업로드·폴링·실패·교체 확인)의 백엔드 쪽 준비가 끝난다. 단, S3의 폴링은 4단계 묶음 B(`GET /claims/{claimId}/record`)에 의존한다(아래 "4단계 묶음 B 의존").

- 1–4단계(`backend-stage1-2-foundation`, `backend-stage3-claim`, `backend-stage4-record-inbox`의 묶음 A)의 공통 모듈·서비스·템플릿을 그대로 쓴다. 불필요한 리팩터링은 하지 않는다.
- 3단계에서 이미 구현한 것: 완료 트랜잭션 `claim_service.complete_claim(claim_id, mode, key, processed_key)`의 `WITH_PHOTO` 분기(Record 조건 `photoKey = :key AND photoStatus = :prev(PROCESSING) AND attribute_not_exists(deliveredAt)`, `photoStatus = READY`·`processedKey` 설정, InboxItem `hasPhoto = true`), `TEXT_ONLY` 완료 때 진행 중인 사진을 `DISCARDED`로 바꾸는 규칙, 포기 때 Record `photoStatus = DISCARDED`. 이번 단계는 이 함수의 조건식·갱신식·실패 분기를 바꾸지 않고 호출만 한다.
- 이번 단계에서 새로 만드는 것: 사진 버킷과 정책, `PhotoQueue`·`PhotoDLQ`·큐 정책·버킷 알림, `PUT /claims/{claimId}/record`의 `photo` 처리(BE-Q34 해제)와 presigned PUT, `POST /claims/{claimId}/record/photo`, `PhotoProcessorFunction`(`src/workers/photo_processor.py`)과 Pillow 레이어(`layers/pillow/`), `GET /inbox/{itemId}`의 `photoUrl`(15분 presigned GET)·`photoCaption`(BE-Q42 해제), EMF 지표 `PhotoProcessingMs`·`PhotoFailed`, DLQ 알람, IAM 최소 권한, 로컬 환경의 S3·SQS·폴러, 단위·로컬·AWS 대상 테스트(T8–T11, T15).
- 범위 밖: `GET /claims/{claimId}/record`(4단계 묶음 B, BE-Q46), AI(6단계), CloudFront·웹 버킷·대시보드·`seed.py`(7단계), 계획 대표 사진(P1), 다중 사진. SDK 타임아웃·재시도 정책(BE-Q48)은 별도 공통 개선 과제로 두고 이번 단계에서 정하지 않는다.
- AWS 배포·리소스 생성은 하지 않는다. `sam validate --lint`와 `sam build`(Pillow 레이어는 `--use-container`)까지 하고, T8–T11·T15는 테스트 코드만 작성한다. 실행·판정은 AWS 담당이 한다(docs/07 §7.8, BE-Q15).
- API 계약(docs/03)과 DynamoDB 키 설계(docs/02 §2.6)는 바꾸지 않는다. 계약에 없는 결정은 임시 기본안으로 적고 BE-Q 번호를 붙였다(마지막 "미결 사항"). 기존 질문은 docs/08 번호를 그대로 쓰고, 새 질문은 BE-Q49부터다. BE-Q45·BE-Q46·BE-Q48은 미결 상태 그대로 둔다.
- **기준 브랜치**: `feat/be-5-photo-pipeline`, `feat/be-4-inbox`(PR #1 head `dc3af68`)에서 갈라졌다. 기존 브랜치(`feat/be-4-inbox`, `feat/be-4-record-inbox`, PR #1–#6의 head)는 바꾸지 않는다. 선행 PR(#2–#6, #1)이 병합되기 전이므로 5단계 PR의 base는 `feat/be-4-inbox`로 두고, 선행 PR이 병합되면 base를 옮긴다(Requirement 15.6).
- **시작 조건**: docs/07 §7.2는 3단계 G1–G4 통과 뒤 다음 단계로 넘어가게 하고, 이후 단계 PR마다 `test_concurrency.py`를 다시 돌리게 한다. 3단계 AWS 판정은 2026-11-25 통과했다. 4단계 AWS 판정(T1 확장·T2·T17)은 아직 실행 전이다. 5단계 구현은 시작할 수 있지만, 5단계 AWS 판정은 4단계 판정과 함께 또는 그 뒤에 한다(Requirement 15.5).

### 4단계 묶음 B 의존

`GET /claims/{claimId}/record`는 4단계 묶음 B(`feat/be-4-record-inbox`의 `f3626c0`)에만 있고, docs/03 §3.4에 503 `TRY_AGAIN`을 적는 계약 변경(BE-Q46)이 프론트엔드 담당 승인 전이다. 5단계는 이 경로 없이 구현·검증할 수 있게 나눈다.

| 구분 | 내용 | 묶음 B 필요 |
|---|---|---|
| 독립 | 버킷·큐·DLQ·알림, presigned PUT 발급, 사진 교체, 사진 처리 Lambda, 완료 연동, 수신함 상세의 `photoUrl`·`photoCaption`, IAM, 지표·알람, 단위 테스트, 로컬·AWS 테스트의 상태 확인(DynamoDB `ConsistentRead` 직접 조회, BE-Q38) | 아니오 |
| 의존 | 프론트 S3 연동의 폴링(화면 5-1·5-2·5-4가 `GET /record`의 `photoStatus`·`delivered`·`claimStatus`로 분기, docs/05 §5.2.5), API로 사진 상태를 확인하는 로컬·AWS 테스트 사례 | 예 |
| 의존 시 처리 | 의존 사례는 묶음 B가 브랜치에 있을 때만 도는 별도 테스트로 둔다(Requirement 14.4). 묶음 B가 대안 A(GetItem 2회, BE-Q46)로 바뀌면 사진 폴링에서 한 응답 안의 `photoStatus`·`delivered`·`claimStatus`가 서로 다른 시점일 수 있다는 4단계 design.md의 표 7행 위험이 그대로 남는다 | — |

## Glossary

- **Backend**: `backend/` 아래의 Python 3.12 Lambda 코드와 SAM 템플릿 전체.
- **Claim_Service**: `src/domain/claim_service.py`. 이어받기·포기·기록·완료 로직. 이번 단계에서 기록 저장의 사진 분기와 사진 교체를 더한다.
- **Photo_Processor**: `src/workers/photo_processor.py`의 SQS 핸들러. 배포 단위는 `PhotoProcessorFunction`.
- **Claims_Function**: `/claims/*` 경로를 처리하는 Lambda(`handlers.claims.handler`).
- **Inbox_Function**: `/inbox*` 경로를 처리하는 Lambda(`handlers.inbox.handler`).
- **Photo_Bucket**: 사진 버킷. 이름 `${AWS::StackName}-photos-${AWS::AccountId}`(BE-PHOTO-09).
- **Original_Key**: `photos/original/{claimId}/{uuid}.{ext}`. 실행자가 presigned PUT으로 올리는 원본의 키. `ext`는 `jpg`(image/jpeg) 또는 `png`(image/png).
- **Processed_Key**: `photos/processed/{claimId}/{attemptUuid}.jpg`. 처리본의 키. `attemptUuid`는 처리 시도(Lambda 실행 1회)마다 새로 만든다. 같은 원본이라도 시도가 다르면 키가 다르다(BE-Q57).
- **Delivered_Processed_Key**: 전달된 Record의 `processedKey`. 수신함 사진이 가리키는 처리본이며 어떤 처리 시도도 이 객체를 지우거나 덮어쓰지 않는다.
- **Definitive_Outcome / Uncertain_Outcome**: 완료 호출 뒤 이 처리본의 전달 여부를 `ConsistentRead`로 확정한 결과(전달됨 또는 확실히 전달 안 됨)와, 호출 또는 확인 읽기가 오류·타임아웃으로 끝나 확정하지 못한 결과.
- **Photo_Queue / Photo_DLQ**: SQS `PhotoQueue`와 그 DLQ `PhotoDLQ`.
- **Record**: `PLAN#{planId}` / `RECORD#{claimId}`. 사진 관련 속성 `photoStatus`, `photoKey`(현재 유효한 원본 키), `processedKey`, `photoError`, `deliveredAt`.
- **Photo_Status**: `NONE` / `UPLOAD_PENDING` / `PROCESSING` / `READY` / `FAILED` / `DISCARDED`(docs/02 §2.5).
- **Current_Photo**: Record의 `photoKey`와 같은 Original_Key. 그 외의 원본은 지난 사진이다.
- **Claimer**: ClaimLookup의 `claimerId`가 요청자 JWT `sub`와 같은 사용자.
- **Owner**: InboxItem의 `ownerId`가 요청자 JWT `sub`와 같은 사용자(계획자).
- **Upload_Descriptor**: 응답의 `upload` 객체 `{ url, method: "PUT", headers: { "Content-Type" }, expiresAt }`(docs/03 §3.4).
- **Complete_Claim**: 3단계 `claim_service.complete_claim`. 이번 단계에서 바꾸지 않는다.
- **Dev_Stack**: 실제 AWS에 SAM으로 배포한 `dev` 스택. T 시나리오의 합격 판정은 여기서만 한다.
- **Local_Env**: docker compose 로컬 환경(Floci 2.5.0-compat, HTTP 어댑터, SQS 폴러). T 판정에는 쓰지 않는다.

## Requirements

### Requirement 1: 사진 버킷과 접근 정책 [BE-PHOTO-08, BE-PHOTO-09, BE-NFR-03]

**User Story:** As a 실행자, I want 내가 올린 사진이 공개되지 않고 필요한 사람만 볼 수 있길 원한다, so that 위치 정보나 사진이 의도치 않게 노출되지 않는다.

#### Acceptance Criteria

1. THE Backend SHALL 템플릿에 Photo_Bucket을 두고 이름을 `!Sub '${AWS::StackName}-photos-${AWS::AccountId}'`로 고정한다. [BE-PHOTO-09]
2. THE Photo_Bucket SHALL 퍼블릭 액세스 차단 네 항목(`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`)을 모두 켠다. 객체 접근은 presigned URL로만 한다. [BE-PHOTO-08, §2.7 6]
3. THE Photo_Bucket SHALL CORS 규칙 하나를 둔다: 허용 Origin은 API CORS와 같은 `AllowedOrigins` 파라미터, 허용 메서드 `PUT`·`GET`, 허용 헤더 `Content-Type`. [BE-PHOTO-08, §2.7 7]
   - BE-Q65에서 조건부 업로드(`If-None-Match: *`)를 채택하면 허용 헤더에 `If-None-Match`를 더한다. 채택 전에는 더하지 않는다.
4. THE Photo_Bucket SHALL 수명 주기 규칙으로 prefix `photos/original/`의 객체를 생성 7일 뒤 만료시킨다. `photos/processed/`에는 만료 규칙을 두지 않는다(수신함에서 계속 보여야 한다). [BE-PHOTO-08, §2.7 6]
5. THE Photo_Bucket SHALL 기본 서버 측 암호화(SSE-S3)를 쓰고, 버킷 정책으로 TLS가 아닌 요청(`aws:SecureTransport = false`)을 거부한다. [BE-Q49]
6. THE Photo_Bucket SHALL 객체 소유권을 `BucketOwnerEnforced`(ACL 비활성)로 둔다. [BE-Q49]
7. THE Backend SHALL 로그·EMF 지표·에러 응답에 presigned URL, 서명 쿼리 문자열, 사용자 ID를 남기지 않는다. [BE-NFR-03]

### Requirement 2: 사진 업로드 URL 발급 (`PUT /claims/{claimId}/record`의 `photo`) [BE-REC-02, BE-REC-03, G3]

**User Story:** As a 실행자, I want 글을 저장하면서 사진 한 장을 올릴 주소를 받고 싶다, so that 브라우저에서 사진을 바로 올릴 수 있다.

#### Acceptance Criteria

1. WHEN Claimer가 `PUT /claims/{claimId}/record { letter, photo: { contentType, size } }`를 호출하고 Plan의 `currentClaimId = claimId`, Plan `status = CLAIMED`, Claim `status = ACTIVE`, Record에 `deliveredAt`이 없으면, THE Claim_Service SHALL 3단계 기록 저장 Transaction(Plan·Claim ConditionCheck + Record Update) 하나로 `letter`, `updatedAt`, 새 Original_Key를 `photoKey`에, `photoStatus = UPLOAD_PENDING`을 쓰고 `processedKey`·`photoError`를 `REMOVE`한다. 사진 교체(Requirement 3)와 같은 초기화 규칙이다. [BE-REC-02, §3.4]
2. THE 응답 SHALL 200 `{ record, upload }`이고 `upload`는 Upload_Descriptor다. `url`은 Original_Key에 대한 presigned PUT URL(유효 10분), `headers`는 `{ "Content-Type": contentType }`, `expiresAt`은 발급 시각 + 10분(`iso_utc`)이다. [BE-REC-02, §3.4]
3. THE presigned PUT URL SHALL `ContentType`과 정확한 `ContentLength`(= 요청의 `size`)를 서명에 포함한다. [§3.4 "presigned PUT은 크기 범위를 강제할 수 없으므로"]
   - 유효 시간(10분) 안에는 같은 URL로 같은 Original_Key에 다시 PUT할 수 있다(원본 덮어쓰기). 덮어쓰기를 막는 조건부 쓰기(`If-None-Match: *`를 서명 헤더에 넣고 `upload.headers`로 넘기는 방식)는 서명 헤더 구성, 버킷 CORS 허용 헤더, `upload.headers`에 헤더가 늘어나는 것에 대한 프론트 처리, Floci 지원을 확인해야 하므로 이번 요구사항에서 정하지 않는다(BE-Q65). 정하기 전까지는 Requirement 5.9의 ETag 확인으로 "이벤트가 가리킨 바로 그 객체만 처리"를 보장한다.
4. THE presigned URL 발급 SHALL Transaction이 성공한 뒤에 한다. Transaction이 실패하면(409 `CLAIM_NOT_ACTIVE`, 404, 403, 503 `TRY_AGAIN`) URL을 만들지 않는다.
5. THE Original_Key의 `uuid` SHALL 요청마다 새로 만든다. 같은 Claim에 다시 사진을 보내면 새 키가 `photoKey`가 되고 이전 키는 Current_Photo가 아니다. [BE-REC-04, T15]
6. IF `photo.contentType`이 `image/jpeg`·`image/png`가 아니거나, `photo.size`가 정수가 아니거나 1 미만 또는 10,485,760(10MB) 초과이거나, `photo`가 객체가 아니면, THEN THE Claims_Function SHALL DB에 쓰지 않고 400 `VALIDATION_ERROR`(`details` 키 `photo.contentType`·`photo.size` 또는 `photo`)로 응답한다. [§3.4, BE-Q50]
7. WHEN 요청에 `photo`가 없거나 `null`이면, THE Claim_Service SHALL 3단계와 같이 글만 갱신하고 `photoStatus`·`photoKey`·`processedKey`·`photoError`를 바꾸지 않으며 `upload: null`을 반환한다. [BE-REC-03, §3.4 "사진 없이 요청하면"]
8. THE Backend SHALL 3단계의 BE-Q34 동작(`photo`가 오면 400)을 이번 단계에서 없앤다. [BE-Q34]
9. 3단계의 실패 분기(Lookup 없음 404, 실행자 아님 403, 끝난 이어받기·전달된 Record 409 `CLAIM_NOT_ACTIVE`와 `StaleRequestRejected` 지표)는 사진이 있을 때도 같다. [BE-REC-01, T6]
10. THE 응답의 `record` SHALL Transaction 뒤 Record를 `ConsistentRead`로 다시 읽어 3단계 `serialize_record` 허용 목록으로 만든다. `photoKey`·`processedKey`·`photoError`는 나가지 않는다. [§2.5, BE-PLAN-08]

### Requirement 3: 사진 교체 (`POST /claims/{claimId}/record/photo`) [BE-REC-04, T15]

**User Story:** As a 실행자, I want 처리에 실패했거나 마음에 들지 않는 사진을 다른 사진으로 바꾸고 싶다, so that 글을 다시 쓰지 않고 사진만 새로 보낼 수 있다.

#### Acceptance Criteria

1. WHEN Claimer가 `POST /claims/{claimId}/record/photo { contentType, size }`를 호출하고 Requirement 2.1의 조건(Plan·Claim 상태, Record에 `deliveredAt` 없음)을 만족하면, THE Claim_Service SHALL Transaction 하나로 Record의 `photoKey`를 새 Original_Key로, `photoStatus`를 `UPLOAD_PENDING`으로 바꾸고 `processedKey`·`photoError`를 `REMOVE`한 뒤 Requirement 2.2와 같은 Upload_Descriptor를 반환한다. [BE-REC-04, §3.4]
   - 교체는 `letter`·`updatedAt`·`authorId`·`claimId`·`planId`를 바꾸지 않는다(작성한 글은 그대로 남는다). 이전 실패 사유(`photoError`)와 이전 처리본 참조(`processedKey`)는 남기지 않는다. 화면 5-2·5-3이 "작성한 글은 저장되어 있어요"를 보여 줄 수 있게 하려는 것이다(docs/05 §5.2.5).
   - 교체 전 `processedKey`가 가리키던 객체는 아직 전달되지 않은 처리본이므로(전달된 Record는 교체 조건에서 거부된다) 고아 객체 정리(Requirement 8.6) 대상이 된다. 교체 API는 S3 객체를 지우지 않는다.
2. THE 응답 본문 SHALL `{ "upload": Upload_Descriptor }`이다. docs/03 §3.4는 "응답은 위와 같은 `upload`"라고만 적었다. `{ upload }`만 담는 것이 권장안이고 프론트엔드 리뷰 대상이다(BE-Q51).
3. THE 교체 SHALL 지금 `photoStatus`가 `NONE`·`UPLOAD_PENDING`·`PROCESSING`·`FAILED` 중 무엇이든 허용한다. `READY`는 전달된 뒤에만 생기므로(BE-Q2) 전달 조건(`attribute_not_exists(deliveredAt)`)에서 거부된다. `DISCARDED`는 포기한 Claim이라 Claim 조건에서 거부된다. [§2.7 5]
4. IF Record가 없으면(글을 저장하기 전), THEN THE Claim_Service SHALL 400 `RECORD_REQUIRED`로 응답하고 아무것도 쓰지 않는다. 권장안이고 프론트엔드 리뷰 대상이다(BE-Q52).
5. Requirement 2.6(본문 검증)과 2.9(실패 분기)를 그대로 따른다. 본문 검증의 `details` 키는 `contentType`·`size` 또는 `body`다.
6. WHEN 교체가 성공하면, THE 이전 Original_Key에서 오는 처리 결과 SHALL 전달되지 않는다(Requirement 6.2·6.6). 이전 원본 객체는 수명 주기로 지워지며 이 API에서 지우지 않는다.

### Requirement 4: S3 이벤트 알림, SQS, DLQ [BE-PHOTO-01, BE-PHOTO-09]

**User Story:** As a AWS 담당, I want 업로드된 원본이 빠짐없이 처리 대기열에 들어가고 반복 실패가 따로 모이길 원한다, so that 처리 실패를 놓치지 않고 원인을 확인할 수 있다.

#### Acceptance Criteria

1. THE Backend SHALL Photo_Bucket의 `s3:ObjectCreated:*` 이벤트 중 prefix `photos/original/`인 것만 Photo_Queue로 보낸다(QueueConfiguration). `photos/processed/`는 알림 대상이 아니다(처리본이 다시 처리를 부르지 않게 한다). [BE-PHOTO-01]
2. THE Photo_Queue SHALL `VisibilityTimeout = 6 × PhotoProcessorFunction Timeout`(= 180초), `RedrivePolicy.maxReceiveCount = 3`, `deadLetterTargetArn = PhotoDLQ`를 갖는다. [BE-PHOTO-01]
3. THE Photo_DLQ SHALL 메시지 보존 기간을 최대(14일)로 둔다. [BE-Q53]
4. THE 큐 정책(`PhotoQueuePolicy`) SHALL `s3.amazonaws.com` 주체에 `sqs:SendMessage`만 허용하고, 조건 `aws:SourceArn = arn:${AWS::Partition}:s3:::${AWS::StackName}-photos-${AWS::AccountId}`(문자열로 씀)와 `aws:SourceAccount = ${AWS::AccountId}`를 둔다. Photo_Bucket은 `DependsOn: PhotoQueuePolicy`를 갖는다. [BE-PHOTO-09]
5. THE Photo_Queue와 Photo_DLQ SHALL SQS 관리형 서버 측 암호화(SSE-SQS)를 쓴다. [BE-Q49]
6. THE PhotoProcessorFunction SHALL Photo_Queue를 이벤트 소스로 `BatchSize: 1`로 받는다. [BE-PHOTO-01]

### Requirement 5: 사진 처리 Lambda의 입력 해석과 무시 조건 [BE-PHOTO-02, BE-PHOTO-03]

**User Story:** As a 개발 담당, I want 처리 Lambda가 처리하면 안 되는 메시지를 확실히 걸러내길 원한다, so that 지난 사진·포기한 이어받기·이미 전달된 기록에 사진이 붙지 않는다.

#### Acceptance Criteria

1. THE PhotoProcessorFunction SHALL `Handler: workers.photo_processor.handler`, `Timeout: 30`, `MemorySize: 1024`, Python 3.12, Pillow 레이어를 갖는다. [BE-PHOTO-01, §2.3]
2. WHEN SQS 메시지 본문이 JSON이 아니거나, `Records`가 없거나, `Event == "s3:TestEvent"`이면, THE Photo_Processor SHALL 아무것도 하지 않고 정상 종료한다(메시지 삭제). [BE-PHOTO-02]
3. THE Photo_Processor SHALL 메시지의 각 `Records[*]`를 차례로 처리하고, S3 키는 `urllib.parse.unquote_plus`로 디코딩한다. [BE-PHOTO-02]
4. IF 디코딩한 키가 Original_Key 형식(`photos/original/{claimId}/{uuid}.{jpg|png}`)이 아니면, THEN THE Photo_Processor SHALL 그 레코드를 무시한다. [BE-Q54]
5. THE Photo_Processor SHALL 키의 `claimId`로 ClaimLookup을, 그 `planId`로 Record를 `ConsistentRead`로 읽는다. ClaimLookup 또는 Record가 없으면 무시한다.
6. IF Record에 `deliveredAt`이 있거나, `photoStatus = DISCARDED`이거나, `photoKey`가 이 키와 다르면, THEN THE Photo_Processor SHALL 처리하지 않고 정상 종료한다. 이 시도는 처리본을 만들지 않았으므로 지울 것이 없다. 다른 시도가 남긴 처리본은 이 시도가 지우지 않는다(Requirement 8.6의 정리 대상). [BE-PHOTO-03, T10, T15]
7. IF Record의 `photoStatus = READY`이고 `deliveredAt`이 없으면, THEN THE Photo_Processor SHALL 처리하지 않고 정상 종료하며 사유 코드(`unexpected_ready`)만 로그에 남긴다. [BE-Q2, BE-Q66]
   - docs/02 §2.7 3-1·3-6은 이 상태에서 "처리를 건너뛰고 완료만 다시 호출"하라고 적었다. 그러나 3단계 Complete_Claim은 `WITH_PHOTO`일 때 트랜잭션 전에 `photoStatus = PROCESSING`이 아니면 409 `CLAIM_NOT_ACTIVE`로 거부하고, `READY`는 Complete_Claim이 `deliveredAt`과 같은 트랜잭션에서만 쓴다. 그래서 이 상태는 정상 경로에서 생기지 않고, 생기더라도 docs/02의 재시도 경로는 성공할 수 없다.
   - Complete_Claim은 바꾸지 않는다. 일시 오류 뒤의 재시도는 Record가 `PROCESSING`으로 남아 있으므로 처리를 처음부터 다시 한다(Requirement 9.7). docs/02 §2.7의 문구 정리는 BE-Q66으로 남긴다.
8. THE 무시 SHALL 모두 정상 종료다. 무시는 SQS 재시도를 부르지 않는다.
9. THE Photo_Processor SHALL 이벤트 레코드의 `s3.object.eTag`가 가리키는 객체만 처리한다: `HeadObject`·`GetObject`에 `IfMatch = eTag`를 지정하고, 일치하지 않으면(같은 키에 다시 업로드돼 객체가 바뀜) 그 레코드를 무시하고 정상 종료한다. 바뀐 객체에는 새 `ObjectCreated` 이벤트가 따로 온다. 객체가 없으면(수명 주기 만료 등) 무시한다. [BE-Q65]

### Requirement 6: 처리 상태 전이 [BE-PHOTO-04, G3]

**User Story:** As a 실행자, I want 사진 처리 상태가 정확히 보이길 원한다, so that 처리 중·실패·완료를 화면에서 구분하고 다음 행동을 고를 수 있다.

#### Acceptance Criteria

1. WHEN 무시 조건에 걸리지 않으면, THE Photo_Processor SHALL Record에 조건부 `UpdateItem`으로 `photoStatus = PROCESSING`을 쓴다. 조건은 `photoKey = :key AND photoStatus IN ('UPLOAD_PENDING', 'PROCESSING') AND attribute_not_exists(deliveredAt)`이다. [BE-PHOTO-04, §2.7 3-2]
2. IF 1의 조건이 실패하면, THEN THE Photo_Processor SHALL 처리하지 않고 정상 종료한다(그 사이 교체·글로 완료·포기가 먼저 커밋된 경우). [§2.7 3-2]
3. WHEN 검사(Requirement 7.1–7.3)에 실패하면, THE Photo_Processor SHALL 조건부 `UpdateItem`으로 `photoStatus = FAILED`, `photoError = <사유 코드>`를 쓰고 정상 종료한다(재시도하지 않는다). 조건은 `photoKey = :key AND photoStatus = 'PROCESSING' AND attribute_not_exists(deliveredAt)`이고, 조건이 실패하면 아무것도 쓰지 않는다. [BE-PHOTO-04, T8]
4. THE `photoError` SHALL 정해진 사유 코드 중 하나다: `UNSUPPORTED_FORMAT`, `TOO_LARGE`, `TOO_MANY_PIXELS`, `CORRUPT_IMAGE`, `RETRY_EXHAUSTED`. 예외 메시지·파일 내용은 쓰지 않는다. [BE-Q55]
5. THE Photo_Processor SHALL `READY`를 직접 쓰지 않는다. `READY`와 `processedKey`는 Complete_Claim의 Record Update만 쓴다. [BE-PHOTO-06, §2.7 3-5]
6. 사진 처리와 교체가 겹치면: 교체가 먼저 커밋되면 1의 조건(`photoKey = :key`)이 실패하고, 처리 뒤 커밋되면 Complete_Claim의 Record 조건(`photoKey = :key`)이 실패한다. 어느 쪽이든 이전 사진은 전달되지 않고 새 사진의 처리 결과만 전달될 수 있다. [T15]
7. 3의 `FAILED`는 실행자에게 사진 교체 또는 `TEXT_ONLY` 완료를 허용한다(Requirement 3.3, 3단계 완료 규칙). `TEXT_ONLY` 완료는 `FAILED`를 `DISCARDED`로 바꾼다. [§2.7 5, T8]

### Requirement 7: 이미지 검증, 축소, 메타데이터 제거 [BE-PHOTO-04, BE-PHOTO-05, G7, BE-NFR-03, T11]

**User Story:** As a 실행자, I want 내 사진에서 위치 정보가 지워진 처리본만 전달되길 원한다, so that 사진 한 장으로 내 위치가 드러나지 않는다.

#### Acceptance Criteria

1. THE Photo_Processor SHALL S3 객체를 읽기 전에 실제 크기(`HeadObject`의 `ContentLength`)를 확인하고, 10,485,760바이트를 넘으면 `TOO_LARGE`로 실패 처리한다(Requirement 6.3). 객체를 읽을 때도 10,485,760바이트를 넘게 읽지 않는다. [BE-PHOTO-04, §3.4 "사진 처리 Lambda가 실제 객체 크기를 다시 검사한다"]
2. THE Photo_Processor SHALL 확장자나 `Content-Type`이 아니라 매직 바이트로 형식을 판정한다: JPEG(`FF D8 FF`) 또는 PNG(`89 50 4E 47 0D 0A 1A 0A`). 그 밖이면 `UNSUPPORTED_FORMAT`. [BE-PHOTO-04]
3. THE Photo_Processor SHALL 디코딩 전에 이미지 헤더의 크기(가로 × 세로)를 읽어 최대 픽셀 수(40,000,000)를 넘으면 `TOO_MANY_PIXELS`로 실패 처리한다. 디코딩·검증이 실패하면(잘린 파일, 손상된 데이터) `CORRUPT_IMAGE`다. [BE-PHOTO-04, BE-Q56, T8]
   - Pillow의 압축 폭탄 방어를 함께 쓴다: `Image.MAX_IMAGE_PIXELS`를 40,000,000으로 두고, `DecompressionBombWarning`(한도 초과)은 경고로 넘기지 않고 오류로 바꿔 `TOO_MANY_PIXELS`로 처리하며, `DecompressionBombError`(한도의 2배 초과)도 `TOO_MANY_PIXELS`다. 전역 경고 필터를 바꾸지 않고 처리 함수 안에서만 경고를 오류로 다룬다.
   - 40,000,000픽셀 이하 이미지의 처리(디코딩·방향 보정·축소·재인코딩)가 PhotoProcessorFunction 메모리 1024MB 안에서 끝나야 한다. 최대 크기(40MP) 이미지의 최대 상주 메모리를 단위 테스트에서 측정해 결과를 README에 적고, 1024MB의 70%를 넘으면 메모리 설정 또는 한도를 다시 정한다(BE-Q56).
4. THE Photo_Processor SHALL EXIF 방향(Orientation)을 픽셀에 반영한 뒤(`ImageOps.exif_transpose`), 긴 변이 1600px를 넘으면 비율을 유지해 1600px로 줄인다. 1600px 이하이면 크기를 바꾸지 않는다. [BE-PHOTO-05]
5. THE Photo_Processor SHALL 결과를 RGB JPEG로 다시 인코딩해 Processed_Key `photos/processed/{claimId}/{attemptUuid}.jpg`에 쓴다. `attemptUuid`는 이 처리 시도에서 새로 만든다. 같은 원본을 여러 실행이 동시에 처리해도 서로의 처리본을 덮어쓰지 않고, 어떤 시도도 Delivered_Processed_Key에 쓰지 않는다. 처리본 업로드는 `IfNoneMatch='*'`(조건부 쓰기)로 하여 같은 키가 이미 있으면 쓰지 않는다. 투명도가 있는 PNG는 흰 배경에 합성한다. JPEG 품질은 85다. [BE-PHOTO-05, BE-Q57, BE-Q58]
6. THE 처리본 SHALL EXIF·GPS·XMP·IPTC·ICC 프로필·주석·썸네일을 포함한 모든 메타데이터를 담지 않는다. 픽셀 데이터만 새 이미지로 옮겨 저장하고 `exif`·`icc_profile` 등을 넘기지 않는다. [BE-PHOTO-05, G7, BE-NFR-03, T11]
7. THE 처리본 업로드 SHALL `ContentType: image/jpeg`이고 Photo_Bucket의 기본 암호화를 따른다.
8. THE 이미지 처리 함수 SHALL S3·DynamoDB를 모르는 순수 함수(`bytes → (jpeg bytes, 메타정보)` 또는 사유 코드 예외)로 분리해 단위 테스트할 수 있게 한다. [docs/07 §7.2 "5단계 사진 처리 로직은 단위 테스트까지 먼저"]

### Requirement 8: 완료 연동 (`complete_claim(WITH_PHOTO)`)과 처리본 정리 [BE-PHOTO-06, G2, G3, G4]

**User Story:** As a 계획자, I want 실행자가 사진과 함께 보낸 방문 기록이 정확히 한 번 수신함에 오길 원한다, so that 같은 편지가 두 번 오거나 지난 사진이 섞이거나 이미 보인 사진이 사라지지 않는다.

#### Acceptance Criteria

1. WHEN 처리본을 썼으면, THE Photo_Processor SHALL `claim_service.complete_claim(claimId, "WITH_PHOTO", key=Original_Key, processed_key=Processed_Key)`를 호출한다. Complete_Claim의 조건식·갱신식·실패 분기는 바꾸지 않는다. [BE-PHOTO-06, §2.6]
2. THE Photo_Processor SHALL Complete_Claim의 반환값만으로 전달 여부를 판단하지 않는다. Complete_Claim은 Claim이 이미 `COMPLETED`이면(예: `TEXT_ONLY` 완료나 다른 처리 시도가 먼저 커밋됨) 사진 키를 보지 않고 멱등 결과를 돌려준다(3단계 동작). 그래서 호출이 끝나면(성공이든 정해진 `ApiError`든) Record를 `ConsistentRead`로 다시 읽어 Definitive_Outcome을 정한다. [T10]
   - 전달됨: `deliveredAt`이 있고 `processedKey = 이 Processed_Key`.
   - 확실히 전달 안 됨: 다시 읽은 Record가 다음 중 하나다. `deliveredAt`이 있고 `processedKey`가 이 키가 아님(없음 포함), `photoKey`가 이 Original_Key가 아님, `photoStatus = DISCARDED`, 또는 Claim이 `ABANDONED`·`EXPIRED`. 이때 Record의 어떤 값도 이 Processed_Key를 가리키지 않는다.
   - 그 밖(Record가 아직 `PROCESSING`이고 미전달, 읽기 실패 등): Uncertain_Outcome.
3. WHEN Definitive_Outcome이 "확실히 전달 안 됨"이면, THE Photo_Processor SHALL 이 시도가 쓴 Processed_Key 객체만 지우고 정상 종료한다. 다른 시도의 처리본과 Delivered_Processed_Key는 지우지 않는다. [BE-PHOTO-06, §2.7 3-5, T10, T15]
4. WHEN Complete_Claim 호출 또는 확인 읽기가 503 `TRY_AGAIN`, DynamoDB·S3 일시 오류, 타임아웃으로 끝나 Uncertain_Outcome이면, THE Photo_Processor SHALL 처리본을 지우지 않고 예외를 올려 SQS 재시도에 맡긴다. 트랜잭션이 실제로는 커밋됐을 수 있기 때문이다(커밋됐다면 Record가 이 처리본을 가리킨다). 재시도는 Requirement 5의 무시 조건으로 다시 판정한다. [BE-PHOTO-07]
5. Complete_Claim이 409 `CLAIM_NOT_ACTIVE`(포기·만료·`currentClaimId` 불일치, 또는 `WITH_PHOTO`의 키·상태 불일치)나 400 `RECORD_REQUIRED`를 내도 2의 확인 읽기로 판단한다. 확인 결과가 "확실히 전달 안 됨"일 때만 3처럼 지운다. [§2.7 3-6, G3]
6. THE Backend SHALL 지우지 못하고 남은 처리본(Uncertain_Outcome 뒤 재시도가 다른 `attemptUuid`로 끝난 경우, Lambda 강제 종료, 교체 전 처리본 등)을 고아 객체로 본다. 고아 객체 정리 방법(정리 시점, Record와 대조하는 기준, 전달된 처리본을 절대 지우지 않는 조건, 비용)은 Design 단계에서 정한다(BE-Q67). 정리 방법이 정해지기 전에는 고아 처리본이 버킷에 남을 수 있고, 수신함에는 Delivered_Processed_Key만 노출되므로 계획자에게 보이지 않는다.
7. 같은 원본에 대한 메시지가 여러 번 오거나 여러 실행이 동시에 처리하면(S3 이벤트 중복, SQS 재전달, 가시성 타임아웃 뒤 재전달), 각 시도는 다른 `attemptUuid`의 처리본을 만든다. Complete_Claim의 Record 조건과 InboxItem `attribute_not_exists(PK)` 조건으로 전달은 1회, InboxItem은 1건이다. 이긴 시도의 처리본은 Delivered_Processed_Key가 되고, 진 시도는 3에 따라 자기 처리본만 지운다. 어떤 시도도 Delivered_Processed_Key를 덮어쓰거나 지우지 않는다. [G2, T5와 같은 성질]
8. THE 3단계 이어받기·포기·완료 Transaction과 `common/ddb.py`의 `transact_with_retry`(그리고 묶음 B에 있는 `transact_get_with_retry`) SHALL 바뀌지 않는다. [G1–G4]

### Requirement 9: 일시 오류, 재시도, 강제 종료, DLQ [BE-PHOTO-07, T9]

**User Story:** As a AWS 담당, I want 일시 오류는 자동으로 다시 시도하고 반복 실패는 실행자에게 실패로 보이길 원한다, so that 실행자가 "처리 중"에서 영영 기다리지 않는다.

#### Acceptance Criteria

1. WHEN S3·DynamoDB 호출 오류, Complete_Claim의 503 `TRY_AGAIN`, 그 밖의 예기치 못한 예외가 나면, THE Photo_Processor SHALL 예외를 올려 Lambda 호출을 실패시킨다(메시지가 남아 가시성 타임아웃 뒤 다시 전달된다). [BE-PHOTO-07]
2. WHEN 메시지의 `attributes.ApproximateReceiveCount`가 3 이상인 호출에서 1의 오류가 나면, THE Photo_Processor SHALL 예외를 올리기 전에 조건부로 `photoStatus = FAILED`, `photoError = RETRY_EXHAUSTED`를 쓴다(조건 `photoKey = :key AND photoStatus IN ('UPLOAD_PENDING','PROCESSING') AND attribute_not_exists(deliveredAt)`). 이 쓰기가 실패해도 원래 예외를 올린다. 메시지는 `maxReceiveCount` 3을 넘어 Photo_DLQ로 간다. [BE-PHOTO-07, §2.7 3-7, T9]
3. Lambda가 강제 종료(타임아웃 30초, 메모리 부족)되면 핸들러 코드가 실행되지 않으므로 2의 `FAILED` 기록은 보장되지 않는다. 3번째 수신에서도 강제 종료되면 메시지는 DLQ로 가고 Record는 `PROCESSING`으로 남을 수 있다. THE Backend SHALL 이 한계를 다음으로 줄이고, 남는 위험을 README에 적는다.
   - 남은 실행 시간 확인: 무거운 단계(원본 읽기, 디코딩·축소, 처리본 업로드, Complete_Claim) 앞에서 `context.get_remaining_time_in_millis()`를 보고, 그 단계를 끝낼 여유(값은 Design 단계에서 정한다)가 없으면 시작하지 않고 1처럼 예외를 올린다. 3번째 수신이면 2의 `FAILED`를 먼저 쓴다.
   - SDK 호출 시간 제한: PhotoProcessorFunction의 S3·DynamoDB 호출이 남은 시간 안에서 끝나도록 연결·읽기 타임아웃과 재시도 횟수를 제한하는 방법을 Design 단계에서 검토한다. 이 검토는 PhotoProcessorFunction에 한정하고, 모든 함수에 걸친 SDK 정책(BE-Q48)은 정하지 않는다.
   - DLQ 이동 뒤 상태 복구: DLQ로 간 메시지의 Record가 `PROCESSING`으로 남은 경우를 `FAILED`로 바로잡는 방법(DLQ 소비 함수, 운영자 절차 등)을 Design 단계에서 정한다(BE-Q68). 정하기 전에도 실행자는 `PROCESSING` 상태에서 사진 교체(Requirement 3.3)와 `TEXT_ONLY` 완료(3단계, `DISCARDED`)를 할 수 있으므로 기록을 보낼 수 있다(docs/05 §5.2.5의 60초 뒤 "글로 완료하기" 강조).
4. WHEN 환경 변수 `FAULT_INJECT`가 `photo`이면, THE Photo_Processor SHALL Record 무시 조건과 `PROCESSING` 전환 뒤, 이미지 처리 전에 강제 예외를 낸다. 그래서 2의 `FAILED` 기록과 DLQ 이동이 실제 경로로 일어난다. [BE-PHOTO-07, T9]
5. THE 장애·지연 주입 SHALL `dev` 스택에서만 켤 수 있다. 템플릿은 `FAULT_INJECT`를 파라미터(`FaultInject`, 허용값은 빈 값과 Design에서 정하는 주입 값, 기본 빈 값)로 PhotoProcessorFunction에만 넘기고, `dev`가 아닌 스택(`demo` 등)에서 빈 값이 아닌 값으로 배포하면 배포가 실패하게 한다(템플릿 `Rules` 등, 방법은 Design). `samconfig.toml`의 `dev`·`demo`에는 이 값을 넣지 않는다. T9·지연 주입 판정 때만 `dev`에 덮어써 배포하고 판정 뒤 되돌린다. [BE-Q59]
6. 검사 실패(Requirement 7.1–7.3)는 일시 오류가 아니다. 재시도하지 않고 `FAILED`로 끝낸다. [BE-PHOTO-04]
7. 재시도는 매번 Requirement 5·6의 무시 조건과 조건부 전이를 처음부터 다시 거친다. Record가 `PROCESSING`이면 처리를 처음부터 다시 하고 새 `attemptUuid`를 쓴다(멱등).

### Requirement 10: 수신함 상세의 사진 [BE-INBOX-02, BE-Q42]

**User Story:** As a 계획자, I want 돌아온 하루에서 실행자가 찍은 사진을 보고 싶다, so that 그날의 장면을 함께 볼 수 있다.

#### Acceptance Criteria

1. WHEN Owner가 `GET /inbox/{itemId}`를 호출하고 InboxItem `hasPhoto = true`이며 Record에 `processedKey`가 있으면, THE Inbox_Function SHALL `record.photoUrl`에 Processed_Key의 presigned GET URL(유효 15분)을 담는다. [BE-INBOX-02, §3.5]
2. THE `record.photoCaption` SHALL 1의 경우에만 `plan.places`의 마지막 장소(배열의 마지막 원소) 이름 + "에서"이고, 저장하지 않고 응답 때 만든다. 장소가 없거나 이름이 비면 `null`이다. [§3.5]
3. WHEN `hasPhoto`가 거짓이거나 `processedKey`가 없으면, THE `record.photoUrl`과 `record.photoCaption` SHALL `null`이다. [§3.5]
4. IF `hasPhoto = true`인데 `processedKey`가 없으면, THEN THE Inbox_Function SHALL `photoUrl`·`photoCaption`을 `null`로 응답하고 사유 코드만 로그에 남긴다(4단계 BE-Q47처럼 500으로 막지 않고 글은 보여 준다). [BE-Q60]
5. THE presigned GET 발급 SHALL 4단계 권한 검사(InboxItem 없음·`ownerId` 불일치는 404) 뒤에만 한다. 실행자 본인용 사진 조회 경로는 이번 단계에 없다(docs/02 §2.8 "사진 GET URL: 해당 실행자"는 API가 정해지지 않았다, BE-Q61).
6. THE 4단계 상세 응답의 나머지 형태(허용 목록, `item`, `plan`)는 바꾸지 않는다. [BE-NFR-07]

### Requirement 11: IAM 최소 권한 [BE-INFRA-06, BE-NFR-02]

**User Story:** As a AWS 담당, I want 각 함수가 자기 일에 필요한 버킷 prefix와 큐에만 접근하길 원한다, so that 한 함수가 잘못돼도 다른 사진이나 데이터에 손대지 못한다.

#### Acceptance Criteria

1. THE Claims_Function SHALL 3단계 DynamoDB 권한(`GetItem`, `PutItem`, `UpdateItem`, `ConditionCheckItem`, HaruTable만)을 유지하고, `s3:PutObject`를 `${PhotoBucketArn}/photos/original/*`에만 더한다(presigned PUT은 발급한 역할의 권한으로 실행된다). [BE-INFRA-06]
2. THE Inbox_Function SHALL 4단계 DynamoDB 권한을 유지하고, `s3:GetObject`를 `${PhotoBucketArn}/photos/processed/*`에만 더한다. [BE-INFRA-06]
3. THE PhotoProcessorFunction SHALL 다음만 갖는다: HaruTable `GetItem`·`PutItem`·`UpdateItem`(Complete_Claim의 Update·Put과 상태 전이·조회), `s3:GetObject`(`photos/original/*`), `s3:PutObject`·`s3:DeleteObject`(`photos/processed/*`), Photo_Queue 소비 권한(`sqs:ReceiveMessage`·`DeleteMessage`·`GetQueueAttributes`, 이 큐만). `index/*`, `Scan`, `DeleteItem`, 버킷 전체 권한, 와일드카드 액션은 없다. [BE-INFRA-06]
4. THE `MeFunction`·`PlansFunction`·`PreSignUpFunction` SHALL 사진 버킷·큐 권한을 갖지 않는다.
5. IF Complete_Claim이 쓰는 Transaction 작업(Update·Put)이 3에 없는 권한을 요구하는 것으로 확인되면(예: `ConditionCheckItem`), THEN THE Backend SHALL 그 작업에 필요한 최소 권한만 더하고 근거를 템플릿 주석과 README에 남긴다. 3단계 기준으로 Complete_Claim은 `ConditionCheck`를 쓰지 않는다.
6. THE `tests/unit/test_template.py` SHALL 위 함수별 Action·Resource 집합을 정확히 단언하고, 모든 함수에 `*`·`DeleteItem`(DynamoDB)·`Scan`이 없다는 기존 단언을 유지한다.

### Requirement 12: 지표와 알람 [BE-OBS-01, BE-OBS-02]

**User Story:** As a AWS 담당, I want 사진 처리 시간과 실패, DLQ 적체를 지표와 알람으로 보고 싶다, so that 시연 전에 사진 경로 이상을 바로 알 수 있다.

#### Acceptance Criteria

1. THE Photo_Processor SHALL 처리본을 쓰고 Complete_Claim까지 끝난 레코드마다 EMF 지표 `PhotoProcessingMs`(단위 `Milliseconds`, 원본 읽기부터 완료 호출 직후까지)를 1건 남긴다. 무시·검사 실패에는 남기지 않는다. [BE-OBS-01]
2. THE Photo_Processor SHALL `FAILED`를 실제로 쓴 경우(검사 실패, 재시도 소진)마다 EMF 지표 `PhotoFailed`(단위 `Count`) 1을 남긴다. [BE-OBS-01]
3. THE `common/metrics.py` SHALL 단위를 지정할 수 있게 확장하되 기존 지표 3종(`ClaimConflict`·`CompleteDuplicate`·`StaleRequestRejected`)의 출력은 그대로 둔다(네임스페이스 `Haru`, 차원 없음). [BE-Q37]
4. THE Backend SHALL `PhotoDLQ`의 `ApproximateNumberOfMessagesVisible` 최대값이 1분 주기 1회에서 0을 넘으면 `ALARM`이 되는 CloudWatch 알람(`PhotoDLQNotEmpty`)을 둔다. `TreatMissingData: notBreaching`. [BE-OBS-02, T9]
5. THE 알람 SHALL 알림 대상(SNS 등)을 두지 않는다. docs에 알림 대상이 없다. 상태 확인은 콘솔·API로 한다. [BE-Q62]
6. THE 지표와 로그 SHALL 사용자 ID, 키, presigned URL, 글 본문을 담지 않는다. 처리 로그는 결과 코드(`ignored`·`failed`·`delivered`·`not_delivered`)와 사유 코드만 남긴다. [BE-NFR-03]
7. Photo_Processor가 Complete_Claim을 부를 때 Claim이 이미 `COMPLETED`이면 3단계 `CompleteDuplicate` 지표가 1 오른다(3단계 동작, 바꾸지 않음). 이 지표가 API 중복 완료와 섞인다는 점은 README에 적는다. [BE-Q63]

### Requirement 13: 로컬 개발 환경 [BE-INFRA-08, §2.4]

**User Story:** As a 개발 담당, I want 로컬에서 업로드 → 알림 → 처리 → 완료 흐름을 돌려 보고 싶다, so that AWS에 배포하기 전에 조건식과 흐름 오류를 잡는다.

#### Acceptance Criteria

1. THE `local/init/01_haru.py` SHALL Floci에 사진 버킷(이름은 `PHOTO_BUCKET` 환경 변수, 기본 `haru-photos-local`), CORS(`http://localhost:5173`, `PUT`·`GET`, `Content-Type`), `photos/original/` 7일 수명 주기, PhotoDLQ, PhotoQueue(`maxReceiveCount` 3, 가시성 타임아웃), 버킷 알림(prefix `photos/original/`)을 멱등하게 만든다. 단계마다 `ok step=` 로그를 남긴다. [§2.4.1]
2. THE `docker-compose.yml` SHALL `aws` 서비스에 `FLOCI_AUTH_VALIDATE_SIGNATURES: "true"`를 두고, `api` 서비스에 `PHOTO_BUCKET`, `PHOTO_QUEUE_URL`, `PUBLIC_S3_ENDPOINT: http://localhost:4566`을 둔다. 이미지 태그는 고정 그대로다. [§2.4.1, BE-INFRA-08]
3. THE presigned URL SHALL `PUBLIC_S3_ENDPOINT`가 있으면 그 호스트와 경로 방식 주소(`addressing_style='path'`)로 서명하고, 비었으면(AWS) 기본 엔드포인트로 서명한다. 서버 측 S3 호출은 `AWS_ENDPOINT_URL`을 따른다. [§2.4.3]
4. THE 로컬 어댑터 SHALL SQS 폴러를 둔다: `ReceiveMessage(AttributeNames=['All'])`로 받은 메시지를 Lambda SQS 이벤트 형태(`Records[0].body`, `attributes.ApproximateReceiveCount`, `messageId`)로 만들어 Photo_Processor 핸들러에 넘기고, 성공이면 삭제, 예외면 남긴다. 폴러는 `STAGE=local`이고 `PHOTO_QUEUE_URL`이 있을 때만 켜진다. [§2.4.1 3]
5. THE 어댑터 이미지 SHALL Pillow를 설치한다(로컬 어댑터 전용 `local/adapter/requirements.txt`). `src/requirements.txt`에는 Pillow를 넣지 않는다(Lambda에서는 레이어로 받는다). [BE-INFRA-08, Requirement 14.9]
6. Floci가 S3 → SQS 알림, presigned PUT의 `ContentLength` 서명 검사, 수명 주기, `IfMatch`·`IfNoneMatch` 조건부 요청을 실제로 지원하는지는 첫 구동 때 항목별로 확인하고 결과를 README §5에 적는다. 판단은 문서가 아니라 실제 구동 결과로 한다. 알림이 동작하지 않으면 docs/02 §2.4.2 대체 구성 A의 방식(업로드 확인 뒤 어댑터가 S3 이벤트 형태 메시지를 큐에 넣음)을 로컬 전용 우회로 쓰고 그 사실을 README에 적는다. [§2.4.2, BE-Q64]
7. 로컬 결과는 T 판정 근거가 아니다(BE-Q15).

### Requirement 14: 테스트

**User Story:** As a 개발 담당, I want 사진 경로의 정상·실패·경합을 자동 테스트로 고정하고 싶다, so that 이후 단계에서 G1–G4와 사진 개인정보 보장이 깨지지 않는다.

#### Acceptance Criteria

1. WHEN `pytest tests/unit`을 실행하면, THE Backend SHALL 다음을 실패 0건으로 통과한다.
   - **이미지 순수 함수**: 정상 JPEG·PNG(투명 포함)·그레이스케일·팔레트, 1600px 초과·이하, EXIF Orientation 1–8 각각의 회전·반전 반영, GPS EXIF가 있는 JPEG에서 처리본의 EXIF·GPS·XMP·ICC·주석 부재, 손상 파일(잘린 JPEG·PNG, 헤더만 있는 파일, 0바이트), 매직 바이트 불일치(확장자만 jpg인 GIF 등), 크기 초과, 헤더 기준 픽셀 수 초과, `DecompressionBombWarning`(한도 초과 ~ 2배 이하)과 `DecompressionBombError`(2배 초과) 모두 `TOO_MANY_PIXELS`이고 경고가 테스트 밖으로 새지 않음. 테스트 이미지는 테스트 안에서 Pillow로 만들고(바이너리 픽스처를 늘리지 않음), GPS·Orientation EXIF는 `Image.Exif`로 넣는다.
   - **메모리**: 40,000,000픽셀 정상 이미지 처리의 최대 상주 메모리를 별도 프로세스에서 측정(`resource.getrusage`의 `ru_maxrss`)해 기준(1024MB의 70%) 이하인지 확인하고 측정값을 출력한다. 느린 테스트 마커(`slow`)로 분리하되 Checkpoint에서는 반드시 실행한다.
   - **핸들러 분기** (moto S3·SQS·DynamoDB): `s3:TestEvent`·`Records` 없음·JSON 아님·잘못된 키 무시, ClaimLookup·Record 없음, 전달됨·`DISCARDED`·키 불일치 무시(처리본을 만들지 않음), `READY`·미전달 → 처리 안 함(`unexpected_ready`), ETag 불일치·객체 없음 → 무시, `PROCESSING` 조건 실패, 검사 실패 → `FAILED`·`photoError`·재시도 없음, 정상 → 처리본(`attemptUuid` 키)·`complete_claim(WITH_PHOTO)`·InboxItem `hasPhoto = true`·Record `READY`·`processedKey`.
   - **경합** (순차 재현): 처리 중 `TEXT_ONLY` 완료 → InboxItem 1건 `hasPhoto = false`, 이 시도의 처리본 삭제(T10의 순차판). 처리 중 교체 → 이전 사진 미전달·처리본 삭제, 새 사진으로 완료(T15의 순차판). 처리 중 포기 → 확인 읽기 후 삭제. 기한 지난 대체(`EXPIRED`) → 미전달·삭제. 같은 메시지 두 번(순차·두 시도가 완료 직전까지 진행한 뒤 차례로 완료) → InboxItem 1건, Record 전달 1회, Delivered_Processed_Key는 남고 진 시도의 처리본만 삭제. 같은 키에 원본 재업로드(ETag가 바뀐 두 이벤트) → 첫 이벤트는 무시되거나 처리되고, 전달된 처리본은 전달 시점의 객체에서 만든 것.
   - **완료 결과 불확실**: Complete_Claim이 트랜잭션을 커밋한 뒤 응답 전에 오류(주입)를 내면 처리본을 지우지 않고 예외를 올리며, 다음 시도에서 Record가 전달됨으로 확인되어 무시되고 Delivered_Processed_Key가 남는다. 확인 읽기가 실패해도 처리본을 지우지 않는다. 503 `TRY_AGAIN` → 지우지 않고 예외.
   - **재시도·시간**: S3·DynamoDB 오류 → 예외, `ApproximateReceiveCount >= 3` → `FAILED`(`RETRY_EXHAUSTED`) 후 예외, `FAILED` 쓰기 실패여도 원래 예외, `FAULT_INJECT=photo` → `PROCESSING` 뒤 예외, 남은 실행 시간이 부족하면 무거운 단계를 시작하지 않고 예외(가짜 context로 주입).
   - **API**: `PUT /record` 사진 경계(contentType 2종·그 외, size 0·1·10,485,760·10,485,761·비정수·불리언), 성공 시 `upload` 형태와 `expiresAt`, presign 인자에 `ContentType`·`ContentLength`, Transaction 실패 시 presign 미호출, 사진 있는 저장·교체에서 `processedKey`·`photoError` 제거, 교체에서 `letter`·`updatedAt` 불변, 사진 없이 저장 시 사진 속성 불변, `POST /record/photo` 성공(`{ upload }`)·Record 없음 400 `RECORD_REQUIRED`·끝난 이어받기 409·남 403·없음 404, `token_use != "id"` → DB·S3 호출 없이 401.
   - **수신함 상세**: 사진 있음 → `photoUrl`(presign 인자 `ExpiresIn=900`, Delivered_Processed_Key)·`photoCaption`(마지막 장소 + "에서"), 사진 없음 → 둘 다 `null`, `hasPhoto = true`·`processedKey` 없음 → 둘 다 `null`.
   - **템플릿·IAM·라우트**: `POST /claims/{claimId}/record/photo`가 `routes.py`·템플릿·어댑터와 일치, 함수별 권한 집합, `FaultInject`가 `dev`가 아닌 스택에서 거부되는 규칙, 알람, EMF 단위, 로그에 URL·사용자 ID 없음.
   - **회귀**: 1–4단계 기존 단위 테스트 전체. 3단계 Property 12–15와 4단계 묶음 A의 Property 18–23이 그대로 통과한다.
2. THE 속성 기반 테스트(Hypothesis, 최소 100회) SHALL 다음을 포함한다(필수).
   - 임의 크기·모드(RGB·RGBA·L·P)·Orientation·EXIF(GPS 포함)의 이미지에 대해 처리본은 긴 변 ≤ 1600, JPEG, 메타데이터 없음, 방향 보정 뒤 비율 유지(반올림 오차 1px 이내).
   - 임의의 연산 열(사진 업로드, 원본 재업로드, 교체, 처리 메시지 전달·중복 전달·지연 전달, 완료 직후 오류 주입, `TEXT_ONLY` 완료, 포기, 기한 지난 대체)과 임의의 처리 순서(시도 사이 끼어들기)에 대해: InboxItem은 최대 1건, `hasPhoto = true ⇔ Record photoStatus = READY ⇔ processedKey 있음 ⇔ deliveredAt 있음 ∧ 사진 전달`, 전달된 처리본은 전달 시점의 Current_Photo(그 ETag)에서 만든 것, 지난 사진의 처리본은 전달되지 않음, Delivered_Processed_Key 객체는 끝까지 존재하고 내용이 바뀌지 않음, Definitive_Outcome이 "확실히 전달 안 됨"인 시도의 처리본은 남지 않음.
3. THE Backend SHALL `tests/local/test_local_photo.py`(마커 `local`)로 Local_Env에서 확인한다: presigned PUT 업로드(로컬 호스트) → 알림 → 폴러 → 처리 → 완료 → 계획자 `GET /inbox/{itemId}`의 `photoUrl`로 처리본을 받아 EXIF·GPS가 없는지, 손상 파일 → `FAILED` 후 `TEXT_ONLY` 완료, 처리 전 교체 → 새 사진으로 완료, 잘못된 `Content-Length`로 업로드하면 서명 검사로 거부, 같은 presigned URL로 두 번 업로드(재업로드) → 전달된 처리본이 하나이고 전달 시점 객체에서 만든 것. 사진 상태는 DynamoDB를 직접 읽어 확인한다. 기존 로컬 테스트 23건(묶음 A)도 그대로 통과한다. Floci가 지원하지 않아 확인할 수 없는 항목은 실패가 아니라 "로컬 미지원"으로 출력하고 README에 적는다(BE-Q64).
4. WHERE 4단계 묶음 B(`GET /claims/{claimId}/record`)가 브랜치에 있으면, THE 로컬·AWS 테스트 SHALL 같은 흐름에서 `GET /record`의 `photoStatus`(`UPLOAD_PENDING` → `PROCESSING`/`FAILED`/`READY`)와 `delivered`도 확인한다. 묶음 B가 없으면 이 사례는 건너뛰고(`ROUTES`에 경로가 없으면 skip) 이유를 출력한다.
5. THE Backend SHALL `tests/integration/test_photo.py`에 AWS 대상 T8·T10·T11·T15를, 같은 파일의 `@pytest.mark.fault` 테스트에 T9와 지연 주입 경합 테스트를 둔다. 실행·판정은 AWS 담당이 한다. [docs/07 §7.5·§7.6]
   - T8: 손상 이미지 업로드 → `photoStatus = FAILED`, 글 유지, `TEXT_ONLY` 완료 200, InboxItem 1건 `hasPhoto = false`.
   - T9(fault, `dev`만): `FAULT_INJECT=photo`로 배포한 `dev` 스택에서 업로드 → 3회 수신 뒤 DLQ에 메시지, `FAILED`(`RETRY_EXHAUSTED`), `PhotoDLQNotEmpty` 알람 `ALARM`(대기 시간 상한을 두고 폴링). 끝나면 테스트가 만든 메시지만 지운다(본문의 키로 식별. 큐 전체 purge 안 함).
   - T10: 처리 중(Record `PROCESSING` 관측 뒤) `TEXT_ONLY` 완료 → InboxItem 1건 `hasPhoto = false`, 이후 처리 Lambda가 전달하지 않음, 이 사진의 처리본이 남지 않음.
   - T11: GPS EXIF가 있는 JPEG 업로드 → 처리본에 EXIF·GPS 없음. 판정 도구는 `exiftool`이 있으면 `exiftool`, 없으면 Pillow로 다시 읽어 확인하고 어느 쪽을 썼는지 결과에 남긴다. 처리본은 계획자의 `GET /inbox/{itemId}`의 `photoUrl`로 받는다.
   - T15: 첫 사진 업로드 → 처리 완료 전(Record `PROCESSING` 관측 뒤) 교체 → 두 번째 사진 업로드 → 두 번째 사진으로 완료, 수신함 사진이 두 번째 원본에서 만든 처리본, 첫 사진의 처리본은 남지 않음.
   - **T10·T15의 판정**: `PROCESSING`을 관측하지 못하면(처리가 너무 빨라 경합 구간을 만들지 못함) 그 실행은 통과도 실패도 아닌 **미검증**으로 기록한다(결과 파일에 `"verdict": "unverified"`와 관측한 상태 열을 남기고 pytest에서는 `xfail(strict=False)`가 아닌 명시적 `skip` 사유 "PROCESSING 미관측, 미검증"). 단위 테스트의 순차 재현은 AWS 판정을 대체하지 않는다.
   - **지연 주입 경합(fault, `dev`만)**: `PROCESSING` 전환 뒤 처리 전에 정해진 시간만큼 기다리는 `dev` 전용 지연 주입 값(Requirement 9.5)으로 배포한 `dev` 스택에서 T10·T15를 다시 실행해, 경합 구간을 확실히 만든 판정을 얻는다. 주입 값 이름, 지연 시간, 가시성 타임아웃과의 관계는 Design 단계에서 정한다(BE-Q69). 지연 주입 실행 결과가 T10·T15의 최종 판정 근거다.
   - **공통**: 상태 확인은 DynamoDB `ConsistentRead`(BE-Q38), 결과는 `save_result`. 결과 파일에는 키와 상태만 남기고 presigned URL을 남기지 않는다.
6. THE 통합 테스트 정리 SHALL 3단계에서 보완한 `_cleanup`(Cognito 사용자, `PLAN#`·`USER#` 파티션과 ClaimLookup, 멱등 키, 실패 기록과 teardown 오류)을 그대로 유지하고, 사진 객체 정리를 더한다.
   - 등록: 사진 테스트는 업로드할 Claim의 `claimId`를 업로드 **전에** `created_photo_claim_ids`에 등록한다. 처리본 키(`attemptUuid`)는 테스트가 미리 알 수 없으므로 키가 아니라 Claim 단위로 등록한다.
   - 삭제: 정리 때 등록된 `claimId`마다 `photos/original/{claimId}/`와 `photos/processed/{claimId}/` prefix만 `ListObjectsV2`(페이지 이어 읽기)로 찾아 지운다. 버킷 전체 목록·삭제, 다른 prefix 삭제는 하지 않는다. 사진 정리는 DynamoDB 정리와 독립적으로 시도하고, 실패는 기존과 같이 `cleanup-failures-*.json`(종류 `s3_prefix`, 대상 prefix, 오류 코드)에 남긴다.
   - DLQ: T9가 만든 메시지는 테스트 안에서 지운다(5의 T9). 정리 단계에서 큐를 purge하지 않는다.
   - 정리 로직을 바꾸면 `tests/unit/test_integration_cleanup.py`에 사진 prefix 정리(moto S3, 다른 Claim의 객체가 남는지 포함)와 실패 기록 회귀 테스트를 더한다.
   - 테스트 실행 주체의 추가 권한(BE-Q38): 사진 버킷 `s3:PutObject`(presigned로 하므로 불필요할 수 있음)·`s3:GetObject`·`s3:ListBucket`(prefix 조건)·`s3:DeleteObject`, DLQ `sqs:ReceiveMessage`·`DeleteMessage`, `cloudwatch:DescribeAlarms`. README 2.1절에 적는다.
7. THE Backend SHALL `sam validate --lint`와 `sam build --use-container`(Pillow 레이어)를 통과한다. Docker를 쓸 수 없으면 그 사실과 대안(레이어를 `manylinux2014_x86_64` wheel로 받는 방식)을 보고하고 사용자에게 묻는다. `sam deploy`는 하지 않는다. [docs/07 §7.3 5단계 위험]
8. THE 4단계 이후 PR마다 `test_concurrency.py`를 다시 돌린다는 규칙(docs/07 §7.2)을 5단계 판정 실행표에 적는다.
9. THE `test_no_stage3_dependencies`(src/requirements.txt에 langgraph·langchain·pillow 없음) SHALL 그대로 통과한다. Pillow는 `layers/pillow/requirements.txt`와 로컬 어댑터 요구사항에만 둔다.

### Requirement 15: 계약·데이터 설계·정합성 유지와 인계

**User Story:** As a 개발 담당, I want 5단계를 더해도 기존 계약과 트랜잭션 보장이 그대로이고 인계 문서가 실제 상태와 맞길 원한다, so that 리뷰와 AWS 판정이 혼동 없이 진행된다.

#### Acceptance Criteria

1. THE Backend SHALL docs/03 §3.4·§3.5의 요청·응답 필드 이름, HTTP 상태, 에러 코드를 바꾸지 않는다. 계약에 없는 세부는 BE-Q로 남기고 docs/03은 고치지 않는다. [BE-NFR-07]
2. THE Backend SHALL docs/02 §2.6의 키 설계를 바꾸지 않고 새 테이블·GSI를 만들지 않는다. Record의 사진 속성은 docs/02 §2.5에 있는 것만 쓴다.
3. THE 3단계 Transaction(`claim_plan`, `abandon`, `complete_claim`, `complete_by_user`)의 조건식·갱신식·실패 분기 SHALL 바뀌지 않는다. `put_record`는 사진 분기를 위해 Record Update 식만 넓히고, Plan·Claim ConditionCheck와 `attribute_not_exists(deliveredAt)` 조건, 실패 분기는 그대로 둔다. 변경 범위는 `git diff`로 확인해 PR에 적는다. [G1–G4, Requirement 2.1]
4. THE `backend/README.md` SHALL 5단계 현황, 배포 전 주의(레이어 `--use-container`, 버킷 이름 고정, `FaultInject`), 함수별 IAM 표(PhotoProcessorFunction 추가, Claims·Inbox의 S3 권한), 판정 실행표(T8–T11·T15, T9 fault 절차, 묶음 B 의존 사례), 로컬 결과, 미결 질문(BE-Q34·BE-Q42 해소, BE-Q49–BE-Q69)을 담는다.
5. THE 5단계 AWS 판정 SHALL 4단계 묶음 A의 판정(T1 확장·T2·T17)과 같은 배포에서 함께 하거나 그 뒤에 한다. 판정 순서와 회귀(T3–T7·T14·T16)를 README 판정 실행표에 적는다.
6. THE 5단계 PR SHALL base를 `feat/be-4-inbox`로 두고, 묶음 B 커밋(`f3626c0`)을 포함하지 않는다. 기존 PR #1–#6과 그 브랜치는 바꾸지 않는다. push·PR은 사용자 확인 뒤에 한다.
7. THE `docs/08-open-questions.md` SHALL BE-Q34(5단계에서 해소)·BE-Q42(해소)를 정리하고 BE-Q49–BE-Q69를 추가한다. BE-Q2는 BE-Q66과 함께 정리한다. BE-Q45·BE-Q46·BE-Q48은 바꾸지 않는다.

## 미결 사항

`docs/08-open-questions.md` §8.1에 추가하거나 기존 번호를 적용한다. 임시 결정은 구현에 쓰고, 팀 결정이 다르면 해당 기준을 고친다.

| # | 내용 | 임시 결정 |
|---|---|---|
| BE-Q2 (기존) | 처리 Lambda의 "`READY`이고 `deliveredAt` 없음" 상태 | 정상 경로에서 생기지 않는다. 생기면 처리하지 않고 사유 코드만 남긴다(Requirement 5.7). docs/02의 "완료만 다시 호출" 경로는 BE-Q66 |
| BE-Q34 (기존) | 3단계 `PUT /record`의 `photo` 400 | **5단계에서 해소**: 계약대로 업로드 URL을 발급한다(Requirement 2.8) |
| BE-Q37 (기존) | EMF 단위 `Count` 고정 | `PhotoProcessingMs`만 `Milliseconds`. 기존 3종은 그대로(Requirement 12.3) |
| BE-Q38 (기존) | AWS 판정 테스트의 DynamoDB 직접 조회 | 사진 상태 확인에도 쓴다. 테스트 실행 주체에 S3 `GetObject`·`PutObject`·`DeleteObject`(테스트 키만), SQS DLQ `ReceiveMessage`·`DeleteMessage`, CloudWatch `DescribeAlarms`가 더 필요하다 |
| BE-Q42 (기존) | 4단계 `photoUrl`·`photoCaption` null | **5단계에서 해소**(Requirement 10) |
| BE-Q45·BE-Q46·BE-Q48 (기존) | `claimerNickname` null, `GET /record` 503, SDK 타임아웃·재시도 | 바꾸지 않는다. BE-Q46은 사진 폴링(S3 연동)의 전제다(Introduction "4단계 묶음 B 의존") |
| BE-Q49 (신규) | 버킷·큐 보안 기본값(SSE-S3, TLS 강제, `BucketOwnerEnforced`, SSE-SQS). docs는 퍼블릭 차단만 적었다 | **임시 결정 유지**: 둔다(Requirement 1.5·1.6·4.5) |
| BE-Q50 (신규) | `photo.size`의 하한과 검증 `details` 키 | 1 이상 정수. `details` 키는 `photo.contentType`·`photo.size`(본문 경로 표기, docs/03 공통 규칙) |
| BE-Q51 (신규) | `POST /record/photo` 응답에 `record`를 담을지. §3.4는 "응답은 위와 같은 `upload`" | **권장안: `{ upload }`만.** 프론트엔드 리뷰 대상(S3 연동 때 MSW와 대조) |
| BE-Q52 (신규) | `POST /record/photo`인데 Record가 없을 때. §3.4·§3.6에 이 경로의 코드가 없다 | **권장안: 400 `RECORD_REQUIRED`**(§3.6의 "기록 없이 완료 요청"과 같은 코드 재사용). 프론트엔드 리뷰 대상 |
| BE-Q53 (신규) | DLQ 보존 기간 | 14일(최대) |
| BE-Q54 (신규) | Original_Key 형식이 아닌 키(사람이 직접 올린 객체 등) | 무시하고 정상 종료 |
| BE-Q55 (신규) | `photoError` 값의 형식. docs는 속성 이름만 적었다 | **임시 결정 유지**: 사유 코드 5종(Requirement 6.4). 응답에는 나가지 않는다 |
| BE-Q56 (신규) | 최대 해상도. docs는 "최대 해상도 검사"만 적었다 | **임시 결정 유지**: 40,000,000픽셀(약 7,700 × 5,200). `DecompressionBombWarning`·`Error` 모두 실패. 40MP 처리의 최대 메모리를 측정해 1024MB의 70%를 넘으면 다시 정한다 |
| BE-Q57 (신규, 수정) | 처리본 키의 `uuid`. docs는 `photos/processed/{claimId}/{uuid}.jpg`만 적었다 | 처리 시도마다 새 `attemptUuid`(Requirement 7.5). 같은 원본의 처리본 키를 공유하면 중복 실행의 진 쪽이 이미 전달된 처리본을 덮어쓰거나 지울 수 있어 바꿨다. 처리본 업로드는 `IfNoneMatch='*'`. 대가로 고아 처리본이 생길 수 있다(BE-Q67) |
| BE-Q58 (신규) | JPEG 품질, 투명 PNG 처리 | **임시 결정 유지**: 품질 85, 흰 배경 합성 |
| BE-Q59 (신규) | `FAULT_INJECT`를 배포에 넘기는 방법 | 템플릿 파라미터 `FaultInject`(기본 빈 값). **`dev` 스택에서만 허용**하고 그 밖의 스택에서는 빈 값이 아니면 배포가 실패한다(Requirement 9.5, 방법은 Design). T9·지연 주입 판정 때만 `dev`에 덮어써 배포하고 판정 뒤 되돌린다 |
| BE-Q60 (신규) | `hasPhoto = true`인데 `processedKey`가 없을 때(정상 경로에 없음) | 사진 필드만 `null`, 글은 200으로 보여 준다(BE-Q47의 500과 다르게 둔 이유: 사진은 부가 정보다) |
| BE-Q61 (신규) | docs/02 §2.8의 "사진 GET URL: 해당 실행자" 경로. 계약에 실행자용 사진 조회 응답 필드가 없다 | 이번 단계에서 만들지 않는다. 필요하면 계약 변경으로 정한다 |
| BE-Q62 (신규) | DLQ 알람의 알림 대상 | **임시 결정 유지**: 두지 않는다(상태만). SNS 주제·구독은 7단계 알람·대시보드와 함께 정한다 |
| BE-Q63 (신규) | 처리 Lambda 경로에서도 `CompleteDuplicate`가 오른다 | 3단계 동작을 바꾸지 않는다. 지표 해석 주의를 README에 적는다 |
| BE-Q64 (신규) | Floci의 S3 → SQS 알림·`ContentLength` 서명 검사·수명 주기·`IfMatch`·`IfNoneMatch` 지원 | **실제 로컬 구동 결과로 판단한다.** 구현 첫 구동 때 항목별로 확인해 README §5에 적고, 그 결과로 로컬 전용 우회(어댑터가 이벤트 메시지를 넣음) 사용 여부와 "로컬 미지원" 테스트 항목을 정한다 |
| BE-Q65 (신규) | presigned PUT URL 재사용(10분 안 같은 키에 다시 PUT)으로 원본이 바뀔 수 있다. 막으려면 `If-None-Match: *`를 서명 헤더에 넣어야 한다 | **미결.** 확인할 것: ① S3 조건부 쓰기 헤더를 presigned PUT 서명에 넣는 방법(boto3 `generate_presigned_url`의 `IfNoneMatch` 지원) ② 버킷 CORS `AllowedHeaders`에 `If-None-Match` 추가 ③ `upload.headers`에 헤더가 하나 늘어나는 것을 프론트가 그대로 보내는지(프론트엔드 리뷰, 계약은 `headers`가 맵이라 형태는 같다) ④ Floci 지원(BE-Q64). 정하기 전까지 처리 Lambda는 이벤트의 ETag와 일치하는 객체만 처리한다(Requirement 5.9) |
| BE-Q66 (신규) | docs/02 §2.7 3-1·3-6의 "`READY`이고 `deliveredAt` 없음이면 완료만 다시 호출" 경로와 3단계 `complete_claim(WITH_PHOTO)`의 `PROCESSING` 전제가 맞지 않는다 | Complete_Claim은 바꾸지 않는다. 이 상태는 정상 경로에서 생기지 않고, 생기면 처리하지 않는다(Requirement 5.7). docs/02 §2.7 문구를 "완료 트랜잭션만 `READY`를 쓰므로 생기지 않는다"로 고칠지는 팀이 정한다 |
| BE-Q67 (신규) | 고아 처리본(완료 결과 불확실 뒤 재시도, 강제 종료, 교체 전 처리본, 진 시도의 삭제 실패) 정리 | **Design에서 정한다.** 조건: 전달된 처리본(Record `processedKey`)은 절대 지우지 않는다. 후보: Record와 대조하는 정리 함수(주기 실행), 태그 기반 수명 주기 등 |
| BE-Q68 (신규) | Lambda 강제 종료로 `FAILED`를 못 쓰고 DLQ로 간 메시지의 Record가 `PROCESSING`으로 남는다 | **Design에서 정한다.** 후보: DLQ 소비 함수가 조건부로 `FAILED`(`RETRY_EXHAUSTED`) 기록, 운영자 절차. 정하기 전에도 실행자는 교체·글로 완료가 가능하다 |
| BE-Q69 (신규) | T10·T15를 AWS에서 확실히 재현하는 `dev` 전용 지연 주입 | **Design에서 정한다.** `FaultInject`의 값 하나로 `PROCESSING` 전환 뒤 지연. 지연 시간은 Lambda 타임아웃 30초·가시성 타임아웃 180초 안에서 정한다. `dev`만 허용(BE-Q59) |
