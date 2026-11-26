# Implementation Plan: backend-stage6b-ai-agent

## Overview

백엔드 6b단계(AI 하루 카드 LangGraph 에이전트)를 `feat/be-6b-ai-agent`(기준 `feat/be-6a-ai-pipeline` `668e49a`, 별도 worktree) 위에 `backend/` 아래 Python 3.12로 구현한다. 근거는 같은 폴더의 `requirements.md`(승인), `design.md`(조건부 승인 뒤 보완, §1–§25)다.

작업 묶음
- **묶음 A (작업 1–19)**: 승인·AWS 없이 하는 구현과 검증. Fake 채팅 모델, 로컬 HTTP 스텁(실제 `ChatOpenAI`), moto, docker compose(Floci)로 검증한다.
- **공급자 검증 (작업 20)**: 개발용 공급자 NVIDIA NIM(BE-Q6 개발용 결정)으로 합성 사연만 보낸다. 20.1은 끝났다. 6b 구현을 멈추지 않고 별도 작업으로 관리한다.
- **별도 승인 그룹 (작업 21–25)**: 프론트 리뷰, AWS 판정, 운영 공급자 결정, 4·5단계 통합 회귀, PR 생성. 각각 승인 뒤에만 한다.

공통 규칙
- API 계약(docs/03)과 프론트엔드 코드는 바꾸지 않는다. 계약 해석이 필요한 결정은 BE-Q로 남긴다. `claim_service.py`, `common/ddb.py`의 `table`·`transact_with_retry`, `fidelity.py`·`privacy.py`의 판정 규칙은 바꾸지 않는다.
- **레벨 0(`AGENT_MODE` 미설정·`pipeline`)은 6a와 같게 동작한다.** 에이전트 코드는 `agent` 분기에서만 쓰이고, 6a 단위·로컬 테스트가 그대로 통과해야 한다.
- 6a의 비종료 500 `NON_TERMINAL_SESSION`은 `agentMode = PIPELINE`(또는 없음) 세션의 비정상 상태에만 유지한다. `AGENT` 세션은 재개·모드 전환 규칙을 따른다(design §13).
- 실제 외부 LLM 호출은 공급자 검증 그룹(작업 20)과 그 그룹이 실행하는 스크립트에서만 한다. 사연은 `tests/fixtures/stories.json`의 합성 사연만. 일반 회귀의 기본값은 Fake 모델이다. 단위 테스트는 외부 소켓 차단(`tests/unit/conftest.py`)을 유지한다.
- API 키와 `.env`는 출력·커밋·push하지 않는다. 결과 파일(`test-results/`)은 gitignore다.
- AWS 배포·리소스 생성·변경, AWS 통합 테스트 실행은 하지 않는다. AWS 대상 테스트는 작성하고 `--collect-only`까지 확인한다.
- 속성 기반 테스트는 **P29–P36(6a 유지)과 P37–P48(6b)이 모두 필수**다. Hypothesis 최소 100회(상태 기계·장애 주입 속성은 50회 이상 + 고정 `@example`), 태그 `Feature: backend-stage6b-ai-agent, Property {n}`. 실패 사례는 `@example`로 고정한다.
- **장애 복구 F0–F17(design §7)은 모두 필수 테스트**다.
- 회귀 기준: 6a 단위 **717건**(공급자 확인 스크립트 테스트를 더한 현재 722건), 로컬 통합 **23건**. 모든 Checkpoint에서 필수다. 6b로 기대값이 바뀌는 6a 테스트는 목록·근거를 남기고 불변식을 약화하지 않는다(design §20.6).
- 미결·임시 항목은 코드 주석과 PR에 번호를 남긴다: BE-Q105·106·108·109·114·121·124·125·126(임시), BE-Q127·BE-Q128(미결). BE-Q6 운영분·BE-Q7·BE-Q10·BE-Q11·BE-Q13은 결정하지 않는다.
- **Git**: 작업 브랜치 `feat/be-6b-ai-agent`에만 push한다. 논리 단위와 Checkpoint마다 테스트 → commit → push. push 전에 민감정보(키·자격 증명·실제 사연)와 불필요한 산출물(`.env`, `.aws-sam/`, `.venv/`, `test-results/`, `__pycache__`)이 없는지 확인한다(아래 "push 전 확인"). force push·rebase·squash를 하지 않는다. 다른 브랜치와 PR #1–#8은 바꾸지 않는다. PR 생성·Ready for Review·병합은 작업 25(별도 승인).
- 의존성은 각 작업의 `선행:` 줄과 끝의 Task Dependency Graph로 적는다.

push 전 확인(각 Checkpoint와 push마다)
1. `git diff --cached --name-only`에 `.env`, `test-results/`, `.aws-sam/`, `.venv/`, `*.pyc`가 없다.
2. 추가 줄에서 키 패턴(`nvapi-` + 20자 이상, `sk-` + 20자 이상, `AKIA`/`ASIA`, `-----BEGIN`, `eyJ…\.`)과 로컬 경로가 없다. 테스트용 가짜 키는 `-test-`·`not-a-real`을 포함한다.
3. 실제 `.env`의 키 값이 diff에 0회 나온다(값을 출력하지 않고 개수만 센다).

## Tasks

### 묶음 A: 승인·AWS 없이 하는 작업

