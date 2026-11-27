# Requirements: frontend-stage1-setup

## Introduction

프론트엔드 1단계(docs/07 §7.4 "프로젝트 세팅과 공통 레이아웃")를 `frontend/`에 만든다. 백엔드 연동 지점은 S0(계약 확정)만 필요하고, 모든 동작은 MSW 목업(`VITE_USE_MOCK=true`)으로 확인한다. 실제 로그인(FE-AUTH-*)은 7단계, 각 화면의 내용은 2–6단계다.

문서에 없는 결정은 docs/08 §8.2의 FE-Q10–FE-Q16 임시 결정을 따른다. FE-Q3은 CSS Modules로 결정되었다.

## Glossary

- **Client**: `src/api/client.ts`. 모든 API 요청이 거치는 fetch 래퍼.
- **Mock_DB**: `src/mocks/db.ts`. 목업 데이터와 상태를 가진 메모리 저장소(localStorage에 보관).
- **Mock_User**: 목업 모드에서 로그인된 것으로 보는 시드 사용자(지연·수현·민준, FE-Q10).
- **Tab_Screen**: 하단 탭이 보이는 화면. `/`, `/me`, `/inbox`(FE-Q12).

## Requirements

### Requirement 1: 프로젝트 세팅 [FE-TECH-01, 03, FE-Q16]

**User Story:** 개발 담당으로서, 문서가 정한 스택으로 만든 프로젝트를 원한다. 그래야 2단계부터 화면만 채우면 된다.

#### Acceptance Criteria

1. THE Frontend SHALL React 18 + TypeScript + Vite, React Router, TanStack Query를 쓰고 `frontend/`에 둔다.
2. THE Frontend SHALL `npm run dev`, `npm run build`, `npm run lint`, `npm run test`, `npm run format` 스크립트를 제공하고, `build`는 타입 검사(`tsc`)를 포함한다.
3. THE Frontend SHALL ESLint와 Prettier 설정을 두고, `npm run lint`가 오류 0건으로 끝난다.
4. THE Frontend SHALL `.env.example`에 `VITE_API_BASE_URL`, `VITE_AWS_REGION`, `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_CLIENT_ID`, `VITE_COGNITO_ENDPOINT`, `VITE_AUTH_MODE`, `VITE_USE_MOCK`와 세 연동 모드의 값 설명을 두고, `.env.local`은 gitignore한다.
5. THE Frontend SHALL 환경 변수를 `src/config.ts` 한 곳에서 읽고, 비밀값을 `VITE_*`에 두지 않는다.

### Requirement 2: 스타일과 레이아웃 [FE-TECH-06, FE-NFR-01, 02, FE-Q3, FE-Q5, FE-Q14]

**User Story:** 사용자로서, 모바일 폭에서 시안과 같은 배치를 보고 싶다.

#### Acceptance Criteria

1. THE Frontend SHALL 스타일을 CSS Modules로만 쓰고, Tailwind 등 다른 방식을 섞지 않는다.
2. THE Frontend SHALL docs/05 §5.3의 색 토큰 7개를 `src/styles/tokens.css`의 CSS 변수로 두고, 컴포넌트는 색을 토큰으로만 쓴다.
3. THE Frontend SHALL 글꼴·간격·모서리 토큰을 추정값으로 표시해 `tokens.css`에 둔다(FE-Q14).
4. THE Layout SHALL 화면 폭 360–480px에서 꽉 차고, 480px보다 넓으면 최대 폭 480px로 가운데 정렬한다.

### Requirement 3: 공통 컴포넌트 [FE-COM-01, 02, FE-NFR-02, 03, 05, 06]

**User Story:** 개발 담당으로서, 모든 화면이 같은 패턴을 쓰도록 공통 컴포넌트를 원한다.

#### Acceptance Criteria

