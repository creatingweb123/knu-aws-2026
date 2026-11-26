# Implementation Plan: backend-stage6a-ai-pipeline

## Overview

백엔드 6a단계(AI 하루 카드 레벨 0, card-sessions 계약, AiQuota)를 `feat/be-6a-ai-pipeline`(base `fix/be-3-local-verify` `8fcf239`, worktree `/home/hwkim/haru-be-ai`) 위에 `backend/` 아래 Python 3.12로 구현한다. 근거는 같은 폴더의 `requirements.md`, `design.md`(승인됨)다.

작업은 다섯 묶음으로 나눈다.
- **묶음 L (작업 1–18)**: 공급자·프론트·팀 승인과 AWS 없이 구현·검증할 수 있는 전부. Fake 채팅 모델과 로컬 HTTP 스텁으로 검증하고, 권장안(BE-Q73 Asia/Seoul, BE-Q86 dev Fake 허용)과 임시안(BE-Q76 trace 문구, BE-Q82 스로틀 값)대로 구현한다.
- **공급자 승인 의존 (작업 19)**: BE-Q6(공급자·모델)·BE-Q7(동의 문구)·BE-Q10(전송 전 마스킹) 확정 뒤에만 한다.
- **프론트·팀 리뷰 의존 (작업 20)**: BE-Q76·BE-Q92·BE-Q13/FE-Q7(프론트), BE-Q73·BE-Q86·BE-Q82(팀) 리뷰 결과를 반영한다.
- **AWS 판정 의존 (작업 21)**: AWS 담당의 `dev` 배포와 판정. 개발 담당은 실행하지 않는다.
- **4·5단계 병합 뒤 통합 (작업 22)**, **6a PR (작업 23)**: 사용자 확인 뒤.

공통 규칙
- API 계약(docs/03)과 DynamoDB 키 설계(docs/02 §2.6)는 바꾸지 않는다. 3단계 `claim_service.py`와 `common/ddb.py`의 `table`·`transact_with_retry`·`ConditionFailed`·`BACKOFF_SECONDS`는 바꾸지 않는다. `common/ddb.py`에는 `use_table`만 더한다(5단계와 같은 함수). `fidelity.py`·`privacy.py`의 판정 규칙은 바꾸지 않는다.
- 6b 기능(`decide`, `ask_planner`, `pause`, 턴 잠금, `AI_SESSION_BUSY` 사용, interrupt/resume, 운영 체크포인터, `HaruAgentCheckpoints` SAM 리소스)은 만들지 않는다. 체크포인터는 로컬 연결 확인 테스트(작업 15.3)만 둔다.
- 실제 LLM 공급자를 부르지 않는다. 실제 사용자 사연을 외부로 보내지 않는다. 테스트 사연은 데모 사연과 합성 사연뿐이다(Requirement 8.6, 8.7).
- AWS 리소스 생성·`sam deploy`·AWS 통합 테스트 실행은 하지 않는다. AWS 대상 테스트는 코드만 쓰고 수집(`--collect-only`)까지 확인한다. T12는 실제 공급자의 401로만 판정하므로 그 전까지 **미검증**이다(BE-Q83).
- 기존 PR #1–#7과 그 브랜치, 다른 worktree, 프론트엔드 작업 트리(`/home/hwkim/knu-aws-2026`), docs/03은 바꾸지 않는다.
- 속성 기반 테스트(Property 29–36)는 **모두 필수**다. Hypothesis 최소 100회, 태그 `Feature: backend-stage6a-ai-pipeline, Property {n}`. 실패 사례는 `@example`로 고정한다.
- 작업 그룹마다 해당 테스트를 돌리고 실패를 고친 뒤 넘어간다. **1–3단계 회귀(단위 296건, 로컬 16건)는 모든 Checkpoint에서 필수**다.
- `agent/`·`handlers/ai_card.py`는 예외 메시지·`repr`·`logger.exception`을 쓰지 않는다(작업 9.6의 정적 검사).
- 미결 항목은 임시 결정으로 구현하고 코드 주석과 PR에 번호를 남긴다: BE-Q73–BE-Q92, BE-Q18, BE-Q21, BE-Q22, BE-Q23, BE-Q25, BE-Q26. BE-Q6·BE-Q7·BE-Q9·BE-Q10·BE-Q12는 결정하지 않는다.
- 커밋은 의미 단위로 하고 push·PR은 사용자 확인 뒤에 한다. IDE의 "브랜치 게시"·"동기화"를 쓰지 않는다.
- 의존성은 각 작업 머리의 `선행:` 줄과 끝의 Task Dependency Graph로 적는다.

## Tasks

### 묶음 L: 승인·AWS 없이 하는 작업

- [x] 1. 공통 모듈 (`src/common`)
  - 선행: 없음
  - [x] 1.1 `common/errors.py`: `AI_QUOTA_EXCEEDED`(429), `AI_SESSION_CLOSED`(409), `AI_SESSION_BUSY`(409, 6a 미사용), `AI_INVALID_OUTPUT`(502), `AI_UNAVAILABLE`(503)와 기본 메시지. 기존 코드·상태 조합 불변.
    - _Requirements: 12.4, 1.10 · §3.6_
  - [x] 1.2 `common/ids.py`: `new_session_id()`(`ais_` + ULID), `is_session_id(s)`(형식 검사).
    - _Requirements: 1.9, 2.4 · BE-Q77_
  - [x] 1.3 `common/metrics.py`: `emf_line(..., unit="Count")`, `emit(..., unit="Count")`(5단계와 같은 시그니처), 상수 `AI_LATENCY_MS`·`AI_FAILURE`·`AI_INVALID_OUTPUT`. 기존 3종 출력은 바이트 단위로 같다.
    - _Requirements: 18.1, 18.2 · BE-OBS-01, BE-Q37_
  - [x] 1.4 `common/ddb.py`: `use_table(t)`만 추가. 나머지 diff 0.
    - _Requirements: 7.6, 12.5 · BE-Q85, BE-Q48(미결 유지)_
  - [x] 1.5 `common/validation.py`: `AiPlaceDraft`·`AiCardDraft`(Card_Schema, strict, extra ignore), 정규화 함수(design §3.1: 키 없음·공백 → `null`, `whyChosen` `""` 유지, `places` 없음 → `[]`), `AiSessionCreate`(`story` 1–1000), `AiTurn`(`expectedTurn` ≥1, `finish`), `AiAnswer`(`choice`·`text`·`skipped` 중 정확히 하나, 길이), `_FIELD_MESSAGES`에 새 필드. `PlanCreate` 불변.
    - _Requirements: 1.2, 3.1, 4.4, 9.3 · BE-Q91_
  - [x] 1.6 공통 모듈 단위 테스트
    - `test_errors.py`: 새 코드·상태, `emf_line` 단위 지정, 기존 `test_emf_line_format` 불변.
    - `test_ids.py`: `ais_` 형식, 잘못된 형식(접두어·길이·문자).
    - `test_ai_card_schema.py`(신규): design §3.1 표의 모든 줄(정상 `null` vs 위반: 숫자 자리 문자열, `"45"`·`45.5`·`45.0`·`True`·9·241, 길이 초과, `places` 4개·비배열·원소 비객체, 알 수 없는 키 무시), 경계값 양 끝, `whyChosen` `""`·`null`.
    - `test_validation.py`: `AiSessionCreate`(0·1·1000·1001자, 비문자열, `details` 키 `story`), `AiTurn`(`expectedTurn` 0·"1"·누락, `answer` 둘 이상·없음·`text` 101자, `skipped: false`).
    - _Requirements: 1.2, 3.1, 4.4, 12.4, 18.2, 19.1 · BE-Q91_

