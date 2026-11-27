# 설계: 백엔드·프론트엔드 정합성 (2026-11-27)

요구사항 번호(ALIGN-*)는 [requirements.md](./requirements.md)를 따른다.

## 1. 결정 요약

| 결정 | 선택 | 버린 대안과 이유 |
|---|---|---|
| D1 닉네임 null | 백엔드는 저장값이 없으면 `null`을 낸다. 프론트 타입을 `string \| null`로 바꾸고 화면이 기본 표시명을 쓴다 (BE-Q45 권장안) | 백엔드가 빈 문자열이나 가짜 이름을 채우는 안: 거짓 값이라 BE-Q45가 금지한다. 저장 시 기본값을 넣는 안: 기존 데이터를 바꿔야 한다 |
| D2 닉네임 길이 | PreSignUp 트리거에서 1–20자를 검사한다 | User Pool 스키마 제약: 만든 뒤 스키마는 바꿀 수 없어 쓸 수 없다. 프론트만 검사: 우회 가능 |
| D3 인증 오류 문구 | Cognito 이름 `UserLambdaValidationException`을 고정 안내 문구로 바꾼다 | 서버 메시지 그대로 표시: 원문을 화면에 쓰지 않는 기존 정책(FE-Q26)에 어긋난다 |
| D4 AI 복원 | 실제 API는 새 필드를 만들지 않는다. 복원 방식은 §4에 설계하고 승인 대기 | 지금 `restore`를 계약에 추가: 승인 없이 계약을 바꾸지 않는다(작업 지시 5.5) |
| D5 로컬 LLM | 로컬 실행은 `LLM_PROVIDER=fake`를 셸 환경 변수로 강제한다 | `backend/.env`의 외부 게이트웨이 설정 사용: 유료 외부 호출이 생긴다 |
| D6 Cognito 브라우저 | 고치지 않는다. 로컬 프론트는 dev-jwt로 검증한다 | 에뮬레이터 CORS 우회 설정: 에뮬레이터 바깥 문제라 검증 범위를 넘는다 |
| D7 프론트 Node | Node 22로 테스트와 빌드를 돌린다(`engines >=22`, FE-Q16) | Node 26: jsdom·undici의 `AbortSignal` 충돌로 259건 전부 실패한다(환경 문제, 코드 문제 아님) |

## 2. API 정합성 분류

| 엔드포인트 | 분류 | 근거 |
|---|---|---|
| `GET /me` | 정상 구현 | 로컬 API와 브라우저 헤더 수. 닉네임 없는 토큰에서 `nickname: null` 확인 |
| `GET /plans?status=OPEN` | 정상 구현 | API와 브라우저 둘러보기. `ownerNickname` null 확인(ALIGN-1) |
| `GET /plans/{planId}` | 정상 구현 | API와 브라우저 상세. 소유자·실행자·일반 사용자 분기 확인 |
| `POST /plans` (멱등 키) | 정상 구현 | API 201, 검증 `details` 키 확인, 브라우저 게시 |
| `POST /plans/{planId}/claims` | 부분 구현 | 201·409 ALREADY_CLAIMED·409 CANNOT_CLAIM_OWN_PLAN을 API로 확인. 200(본인 재요청)은 단위 테스트. 2-1 화면은 MSW 테스트 |
| `POST /claims/{claimId}/abandon` | 정상 구현 | API 200, 계획 OPEN 복귀, 두 번째 요청 409 확인 |
| `GET /me/claims?status=ACTIVE` | 정상 구현 | API와 브라우저 내 하루. D-n·기한 문구 확인 |
| `PUT /claims/{claimId}/record` | 정상 구현 | API 글·사진, 브라우저 글 작성 |
| `POST /claims/{claimId}/record/photo` | 정상 구현 | API 실패 뒤 교체 → READY, 전달 뒤 교체는 409 CLAIM_NOT_ACTIVE |
| `GET /claims/{claimId}/record` | 부분 구현 | 스냅샷 응답과 403·종료 상태 확인. 503 `TRY_AGAIN`은 단위 테스트뿐. 계약 §3.4 미반영(ALIGN-5) |
| `POST /claims/{claimId}/complete` | 정상 구현 | API 200, 재시도 멱등, 사진 대기 중 글로 완료 → DISCARDED |
| `POST /ai/card-sessions` 외 2개 (Agent·Pipeline) | 정상 구현 | Agent: 질문·답변·`degraded`·503 확인. Pipeline: 산책·비산책 확인. 429 한도 초과 시 직접 작성 전환(브라우저) |
| `notes[].restore` | MSW 전용 | 실제 API에 없다. 버튼이 나오지 않는다(ALIGN-4) |
| `GET /inbox`, `GET /inbox/{itemId}`, 읽음, 답장 | 정상 구현 | API와 브라우저. 미확인 수 증감, 중복 읽음·답장 409, 타인 접근 404 |
| `GET /me`의 `unreadInboxCount` | 정상 구현 | 새 기록 +1, 읽음 −1 확인 |
| 로그인(Cognito 브라우저) | 실행 검증 필요 | 로컬 Floci CORS로 막힘(ALIGN-8). 토큰 API 수준은 확인 |
| 가입 닉네임 거절(PreSignUp) | 실행 검증 필요 | 단위 테스트만. AWS 배포 뒤 확인 |

