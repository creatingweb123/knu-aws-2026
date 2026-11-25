# 이어온 하루 프론트엔드

모바일 웹(React 18 + TypeScript + Vite). 명세는 [docs/](../docs/)가 기준이고, 단계별 범위는 [docs/07 §7.4](../docs/07-development-plan.md), 이번 단계 spec은 `.kiro/specs/frontend-stage1-setup/`이다.

## 상태

| 항목   | 상태                                                                                                   |
| ------ | ------------------------------------------------------------------------------------------------------ |
| 단계   | **1단계 완료**(세팅, 공통 컴포넌트, API 타입·클라이언트, MSW 목업, 라우트 골격). 2–4단계는 이어서 진행 |
| 연동   | MSW 목업 모드만. 실제 API 전환은 S2(백엔드 4단계 배포 후), Cognito 로그인은 7단계                      |
| 스타일 | CSS Modules(FE-Q3 결정). 토큰은 `src/styles/tokens.css`, 색은 추정값(FE-Q5, FE-Q14)                    |

## 시작

Node 22 이상.

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local   # VITE_USE_MOCK=true가 기본값
npm run dev                         # http://localhost:5173
```

PowerShell에서 `npm.ps1` 실행이 막혀 있으면 `npm.cmd`로 실행한다.

| 명령             | 내용                                                        |
| ---------------- | ----------------------------------------------------------- |
| `npm run dev`    | 개발 서버(5173)                                             |
| `npm run build`  | 타입 검사(`tsc -b`) + 빌드                                  |
| `npm run lint`   | ESLint(`dangerouslySetInnerHTML` 금지 규칙 포함, FE-NFR-05) |
| `npm run test`   | Vitest(jsdom) + MSW Node                                    |
| `npm run format` | Prettier                                                    |

## 연동 모드 (FE-TECH-08)

환경 변수만 바꿔 전환한다. 값은 `.env.example`의 표와 docs/02 §2.4.7을 따른다.

| 모드              | 설정                                                             | 비고                                                                      |
| ----------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------- |
| MSW 목업          | `VITE_USE_MOCK=true`                                             | 1–6단계 개발 기본값                                                       |
| 로컬 백엔드       | `VITE_USE_MOCK=false`, `VITE_API_BASE_URL=http://localhost:3000` | 백엔드 Docker 환경 첫 실행 확인 전(backend/README.md 5절). 로그인은 7단계 |
| `dev`/`demo` 스택 | SAM 출력값                                                       | S1–S5                                                                     |

## 목업 사용 방법

- 화면 위쪽 검은 **목업 바**(개발 빌드 + 목업 모드에서만 보임)에서 사용자(지연·수현·민준)를 고른다. 목업 모드에서는 고른 사용자로 로그인된 상태로 본다(FE-Q10, FE-Q13).
- 사용자 선택은 **탭별**이다. 탭 A는 수현, 탭 B는 민준으로 두면 같은 목업 데이터에서 동시 이어받기 경합을 재현할 수 있다(2단계).
- 목업 데이터는 localStorage `haru.mock.db`에 있어 탭끼리 공유된다. 목업 바의 **초기화**로 시드로 되돌린다.
- 시나리오는 진입 URL의 `?mock=값`으로 고르고 탭을 닫을 때까지 유지된다(FE-Q11). `?mock=`(빈 값)이면 지운다. 시나리오 처리는 5단계(사진)·6단계(AI)에서 추가한다.

시드 데이터(`src/mocks/db.ts`, FE-Q15)

| 계획                                      | 계획자 | 상태            | 확인할 수 있는 것                            |
| ----------------------------------------- | ------ | --------------- | -------------------------------------------- |
| 이사 전, 마지막 동네 산책 (`pln_demo`)    | 지연   | OPEN            | 데모 계획(출근길 빵집·하천 산책로 벤치)      |
| 비 오는 날 도서관 가는 길 (`pln_library`) | 민준   | OPEN            | 민준 기준 "내가 남긴 하루"                   |
| 시장 골목 아침 장보기 (`pln_market`)      | 지연   | CLAIMED(민준)   | 수현 기준 2-1, 민준 기준 내가 이어받은 하루  |
| 해 질 녘 다리 위에서 (`pln_bridge`)       | 지연   | COMPLETED(수현) | 지연 수신함의 안 읽은 편지 1건(헤더 주황 점) |

## 구조

docs/02 §2.10을 따른다.

```
src/
  api/        types.ts(docs/03과 같은 이름), client.ts(모든 요청), errors.ts, queries/
  auth/       tokens.ts(getIdToken, 7단계에 Amplify로 교체), RequireAuth.tsx
  components/ Header, BottomTab, PrimaryButton, StatusBadge, RouteTimeline, TextField/TextArea,
              Toast, ResultScreen, PageTitle, Layout, DevMockBar(개발 전용)
  pages/      login/ browse/ (2–6단계에 plan/ me/ record/ inbox/ 추가)
  mocks/      db.ts, session.ts, handlers/, browser.ts
  styles/     tokens.css, global.css
  utils/      date.ts(KST)
  routes.tsx  경로 표(docs/05 §5.1)
```

- `client.ts` 규칙: ID 토큰을 `Authorization: Bearer`로 붙이고, 토큰이 없으면 요청하지 않는다. 401은 본문과 무관하게 상태 코드로 판단해 `/login?redirect=`로 보낸다. 503 `TRY_AGAIN`은 1회 재시도한다. 계약 형식이 아닌 오류는 `INTERNAL_ERROR`(BE-Q23).
- 계약이 바뀌면 `types.ts`와 MSW 핸들러를 같은 PR에서 고친다(FE-NFR-07).

## 임시 결정 (docs/08 §8.2)

| #      | 결정                                                                        |
| ------ | --------------------------------------------------------------------------- |
| FE-Q3  | CSS Modules                                                                 |
| FE-Q10 | 개발 전용 목업 바, 사용자 선택은 탭별 sessionStorage, 데이터는 localStorage |
| FE-Q11 | `?mock=`은 sessionStorage `haru.mock.scenario`에 유지                       |
| FE-Q12 | 하단 탭은 `/`, `/me`, `/inbox`                                              |
| FE-Q13 | `/login`을 뺀 모든 경로 보호                                                |
| FE-Q14 | 시스템 글꼴, 4px 간격, 모서리 14px(추정값)                                  |
| FE-Q15 | 시드 장소 이름은 명세(출근길 빵집)                                          |
| FE-Q16 | Node 22, 버전은 `package-lock.json`으로 고정                                |