1. THE Header SHALL 뒤로가기 버튼(선택), 가운데 제목, 오른쪽 편지 아이콘(수신함 링크)을 보여주고, `GET /me`의 `unreadInboxCount > 0`이면 편지 아이콘에 주황(`--color-accent`) 점을 표시한다.
2. THE BottomTab SHALL 둘러보기(`/`) / 내 하루(`/me`) / 수신함(`/inbox`) 세 탭을 보여주고, 현재 탭을 `--color-primary`로 표시하며, Tab_Screen에서만 보인다.
3. THE PrimaryButton SHALL 화면 아래에 고정된 꽉 찬 폭 버튼(모서리 12–16px)이고, `loading` 동안 비활성화된다.
4. THE StatusBadge SHALL 이어받기 가능 / 이어받음 / 완료 / 공개 / 새 편지 / 읽은 기록 / 내가 이어받은 하루 / 내가 남긴 하루를 표시한다.
5. THE RouteTimeline SHALL 장소마다 번호 원과 세로 연결선을 그리고, 마지막 장소의 원을 `--color-primary`로 채운다.
6. THE TextField and TextArea SHALL 라벨, 글자 수(최대값이 있을 때), 에러 메시지를 보여주고, 에러는 `aria-describedby`로 입력칸과 연결한다.
7. THE Toast SHALL 짧은 메시지를 잠시 보여주고 사라지며, 앱 어디서든 `useToast()`로 띄울 수 있다.
8. THE ResultScreen SHALL 원형 아이콘(체크·느낌표) + 제목 + 설명 + 요약 카드(선택) + 하단 버튼을 보여준다.
9. THE PageTitle SHALL 큰 제목(굵게) + 회색 보조 설명 패턴을 제공한다.
10. THE Components SHALL 사용자 입력을 React 기본 이스케이프로만 렌더링한다(`dangerouslySetInnerHTML` 금지).

### Requirement 4: API 타입과 공통 클라이언트 [FE-TECH-05, FE-COM-03, 04, 05, FE-NFR-05]

**User Story:** 개발 담당으로서, 모든 요청이 한 곳에서 토큰 부착과 에러 처리를 하길 원한다.

#### Acceptance Criteria

1. THE Frontend SHALL docs/03의 이름으로 `src/api/types.ts`에 `Plan`, `PlanSummary`, `Place`, `Claim`, `Record`, `InboxItem`, `SessionView`, `AiQuestion`, `AiNote`, `AiTraceStep`, `Flag`, `ErrorCode`, 요청·응답 래퍼 타입을 정의한다. `Plan`에 `currentClaimId`를 넣지 않는다(BE-Q33).
2. THE Client SHALL 모든 요청에 `Authorization: Bearer {ID 토큰}`을 붙이고, 토큰이 없으면 요청을 보내지 않고 401로 처리한다.
3. WHEN 응답이 4xx/5xx이고 본문이 `{ error: { code, message, details? } }`이면, THE Client SHALL `ApiError(status, code, message, details)`를 던진다.
4. WHEN 응답이 401이면(본문 형식과 무관, docs/03 §3.6), THE Client SHALL `ApiError(401, 'UNAUTHORIZED')`를 던지고 `/login?redirect={현재 경로}`로 이동시킨다.
5. WHEN 응답이 503 `TRY_AGAIN`이면, THE Client SHALL 같은 요청을 1회 다시 보내고, 또 실패하면 `ApiError`를 던진다.
6. WHEN 본문이 계약 형식이 아닌 오류 응답이면, THE Client SHALL `code`를 `INTERNAL_ERROR`로 둔 `ApiError`를 던진다(BE-Q23).
7. THE Client SHALL 토큰과 presigned URL을 로그·에러 메시지에 남기지 않는다.
8. THE Client SHALL `Idempotency-Key` 등 추가 헤더와 타임아웃(`timeoutMs`)을 요청별로 받을 수 있다.
9. THE Frontend SHALL `ApiError.code`별 공통 안내 문구(`NOT_FOUND`, `FORBIDDEN`, `TRY_AGAIN` 등)와 `VALIDATION_ERROR.details` 경로→입력칸 매핑 함수를 제공한다.

### Requirement 5: MSW 목업 [FE-TECH-04, FE-NFR-07, FE-Q10, FE-Q11, FE-Q15]

**User Story:** 개발 담당으로서, 백엔드 없이 계약과 같은 응답으로 화면을 만들고 싶다.

#### Acceptance Criteria

