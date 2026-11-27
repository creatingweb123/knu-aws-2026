# Requirements: frontend-stage6-ai-card

## Introduction

프론트엔드 6단계(docs/07 §7.4 "AI와 함께 정리하기와 작성 시간 측정")를 만든다. 화면 3(AI 버튼), 3-1(새 화면), 3-2(flags 연결)가 대상이고 요구사항은 FE-CRT-01–04, 09, 12–14, FE-TECH-04다. 계약은 docs/03 §3.2(`SessionView`, `turns` 규칙, 동시 요청·멱등, 에러). 문서에 없는 결정은 docs/08 FE-Q25, "다시 넣기" 값은 FE-Q7(MSW 임시 필드)을 따른다. 실제 API 확인은 백엔드 연동 S4(6a 레벨 0) 이후다.

## Requirements

### Requirement 1: 세션 시작 [FE-CRT-01, FE-CRT-02]

1. THE 사연 입력 SHALL "AI와 함께 정리하기"를 활성화한다. 누르면 사연을 검증(1–1,000자)하고 이전 AI 상태(sessionId·turn·card·flags·notes)를 지운 뒤 3-1로 간다.
2. WHEN 3-1에 들어왔고 `sessionId`가 없으면 THE 3-1 SHALL `POST /ai/card-sessions { story }`를 한 번 보낸다(개발 모드 이중 실행에도 한 번).
3. WHEN `sessionId`가 있고 READY 카드가 없으면 THE 3-1 SHALL `GET /ai/card-sessions/{sessionId}`로 복구한다(새로고침). READY 카드가 있으면 저장된 카드·flags·notes로 READY를 보여 준다.
4. THE 3-1 SHALL 받은 응답마다 `sessionId`와 `turn`을 Plan_Draft에 저장하고, 다음 `turns`의 `expectedTurn`에 마지막 `turn`을 그대로 넣는다. 분기는 `status`로만 한다.
5. AI 요청의 클라이언트 타임아웃은 35초(FE-Q25).

### Requirement 2: 턴 진행 [FE-CRT-13]

`decideAiNextStep(view, consecutiveWorking, finishRequested)`는 다음 행동을 정하는 순수 함수다.

1. `WORKING` → `turns { expectedTurn }` 자동 전송. 연속 `WORKING` 2회부터는 `finish: true`를 넣고, 한 번 넣으면 이후 `WORKING`에도 계속 넣는다. 다른 상태를 받으면 연속 횟수는 0.
2. `ASKING` → 사용자 입력을 기다린다. 다만 `finishRequested`(예약)면 바로 `turns { expectedTurn, finish: true }`.
3. `READY` → 카드 표시. `FAILED` → 실패 처리.
4. 409 `AI_SESSION_BUSY` → 2초 뒤 `GET`. 재동기화 `GET`이 보낸 `expectedTurn`과 같은 `turn`의 `WORKING`이면 2초 간격으로 `GET`을 반복하고(연속 횟수에 넣지 않음), 30초가 지나도 같으면 `turns`를 다시 보낸다.
5. 409 `AI_SESSION_CLOSED` → `GET` 후 그 상태로 분기.
6. `turns`의 네트워크 오류·클라이언트 타임아웃 → `GET`으로 한 번 재동기화하고 그 결과로 분기. `GET`도 실패하면 실패 처리.
7. `VALIDATION_ERROR`(답변 형식) → 토스트 후 `GET`으로 다시 맞춘다.

### Requirement 3: 질문 답하기 [FE-CRT-12, FE-NFR-03]

1. THE 질문 말풍선 SHALL `question.text`와 보조 문구 `question.reason`, `options[]` 버튼, `allowFreeText`일 때만 직접 입력(1–100자, 앞뒤 공백 제외)과 "보내기", "건너뛰기"를 보여 준다.
2. 선택지 → `answer { questionId, choice }`, 직접 입력 → `answer { questionId, text }`, 건너뛰기 → `answer { questionId, skipped: true }`. 요청 중에는 말풍선 버튼을 비활성화한다.
3. "이대로 카드 받기"는 `WORKING`·`ASKING`에서 보인다. 요청이 없을 때 누르면 `turns { expectedTurn, finish: true }`, 요청 중이면 예약만 하고 "카드를 받을게요"(비활성)로 바뀐다(FE-Q25).

### Requirement 4: 단계 칩과 카드 미리보기 [FE-CRT-03]