### 2.1 공통 오류 응답

| 코드 | 확인 방법 |
|---|---|
| 400 VALIDATION_ERROR + `details` | 계획 필드·사진 형식·답장 길이·Idempotency-Key 누락 |
| 401 UNAUTHORIZED | 토큰 없음·형식 오류. 프론트 클라이언트는 상태 코드로 판단 |
| 403 FORBIDDEN | 남의 Claim의 기록 조회·쓰기·포기·완료 |
| 404 NOT_FOUND | 없는 계획·기록, 타인의 수신함 항목, 없는 AI 세션 |
| 409 | ALREADY_CLAIMED, CANNOT_CLAIM_OWN_PLAN, CLAIM_NOT_ACTIVE, REPLY_ALREADY_SENT, AI_SESSION_CLOSED |
| 429 AI_QUOTA_EXCEEDED | 로컬 하루 한도(10건) 초과 시 브라우저가 직접 작성 화면으로 넘어가고 사연을 유지한다 |
| 503 AI_UNAVAILABLE | Agent 모드 LLM 오류에 후보 카드가 없을 때. 같은 방식으로 직접 작성 |

## 3. 닉네임 처리 (ALIGN-1, ALIGN-2, ALIGN-3)

- 백엔드: `serialize_plan`, `serialize_plan_summary`, `serialize_claim`, `serialize_inbox_item`은 저장값이 없으면 `null`을 낸다(변경 없음).
- 프론트: `src/utils/nickname.ts`의 `displayNickname(nickname, fallback)`이 공백과 `null`을 기본 표시명으로 바꾼다. 적용 위치는 상세, 둘러보기 카드, 내 하루, 포기 화면, 기록 작성, 수신함 목록·상세다.
- 계약 문서: `docs/03` 공통 규칙에 "닉네임은 `null`일 수 있다(BE-Q45)"를 적는다. 프론트 타입은 이미 반영했으므로 문서 항목은 **구현 반영, 계약 승인 대기**로 표시한다.
- PreSignUp: `_check_nickname`은 `request.userAttributes`에 `nickname` 키가 있을 때만 검사한다. 키가 없으면 User Pool의 Required 설정이 가입을 막으므로 트리거는 건너뛴다. 이렇게 해야 기존 속성 테스트(임의 입력)가 그대로 통과한다.

## 4. AI 복원 설계 (ALIGN-4, BE-Q13, FE-Q7)

### 4.1 현재 상태

- MSW는 `notes[].restore = { value, type }`를 보낸다. 실제 API는 보내지 않는다.
- 프론트는 `restore`가 없으면 "다시 넣기" 버튼을 그리지 않는다. 따라서 실제 API에서는 기능이 없다. 이 동작은 FE-Q7 결정과 같다.
- `REMOVED` 메모의 `path`는 제거 전 후보 인덱스 기준이다(BE-Q76). 복원은 장소 목록 끝에 추가한다.