- [x] 2. 의존성 잠금과 개발 환경
  - 선행: 없음
  - [x] 2.1 `src/ai-requirements.in`(직접 의존성: `langgraph==1.2.24`, `langgraph-checkpoint==4.3.2`, `langchain-core==1.8.4`, `langchain-openai==1.8.5`, `langgraph-checkpoint-aws==1.3.0`, `boto3>=1.43.64`, `pydantic==2.14.4`, `python-ulid==4.2.0`). 구현 시점에 PyPI를 다시 확인하고 바꾼 값이 있으면 이유를 주석에 남긴다.
  - [x] 2.2 `src/ai-requirements.lock`: `uv pip compile src/ai-requirements.in --python-version 3.12 --python-platform x86_64-manylinux_2_28 --generate-hashes -o src/ai-requirements.lock`. 생성 명령과 날짜를 머리 주석에 남긴다. 해시 설치(`--require-hashes`)가 Lambda 빌드 이미지에서 동작하지 않으면 해시 없는 `==` 잠금으로 바꾸고 README에 적는다.
  - [x] 2.3 `requirements-dev.txt`: 잠금 파일의 버전으로 AI 패키지를 설치(해시 없는 설치용 파일이 필요하면 같은 명령으로 생성), `boto3`·`botocore`를 잠금 버전에 맞춘다. 개발 `.venv`를 다시 만들어 1–3단계 단위 296건이 그대로 통과하는지 먼저 확인한다.
  - [x] 2.4 `tests/unit/test_ai_lock.py`: 잠금 파일의 모든 패키지 줄이 `==`, 직접 의존성이 모두 있음, `pydantic`·`python-ulid` 버전이 `src/requirements.txt`와 같음, `src/requirements.txt`에 AI 패키지가 없음.
  - _Requirements: 16.1, 16.2, 16.5, 19.13 · BE-Q18, BE-Q80_

- [x] 3. AiSession·AiQuota 서비스 (`domain/ai_session_service.py`)
  - 선행: 1.2, 1.4, 1.5
  - [x] 3.1 Asia/Seoul 날짜: `quota_day(now_utc) -> (yyyymmdd, ttl_epoch)`, `ZoneInfo` 실패 시 고정 오프셋 대체와 경고 1회(design §6).
    - _Requirements: 6.2, 6.5 · BE-Q73_
  - [x] 3.2 AiQuota: `consume(user_id, now)` — `ADD sessions :one SET ttl = if_not_exists(...)`, 조건 `attribute_not_exists(sessions) OR sessions < :limit`, `AI_DAILY_SESSION_LIMIT`(기본 10). 조건 실패 → 429, 그 밖 → 500 `INTERNAL_ERROR`(사유 `QUOTA_WRITE_FAILED`). 되돌리지 않는다.
    - _Requirements: 6.1–6.4, 6.6 · BE-AI-10_
  - [x] 3.3 AiSession: `build_session_item(...)`(design §5.1 속성 전체, `llmMode`·`llmProviderLabel` 포함, `ttl` = createdAt + 30일), `put_session(item)`(조건 `attribute_not_exists(PK)`), `get_live_session(id)`(`ConsistentRead`, `ttl <= now`·`ttl` 이상이면 `None`), `verify_saved(item)`(design §4.4).
    - _Requirements: 5.1, 5.4, 5.7, 5.8 · BE-AI-07, BE-Q74, BE-Q89_
  - [x] 3.4 `serialize_session_view(item)`: 허용 목록 9개 키, 상태별 `card`·`flags`·`notes`, `places` 항상 배열, `question` `null`, 내부 속성(`llmMode` 포함) 제외.
    - _Requirements: 4.1–4.6, 4.10 · §3.2, BE-Q76_
  - [x] 3.5 단위 테스트 (`tests/unit/test_ai_session_service.py`, moto)
    - TTL: `ttl = now`·`now − 1`·`now + 1`, `ttl` 없음·문자열 → 각각 Live/Expired, 항목이 남아 있어도 Expired면 `None`.
    - 저장: 조건 실패, 숫자 `Decimal`, `null` 저장·복원, 시간 값 밀리초 3자리 UTC.
    - AiQuota: 10건 성공·11번째 429, 400 경로는 호출되지 않음(핸들러 테스트에서), 502·503 세션도 1건, 사용자 분리, KST 경계(UTC `14:59:59.999` → 그날 키, `15:00:00.000` → 다음 날 키, 각 `ttl` 값), `ZoneInfo` 실패 대체 경로.
    - 동시성: 스레드 15개 × (남은 한도 10 / 0) → 성공 10 / 0(moto 조건식 확인, 판정은 AWS).
    - `verify_saved`: 우리 항목·다른 항목·없음·조회 실패.
    - _Requirements: 5.8, 6.1–6.5, 19.2–19.4 · BE-Q73, BE-Q89_
  - [x] 3.6 Write property test for SessionView (`tests/unit/test_ai_properties.py`)
    - **Property 31: SessionView는 상태별 규칙을 지키고 허용 목록 밖 키가 없다**
    - 생성기: 임의 상태(`READY`·`FAILED`, 6b 상태 포함)·카드·플래그·메모·내부 속성이 든 AiSession 항목.
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**
  - [x] 3.7 Write property test for AiQuota (`tests/unit/test_ai_properties.py`)
    - **Property 33: 하루 성공한 세션 생성 수는 한도 이하이고, 성공 수 = 모델을 부른 세션 수**
    - 생성기: 한도 1–20, 요청 수 0–30, 사용자 1–3명, 시각(경계 전후). moto 위에서 순서대로·스레드 동시로 실행.
    - **Validates: Requirements 6.1, 6.3, 6.4, 6.5**