- [x] 1. AiSession 잠금·커밋 서비스 (`domain/ai_session_service.py`, `common/validation.py`)
  - 선행: 없음
  - [x] 1.1 새 속성(design §3.1: `lockToken`, `lockedUntil`, `lockedAt`, `turnAttempts`, `turnRuns`, `pendingResume`, `question`, `questionAskedAt`, `askedPaths`, `checkpointId`, `modelCallsReserved`, `tokenCharged`, `tokenInEstimated`, `checkDraftCount`, `gateRejects`, `questionsAsked`, `bestCard`, `recoveries`, `checkpointBytesMax`)과 에이전트 생성 항목(`turn 0`, `WORKING`, 잠금) 빌더. 6a `build_session_item`·`serialize_session_view` 동작 불변(레벨 0 항목 바이트 비교).
    - _Requirements: 2.4, 2.5 · BE-Q100_
  - [x] 1.2 `acquire_lock(…)`: design §5.2 조건식·갱신식(소유자·TTL·turn·상태·잠금 만료, 답변/finish 조건, `pendingResume if_not_exists`, `finishRequested`, `turnRuns list_append`, `ADD turnAttempts`, `ALL_NEW`). 결과: 성공 / 조건 실패 / 불확실.
    - _Requirements: 4.1–4.4, 4.6 · BE-Q93, BE-Q96, BE-Q110, BE-Q118_
  - [x] 1.3 잠금 실패 분기(design §5.1 ⑥): 다시 읽어 404 → 200 → 409 CLOSED → 409 BUSY → 400/500.
    - _Requirements: 3.2, 4.5_
  - [x] 1.4 `commit_turn(…)`: design §5.3(조건 `lockToken`·`turn`, `turn + 1`, 상태별 필드, `answers` 추가, `tokenCharged` 보정 ADD, 잠금·`pendingResume`·`turnRuns` 제거). `verify_commit`(강한 일관성 확인 조회), 조건 실패 재조회 분기.
    - _Requirements: 5.1–5.5 · BE-Q89 방식_
  - [x] 1.5 `release_lock(…)`(design §9.3 중단 해제)과 `close_deterministically` 저장 함수(design §7.1, 잠금 조건).
    - _Requirements: 7.4, 7.6, 12.3 · BE-Q113, BE-Q121_
  - [x] 1.6 상태 기반 검증(design §5.4 표): `questionId`·`choice ∈ options`·`allowFreeText`·`ASKING` 무입력·`WORKING` 답변(멱등/400).
    - _Requirements: 3.3–3.6 · BE-Q109_
  - [x] 1.7 단위 테스트 (`tests/unit/test_agent_lock.py`, moto): 조건식 각 항목을 하나씩 깨뜨린 사례, 만료 경계(`lockedUntil = now`), `pendingResume` 첫 답 우선, `turnRuns` 순서, 커밋 조건 실패·불확실(Stubber/주입), 중단 해제, 6a 레벨 0 항목 불변.
    - _Requirements: 4, 5, 20.2_

- [x] 2. 모델 호출 예약 (`agent/budget.py`, `agent/llm.py`)
  - 선행: 1.1
  - [x] 2.1 `BudgetService.reserve(est)`: design §8.1 조건식(`lockToken`, `modelCallsReserved < 6`, `tokenCharged + est ≤ 30000`), 결과 `Reservation` / `FenceLost` / `BudgetExhausted(kind)` / `ReservationUncertain`. 환불 없음. `NoopBudget`(레벨 0·평가).
    - _Requirements: 11.1, 11.4, 11.8 · BE-Q97_
  - [x] 2.2 `LlmCaller(…, budget=)`: 호출 직전 예약, 불확실이면 호출하지 않음, `bind_tools` 지원(`parallel_tool_calls`는 설정 시만, `tool_choice`는 값이 있을 때만), 예약 뒤 `ai-slow` 훅 자리(작업 13.4). 6a 호출·분류·deadline·AsyncClient 종료 불변.
    - _Requirements: 8.1, 12.1 · BE-AI-02, BE-Q78_
  - [x] 2.3 토큰: `est`(글자 수 / `AI_TOKEN_EST_DIVISOR`=2, 도구 스키마 포함), 보고·추정·차감 구분(design §8.3).
    - _Requirements: 11.5, 11.6 · BE-Q120_
  - [x] 2.4 단위 테스트 (`tests/unit/test_agent_budget.py`): 6회·토큰·`lockToken` 조건, 불확실 시 Fake 호출 0, 예약 뒤 실패해도 환불 없음, 복구 재호출이 같은 6회 안(보완 4), 늦은 예약 반영(주입), 토큰 보정, 6a `LlmCaller` 테스트 전부 회귀.
    - _Requirements: 11, 20.2_
  - [x] 2.5 Write property test (`tests/unit/test_agent_properties.py`)
    - **Property 37: 임의의 응답·턴·장애 열에서 `modelCallsReserved` ≤ 6, 실제 호출 ≤ 예약, `tokenCharged` ≤ 30,000 + 마지막 보정분, 카운터는 줄지 않는다**
    - **Validates: Requirements 11.1, 11.4, 11.8 · BE-Q97**

