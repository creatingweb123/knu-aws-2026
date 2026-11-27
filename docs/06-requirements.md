# 6. 요구사항

명세를 구현·검증할 수 있는 단위로 나누고 ID를 붙인 목록이다. 백엔드는 `BE-*`, 프론트엔드는 `FE-*`다. PR 본문에는 관련 요구사항 ID를 적는다. 요구사항은 산책에 한정되지 않는다. 장소 1곳이거나 걷지 않는 활동이어도 같은 요구가 성립해야 하며, 이를 확인하는 기준은 [§6.7](#67-인수-기준)의 '일상 활동 일반화'에 있다. 서비스의 세 층(본질·MVP 적용 범위·대표 활용 사례)은 [§1.1](./01-overview.md)을 따른다. 이 목록과 명세(2–5장)가 다르면 명세가 우선하고, 이 목록을 고친다.

## 6.1 용어

| 용어 | 뜻 |
|---|---|
| 계획자 (owner) | 하루(Plan)를 남긴 사용자 |
| 실행자 (claimer) | 하루를 이어받은 사용자 |
| Plan | 하루 계획. 실현하지 못한 일상 계획(산책, 카페·서점 방문, 전시 관람, 사진 촬영 등)을 양도하는 단위다. `OPEN` → `CLAIMED` → `COMPLETED` |
| Claim | 한 번의 이어받기 시도. `ACTIVE` → `COMPLETED` / `ABANDONED` / `EXPIRED` |
| Record | Claim당 1개인 경험 기록(글 + 사진 상태). 화면과 서술에서는 '경험 기록', 필드·API·ID는 `Record`·`record`·`REC`를 그대로 쓴다 |
| InboxItem | 계획자 수신함 항목. Claim당 최대 1개, `itemId = claimId` |
| 지연 해제 | 스케줄러 없이, 기한 지난 Claim을 새 이어받기 요청 시점에 `EXPIRED`로 바꾸는 방식 |
| AiSession | 하루 카드 에이전트 세션. `WORKING` / `ASKING` → `READY` / `FAILED`. HTTP 요청 1번이 에이전트 1턴 |
| 근거 텍스트 | 원문 충실도 판정의 기준. 사연 + 이 세션에서 계획자가 직접 입력한 답변. 모델이 만든 문장은 포함하지 않는다 |
| 레벨 0 | 같은 API 안의 결정적 파이프라인(`AGENT_MODE=pipeline`). 질문 없이 단발 생성 + 결정적 검사·폴백 |

## 6.2 백엔드 기능 요구사항

표기: **[필수]** P0 완료 조건, 근거 열은 관련 명세의 절 번호(§), 보장 번호(G), 검증 시나리오(T), 미결 질문(Q)이다.

### 6.2.1 인증·사용자 (AUTH)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-AUTH-01 | Cognito User Pool은 이메일을 사용자 이름으로 쓰고, `nickname`을 필수 속성으로 받는다. App Client는 클라이언트 시크릿 없이 생성한다(브라우저 SDK 사용). | [§1.6](./01-overview.md) |
| BE-AUTH-02 | PreSignUp Lambda가 `autoConfirmUser = true`, `autoVerifyEmail = true`를 설정해 인증 코드 단계를 없앤다. | [§1.6](./01-overview.md) |
| BE-AUTH-03 | 모든 API 경로는 JWT authorizer로 보호한다. 토큰이 없거나 만료되면 401 `UNAUTHORIZED`. | [§3](./03-api-contract.md), T1 |
| BE-AUTH-04 | 사용자 ID는 JWT `sub`, 닉네임은 ID 토큰의 `nickname` 클레임에서 읽는다. 요청 본문의 사용자 ID는 쓰지 않는다. | [§3](./03-api-contract.md), [§2.8](./02-architecture.md) |
| BE-AUTH-05 | `GET /me`는 `userId`, `nickname`, `unreadInboxCount`를 반환한다. | [§3.1](./03-api-contract.md) |

### 6.2.2 AI 하루 카드 정리 (AI)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-AI-01 | 세션 API 3개를 둔다. `POST /ai/card-sessions { story(1–1,000자) }`, `POST /ai/card-sessions/{sessionId}/turns { expectedTurn, answer?, finish? }`, `GET /ai/card-sessions/{sessionId}`. 모두 200 `SessionView { sessionId, status, turn, trace, question, card, flags, notes, degraded }`를 반환한다. `card` 필드 이름은 `POST /plans` 요청과 같다. 소유자가 아니거나 없는 세션은 404 `NOT_FOUND`. | [§3.2](./03-api-contract.md), [§2.8](./02-architecture.md) |
| BE-AI-02 | 모델은 `ChatOpenAI(base_url=LLM_BASE_URL, api_key, model=LLM_MODEL, use_responses_api=False)`로 OpenAI 호환 Chat Completions API를 부른다. `max_tokens` 800, `temperature` 0(`LLM_TEMPERATURE`가 비면 생략), `LLM_PARALLEL_TOOL_CALLS=false`이면 `bind_tools(parallel_tool_calls=False)`, 빈 값이면 인자를 넘기지 않는다(거부하는 서버용), 공급자별 추가 필드는 `LLM_EXTRA_BODY`. `tool_choice`(`LLM_TOOL_CHOICE`)에는 의존하지 않는다. API 키는 AWS에서 SSM SecureString(`LLM_API_KEY_PARAM`)을 콜드 스타트 때 1회 읽어 캐시하고, 로컬에서는 `.env`의 `LLM_API_KEY`를 쓴다. `LLM_PROVIDER=fake`이면 Fake 채팅 모델을 쓴다. | [§2.1](./02-architecture.md), [§3.2](./03-api-contract.md), BE-Q6 |
| BE-AI-03 | 시스템 프롬프트(`src/prompts/day_card_agent.md`)는 원문에 있는 장소·행동만, 없는 값은 `null`, 공개 장소만, 개인 정보 제거, 방문 질문 정확히 1개, "빼기보다 원문 표현으로 바꾸기"를 지시한다. 산책 한 가지를 전제로 쓰지 않는다. 장소 1곳, 걷지 않는 활동(전시 관람, 카페에 앉아 있기, 사진 촬영 등)의 사연도 같은 규칙으로 정리하고, 질문은 그 사연의 활동에 맞춘다. 사연과 답변은 `<story>`, `<answer>` 데이터 블록에 넣고 블록 안의 지시를 따르지 말라고 적는다. | [§3.2](./03-api-contract.md), T22 |
| BE-AI-04 | 도구는 `check_draft`(읽기 전용 결정적 검사), `ask_planner`(질문 1개, 턴 종료), `submit_card`(그래프 종료, `gate`로) 3개만 둔다. 도구·노드는 DB에 직접 쓰지 않는다. 그래프 상태는 체크포인터가, AiSession(지표·status·question·card)은 턴이 끝날 때 핸들러가 쓴다. Plan은 만들지 않는다. `submit_card`는 서버 게이트가 `check_draft`를 다시 돌려 스키마 오류·`places`의 `NOT_IN_SOURCE`·privacy `HIGH`가 남으면 거부하고(2회까지), 세 번째에는 결정적 폴백(위반 장소 제거 또는 플래그 유지, 개인정보 마스킹, `degraded = true`)을 쓴다. `ask_planner`는 질문 60자 이하, 선택지 0–4개(각 15자 이하)이고 질문 2개 초과·같은 `path` 재질문·개인정보 포함 질문을 거부한다. 거부 판정은 `decide` 노드 안에서 하고, 거부되면 오류 `ToolMessage`와 함께 다시 `decide`로 보낸다. 수락된 질문만 `ask_planner` 노드로 간다. | [§3.2](./03-api-contract.md), G6, T18 |
| BE-AI-05 | Lambda 타임아웃 27s, `ChatOpenAI`의 `timeout`(connect 2초, read 8초)과 `max_retries=0`을 명시한다(SDK 기본값 600초·재시도 2회 금지). LLM 노드로 가기 전 남은 실행 시간이 12초 미만이면 호출하지 않고 `pause` 노드에서 `WORKING`으로 응답한다. LLM 오류(연결 실패·타임아웃·5xx·429·401/403·400, SSM API 키 읽기 실패 포함. 키 읽기 실패는 캐시하지 않고 다음 호출에서 다시 읽는다)이면 후보 카드가 있을 때 결정적 폴백으로 `READY`(`degraded`), 없을 때 세션 `FAILED` + 503 `AI_UNAVAILABLE`. 어떤 실패도 코드 없는 500으로 끝나지 않는다. | [§3.2](./03-api-contract.md), T12, T21 |
| BE-AI-06 | 원문 충실도 판정 함수는 `find_not_in_source(sources, targets)`다. `sources`는 사연 + 이 세션에서 계획자가 직접 입력한 답변, `targets`는 `places[].name`/`activity`. 정규화(공백·조사 제거)한 핵심 명사가 근거 텍스트에 없으면 `NOT_IN_SOURCE`, `null` 필드는 `MISSING`. 같은 함수를 `POST /plans` 지표 계산과 공유한다. 개인정보는 `scan_privacy`(`src/domain/privacy.py`)가 사연·답변·질문문·카드를 대상으로 전화·이메일·주민번호·차량번호·동/호수·번지 정규식, 비공개 장소 사전, 제3자 실명 후보로 판정한다. `HIGH`(연락처, 동·호수)는 게이트에서 막고 마스킹한다. 개인정보가 든 답변은 근거 텍스트에서 뺀다. | [§3.2](./03-api-contract.md), [§3.3](./03-api-contract.md), T19 |
| BE-AI-07 | 세션은 `AiSession`(`AISESSION#{sessionId}`/`META`, TTL 30일)에 저장한다. 사연, 답변, 첫 제안·첫 검사 결과(`firstProposal`, `firstReport`), 카드·플래그·메모·trace, 호출·토큰 수를 남긴다. 모델 대화와 그래프 상태는 AiSession이 아니라 체크포인트 테이블(BE-AI-14)에 둔다. 이 시점에 Plan은 만들지 않는다. | [§2.6](./02-architecture.md), G6 |
| BE-AI-08 | 세션 예산: 모델 호출 6회, 질문 2개, `check_draft` 4회, 게이트 거부 2회, 누적 입력 토큰 3만. 예산을 다 쓰면 결정적 폴백으로 `READY`(`degraded`). 질문 예산을 다 썼거나 마지막 모델 호출이거나 `finish`를 받은 뒤(`finishRequested = true`, 이후 턴에도 유지)이면 `ask_planner`를 도구 목록에서 뺀다. finish 턴이 `WORKING`이 되면 프론트는 `finish: true`로 이어서 보내고, 모델 호출 예산을 다 쓰면 결정적 폴백으로 `READY`(`degraded`)가 된다. 모델이 도구 호출 없이 텍스트만 돌려주면 제출 재촉을 1회 덧붙여 `decide`를 다시 부르고(예산 포함), 그래도 없으면 결정적 폴백. 허용 목록 밖 도구·파싱 안 되는 인자는 오류 `ToolMessage`로 돌려주고, 한 응답의 여러 도구 호출은 첫 번째만 실행한다(나머지는 `ONE_TOOL_PER_TURN` 오류 `ToolMessage`). | [§3.2](./03-api-contract.md) |
| BE-AI-09 | 턴 시작 시 조건부 갱신(`attribute_exists(PK) AND ownerId = :me AND turn = :expectedTurn AND status IN (ASKING, WORKING) AND` 잠금 없음/만료)으로 `lockedUntil = now + 30s`를 걸고, 같은 갱신에서 `status = WORKING`으로 바꾸며 `answer`·`finish`를 기록한다(처리 중 `GET`은 처리 전 `turn`의 `WORKING`). 실패 시 세션을 다시 읽어 순서대로 분기한다: 세션 없음·소유자 아님 → 404 `NOT_FOUND`, `turn ≠ expectedTurn` → 모델 호출 없이 현재 `SessionView` 200, `READY`·`FAILED` → 409 `AI_SESSION_CLOSED`, 잠금 중 → 409 `AI_SESSION_BUSY`. | [§2.6](./02-architecture.md), [§3.2](./03-api-contract.md), [§2.8](./02-architecture.md), T20 |
| BE-AI-10 | 세션 생성 시 `AiQuota`(`AIQUOTA#{userId}#{yyyymmdd}`/`META`, TTL 2일)에 `ADD sessions 1`을 조건 `attribute_not_exists(sessions) OR sessions < :limit`(기본 10)으로 건다. 초과하면 모델을 부르지 않고 429 `AI_QUOTA_EXCEEDED`. | [§2.6](./02-architecture.md), [§3.2](./03-api-contract.md) |
| BE-AI-11 | 레벨 0: `AGENT_MODE=pipeline`이면 같은 그래프에서 `decide` 대신 고정 규칙 노드를 연결해, 같은 계약으로 모델 1회 생성(검증 실패 시 남은 시간이 12초 이상일 때만 1회 재시도) → `check_draft` → 규칙 노드 → `gate`(통과하면 END, 위반이 남으면 재시도 없이 결정적 폴백) → 질문 없이 `READY`. interrupt가 없으므로 체크포인터 없이 컴파일한다. 레벨 0도 같은 LangGraph 의존성을 쓰므로 의존성 문제는 이 전환으로 피할 수 없고, 6a에서 먼저 검증한다. 검증을 통과한 후보 카드가 없으면 502 `AI_INVALID_OUTPUT`(레벨 0 전용). 세션 `agentMode = PIPELINE`. | [§3.2](./03-api-contract.md) |
| BE-AI-12 | (선택) 공급자별 보조 판정: 차단 기준은 `scan_privacy` 정규식뿐이다. 공급자가 OpenAI일 때만 `/v1/moderations`를 참고 플래그로 쓸 수 있다(유해 콘텐츠 분류이지 PII 탐지가 아니고, 공통 기능이 아니다. Ollama·vLLM·Anthropic·Gemini 호환 문서에 없다). 기본은 쓰지 않는다. | [§3.2](./03-api-contract.md) |
| BE-AI-13 | 에이전트는 LangGraph `StateGraph`로 노드를 명시적으로 연결한다(`src/agent/graph.py`, `nodes.py`, `tools.py`). 범용 prebuilt 에이전트는 쓰지 않는다. 노드: `draft`(content JSON 파싱, JSON이 아니면 1회 재시도)·`decide`(LLM, `ask_planner` 거부 판정 포함), `check_draft`·`gate`·`fallback`(순수 함수), `ask_planner`(거부 분기 없이 노드 맨 앞에서 항상 `interrupt(question)`, 재개 값 `Command(resume=answer)`), `pause`(무조건 `interrupt({"kind":"continue"})`). 조건부 엣지: 예산 소진 → `fallback`, 게이트 3번째 거부 → `fallback`, 시간 가드 → `pause`, LLM 호출 오류(노드 안에서 잡아 `llmError` 기록) → 후보 카드가 있으면 `fallback`·없으면 END(핸들러가 `FAILED`/503 `AI_UNAVAILABLE`로 변환), `finish`·질문 예산 소진·마지막 호출이면 `ask_planner`를 뺀 도구 목록. 턴 잠금·`AiQuota`·`SessionView` 변환·trace 생성은 그래프 밖 핸들러가 한다. 그래프는 `config={"configurable":{"thread_id": sessionId}}`, `durability="sync"`로 실행하고, 재개 전 `get_state`로 대기 중인 interrupt를 확인한다. | [§3.2](./03-api-contract.md), BE-Q19 |
| BE-AI-14 | 체크포인터는 `langgraph-checkpoint-aws`의 `DynamoDBSaver`를 별도 테이블 `HaruAgentCheckpoints`(PK/SK, TTL `ttl`, on-demand, PITR)에 연결한다. `consistent_read=True`, `ttl_seconds`는 AiSession TTL(30일) 이하, S3 오프로드는 끈다. 로컬에서는 `CHECKPOINT_DDB_ENDPOINT`로 에뮬레이터에 붙고, AWS에서는 빈 값으로 두어 코드가 `None`을 넘긴다. 의존성은 `AiCardFunction` 빌드에만 `==`로 고정해 넣는다(`langgraph`, `langgraph-checkpoint`, `langchain-core`, `langchain-openai`, `langgraph-checkpoint-aws`, `boto3>=1.43.64`). | [§2.1](./02-architecture.md), [§2.6](./02-architecture.md), BE-Q18, BE-Q20, BE-Q21 |
| BE-AI-15 | LangSmith 추적을 끈다. SAM과 docker compose에 `LANGSMITH_TRACING=false`, `LANGCHAIN_TRACING_V2=false`를 둘 다 명시하고 `LANGSMITH_API_KEY`는 두지 않는다. 핸들러는 그래프 실행을 `langsmith.tracing_context(enabled=False)`로 감싼다. | [§2.1](./02-architecture.md), BE-NFR-03 |

### 6.2.3 계획 (PLAN)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-PLAN-01 | `POST /plans`는 `Idempotency-Key` 헤더가 필수다. 같은 키·같은 본문이면 처음 만든 Plan을 반환하고, 본문이 다르면 409 `IDEMPOTENCY_CONFLICT`. 키는 `IDEM#{userId}#{key}`(TTL 24시간)로 저장한다. | [§3.3](./03-api-contract.md), T13 |
| BE-PLAN-02 | 입력 검증: `title` 1–40자, `summary` 1–120자, `reason` 1–300자, `estimatedMinutes` 10–240, `places` 1–3개(`name` 1–30, `activity` 1–60, `whyChosen` 0–120), `question` 1–80자, `authoring.story` 1–1,000자(두 모드 모두 필수). 실패 시 400 `VALIDATION_ERROR` + `details`(요청 본문 경로별 메시지). | [§2.5](./02-architecture.md), [§3.3](./03-api-contract.md) |
| BE-PLAN-03 | `authoring = { mode, durationMs, aiSessionId?, story }`. `metrics.authoringMode`, `durationMs`, `addedNotInSource`(사연 기준), `privacyInPublished`를 저장한다. `AI_EDITED`이고 `aiSessionId` 세션의 `ownerId`가 요청자와 같으면 세션에서 답변을 읽어 `addedNotInSourceOrAnswers`, `firstProposalNotInSource`, `deliveredNotInSource`, `agentSelfRepairs`, `missingFirst`, `missingDelivered`, `questionsAsked`, `questionsSkipped`, `privacyDetected`, `agentWaitMs`, `answerWaitMs`, `editMs`, `fieldsEditedAfterHandoff`, `modelCalls`, `agentMode`를 함께 저장한다. 소유자가 다르거나 세션이 없으면 세션을 무시한다. | [§3.3](./03-api-contract.md) |
| BE-PLAN-04 | `GET /plans?status=OPEN&limit&cursor`는 `PlanSummary` 목록을 `createdAt` 역순으로 반환한다. 기한 지난 `CLAIMED`도 `status: "OPEN"`으로 포함한다. | [§3.3](./03-api-contract.md), T16 |
| BE-PLAN-05 | `GET /plans/{planId}`는 `plan`, `isOwner`, `myClaim`, `claimable`을 반환한다. `claimable = !isOwner && myClaim == null && (OPEN 또는 기한 지난 CLAIMED)`. | [§3.3](./03-api-contract.md) |
| BE-PLAN-06 | 상세의 상태 표시: 기한 지난 `CLAIMED`는 현재 실행자가 아니면 `OPEN`, 현재 실행자 본인에게는 `CLAIMED` + `myClaim`. 다른 사람이 기한 내 이어받았으면 `CLAIMED`이고 실행자 정보는 응답에서 뺀다. | [§3.3](./03-api-contract.md) |
| BE-PLAN-07 | `COMPLETED` 계획은 소유자와 해당 실행자만 조회한다. 그 외는 404 `NOT_FOUND`. | [§3.3](./03-api-contract.md), [§2.8](./02-architecture.md) |
| BE-PLAN-08 | `metrics`는 소유자 응답에만 포함한다. 내부 속성(`claimerId`, `currentClaimId`, `dueAt`, `GSI*`, `version`)은 응답 직렬화 단계에서 허용 목록 방식으로 걸러낸다. | [§2.5](./02-architecture.md), [§3.3](./03-api-contract.md) |
| BE-PLAN-09 | Plan 갱신 시 `version`을 1 올리고, `status`가 바뀌면 `GSI1PK`를 함께 바꾼다. | [§2.6](./02-architecture.md) |

### 6.2.4 이어받기·포기 (CLAIM)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-CLAIM-01 | `POST /plans/{planId}/claims`는 TransactWriteItems로 Plan 조건부 갱신(소유자 아님, `OPEN` 또는 기한 지난 `CLAIMED`)과 Claim·ClaimLookup 생성을 한 번에 처리한다. 성공 201. | [§2.6](./02-architecture.md), G1 |
| BE-CLAIM-02 | 동시 요청 중 정확히 하나만 성공하고, 나머지는 409 `ALREADY_CLAIMED`. | G1, T3 |
| BE-CLAIM-03 | 같은 사용자의 중복 요청은 기존 ACTIVE Claim을 200으로 반환한다(Claim 1건). | [§2.6](./02-architecture.md), T4 |
| BE-CLAIM-04 | 소유자가 요청하면 409 `CANNOT_CLAIM_OWN_PLAN`. | [§2.6](./02-architecture.md) |
| BE-CLAIM-05 | `dueAt = claimedAt + CLAIM_DURATION_DAYS`(환경 변수, 기본 3일). 기한 지난 Claim을 대체할 때 같은 트랜잭션에서 이전 Claim을 `EXPIRED`로 바꾼다. | [§2.5](./02-architecture.md), T14 |
| BE-CLAIM-06 | `POST /claims/{claimId}/abandon`: Plan을 `OPEN`으로 되돌리고 `currentClaimId`/`claimerId`/`dueAt`을 제거, Claim은 `ABANDONED`, Record가 있으면 `photoStatus = DISCARDED`. 실행자가 아니면 403, 이미 종료된 Claim이면 409 `CLAIM_NOT_ACTIVE`. | [§2.6](./02-architecture.md), T6, T16 |
| BE-CLAIM-07 | `GET /me/claims?status=ACTIVE|COMPLETED`는 `{ claim, plan, record|null }` 목록을 반환한다. | [§3.1](./03-api-contract.md) |

### 6.2.5 경험 기록·완료 (REC)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-REC-01 | `PUT /claims/{claimId}/record`: 요청자 = 실행자, Claim `ACTIVE`, Plan `currentClaimId = claimId`일 때만 글(1–1,000자)을 저장한다. 완료 전까지 덮어쓸 수 있다. 실행자가 아니면 403, 그 외 조건 실패는 409 `CLAIM_NOT_ACTIVE`. | [§3.4](./03-api-contract.md), G3 |
| BE-REC-02 | `photo`가 있으면 `contentType`(jpeg/png)·`size`(≤ 10MB)를 검증하고 `photoKey = photos/original/{claimId}/{uuid}.{ext}`, `photoStatus = UPLOAD_PENDING`으로 저장한 뒤 presigned PUT URL(10분, `ContentType`·`ContentLength` 서명 포함)을 `upload`로 반환한다. | [§3.4](./03-api-contract.md) |
| BE-REC-03 | `photo` 없이 요청하면 진행 중인 사진 상태는 건드리지 않고 글만 갱신한다. | [§3.4](./03-api-contract.md) |
| BE-REC-04 | `POST /claims/{claimId}/record/photo`: 새 `photoKey`와 업로드 URL을 발급하고 `UPLOAD_PENDING`으로 바꾼다. 이전 키의 처리 결과는 무시된다. | [§3.4](./03-api-contract.md), T15 |
| BE-REC-05 | `GET /claims/{claimId}/record`는 `record`, `claimStatus`, `delivered`, `photoStatus`를 반환한다. 기록이 없으면 `record: null`, `photoStatus: "NONE"`. 포기·만료된 Claim도 실행자 본인은 조회할 수 있다. | [§3.4](./03-api-contract.md) |
| BE-REC-06 | `POST /claims/{claimId}/complete`(`mode: TEXT_ONLY`)는 트랜잭션 전에 요청자 = 실행자인지 확인한다(아니면 403). 완료는 공통 함수 `complete_claim(claimId, mode, ...)`로 Plan·Claim·Record 갱신과 InboxItem 생성을 하나의 트랜잭션에서 처리한다. | [§2.6](./02-architecture.md), G4 |
| BE-REC-07 | 완료 반복 호출은 멱등이다. 이미 완료된 Claim이면 기존 결과를 200으로 반환하고 `CompleteDuplicate` 메트릭을 올린다. 수신함 항목과 Record는 1건만 남는다. | G2, T5 |
| BE-REC-08 | `TEXT_ONLY` 완료 시 사진이 없었으면 `photoStatus = NONE`, 처리 중·실패였으면 `DISCARDED`. 이미 사진과 함께 완료된 뒤의 `TEXT_ONLY` 요청은 200, `hasPhoto: true`. | [§2.6](./02-architecture.md), [§3.4](./03-api-contract.md), T10 |
| BE-REC-09 | 완료 조건 실패 분기: Claim `COMPLETED` → 200 멱등, `ABANDONED`/`EXPIRED` 또는 `currentClaimId` 불일치 → 409 `CLAIM_NOT_ACTIVE`, 글 없음 → 400 `RECORD_REQUIRED`. | [§2.6](./02-architecture.md), T6, T7 |
| BE-REC-10 | 모든 트랜잭션은 공통 실패 처리를 따른다: `TransactionConflict`가 있으면 50·100·200ms 백오프로 최대 3회 재시도, 모두 `ConditionalCheckFailed`일 때만 `ConsistentRead`로 재조회해 분기, 판정 불가 시 503 `TRY_AGAIN`. | [§2.6](./02-architecture.md) |

### 6.2.6 사진 처리 (PHOTO)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-PHOTO-01 | S3 `ObjectCreated`(prefix `photos/original/`) → SQS `PhotoQueue` → `PhotoProcessorFunction`(batch 1, timeout 30s, 1024MB). visibility timeout = 6 × Lambda timeout, `maxReceiveCount` 3 → `PhotoDLQ`. | [§2.7](./02-architecture.md) |
| BE-PHOTO-02 | `s3:TestEvent`나 `Records` 없는 메시지는 정상 종료한다. S3 키는 `unquote_plus`로 디코딩한다. | [§2.7](./02-architecture.md) |
| BE-PHOTO-03 | Record를 `ConsistentRead`로 읽어 이미 전달됨·`DISCARDED`·`photoKey` 불일치면 무시하고(처리본 있으면 삭제) 종료한다. | [§2.7](./02-architecture.md), T10, T15 |
| BE-PHOTO-04 | 조건부로 `PROCESSING` 전환 → 매직 바이트(JPEG/PNG)·실제 크기 ≤ 10MB·최대 해상도 검사. 실패하면 `FAILED` + `photoError`, 재시도하지 않는다. | [§2.7](./02-architecture.md), T8 |
| BE-PHOTO-05 | EXIF 방향 반영 → 긴 변 1600px 축소 → EXIF/GPS 포함 모든 메타데이터 제거 → JPEG 재인코딩 → `photos/processed/{claimId}/{uuid}.jpg`. | [§2.7](./02-architecture.md), G7, T11 |
| BE-PHOTO-06 | 처리 후 `complete_claim(claimId, WITH_PHOTO, key, processedKey)`를 호출한다. `READY`는 별도로 쓰지 않고 완료 트랜잭션이 설정한다. 경합으로 조건이 실패하면 처리본을 지운다. | [§2.6](./02-architecture.md), [§2.7](./02-architecture.md) |
| BE-PHOTO-07 | 일시 오류는 예외로 SQS 재시도한다. `ApproximateReceiveCount >= 3`이면 예외 전에 조건부로 `FAILED`를 기록한다. 환경 변수 `FAULT_INJECT=photo`로 강제 예외를 낼 수 있다. | [§2.7](./02-architecture.md), T9 |
| BE-PHOTO-08 | 사진 버킷: 퍼블릭 차단, 원본 7일 수명 주기, CORS(API와 같은 Origin, `PUT`/`GET`, `Content-Type`). | [§2.7](./02-architecture.md) |
| BE-PHOTO-09 | 버킷 알림 순환 의존성을 피하기 위해 버킷 이름을 `${AWS::StackName}-photos-${AWS::AccountId}`로 고정하고 버킷에 `DependsOn: PhotoQueuePolicy`를 둔다. | [§2.7](./02-architecture.md) |

### 6.2.7 수신함·답장 (INBOX)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-INBOX-01 | `GET /inbox`는 요청자의 InboxItem을 `createdAt` 역순으로 반환한다. | [§3.5](./03-api-contract.md) |
| BE-INBOX-02 | `GET /inbox/{itemId}`는 `item`, `plan`, `record { letter, deliveredAt, photoUrl, photoCaption }`을 반환한다. `photoUrl`은 15분 presigned GET, `photoCaption`은 사진이 있을 때 마지막 장소 이름 + "에서". 소유자가 아니면 404. | [§3.5](./03-api-contract.md), T2 |
| BE-INBOX-03 | `POST /inbox/{itemId}/read` → 204, `read = true`. | [§3.5](./03-api-contract.md) |
| BE-INBOX-04 | `POST /inbox/{itemId}/reply`(`text` 1–100자)는 `attribute_not_exists(reply)` 조건으로 1회만 저장한다. 성공 201, 중복 409 `REPLY_ALREADY_SENT`. InboxItem 생성 시 `reply` 속성은 쓰지 않는다(응답에서만 `null`). | [§2.5](./02-architecture.md), [§3.5](./03-api-contract.md), T17 |

### 6.2.8 배포·인프라 (INFRA)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-INFRA-01 | `sam build && sam deploy --config-env demo`로 빈 계정에 스택 전체가 한 번에 생성된다. `samconfig.toml`에 `dev`, `demo` 환경을 둔다. | [§7.7](./07-development-plan.md) |
| BE-INFRA-02 | 스택은 웹 버킷(비공개) + CloudFront(OAC)를 만든다. SPA 라우팅을 위해 CloudFront에서 403/404를 `/index.html`(200)으로 돌려준다. | [§2.1](./02-architecture.md), [§2.10](./02-architecture.md) |
| BE-INFRA-03 | API CORS: Origin = CloudFront 도메인, `http://localhost:5173` / 헤더 `Authorization`, `Content-Type`, `Idempotency-Key` / 메서드 `GET`, `POST`, `PUT`, `OPTIONS`. | [§3](./03-api-contract.md) |
| BE-INFRA-04 | 출력값 `ApiUrl`, `UserPoolId`, `UserPoolClientId`, `WebBucketName`, `DistributionId`, `DistributionDomain`을 내보낸다(프론트 배포용). | [§2.10](./02-architecture.md) |
| BE-INFRA-05 | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY_PARAM`, `LLM_TOOL_CHOICE`, `LLM_PARALLEL_TOOL_CALLS`, `LLM_EXTRA_BODY`, `LLM_PROVIDER_LABEL`, `AGENT_MODE`, `CHECKPOINT_TABLE`, `CLAIM_DURATION_DAYS` 등 설정값은 파라미터/환경 변수로 분리한다. 로컬 전용 변수 중 SDK 표준 변수(`AWS_ENDPOINT_URL`, `AWS_EMF_ENVIRONMENT`)는 AWS 배포에서 정의하지 않고(SAM 환경 변수에 넣지 않음), 앱 전용 변수(`PUBLIC_S3_ENDPOINT`, `CHECKPOINT_DDB_ENDPOINT`)는 빈 값이면 코드가 `None`으로 처리한다. | [§3.2](./03-api-contract.md), [§7.7](./07-development-plan.md) |
| BE-INFRA-06 | Lambda별 IAM 권한은 필요한 테이블·버킷 prefix·큐·파라미터로 한정한다. `AiCardFunction`은 HaruTable `GetItem`/`PutItem`/`UpdateItem`에 `dynamodb:LeadingKeys` 조건(`AISESSION#*`, `AIQUOTA#*`), `HaruAgentCheckpoints`의 `GetItem`/`PutItem`/`Query`/`BatchGetItem`/`BatchWriteItem`, LLM API 키 파라미터의 `ssm:GetParameter`만 갖는다. Lambda는 VPC 밖에 둔다. `/ai/card-sessions*`에 HTTP API 경로별 스로틀을 건다. | [§2.8](./02-architecture.md), 보안 기본값, BE-Q8 |
| BE-INFRA-07 | SAM 템플릿에 `HaruAgentCheckpoints` 테이블(PK/SK, TTL `ttl`, on-demand, PITR)을 리소스로 두고, LLM API 키는 SSM 표준 SecureString(`/<app>/<stage>/llm/api-key`)으로 미리 만든다(값은 저장소에 넣지 않는다). | [§2.6](./02-architecture.md), [§3.2](./03-api-contract.md) |
| BE-INFRA-08 | 로컬 개발 환경: `docker compose up`으로 에뮬레이터(DynamoDB·S3·SQS·Cognito User Pool), HTTP 어댑터(payload 2.0 이벤트 변환, Floci User Pool JWKS와 dev JWT 공개키로 검증 후 `jwt.claims` 주입(`iss`·JWKS URL은 `LOCAL_JWT_ISSUER`·`LOCAL_JWKS_URL`), SQS 폴러)가 뜨고, init 스크립트가 테이블·버킷·큐·유저 풀·시드 사용자를 만든다. 같은 핸들러 코드를 쓰고 엔드포인트만 환경 변수로 바꾼다. 이미지 태그는 고정한다(`latest` 금지). | [§2.4](./02-architecture.md), BE-Q15–BE-Q17, BE-Q21 |

### 6.2.9 관측·측정 (OBS)

| ID | 요구사항 | 근거 |
|---|---|---|
| BE-OBS-01 | EMF 로그로 `ClaimConflict`, `CompleteDuplicate`, `StaleRequestRejected`, `PhotoProcessingMs`, `PhotoFailed`, `AiLatencyMs`, `AiFailure`, `AiInvalidOutput`, `AgentModelCalls`, `AgentTokens`, `AgentTurnMs`, `AgentQuestionsAsked`, `AgentGateRejected`, `AgentDegraded`, `AgentSelfRepairs`, `AgentCheckpointBytes`를 기록한다. 로컬에서는 `AWS_EMF_ENVIRONMENT=Local`로 stdout에 출력한다. | [§2.9](./02-architecture.md) |
| BE-OBS-02 | 알람: `PhotoDLQ` 메시지 수 > 0, API Gateway 5xx, Lambda Errors/Duration, `AgentTokens`. AWS Budgets 월 알림. | [§2.9](./02-architecture.md) |
| BE-OBS-03 | CloudWatch 대시보드에 API 오류, 사진 처리 시간, AI 지연, AI 세션 상태 분포, DLQ 깊이를 표시한다. | [§7.7](./07-development-plan.md) |
| BE-OBS-04 | `scripts/report.py`가 기한 내 경험 기록, 답장률, 모드별 작성 시간 중앙값, 모드별 `addedNotInSource`와 AI 세션 지표([§2.9](./02-architecture.md) 표), (선택) `check_invariants` 결과를 집계한다. `scripts/eval_agent.py`가 `tests/fixtures/stories.json` 15건으로 단발·레벨 0·에이전트를 비교한다. | [§2.9](./02-architecture.md) |
| BE-OBS-05 | `scripts/seed.py`가 데모 계정 3개(지연, 수현, 민준)와 예시 계획을 다시 만든다. 예시 계획은 대표 사례인 동네 산책만이 아니라 산책이 아닌 활동(장소 1곳 포함)도 담는다. | [§2.10](./02-architecture.md), [§7.7](./07-development-plan.md) |

## 6.3 백엔드 비기능 요구사항

| ID | 분류 | 요구사항 |
|---|---|---|
| BE-NFR-01 | 정합성 | 이어받기 1명 확정(G1), 완료·수신함 1건(G2), 종료된 Claim 쓰기 거부(G3), 완료 원자성(G4)을 T3–T7로 증명한다. |
| BE-NFR-02 | 보안 | 권한 판단은 JWT `sub`와 저장된 `ownerId`/`claimerId` 비교로만 한다([§2.8](./02-architecture.md) 표). 남의 리소스는 403 또는 404로 응답하고 데이터를 노출하지 않는다. |
| BE-NFR-03 | 개인정보 | 처리된 사진에 EXIF/GPS가 남지 않는다. 사진 접근은 presigned URL로만 한다. 로그에 토큰·사연 원문·사진 URL을 남기지 않는다. 사연·답변 원문은 로그·`trace`에 남기지 않고 유형과 개수만 남긴다. `AiSession`과 체크포인트(대화 원문 포함)는 소유자만 조회하고 TTL(30일 이하) 뒤 삭제된다. 사연은 AI 정리를 요청할 때만 외부 LLM 공급자로 보내고, LangSmith 등 다른 외부 서비스로는 보내지 않는다(BE-AI-15). |
| BE-NFR-04 | 응답 시간 | AI 세션 요청(생성·턴·조회) 각각이 30초(HTTP API 통합 상한) 안에 `SessionView` 또는 정해진 에러 코드로 응답한다. 턴 응답 p95 목표는 15초 이하다. |
| BE-NFR-05 | 오류 형식 | 모든 4xx/5xx는 `{ "error": { "code", "message", "details"? } }` 형식이다. 시간 값은 ISO 8601 UTC. |
| BE-NFR-06 | 재현성 | 새 스택 배포 + seed로 데모 환경을 언제든 다시 만들 수 있다. |
| BE-NFR-07 | 계약 일치 | 응답 형태가 프론트 MSW 목업과 일치한다. 계약 변경은 [§3](./03-api-contract.md)을 먼저 고치고 프론트에 알린 뒤 반영한다. |

## 6.4 프론트엔드 기술 요구사항

| ID | 요구사항 |
|---|---|
| FE-TECH-01 | React 18 + TypeScript + Vite, React Router, TanStack Query를 쓴다. |
| FE-TECH-02 | 인증은 `aws-amplify/auth`(Auth 모듈만)로 Cognito User Pool에 연결한다. API 호출에는 **ID 토큰**을 `Authorization: Bearer`로 붙인다(닉네임 클레임 때문). `VITE_COGNITO_ENDPOINT`가 있으면 그 주소의 User Pool(로컬 Floci Cognito)에 붙는다(지원 여부는 FE-Q8). |
| FE-TECH-03 | 환경 변수 `VITE_API_BASE_URL`, `VITE_AWS_REGION`, `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_CLIENT_ID`, `VITE_COGNITO_ENDPOINT`(로컬 백엔드 모드만, `dev`/`demo` 스택은 비움), `VITE_AUTH_MODE`(`cognito` 기본 / `dev-jwt` 로컬 백엔드 모드 전용), `VITE_USE_MOCK`. 값은 `.env.local`에 두고 저장소에는 `.env.example`만 올린다. `VITE_*` 값은 빌드 산출물에 들어가므로 비밀값을 두지 않는다. |
| FE-TECH-04 | `VITE_USE_MOCK=true`이면 MSW가 백엔드 계약과 같은 형태로 응답한다. 목업 데이터는 시안 인물(지연·수현·민준)을 쓴다. AI 정리 세션은 상태 머신(`WORKING`·`ASKING`·`READY`·`FAILED`)으로 흉내 내고, 쿼리 파라미터로 경로를 고른다([§2.10](./02-architecture.md)). |
| FE-TECH-05 | API 타입은 [§3](./03-api-contract.md)과 같은 이름으로 `src/api/types.ts`에 정의한다. |
| FE-TECH-06 | 스타일은 CSS Modules 또는 Tailwind 중 팀 합의로 하나만 쓴다. 디자인 토큰은 `src/styles`에 CSS 변수로 둔다. |
| FE-TECH-07 | 빌드 산출물은 백엔드 SAM 스택이 만든 S3 웹 버킷에 sync하고 CloudFront 캐시를 무효화한다. |
| FE-TECH-08 | 연동 모드는 세 가지다: MSW 목업(`VITE_USE_MOCK=true`), 로컬 백엔드(백엔드 docker compose, API `http://localhost:3000`(어댑터) 또는 Vite 프록시), `dev`/`demo` 스택(SAM 출력 `ApiUrl`). 환경 변수만 바꿔 전환하고 코드 분기는 두지 않는다(dev JWT 제외, FE-TECH-09). 모드별 값은 [§2.4.7](./02-architecture.md). |
| FE-TECH-09 | 로컬 백엔드 모드의 인증은 Floci Cognito(`http://localhost:4566`)의 시드 사용자로 로그인하는 것을 기본으로 한다. Amplify가 사용자 지정 엔드포인트를 지원하지 않으면(FE-Q8) `VITE_AUTH_MODE=dev-jwt`로 백엔드 어댑터의 dev JWT(`STAGE=local` 전용)를 받아 쓴다. 어댑터는 dev JWT 공개키도 신뢰하므로 dev JWT는 시드 사용자 ID 토큰과 같은 검증을 통과하고 `Authorization: Bearer` 방식도 같다. dev JWT 경로는 개발 빌드(`import.meta.env.DEV`)에서만 동작하고 배포 빌드에는 들어가지 않는다. |

## 6.5 프론트엔드 기능 요구사항

제목의 절 번호(§)는 화면별 상세 요구사항, 화면 번호는 [§5.1](./05-screens.md) 표의 `#`이다.

### 6.5.1 공통 (COMMON)

| ID | 요구사항 | 근거 |
|---|---|---|
| FE-COM-01 | 하단 탭(둘러보기 / 내 하루 / 수신함)은 목록형 화면에만 보인다. | [§5.1](./05-screens.md) |
| FE-COM-02 | 헤더 오른쪽 편지 아이콘과 하단 탭의 수신함에 `GET /me`의 `unreadInboxCount > 0`이면 주황 점을 표시한다. | [§5.2.6](./05-screens.md) |
| FE-COM-03 | 401 `UNAUTHORIZED`를 받으면 `/login?redirect={현재 경로}`로 보내고, 로그인 후 그 경로로 돌아온다. | [§5.1](./05-screens.md) |
| FE-COM-04 | 공통 에러 처리: `NOT_FOUND` → "찾을 수 없어요" 후 둘러보기/수신함, `FORBIDDEN` → 안내 후 둘러보기, `VALIDATION_ERROR` → `details`의 경로별 메시지를 해당 입력칸에 표시, `TRY_AGAIN` → 같은 요청 1회 재시도 후 실패 시 토스트. | [§3.7](./03-api-contract.md) |
| FE-COM-05 | 모든 API 호출은 토큰을 붙이는 공통 클라이언트를 거친다. 토큰 없이 API를 호출하는 경로가 없어야 한다. | [§7.7](./07-development-plan.md) |
| FE-COM-06 | 서버 시간(UTC ISO 8601)은 한국 시간(Asia/Seoul)으로 표시한다. | [§3](./03-api-contract.md) |

### 6.5.2 로그인·회원가입 (AUTH) — 화면 0

| ID | 요구사항 |
|---|---|
| FE-AUTH-01 | 이메일·비밀번호로 로그인한다. |
| FE-AUTH-02 | 회원가입은 이메일·비밀번호·닉네임(필수)을 받는다. 백엔드가 즉시 자동 확인하므로 인증 코드 화면이 없고, 가입 성공 후 바로 로그인한다. 자동 확인(PreSignUp 트리거)은 로컬 백엔드 모드에서 동작하지 않으므로 이 흐름은 `dev` 스택에서 확인하고, 로컬에서는 시드 사용자로 로그인한다. 닉네임은 앞뒤 공백을 뺀 1–20자이며, 백엔드 PreSignUp 트리거가 같은 규칙으로 거절한다(2026-11-27, BE-Q139, 배포 뒤 확인). |
| FE-AUTH-03 | 로그인하지 않은 사용자가 보호된 경로에 들어오면 로그인 화면으로 보낸다(FE-COM-03과 같은 redirect 규칙). |

### 6.5.3 둘러보기 (BROWSE) — 화면 1, §5.2.1

| ID | 요구사항 |
|---|---|
| FE-BRW-01 | `GET /plans?status=OPEN` 결과를 최신순 카드로 표시한다. 카드: "이어받기 가능" 배지, "{계획자}의 하루", 장소 수만큼의 번호 원, 제목, `summary` 2줄 말줄임, `약 {n}분 · 장소 {k}곳`(티켓 모양, [§5.3](./05-screens.md)). 장소 1곳과 활동 종류에 상관없이 같은 카드로 보인다. |
| FE-BRW-02 | 목록이 비면 "아직 남겨진 하루가 없어요"와 하루 남기기 유도 버튼을 보여준다. 안내 문구는 산책을 전제로 하지 않는다("하지 못한 하루가 있다면 첫 하루를 남겨 보세요.", [§5.2.7](./05-screens.md)). |
| FE-BRW-03 | "취소된 하루 남기기" 버튼으로 사연 입력 화면에 간다. |
| FE-BRW-04 | 내가 남긴 하루도 목록에 보일 수 있다. 이어받기 가능 여부는 상세의 `claimable`로만 판단한다. |

### 6.5.4 하루 들여다보기·이어받기 (PLAN) — 화면 2, 2-1, §5.2.2

| ID | 요구사항 |
|---|---|
| FE-PLN-01 | 계획자 닉네임, 취소한 이유(`reason`), 방문할 장소 타임라인(장소·하고 싶었던 일·고른 이유)을 보여준다. 장소가 1곳이어도 어색하지 않게 항목 하나로 보인다. 이어받을 수 있는 하루·내가 이어받은 하루·내가 남긴 하루에서는 방문 질문(`question`)도 보여 준다. |
| FE-PLN-02 | 상세 분기는 위에서부터 먼저 맞는 하나만 적용한다: 404 → "이 하루는 더 이상 볼 수 없어요" / `myClaim.status === 'ACTIVE'` → "내가 이어받은 하루" + "내 하루로 가기" / `isOwner` → "내가 남긴 하루" + 상태만 / `claimable` → "이 하루 이어받기" / `status === 'CLAIMED'` → 2-1 안내 / `COMPLETED` → 완료 배지 읽기 전용 / 그 외 → "다른 하루 둘러보기". |
| FE-PLN-03 | 이어받기는 `POST /plans/{planId}/claims`. 201 또는 200이면 `/me`로 이동한다. 요청 중에는 버튼을 비활성화한다. |
| FE-PLN-04 | 409 `ALREADY_CLAIMED`면 페이지 이동 없이 같은 화면에 2-1 안내 박스("이미 다른 사람이 이어받았어요" + "다른 하루 둘러보기")를 띄운다. |
| FE-PLN-05 | 409 `CANNOT_CLAIM_OWN_PLAN`은 토스트로 처리한다. |

### 6.5.5 하루 남기기 (CREATE) — 화면 3 ~ 3-4, §5.2.3

| ID | 요구사항 |
|---|---|
| FE-CRT-01 | 사연 입력(1–1,000자)과 "집 주소나 개인 정보는 적지 말아주세요" 안내, 외부 AI 전송 안내("사연이 외부 AI 서비스(<공급자명>, <처리 국가>)로 전송되고 공급자 정책에 따라 최대 N일 보관될 수 있어요", FE-Q6)를 보여준다. "AI와 함께 정리하기"와 "직접 작성하기" 두 버튼을 둔다. 입력 예시(placeholder)는 일상 활동의 폭을 보이는 문구로 쓴다([§5.2.7](./05-screens.md)). |
| FE-CRT-02 | AI 경로는 세션 API를 쓴다. `POST /ai/card-sessions { story }` → `SessionView`. `sessionId`와 마지막 `turn`을 보관하고, 다음 턴은 `POST /ai/card-sessions/{sessionId}/turns { expectedTurn: 마지막 turn, answer?, finish? }`로 보낸다. 화면 분기는 응답 `status`(`WORKING`·`ASKING`·`READY`·`FAILED`)로만 한다. 생성 응답이 바로 `READY`인 경우(레벨 0)도 처리한다. `READY`면 `card`를 폼 초기값으로 그대로 쓰고(`null`은 빈칸) 모드는 `AI_EDITED`. |
| FE-CRT-03 | AI와 함께 정리하기 화면(3-1): `trace[]` 단계 칩(`step` 순서대로 켬), 질문 말풍선(`ASKING`), "이대로 카드 받기", 카드 미리보기(`flags`에 `NOT_IN_SOURCE`가 없으면 "원문 대조 통과" 배지), "AI가 바꾼 것" 메모(`notes[].reason` + 출처 칩 `STORY` → "원문", `ANSWER` → "내 답변"), "폼에서 다듬기". `flags[].path` 연결은 폼(3-2)에 그대로 둔다: `NOT_IN_SOURCE` → "원문에 없던 내용이에요, 확인해 주세요", `MISSING` → "직접 채워주세요", `PRIVACY` → "공개하기 어려운 정보일 수 있어요". |
| FE-CRT-04 | AI 실패(`FAILED`/503 `AI_UNAVAILABLE`(LLM API 오류·타임아웃이고 후보 카드 없음), 502 `AI_INVALID_OUTPUT`, 429 `AI_QUOTA_EXCEEDED`, 세션 404, 타임아웃, 5xx) 시 사연을 유지하고 "AI 카드를 만들지 못했어요. 직접 정리해 주세요" 안내 후 빈 폼으로 이동한다. 폼 상단에 사연을 참고용으로 보여준다. 모드는 `MANUAL`이고 `aiSessionId`는 보내지 않는다. AI 세션 요청의 클라이언트 타임아웃은 서버 상한 30초보다 길게 잡고, `turns`의 네트워크 오류·타임아웃은 `GET`으로 한 번 재동기화한 뒤 판단한다. |
| FE-CRT-05 | 직접 작성 경로: AI 호출 없이 폼으로 가고, `summary` 기본값을 사연 앞부분(120자 이내)으로 채운다. 모드는 `MANUAL`. |
| FE-CRT-06 | 폼 검증: 제목 1–40, `summary` 1–120, 취소한 이유 1–300, 예상 소요 시간 10–240분, 장소 1–3곳(이름 1–30, 하고 싶었던 일 1–60, 고른 이유 0–120), 방문 질문 1–80(1개 필수). 사연은 두 모드 모두 필수. |
| FE-CRT-07 | 장소 추가 화면(3-3)에서 장소 이름·하고 싶었던 일·고른 이유를 입력해 방문할 장소에 추가한다(최대 3곳). 버튼과 제목에 '동선' 표현을 쓰지 않는다. |
| FE-CRT-08 | 작성 상태(사연, `sessionId`, 마지막 `turn`, READY 카드, `flags`, `notes`, 폼 값, `startedAt`, `idempotencyKey`)를 하나로 묶어 `sessionStorage`에 저장한다. 하위 경로 이동·새로고침에도 유지하고, 공개 성공 시 삭제한다. |
| FE-CRT-09 | `startedAt`은 사연 입력 화면에 처음 들어올 때 한 번만 기록한다. 공개 요청에 `authoring { mode, durationMs, aiSessionId?, story }`를 포함한다. `aiSessionId`는 `AI_EDITED`일 때만 넣는다. |
| FE-CRT-10 | 공개는 `POST /plans` + `Idempotency-Key`. 키는 공개 버튼을 누를 때 본문과 함께 만들고, 같은 본문 재전송 때만 재사용한다. 폼이 바뀌면 새 UUID. 409 `IDEMPOTENCY_CONFLICT`면 새 키로 1회 재요청한다. |
| FE-CRT-11 | 공개 성공 시 공개 완료 화면(3-4, `/plans/:planId/published`)과 "둘러보기로 가기"를 보여준다. |
| FE-CRT-12 | 질문 답변(`ASKING`): `question.text`와 `reason`을 말풍선으로 보여준다. 선택지 → `answer { questionId, choice }`, `allowFreeText === true`일 때만 직접 입력(1–100자) → `answer { questionId, text }`, "건너뛰기" → `answer { questionId, skipped: true }`(그 필드는 `MISSING`으로 남음). "이대로 카드 받기" → `finish: true`(`answer` 없이 보내면 현재 질문은 건너뜀). |
| FE-CRT-13 | 턴 진행·재동기화: `WORKING`이면 `answer` 없이 `turns`를 자동으로 보내고, `WORKING`을 연속 2회 받으면 다음 요청에 `finish: true`를 넣고, 그 뒤 `WORKING`이 와도 `finish: true`로 이어서 보낸다. 409 `AI_SESSION_BUSY` → 2초 뒤 `GET /ai/card-sessions/{sessionId}`로 다시 맞춘다. 재동기화 `GET`이 보낸 `expectedTurn`과 같은 `turn`의 `WORKING`이면 2초 간격으로 `GET`을 반복하고, 이 응답은 연속 `WORKING` 횟수에 넣지 않는다(잠금 시간 30초가 지나도 같으면 `turns`를 다시 보낸다). 409 `AI_SESSION_CLOSED` → `GET` 후 현재 상태를 보여준다. 3-1 진입 시 `sessionId`가 있고 READY 카드가 없으면 `GET`으로 세션을 복구한다(새로고침 포함). |
| FE-CRT-14 | 메모 "다시 넣기": `action === 'REMOVED'` 메모에 버튼을 두고, 누르면 그 항목을 폼에 되살리며 `PRIVACY` 또는 `NOT_IN_SOURCE` 경고를 함께 붙인다(복원할 값·유형·위치는 FE-Q7). |

### 6.5.6 내 하루·포기 (ME) — 화면 4, 4-1, §5.2.4

| ID | 요구사항 |
|---|---|
| FE-ME-01 | `GET /me/claims?status=ACTIVE`로 이어받은 하루를 보여준다. 없으면 둘러보기 유도. |
| FE-ME-02 | 기한 문구: 기한 전 "{M}월 {D}일까지 다녀온 이야기를 보내주세요.", 기한 후 "기한이 지났어요. 다른 사람이 이어받기 전까지는 보낼 수 있어요." 기한 문구 옆에 KST 기준 남은 날 칩("D-{n}" / "D-day" / "기한 지남")과, 카드 안에 진행 단계 막대(이어받음 → 다녀오기 → 경험 기록 보내기)를 둔다([§5.2.4](./05-screens.md)). |
| FE-ME-03 | "다녀온 이야기 쓰기"는 `record.photoStatus`에 따라 이동한다: 기록 없음/`NONE` → 작성, `UPLOAD_PENDING`/`PROCESSING` → 보내는 중, `FAILED` → 사진 처리 실패. |
| FE-ME-04 | 포기: 확인 화면("계속 이어가기" / "이어받기 포기") → `POST /claims/{claimId}/abandon` → 둘러보기. 409 `CLAIM_NOT_ACTIVE`면 "이미 종료된 이어받기예요" 안내 후 새로고침. |

### 6.5.7 경험 기록·사진·완료 (REC) — 화면 5 ~ 5-4, 8, §5.2.5

| ID | 요구사항 |
|---|---|
| FE-REC-01 | 작성 화면 상단에 계획 제목, "{계획자 닉네임}에게", 하루 카드의 방문 질문을 보여준다. |
| FE-REC-02 | 진입 시 `GET /claims/{claimId}/record`로 서버 글을 먼저 채우고, 없을 때만 `localStorage` 임시 글을 쓴다. 임시 글은 입력 중 저장하고, 전송 완료·종료 안내 시 삭제한다. |
| FE-REC-03 | 글 1–1,000자. 사진은 JPEG/PNG, 10MB 이하, 1장(선택). 형식·크기는 클라이언트에서 먼저 검사한다. |
| FE-REC-04 | 사진 있음: `PUT /record { letter, photo: { contentType, size } }` → 응답 `upload`로 `fetch(upload.url, { method: 'PUT', body: file, headers: upload.headers })` → 보내는 중 화면. 업로드 실패는 사진 처리 실패와 같게 처리한다. `upload.url`의 호스트·경로는 바꾸지 않는다(로컬 백엔드 모드는 `http://localhost:4566` 호스트·경로 방식 주소로 서명되고, host도 서명에 들어간다). |
| FE-REC-05 | 사진 없음 또는 "글로 완료하기": 항상 `PUT /record { letter }` 후 `POST /complete { mode: 'TEXT_ONLY' }`. 400 `RECORD_REQUIRED`면 `PUT /record` 후 1회 재시도. 네트워크 오류·503 `TRY_AGAIN`은 같은 요청 1회 자동 재시도. |
| FE-REC-06 | 보내는 중(5-1): `GET /record`를 2초 간격으로 폴링한다. 판정 순서: `delivered` → 완료 / `claimStatus`가 `ABANDONED`·`EXPIRED` 또는 403·404·409 → 화면 8 / `photoStatus === 'FAILED'` → 실패 화면 / 그 외 계속 폴링. |
| FE-REC-07 | 폴링 60초가 지나도 처리 중이면 "글로 완료하기"를 강조한다. `UPLOAD_PENDING`이 30초 넘게 그대로면(새로고침 후 돌아온 경우 포함) 실패 화면을 보여준다. |
| FE-REC-08 | 실패 화면(5-2): 작성한 글을 유지하고 "사진 바꾸기" / "글로 완료하기"를 제공한다. |
| FE-REC-09 | 사진 교체(5-3): `POST /record/photo { contentType, size }` → 새 URL로 업로드 → 보내는 중. |
| FE-REC-10 | 전송 완료(5-4) 문구는 서버 결과로 정한다: `complete` 응답의 `hasPhoto`, 폴링 경로는 `photoStatus === 'READY'`. 새로고침 시 `GET /record`로 다시 판단한다. |
| FE-REC-11 | 종료된 이어받기(화면 8): `PUT /record`, `POST /record/photo`, `POST /complete`의 409 `CLAIM_NOT_ACTIVE` 또는 폴링 판정에서 띄운다. "이 이어받기는 종료되었어요" + 작성 글 복사 + "다른 하루 둘러보기". `photoStatus = DISCARDED`는 종료 판단에 쓰지 않는다. |

### 6.5.8 수신함·돌아온 하루·답장 (INBOX) — 화면 6 ~ 7-1, §5.2.6

| ID | 요구사항 |
|---|---|
| FE-INB-01 | `GET /inbox`를 최신순으로 표시한다. `read === false`면 "새 편지" 배지 + 주황 점, 아니면 "읽은 기록". `hasPhoto`에 따라 "사진과 경험 기록을 보냈어요" / "경험 기록을 보냈어요". |
| FE-INB-02 | 상세 진입 시 `POST /inbox/{itemId}/read`를 호출하고 수신함 목록과 `GET /me` 캐시를 무효화한다. |
| FE-INB-03 | 상세: 사진(있으면, `record.photoUrl`) + `photoCaption`, "내가 남긴 계획"(베이지, `plan.summary`) / "{실행자}의 경험 기록"(연녹색, `record.letter`) 2단 카드. |
| FE-INB-04 | 사진 URL이 만료돼 이미지 로드가 실패하면 상세를 다시 조회한다(1회). |
| FE-INB-05 | 한 줄 답장 1–100자 → `POST /inbox/{itemId}/reply`. 성공 또는 409 `REPLY_ALREADY_SENT`면 "보낸 답장" 읽기 전용(7-1)과 "수신함으로" 버튼을 보여준다. 이미 `reply`가 있는 항목은 처음부터 7-1로 보인다. |

## 6.6 프론트엔드 비기능 요구사항

| ID | 분류 | 요구사항 |
|---|---|---|
| FE-NFR-01 | 반응형 | 360–480px 폭에서 시안과 같은 배치. 그보다 넓으면 최대 폭 480px 가운데 정렬. |
| FE-NFR-02 | 디자인 | [§5.3](./05-screens.md) 토큰과 레이아웃 패턴(큰 제목 2줄 + 회색 보조 문구 + 하단 고정 주 버튼, 번호 원 타임라인, 상태 배지)을 공통 컴포넌트로 만든다. 시안이 없는 화면(0, 3, 3-1, 8)도 같은 패턴을 따른다. 3-1(AI와 함께 정리하기)은 큰 제목 + 단계 칩 + 질문 말풍선 + 카드 미리보기·메모 + 하단 고정 주 버튼("폼에서 다듬기"), 보조 버튼 "이대로 카드 받기"로 구성한다. |
| FE-NFR-03 | 중복 요청 방지 | 상태를 바꾸는 버튼(이어받기, 공개, 포기, 완료, 답장, AI 질문 답변·건너뛰기)은 요청 중 비활성화한다. "이대로 카드 받기"는 `WORKING` 자동 요청 중에도 누를 수 있고, 다음 요청에 `finish`를 예약만 한다(중복 예약 방지). |
| FE-NFR-04 | 데이터 보존 | 하루 남기기 입력과 AI 세션 ID는 새로고침에도 유지되고(sessionStorage, 세션 상태는 `GET`으로 복구), 경험 기록 글은 실패·새로고침에도 유지된다(서버 저장 + localStorage). |
| FE-NFR-05 | 보안 | 토큰은 Amplify가 관리하는 저장소에만 둔다(dev JWT는 개발 빌드의 메모리에만). 로그·에러 메시지에 토큰과 presigned URL을 출력하지 않는다. LLM API 키 같은 비밀값은 프론트 환경 변수와 번들에 두지 않는다. 사용자 입력과 AI 응답(질문문·선택지·메모·단계 칩)은 React 기본 이스케이프로만 렌더링한다(`dangerouslySetInnerHTML` 금지). |
| FE-NFR-06 | 접근성 | 입력칸마다 라벨, 에러 메시지는 입력칸과 연결(`aria-describedby`), 버튼은 키보드로 동작. |
| FE-NFR-07 | 계약 일치 | MSW 핸들러 응답은 [§3](./03-api-contract.md) 예시와 같은 형태다. 계약이 바뀌면 타입과 핸들러를 같은 PR에서 고친다. 계약 일치의 판정은 `dev` 스택 응답으로 하고, 로컬 백엔드 모드의 동작은 근거로 쓰지 않는다. |

## 6.7 인수 기준

### 백엔드

- T1–T22([§7.6](./07-development-plan.md))이 실제 AWS에 SAM으로 배포한 스택에서 통과한다. 로컬 Docker 환경의 통과는 인수 기준으로 치지 않는다. T3·T5는 `concurrent.futures`로 실제 API를 동시에 호출하고 결과 로그를 보관한다.
- [§7.7](./07-development-plan.md) 완료 기준의 모든 항목을 만족한다.
- 90초 시연 시나리오가 배포 환경에서 동작한다: 지연 사연 입력 → AI와 함께 정리(질문 1개) → 공개 → 수현·민준 동시 이어받기(한 명만 확정) → 사진+기록 전송 → 지연 수신함·답장.
- 에이전트 그래프(6b)가 리허설 전에 T18–T22를 통과하지 못하면 `AGENT_MODE=pipeline`(레벨 0)으로 출시한다([§7.3](./07-development-plan.md) 6b단계).

### 프론트엔드

[§7.7](./07-development-plan.md) 완료 기준을 그대로 쓴다.

- [ ] 데모 계정 3개로 90초 시연 시나리오가 끊김 없이 동작
- [ ] 수현·민준 동시 이어받기 시 한 명만 확정, 다른 쪽은 "이미 다른 사람이 이어받았어요"
- [ ] 완료 버튼을 여러 번 눌러도 수신함 항목 1건
- [ ] 사진 처리 실패 시 글 유지, 사진 교체 또는 글로 완료 가능
- [ ] 사진 없이 "글로 완료" 시 바로 전송(`PUT /record` → `complete`)
- [ ] AI 정리 실패(`FAILED`, 한도 초과 포함) 시 사연 유지, 직접 작성으로 전환
- [ ] AI 정리 중 새로고침해도 세션 복구
- [ ] 질문 건너뛰기와 "이대로 카드 받기"로 언제든 폼 진입
- [ ] 공개 요청에 `authoring.mode`, `durationMs`, `story` 포함
- [ ] 하루 남기기 도중 새로고침해도 입력값과 측정 시작 시각 유지
- [ ] 360–480px 폭에서 시안과 같은 배치
- [ ] CloudFront 배포 URL에서 동작, 토큰 없이 API를 호출하는 경로 없음

### 일상 활동 일반화 (백엔드·프론트엔드 공통)

서비스는 산책 전용이 아니므로, 대표 사례(동네 산책)와 다른 활동에서도 같은 요구가 성립해야 한다. 새 요구사항 ID는 만들지 않고 위 BE-AI-03, BE-PLAN-02, BE-OBS-05, FE-BRW-01·02, FE-PLN-01, FE-CRT-01·07, FE-REC-01의 확장으로 확인한다. 항목마다 상태를 적는다(2026-11-27 기준). 판정 방법은 [§7.5](./07-development-plan.md)의 '다양한 일상 활동 시나리오 검증'이다.

- [ ] 장소 1곳 계획(예: 전시회 한 곳)을 만들고 공개할 수 있고, 목록 카드는 `장소 1곳`, 상세는 항목 하나의 방문할 장소로 보인다. (BE-PLAN-02, FE-BRW-01, FE-PLN-01. 확인 대상은 프론트 목업·단위 테스트이고 AWS 판정은 아직 하지 않았다)
- [ ] 걷지 않는 활동(카페에서 앉아 있기, 전시 관람, 사진 촬영 등)의 사연도 Fake LLM·오프라인 평가에서 `NOT_IN_SOURCE`·`PRIVACY` 규칙이 같게 동작하고, 질문과 선택지가 산책을 전제하지 않는다. (BE-AI-03, BE-AI-06. Fake 시나리오 단위 테스트까지가 이번 범위이고 실제 LLM 평가는 계획이다)
- [ ] 시드와 목업에 대표 사례 외 활동 예시가 있어 데모 계정으로 같은 흐름(이어받기 → 경험 기록 → 수신함 → 답장)을 볼 수 있다. (BE-OBS-05, FE-TECH-04)
- [ ] 고정 UI 문구(로그인·둘러보기·빈 상태·placeholder·종료 안내)에 '산책'·'동선'이 없다. 비공개 장소 선택지·메모는 "장소에서 빼기"·"비공개 장소라 뺐어요." 값이다. (FE-BRW-02, FE-CRT-01·07, FE-REC-01. 확인 대상은 프론트 단위 테스트)
- [ ] 위 확인이 `dev`·`demo` 스택에서도 같게 나온다. (실제 AWS 판정 대기)