1. WHEN `VITE_USE_MOCK=true`이면, THE Frontend SHALL 앱을 그리기 전에 MSW 워커를 시작하고, 그 외에는 MSW 코드를 불러오지 않는다.
2. THE Mock_DB SHALL 시드 사용자 지연·수현·민준과 docs/02 §2.5 예시 계획("이사 전, 마지막 동네 산책", 출근길 빵집·하천 산책로 벤치)을 포함한 계획 2건 이상을 가진다.
3. THE Mock_DB SHALL 상태를 localStorage `haru.mock.db`에 저장해 같은 브라우저의 탭끼리 공유하고, 초기화 함수를 제공한다.
4. THE Mock handlers SHALL 1단계에서 `GET /me`, `GET /plans`, `GET /plans/{planId}`를 docs/03과 같은 형태로 응답하고, 나머지 경로는 2–6단계에서 추가한다.
5. THE Mock handlers SHALL 요청의 `Authorization` 토큰으로 Mock_User를 판별하고, 토큰이 없으면 401을 돌려준다.
6. THE Frontend SHALL 개발 빌드에서만 Mock_User 전환 바를 보여주고, 선택을 탭별 sessionStorage `haru.mock.user`(새 탭 기본값은 localStorage)에 저장해 탭마다 다른 Mock_User를 쓸 수 있게 한다.
7. THE Frontend SHALL 진입 URL의 `?mock=` 값을 sessionStorage `haru.mock.scenario`에 저장해 핸들러가 읽을 수 있게 한다.

### Requirement 6: 인증 골격 [FE-TECH-02, 08, 09, FE-AUTH-03, FE-Q13]

**User Story:** 개발 담당으로서, 7단계에 Cognito를 붙일 자리를 지금 만들어 두고 싶다.

#### Acceptance Criteria

1. THE Frontend SHALL `src/auth/`에 토큰 공급 인터페이스(`getIdToken()`)를 두고, Client는 이것으로만 토큰을 얻는다.
2. WHILE 목업 모드이면, THE Auth SHALL Mock_User의 목업 토큰을 돌려준다.
3. WHILE 목업 모드가 아니면, THE Auth SHALL 1단계에서는 토큰이 없다고 보고(로그인 화면으로 이동), 7단계에서 Amplify로 교체한다.
4. THE RequireAuth SHALL `/login`을 뺀 모든 경로를 감싸고, 토큰이 없으면 `/login?redirect={현재 경로}`로 보낸다.

### Requirement 7: 라우트 골격 [docs/05 §5.1, FE-COM-01]

**User Story:** 개발 담당으로서, 모든 경로가 열려 있어 2단계부터 페이지만 채우면 되길 원한다.

#### Acceptance Criteria

1. THE Router SHALL docs/05 §5.1의 경로 17개(`/login`, `/`, `/plans/:planId`, `/plans/new`, `/plans/new/card`, `/plans/new/form`, `/plans/new/place`, `/plans/:planId/published`, `/me`, `/claims/:claimId/abandon`, `/claims/:claimId/record`, `/claims/:claimId/sending`, `/claims/:claimId/record/photo`, `/claims/:claimId/done`, `/inbox`, `/inbox/:itemId`, 그 외 경로의 404)를 등록하고, 각 경로는 화면 번호와 이름을 보여주는 빈 페이지를 연다.
2. THE Router SHALL `/plans/new*`를 `/plans/:planId`보다 먼저 맞춘다.
3. THE Browse page SHALL 1단계에서 `GET /plans` 목업 응답의 건수를 보여줘 Client와 MSW 연결을 확인할 수 있게 한다.

### Requirement 8: 검증

#### Acceptance Criteria

1. WHEN `npm run dev`(`VITE_USE_MOCK=true`)로 실행하면, THE Frontend SHALL 탭 이동이 되고 모든 경로가 열린다(§7.4 완료 조건).
2. THE Frontend SHALL `npm run build`, `npm run lint`, `npm run test`가 모두 성공한다.
3. THE Tests SHALL Client(토큰 부착, 토큰 없음, 에러 변환, 401 이동, `TRY_AGAIN` 1회 재시도, 비계약 본문), 날짜 KST 변환, 라우트 목록(경로 17개 렌더링), Mock_DB 시드와 `GET /plans/{planId}` 분기 값(`isOwner`, `claimable`)을 확인한다.
