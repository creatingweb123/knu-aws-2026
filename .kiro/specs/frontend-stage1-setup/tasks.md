# Implementation Plan: frontend-stage1-setup

- [x] 1. 프로젝트 세팅: Vite + React 18 + TS, React Router, TanStack Query, ESLint/Prettier, Vitest, `.env.example`, `config.ts`
  - _Requirements: 1.1–1.5_
- [x] 2. 스타일: `tokens.css`, `global.css`, 480px 레이아웃
  - _Requirements: 2.1–2.4_
- [x] 3. API: `types.ts`, `client.ts`, `errors.ts`, `useMe`·`usePlans`
  - _Requirements: 4.1–4.9_
- [x] 4. 인증 골격: `auth/tokens.ts`, `RequireAuth`
  - _Requirements: 6.1–6.4_
- [x] 5. MSW: `db.ts`, `session.ts`, 핸들러(`/me`, `/plans`, `/plans/{planId}`), `browser.ts`, `DevMockBar`
  - _Requirements: 5.1–5.7_
- [x] 6. 공통 컴포넌트: Header, BottomTab, PrimaryButton, StatusBadge, RouteTimeline, TextField, TextArea, Toast, ResultScreen, PageTitle, Layout
  - _Requirements: 3.1–3.10_
- [x] 7. 라우트 골격과 빈 페이지 17개
  - _Requirements: 7.1–7.3_
- [x] 8. 테스트와 검증: `npm run lint`, `npm run test`, `npm run build`
  - _Requirements: 8.2, 8.3_
  - 8.1(`npm run dev`로 브라우저에서 탭 이동 확인)은 라우트 테스트(`routes.test.tsx`)로 대신했다. 실제 브라우저 확인은 개발 담당이 한다.
- [x] 9. `frontend/README.md`, push `feat/fe-1-setup`

## 구현 중 바뀐 것

- `TextArea`는 `TextField.tsx`에 함께 구현하고 `TextArea.tsx`에서 다시 내보낸다(라벨·글자 수·에러 공유).
- 목업 사용자 선택을 localStorage에서 탭별 sessionStorage로 바꿨다. 탭끼리 같은 localStorage를 공유하면 탭 A 수현·탭 B 민준을 유지할 수 없어 2단계 경합 재현이 안 된다(요구사항 5.6, docs/08 FE-Q10 갱신).
- `useToast`는 fast refresh 규칙 때문에 `components/useToast.ts`로, `createQueryClient`는 `queryClient.ts`로 분리했다.