- [x] 4. 카드 파싱과 검사·수리 (`agent/card.py`, `agent/tools.py`, `agent/repair.py`)
  - 선행: 1.5
  - [x] 4.1 `agent/card.py`: content 텍스트 추출(블록 목록 포함), 코드 펜스 제거, 첫 `{`에서 `raw_decode`, 정규화 → `AiCardDraft`. 결과 `ok | NOT_JSON | SCHEMA(경로 목록)`. 원문을 결과에 담지 않는다.
    - _Requirements: 9.3, 9.4 · BE-Q91_
  - [x] 4.2 `agent/tools.py`: `check_draft(card, sources) -> Report`(경로만, 텍스트 없음), `gate_verdict(report)`, `final_check(card, sources, masked_paths, allowed_nis_activities) -> (flags, blocked)`(design §9.4 표, 플래그 정렬·중복 제거).
    - _Requirements: 11.1, 11.4, 11.7–11.9 · BE-Q88, BE-Q22_
  - [x] 4.3 `agent/repair.py`: 작업 카드의 `_src` 부여·제거, `apply_rules`(장소 이름·활동의 비공개 장소 제거, `REMOVED`), `apply_fallback`(가리기 → 재검사 → 이름 NOT_IN_SOURCE 제거 → 활동만 위반 `KEPT_FLAGGED`, 길이 초과 자르기, `degraded`), 경로·인덱스 변환(design §10).
    - _Requirements: 4.5, 4.7, 4.8, 11.3, 11.5, 11.6 · BE-Q13, BE-Q76_
  - [x] 4.4 단위 테스트 (`tests/unit/test_ai_checks.py`)
    - JSON 추출: 펜스, 앞뒤 설명문, 두 객체, 배열 최상위, 잘린 JSON, 블록 목록 content.
    - `check_draft`: 원문 대조(장소 이름·활동), 개인정보(카드의 모든 문자열 필드, HIGH·MEDIUM), `missing`(design §3.2 표, `whyChosen` 제외, 빈 `places`).
    - Gate: 각 거부 조건 하나씩, 규칙 노드 뒤 다시 계산하는지(이전 Report를 넘겨도 쓰지 않음).
    - `rules`: 이름·활동에 비공개 장소 → 제거와 `REMOVED` 경로(Candidate 인덱스), `whyChosen`·`title`의 비공개 장소는 남고 `PRIVACY`.
    - Fallback: 연락처가 든 이름 → 가린 뒤 제거, 활동에 연락처 → 가림 + `KEPT_FLAGGED`, 이름 NOT_IN_SOURCE 제거, 모든 장소 제거 → `places: []` + `MISSING(places)`, "1호" 가림 뒤 길이(최대 길이 필드), `degraded`.
    - Final_Check: design §9.4 표의 차단 5종·허용 4종을 각각, Gate 통과 경로도 Final_Check를 거침, 차단 시 `blocked` 사유 코드.
    - 인덱스: design §10.3 예와 같은 결과, 제거가 여러 번일 때 `REMOVED`는 모두 Candidate 기준, `flags`가 뺀 장소를 가리키지 않음.
    - _Requirements: 4.5, 4.7, 4.8, 11.1–11.9, 19.5 · BE-Q88_
  - [x] 4.5 Write property test for Final_Check 불변식 (`tests/unit/test_ai_properties.py`)
    - **Property 29: 규칙 노드·(Gate 거부 시) Fallback·Final_Check를 거친 카드는 차단 조건이 없고, 정상 코드에서 차단이 나오지 않는다**
    - 생성기: 장소 0–3개, 원문 일부·원문에 없는 낱말·개인정보 표본(전화·이메일·주민번호·동호수·차량번호·번지·비공개 장소)을 섞은 문자열, `null` 필드, 사연(근거) 문자열.
    - 확인: `HIGH` 0, 스키마 오류 0, 장소 이름 NOT_IN_SOURCE 0, 장소의 비공개 장소 0, 활동 NOT_IN_SOURCE는 모두 `KEPT_FLAGGED` 메모와 플래그 있음, `blocked`가 비어 있음.
    - **Validates: Requirements 11.4, 11.5, 11.6, 11.7, 11.8, 11.9**
  - [x] 4.6 Write property test for 경로 기준 (`tests/unit/test_ai_properties.py`)
    - **Property 30: `flags`는 최종 카드 경로만, `REMOVED` 메모는 Candidate_Card 경로, `KEPT_FLAGGED`는 최종 카드 경로를 가리킨다**
    - 생성기: 4.5와 같음.
    - **Validates: Requirements 4.6, 4.7, 4.8**

- [x] 5. Checkpoint A - 공통·서비스·검사 단위 테스트와 회귀
  - `pytest tests/unit` 실패 0건(1–3단계 296건 포함), Property 29·30·31·33 통과(각 100예시 이상). 실패는 원인을 고친 뒤 다음으로 간다.
  - _Requirements: 19.5, 19.13_

- [x] 6. 프롬프트 (`agent/prompt.py`, `prompts/day_card.md`)
  - 선행: 1.5
  - [x] 6.1 `prompts/day_card.md`: design §8.1 원칙(원문 장소·행동만, `null`, 공개 장소, 개인정보 제거, 질문 정확히 1개, "빼기보다 원문 표현으로 바꾸기", Card 필드 JSON 객체 하나, 블록 안 지시 무시). 예시 출력에는 데모 사연 기반 값만 쓴다.
    - _Requirements: 10.1, 10.2, 10.5 · BE-AI-03_
  - [x] 6.2 `agent/prompt.py`: 파일 로드(콜드 스타트 1회), `prompt_version()`(SHA-256 앞 12자), `neutralize(story)`(`<\s*/?\s*(story|answer)\b`의 `<` → `＜`), `build_messages(story)`, `retry_message(kinds, paths)`(실패 원문 없음).
    - _Requirements: 10.3, 10.4 · BE-Q10(마스킹 안 함)_
  - [x] 6.3 단위 테스트 (`tests/unit/test_ai_prompt.py`): 태그 변형(대소문자·공백·`</ story>`·`<answer>`), 그 밖 글자 보존, 재시도 메시지에 원문 없음, 버전 값이 파일 내용에 따라 바뀜.
    - _Requirements: 10.2, 10.3_
  - [x] 6.4 Write property test for 데이터 블록 (`tests/unit/test_ai_properties.py`)
    - **Property 32: 어떤 사연이든 사용자 메시지에는 `<story>`·`</story>`가 정확히 한 번씩이고, 사연 부분에 블록 태그 패턴이 없으며, 태그의 `<` 외 글자는 원문과 같다**
    - 생성기: 임의 유니코드 텍스트 + 태그 조각 삽입.
    - **Validates: Requirements 10.2, 10.3**