- [x] 3. 체크포인트 저장소 (`agent/checkpoint.py`)
  - 선행: 1.1
  - [x] 3.1 `CheckpointStore`: 공유 `DynamoDBSaver`(콜드 스타트 1회, 체크포인트 전용 SDK 설정 connect 1·read 1·시도 1), 실행별 얕은 복사(울타리 `FENCE_MS` 24초, `COMMIT_RESERVE_MS`, 실행별 `ttl_seconds = 세션 ttl − now − 60`), 동기 `aput`·`aput_writes`·`aget_tuple`·`alist`·`adelete_thread`, 페이로드 크기 측정, `CHECKPOINT_DDB_ENDPOINT`.
    - _Requirements: 6.1–6.3, 6.6 · BE-Q104, BE-Q105, BE-Q119, BE-Q125_
  - [x] 3.2 `select_tip(session, hist)`: design §6.2(자손·`runTurn`·`runId ∈ turnRuns`·`runAttempt`·`consumedResumeIds` 검사, 가장 큰 시도의 최신, 없으면 base, base 없음 → F11), 사유 코드 로그.
    - _Requirements: 7.1 · BE-Q94, BE-Q126_
  - [x] 3.3 `classify_resume(state, session)`: design §6.3 표(질문 재개 / pause 재개 / 다른 질문 대기 / 턴 종료 / 중간 정지 / 이상).
    - _Requirements: 6.4, 7.1–7.3 · BE-Q19, BE-Q95_
  - [x] 3.4 삭제: 종료 커밋 확인 뒤 남은 시간 ≥ 1.5초일 때 1회, 실패·생략 사유 코드.
    - _Requirements: 6.7 · BE-Q103_
  - [x] 3.5 단위 테스트 (`tests/unit/test_agent_checkpoint.py`, moto): 울타리(시작 거부·커밋 여유), 스레드 미사용, tip 선택(포크·늦은 쓰기·다른 턴·모르는 실행·모르는 `resumeId`·더 큰 시도 우선), TTL ≤ 세션 TTL, 크기 측정, 삭제 정책.
    - _Requirements: 6, 7, 20.2_
  - [x] 3.6 호환성 테스트 (`tests/unit/test_agent_checkpoint_compat.py`): design §24.1의 1–6(버전 일치, 내부 속성, 복사 독립, 스레드 수, DynamoDB 연산 5개, metadata 표지).
    - _Requirements: 24.2, 24.4 · BE-Q119_
  - [x] 3.7 Write property test
    - **Property 46: 체크포인트 `ttl` ≤ AiSession `ttl`. 임의의 늦은 쓰기·포크·표지 오염에서 tip은 커밋 기준의 자손이고 조상은 이번 턴·`turnRuns` 실행·알려진 `resumeId`만 담으며, 더 큰 시도 가지가 있으면 그 가지에서 고른다**
    - **Validates: Requirements 6.3, 7.1 · BE-Q94, BE-Q104**

- [x] 4. Checkpoint A - 저장 계층
  - 작업 1–3 테스트, P37·P46 통과. `pytest tests/unit` 전체(722건 + 새 테스트) 실패 0. 레벨 0 경로 불변. **push 전 확인 → commit → push.**
  - _Requirements: 20.4, 20.5_

- [x] 5. Fake 모델과 스텁의 도구 호출 (`agent/fake_llm.py`, `tests/unit/llm_stub.py`)
  - 선행: 2.2
  - [x] 5.1 Fake: 도구 호출 단계(`tool_calls`, `invalid_tool_calls`, 여러 호출, 텍스트만), `bind_tools`, 호출별 메시지 요약·**도구 이름 목록** 기록, 단계 선택은 그래프 상태의 응답 받은 호출 수(design §20.1). 시나리오: `happy`, `ask_once`, `no_tool_call`, `no_tool_call_twice`, `bad_json_args`, `unknown_tool`, `parallel_calls`, `gate_reject_twice`, `timeout`, `http_500`, `http_401`, `http_400`, `budget_exhausted`, `question_rejected`, `private_place_ask`, `slow_agent`, `token_heavy`. 6a 시나리오 불변.
    - _Requirements: 19.1–19.3, 19.5_
  - [x] 5.2 스텁: OpenAI 형식 `tool_calls` 응답 모드(한 개·여러 개·잘못된 인자 JSON·도구 없음), 요청 본문 기록(`tools`·`parallel_tool_calls`·`tool_choice`).
    - _Requirements: 19.4_
  - [x] 5.3 단위 테스트: 시나리오별 Fake 출력 형태, 스텁 왕복(실제 `ChatOpenAI`), 소켓은 127.0.0.1만.
    - _Requirements: 19, 20.6_

- [x] 6. 에이전트 프롬프트 (`prompts/day_card_agent.md`, `agent/prompt.py`)
  - 선행: 없음
  - [x] 6.1 `day_card_agent.md`: design §12(원칙, 도구 규칙, 질문 우선순위, 블록 지시 무시, 질문문 개인정보 금지, 초안 절). 6a `day_card.md` 불변.
    - _Requirements: 16.1, 9.5 · BE-AI-03_
  - [x] 6.2 `agent_system_prompt()`, `agent_messages(story)`, `answer_block(answer)`(`neutralize`), 에이전트 `promptVersion`.
    - _Requirements: 10.6, 16.2, 16.3_
  - [x] 6.3 단위 테스트와 Property 32 확장(에이전트 메시지의 `<story>`·`<answer>` 블록).
    - _Requirements: 16.2 · 6a P32_

- [x] 7. 도구·질문·메모 (`agent/tools.py`)
  - 선행: 6
  - [x] 7.1 도구 인자 스키마(pydantic), Tool_Error 형식(`ONE_TOOL_PER_TURN`, `INVALID_ARGS`, `UNKNOWN_TOOL`, `QUESTION_REJECTED`, `GATE_REJECTED`, `CHECK_LIMIT`), 모델용 검사 보고서(경로·유형만, design §10.5).
    - _Requirements: 8.3, 8.4, 8.7, 8.8 · BE-Q115_
  - [x] 7.2 질문 검증(design §11.1: 개수·`path` 중복·길이·선택지·개인정보·허용 경로·`finishRequested`), `questionId` 서버 부여.
    - _Requirements: 9.1–9.4 · BE-Q123_
  - [x] 7.3 비공개 장소 질문(선택지 고정 `["동선에서 빼기"]` + 직접 입력)과 답변의 결정적 반영(design §11.2).
    - _Requirements: 9.6 · BE-Q116_
  - [x] 7.4 답변 근거: 개인정보 답변 `privacy = true`, Sources 제외(6a `ai_metrics.answer_sources`와 같은 규칙), 모델에는 `withheld`.
    - _Requirements: 10.3, 10.4_
  - [x] 7.5 `notes` 검증(design §10.6: `REWRITTEN`·`ASKED`만 모델 값, `source` 서버 재결정, `reason` 60자·개인정보 대체).
    - _Requirements: 8.9, 10.5, 14.4 · BE-Q76_
  - [x] 7.6 단위 테스트 (`tests/unit/test_agent_tools.py`): 거부 사유별, 비공개 장소 3가지 답, Tool_Error에 원문 없음.
    - _Requirements: 8, 9, 10_
  - [x] 7.7 Write property tests
    - **Property 40: 임의의 Tool_Call 묶음에서 실행 도구 ≤ 1, 모든 `tool_call_id`에 ToolMessage 정확히 1개**
    - **Property 41: 수락된 질문은 길이·개수·`path` 중복·허용 경로·개인정보 규칙을 모두 지킨다**
    - **Validates: Requirements 8.3, 8.4, 9.1–9.4**

