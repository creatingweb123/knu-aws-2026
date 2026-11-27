# Requirements: frontend-stage4-record-inbox

## Introduction

프론트엔드 4단계(docs/07 §7.4 "내 하루 → 방문 기록(글만) → 수신함 → 답장")를 만든다. 화면 4, 4-1, 5(글만), 5-4, 6, 7, 7-1, 8이 대상이고 요구사항은 FE-ME-01–04, FE-REC-01–03(사진 제외)·05·10·11, FE-INB-01–05, FE-COM-02·06이다. 사진 업로드·폴링·실패·교체(5-1, 5-2, 5-3, FE-REC-03 사진·04·06–09)는 5단계다.

이 단계가 끝나면 글 경로 기준으로 시연 시나리오 전체(지연 공개 → 수현 이어받기 → 방문 기록 → 지연 수신함 → 답장)가 MSW 목업에서 동작한다. 계약은 docs/03 §3.1, §3.4, §3.5를 따른다. 문서에 없는 결정은 docs/08 FE-Q19(확장), FE-Q21–FE-Q22를 따른다.

## Requirements

### Requirement 1: 내 하루 [FE-ME-01–03, FE-COM-06, FE-Q21]

1. THE 내 하루 SHALL `GET /me/claims?status=ACTIVE`의 항목을 응답 순서(이어받은 시각 최신순)대로 모두 카드로 보여 준다(FE-Q21).
2. THE 카드 SHALL 제목, `{계획자} · 약 n분 · 장소 k곳`, 기한 문구, 동선 타임라인, "다녀온 이야기 쓰기", "이어받기 포기"를 보여 준다.
3. THE 기한 문구 SHALL `dueAt`이 지금보다 뒤면 "{M}월 {D}일까지 다녀온 이야기를 보내주세요."(KST), 지났으면 "기한이 지났어요. 다른 사람이 이어받기 전까지는 보낼 수 있어요."다.
4. WHEN "다녀온 이야기 쓰기"를 누르면 THE 내 하루 SHALL `record.photoStatus`가 `UPLOAD_PENDING`·`PROCESSING`·`FAILED`이면 `/claims/{claimId}/sending`, 그 외(기록 없음, `NONE`, 문서에 없는 `READY`·`DISCARDED` 포함, FE-Q22)는 `/claims/{claimId}/record`로 간다.
5. WHEN 항목이 없으면 THE 내 하루 SHALL "아직 이어받은 하루가 없어요"와 "하루 둘러보기" 버튼을 보여 준다.

### Requirement 2: 이어받기 포기 [FE-ME-04]

1. THE 포기 확인(4-1) SHALL 하루 제목(알 수 있으면), "포기하면 이 하루는 다시 공개돼요" 안내, "계속 이어가기"·"이어받기 포기" 버튼을 보여 준다.
2. WHEN "이어받기 포기"를 누르면 THE 화면 SHALL `POST /claims/{claimId}/abandon`을 보내고(요청 중 비활성), 성공하면 목록·내 하루 캐시를 무효화하고 그 하루의 임시 글을 지운 뒤 둘러보기로 간다.
3. WHEN 409 `CLAIM_NOT_ACTIVE`이면 THE 화면 SHALL "이미 종료된 이어받기예요" 토스트 후 내 하루 캐시를 다시 읽고 내 하루로 간다. 403·404는 공통 문구 토스트 후 둘러보기로 간다.
4. WHEN "계속 이어가기"를 누르면 THE 화면 SHALL 내 하루로 간다.

### Requirement 3: 방문 기록 작성(글) [FE-REC-01–03, FE-REC-05, FE-Q19]

1. THE 작성 화면(5) SHALL 계획 제목, "{계획자 닉네임}에게", 방문 질문, 글 입력칸(1–1,000자)을 보여 준다. 계획 정보는 `GET /me/claims?status=ACTIVE`에서 찾는다.
2. WHEN 진입하면 THE 작성 화면 SHALL `GET /claims/{claimId}/record`의 `record.letter`를 먼저 채우고, 없을 때만 localStorage `haru.letterDraft.{claimId}`를 쓴다. 입력할 때마다 임시 글을 저장한다.
3. IF `GET /record`의 `delivered`가 참이면 THE 작성 화면 SHALL 전송 완료로 간다(replace). `claimStatus`가 `ABANDONED`·`EXPIRED`이면 화면 8을 보여 준다. 403·404이면 공통 문구와 "둘러보기로 가기"를 보여 준다.
4. WHEN "글로 완료하기"를 누르면 THE 작성 화면 SHALL 글을 검증(앞뒤 공백 제외 1–1,000자)하고 `PUT /record { letter }` → `POST /complete { mode: 'TEXT_ONLY' }`를 보낸다. 요청 중에는 버튼을 비활성화한다.
5. WHEN `complete`가 400 `RECORD_REQUIRED`이면 THE 흐름 SHALL `PUT /record` 후 `complete`를 한 번 다시 보낸다. 네트워크 오류도 `complete`를 한 번 다시 보낸다(`TRY_AGAIN` 1회 재시도는 Client).
6. WHEN 완료되면 THE 흐름 SHALL 임시 글을 지우고 내 하루·수신함 관련 캐시를 무효화하고, 응답 `hasPhoto`를 라우터 state로 넘겨 전송 완료(5-4)로 간다(replace).
7. IF `PUT /record`·`complete`가 409 `CLAIM_NOT_ACTIVE`이면 THE 작성 화면 SHALL 화면 8을 보여 준다. `VALIDATION_ERROR`는 `details.letter`를 입력칸에, 그 밖의 오류는 토스트로 보여 주고 글을 유지한다.