- [x] 7. LLM 클라이언트·Fake·시간 예산 (`agent/llm.py`, `agent/fake_llm.py`, `agent/timebudget.py`)
  - 선행: 1.3, 2.3
  - [x] 7.1 `agent/timebudget.py`: `TimeBudget(context, event, clock)` — `min(lambda 남은 시간, timeEpoch + 29초 − now)`, `timeEpoch` 검증(정수, `now − 30s − 2s ≤ t ≤ now + 2s`, 아니면 무시하고 `TIME_EPOCH_IGNORED`), `can_start_call()`(≥ 12초), `call_deadline_s()`(`min(10, (remaining − 4초)/1000)`), `can_verify()`(≥ 1.5초).
    - _Requirements: 9.5, 12.2, 12.5, 12.6 · BE-Q90_
  - [x] 7.2 `agent/llm.py` 설정·키: 환경 변수 파싱(design §11.1), `CONFIG` 사유, `fake` 런타임 차단(`FAKE_LLM_ALLOWED`, 함수 이름 `haru-dev-` 또는 로컬 `STAGE=local`), SSM 키 캐시(성공만 캐시, 실패 `KEY_READ_FAILED`, AI 전용 `Config`), 로컬 `LLM_API_KEY`, `SecretStr`.
    - _Requirements: 7.1–7.9, 7.12, 15.10 · BE-Q81, BE-Q85, BE-Q86_
  - [x] 7.3 `agent/llm.py` 호출: `call_llm(messages, deadline_s)` — 호출마다 `httpx.AsyncClient`(async with) + `ChatOpenAI(…, http_async_client=…, max_retries=0, use_responses_api=False)` + `asyncio.wait_for`. 오류 분류표(design §11.3, `APITimeoutError`를 `APIConnectionError`보다 먼저), 토큰 합산·추정(`tokenEstimated`). 라이브러리 로거 수준 고정.
    - _Requirements: 7.10, 7.11, 5.6, 13.3 · BE-Q78, BE-Q92_
  - [x] 7.4 `agent/fake_llm.py`: `FakeScenarioChatModel`(async, 단계 `content`·`raise`·`sleep`, 호출 기록), 시나리오 18종(design §11.4), 실제 `openai` 예외 생성.
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 7.5 로컬 HTTP 스텁 (`tests/unit/llm_stub.py`): `ThreadingHTTPServer`(127.0.0.1), 모드 `ok`·`no_usage`·`fenced`·`prose_around_json`·`status:<code>`·`drip`·`hang`·`close`, 요청 기록(키는 비교만).
    - _Requirements: 8.4_
  - [x] 7.6 단위 테스트
    - `test_ai_timebudget.py`: `timeEpoch` 없음·문자열·음수·미래 +10초·과거 −40초·정상 −3초(남은 26초), 12초·4초·1.5초 경계, 콜드 스타트 흉내(Init 3초 뒤 시작).
    - `test_ai_llm.py`: 설정 오류 각 사유(값을 로그에 안 남김), `LLM_TEMPERATURE` 빈 값, `LLM_EXTRA_BODY` 비객체, `LLM_MAX_RETRIES` 0 외, SSM 캐시(Stubber: 성공 1회만 호출·실패는 다음 호출에서 다시 읽음·`WithDecryption=True`·이름만 사용), `fake` 차단 3경우, AWS 설정에서 `LLM_API_KEY` 미사용.
    - `test_ai_llm_stub.py`(실제 `ChatOpenAI`): 경로 `/v1/chat/completions`, `max_completion_tokens`, `extra_body` 합침, `temperature` 생략, `tools` 없음, 호출 1회(재시도 0), 400·401·403·404·429·500·503·연결 거부·연결 타임아웃의 분류 코드, usage 없음 → 추정, 펜스·설명문 JSON 추출.
    - `test_ai_fake_vs_stub.py`: 같은 시나리오(정상·잘못된 JSON·스키마 오류·타임아웃·400·401·429·500)를 Fake와 스텁에서 돌려 분류 코드·그래프 결과가 같음(작업 8 뒤 그래프 수준 비교 추가).
    - _Requirements: 7.1–7.11, 8.1–8.4, 19.6 · BE-Q78, BE-Q90_
  - [x] 7.7 취소·Warm 호출 테스트 (`tests/unit/test_ai_cancel.py`)
    - `drip`·`hang`·`close`에서 `call_llm` 전체 반환 시간(취소 + `aclose` 포함) ≤ deadline + 500ms, 20회 반복 최댓값을 출력해 README 근거로 쓴다.
    - 취소된 호출 뒤 같은 프로세스의 다음 호출 정상.
    - Warm: 같은 프로세스에서 `asyncio.run`을 30회 반복(정상·취소 섞음) → `Event loop is closed` 없음, `ResourceWarning`·미완료 태스크 경고를 오류로 바꿔도 통과, 열린 소켓 수가 늘지 않음(`psutil` 없이 `/proc/self/fd` 수로 확인, 리눅스 전용 표시).
    - _Requirements: 7.11, 12.5, 12.6 · BE-Q78_

- [x] 8. 레벨 0 그래프 (`agent/state.py`, `agent/nodes.py`, `agent/graph.py`)
  - 선행: 4, 6, 7
  - [x] 8.1 `state.py`(design §7.1), `nodes.py`(draft·check_draft·rules·gate·fallback·final_check, draft는 async, 나머지 순수), `graph.py`(`build_pipeline_graph()`, 체크포인터 없이 compile, 조건부 엣지 2개, 모듈 로드 때 1회 생성).
    - draft: design §8.3 알고리즘(12초 확인, LLM_Error 재시도 없음, 검증 실패만 1회 재시도, `TIME_BUDGET`, `model_calls`는 실제 요청 수, 실패 원문 미보관). check_draft 첫 실행만 `first_proposal`·`first_report`를 쓴다. trace 항목(design §10.4 문구·개수·유형만).
    - _Requirements: 9.1–9.9, 5.2, 4.9 · BE-AI-11, BE-AI-13_
  - [x] 8.2 단위 테스트 (`tests/unit/test_ai_graph.py`): Fake 시나리오별 최종 상태(후보·`llm_error`·`last_failure`·`model_calls`·`degraded`·`flags`·`notes`·`blocked`·trace), 12초 미만 재시도 생략, 첫 호출 전 12초 미만 → `TIME_BUDGET`·호출 0회, `slow` + deadline, 체크포인터 없음, prebuilt 미사용(import 검사).
    - _Requirements: 9.1–9.7, 19.1_
  - [x] 8.3 Write property test for draft 호출 수 (`tests/unit/test_ai_properties.py`)
    - **Property 35: `draft` 호출 수는 0–2회이고, 2회째는 첫 시도가 검증 실패였고 시작 때 남은 시간이 12초 이상일 때만이다. LLM_Error 뒤에는 재시도하지 않는다**
    - 생성기: 시도별 결과(정상·`NOT_JSON`·`SCHEMA`·LLM_Error 종류)와 남은 시간 열.
    - **Validates: Requirements 9.4, 9.5, 9.6**
  - [x] 8.4 Write property test for 첫 제안 보존 (`tests/unit/test_ai_properties.py`)
    - **Property 36: `firstProposal`·`firstReport`는 그래프가 끝난 뒤에도 첫 `check_draft`의 입력·출력과 같다**
    - 생성기: 4.5의 카드 생성기를 Fake 응답으로 감싼 것, Gate 통과·거부 모두.
    - **Validates: Requirements 5.2**