- [x] 8. 에이전트 그래프 (`agent/state.py`, `agent/nodes.py`, `agent/graph.py`)
  - 선행: 2, 3, 5, 7
  - [x] 8.1 상태 필드(design §3.3), 6a 필드 불변.
    - _Requirements: 1.7_
  - [x] 8.2 노드: 에이전트 `draft`(JSON 아님 1회 재시도·빈 카드·스키마 위반 그대로), `decide_gate`(예산 카운터·12초·실행 시간 상한), `decide`(도구 목록 축소, 응답 처리 순서 design §10.4, 재촉 1회), 도구 실행(`check_draft` 집계 BE-Q98, `gate` 거부 집계), `ask_planner`(맨 앞 무조건 interrupt, 재개 값 기록·`consumedResumeIds`), `pause`(무조건 interrupt, `route` 복귀), `outcome` 기록. 유효 후보(design §10.3: 정보 없는 카드 제외, `places`만 빈 카드는 유효).
    - _Requirements: 1.3–1.6, 8, 9, 10, 11.2–11.3, 12.2, 13.1–13.4 · BE-Q98, BE-Q99, BE-Q122_
  - [x] 8.3 `build_agent_graph(checkpointer)`: design §10.1 엣지, prebuilt 미사용, 레벨 0 `build_pipeline_graph` 불변.
    - _Requirements: 1.1–1.4_
  - [x] 8.4 단위 테스트 (`tests/unit/test_agent_graph.py`, moto 체크포인터): 시나리오별 결과·trace·카운터, `pause`와 재개, LLM 오류 × 후보(정보 없는 카드 / `places`만 빈 카드 / 정상), Final_Check 차단 502, 레벨 0 6a 테스트 회귀.
    - _Requirements: 20.1_
  - [x] 8.5 Write property tests
    - **Property 39: 마지막 호출·`finishRequested`·질문 2개일 때 `decide`에 전달된 도구 목록에 `ask_planner`가 없다**
    - **Property 43: 어떤 경로로 끝나도 `READY` 카드는 Final_Check 차단 조건이 없다(6a P29 확장)**
    - **Validates: Requirements 8.2, 1.4**

- [x] 9. Checkpoint B - 그래프
  - P37·P39–P41·P43·P46 통과, 6a P29–P36 통과, 단위 전체 실패 0, 레벨 0 불변. **push 전 확인 → commit → push.**
  - _Requirements: 20.3–20.5_

- [x] 10. 핸들러 (`handlers/ai_card.py`)
  - 선행: 1, 3, 8
  - [x] 10.1 모드 분기: `agent`이면 에이전트, 미설정·`pipeline`이면 6a, 그 밖 503(할당량 전).
    - _Requirements: 1.1, 1.2 · BE-Q87_
  - [x] 10.2 에이전트 생성(design §4.1: 검증 → 할당량 → `WORKING`·잠금 항목 PutItem → 체크포인트 존재 확인 → 실행 → 커밋 → 응답).
    - _Requirements: 2 · BE-Q100_
  - [x] 10.3 에이전트 턴(design §5.1 ①–⑨: 형태 → 소유 → 모드 → 상태 기반 검증 → 잠금 → 시도 상한 → tip·입력 선택 → 실행 → 커밋 → 삭제), 실행 config(`thread_id`, `checkpoint_id = tip`, metadata 표지, `durability="sync"`, `tracing_context(enabled=False)`).
    - _Requirements: 3, 4, 5, 6.2, 6.4, 7 · BE-Q94–BE-Q96, BE-Q113_
  - [x] 10.4 중단 해제(울타리·체크포인트 일시 오류, 같은 `turn`의 `WORKING`), `FenceLost` 500, 결정적 폐쇄(F11–F13).
    - _Requirements: 7.4, 7.6, 12.3 · BE-Q121_
  - [x] 10.5 모드 전환(design §13 표): `pipeline` + `AGENT` 비종료 → 잠금 → 결정적 폐쇄 → 커밋 → 삭제. `PIPELINE` 비종료는 6a 500 유지.
    - _Requirements: 15.1–15.4 · BE-Q101, BE-Q87_
  - [x] 10.6 SessionView·trace(design §14: `ask_planner`, Tool_Error·재촉 표기, `pause` 미표기, 원문 인용 없음).
    - _Requirements: 14.1–14.5 · BE-Q124_
  - [x] 10.7 단위 테스트 (`tests/unit/test_handlers_ai_agent.py`): 3개 경로 흐름, 상태 기반 400, 실패 분기 순서, 모드 전환 표 전 칸, 6a 핸들러 테스트 회귀(레벨 0).
    - _Requirements: 20.1, 20.5_
  - [x] 10.8 장애 복구 테스트 (`tests/unit/test_agent_recovery.py`, 필수): **F0–F17 각각**을 테스트 전용 주입점(잠금·예약·노드 사이·체크포인트 쓰기 n번째·커밋·삭제)으로 만든 뒤 다음 시도로 복구. 각 사례에서 답변 반영 횟수, 추가 모델 호출 수, 최종 `outcome`, `turn`, `turnAttempts`를 확인. 늦은 체크포인트 쓰기(F16: 이전 시도의 쓰기를 새 시도 tip 선택 뒤에 주입), 계보 분기(포크 두 개), 표지 오염(F17), 커밋 결과 불확실(F7: 반영됨/안 됨 두 갈래), 답변 중복 전송(같은 `questionId` 재요청·다른 값 재요청).
    - _Requirements: 7, 20.2 · BE-Q94–BE-Q97, BE-Q113, BE-Q118_
  - [x] 10.9 프론트 모형(`tests/unit/frontend_sim.py`): docs/03 규칙(WORKING 자동 이어가기, 연속 2회 WORKING 뒤 `finish`, BUSY 2초 뒤 GET, CLOSED 뒤 GET, 같은 `turn`의 WORKING 처리).
    - _Requirements: 12.4 · BE-Q121_
  - [x] 10.10 Write property tests
    - **Property 38: 임의의 동시·중복 턴 요청 순서에서 커밋은 `lockToken`당 최대 1회, `turn`은 커밋마다 정확히 1 오르고, 한 `resumeId`는 `answers`와 그래프 상태에 최대 한 번**
    - **Property 44: SessionView는 상태별 규칙을 지키고 `ASKING`일 때만 `question`이 있다(6a P31 확장)**
    - **Property 45: 한 턴 안의 임의 장애 지점(F1–F7·F14·F16)에서 복구 결과는 장애 없는 실행과 같은 `outcome`·카드이고, 추가 모델 호출 수 ≤ "모델 응답 뒤 결과 저장 전" 장애 수**
    - **Property 47: `pipeline` 모드에서 비종료 에이전트 세션은 한 번의 잠금 요청으로 종료 상태가 되고 모델 호출 0. `PIPELINE` 비종료 세션은 500이고 바뀌지 않는다**
    - **Property 48: 프론트 모형과 임의 장애(울타리 닫힘·예약 불확실·강제 종료·동시 요청)에서 세션은 정해진 요청 수 안에 종료 상태 또는 오류가 되고 같은 턴 시도는 4를 넘지 않는다**
    - **Validates: Requirements 4, 5, 7, 12.4, 14, 15 · BE-Q101, BE-Q121**