### Requirement 4: 전송 완료와 종료 안내 [FE-REC-10, FE-REC-11]

1. THE 전송 완료(5-4) SHALL 라우터 state의 `hasPhoto`로, 없으면(새로고침) `GET /record`의 `delivered && photoStatus === 'READY'`로 문구를 정한다: 사진 있음 "사진과 방문 기록을 보냈어요", 없음 "방문 기록을 보냈어요". 버튼은 "둘러보기로 돌아가기".
2. IF 새로고침 후 `GET /record`가 `delivered = false`이면 THE 전송 완료 SHALL 작성 화면으로 보낸다(replace).
3. THE 종료 안내(8) SHALL "이 이어받기는 종료되었어요", 작성한 글(있으면)과 "글 복사하기", "다른 하루 둘러보기"를 보여 주고, 보여 줄 때 임시 글을 지운다. `photoStatus = DISCARDED`는 종료 판단에 쓰지 않는다.

### Requirement 5: 수신함 [FE-INB-01, FE-COM-02]

1. THE 수신함(6) SHALL `GET /inbox` 항목을 응답 순서(최신순)대로 보여 준다. `read === false`면 "새 편지" 배지와 주황 점, 아니면 "읽은 기록" 배지.
2. THE 항목 SHALL 하루 제목, "{실행자}님이 사진과 방문 기록을 보냈어요"(`hasPhoto`) 또는 "{실행자}님이 방문 기록을 보냈어요", 도착 시각(KST)을 보여 주고 `/inbox/{itemId}`로 연결한다.
3. WHEN 항목이 없으면 THE 수신함 SHALL "아직 돌아온 하루가 없어요"를 보여 준다.

### Requirement 6: 돌아온 하루와 답장 [FE-INB-02–05]

1. WHEN 상세를 불러왔고 `item.read === false`이면 THE 상세(7) SHALL `POST /inbox/{itemId}/read`를 한 번 보내고 수신함 목록과 `GET /me`를 무효화한다.
2. THE 상세 SHALL 사진(`photoUrl`이 있으면)과 `photoCaption`, "내가 남긴 계획"(베이지, `plan.title`·`plan.summary`) / "{실행자}의 방문 기록"(연녹색, `record.letter`) 카드를 보여 준다. 사진 로드가 실패하면 상세를 한 번 다시 읽는다.
3. WHILE `item.reply`가 없으면 THE 상세 SHALL 한 줄 답장 입력(1–100자, 앞뒤 공백 제외)과 "답장 보내기"를 보여 준다. 요청 중 비활성.
4. WHEN 답장이 201이거나 409 `REPLY_ALREADY_SENT`이면 THE 상세 SHALL "보낸 답장" 읽기 전용(7-1)과 "수신함으로" 버튼으로 바꾼다(409면 상세를 다시 읽어 실제 답장을 보여 준다). 처음부터 `reply`가 있으면 7-1로 보여 준다.
5. IF 상세가 404이면 THE 상세 SHALL "찾을 수 없어요"와 "수신함으로" 버튼을 보여 준다.

### Requirement 7: 목업 [FE-TECH-04, docs/03 §3.1, §3.4, §3.5]

1. `GET /me/claims?status=ACTIVE|COMPLETED`: 요청자의 Claim 중 그 상태만, `claimedAt` 최신순, `{ claim, plan, record|null }`. 다른 값은 400 `VALIDATION_ERROR { status }`.
2. `POST /claims/{claimId}/abandon`·`PUT /record`·`GET /record`·`POST /complete`: 없는 Claim 404, 남의 Claim 403(백엔드 `_lookup`). 쓰기는 Claim `ACTIVE`이고 Plan `CLAIMED`·`currentClaimId = claimId`일 때만, 아니면 409 `CLAIM_NOT_ACTIVE`.
3. 포기: Claim `ABANDONED`, Plan `OPEN`(currentClaimId·claimerId·dueAt 제거), Record가 있으면 `photoStatus = DISCARDED`.
4. `PUT /record`: `letter` 1–1,000자 검증, 전달된 기록이면 409, `photoStatus`는 없으면 `NONE`. 4단계 목업은 `photo`를 받지 않는다(400, 5단계에서 추가). 응답 `upload: null`.
5. `complete`: `mode`는 `TEXT_ONLY`만. 이미 `COMPLETED`면 200 멱등(`hasPhoto = photoStatus === 'READY'`). 기록이 없으면 400 `RECORD_REQUIRED`. 완료하면 Plan `COMPLETED`, Claim `COMPLETED`(`late = 지금 > dueAt`), Record `deliveredAt`, InboxItem 1건(`itemId = claimId`, 계획자 소유, 안 읽음).
6. 수신함: 목록은 요청자 것만 `createdAt` 최신순. 상세·읽음·답장은 요청자 것이 아니면 404. 답장 1–100자, 이미 있으면 409 `REPLY_ALREADY_SENT`, 201 `{ reply }`. `photoCaption`은 사진이 있으면 마지막 장소 이름 + "에서".

### Requirement 8: 검증

1. THE 테스트 SHALL 목업 판정(포기·기록·완료 멱등·RECORD_REQUIRED·CLAIM_NOT_ACTIVE·수신함·답장), 기한 문구, 화면 흐름(내 하루 → 작성 → 글로 완료 → 5-4, 임시 글 복원, 포기, 종료 안내, 수신함 → 상세 읽음 → 답장 → 7-1), 시연 시나리오 전체(지연 공개 → 수현 이어받기 → 완료 → 지연 수신함·답장)를 확인한다.
2. THE Frontend SHALL lint, test, build, format:check를 통과한다.