- [x] 9. 핸들러 (`handlers/ai_card.py`, `handlers/routes.py`)
  - 선행: 3, 8
  - [x] 9.1 콜드 스타트 초기화: AI 전용 `Config`로 DynamoDB 리소스·SSM 클라이언트 생성, `ddb.use_table`, 그래프·프롬프트 로드. 라이브러리 로거 수준.
    - _Requirements: 7.6, 12.5 · BE-Q85_
  - [x] 9.2 `POST /ai/card-sessions`: design §4.1 순서(검증 → `AGENT_MODE` → 할당량 → `tracing_context(enabled=False)` 안에서 `asyncio.run(graph.ainvoke)` → 결과 판정 → 저장·확인(§4.4) → EMF → 응답). `AGENT_MODE` 미설정 → `pipeline`, 그 밖 → 503 `CONFIG_AGENT_MODE`(할당량 전).
    - _Requirements: 1.1–1.8, 1.10, 5.1, 5.4, 6.1, 9.2, 9.10, 12.3, 13.5, 18.1 · BE-Q74, BE-Q75, BE-Q87, BE-Q88, BE-Q89_
  - [x] 9.3 `GET /ai/card-sessions/{sessionId}`, `POST …/turns`: design §4.2·§4.3. 형식 오류 ID 404, 404 본문 동일, turns ①–③, 비종료 세션 500 `NON_TERMINAL_SESSION`.
    - _Requirements: 2.1–2.4, 3.1–3.5 · BE-Q77, BE-Q87_
  - [x] 9.4 `routes.py`에 3개 경로(`handlers.ai_card.handler`).
    - _Requirements: 15.1, 19.12_
  - [x] 9.5 단위 테스트 (`tests/unit/test_handlers_ai_card.py`, moto + Fake)
    - 생성: Fake 시나리오별 응답 코드·SessionView·AiSession 속성(`llmMode` 저장, 응답에는 없음)·할당량·EMF 3종. 400은 할당량 미사용·모델 0회, `AGENT_MODE=agent`·`foo` → 503·할당량 미사용·모델 0회, 미설정 → 정상.
    - 원인이 섞인 실패(검증 실패 → LLM_Error → 503, LLM 없음 → 검증 실패 두 번 → 502), `TIME_BUDGET` → 503, Final_Check 차단 주입(모의) → 502 `FALLBACK_INVARIANT`.
    - 소유권·TTL: 남의 세션·없는 세션·만료(항목 남음)·형식 오류 ID → GET·turns 404(본문·상태 동일), 모델·쓰기 0.
    - turns: 같은 turn 409, 다른 turn 200, 형태 오류 400, 비종료 세션(직접 넣은 항목) 500·세션 불변.
    - _Requirements: 1.1–1.10, 2.1–2.4, 3.1–3.5, 5.8, 6.1, 19.1, 19.2 · BE-Q87_
  - [x] 9.6 저장 불확실성·429·로그·추적 테스트
    - `test_ai_save_uncertain.py`: `PutItem` 읽기 타임아웃(Stubber/주입) 후 확인 조회 성공 → 200, 조건 실패인데 우리 항목 → 200, 다른 항목 → 500, 확인 조회 실패 → 500, 남은 시간 1.5초 미만 → 조회 없이 500, 모든 경우 할당량 그대로.
    - `test_ai_429.py`: 공급자 429(Fake·스텁) → 503 `AI_UNAVAILABLE`·`llmError=HTTP_429`, 할당량 429는 계약 형식, 두 경우의 `AiFailure`·로그 구분.
    - `test_ai_logging.py`: 모든 시나리오(성공·실패·예외 주입)에서 로그·trace·응답·AiSession 로그 필드에 사연 표본·카드 문자열·가짜 키(`sk-test-…`)·모델 응답 원문이 없음, 라이브러리 로거 수준, AST 검사로 `agent/`·`handlers/ai_card.py`에 `logger.exception`·`exc_info=True`·`str(e)`·`repr(e)`·`%r` 포맷 없음.
    - `test_ai_tracing.py`: `LANGSMITH_TRACING=true`·`LANGCHAIN_TRACING_V2=true`로 두고 핸들러 실행 → langsmith 전송 함수 호출 0회(전송 경로를 막아 확인), 네트워크 호출 0회.
    - _Requirements: 13.1–13.8, 12.3, 19.6 · BE-Q89, BE-Q92_
  - [x] 9.7 Write property test for 유출 방지 (`tests/unit/test_ai_properties.py`)
    - **Property 34: 어떤 사연·카드·시나리오에서도 로그와 trace에 사연·카드 문자열(4자 이상 부분 문자열)이 나오지 않는다**
    - 생성기: 임의 사연(개인정보 표본 포함), Fake 응답 카드, 시나리오.
    - **Validates: Requirements 4.9, 13.1, 13.2, 13.8**

- [x] 10. Checkpoint B - AI 경로 단위 테스트와 회귀
  - `pytest tests/unit` 실패 0건(296건 포함), Property 29–36 중 지금까지의 7개 통과, `test_ai_cancel.py`의 반환 시간 최댓값 기록. 실제 공급자 호출 0회(스텁·Fake만, 소켓 대상은 127.0.0.1뿐인지 테스트가 확인).
  - _Requirements: 8.6, 8.7, 19.13_

- [x] 11. `POST /plans` AI 지표 (`domain/ai_metrics.py`, `plan_service.py`)
  - 선행: 3.3
  - [x] 11.1 `domain/ai_metrics.py`: design §16.2 계산식 전부(순수 함수, AI 패키지 import 없음), `fieldsEditedAfterHandoff` 비교 단위.
    - _Requirements: 14.3 · BE-Q79_
  - [x] 11.2 `plan_service.compute_metrics`: `AI_EDITED` + `aiSessionId`일 때만 `get_live_session`(기존 테이블 클라이언트), 제외 사유(없음·만료·소유자 다름·`READY` 아님·읽기 실패·계산 예외)는 로그 사유 코드만, Plan 생성은 막지 않음. 기존 네 지표·본문 해시·멱등 경로 불변.
    - _Requirements: 14.1, 14.2, 14.4–14.8 · BE-Q79_
  - [x] 11.3 단위 테스트 (`tests/unit/test_ai_metrics.py`, `test_plan_service_moto.py`·`test_handlers.py` 보강)
    - 계산식 각 지표, 비교 단위 예(design §16.2), `whyChosen` `null` = `""`, 장소 수가 다를 때, `editMs` 음수 → 0.
    - 제외 사유 6종 → AI 지표 없이 201(응답 본문은 지표 외 같음), `MANUAL` → 세션 조회 0회(+ `aiSessionId`가 와도), 멱등 재요청 → 지표 불변·세션 조회 0회.
    - **기존 `MANUAL` 경로 회귀**: 1·2단계 Plan 테스트 전부 통과, `MANUAL` 요청의 저장 항목·응답이 6a 전과 같음(같은 입력으로 비교).
    - _Requirements: 14.1–14.8, 19.7_
  - [x] 11.4 의존성 분리 테스트 (`tests/unit/test_ai_isolation.py`): 하위 프로세스에서 `langgraph`·`langchain*`·`openai`·`langsmith` import를 막고 `handlers.plans`·`handlers.me`·`handlers.claims`·`domain.ai_metrics`·`domain.ai_session_service`를 import하고 `compute_metrics`를 표본 세션으로 실행. 다른 핸들러가 `agent`를 import하지 않음(AST).
    - _Requirements: 16.3, 15.9_