- [x] 11. 로그·추적·지표 (`handlers/ai_card.py`, `common/metrics.py`, `domain/ai_metrics.py`)
  - 선행: 10
  - [x] 11.1 EMF 8종(design §17, `Bytes` 단위 포함) + 6a 3종, 로그 필드(design §16), 라이브러리 로거에 `langgraph_checkpoint_aws` 추가.
    - _Requirements: 17.1–17.3, 18.1 · BE-OBS-01_
  - [x] 11.2 `POST /plans` 지표: 에이전트 세션 `answers` 형식, `agentMode`(`AGENT`/`DEGRADED`), `privacyDetected`(종료 때 1회). 6a 레벨 0 지표 불변.
    - _Requirements: 18.2 · BE-Q79_
  - [x] 11.3 테스트 (`test_agent_logging.py`, `test_agent_tracing.py`): 6a 검사를 도구 호출·interrupt·resume·체크포인트 경로로 넓힘(DEBUG에서 체크포인트 본문 미노출, AST 금지 패턴을 새 모듈에 적용, LangSmith 전송 0), `test_ai_metrics.py` 에이전트 사례.
    - _Requirements: 17, 18_
  - [x] 11.4 Write property test
    - **Property 42: 개인정보가 탐지된 답변은 Sources에 없고, ToolMessage·로그·trace·EMF에 사연·답변·카드 문자열(한글 4자 이상 창)이 없다**
    - **Validates: Requirements 10.3, 17.1**

- [x] 12. Checkpoint C - 핸들러와 복구
  - **P29–P48 전부 통과**, F0–F17 전부 통과, 단위 전체 실패 0(722건 + 새 테스트), 레벨 0 핸들러 테스트 불변. **push 전 확인 → commit → push.**
  - 상태: 단위 1016건 통과(P29–P48, F0–F17 포함). 강제 종료 흉내는 한 번 죽으면 이후 모든 지점에서 던지게 했다(LangGraph가 일부 put 예외를 늦게 드러내므로).
  - _Requirements: 20_

- [x] 13. 인프라 (`template.yaml`, `agent/fault.py`, `docker-compose.yml`, `.env.example`)
  - 선행: 10
  - [x] 13.1 `HaruAgentCheckpoints`(PK/SK, TTL, on-demand, PITR), AiCardFunction 세 번째 정책(5개 연산, 이 테이블만), `CHECKPOINT_TABLE`, `AgentMode: [pipeline, agent]`(기본 `pipeline`).
    - _Requirements: 24.1–24.3, 15.1 · BE-INFRA-06, BE-INFRA-07_
  - [x] 13.2 `AgentTokens` 알람(5분 합계 300,000, 알림 대상 없음).
    - _Requirements: 18.4 · BE-Q114_
  - [x] 13.3 `AiFaultInject`(`""`, `ai-slow`), Rules, 환경 값 `!If [FakeAllowed, …]`, 런타임 확인(`FAULT_INJECT_ALLOWED`, 함수 이름 `haru-dev-` 또는 로컬).
    - _Requirements: 22.3 · BE-Q107_
  - [x] 13.4 `agent/fault.py`: 예약 뒤 호출 직전 9초 지연(deadline 안, 취소 가능, Fake·실제 공통).
    - _Requirements: 22.3 · BE-Q108_
  - [x] 13.5 compose `AGENT_MODE: ${AGENT_MODE:-pipeline}`, `CHECKPOINT_DDB_ENDPOINT`, `AGENT_TEST_HOOKS`(로컬 전용). `.env.example` 주석.
    - _Requirements: 21.2_
  - [x] 13.6 템플릿 단위 테스트: 새 리소스·권한·다른 함수 권한 없음·`AgentMode` 값·`AiFaultInject` 세 겹 차단 평가(Stage·스택 이름 조합)·알람·경로 일치·`LLM_API_KEY` 미정의. 기대값이 바뀐 6a 템플릿 테스트 목록과 근거.
    - _Requirements: 24, 20.5_

