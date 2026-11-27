# Requirements: frontend-stage3-create-plan

## Introduction

프론트엔드 3단계(docs/07 §7.4 "하루 남기기 (직접 작성 경로 먼저)")를 만든다. 화면 3(사연 입력), 3-2(폼), 3-3(장소 추가), 3-4(공개 완료)가 대상이다. 요구사항은 FE-CRT-01, 05–11, FE-COM-04다. AI 정리(3-1, FE-CRT-02–04, 12–14)는 6단계다.

계약은 docs/03 §3.3 `POST /plans`를 그대로 따른다. 문서에 없는 결정은 docs/08 FE-Q18–FE-Q20을 따른다. 외부 AI 전송 안내의 공급자명·처리 국가·보관 기간은 FE-Q6이 정해질 때까지 비워 둔다.

## Glossary

- **Plan_Draft**: 작성 중 상태. `src/state/planDraft.ts`, sessionStorage `haru.planDraft`.
- **Story_Page** `/plans/new`, **Form_Page** `/plans/new/form`, **Place_Page** `/plans/new/place`, **Published_Page** `/plans/:planId/published`.
- **Content_Hash**: 공개 요청 본문에서 `authoring.durationMs`를 뺀 값의 해시(FE-Q18).

## Requirements

### Requirement 1: 사연 입력 [FE-CRT-01, FE-CRT-05, FE-CRT-09]

#### Acceptance Criteria

1. THE Story_Page SHALL 사연 입력칸(1–1,000자, 글자 수 표시), "집 주소나 개인 정보는 적지 말아주세요" 안내, 외부 AI 전송 안내를 보여 준다. 공급자명·처리 국가·보관 기간은 FE-Q6이 정해지면 채운다.
2. THE Story_Page SHALL "AI와 함께 정리하기"와 "직접 작성하기" 버튼을 둔다. 6단계 전까지 "AI와 함께 정리하기"는 비활성화하고 "AI 정리는 준비 중이에요"를 연결한다.
3. WHEN Story_Page에 처음 들어오면 THE Plan_Draft SHALL `startedAt`을 한 번만 기록한다. 이미 있으면 바꾸지 않는다.
4. THE Story_Page SHALL 입력할 때마다 사연을 Plan_Draft에 저장한다(새로고침 복원).
5. WHEN "직접 작성하기"를 누르면 THE Story_Page SHALL 사연을 검증(앞뒤 공백 제외 1–1,000자)하고, 통과하면 모드를 `MANUAL`로 두고 폼의 `summary`가 비어 있으면 사연 앞부분(120자 이내)으로 채운 뒤 Form_Page로 간다. 실패하면 입력칸에 오류를 보여 준다.

### Requirement 2: 폼 [FE-CRT-06, FE-COM-04]

#### Acceptance Criteria

1. IF Plan_Draft에 사연이 없으면 THE Form_Page·Place_Page SHALL Story_Page로 보낸다.
2. THE Form_Page SHALL 상단에 사연을 참고용으로 보여 주고, 제목(40), 하고 싶었던 일 요약(120), 취소한 이유(300), 예상 소요 시간(분, 10–240 정수), 방문할 장소(1–3곳), 방문 질문(80) 입력칸을 둔다.
3. THE Form_Page SHALL 입력할 때마다 폼 값을 Plan_Draft에 저장한다.
4. THE 방문할 장소 목록 SHALL 장소마다 이름·하고 싶었던 일·고른 이유와 "고치기"·"빼기" 버튼을 보여 주고, 3곳 미만이면 "장소 추가" 버튼으로 Place_Page에 간다(FE-Q20).
5. WHEN "이 하루 공개하기"를 누르면 THE Form_Page SHALL 클라이언트 검증을 하고, 실패하면 요청하지 않고 경로별 오류를 해당 입력칸에 보여 준다. 규칙과 문구는 백엔드 검증(`common/validation.py`)과 같고, 앞뒤 공백을 뺀 값으로 센다(FE-Q19).
6. WHEN 서버가 400 `VALIDATION_ERROR`를 돌려주면 THE Form_Page SHALL `details`의 경로(`places[0].name` 등)별 메시지를 같은 입력칸에 보여 준다. 장소 경로의 오류는 그 장소 항목에 보여 준다.

### Requirement 3: 장소 추가·고치기 [FE-CRT-07, FE-Q20]

#### Acceptance Criteria

