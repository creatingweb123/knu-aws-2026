# Implementation Plan: backend-stage5-photo-pipeline

## Overview

백엔드 5단계(사진 파이프라인)를 `feat/be-5-photo-pipeline`(base `feat/be-4-inbox`, PR #1 head `dc3af68`) 위에 `backend/` 아래 Python 3.12로 구현한다. 근거는 같은 폴더의 `requirements.md`, `design.md`(승인됨)다.

작업은 세 묶음으로 나눈다.
- **묶음 P (작업 1–16)**: 계약 변경·묶음 B 없이 구현·검증할 수 있는 전부. 프론트 승인 대상(BE-Q51·BE-Q52)은 권장안대로 구현하고, BE-Q65 조건부 업로드는 스위치(`UploadIfNoneMatch`) 기본 꺼짐으로 구현한다.
- **묶음 B 의존 (작업 17)**: 4단계 묶음 B(`GET /claims/{claimId}/record`, `f3626c0`, BE-Q46 승인 대기)가 브랜치에 들어온 뒤에만 한다.
- **프론트 승인 의존 (작업 18)**: BE-Q51·BE-Q52·BE-Q65의 프론트엔드 리뷰·승인 뒤에만 한다.

공통 규칙
- 3단계 트랜잭션(`claim_plan`, `abandon`, `complete_claim`, `complete_by_user`)과 `common/ddb.py`의 `table`·`transact_with_retry`·`ConditionFailed`·`_cancellation_codes`·`BACKOFF_SECONDS`는 바꾸지 않는다. `put_record`는 Record Update 식의 사진 분기와 반환 형태(`(record, upload)`)만 바꾼다(Requirement 15.3). `common/ddb.py`에는 `use_table`만 더한다.
- API 계약(docs/03)과 DynamoDB 키 설계(docs/02 §2.6)는 바꾸지 않는다. docs/03 수정은 작업 18(승인 뒤)에서만 한다.
- 기존 PR #1–#6과 그 브랜치, `feat/be-4-record-inbox`, 프론트엔드 작업 트리(`/home/hwkim/knu-aws-2026`)는 바꾸지 않는다.
- AWS 리소스 생성·`sam deploy`·AWS 통합 테스트 실행은 하지 않는다. AWS 대상 테스트는 코드만 쓰고 수집(`--collect-only`)까지 확인한다. 판정은 AWS 담당이 Dev_Stack(`haru-dev`)에서 한다(BE-Q15).
- 속성 기반 테스트(Property 25–28)는 필수다. Hypothesis 최소 100회, 태그 `Feature: backend-stage5-photo-pipeline, Property {n}`.
- 작업 그룹마다 해당 테스트를 실행하고 실패 원인을 고친 뒤 다음 그룹으로 넘어간다. 1–4단계 회귀 테스트는 Checkpoint마다 필수다.
- T10·T15의 "미검증(unverified)"은 합격으로 처리하지 않는다. 단위 테스트의 순차 재현은 AWS 판정을 대체하지 않는다.
- Floci에서 확인할 수 없는 기능은 "로컬 미지원"으로 표시하고 AWS 판정 항목으로 넘긴다(작업 11·13).
- 미결 항목은 임시 결정으로 구현하고 코드 주석과 PR에 번호를 남긴다: BE-Q2, BE-Q37, BE-Q38, BE-Q49–BE-Q72. BE-Q45·BE-Q46·BE-Q48은 바꾸지 않는다. BE-Q34·BE-Q42는 이 단계에서 해소한다.
- 커밋은 의미 단위로 하고 push·PR은 사용자 확인 뒤에 한다.
- 의존성은 각 그룹 머리의 `선행:` 줄과 끝의 Task Dependency Graph로 적는다.

## Tasks

### 묶음 P: 계약 변경·묶음 B 없이 하는 작업

- [x] 1. 공통 모듈 (`src/common`)
  - 선행: 없음
  - [x] 1.1 `common/s3.py` 신규
    - `ORIGINAL_PREFIX`, `PROCESSED_PREFIX`, `EXT`, `photo_bucket()`, `new_original_key()`, `parse_original_key()`(형식 밖이면 `None`, BE-Q54), `new_processed_key()`(`attemptUuid`, BE-Q57), `quote_etag()`, `presign_put()`(Upload_Descriptor, `ContentType`·`ContentLength` 서명, 스위치가 켜지면 `IfNoneMatch="*"`와 `headers["If-None-Match"]`), `presign_get(key, 900)`.
    - presign 클라이언트는 `PUBLIC_S3_ENDPOINT`가 있으면 그 주소와 경로 방식, 없으면 기본 엔드포인트(가상 호스트 방식), `signature_version="s3v4"`. 스위치는 환경 변수 `PHOTO_UPLOAD_IF_NONE_MATCH == "true"`.
    - _Requirements: 2.2, 2.3, 2.5, 5.4, 7.5, 10.1, 13.3 · BE-REC-02, BE-Q54, BE-Q57, BE-Q65_
  - [x] 1.2 `common/validation.py`: `PhotoIn`(`contentType` 2종, `size` 1–10,485,760 strict 정수), `PhotoRequest = PhotoIn`, `RecordPut.photo: PhotoIn | None`, `_FIELD_MESSAGES`에 `contentType`·`size`.
    - _Requirements: 2.6, 3.5 · BE-Q50_
  - [x] 1.3 `common/metrics.py`: `emf_line(..., unit="Count")`, `emit(..., unit="Count")`, 상수 `PHOTO_PROCESSING_MS`·`PHOTO_FAILED`. 기존 3종 출력 불변.
    - _Requirements: 12.1–12.3 · BE-OBS-01, BE-Q37_
  - [x] 1.4 `common/ddb.py`: `use_table(t)`만 추가. 나머지는 diff 0.
    - _Requirements: 8.8, 9.3 · BE-Q48(미결 유지), BE-Q71_
  - [x] 1.5 공통 모듈 단위 테스트
    - `tests/unit/test_photo_s3.py`(신규): 키 생성·해석(정상, 다른 prefix, `clm_` 아님, uuid 형식 아님, 확장자 3종), `quote_etag`, presign 인자 스파이(`ContentType`, `ContentLength`, `ExpiresIn=600`/`900`, 스위치 꺼짐에 `IfNoneMatch` 없음·켜짐에 있음, `headers`가 각각 `{Content-Type}` / `{Content-Type, If-None-Match}`), 생성 URL의 `X-Amz-SignedHeaders`에 `content-length;content-type;host`(+`if-none-match`), `expiresAt` 밀리초 UTC, 로컬 엔드포인트가 URL 호스트에 들어감.
    - `tests/unit/test_validation.py`: `PhotoIn` 경계(contentType 2종·그 외, size 0·1·10,485,760·10,485,761·`True`·`1.5`·`"10"`), `RecordPut`의 `details` 키 `photo.contentType`·`photo.size`·`photo`, `PhotoRequest`의 `contentType`·`size`·`body`.
    - `tests/unit/test_errors.py`: `emf_line` 단위 지정과 기존 `test_emf_line_format` 불변.
    - **S3 조건부 요청 지원 확인(moto)**: moto 5.2.6에서 `PutObject(IfNoneMatch="*")` 두 번째 412, `GetObject`/`HeadObject(IfMatch=…)` 불일치 412를 확인하는 테스트를 먼저 둔다. 지원하지 않는 조합은 이후 테스트에서 Stubber 주입으로 대신한다는 표시(마커·주석)를 남긴다.
    - _Requirements: 2.3, 2.6, 5.9, 7.5, 12.3, 14.1 · BE-Q50, BE-Q65_

- [x] 2. 이미지 순수 함수 (`domain/photo_image.py`)
  - 선행: 1.3(없어도 되지만 같은 브랜치 순서)
  - [x] 2.1 `photo_image.py` 구현
    - `MAX_BYTES`, `MAX_PIXELS = 40_000_000`, `LONG_EDGE = 1600`, `JPEG_QUALITY = 85`, `PhotoRejected(code)`, `ProcessedImage`, `sniff_format`, `process_image`를 design "`domain/photo_image.py`" 절차 1–8대로 만든다.
    - `DecompressionBombWarning`은 함수 안에서만 오류로 바꾸고 `MAX_IMAGE_PIXELS`는 `try/finally`로 원래 값을 되돌린다. JPEG은 `draft("RGB", (1600, 1600))`. 메타데이터는 픽셀만 새 이미지로 옮겨 없앤다. 투명은 흰 배경 합성.
    - _Requirements: 7.1–7.6, 7.8 · BE-PHOTO-04, BE-PHOTO-05, G7, BE-Q55, BE-Q56, BE-Q58_
  - [x] 2.2 이미지 단위 테스트 (`tests/unit/test_photo_image.py`)
    - 정상 JPEG·PNG(투명 포함)·그레이스케일·팔레트·CMYK, 1600px 초과·이하·정확히 1600, Orientation 1–8 각각의 결과 크기·픽셀 방향(모서리에 색 점을 찍어 회전·반전 확인).
    - 메타데이터: GPS IFD(`0x8825`)·Orientation·ICC(`ImageCms.createProfile("sRGB")`)·XMP·주석이 있는 입력 → 처리본을 Pillow로 다시 열어 `getexif()` 비어 있음, `info`에 `exif`·`icc_profile`·`xmp`·`comment` 없음, JPEG 세그먼트 직접 스캔으로 APP1·APP2·APP13·COM 마커 없음.
    - 거부: 잘린 JPEG·PNG, 헤더만 있는 파일, 0바이트, GIF·WebP·BMP, 확장자만 jpg인 다른 형식, 매직 바이트는 JPEG인데 내용이 PNG, 10,485,761바이트 → 각각 정해진 `PhotoRejected` 코드.
    - 압축 폭탄: 헤더상 픽셀 수가 `MAX_PIXELS` 초과(작은 실제 데이터로 헤더만 크게 만든 PNG) → `TOO_MANY_PIXELS`(디코딩 전), `MAX_PIXELS` 초과 ~ 2배 이하에서 `DecompressionBombWarning` 경로, 2배 초과에서 `DecompressionBombError` 경로가 모두 `TOO_MANY_PIXELS`. `warnings.catch_warnings(record=True)`로 경고가 함수 밖으로 새지 않음, 호출 뒤 `Image.MAX_IMAGE_PIXELS`와 경고 필터가 원래 값.
    - _Requirements: 7.1–7.6, 14.1 · BE-Q55, BE-Q56, T8, T11_
  - [x] 2.3 메모리·시간 측정 (`tests/unit/test_photo_memory.py`, 마커 `slow`)
    - 40,000,000픽셀 이하 최대 크기의 JPEG·PNG를 `subprocess`로 처리해 `ru_maxrss`를 출력하고 717MB(1024MB의 70%) 이하인지 단언한다. 처리 시간도 출력한다(`PRE_PROCESS_MS` 근거, BE-Q71). `pytest.ini`에 `slow` 마커를 등록한다. 기본 실행에서는 빠지지만 Checkpoint 5·16에서는 `-m slow`로 반드시 실행한다.
    - _Requirements: 7.3, 14.1 · BE-Q56, BE-Q71_
  - [x] 2.4 Write property test for 처리본 규칙 (`tests/unit/test_photo_properties.py`)
    - **Property 25: 처리본은 크기·형식 규칙을 지키고 메타데이터가 없다**
    - 생성기: 크기 1×1 ~ 4000×4000, 모드 RGB·RGBA·L·P, Orientation 1–8, GPS EXIF·ICC 유무, 저장 형식 JPEG·PNG.
    - **Validates: Requirements 7.4, 7.5, 7.6**
  - [x] 2.5 Write property test for 거부 사유 (`tests/unit/test_photo_properties.py`)
    - **Property 26: 거부 사유는 입력 결함과 일치하고 예외가 새지 않는다**
    - 생성기: 무작위 바이트, 정상 이미지를 임의 위치에서 자른 것, 매직 바이트 변조, 헤더 픽셀 수 변조.
    - **Validates: Requirements 7.1, 7.2, 7.3**

- [x] 3. 사진 업로드 URL·교체 API (`claim_service`, `handlers/claims.py`)
  - 선행: 1.1, 1.2
  - [x] 3.1 `claim_service.put_record`의 사진 분기
    - `put_record(claim_id, user, letter, now=None) -> record`는 3단계 그대로 두고 `put_record_with_photo(..., photo, now=None) -> (record, upload)`를 더한다(내부 `_write_record` 공유, 3단계 호출부 무변경). 사진이 있으면 Record Update를 `SET …, photoKey = :key, photoStatus = :pending REMOVE processedKey, photoError`로 바꾸고, Transaction 성공·재조회 뒤에만 `presign_put`. 사진이 없으면 3단계 식 그대로, `upload=None`.
    - Plan·Claim ConditionCheck 두 항목 생성은 비공개 헬퍼로 뽑되 식은 그대로 둔다(작업 15에서 diff로 확인).
    - _Requirements: 2.1–2.5, 2.7, 2.9, 2.10, 15.3 · BE-REC-02, BE-REC-03, G3_
  - [x] 3.2 `claim_service.replace_photo` 신규
    - Transaction: Plan CC + Claim CC + Record Update(`attribute_exists(PK) AND attribute_not_exists(deliveredAt)`, `SET photoKey, photoStatus REMOVE processedKey, photoError`). `ConditionFailed`면 재조회: 끝난 이어받기 → 409 `CLAIM_NOT_ACTIVE`(+`StaleRequestRejected`), Record 없음 → 400 `RECORD_REQUIRED`(BE-Q52 권장안), 전달된 Record → 409. 성공 뒤에만 `presign_put`. `letter`·`updatedAt` 불변.
    - `photo_status_update(plan_id, claim_id, *, key, to, allowed_from, error=None) -> bool` 헬퍼(처리 Lambda·복구 스크립트 공용).
    - _Requirements: 3.1–3.6, 15.3 · BE-REC-04, BE-Q52, T15_
  - [x] 3.3 핸들러·라우트
    - `_put_record`: BE-Q34의 `photo` 400 분기를 지우고 `RecordPut`(photo 포함)으로 검증, `{record, upload}`. `_replace_photo`: `PhotoRequest` 검증, 200 `{upload}`(BE-Q51 권장안). 모든 함수 첫 줄 `get_user`.
    - `handlers/routes.py`에 `"POST /claims/{claimId}/record/photo": "handlers.claims.handler"`. 어댑터는 `ROUTES`에서 경로를 만든다.
    - _Requirements: 2.8, 3.2, 3.5 · BE-Q34(해소), BE-Q51, BE-AUTH-04_
  - [x] 3.4 API 단위 테스트 (`tests/unit/test_photo_api.py` 신규, `test_handlers_claims.py`·`test_claim_service_moto.py` 수정)
    - `PUT /record` 사진 성공: 200 `{record, upload}`, `upload` 형태·`expiresAt`, Record `UPLOAD_PENDING`·새 `photoKey`·`processedKey`·`photoError` 없음, 응답 `record`에 `photoKey` 없음. 같은 Claim에 두 번 → 키가 다름.
    - 검증 경계는 DB·presign 호출 없이 400. 끝난 이어받기·전달된 Record·남·없음·`token_use != "id"` → 409·409·403·404·401이고 presign 미호출. Transaction 503 → presign 미호출.
    - 사진 없는 저장 → 사진 속성 불변(`UPLOAD_PENDING`·`PROCESSING`·`FAILED` 각각에서).
    - `POST /record/photo`: 성공 `{upload}` 200, `letter`·`updatedAt` 불변, `processedKey`·`photoError` 제거, `NONE`·`UPLOAD_PENDING`·`PROCESSING`·`FAILED`에서 허용, Record 없음 400 `RECORD_REQUIRED`, Record 없음 + 끝난 이어받기 → 409(순서), 전달됨 409, 남 403, 없음 404.
    - 3단계 기존 사례 수정: `test_record_validation`의 BE-Q34 사례를 새 동작(200 + `upload`)으로 바꾼다. 그 밖의 3단계 사례 기대값은 그대로.
    - _Requirements: 2.1–2.10, 3.1–3.6, 14.1 · BE-Q34, BE-Q50–BE-Q52_
  - [x] 3.5 Write property test for 업로드 URL·교체 (`tests/unit/test_photo_properties.py`)
    - **Property 28: 업로드 URL 발급·교체는 글과 전달 상태를 지킨다**
    - 생성기: 3단계 연산열(이어받기·포기·기록·완료·기한 경과) + 사진 업로드·교체 요청, 임의 요청자.
    - **Validates: Requirements 2, 3**

- [x] 4. 수신함 상세의 사진 (`handlers/inbox.py`, `responses.py`)
  - 선행: 1.1
  - [x] 4.1 `serialize_inbox_record(record, *, photo_url=None, caption=None)`, `_detail`이 `hasPhoto`·`processedKey`가 있으면 `presign_get(processedKey, 900)`와 마지막 장소 + "에서"를 넣는다. `hasPhoto = true`·`processedKey` 없음은 `null` + 경고 로그 `inbox_photo_missing`(BE-Q60). presign은 4단계 소유자 확인 뒤에만.
    - _Requirements: 10.1–10.6 · BE-INBOX-02, BE-Q42(해소), BE-Q60_
  - [x] 4.2 단위 테스트 (`test_handlers_inbox.py`, `test_serialization.py` 수정)
    - 사진 있음 → `photoUrl`(presign 인자 `ExpiresIn=900`, 키 = `processedKey`)·`photoCaption`, 장소 이름 빔 → caption `null`, 사진 없음 → 둘 다 `null`, `hasPhoto`·`processedKey` 불일치 → 둘 다 `null`·로그에 키 없음. 남·없음 404에서 presign 미호출. 4단계 Property 22의 사진 필드 단언을 새 규칙으로 고친다(사진 없는 항목은 여전히 `null`).
    - _Requirements: 10.1–10.6, 14.1_

- [x] 5. Checkpoint - API·이미지 단위 테스트와 회귀
  - `pytest tests/unit`과 `pytest tests/unit -m slow` 실패 0건. 1–4단계 기존 단위 테스트 전체(3단계 Property 12–15, 4단계 묶음 A Property 18–23 포함)가 통과해야 한다.
  - _Requirements: 14.1, 15.3 · G1–G4_

- [x] 6. 사진 처리 Lambda (`workers/photo_processor.py`)
  - 선행: 2.1, 3.2, 5
  - [x] 6.1 초기화·입력 해석·무시 조건
    - 콜드 스타트: `Config(connect_timeout=2, read_timeout=5, retries={"mode": "standard", "total_max_attempts": 2})`(환경 변수로 조정), 그 설정의 S3 클라이언트, `ddb.use_table(...)`.
    - 핸들러: 레코드 순회, JSON 아님·`Records` 없음·`s3:TestEvent` 무시, `unquote_plus`, `parse_original_key`, ClaimLookup·Record `ConsistentRead`, 전달됨·`DISCARDED`·키 불일치 무시, `READY`·미전달 → 경고 `photo_unexpected_ready`·무시(BE-Q66), `HeadObject(IfMatch)` 412·404 → 무시, 403 → 재시도 대상(BE-Q70).
    - _Requirements: 5.1–5.9 · BE-PHOTO-02, BE-PHOTO-03, BE-Q2, BE-Q54, BE-Q66, BE-Q70_
  - [x] 6.2 상태 전이·처리·업로드·완료·정리
    - `PROCESSING` 조건부 전환(실패 → 무시), 크기 초과 `FAILED TOO_LARGE`, `GetObject(IfMatch)`(10MB+1바이트까지만 읽음), `process_image` 거부 → 조건부 `FAILED code`·`PhotoFailed`.
    - 처리본 `PutObject(attempt_key, IfNoneMatch="*")`: 200이면 `created = True`. 412 → 자기 객체 아님, 건드리지 않고 새 키로 1회 다시, 그래도 412면 예외. 타임아웃·연결 오류 → `created = False`로 두고 예외(완료 미호출, 삭제 없음).
    - `complete_claim(WITH_PHOTO)` → `CLAIM_NOT_ACTIVE`·`RECORD_REQUIRED`·`NOT_FOUND`는 판정으로 넘김, `TRY_AGAIN`·SDK 오류는 결과 불확실.
    - 확인 재조회 → `settle` → `delivered`(지표) / `not_delivered`(`created`일 때만 자기 처리본 삭제, 삭제 실패는 로그만) / `uncertain`(삭제 없이 예외). 재조회 실패 → 삭제 없이 예외.
    - _Requirements: 6.1–6.7, 7.1, 7.5, 7.7, 8.1–8.7 · BE-PHOTO-04, BE-PHOTO-06, G2, G4, BE-Q57, BE-Q67_
  - [x] 6.3 재시도·시간 guard·장애 주입
    - 재시도 대상 예외에서 `receive_count >= 3`이면 먼저 조건부 `FAILED RETRY_EXHAUSTED`·`PhotoFailed`, 쓰기 실패여도 원래 예외. guard(`PHOTO_RESERVE_MS` + 단계별 예산, 환경 변수): 부족하면 `TimeBudgetExceeded`, 완료 전 부족이면 `created`인 처리본만 지우고 예외.
    - 주입: `FAULT_INJECT`가 `photo`면 `PROCESSING` 직후 예외, `photo-slow`면 `FAULT_DELAY_S`(1–10, 기본 5)초 대기. 허용은 `FAULT_INJECT_ALLOWED == "true"` **그리고** (`AWS_LAMBDA_FUNCTION_NAME`이 `haru-dev-`로 시작 **또는** 그 변수가 없고 `STAGE == "local"`)일 때만. 아니면 무시하고 콜드 스타트에 `fault_inject_blocked` 1회.
    - 로그는 결과·사유 코드만, EMF `PhotoProcessingMs`(Milliseconds)·`PhotoFailed`(Count).
    - _Requirements: 9.1–9.7, 12.1, 12.2, 12.6 · BE-PHOTO-07, BE-Q59, BE-Q69, BE-Q71, T9_
  - [x] 6.4 처리 Lambda 단위 테스트 (`tests/unit/test_photo_processor.py`, moto S3·DynamoDB)
    - 분기: Requirement 14.1 "핸들러 분기"의 모든 사례. 정상 경로에서 처리본 키가 `photos/processed/{claimId}/{32hex}.jpg`, Record `READY`·`processedKey = 그 키`, InboxItem `hasPhoto = true`.
    - **S3 조건부 요청**: `HeadObject`/`GetObject` ETag 불일치 → 무시·처리본 없음, 원본 없음 404 → 무시, 403 → 예외. 처리본 `PutObject` 412(미리 같은 키에 객체를 넣거나 Stubber) → 그 키를 지우지 않고 새 키 1회, 두 번 412 → 예외·삭제 없음. `PutObject` 타임아웃 → 완료 미호출·삭제 없음·예외.
    - **경합(순차 재현)**: S2 같은 메시지 두 번(두 시도가 완료 직전까지 간 뒤 차례로 완료) → 전달 1회, 이긴 처리본 남음, 진 처리본만 삭제. S3 재업로드(ETag 다른 두 이벤트). S4 처리 중 `TEXT_ONLY` 완료. S5 처리 중 교체. S6 처리 중 포기, 기한 지난 대체(`EXPIRED`). 각 사례에서 InboxItem 1건 이하, Record 상태, 남은 처리본 목록을 단언한다.
    - **결과 불확실(S7)**: `complete_claim`을 감싸 "트랜잭션은 커밋하고 예외를 올리는" 래퍼 → 처리본 보존·예외, 다음 시도는 `delivered`로 무시·처리본 남음. 재조회 실패 → 보존·예외. 재조회 결과 `PROCESSING`·미전달 → 보존·예외. `TRY_AGAIN` → 보존·예외.
    - 재시도·시간·주입: `ApproximateReceiveCount` 1·2 → 예외만, 3 → `FAILED RETRY_EXHAUSTED` 후 예외, `FAILED` 쓰기 실패여도 원래 예외. 가짜 context로 각 guard 지점의 부족 → 예외, 완료 전 부족 → `created` 처리본만 삭제. `FAULT_INJECT=photo`·`photo-slow`(sleep 스파이).
    - 로그: `caplog`로 키·`claimId`·사용자 ID·URL이 없음.
    - _Requirements: 5–9, 12.6, 14.1 · T8, T10, T15의 순차판(판정 대체 아님)_
  - [x] 6.5 중첩 재시도 상한 테스트 (`tests/unit/test_photo_retry_budget.py`)
    - 처리 Lambda 설정의 `Config`가 `standard`·`total_max_attempts=2`·connect 2·read 5인지 확인. Stubber·moto 래퍼로 `TransactionConflict`·`ConditionFailed`·스로틀링을 주입해 `complete_claim` 1회의 API 호출 수가 설계 상한(GetItem 16 + TransactWriteItems 12 = 28회, SDK 시도 포함 56회) 이하이고, 전 반복이 충돌·조건 실패인 최악 경로에서 정확히 GetItem 16·TransactWriteItems 12인지, `transact_with_retry` 대기 합이 1.05초 이하인지 센다. 지연 주입 가짜 클라이언트로 guard가 완료 시작 전에는 멈추고 시작 뒤에는 멈추지 못한다(끝까지 진행한다)는 사실을 고정한다. 결과 호출 수를 출력해 BE-Q71 근거로 남긴다.
    - _Requirements: 9.3 · BE-Q71_
  - [x] 6.6 장애 주입 차단 테스트 (`tests/unit/test_photo_fault_guard.py`)
    - **런타임 검증**: `FAULT_INJECT_ALLOWED`(true/false/없음) × `AWS_LAMBDA_FUNCTION_NAME`(`haru-dev-PhotoProcessorFunction-x` / `haru-demo-…` / 없음) × `STAGE`(local/없음) 조합별 허용 여부, 차단 시 `fault_inject_blocked` 1회, 차단 상태에서 `photo`·`photo-slow`가 아무 효과 없음.
    - **Rules 검증**: 템플릿 `Rules`의 단언 식을 파싱해 (`Stage`, `FaultInject`) 조합 6개에 대해 평가기로 계산한다. `dev`+임의 값은 허용, `demo`+빈 값은 허용, `demo`+`photo`/`photo-slow`는 거부.
    - **Conditions 검증(실제 스택 이름)**: `FaultAllowed` 조건 식을 파싱해 (`Stage`, `AWS::StackName`) 조합(`dev`/`haru-dev`, `dev`/`haru-demo`, `demo`/`haru-dev`, `demo`/`haru-demo`, `dev`/`other`)으로 평가하고, 참일 때만 `FAULT_INJECT`·`FAULT_INJECT_ALLOWED`가 주입 값·`true`로 렌더링되는지 확인한다(`!If` 해석). `dev`/`haru-demo`(Rules 우회 시나리오)에서 거짓이어야 한다.
    - _Requirements: 9.4, 9.5 · BE-Q59_
  - [x] 6.7 Write property test for 전달 1회와 현재 사진 (`tests/unit/test_photo_properties.py`)
    - **Property 27: 사진 전달은 최대 한 번이고 전달된 사진은 그 시점의 현재 사진이다**
    - moto + 상태 기계. 처리 시도를 단계별 제너레이터(무시 판정 → `PROCESSING` → 처리 → 업로드 → 완료 → 확인)로 쪼개고, 메시지 큐를 테스트가 쥔다. 연산: 사진 업로드, 원본 재업로드, 교체, 메시지 전달·중복·지연, 시도 한 단계 진행, 완료 직후 오류 주입, `TEXT_ONLY` 완료, 포기, 기한 경과 + 다른 사용자 이어받기. 끝에 남은 메시지·시도를 모두 진행하고 design의 불변식 5개를 확인한다.
    - **Validates: Requirements 5, 6, 8, 9.7, 14.2**

- [x] 7. 운영자 복구 스크립트 (`backend/scripts/photo_dlq_recover.py`)
  - 선행: 3.2(`photo_status_update`)
  - [x] 7.1 스크립트 구현
    - 기본 dry-run, `--apply`일 때만 조건부 `FAILED RETRY_EXHAUSTED`(조건 `photoKey = :key AND photoStatus = PROCESSING AND attribute_not_exists(deliveredAt)`). DLQ는 `ReceiveMessage(VisibilityTimeout=60)`로 읽기만 하고 `DeleteMessage`·`SendMessage`·`ChangeMessageVisibility`·redrive를 부르지 않는다. 안전 확인 출력(`PhotoQueue` 처리 중 메시지 수, 처리 Lambda 최근 동시 실행). 판정표 5종(design "운영자 복구 절차"), 결과 요약. 출력에 키·사용자 ID·URL 없음(`claimId` 앞 8자만).
    - _Requirements: 9.3 · BE-Q68_
  - [x] 7.2 스크립트 단위 테스트 (`tests/unit/test_photo_dlq_recover.py`, moto SQS·DynamoDB)
    - 판정표 각 줄, dry-run이 테이블·큐를 바꾸지 않음(전후 스냅샷), `--apply`의 조건 실패("그새 바뀜") 처리, 금지 API 미호출(스파이), 처리 중 메시지가 있을 때 경고, 출력에 키·사용자 ID 없음.
    - _Requirements: 9.3, 14.1 · BE-Q68_
  - [x] 7.3 런북 초안 (`backend/README.md`에 넣을 절, 작업 16에서 반영)
  - [x] 7.4 `--apply` 안전 확인 강화(2026-11-26 사용자 요청): 스택 재확인, 매핑 `Disabled`·60초, 처리 중 메시지 0(3회), 실행 종료(지표 지연 300초 뒤, 데이터 없음은 0으로 보지 않음). dry-run의 가시성 변경 명시. `test_photo_dlq_recover.py` 28건
    - "DLQ에 메시지가 있어도 같은 사진을 처리하는 Lambda가 실행 중일 수 있다", `--apply` 전 확인(처리 중 메시지 0, 가시성 180초 경과), SQS 메시지 수는 근사값이므로 필요하면 이벤트 소스 매핑을 끄고(`update-event-source-mapping --no-enabled`) 실행 종료(`ConcurrentExecutions` 0, 새 `START` 로그 없음)를 확인한 뒤 복구하고 다시 켜는 절차, 메시지 삭제·redrive는 운영자가 판정 확인 뒤 수동, 사용자 복구 경로, 필요한 권한.
    - _Requirements: 9.3, 15.4 · BE-Q68_

- [x] 8. Checkpoint - 처리 Lambda·복구 스크립트와 회귀
  - `pytest tests/unit`, `pytest tests/unit -m slow` 실패 0건. Property 25–28 각각 100회 이상 통과. 1–4단계 회귀 전체 통과.
  - _Requirements: 14.1, 14.2 · G1–G4_

- [x] 9. SAM 템플릿 (`template.yaml`, `samconfig.toml`, `layers/pillow`)
  - 선행: 3.3, 6.3, 8
  - [x] 9.1 Parameters·Conditions·Rules
    - `Stage`(dev/demo, 기본 demo), `FaultInject`(""/photo/photo-slow), `UploadIfNoneMatch`("false"/"true", 기본 false). `IsDev`, `FaultAllowed = IsDev ∧ AWS::StackName = haru-dev`, `UseIfNoneMatch`. Rule `FaultInjectOnlyInDev`. `samconfig.toml` dev에 `Stage=dev`, demo에 `Stage=demo`(다른 값은 넣지 않는다).
    - _Requirements: 9.5 · BE-Q59, BE-Q65_
  - [x] 9.2 버킷·정책·큐·DLQ·알람
    - `PhotoQueuePolicy`(문자열 SourceArn, SourceAccount), `PhotoBucket`(`DependsOn: PhotoQueuePolicy`, 이름 고정, 퍼블릭 차단 4개, `BucketOwnerEnforced`, AES256, CORS(`!If UseIfNoneMatch`로 허용 헤더), 수명 주기 원본 7일 + MPU 중단 1일, 알림 prefix `photos/original/`), `PhotoBucketPolicy`(TLS 강제, `UseIfNoneMatch`일 때 `s3:if-none-match` 없는 원본 PUT 거부), `PhotoDLQ`(14일, SSE-SQS), `PhotoQueue`(가시성 180, redrive 3, SSE-SQS), `PhotoDLQNotEmpty`(알림 대상 없음).
    - _Requirements: 1.1–1.6, 4.1–4.6, 12.4, 12.5 · BE-PHOTO-01, BE-PHOTO-08, BE-PHOTO-09, BE-Q49, BE-Q53, BE-Q62, BE-Q65_
  - [x] 9.3 레이어·함수·권한
    - `PillowLayer`(`layers/pillow/requirements.txt`에 `Pillow==13.0.0`, `BuildMethod: python3.12`, x86_64). `PhotoProcessorFunction`(30s·1024MB·x86_64, 이벤트는 `AWS::Lambda::EventSourceMapping` batch 1 — SAM `SQS` 이벤트의 관리형 정책이 Resource `*`라 쓰지 않는다, SQS 권한은 인라인으로 PhotoQueue만, 환경 변수: `PHOTO_BUCKET`, `FAULT_INJECT: !If [FaultAllowed, !Ref FaultInject, ""]`, `FAULT_INJECT_ALLOWED: !If [FaultAllowed, "true", "false"]`, `FAULT_DELAY_S`, SDK·시간 예산 값, 정책 문장 DynamoDB 1 + S3 1). `ClaimsFunction`에 `ReplacePhoto` 이벤트·`s3:PutObject`(original)·환경 변수, `InboxFunction`에 `s3:GetObject`(processed)·환경 변수. 다른 함수는 불변. Outputs 불변.
    - _Requirements: 5.1, 11.1–11.5 · BE-INFRA-06, BE-Q59, BE-Q71_
  - [x] 9.4 템플릿 단위 테스트 (`tests/unit/test_template.py`)
    - 라우트 일치(새 경로 포함), 함수별 정책 Action·Resource 집합 정확 일치(ClaimsFunction·InboxFunction은 기존 DynamoDB 문장 그대로 + S3 문장, PhotoProcessorFunction 신규), `*`·DynamoDB `DeleteItem`·`Scan` 금지, 버킷 속성(이름, 퍼블릭 차단, 소유권, 암호화, CORS의 `!If`, 수명 주기, 알림 prefix, `DependsOn`), 큐 정책 조건, 큐·DLQ 속성, 알람 속성, 레이어 속성, Rules 단언 식, `FaultAllowed`가 `AWS::StackName`을 비교하고 `FAULT_INJECT`·`FAULT_INJECT_ALLOWED`가 `!If FaultAllowed`로 감싸였는지, `test_no_stage3_dependencies`(src/requirements.txt에 Pillow 없음) 유지, samconfig에 `Stage`만 더해졌는지.
    - _Requirements: 11.6, 14.1, 14.9 · BE-Q59_
  - [x] 9.5 검사·빌드
    - `cfn-lint template.yaml` 0건, `sam validate --lint`, `sam build --use-container`(Docker 필요, Pillow 레이어가 Lambda 빌드 이미지에서 빌드). 산출물에서 `PhotoProcessorFunction`·`PillowLayer`의 Pillow가 `cp312`·`x86_64`(manylinux) wheel인지, 다른 함수 산출물에 Pillow·langgraph·langchain이 없는지 확인한다. `sam deploy`는 하지 않는다. Docker를 쓸 수 없으면 사유와 대안(`manylinux2014_x86_64` wheel 다운로드)을 보고하고 묻는다.
    - _Requirements: 14.7 · docs/07 §7.3 5단계 위험_

- [x] 10. Checkpoint - SAM 검증
  - `cfn-lint` 0건, `sam validate --lint` 통과, `sam build --use-container` 성공, `pytest tests/unit/test_template.py` 통과. 미실행 항목이 있으면 사유와 함께 묻는다.
  - _Requirements: 14.7_

- [x] 11. 로컬 환경 (`local/`, `docker-compose.yml`)
  - 선행: 6.3, 10
  - [x] 11.1 init·compose·어댑터
    - `local/init/01_haru.py`: `create_photo_dlq`, `create_photo_queue`, `create_photo_bucket`(CORS, 수명 주기), `put_photo_notification`(멱등, `ok step=`). `tests/unit/test_local_init.py`에 단계 사례 추가.
    - `docker-compose.yml`: `aws`에 `FLOCI_AUTH_VALIDATE_SIGNATURES: "true"`, `api`에 `PHOTO_BUCKET`, `PHOTO_QUEUE_URL`, `PUBLIC_S3_ENDPOINT`, `FAULT_INJECT`, `FAULT_INJECT_ALLOWED: "true"`, `PHOTO_UPLOAD_IF_NONE_MATCH`. 이미지 태그 고정 그대로.
    - 어댑터: SQS 폴러 스레드(`STAGE=local`이고 `PHOTO_QUEUE_URL`이 있을 때만), Lambda SQS 이벤트 형태, 성공 시 삭제·예외 시 남김. `local/adapter/requirements.txt`에 `Pillow==13.0.0`. `tests/unit/test_adapter.py`에 폴러 사례(가짜 SQS 클라이언트: 성공 삭제, 예외 유지, 꺼짐 조건) 추가.
    - _Requirements: 13.1–13.5 · BE-INFRA-08_
  - [x] 11.2 Floci 기능 재확인 (BE-Q64, 실제 구동 결과로 판단)
    - `docker compose up -d --build`로 직접 띄워(서명 검사 켬) 항목별로 확인하고 결과를 기록한다: 버킷 알림(prefix·`s3:TestEvent`·`eTag`), presigned PUT `Content-Length` 서명 검사(403), presigned·SDK `If-None-Match`(412), `IfMatch`(412), SQS redrive(`maxReceiveCount` 3 → DLQ)와 `ApproximateReceiveCount` 증가, 수명 주기 설정 수락, CORS 설정 수락. 서명 검사를 켠 상태에서 기존 로컬 23건이 그대로 도는지.
    - 결과로 "로컬 미지원" 목록을 확정한다. 최소 후보: 수명 주기 실제 만료, 브라우저 CORS preflight·오류 응답 CORS 헤더, 버킷 정책(TLS·`s3:if-none-match` 강제), Lambda 강제 종료·실제 SQS 이벤트 소스 매핑·DLQ 알람. redrive가 안 되면 재시도 소진 분기도 추가한다. 서명 검사로 기존 테스트가 깨지면 끄고 `Content-Length` 사례를 미지원으로 옮긴다.
    - 알림이 동작하지 않는 것으로 바뀌었으면 그때만 로컬 전용 우회(어댑터가 이벤트를 넣음)를 더하고 README에 적는다.
    - _Requirements: 13.6, 13.7 · BE-Q64_
  - [x] 11.3 로컬 통합 테스트 (`tests/local/test_local_photo.py`, 마커 `local`)
    - 정상: 업로드(presigned URL, `localhost:4566`) → 폴러 → 처리 → 완료 → 계획자 상세 `photoUrl`로 처리본을 받아 EXIF·GPS 없음. 손상 파일 → `FAILED CORRUPT_IMAGE` → `TEXT_ONLY` 완료. 처리 전 교체 → 새 사진으로 완료, 처리본 1개. 잘못된 `Content-Length` → 403. 같은 URL 재업로드(스위치 꺼짐) → 전달 1회·처리본 1개. 스위치 켜짐(`PHOTO_UPLOAD_IF_NONE_MATCH=true`일 때만 도는 사례) → 두 번째 PUT 412. `FAULT_INJECT=photo-slow`일 때만 도는 사례: `PROCESSING` 관측 뒤 `TEXT_ONLY` 완료·교체 경합(로컬 확인용, 판정 근거 아님). redrive가 지원되면 `FAULT_INJECT=photo`로 DLQ 이동·`FAILED RETRY_EXHAUSTED`.
    - 상태 확인은 DynamoDB 직접 조회(200ms 간격, 최대 20초). "로컬 미지원" 항목은 사유를 출력하는 skip.
    - _Requirements: 14.3 · BE-Q15, BE-Q64_

- [x] 12. Checkpoint - 로컬 통합 테스트
  - `docker compose up -d --build` 후 `pytest -m local tests/local`: 기존 23건(묶음 A) + 5단계 추가분 전부 통과(조건부 사례는 해당 환경 변수로 한 번씩 다시 기동해 실행). 건수·날짜·기준 커밋·Floci 확인 결과를 기록한다. T 판정 근거는 아니다(BE-Q15).
  - _Requirements: 13.6, 14.3_

- [x] 13. AWS 통합 테스트 작성 (`tests/integration/test_photo.py`, 실행·판정은 AWS 담당)
  - 선행: 9.3, 12
  - [x] 13.1 공통 헬퍼와 정리 확장 (`tests/integration/conftest.py`)
    - 사진 버킷·큐·DLQ·알람 이름을 `DescribeStackResource`로 읽는 헬퍼, presigned PUT 업로드 헬퍼(결과에 URL을 남기지 않음), Record 상태 대기(`ConsistentRead` 폴링), 처리본 목록(Claim prefix).
    - 정리 전 대기 `wait_photo_settled(claim_id)`: 각 사진 테스트가 끝나기 전에 부른다. Record가 전달·`FAILED`·`DISCARDED`이고 30초 동안 Record와 처리본 목록이 바뀌지 않을 때까지 기다린다(최대 5분, 안 되면 `cleanup_after_unsettled` 기록).
    - `_cleanup`: 기존 Cognito·`PLAN#`·`USER#`·ClaimLookup·멱등 키 정리를 그대로 두고, DynamoDB 정리 **뒤에** `created_photo_claim_ids`의 `photos/original/{id}/`·`photos/processed/{id}/` prefix만 `ListObjectsV2`(페이지) → `DeleteObject`. 지연된 Lambda가 정리 뒤 처리본을 만드는 좁은 구간을 위해 prefix 삭제를 30초 뒤 한 번 더 하고 새로 생긴 객체를 `cleanup-late-objects`로 기록한다. 실패는 `cleanup-failures-*.json`(종류 `s3_prefix`). 버킷 전체 삭제·큐 purge 없음. 업로드 전에 `claimId`를 등록한다.
    - `tests/unit/test_integration_cleanup.py`: moto S3로 prefix 정리, 다른 Claim 객체가 남는지, 페이지 이어 읽기, S3 실패 기록과 DynamoDB·Cognito 정리의 독립성, DynamoDB 정리가 S3보다 먼저인 순서, 두 번째 prefix 삭제가 늦게 생긴 객체를 지우고 기록하는지(대기는 주입한 `sleep`), `wait_photo_settled`의 안정 판정과 시간 초과.
    - _Requirements: 14.5, 14.6 · BE-Q38_
  - [x] 13.2 기본 배포 대상 테스트
    - `test_T8_corrupt_image`, `test_T11_gps_stripped`(`exiftool` 있으면 사용, 없으면 Pillow, 도구 이름 기록), `test_T10_text_only_during_processing`, `test_T15_replace_during_processing`(두 원본을 다른 단색으로 만들어 처리본 픽셀로 구분), `test_photo_reupload`, `test_photo_iam_and_cors`(preflight, 오류 응답의 CORS 헤더·오류 코드 기록), `test_photo_fault_blocked`(함수 이름 접두사, 처리된 템플릿의 조건, 읽기 전용).
    - **T10·T15 판정 규칙**: `PROCESSING`을 관측하지 못하면 결과 파일에 `"verdict": "unverified"`와 관측한 상태 열을 남기고 사유 있는 `skip`("PROCESSING 미관측, 미검증, 재시험 필요")으로 끝낸다. `xfail`·통과로 처리하지 않는다. README 판정 실행표에서 미검증은 불합격과 같이 "재시험 필요"로 적는다.
    - _Requirements: 14.5 · T8, T10, T11, T15, BE-Q65, BE-Q70, BE-Q72_
  - [x] 13.3 장애·지연 주입 배포 대상 테스트 (`@pytest.mark.fault`, dev만)
    - `test_T10_T15_with_delay`(`FaultInject=photo-slow`, 최종 판정 근거), `test_T9_dlq`(`FaultInject=photo`: `FAILED RETRY_EXHAUSTED` 대기 최대 10분, DLQ에서 그 키의 메시지 확인, `PhotoDLQNotEmpty` `ALARM` 대기 최대 5분, 그 메시지만 삭제). 테스트 시작 때 함수 환경의 `FAULT_INJECT`가 기대값인지 확인하고 아니면 skip(잘못된 배포에서 판정하지 않음).
    - `pytest.ini`에 `fault` 마커 등록. 기본 실행(`-m integration`)과 분리해 `-m "integration and fault"`로만 돈다.
    - _Requirements: 9.4, 9.5, 14.5 · T9, T10, T15, BE-Q59, BE-Q69_
  - [x] 13.4 수집 확인
    - `pytest -m integration tests/integration --collect-only`, `pytest -m "integration and fault" tests/integration --collect-only` 수집 오류 없음(실행하지 않는다). `pytest tests/unit/test_integration_cleanup.py` 통과.
    - _Requirements: 14.5, 14.6_

- [x] 14. Checkpoint - 전체 회귀
  - `pytest tests/unit`(+`-m slow`) 실패 0건, 1–4단계 회귀 전체 통과(G1–G4 관련 3단계 테스트, 4단계 묶음 A, `test_auth.py`, `test_integration_cleanup.py`), 12번 로컬 결과 유지, 통합 테스트 수집 성공.
  - _Requirements: 14.1, 14.8, 15.3 · G1–G4_

- [x] 15. 변경 범위 확인
  - 선행: 14
  - `git diff feat/be-4-inbox -- backend/src/domain/claim_service.py`에서 `claim_plan`·`abandon`·`complete_claim`·`complete_by_user`·`list_my_claims` 본문 변경 0줄, `put_record`는 Record Update 식의 사진 분기·반환 형태·ConditionCheck 헬퍼 추출뿐(식 동일)인지 확인한다. `common/ddb.py`는 `use_table` 추가뿐. docs/03 diff 0, `frontend/` diff 0. 결과를 PR 본문 초안에 적는다.
  - _Requirements: 15.1–15.3 · G1–G4_

- [x] 16. 인계 문서와 커밋
  - 선행: 15, 7.3
  - [x] 16.1 `backend/README.md`
    - 현황(5단계, 브랜치, 단위·로컬 결과, SAM 결과, AWS 판정 미실행), 배포 전 주의(`sam build --use-container`, 버킷 이름 고정, `Stage` 파라미터, `FaultInject`는 dev만·복원 절차, `UploadIfNoneMatch`는 프론트 승인 전 false), 함수별 IAM 표, 5단계 판정 실행표(T8–T11·T15, 재업로드, IAM/CORS, 주입 차단 검증, T9·지연 주입 절차, 판정 순서, T10·T15 미검증 = 재시험 필요, 회귀 `test_concurrency.py`), 테스트 실행 주체 추가 권한, 운영자 복구 런북(7.3), 알려진 한계(스위치 꺼짐 동안 원본 불변성 미보장, 고아 처리본, 강제 종료, 중첩 재시도), "로컬 미지원" 목록과 Floci 확인 결과(11.2), 지표 해석(`CompleteDuplicate`, BE-Q63), 미결 질문(BE-Q34·BE-Q42 해소, BE-Q49–BE-Q72), 묶음 B 의존·프론트 승인 의존 작업 목록.
    - _Requirements: 15.4, 15.5 · docs/07 §7.8_
  - [x] 16.2 `docs/08-open-questions.md`
    - BE-Q34·BE-Q42 해소로 정리, BE-Q2를 BE-Q66과 함께 정리, BE-Q49–BE-Q72 추가(임시 결정·권장안 그대로, BE-Q51·BE-Q52·BE-Q65는 프론트 리뷰 대상 표시), §8.3 결정 시점 표에 5단계 행. BE-Q45·BE-Q46·BE-Q48은 바꾸지 않는다.
    - _Requirements: 15.7_
  - [x] 16.3 커밋 (push 안 함)
    - spec, 공통·이미지, API, 처리 Lambda·복구 스크립트, 템플릿, 로컬, AWS 테스트, 문서 순서의 의미 단위 커밋. 프론트 트리·docs/03·기존 브랜치 무변경을 확인한다. push·PR은 사용자 확인 뒤(PR base `feat/be-4-inbox`, `f3626c0` 미포함, Requirement 15.6).
    - _Requirements: 15.6_

### 묶음 B 의존 (4단계 `GET /claims/{claimId}/record`가 브랜치에 들어온 뒤)

- [~] 17. `GET /record` 폴링 확인 **[2026-11-27: `feat/be-7-completion`에 묶음 B 구현, 로컬 폴링 사례 4건 통과(`tests/local/test_local_photo.py`). BE-Q46 계약 승인과 AWS 판정은 대기]** (이전 기록: 2026-11-26 보류)
  - 선행: 16, BE-Q46 결정(승인 → 묶음 B 병합, 또는 거부 → 대안 A로 교체된 묶음 B 병합)
  - [ ] 17.1 PR base를 묶음 B가 들어간 브랜치로 옮긴다(rebase 없이 base 변경 또는 병합 커밋, 사용자 확인).
  - [ ] 17.2 로컬 `test_record_polling_view`와 AWS 같은 이름 사례: 업로드 흐름에서 `GET /record`의 `photoStatus`(`UPLOAD_PENDING` → `PROCESSING`/`FAILED`/`READY`)·`delivered`·`claimStatus`를 확인한다. 묶음 B 전에는 이 사례가 `ROUTES`에 경로가 없어 skip(사유 출력)되는지 지금(작업 11.3·13.2)도 확인해 둔다.
  - [ ] 17.3 대안 A로 결정되면 한 응답 안의 필드 시점 불일치 가능성(4단계 design 표 7행)을 사진 폴링 기준으로 README와 프론트 전달 항목에 적는다.
  - [ ] 17.4 S3 연동 지점 전달: 묶음 B와 5단계가 `dev`에 함께 배포된 뒤 프론트가 업로드·폴링·실패·교체를 실제 API로 전환할 수 있다고 알린다(BE-Q65 412 처리 ①의 전제).
  - _Requirements: 14.4 · BE-Q46, S3_

### 프론트 승인 의존 (프론트엔드 담당 리뷰·승인 뒤)

- [ ] 18. 계약 문서 반영과 스위치 켜기 **[대기: 프론트엔드 담당 승인]** (2026-11-26 현재 보류, `UploadIfNoneMatch=false`)
  - 선행: 16, 프론트엔드 담당의 BE-Q51·BE-Q52·BE-Q65 리뷰 결과. 순서는 docs/07 §7.2(docs/03 수정 PR → 승인 → 반영)
  - [ ] 18.1 BE-Q51·BE-Q52 **[승인 대기]**: 승인되면 docs/03 §3.4 `POST /claims/{claimId}/record/photo`에 "200 `{ upload }`", "Record가 없으면 400 `RECORD_REQUIRED`(끝난 이어받기는 409가 먼저)"를 적는다. 거부·변경되면 3.2·3.3·3.4와 design을 함께 고친다.
  - [ ] 18.2 BE-Q65 **[승인 대기]**: 승인되면 docs/03 §3.4 `upload.headers`에 `If-None-Match: *`가 들어갈 수 있음과 업로드 실패 처리(design "presigned PUT의 S3 응답별 처리")를 적는다. `samconfig.toml` dev에 `UploadIfNoneMatch=true`를 더하는 변경은 AWS 담당과 함께 정하고, 켠 배포에서 CORS 허용 헤더·버킷 정책(헤더 없는 PUT 403)·재업로드 412를 AWS 판정 항목으로 추가한다. 프론트 `types.ts`·MSW·업로드 코드는 프론트 담당이 같은 시점에 고친다(이 spec 범위 밖).
  - [ ] 18.3 거부되면 스위치를 끈 상태를 유지하고 "스위치 꺼짐 동안의 한계"를 영구 한계로 README·docs/08에 적는다.
  - _Requirements: 2.3, 3.2, 3.4, 15.1 · BE-Q51, BE-Q52, BE-Q65, docs/07 §7.2_

- [x] 19. 5단계 PR **[사용자 확인 2026-11-26, Draft PR #7]**
  - 선행: 16 (17·18과 독립. 17·18이 끝나기 전이면 그 사실을 PR 본문에 적는다)
  - 결과: https://github.com/creatingweb123/knu-aws-2026/pull/7 (Draft, base `feat/be-4-inbox`). 본문에 작업 17·18 보류, AWS 판정 미실행, `UploadIfNoneMatch=false`를 적었다. Ready for Review 전환·병합은 하지 않는다.
  - PR base `feat/be-4-inbox`, 묶음 B `f3626c0` 미포함. 본문에 요구사항·BE-Q 번호, 단위·로컬 결과, AWS 판정 미실행과 판정 절차, 변경 범위 확인(15), 묶음 B·프론트 승인 대기 항목을 적는다.
  - _Requirements: 15.6_

## Notes

- 속성과 작업: P25 → 2.4, P26 → 2.5, P27 → 6.7, P28 → 3.5. 모두 필수다. 3단계 Property 12–15와 4단계 묶음 A의 Property 18–23은 Checkpoint 5·8·14에서 회귀로 확인한다.
- 이미지 처리(2)는 S3·DynamoDB와 독립이라 다른 그룹과 병행할 수 있다(docs/07 §7.2 "5단계 사진 처리 로직은 단위 테스트까지 먼저").
- 순차 재현(6.4·6.7)은 로직 확인용이다. T8–T11·T15의 판정은 AWS(13.2·13.3)에서만 하며, T10·T15는 지연 주입 실행(13.3)이 최종 근거다. 미검증은 합격이 아니다.
- AWS에서만 판정하는 항목: 실제 SQS 이벤트 소스 매핑·가시성·redrive·DLQ 알람, Lambda 강제 종료·`Duration`, 레이어 import·아키텍처, IAM 최소 권한(`AccessDenied` 없음), 버킷 정책(TLS·조건부 쓰기 강제), 수명 주기 만료, 브라우저 CORS(오류 응답 포함), 장애 주입 차단(Rules·`FaultAllowed`·런타임), 실제 병렬성의 경합.
- 새 테스트 파일: `test_photo_s3.py`, `test_photo_image.py`, `test_photo_memory.py`, `test_photo_api.py`, `test_photo_processor.py`, `test_photo_retry_budget.py`, `test_photo_fault_guard.py`, `test_photo_properties.py`, `test_photo_dlq_recover.py`, `tests/local/test_local_photo.py`, `tests/integration/test_photo.py`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "2.1"] },
    { "id": 1, "tasks": ["1.5", "2.2", "2.3", "2.4", "2.5", "3.1", "4.1"] },
    { "id": 2, "tasks": ["3.2", "4.2"] },
    { "id": 3, "tasks": ["3.3", "7.1"] },
    { "id": 4, "tasks": ["3.4", "3.5", "7.2", "7.3"] },
    { "id": 5, "tasks": ["5"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["6.2"] },
    { "id": 8, "tasks": ["6.3"] },
    { "id": 9, "tasks": ["6.4", "6.5", "6.6", "6.7"] },
    { "id": 10, "tasks": ["8"] },
    { "id": 11, "tasks": ["9.1", "9.2", "9.3"] },
    { "id": 12, "tasks": ["9.4", "9.5"] },
    { "id": 13, "tasks": ["10"] },
    { "id": 14, "tasks": ["11.1"] },
    { "id": 15, "tasks": ["11.2"] },
    { "id": 16, "tasks": ["11.3"] },
    { "id": 17, "tasks": ["12"] },
    { "id": 18, "tasks": ["13.1"] },
    { "id": 19, "tasks": ["13.2", "13.3"] },
    { "id": 20, "tasks": ["13.4"] },
    { "id": 21, "tasks": ["14"] },
    { "id": 22, "tasks": ["15"] },
    { "id": 23, "tasks": ["16.1", "16.2"] },
    { "id": 24, "tasks": ["16.3"] },
    { "id": 25, "tasks": ["17.1", "18.1", "18.2", "19"] },
    { "id": 26, "tasks": ["17.2", "17.3", "18.3"] },
    { "id": 27, "tasks": ["17.4"] }
  ]
}
```