- [x] 14. 빌드와 의존성 격리 재검증
  - 선행: 13
  - [x] 14.1 `cfn-lint` 0건, `sam validate --lint`, `sam build --use-container`(AI 잠금 `--require-hashes`).
    - _Requirements: 24.6_
  - [x] 14.2 `scripts/check_ai_build.py` 확장: 에이전트 그래프 컴파일 + Fake `ask_once`(메모리 체크포인터) + `agent.checkpoint` import, 크기·import 시간(5회), 다른 함수 산출물 AI 패키지 0·체크포인트 테이블 권한 0, PlansFunction 인증 경로(6a 검사) 유지.
    - _Requirements: 24.5 · BE-Q18_
  - [x] 14.3 측정값 기록(6a 96.2MB·37.0MB·1.16–1.36초와 비교).
    - _Requirements: 24.5_
    - 상태(로컬 측정): AiCardFunction 압축 해제 96.3MB·zip 37.0MB(6a 96.2·37.0), handlers.ai_card import 중앙값 1.24초(1.21–1.26), 에이전트 모듈 포함 import 1.34초(1.31–1.43), 에이전트 Fake ask_once ASKING→READY 0.03초·최대 RSS 98.8MB, 다른 함수 8.1MB·AI 패키지 0. cfn-lint 0건, `sam validate --lint` 통과, `sam build --use-container`(`--require-hashes`) 성공.

- [x] 15. Checkpoint D - SAM·빌드
  - 14 전부 통과, 단위 전체 실패 0. **push 전 확인 → commit → push.**
  - _Requirements: 24.6_

- [x] 16. 로컬 통합 (`tests/local/test_local_agent.py`)
  - 선행: 13, 14
  - [x] 16.1 `AGENT_MODE=agent`로 띄웠을 때만 도는 사례: `ask_once`(생성 ASKING → 답 → READY → `POST /plans` 지표), `finish`, `WORKING` 이어가기(`slow_agent`), 같은 턴 동시 5요청, 중복 답변, 체크포인트 삭제 확인.
    - _Requirements: 21.1, 21.4_
  - [x] 16.2 강제 종료 복구: 테스트 전용 주입(`STAGE=local` + `AGENT_TEST_HOOKS=true`)으로 어댑터 처리 중 `os._exit` → 컨테이너 재시작 → 다음 요청으로 복구(F2·F4·F6 최소).
    - _Requirements: 21.3_
  - [x] 16.3 모드 전환: 같은 볼륨에서 `AGENT_MODE`를 바꿔 다시 띄우고 진행 중 세션 폐쇄 확인.
    - _Requirements: 15.6_
  - [x] 16.4 실행: 기본(`pipeline`) 상태에서 **기존 23건 통과**, `agent`로 다시 띄워 새 사례 통과. 결과에 `llmMode: fake`, 판정 근거 아님.
    - _Requirements: 20.5, 21.4_
    - 상태(2026-11-26, llmMode: fake, 판정 근거 아님): 기본 pipeline에서 기존 23건 통과. `AGENT_MODE=agent FAKE_LLM_SCENARIO=ask_once` + `LOCAL_AGENT_MODE=agent LOCAL_COMPOSE_CONTROL=1`에서 새 9건 통과(동시 5요청 200 1건·409 BUSY 4건, ai-slow 3요청 37.8초, 강제 종료 F2·F4·F6 복구, 모드 전환). `check_ai_build.py --local-ddb-network haru_default` 통과. 컨테이너를 다시 띄우면 dev 토큰 서명 키가 바뀌므로 토큰을 다시 받는다.

- [x] 17. AWS 통합 테스트 작성 (`tests/integration/test_ai.py`, 작성·수집만)
  - 선행: 10, 13
  - [x] 17.1 T18·T19·T22(실제 공급자 필요, Fake면 사유 있는 skip), T20(Fake `dev` 가능, `llmMode` 기록), T21(`fault`, `AiFaultInject=ai-slow`). T22는 design §20.5 기준(픽스처 `legitPlaces`).
    - _Requirements: 22.1–22.3 · BE-Q111_
  - [x] 17.2 정리: 체크포인트 스레드 삭제를 `_cleanup`에 추가(테스트 주체 권한 문서화), `test_integration_cleanup.py` 사례.
    - _Requirements: 22.4_
  - [x] 17.3 `--collect-only`(`-m integration`, `-m "integration and fault"`) 오류 없음, `STACK_NAME` 없으면 skip.
    - _Requirements: 22.5_
    - 상태: `-m integration` 26건 수집, `-m "integration and fault"` 3건 수집, `STACK_NAME` 없이 전부 skip. T20은 비종료 세션이 필요해 Fake dev(happy 고정)에서는 skip된다(실제 공급자 스택의 빈칸 사연으로 판정).
    - 보강(커밋 `b2b7c5d`): T20 판정을 `tests/integration/verdicts.py`로 분리했다. 세션당 예약 6 상한 외에, 예약 증가가 커밋된 턴의 모델 호출 수와 같은지(중복 요청의 추가 호출 0), 200 본문이 같은 턴의 같은 SessionView인지, 응답 코드 집합을 본다. 판정 함수는 단위 테스트 16건으로 확인했다.

- [x] 18. 오프라인 평가 도구 (`scripts/eval_agent.py`)
  - 선행: 8
  - [x] 18.1 design §21: 레벨 0 실행 1회로 ①(같은 `draft` 출력에 검사만)과 ②(같은 출력의 후처리 뒤)를 함께 내고, ③ 에이전트는 별도 호출(메모리 체크포인터, 픽스처 자동 답). 사연별 반복(기본 3) 중앙값, 결과 파일에 모델·설정·프롬프트 버전·`llmMode`·자동 답 규칙. 호출 수 상한과 쉼(공급자 한도).
    - _Requirements: 23.1–23.4 · BE-Q112_
  - [x] 18.2 Fake 실행 단위 테스트(`test_eval_agent.py`): 표 형식과 열이 맞는지만 본다. Fake 결과를 품질 근거로 쓰지 않는다는 문구가 출력에 있다.
    - _Requirements: 23.5_

