# 작업과 검증 기록: 백엔드·프론트엔드 정합성 (2026-11-27)

요구사항은 [requirements.md](./requirements.md), 설계는 [design.md](./design.md)를 따른다. 아래 결과는 2026-11-27 이 작업에서 실행한 값이다. 이전 기록(backend/README 1–12절 등)과 섞지 않는다.

## 1. 구현 작업

| # | 작업 | 상태 | 관련 |
|---|---|---|---|
| T1 | `origin/main`(`cf0220e`)으로 fast-forward. 로컬 `main`에 고유 커밋이 없어 안전했다 | 완료 | 기준 |
| T2 | 프론트 닉네임 타입을 `string \| null`로 바꾸고 `utils/nickname.ts`로 기본 표시명 적용(6개 화면) | 완료 | ALIGN-1, R1 |
| T3 | 상세 화면 회귀 테스트(닉네임 null), `displayNickname`·`initialOf` 단위 테스트 | 완료 | ALIGN-1 |
| T4 | 백엔드 PreSignUp 닉네임 1–20자 검사, 단위 테스트 13건 | 완료(AWS 배포 뒤 확인 대기) | ALIGN-2, R2 |
| T5 | `UserLambdaValidationException` 안내 문구 매핑과 테스트 | 완료 | ALIGN-3, R3 |
| T6 | 로컬 회귀 테스트: 닉네임 없는 계획의 null 응답, 기한 경과 양도와 EXPIRED 쓰기 차단(`tests/local/test_local_alignment.py`) | 완료 | ALIGN-1, 기한 정책 |
| T7 | 계약·요구사항·설계·미결 문서 갱신 | 완료(§3) | R5 |
| T8 | 계약 문서에 `restore`·503·닉네임 null의 승인 대기 표시 | 완료(§3) | ALIGN-4·5 |

프론트 수정 파일: `src/api/types.ts`, `src/utils/nickname.ts`(신규), `src/utils/nickname.test.ts`(신규), `src/pages/plan/PlanDetailPage.tsx`(+테스트), `src/pages/browse/PlanCard.tsx`, `src/pages/me/MyDayPage.tsx`, `src/pages/me/AbandonPage.tsx`, `src/pages/record/RecordPage.tsx`, `src/pages/inbox/InboxPage.tsx`, `src/pages/inbox/InboxDetailPage.tsx`, `src/auth/authErrors.ts`, `src/auth/auth.test.ts`.

백엔드 수정 파일: `src/handlers/pre_signup.py`, `tests/unit/test_pre_signup.py`(신규), `tests/local/test_local_alignment.py`(신규).

백엔드 응답 형태와 핸들러 로직은 바꾸지 않았다. 계약 필드 추가도 없다.

## 2. 검증 기록 (2026-11-27)

### 2.1 자동 테스트

| 대상 | 명령 | 결과 |
|---|---|---|
| 백엔드 단위 | `pytest tests/unit -q` | 1670 passed, 2 deselected(`slow` 40MP 측정) |
| 백엔드 로컬, 파이프라인 기본 | `pytest -m local tests/local` | 41 passed, 23 skipped(Agent 전용) |
| 백엔드 로컬, Agent | `LOCAL_AGENT_MODE=agent pytest -m local tests/local/test_local_agent.py tests/local/test_local_alignment.py` | 6 passed, 5 skipped(컨테이너 재기동 사례는 `LOCAL_COMPOSE_CONTROL=1` 필요) |
| 프론트 단위 | `npx vitest run` (Node 22.23.5) | 28 files, 264 tests passed(이전 259) |
| 프론트 타입 | `npx tsc -b` | 통과 |
| 프론트 린트 | `npx eslint .` | 통과 |
| 프론트 포맷 | `npx prettier --check` (수정 파일) | 통과. 저장소 기존 경고 2개(`src/mocks/db.ts`, `BrowsePage.test.tsx`)는 이 작업과 무관 |
| 프론트 빌드 | `npm run build` (Node 22) | 통과 |

Node 26에서 프론트 테스트를 돌리면 259건이 모두 실패한다(undici `AbortSignal`). 같은 코드가 Node 22에서 통과하므로 Node 22를 기준으로 기록한다(D7).

### 2.2 로컬 API 점검 (실제 compose 스택, 저장소 밖 스크립트)

- 13단계 흐름: 지연 로그인 → 사연 AI 정리(질문 응답 건너뛰기) → 게시 → 수현 둘러보기·상세 → 이어받기(201) → 내 하루 → 글 저장 → 글로 완료 → 완료 재요청(멱등, 200) → 지연 미확인 1 → 수신함 상세 → 읽음(204, 재요청 204) → 미확인 감소 → 답장(201) → 재답장(409).
- 사진: 업로드 → 처리 → READY·전달, 수신함 `hasPhoto: true`. 선언 크기 불일치 presigned PUT은 403 `SignatureDoesNotMatch`. 처리 실패(FAILED) → 교체 → READY. 업로드 대기 중 글로 완료 → DISCARDED, 늦은 업로드는 무시.
- 기한: 기한 경과 전 다른 사람 409, 경과 후 목록·상세에 OPEN으로 표시, 이전 실행자 늦은 기록 200, 새 실행자 201 후 이전 Claim EXPIRED, 이후 쓰기·완료·포기 409 `CLAIM_NOT_ACTIVE`.
- 포기: 200 ABANDONED, 계획 OPEN 복귀, 다른 사람 이어받기 201, 재포기 409.
- 오류: 토큰 없음·잘못된 토큰 401 `UNAUTHORIZED`, 타인의 기록 조회·쓰기·포기·완료 403 `FORBIDDEN`, 없는 계획 404, 본문 오류 400 `VALIDATION_ERROR`의 `details`(`places[0].name`, `photo.contentType`, `text`, `Idempotency-Key`), 없는 수신함 항목 404.
- 닉네임 없는 토큰(`dev-nonick`): `GET /me` nickname null, 계획 `owner.nickname` null, 목록 `ownerNickname` null.
- AI 오류 경로(Agent, 시나리오별 컨테이너 재기동): `http_500` → 503 `AI_UNAVAILABLE`, `budget_exhausted`·`privacy_card`·`gate_reject_thrice` → 200 READY `degraded: true`와 `PRIVACY` 플래그 또는 `REMOVED` 메모, `exhibition_ask_time` → ASKING(질문 있음). 로컬 한도 10건 초과 시 429 `AI_QUOTA_EXCEEDED`.

