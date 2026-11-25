# Implementation Plan: frontend-stage3-create-plan

- [x] 1. docs/08에 FE-Q18–FE-Q20 추가, `useClaimPlan` → `api/mutations/useClaim.ts`
- [x] 2. `utils/validation.ts`, `utils/hash.ts`, `utils/uuid.ts`
  - _Requirements: 2.5, 3.1, 5.2_
- [x] 3. `state/planDraft.ts`
  - _Requirements: 1.3, 1.4, 4.1, 4.2_
- [x] 4. 목업 `POST /plans`(검증·멱등), db 버전 2
  - _Requirements: 7.1–7.3_
- [x] 5. `publish.ts`, `useCreatePlan`
  - _Requirements: 5.1–5.3_
- [x] 6. 화면 3·3-2·3-3·3-4, 라우트 연결
  - _Requirements: 1, 2, 3, 5.4–5.6, 6_
- [x] 7. 테스트와 검증: lint, test, build, format:check
  - _Requirements: 8.1, 8.2_
- [x] 8. push `feat/fe-3-create-plan`

## 구현 중 바뀐 것

- 목업 `POST /plans`는 `Idempotency-Key` 누락과 본문 검증 오류를 합쳐 한 번에 돌려준다. 백엔드 `handlers/plans.py`의 `_create`가 그렇게 한다(설계의 "키 없음 먼저"를 고쳤다).
- `usePlanDraft().update`는 sessionStorage에 바로 쓴다. React 상태 갱신 함수 안에서 쓰면 `update` 직후 `navigate`할 때 다음 화면이 이전 값을 읽을 수 있다.
- 사연 입력 화면에서 "AI 정리는 준비 중이에요" 안내는 외부 AI 전송 안내 박스 안에 두었다(6단계에서 지운다).
- 테스트 파일을 병렬로 돌리면 이 PC에서 첫 렌더가 1초를 넘겨 `findBy`가 실패할 때가 있어, `asyncUtilTimeout`을 5초, Vitest `testTimeout`을 30초로 늘렸다(`src/test/setup.ts`, `vite.config.ts`).
- `usePlan`에 `enabled` 옵션을 추가했다(공개 완료 화면이 라우터 state가 있으면 다시 읽지 않게).