- [x] 12. SAM 템플릿 (`template.yaml`, `samconfig.toml`, `src/Makefile`)
  - 선행: 2.2, 9.4
  - [x] 12.1 Parameters: `Stage`(5단계와 같은 정의), `LlmProvider`(`openai_compat`·`fake`), `LlmBaseUrl`, `LlmModel`, `LlmApiKeyParam`(`AllowedPattern`), `LlmProviderLabel`, `LlmTemperature`, `LlmMaxTokens`, `LlmConnectTimeoutS`, `LlmReadTimeoutS`, `LlmExtraBody`, `LlmToolChoice`, `LlmParallelToolCalls`, `AgentMode`(`AllowedValues: [pipeline]`), `AiDailySessionLimit`. Rules(Fake는 dev만), Conditions(`IsDev`, `FakeAllowed`, `HasLlmKeyParam`). `samconfig.toml`: dev `Stage=dev`, demo `Stage=demo`, 공급자 값은 넣지 않음.
    - _Requirements: 15.2, 15.10 · BE-Q86, BE-Q87_
  - [x] 12.2 `AiCardFunction`: `CodeUri: src/`, `Metadata.BuildMethod: makefile`, `Handler: handlers.ai_card.handler`, 27초, 1024MB, x86_64, 이벤트 3개, 환경 변수(`LLM_PROVIDER`는 `!If FakeAllowed`, `FAKE_LLM_ALLOWED`, `LLM_API_KEY_PARAM`은 조건부, `LLM_API_KEY` 없음, AI SDK 설정 값), 정책(design §14.3: LeadingKeys, 조건부 SSM). Globals의 LangSmith 변수 2개 유지.
    - _Requirements: 12.1, 15.1–15.6, 7.5 · BE-Q81, BE-Q84_
  - [x] 12.3 HttpApi `RouteSettings`: 경로 3개 임시값(design §19.2).
    - _Requirements: 15.7 · BE-Q82, BE-Q92_
  - [x] 12.4 `src/Makefile`: `build-AiCardFunction`(design §17.1).
    - _Requirements: 16.4, 16.5, 16.7 · BE-Q80_
  - [x] 12.5 템플릿 단위 테스트 (`tests/unit/test_template.py`): AiCardFunction 설정 전부, `LLM_API_KEY` 미정의, LangSmith 변수 2개·API 키 변수 없음, IAM(액션 3개·LeadingKeys 2개·`Query`/`Scan`/`index/*`/`GetParameters*`/`kms:*` 없음, SSM 문장 조건부·ARN 하나), RouteSettings 3개, Rules·Conditions 평가(5단계 fault guard 테스트 방식: `Stage`·`LlmProvider`·스택 이름 조합별 결과), `AgentMode` AllowedValues, 다른 함수 불변(권한·환경 변수·CodeUri), `HaruAgentCheckpoints` 리소스 없음, 경로가 `routes.py`와 같음.
    - _Requirements: 15.1–15.10, 19.8_

- [ ] 13. 빌드 검증 (`scripts/check_ai_build.py`)
  - 선행: 12
  - [ ] 13.1 `scripts/check_ai_build.py`: design §17.3의 1–5(다른 함수 금지 패키지 검사, AiCardFunction 크기·상위 패키지·250MB, 런타임 컨테이너 import 시간 5회·그래프 Fake 1회·`zoneinfo`, **각 Lambda 산출물 독립 import·실행**(인증 없는 이벤트 → 401, `sys.modules` 검사, `PlansFunction`의 `ai_metrics` 계산, PreSignUp 표본 이벤트), 결과 JSON 출력).
    - _Requirements: 16.3, 16.6, 16.8 · BE-Q18_
  - [ ] 13.2 `cfn-lint template.yaml` 0건, `sam validate --lint` 통과, `sam build --use-container` 성공. `--require-hashes` 동작 확인(2.2).
    - _Requirements: 15.8, 16.7_
  - [ ] 13.3 `check_ai_build.py` 실행과 기록: 압축 해제·zip 크기, import 시간(중앙값·최댓값), 함수별 독립 실행 결과를 README 초안에 적고 설계 단계 값(125.4MB, 49.8MB, 0.74–0.91초)과 비교. 배포 형식은 SAM ZIP 유지.
    - _Requirements: 16.8 · BE-Q18_

- [ ] 14. Checkpoint C - SAM·빌드
  - 13.2·13.3 통과, `pytest tests/unit` 실패 0건(296건 포함). 다른 함수 산출물에 AI 패키지 0개, 각 함수 독립 실행 통과.
  - _Requirements: 15.8, 16.3, 19.13_

- [ ] 15. 로컬 환경과 로컬 통합 테스트
  - 선행: 9, 11, 13
  - [ ] 15.1 `docker-compose.yml`(design §17.4·Requirement 17.1의 환경 변수, `STAGE=local`, `FAKE_LLM_ALLOWED=true`, `AGENT_MODE=pipeline`, LangSmith 2개 유지), `local/adapter/Dockerfile`(잠금 파일 설치, 시간대 데이터 확인), `.env.example`(`LLM_PROVIDER=fake`, 빈 `LLM_API_KEY`, 실모델 전환 주석). `local/init` 변경 없음. 리눅스 umask 문제는 `chmod -R go+rX local src` 뒤 기동(README 기존 절차).
    - _Requirements: 17.1–17.4, 13.4_
  - [ ] 15.2 `tests/local/test_local_ai.py`(마커 `local`): design §20.4 — 생성 → GET → turns(409·200) → `POST /plans`(`AI_EDITED`, DynamoDB에서 지표 확인) → 같은 사용자 `MANUAL` 공개 정상, 남의 세션 404, 11번째 429(전용 사용자), 만료 세션(ttl 과거로 바꾼 항목) 404·지표 제외. `FAKE_LLM_SCENARIO`를 바꿔 띄웠을 때만 도는 사례: `http_401`·`http_429` → 503, `bad_json` → 502, `privacy_high` → degraded. 결과에 `llmMode: fake`.
    - _Requirements: 19.9, 14.1, 5.8_
  - [ ] 15.3 `tests/local/test_local_checkpointer.py`(마커 `local`): design §18 — Floci `HaruAgentCheckpoints`에 `DynamoDBSaver(consistent_read=True, ttl_seconds, boto_config=AI SDK)`로 동기·비동기 각각 interrupt → `get_state` 대기 interrupt → `Command(resume)` → 결과, 항목마다 `ttl`, `delete_thread` 뒤 그 스레드 0건. 스레드 ID `t6a_` + 임의값, 실패해도 정리. 제품 경로에 연결하지 않음.
    - _Requirements: 16.9 · BE-Q21, BE-Q84_
  - [ ] 15.4 로컬 실행: `docker compose up -d --build` 후 `pytest -m local tests/local` — **기존 16건 + 새 사례 전부 통과**, 조건부 사례는 해당 환경 변수로 한 번씩 다시 띄워 실행. 건수·날짜·기준 커밋을 기록. T 판정 근거 아님(BE-Q15).
    - _Requirements: 19.9, 19.13_

- [ ] 16. AWS 통합 테스트 작성 (`tests/integration/test_ai.py`, 실행·판정은 AWS 담당)
  - 선행: 9, 15
  - [ ] 16.1 `conftest.py`: 테스트가 만든 `sessionId`와 `AIQUOTA#{sub}#{KST 날짜}`를 정리 대상으로 등록해 지우는 확장(기존 Cognito·`PLAN#`·`USER#`·`IDEM#` 정리 유지), 함수 환경 변수 읽기 헬퍼(`lambda:GetFunctionConfiguration`), 결과 파일에 `scenario`·`llmMode`. `tests/unit/test_integration_cleanup.py`에 새 정리 대상 사례 추가.
    - _Requirements: 19.10–19.12_
  - [ ] 16.2 `test_T12_invalid_key`(마커 `fault`): 함수가 `LLM_PROVIDER=openai_compat`이고 `LLM_API_KEY_PARAM`이 있을 때만 판정, 아니면 사유 있는 skip("실제 공급자 없음, T12 미검증"). 합성 사연 → 503 `AI_UNAVAILABLE`, AiSession `FAILED`·`llmError=HTTP_401`, 그 사용자 Plan 0건. **실제 공급자 검증 전까지 미검증으로 유지**하고 skip·보조 사례를 통과로 세지 않는다.
    - _Requirements: 19.10 · T12, BE-Q83_
  - [ ] 16.3 `test_T12_aux_ssm_missing`(마커 `fault`): 파라미터 없음 → 503·`KEY_READ_FAILED`, 결과 파일 `scenario: "T12-aux-ssm-missing"`, T12 통과로 세지 않음.
    - _Requirements: 19.11 · BE-Q83_
  - [ ] 16.4 `test_ai_routes_fake`(기본, 함수 `LLM_PROVIDER=fake`인 dev에서만): 생성·GET·turns·남의 세션 404·11번째 429, 결과 `llmMode: fake`(공급자 품질 근거 아님). T1이 AI 경로 3개를 포함하는지 확인.
    - _Requirements: 19.12, 15.10 · BE-Q86_
  - [ ] 16.5 수집 확인: `pytest -m integration tests/integration --collect-only`, `pytest -m "integration and fault" tests/integration --collect-only` 오류 없음(실행 안 함). `STACK_NAME` 없이 실행하면 모두 skip.
    - _Requirements: 19.10–19.12_