### 4.2 문제

- 뺀 값은 개인정보(연락처, 동·호수, 비공개 장소)이거나 원문에 없던 말일 수 있다.
- 서버가 뺀 값을 응답에 다시 실어 보내면, 개인정보가 응답 본문에 한 번 더 나간다. 그 값을 그대로 공개 카드에 넣을 수 있는 경로가 생긴다.

### 4.3 안

| 안 | 내용 | 계약 변경 | 개인정보 | 판정 |
|---|---|---|---|---|
| A (권장) | 서버는 뺀 값을 응답하지 않는다. 메모는 사유만 준다. 계획자는 기존 "장소 추가하기"로 직접 다시 넣는다 | 없음 | 응답에 원래 값이 나가지 않는다. 직접 입력은 MANUAL 작성과 같은 정책이고, 서버는 `privacyInPublished` 지표로만 센다 | 지금 적용한 상태 |
| B | `notes[]`에 `restore?: { value: PlaceInput, type: 'NOT_IN_SOURCE' }`를 추가하고, `PRIVACY`로 뺀 값은 절대 싣지 않는다 | `notes` 확장, 프론트 승인 필요 | 개인정보 값은 응답에 없다. 원문에 있던 장소만 되살린다 | 승인 뒤 선택 |
| C | 뺀 값을 서버 세션에 두고 별도 엔드포인트로 복원 | 새 API | 세션 보관 기간 정책 필요 | 채택하지 않음(새 API) |

- 안 A의 대가: 계획자가 이름과 활동을 다시 입력한다. 원문에 있던 장소도 직접 적어야 한다.
- 안 B를 승인받으면 `PRIVACY` 뺀 항목은 여전히 복원하지 않는다는 조건을 계약에 명시한다.
- 어느 안이든 메모 `path`는 제거 전 인덱스를 쓴다(BE-Q13 미결 유지).

## 5. 로컬 실행 환경 (D5, D6, D7)

- `backend/.env`는 이 개발 PC에서 외부 게이트웨이(`openai_compat`)를 가리킨다. 이 설정으로 `docker compose up`을 하면 사연이 외부로 나간다. 검증 중에는 셸에서 `LLM_PROVIDER=fake LLM_BASE_URL= LLM_API_KEY= LLM_MODEL= LLM_EXTRA_BODY=`로 덮어썼다. compose의 `environment`가 `env_file`보다 우선한다.
- 시드: `python scripts/seed.py --local --apply --users fixed`(dev-jwt 인물 ID와 맞춤).
- 프론트 개발 서버: `VITE_USE_MOCK=false VITE_API_BASE_URL=http://localhost:3000 VITE_AUTH_MODE=dev-jwt`, 포트 5173(CORS 허용 출처).
- AI 한도 테스트: 로컬 `AI_DAILY_SESSION_LIMIT`을 올려 반복 검증했다. 기본값 10은 그대로 둔다.

## 6. 검증 방법

1. 기존 테스트를 그대로 돌린다(백엔드 단위·로컬, 프론트 단위·타입·린트·빌드).
2. 발견한 불일치마다 회귀 테스트를 추가한다.
   - 프론트: 닉네임 null 상세 화면, `displayNickname`, `UserLambdaValidationException` 문구.
   - 백엔드: PreSignUp 닉네임 검사(단위), 닉네임 없는 계획·claimer null, 기한 경과 양도와 EXPIRED 쓰기 차단(로컬).
3. API 점검 스크립트(저장소 밖 `/tmp`, 커밋하지 않음)로 13단계 흐름과 오류 응답을 실제 API에 대고 확인했다.
4. 브라우저 점검(Playwright, 저장소 밖)으로 프론트를 실제 API에 붙여 같은 흐름을 돌렸다. 결과와 한계는 [tasks.md](./tasks.md)에 있다.