1. THE 단계 칩 SHALL `trace[]`를 `step` 순서대로 칩 하나씩, `summary`를 문구로 보여 준다. 요청 중이면 끝에 진행 중 칩을 붙인다.
2. THE 카드 미리보기(READY) SHALL 제목, 요약, 취소한 이유, 예상 소요 시간, 장소(이름·하고 싶었던 일·고른 이유), 방문 질문을 보여 주고 `null`은 "비어 있어요"로 보여 준다. `flags`에 `NOT_IN_SOURCE`가 없으면 "원문 대조 통과" 배지를 붙인다("0건 보장" 같은 문구는 쓰지 않는다).
3. THE "AI가 바꾼 것" 메모 SHALL `notes[]`마다 `reason`과 출처 칩(`STORY` → "원문", `ANSWER` → "내 답변")을 보여 준다.
4. "폼에서 다듬기"(주 버튼) → 처음이면 카드를 폼 값으로 넣고(`null`은 빈칸, 분은 문자열) 모드를 `AI_EDITED`로 둔 뒤 폼으로 간다. 다시 누르면 폼 값을 유지한다(FE-Q25).

### Requirement 5: "다시 넣기" [FE-CRT-14, FE-Q7]

1. WHEN 메모가 `REMOVED`이고 `restore`(MSW 임시 필드)가 있으면 THE 메모 SHALL "다시 넣기"를 보여 준다. 누르면 카드 `places` 끝에 `restore.value`를 넣고 그 장소의 `name` 경로에 `restore.type` flag를 붙인다. 한 번 넣으면 "다시 넣었어요"(비활성). 장소가 이미 3곳이면 비활성.
2. 카드를 폼에 넣은 뒤 누르면 폼 `places` 끝에 넣는다(같은 flag).

### Requirement 6: 폼의 flags [FE-CRT-03]

1. THE 폼 SHALL Plan_Draft `flags[].path`와 같은 경로의 입력칸에 안내를 보여 준다: `NOT_IN_SOURCE` "원문에 없던 내용이에요, 확인해 주세요", `MISSING` "직접 채워주세요", `PRIVACY` "공개하기 어려운 정보일 수 있어요". 장소 경로는 그 장소 항목에 보여 준다. 검증 오류가 있으면 오류가 먼저다.
2. 그 경로의 입력을 고치면 해당 flag를 지운다(장소 고치기·빼기는 그 장소 flag를 지우고, 빼면 뒤 장소 인덱스를 당긴다).

### Requirement 7: AI 실패 [FE-CRT-04]

1. WHEN `FAILED`·503 `AI_UNAVAILABLE`·502 `AI_INVALID_OUTPUT`·429 `AI_QUOTA_EXCEEDED`·세션 404·타임아웃·5xx이면 THE 3-1 SHALL 사연을 유지하고 AI 상태를 지운 뒤 모드를 `MANUAL`로, 폼을 빈칸으로 두고 폼으로 간다(replace).
2. THE 폼 SHALL 이 경우 위쪽에 "AI 카드를 만들지 못했어요. 직접 정리해 주세요"를 보여 준다. 공개 요청에는 `aiSessionId`를 넣지 않는다.

### Requirement 8: 공개 [FE-CRT-09]

1. AI 경로로 공개하면 `authoring = { mode: 'AI_EDITED', durationMs, aiSessionId, story }`(3단계 publish.ts 규칙 그대로).

### Requirement 9: MSW AI 세션 [FE-TECH-04, docs/02 §2.10]

1. 공통: 소유자가 아니거나 없는 세션 404, `story` 1–1,000자, `turn ≠ expectedTurn`이면 현재 view 200, `READY`·`FAILED`면 409 `AI_SESSION_CLOSED`, `ASKING`인데 `answer`·`finish` 없으면 400, `answer` 형식(questionId·choice·text·skipped 중 하나) 어기면 400.
2. 시나리오: 없음(레벨 0, 생성 응답 READY), `ai-ask`, `ai-working`, `ai-degraded`, `ai-busy`, `ai-fail`, `ai-fail-turn`, `ai-quota`, `ai-invalid`. 데모 사연 예시(§3.2)를 따른다.

### Requirement 10: 검증

1. THE 테스트 SHALL `decideAiNextStep`, 목업 시나리오 9가지, 3-1 화면 흐름(ai-ask 답변·건너뛰기·이대로 받기, ai-working 자동 finish, ai-busy 재동기화, ai-degraded flags·다시 넣기, 실패 4종 → 직접 작성, 새로고침 복구), 폼 flags 표시·지우기, AI_EDITED 공개 본문을 확인한다.
2. THE Frontend SHALL lint, test, build, format:check를 통과한다.

## 정합성 갱신(2026-11-27, spec backend-frontend-alignment)

- `notes[].restore`는 MSW 목업에서만 온다. 실제 API에는 없으므로 "다시 넣기"는 보이지 않는다. 복원 방식(안 A 적용, 안 B 승인 대기)은 [설계 §4](../backend-frontend-alignment/design.md)를 따른다(FE-Q7·BE-Q13).
