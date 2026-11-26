# Requirements: frontend-stage5-photo

## Introduction

프론트엔드 5단계(docs/07 §7.4 "사진 업로드·폴링·실패·교체")를 만든다. 화면 5(사진 선택), 5-1(보내는 중), 5-2(사진 처리 실패), 5-3(사진 교체), 5-4(사진 포함 완료 문구), 7(사진·캡션)이 대상이고 요구사항은 FE-REC-03, 04, 06–10, FE-INB-03, 04다. 계약은 docs/03 §3.4·§3.5. 문서에 없는 결정은 docs/08 FE-Q23·FE-Q24를 따른다. 실제 S3 업로드 확인은 백엔드 연동 S3 이후 `dev` 스택에서 한다.

## Requirements

### Requirement 1: 사진 선택 [FE-REC-03]

1. THE 작성 화면 SHALL 사진 1장(선택)을 고르는 입력을 두고, JPEG·PNG가 아니거나 10MB를 넘거나 0바이트면 "JPEG 또는 PNG, 10MB 이하 사진을 골라 주세요."를 보여 주고 선택하지 않는다.
2. THE 작성 화면 SHALL 고른 사진의 미리보기와 "사진 빼기"를 보여 준다(미리보기 URL은 바꾸거나 떠날 때 해제한다).
3. WHILE 사진이 있으면 THE 작성 화면 SHALL 주 버튼 "사진과 방문 기록 보내기"와 보조 버튼 "사진 없이 글로 완료"를, 없으면 "글로 완료하기"를 보여 준다.

### Requirement 2: 사진과 함께 보내기 [FE-REC-04, FE-Q23]

1. WHEN "사진과 방문 기록 보내기"를 누르면 THE 화면 SHALL 글을 검증하고 `PUT /record { letter, photo: { contentType, size } }`를 보낸 뒤 응답 `upload`로 `fetch(upload.url, { method: upload.method, headers: upload.headers, body: file })`를 보낸다. URL·헤더는 바꾸지 않고 파일을 변환하지 않는다. 업로드 요청에는 `Authorization`을 붙이지 않는다.
2. THE 화면 SHALL 업로드를 시작할 때 `haru.sending.{claimId}`에 `{ startedAt }`을 저장하고, 업로드가 실패하면(네트워크 오류·2xx 아님) `uploadFailed = true`로 바꾼다. 어느 쪽이든 보내는 중(`/claims/{claimId}/sending`, replace)으로 간다.
3. IF `PUT /record`가 409 `CLAIM_NOT_ACTIVE`이면 화면 8, `VALIDATION_ERROR`이면 `details.letter`·`details.photo`를 해당 입력에, 그 밖은 토스트.
4. 요청 중에는 두 버튼을 비활성화한다. presigned URL은 로그·오류 문구에 남기지 않는다(FE-NFR-05).

### Requirement 3: 보내는 중과 판정 [FE-REC-06, FE-REC-07, FE-Q23]

`decideSendingState({ data, error }, elapsedMs, uploadFailed)`는 위에서부터 먼저 맞는 하나를 고른다.

1. `data.delivered` → 완료(`hasPhoto = photoStatus === 'READY'`)
2. `claimStatus`가 `ABANDONED`·`EXPIRED`, 또는 오류가 403·404·409 → 종료(화면 8)
3. `photoStatus === 'FAILED'`, 또는 `uploadFailed`, 또는 `UPLOAD_PENDING`이고 `elapsedMs > 30초`, 또는 `NONE`·`DISCARDED` → 실패(5-2)
4. 그 외 → 대기(`emphasize = elapsedMs >= 60초`). 데이터 없이 다른 오류(네트워크 등)이면 대기를 유지한다.

- THE 보내는 중 SHALL `GET /record`를 2초 간격으로 폴링하고, 기준 시각은 `haru.sending.{claimId}.startedAt`, 없으면 `record.updatedAt`이다.
- 대기 화면(5-1): 진행 표시, "보내는 중이에요", "글로 완료하기". 강조면 "사진 처리가 늦어지고 있어요. 글로 먼저 완료할 수 있어요."와 함께 주 버튼으로 바꾼다.
- 완료 → 임시 글·`haru.sending` 삭제, 전송 완료(5-4)로 replace(`hasPhoto` state).
- 종료 → 화면 8(서버 글 또는 임시 글).