- [ ] 17. Checkpoint D - 전체 회귀와 변경 범위
  - `pytest tests/unit` 실패 0건(1–3단계 296건 포함), Property 29–36 **8개 모두** 통과, `pytest -m local tests/local` 기존 16건 + 새 사례 통과, 통합 테스트 수집 성공, cfn-lint·`sam validate --lint`·`sam build --use-container`·`check_ai_build.py` 통과.
  - 변경 범위(`git diff fix/be-3-local-verify`): `claim_service.py` 0줄, `ddb.py`는 `use_table`만, `fidelity.py`·`privacy.py` 0줄, `docs/03` 0줄, `frontend/` 0줄, 다른 함수의 템플릿 속성 불변. 결과를 PR 본문 초안에 적는다.
  - _Requirements: 19.13, 20.1, 20.2_

- [ ] 18. 인계 문서와 커밋
  - 선행: 17
  - [ ] 18.1 `backend/README.md`: 6a 현황, 배포 전 주의(SecureString 먼저 생성 절차, `sam build --use-container`, `AGENT_MODE=pipeline`, 공급자 값 미정, Fake dev 허용 조건), 함수별 IAM 표(AiCardFunction), 판정 실행표(T12 미검증·보조 사례·Fake 경로 확인 구분), 빌드 측정값(13.3), 취소 반환 시간(7.7), Floci `DynamoDBSaver` 결과(15.3), 공급자 실측 양식(Requirement 8.5), 429 세 종류, 알려진 한계(휴리스틱 한계 11.11, 마스킹 안 함 BE-Q10, 강제 종료·저장 불확실 시 세션 없음·할당량 소모 BE-Q74·BE-Q89, 취소 지연, `dev` Plan 지표는 품질 분석에 쓰지 않음), 4·5단계 병합 뒤 통합 회귀 계획(작업 22).
    - _Requirements: 20.4, 20.5, 5.5, 12.6, 11.11_
  - [ ] 18.2 `docs/08-open-questions.md`: BE-Q18·BE-Q21의 6a 결과(확인한 것·남은 것), BE-Q6·BE-Q9·BE-Q12의 현황(미결 유지), BE-Q73–BE-Q92 추가(결정·권장안·임시·미결 구분, 결정되지 않은 것을 결정처럼 쓰지 않음), §8.3에 6a 행.
    - _Requirements: 20.6_
  - [ ] 18.3 커밋(push 안 함): spec, 공통·잠금, 서비스, 검사·프롬프트, LLM·그래프, 핸들러, Plan 지표, 템플릿·빌드, 로컬, AWS 테스트, 문서 순서의 의미 단위.
    - _Requirements: 20.7_

### 공급자 승인 의존 (BE-Q6·BE-Q7·BE-Q10 확정 뒤)

- [ ] 19. 실제 공급자 연결과 실측 **[대기: 공급자·모델 승인(BE-Q6), 동의 문구(BE-Q7), 전송 전 마스킹 결정(BE-Q10)]**
  - 선행: 18, 팀 승인
  - [ ] 19.1 BE-Q10이 "마스킹한다"로 정해지면 `neutralize` 뒤에 `scan_privacy` 마스킹을 더하고, 원문 대조 근거를 마스킹된 사연으로 바꾸는 변경을 별도 spec 수정과 함께 한다. "안 한다"면 그대로 둔다.
  - [ ] 19.2 LLM 담당: 합성 사연(`tests/fixtures`)으로 실측 양식(README)을 채운다 — 요청 필드 수용(`max_completion_tokens`·`max_tokens`·`temperature`·`extra_body`), usage 반환, 호출 지연 p50·p95(BE-Q12), 오류 응답 형태. 필요하면 `LLM_EXTRA_BODY`·`LLM_TEMPERATURE` 값을 정한다(BE-Q9).
  - [ ] 19.3 `samconfig.toml` dev에 승인된 `LlmBaseUrl`·`LlmModel`·`LlmApiKeyParam`·`LlmProviderLabel`을 넣는 변경(AWS 담당과 함께, 키 값은 넣지 않음).
  - [ ] 19.4 프론트·동의 문구에 `LLM_PROVIDER_LABEL`과 같은 값을 쓰도록 프론트 담당에게 전달(FE-Q6).
  - _Requirements: 8.5, 8.7, 7.12 · BE-Q6, BE-Q7, BE-Q9, BE-Q10, BE-Q12_

### 프론트·팀 리뷰 의존

- [ ] 20. 리뷰 결과 반영 **[대기: 프론트엔드 담당 리뷰(BE-Q76·BE-Q92·BE-Q13/FE-Q7), 팀 리뷰(BE-Q73·BE-Q86·BE-Q82)]**
  - 선행: 18
  - [ ] 20.1 BE-Q76: trace `tool` 이름·문구, 메모 문구가 바뀌면 `nodes.py`·`repair.py`와 테스트를 고친다(계약 형태는 그대로).
  - [ ] 20.2 BE-Q92: API Gateway 스로틀 429 본문을 계약 예외로 docs/03에 적을지 프론트와 정한다. 적기로 하면 docs/07 §7.2 절차(docs/03 수정 PR → 승인)로 한다.
  - [ ] 20.3 BE-Q13·FE-Q7: `REMOVED` 메모에 원래 값·유형을 담기로 하면 계약 변경 절차를 따른 뒤 구현한다(이 spec 밖일 수 있음).
  - [ ] 20.4 BE-Q73: UTC로 바뀌면 `quota_day`와 경계 테스트만 바꾼다. BE-Q86: Fake dev 허용이 거부되면 `LlmProvider` 파라미터·Rules·조건·런타임 허용을 지우고 `test_ai_routes_fake`를 뺀다. BE-Q82: 스로틀 값이 정해지면 템플릿·테스트 값을 바꾼다.
  - _Requirements: 4.9, 6.5, 15.7, 15.10 · BE-Q13, BE-Q73, BE-Q76, BE-Q82, BE-Q86, BE-Q92_

### AWS 판정 의존 (AWS 담당이 실행)