### 2.3 브라우저 실연동 (Playwright, Chromium, 로컬 Vite 5173 + 로컬 어댑터 3000)

| 시나리오 | 모드·사례 | 결과 |
|---|---|---|
| 주 흐름 (지연 → 수현 → 지연) | Agent, `ask_once`, 산책 | 게시 → 이어받기 → 내 하루(D-3) → 기록 → 전송 완료 → 수신함 → 읽음 → 답장. HTTP 4xx·5xx와 페이지 오류 없음 |
| 주 흐름 | Agent, `exhibition_ask_time`, 전시(비산책) | 질문 턴 후 READY, 같은 흐름 끝까지 통과 |
| 주 흐름 | Pipeline, `happy`, 산책 | 같은 흐름 통과 |
| 주 흐름 | Pipeline, `cafe`, 카페(비산책) | 같은 흐름 통과 |
| 사진 전송 | Pipeline, 수현 계정, 사진 1장 | 업로드 → 처리 → 전송 완료 화면, 수신함 사진 항목 |
| 닉네임 없는 계획 상세 (ALIGN-1 재현) | 수정 전 | `Cannot read properties of null (reading 'slice')`로 앱 오류 화면 |
| 닉네임 없는 계획 상세 | 수정 후 | "계획을 남긴 사람 · 취소한 이유" 정상 표시, 둘러보기 "계획을 남긴 사람의 하루" |
| 한도 초과 | Pipeline, 지연 계정 한도 10 | 429 후 직접 작성 화면, 사연 유지(기대 동작) |
| Cognito 로그인 | `VITE_AUTH_MODE=cognito`, Floci | CORS 사전 요청 405로 막힘, "네트워크 연결을 확인해 주세요." (ALIGN-8) |

브라우저 콘솔에는 DOM 중첩 경고 1종만 남았다(CardPreview, ALIGN-6). 다른 콘솔 오류와 HTTP 4xx·5xx는 없었다.

## 3. 계약 문서 반영 상태

| 항목 | 문서 | 상태 |
|---|---|---|
| 닉네임 `null` 가능 (BE-Q45) | `docs/03` 공통 규칙 | 구현 반영. 프론트 담당 리뷰 대기 |
| `notes[].restore` (BE-Q13·FE-Q7) | `docs/03` §3.2 | 변경 없음. 안 A 권장, 승인 대기 |
| 503 `TRY_AGAIN` on `GET /record` (BE-Q46) | `docs/03` §3.4 | 변경 없음. 승인 대기 |
| 닉네임 1–20자 PreSignUp (FE-Q26) | `docs/06` FE-AUTH-02 | 구현 반영. AWS 배포 뒤 확인 대기 |

## 4. 남은 항목과 승인 필요 사항

| 항목 | 이유 | 누가 |
|---|---|---|
| 닉네임 null의 계약 확정 | 프론트 담당이 리뷰해야 `docs/03`에서 확정으로 쓸 수 있다 | 프론트 담당 |
| 복원 방식 A/B 결정 | 안 B는 계약 확장이다 | 프론트·백엔드 |
| `GET /record` 503 계약 반영 | BE-Q46 승인 전에는 §3.4를 고치지 않는다 | 프론트 담당 |
| PreSignUp 닉네임 검사의 AWS 확인 | 로컬 Floci는 PreSignUp 트리거를 연결하지 않았다 | AWS 담당 |
| CardPreview DOM 중첩 경고(FE-Q28) | 디자인 변경을 피하려고 고치지 않았다 | 프론트 담당 |
| "3일" 안내 문구 고정(ALIGN-7) | 기한 일수가 바뀌면 문구도 맞춰야 한다 | 프론트 담당 |
| 503 `TRY_AGAIN` 실제 경합 재현 | 로컬에서는 재시도 소진을 만들지 못했다(단위 테스트만) | 백엔드 |
| 실제 LLM 품질(비산책 포함) | 유료 호출이라 하지 않았다. 파이프라인 구조와 Fake 시나리오만 확인 | 팀(BE-Q6·Q7) |
| 실제 Cognito 브라우저 로그인 | Floci CORS 문제(ALIGN-8) | 로컬 환경 담당 |
| AWS 배포 검증 | 이번 작업은 배포하지 않았다 | AWS 담당 |

로컬 Floci 데이터에는 검증 중 만든 계획이 남아 있다. 여기에는 잘못된 프로브 실행으로 만들어진 소유자 `d`·`e`의 계획도 있다. 로컬 데이터이며 저장소에는 없다. 필요하면 `docker compose down -v`로 지우고 다시 시드한다(볼륨 삭제는 사용자 확인 뒤).