- [x] 19. Checkpoint E - 전체 회귀와 인계
  - [x] 19.1 전체 회귀: 단위 전체(722건 + 6b), P29–P48, F0–F17, 로컬 23건 + 6b 사례, 통합 수집, cfn-lint·`sam validate --lint`·`sam build --use-container`·`check_ai_build.py`.
    - _Requirements: 20.4, 20.5, 24.6_
  - [x] 19.2 변경 범위(`git diff feat/be-6a-ai-pipeline`): `claim_service.py`·`fidelity.py`·`privacy.py`·`docs/03`·`frontend/` 0줄, `ddb.py` 0줄, 레벨 0 노드·프롬프트(`day_card.md`) 0줄.
    - _Requirements: 25.2, 25.3_
  - [x] 19.3 README(6b 현황, 배포 전 주의, IAM 표, 판정 실행표, 측정값, 복구 동작·한계, 모드 전환 절차, 오프라인 평가 절차)와 docs/08(BE-Q13·14·19·20·87 결과, BE-Q93–BE-Q128 옮기기, 결정되지 않은 것은 미결로).
    - _Requirements: 25.5, 25.6_
  - [x] 19.4 **push 전 확인 → commit → push.**
    - 상태(2026-11-26): 단위 1038건 통과(P29–P48, F0–F17), 로컬 pipeline 23건 + agent 9건, 통합 수집 26·3건, cfn-lint 0건·`sam validate --lint`·`sam build --use-container`·`check_ai_build.py`(로컬 DB 포함) 통과. 변경 범위: `claim_service.py`·`fidelity.py`·`privacy.py`·`ddb.py`·레벨 0 `nodes.py`·`tools.py`·`repair.py`·docs/03·frontend 0줄. `day_card.md`는 승인된 BE-Q127 한 줄(c69ac89).
    - _Requirements: 25.7_

### 공급자 검증 (개발용 NVIDIA NIM, BE-Q6 개발용 결정 승인됨, 합성 사연만)

- [ ] 20. 실제 공급자 호환성·스모크 (**20.1 완료. 20.2–20.4 실행은 대기: `LLM_API_KEY`가 `knu-aws-2026/backend/.env`에 없다, 2026-11-26 23:47 확인**)
  - 선행: 20.1 없음, 20.2는 10, 20.3은 18
  - [x] 20.1 6a 파이프라인과 요청 필드 확인(`scripts/probe_provider.py`, 2026-11-26, 커밋 `2e306a9`): Thinking 기본 켜짐 → `LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}` 필수, `max_completion_tokens`·`max_tokens`·`temperature=0`·`tools`·`parallel_tool_calls=false`·ToolMessage 후속·usage 동작, 레벨 0 합성 15건 14 READY·1건 502(장소 5곳, BE-Q127), 중앙값 1.13초·최대 4.33초·타임아웃 0, 잘못된 키 403(BE-Q128), 6a 핸들러 끝까지 200 READY. README 10.5·10.9·10.10.
    - _Requirements: 19.4 · BE-Q6(개발용), BE-Q9, BE-Q12_
  - [ ] 20.2 6b 에이전트 스모크: `AGENT_MODE=agent`로 합성 사연 5건(데모·비공개 장소·연락처·인젝션·빈칸)을 끝까지(질문은 픽스처 자동 답) 진행해 도구 호출 형태, 질문 수, 예약 사용 수, 턴 지연, deadline 준수를 기록한다(moto + 메모리 또는 Floci 체크포인터). Thinking OFF 고정. 6a 제한·예산 값을 완화하지 않는다.
    - 상태: **준비 완료, 실행 대기(키).** `tests/local/test_local_agent_real.py`(Floci DynamoDB + 실제 핸들러, `LOCAL_REAL_PROVIDER=1`)를 커밋 `14b6b83`에 두었다. 페이크 드라이런으로 흐름과 기준 판정을 확인했다(5건 READY, 동시 요청 통과, `llmMode` 가드 작동). 실제 공급자 결과는 없다.
    - _Requirements: 8, 11, 12 · BE-Q9, BE-Q12_
  - [ ] 20.3 오프라인 평가 실제 실행: 15건 × 반복 3, 실행 전 예상 호출 수를 출력하고 공급자 한도 안에서 나눠 돈다. 결과 표를 README에 붙이고 에이전트가 낫지 않은 유형도 적는다. 결과는 개발용 trial 결과이며 운영 공급자 결정 근거가 아니다(작업 23).
    - 상태: **도구 보강 완료(커밋 `ddc5612`), 실행 대기(키).** ①은 검사만 한 초안, ②는 같은 draft의 최종 카드, ③은 별도 호출(NoopBudget, 메모리 체크포인터). 429가 3회 연속이면 우회 없이 중단하고 부분 결과를 남긴다. 키 없이 실행하면 네트워크 호출 전에 종료함을 확인했다.
    - _Requirements: 23 · BE-Q112_
  - [ ] 20.4 BE-Q127(장소 4곳 이상)·BE-Q128(잘못된 키 403과 T12) 결정 요청. 결정에 따라 프롬프트·재시도 메시지·T12 기대값을 별도 커밋으로 바꾼다(결정 전에는 바꾸지 않는다).
    - 상태: 결정과 반영은 끝났다. BE-Q127 옵션 B(프롬프트 규칙과 재시도 메시지, promptVersion `ca6ada9ac3ef`, 서버는 배열을 자르지 않음, 커밋 `c69ac89`). BE-Q128 401·403과 `T12_BASELINE`(커밋 `c69ac89`). **남은 것은 키가 있을 때 장소 5곳 사연 3회 재검증(BE-Q127)과 정상 키 기준 기록 생성뿐이다.**
    - _Requirements: 13.4, 22 · BE-Q83, BE-Q91_
  - 각 하위 작업 뒤 **push 전 확인(실제 키 0회 포함) → commit → push.** `test-results/`는 커밋하지 않는다.