### Requirement 4: 실패와 교체 [FE-REC-05, FE-REC-08, FE-REC-09]

1. THE 실패 화면(5-2) SHALL "사진을 보내지 못했어요", "작성한 글은 저장되어 있어요."와 "사진 바꾸기"(→ 5-3)·"글로 완료하기"를 보여 준다.
2. "글로 완료하기"(5-1·5-2·5-3) SHALL 서버에 저장된 글(`record.letter`, 없으면 임시 글)로 `PUT /record { letter }` → `complete(TEXT_ONLY)`를 보내고(4단계와 같은 재시도), 응답 `hasPhoto`로 5-4 문구를 정한다. 글이 없으면 작성 화면으로 보낸다. `CLAIM_NOT_ACTIVE`면 화면 8.
3. THE 사진 교체(5-3) SHALL 사진 선택(1과 같은 검사, 미리보기)과 "이 사진으로 보내기"·"글로 완료하기"를 둔다. 보내기는 `POST /record/photo { contentType, size }` → 업로드 → 2.2와 같이 보내는 중으로 간다.

### Requirement 5: 돌아온 하루의 사진 [FE-INB-03, FE-INB-04]

1. THE 돌아온 하루 SHALL `photoUrl`이 있으면 사진과 `photoCaption`을 보여 주고, 사진 로드가 실패하면 상세를 한 번 다시 읽는다(4단계에 구현, 이 단계에서 목업 사진으로 확인).

### Requirement 6: 목업 [FE-Q24]

1. `PUT /record`의 `photo`: `image/jpeg`·`image/png`, `size` 1–10,485,760 정수가 아니면 400 `VALIDATION_ERROR { photo }`. 통과하면 `photoKey = photos/original/{claimId}/{uuid}.{jpg|png}`, `UPLOAD_PENDING`, `upload = { url, method: 'PUT', headers: { 'Content-Type' }, expiresAt: 지금+10분 }`.
2. `POST /record/photo`: 쓰기 조건은 `PUT /record`와 같고, 기록이 없으면 400 `RECORD_REQUIRED`. 새 키로 교체하고 `UPLOAD_PENDING`.
3. 업로드 PUT: URL 경로의 키가 현재 `photoKey`이고 `UPLOAD_PENDING`일 때만 `PROCESSING`(처리 끝 시각 = 지금 + 지연). 다른 키(교체 전)는 무시한다. `Content-Type`이 서명과 다르면 403.
4. 처리는 조회·쓰기 때 시각으로 계산한다. 끝나면 `?mock=photo-fail`이면 `FAILED`, 아니면 Claim이 쓰기 가능할 때 사진 포함 완료(Record `READY`·`deliveredAt`, Plan·Claim `COMPLETED`, InboxItem `hasPhoto = true`), 쓰기 불가면 무시.
5. 글로 완료(TEXT_ONLY)는 사진이 `UPLOAD_PENDING`·`PROCESSING`·`FAILED`·`READY`(미전달)면 `DISCARDED`로 둔다. 이미 사진과 함께 완료됐으면 멱등 200 `hasPhoto: true`.
6. 수신함 상세 `photoUrl`은 `hasPhoto`이면 고정 그림(data URL).

### Requirement 7: 검증

1. THE 테스트 SHALL 사진 검사, `decideSendingState` 전 분기(30초·60초 경계 포함), 목업(업로드 URL·처리·실패·교체 후 이전 키 무시·TEXT_ONLY 폐기·검증), 화면 흐름(사진 보내기 → 5-1 → 5-4 사진 문구, `photo-fail` → 5-2 → 글로 완료, 5-2 → 교체 → 완료, 업로드 실패 → 5-2, 돌아온 하루 사진·캡션)을 확인한다.
2. THE Frontend SHALL lint, test, build, format:check를 통과한다.