- [ ] 21. `dev` 배포와 판정 **[대기: AWS 담당 일정. 개발 담당은 실행하지 않는다]**
  - 선행: 18, 21.1은 19 뒤
  - [ ] 21.1 T12: 실제 공급자 엔드포인트가 설정된 `dev`에서 `LlmApiKeyParam`이 잘못된 키 값을 가진 파라미터를 가리키게 배포 → `test_T12_invalid_key`. 그 전까지 T12는 **미검증**이다.
  - [ ] 21.2 보조·경로 확인: `test_T12_aux_ssm_missing`(보조), Fake 허용 dev에서 `test_ai_routes_fake`, T1(AI 경로 포함). 결과는 `llmMode`와 함께 기록하고 공급자 품질 근거로 쓰지 않는다.
  - [ ] 21.3 AWS 전용 확인: Init Duration·최대 메모리(BE-Q18, 메모리 조정), `timeEpoch` 기준 남은 시간과 콜드 스타트(BE-Q90), `dynamodb:LeadingKeys`가 `PLAN#` 쓰기를 막는지(정책 시뮬레이터 또는 시험 호출), SSM 키 읽기·캐시, 경로 스로틀 429(본문 형태 기록), Fake 차단 세 겹(`demo`에 `LlmProvider=fake` 변경 세트가 Rules로 거부), `AgentMode`에 `agent` 거부.
  - [ ] 21.4 회귀: `test_concurrency.py`(T3·T4·T5·T14), T6·T7·T13·T16.
  - _Requirements: 15.3–15.10, 16.8, 19.10–19.12 · T1, T12, BE-Q18, BE-Q83, BE-Q90_

### 4·5단계 병합 뒤

- [ ] 22. 통합 회귀 **[대기: 4단계(PR #1)·5단계(PR #7) 병합]**
  - 선행: 18, 4·5단계 병합
  - [ ] 22.1 4·5단계가 들어간 기준 브랜치로 병합(rebase 없음, 사용자 확인). 충돌 해결 원칙: `metrics.emit`·`ddb.use_table`은 같은 함수 하나로, `Stage` 파라미터 하나, `routes.py`·`errors.py`·`validation.py`·`test_template.py`·`conftest.py`·`docker-compose.yml`·`local/adapter/*`는 합치기, docs/08은 번호가 겹치지 않으므로 합치기.
  - [ ] 22.2 전체 회귀: 단위 전체(1–5단계 + 6a, Property 12–15·18–23·25–36), 로컬 전체(1–5단계 + 6a), `check_ai_build.py`(Pillow 레이어·사진 처리 함수 포함 모든 함수에 AI 패키지 없음, 각 함수 독립 실행), cfn-lint·`sam validate --lint`·`sam build --use-container`.
  - [ ] 22.3 AWS 판정 요청: T1·T2·T12와 이전 단계 회귀(T3–T11·T13–T17)를 AWS 담당에게 넘긴다.
  - _Requirements: 20.3, 20.4_

### PR

- [ ] 23. 6a PR **[사용자 확인 필요]**
  - 선행: 18 (19–22와 독립. 끝나기 전이면 그 사실을 본문에 적는다)
  - push는 이 브랜치만 명시적으로 한다. PR은 Draft, base는 그때 병합 상태에 따라 사용자와 정한다(`fix/be-3-local-verify` 또는 병합된 기준 브랜치). 본문에 요구사항·BE-Q 번호, 단위·로컬 결과, 빌드 측정, T12 미검증과 판정 절차, 변경 범위 확인(17), 공급자·프론트·팀·AWS 대기 항목을 적는다.
  - _Requirements: 20.7_

## Notes

- 속성과 작업: P29 → 4.5, P30 → 4.6, P31 → 3.6, P32 → 6.4, P33 → 3.7, P34 → 9.7, P35 → 8.3, P36 → 8.4. 모두 필수다. 1–3단계 속성(Property 1–15 중 해당분)은 Checkpoint마다 회귀로 확인한다.
- Fake 테스트만으로 끝내지 않는다. `ChatOpenAI`의 요청·응답·예외·취소는 로컬 HTTP 스텁(7.5–7.7)으로 같은 시나리오를 다시 확인한다.
- AWS에서만 판정하는 항목: T12(실제 공급자 401), Init Duration·메모리, `timeEpoch`와 HTTP API 30초, IAM `LeadingKeys`, SSM 키 읽기, 경로 스로틀, Fake·`AgentMode` 차단, 실제 병렬성에서 AiQuota 한도.
- 강제 종료를 완전히 막는다고 가정하지 않는다. 남는 결과(세션 없음, 할당량 1 소모, 500 뒤 세션이 남을 수 있음)는 테스트가 아니라 문서로 남긴다.
- 새 테스트 파일: `test_ai_card_schema.py`, `test_ids.py`(없으면 신규), `test_ai_lock.py`, `test_ai_session_service.py`, `test_ai_checks.py`, `test_ai_prompt.py`, `test_ai_timebudget.py`, `test_ai_llm.py`, `test_ai_llm_stub.py`, `test_ai_fake_vs_stub.py`, `test_ai_cancel.py`, `test_ai_graph.py`, `test_handlers_ai_card.py`, `test_ai_save_uncertain.py`, `test_ai_429.py`, `test_ai_logging.py`, `test_ai_tracing.py`, `test_ai_metrics.py`, `test_ai_isolation.py`, `test_ai_properties.py`, `llm_stub.py`(헬퍼), `tests/local/test_local_ai.py`, `tests/local/test_local_checkpointer.py`, `tests/integration/test_ai.py`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5", "2.1"] },
    { "id": 1, "tasks": ["1.6", "2.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "3.1", "4.1", "6.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.2", "6.2"] },
    { "id": 4, "tasks": ["3.4", "4.3", "6.3", "6.4", "7.1"] },
    { "id": 5, "tasks": ["3.5", "3.6", "3.7", "4.4", "4.5", "4.6", "7.2"] },
    { "id": 6, "tasks": ["5"] },
    { "id": 7, "tasks": ["7.3", "7.4", "7.5"] },
    { "id": 8, "tasks": ["7.6", "7.7", "11.1"] },
    { "id": 9, "tasks": ["8.1", "11.2"] },
    { "id": 10, "tasks": ["8.2", "8.3", "8.4", "11.3", "11.4"] },
    { "id": 11, "tasks": ["9.1", "9.4"] },
    { "id": 12, "tasks": ["9.2", "9.3"] },
    { "id": 13, "tasks": ["9.5", "9.6", "9.7"] },
    { "id": 14, "tasks": ["10"] },
    { "id": 15, "tasks": ["12.1", "12.4"] },
    { "id": 16, "tasks": ["12.2", "12.3"] },
    { "id": 17, "tasks": ["12.5"] },
    { "id": 18, "tasks": ["13.1"] },
    { "id": 19, "tasks": ["13.2"] },
    { "id": 20, "tasks": ["13.3"] },
    { "id": 21, "tasks": ["14"] },
    { "id": 22, "tasks": ["15.1"] },
    { "id": 23, "tasks": ["15.2", "15.3"] },
    { "id": 24, "tasks": ["15.4", "16.1"] },
    { "id": 25, "tasks": ["16.2", "16.3", "16.4"] },
    { "id": 26, "tasks": ["16.5"] },
    { "id": 27, "tasks": ["17"] },
    { "id": 28, "tasks": ["18.1", "18.2"] },
    { "id": 29, "tasks": ["18.3"] },
    { "id": 30, "tasks": ["19.1", "19.2", "20.1", "20.2", "20.3", "20.4", "21.2", "21.3", "21.4", "23"] },
    { "id": 31, "tasks": ["19.3", "19.4"] },
    { "id": 32, "tasks": ["21.1", "22.1"] },
    { "id": 33, "tasks": ["22.2"] },
    { "id": 34, "tasks": ["22.3"] }
  ]
}
```
