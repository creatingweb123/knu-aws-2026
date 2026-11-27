# Implementation Plan: frontend-stage2-browse-claim

- [x] 1. docs/08에 FE-Q17(2단계 목업 시나리오) 추가
  - _Requirements: 6.4, 6.5_
- [x] 2. 이어받기 목업: `claimPlan()`, `POST /plans/{planId}/claims` 핸들러, `?mock=claim-conflict`·`?mock=browse-empty`
  - _Requirements: 6.1–6.5_
- [x] 3. `utils/plan.ts`, `useClaimPlan`
  - _Requirements: 1.2, 5.1–5.5_
- [x] 4. 둘러보기: `PlanCard`, `BrowsePage` 카드·빈 상태·오류
  - _Requirements: 1.1–1.6, 2.1–2.2_
- [x] 5. 상세: `decideDetailView`, `ClaimedNotice`, `PlanDetailPage`, 라우트 연결
  - _Requirements: 3.1–3.4, 4.1–4.8, 5.1–5.6_
- [x] 6. 테스트와 검증: lint, test(8파일 94건), build, format:check
  - _Requirements: 7.1–7.3_
  - 7.3(두 브라우저 탭 실제 확인)은 같은 DB에 두 사용자가 차례로 요청하는 테스트로 대신했다. 실제 브라우저 확인은 개발 담당이 한다(frontend/README.md 절차).
- [x] 7. push `feat/fe-2-browse-claim`

## 구현 중 바뀐 것

- "취소된 하루 남기기"를 하단 고정 버튼이 아니라 제목 아래 보조 버튼으로 두었다. 둘러보기는 하단 탭이 있는 화면이라 고정 버튼이 탭과 겹친다(요구사항 2.2 수정).
- 상세는 `PlanDetailPage`가 `key={planId}`로 내부 컴포넌트를 다시 만든다. 다른 하루로 옮겨도 이전 하루의 `ALREADY_CLAIMED` 상태가 남지 않는다.
- 테스트용 `src/test/renderApp.tsx`(앱 라우트 + 목업 사용자)를 추가했다. 1단계의 `plan-count` 표시는 카드 목록으로 바뀌어 라우트 테스트를 고쳤다.
