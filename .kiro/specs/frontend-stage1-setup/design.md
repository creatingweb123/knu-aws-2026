# Design: frontend-stage1-setup

## Overview

docs/02 §2.10의 프론트엔드 구조를 그대로 만든다. 1단계는 골격이고, 화면 내용은 2–6단계, Cognito는 7단계다.

## 구조

```
frontend/
  index.html, package.json, vite.config.ts, tsconfig*.json, eslint.config.js, .prettierrc, .env.example
  public/mockServiceWorker.js      # msw init으로 생성
  src/
    main.tsx                       # 목업이면 MSW 시작 → React 렌더
    App.tsx                        # QueryClient, ToastProvider, Router
    config.ts                      # VITE_* 읽기
    routes.tsx                     # 경로 표(ROUTES)와 라우터
    api/
      types.ts                     # docs/03 타입
      client.ts                    # request(), ApiError
      errors.ts                    # 공통 문구, details 경로 매핑
      queries/useMe.ts, usePlans.ts
    auth/
      tokens.ts                    # getIdToken(): 목업 사용자 토큰 / (7단계) Amplify
      RequireAuth.tsx
    components/                    # Header, BottomTab, PrimaryButton, StatusBadge, RouteTimeline,
                                   # TextField, TextArea, Toast, ResultScreen, PageTitle, Layout, DevMockBar
    pages/                         # login/ browse/ plan/ me/ record/ inbox/ + NotFound, Placeholder
    state/                         # (3·4단계) planDraft.ts, letterDraft.ts
    mocks/
      browser.ts                   # setupWorker
      db.ts                        # 시드, localStorage 보관, 초기화
      session.ts                   # 목업 사용자·시나리오(FE-Q10, FE-Q11)
      handlers/index.ts, me.ts, plans.ts
    styles/tokens.css, global.css
    utils/date.ts                  # KST 표시
```

## 결정

- **스타일(FE-Q3)**: CSS Modules. 전역은 `global.css`(리셋, 480px 컨테이너)와 `tokens.css`만.
- **목업 사용자(FE-Q10)**: 목업 토큰은 `mock.{userId}` 문자열. Client는 실제 토큰과 같은 방식(`Authorization: Bearer`)으로 붙이고, 핸들러가 토큰에서 사용자를 찾는다. 이렇게 하면 Client에 목업 분기가 없다(FE-TECH-08).
- **목업 데이터 공유**: `db.ts`는 매 요청마다 localStorage에서 읽고 쓴다. 두 탭이 같은 데이터를 보므로 2단계에서 경합을 재현할 수 있다.
- **MSW 범위**: 1단계는 `GET /me`, `GET /plans`, `GET /plans/{planId}`. 상세의 상태 표시 규칙(기한 지난 `CLAIMED` → `OPEN`, `COMPLETED`는 참여자만, `claimable` 공식)은 docs/03 §3.3을 따른다. 나머지 경로는 해당 단계에서 추가한다.
- **401**: Client가 `window.location.assign('/login?redirect=…')`이 아니라 등록된 `onUnauthorized` 콜백을 부른다. 라우터가 `navigate`로 처리하고, 테스트에서는 콜백을 바꿔 확인한다.
- **TRY_AGAIN**: Client 안에서 1회 재시도. 화면은 재시도 뒤 실패만 받는다. `RECORD_REQUIRED`·`IDEMPOTENCY_CONFLICT` 재시도는 각 단계의 mutation에서 한다.
- **비계약 오류 본문**: `INTERNAL_ERROR`(BE-Q23 임시 코드)로 정규화한다. `ErrorCode` 타입에 포함한다.
- **시간**: `utils/date.ts`가 `Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul' })`로 표시한다(FE-COM-06).
- **보호 경로(FE-Q13)**: `RequireAuth`가 `getIdToken()`으로 판단한다. 비목업 모드에서는 1단계에 토큰이 없으므로 `/login`으로 간다.
- **하단 탭(FE-Q12)**: 경로 표의 `tab: true`인 화면만 `Layout`이 `BottomTab`을 그린다.

## 테스트

Vitest + Testing Library(jsdom). MSW는 `msw/node`의 `setupServer`로 같은 핸들러를 쓴다.

| 대상 | 파일 |
|---|---|
| Client | `src/api/client.test.ts` |
| 에러 문구·경로 매핑 | `src/api/errors.test.ts` |
| KST 표시 | `src/utils/date.test.ts` |
| 라우트 17개 렌더링 | `src/routes.test.tsx` |
| Mock_DB·상세 분기 | `src/mocks/handlers/plans.test.ts` |