1. THE Place_Page SHALL 장소 이름(1–30), 하고 싶었던 일(1–60), 이 장소를 고른 이유(0–120, 선택)를 받는다.
2. WHEN 저장을 누르면 THE Place_Page SHALL 검증하고, 통과하면 장소 목록 끝에 추가(`?index=` 없음)하거나 그 위치의 장소를 바꾼(`?index=n`) 뒤 Form_Page로 돌아간다.
3. IF 이미 3곳인데 추가로 들어오거나 `index`가 범위 밖이면 THE Place_Page SHALL Form_Page로 돌려보낸다.

### Requirement 4: 작성 상태 보관 [FE-CRT-08, FE-CRT-09]

#### Acceptance Criteria

1. THE Plan_Draft SHALL `{ story, sessionId, turn, card, flags, notes, form, mode, startedAt, idempotencyKey, keyBodyHash, keyDurationMs }`를 sessionStorage 한 항목에 저장하고 복원한다. 손상된 값은 버린다.
2. THE Plan_Draft SHALL 하위 경로 이동·새로고침에도 유지되고, 공개에 성공하면 지운다.

### Requirement 5: 공개 [FE-CRT-09, FE-CRT-10, FE-Q18]

#### Acceptance Criteria

1. THE 공개 요청 SHALL `POST /plans` 본문에 폼 값(앞뒤 공백 제거, `places[].order` 없음)과 `authoring { mode, durationMs, story }`를 담는다. `aiSessionId`는 `AI_EDITED`이고 `sessionId`가 있을 때만 넣는다. `durationMs = 공개를 누른 시각 − startedAt`.
2. WHEN 공개를 누르면 THE Form_Page SHALL Content_Hash가 저장된 `keyBodyHash`와 같으면 저장된 `idempotencyKey`와 `keyDurationMs`로 같은 본문을 다시 보내고, 다르면 새 UUID 키와 새 `durationMs`를 만들어 저장한 뒤 보낸다.
3. WHEN 409 `IDEMPOTENCY_CONFLICT`이면 THE Form_Page SHALL 새 키로 같은 본문을 한 번 다시 보낸다. 다시 실패하면 오류 토스트.
4. WHILE 요청 중이면 THE 공개 버튼 SHALL 비활성화된다(FE-NFR-03).
5. WHEN 201이면 THE Form_Page SHALL Plan_Draft를 지우고 목록 캐시를 무효화하고, 응답 `plan`을 라우터 state로 넘겨 Published_Page로 간다(replace).
6. IF 그 밖의 오류이면 THE Form_Page SHALL 공통 문구로 토스트를 띄우고 입력값을 유지한다.

### Requirement 6: 공개 완료 [FE-CRT-11, FE-Q2]

#### Acceptance Criteria

1. THE Published_Page SHALL 체크 아이콘, "하루를 공개했어요", 요약 카드(제목, `약 n분 · 장소 k곳`), "둘러보기로 가기" 버튼을 보여 준다.
2. THE Published_Page SHALL 라우터 state의 `plan`을 쓰고, 없으면(새로고침) `GET /plans/{planId}`로 다시 읽는다.

### Requirement 7: 공개 목업 [FE-TECH-04, docs/03 §3.3]

#### Acceptance Criteria

1. THE `POST /plans` 목업 SHALL 백엔드와 같은 규칙으로 검증하고 400 `VALIDATION_ERROR`의 `details`를 같은 경로·문구로 돌려준다. `Idempotency-Key`가 없으면 `details: { "Idempotency-Key": "필수 헤더예요." }`.
2. THE 목업 SHALL 사용자·키별로 본문 해시와 `planId`를 저장한다. 같은 키·같은 본문이면 처음 만든 Plan을 201로, 다른 본문이면 409 `IDEMPOTENCY_CONFLICT`를 돌려준다.
3. THE 새 Plan SHALL `planId = "pln_" + 고유값`, `status = OPEN`, 소유자 닉네임, `places[].order`(1부터), 소유자용 `metrics { authoringMode, durationMs }`를 가진다. 만든 Plan은 둘러보기 목록 맨 앞에 보인다.

### Requirement 8: 검증

#### Acceptance Criteria

1. THE 테스트 SHALL 검증 규칙(경계값), Plan_Draft 저장·복원·`startedAt` 1회 기록, 공개 본문과 키 재사용 규칙, 목업 `POST /plans`(201, 같은 키 재요청, 409, 400 details), 화면 흐름(사연 → 폼 → 장소 추가 왕복 → 공개 → 공개 완료, 새로고침 뒤 값과 `startedAt` 유지, `IDEMPOTENCY_CONFLICT` 재요청, `VALIDATION_ERROR` 표시)을 확인한다.
2. THE Frontend SHALL `npm run lint`, `npm run test`, `npm run build`, `npm run format:check`를 오류 없이 통과한다.
