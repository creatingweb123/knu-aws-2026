# Implementation Plan: frontend-stage6-ai-card

- [x] 1. docs/08 FE-Q25, FE-Q7 임시 필드
- [x] 2. MSW AI 세션(`ai.ts`, db 버전 3)
  - _Requirements: 9_
- [x] 3. `api/ai.ts`, `decideAiNextStep`, `useAiSession`, `cardForm.ts`, Plan_Draft 필드
  - _Requirements: 1, 2, 5, 6_
- [x] 4. 화면 3-1, 사연 입력 AI 버튼, 폼 flags·실패 안내
  - _Requirements: 1, 3, 4, 5, 6, 7, 8_
- [x] 5. 테스트와 검증: lint, tsc, test(24파일 236건), build, format:check
  - _Requirements: 10_
- [x] 6. push `feat/fe-6-ai-card`

## 구현 중 바뀐 것

- 3단계 테스트 "AI 버튼은 6단계 전까지 비활성"을 활성 확인으로 바꿨다. 사연 입력의 "AI 정리는 준비 중이에요" 문구를 지웠다.
- "직접 작성하기"도 이전 AI 상태(sessionId·카드·flags)를 지운다. AI 뒤 직접 작성으로 바꾸면 `aiSessionId`와 AI 안내가 남지 않게 하려는 것이다.
- READY 카드는 처음 받을 때만 Plan_Draft에 저장한다. "다시 넣기"로 바꾼 카드를 재동기화 응답이 덮지 않게 하려는 것이다.
- 테스트 setup에서 매 테스트 뒤 `server.events` 리스너를 지운다(요청 본문을 모으는 테스트가 실패해도 다음 테스트에 남지 않게).
- `ai-busy` 흐름 테스트는 실제 2초 대기를 두 번 거치므로 테스트 제한을 60초로 두었다.
