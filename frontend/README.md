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
- 시나리오는 진입 URL의 `?mock=값`으로 고르고 탭을 닫을 때까지 유지된다(FE-Q11). `?mock=`(빈 값)이면 지운다. 시나리오가 없으면 AI 정리는 레벨 0처럼 생성 응답이 바로 `READY`다.

| 시나리오                                    | 동작                                                              | 단계 |
| ------------------------------------------- | ----------------------------------------------------------------- | ---- |
| `?mock=claim-conflict`                      | 이어받기가 항상 409 `ALREADY_CLAIMED`(한 탭에서 2-1 안내 확인)    | 2    |
| `?mock=browse-empty`                        | 둘러보기 목록이 비어 있음(빈 상태 확인)                           | 2    |
| `?mock=photo-fail`                          | 사진 처리 결과 `FAILED`(5-2 실패 화면)                            | 5    |
| `?mock=photo-slow`                          | 사진 처리 90초(5-1에서 60초 뒤 "글로 완료하기" 강조)              | 5    |
| `?mock=photo-upload-fail`                   | 업로드 PUT이 500(브라우저 업로드 실패 → 5-2)                      | 5    |
| `?mock=ai-ask`                              | 데모 경로: 소요 시간 질문 1개 → 답변 → `READY`                    | 6    |
| `?mock=ai-working`                          | `WORKING` 2회 → `finish: true` → `READY`                          | 6    |
| `?mock=ai-degraded`                         | `READY` + `degraded`, `NOT_IN_SOURCE`·`PRIVACY` 안내, "다시 넣기" | 6    |
| `?mock=ai-busy`                             | 첫 답변에 409 `AI_SESSION_BUSY` → 2초 뒤 재동기화 → `READY`       | 6    |
| `?mock=ai-fail` / `ai-quota` / `ai-invalid` | 생성에 503 / 429 / 502 → 직접 작성                                | 6    |
| `?mock=ai-fail-turn`                        | 질문에 답하면 503 → 직접 작성                                     | 6    |

사진은 시나리오가 없으면 업로드 3초 뒤 처리가 끝나 사진과 함께 전달된다. 업로드 주소는 `https://mock-upload.haru.local/...`이고 MSW가 받는다(FE-Q24).

두 탭 경합 확인: 목업 바에서 **초기화** → 탭 A 수현, 탭 B 민준으로 `/plans/pln_demo`를 연다 → A에서 이어받기(내 하루로 이동) → B에서 이어받기(같은 화면에 "이미 다른 사람이 이어받았어요").

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
  api/        types.ts(docs/03과 같은 이름), client.ts(모든 요청), errors.ts, queries/, mutations/
  auth/       tokens.ts(getIdToken, 7단계에 Amplify로 교체), RequireAuth.tsx
  components/ Header, BottomTab, PrimaryButton, StatusBadge, RouteTimeline, TextField/TextArea,
              Toast, ResultScreen, PageTitle, Layout, DevMockBar(개발 전용)
  pages/      login/ browse/ plan/(상세·이어받기, create/ 하루 남기기) me/(내 하루·포기)
              record/(방문 기록·사진·보내는 중·실패·교체·전송 완료·종료 안내) inbox/(수신함·돌아온 하루)
  state/      planDraft.ts(하루 남기기 작성 상태, sessionStorage), letterDraft.ts(방문 기록 임시 글, localStorage),
              sendingClock.ts(보내는 중 기준 시각·업로드 실패, sessionStorage)
  mocks/      db.ts, session.ts, handlers/, browser.ts
  styles/     tokens.css, global.css
  utils/      date.ts(KST), plan.ts, validation.ts(백엔드와 같은 규칙·문구), hash.ts, uuid.ts
  routes.tsx  경로 표(docs/05 §5.1)
```

- `client.ts` 규칙: ID 토큰을 `Authorization: Bearer`로 붙이고, 토큰이 없으면 요청하지 않는다. 401은 본문과 무관하게 상태 코드로 판단해 `/login?redirect=`로 보낸다. 503 `TRY_AGAIN`은 1회 재시도한다. 계약 형식이 아닌 오류는 `INTERNAL_ERROR`(BE-Q23).
- 계약이 바뀌면 `types.ts`와 MSW 핸들러를 같은 PR에서 고친다(FE-NFR-07).

## 임시 결정 (docs/08 §8.2)

| #      | 결정                                                                                                 |
| ------ | ---------------------------------------------------------------------------------------------------- |
| FE-Q3  | CSS Modules                                                                                          |
| FE-Q10 | 개발 전용 목업 바, 사용자 선택은 탭별 sessionStorage, 데이터는 localStorage                          |
| FE-Q11 | `?mock=`은 sessionStorage `haru.mock.scenario`에 유지                                                |
| FE-Q12 | 하단 탭은 `/`, `/me`, `/inbox`                                                                       |
| FE-Q13 | `/login`을 뺀 모든 경로 보호                                                                         |
| FE-Q14 | 시스템 글꼴, 4px 간격, 모서리 14px(추정값)                                                           |
| FE-Q15 | 시드 장소 이름은 명세(출근길 빵집)                                                                   |
| FE-Q16 | Node 22, 버전은 `package-lock.json`으로 고정                                                         |
| FE-Q17 | 2단계 목업 시나리오 `claim-conflict`, `browse-empty`                                                 |
| FE-Q18 | 공개 키 재사용은 `durationMs`를 뺀 본문 해시로 판단, 재전송은 처음 본문 그대로                       |
| FE-Q19 | 폼 값은 앞뒤 공백을 빼고 검증·전송, 글자 수는 코드 포인트                                            |
| FE-Q20 | 폼의 장소는 "고치기"(`/plans/new/place?index=n`)·"빼기"                                              |
| FE-Q21 | 내 하루는 진행 중인 이어받기를 모두 카드로                                                           |
| FE-Q22 | `READY`(미전달)·`DISCARDED`면 "다녀온 이야기 쓰기"는 작성 화면으로                                   |
| FE-Q23 | 보내는 중 기준 시각·업로드 실패는 sessionStorage `haru.sending.{claimId}`                            |
| FE-Q24 | 사진 목업: 업로드 주소, 3초 처리, `photo-fail`·`photo-slow`·`photo-upload-fail`                      |
| FE-Q25 | AI 정리 세부(실패 뒤 빈 폼, 카드는 처음 한 번만 폼에, flags는 고치면 지움, 예약 표시, 타임아웃 35초) |
| FE-Q7  | "다시 넣기"는 MSW 임시 필드 `notes[].restore`가 있을 때만(실제 API에는 없음)                         |