### 별도 승인 그룹

- [ ] 21. 프론트 리뷰 **[대기: 프론트엔드 담당]**
  - 선행: 19
  - [ ] 21.1 BE-Q121(같은 `turn`의 `WORKING`), BE-Q124(trace 표기), BE-Q76(문구), 데모 단계 칩 문구(장소 인용 없음), BE-Q13·FE-Q7(메모 복원, 계약 변경 절차).
  - [ ] 21.2 S4 재확인 경로(질문·`WORKING`·`AI_SESSION_BUSY`·`AI_SESSION_CLOSED`) 정리 전달.
  - _Requirements: 14.3, 14.4, 14.7 · docs/07 §7.3 S4_

- [ ] 22. AWS 판정 **[대기: AWS 담당. 개발 담당은 실행하지 않는다]**
  - 선행: 19
  - [ ] 22.1 `dev`에 `AgentMode=agent` 배포, Fake로 T20·T21(`llmMode` 기록), 실제 공급자 설정 스택에서 T18·T19·T22(합성 사연).
  - [ ] 22.2 AWS 전용 확인: 체크포인트 테이블 IAM(5개 연산), 쓰기 p99와 울타리·저장 여유(BE-Q106·BE-Q125), Init Duration·메모리(BE-Q18), 실제 병렬성에서 잠금·예약(T20), `AgentCheckpointBytes`.
  - [ ] 22.3 6a 회귀(T12는 BE-Q128 결정 뒤).
  - _Requirements: 22, 24 · T18–T22_

- [ ] 23. 운영 공급자 결정 **[대기: 팀 승인]**
  - 선행: 20.3
  - [ ] 23.1 시범 운영·`demo` 공급자(BE-Q6 운영분): NVIDIA trial은 운영 사용 불가이므로 유료·자체 호스팅 여부, 처리 국가·보존 기간 확인.
  - [ ] 23.2 BE-Q7 동의 문구, BE-Q10 전송 전 마스킹, BE-Q11 단가·알람 임계값.
  - [ ] 23.3 `samconfig.toml` 공급자 파라미터와 SSM 키(AWS 담당, 키 값은 저장소에 넣지 않음).
  - _Requirements: 25 · BE-Q6, BE-Q7, BE-Q10, BE-Q11_

- [ ] 24. 4·5단계 통합 회귀 **[대기: PR #1·#7·#8 병합]**
  - 선행: 19
  - [ ] 24.1 병합(rebase 없음), 겹치는 파일(design 요구 25.4 목록, `FaultInject`와 `AiFaultInject` 공존) 해결.
  - [ ] 24.2 전체 단위·로컬·빌드 회귀, AWS 판정 요청.
  - _Requirements: 25.4_

- [ ] 25. 6b PR 생성 **[대기: 사용자 승인]**
  - 선행: 19
  - Draft PR, base는 그때 PR #8 병합 상태에 따라 정한다. Ready for Review 전환·병합은 별도 승인.
  - _Requirements: 25.7_

## Task Dependency Graph

```
1 ─┬─ 2 ─┐
   └─ 3 ─┼─ 4(CP-A)
6 ── 7 ──┤
2.2 ── 5 ┤
         └─ 8 ── 9(CP-B) ── 10 ─┬─ 11 ── 12(CP-C)
                                 ├─ 13 ── 14 ── 15(CP-D) ── 16
                                 └─ 17
              8 ── 18
12, 15, 16, 17, 18 ── 19(CP-E)
20.1(완료) · 20.2 ← 10 · 20.3 ← 18 · 20.4 ← 승인
19 ── 21 · 22 · 24 · 25        20.3 ── 23
```

## Notes

- 속성과 작업: P37 → 2.5, P38 → 10.10, P39 → 8.5, P40 → 7.7, P41 → 7.7, P42 → 11.4, P43 → 8.5, P44 → 10.10, P45 → 10.10, P46 → 3.7, P47 → 10.10, P48 → 10.10. P29–P36은 6a `test_ai_properties.py` 그대로. 모두 필수다.
- 장애 복구와 작업: F0–F17 → 10.8(단위, 필수), F2·F4·F6 → 16.2(로컬 프로세스 종료), P45·P48 → 10.10(속성).
- 반드시 확인하는 위험: 늦은 체크포인트 쓰기(F16, P46), 계보 분기(3.5, P46), 모델 호출 예약 상한(2.4, P37), 답변 중복 반영(10.8, P38), 커밋 결과 불확실(F7, 1.7).
- 기대값이 바뀔 6a 테스트(근거와 함께 PR에 적는다): `test_template.py`의 테이블 목록·AiCard 정책 개수·`AgentMode` 허용 값, `check_ai_build.py` 기대 결과. 6a 비종료 500 테스트(`PIPELINE` 세션)는 그대로 유효하다.
- 실제 공급자 호출은 작업 20에서만. 일반 테스트·Checkpoint는 Fake·스텁만 쓴다.
- 새 테스트 파일: `test_agent_lock.py`, `test_agent_budget.py`, `test_agent_checkpoint.py`, `test_agent_checkpoint_compat.py`, `test_agent_tools.py`, `test_agent_graph.py`, `test_handlers_ai_agent.py`, `test_agent_recovery.py`, `frontend_sim.py`(헬퍼), `test_agent_logging.py`, `test_agent_tracing.py`, `test_agent_fake_vs_stub.py`, `test_agent_properties.py`, `test_eval_agent.py`, `tests/local/test_local_agent.py`. 공급자 확인: `test_probe_provider.py`(완료).
