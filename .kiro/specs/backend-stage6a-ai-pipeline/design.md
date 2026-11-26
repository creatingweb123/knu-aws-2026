# Design Document: backend-stage6a-ai-pipeline

## Overview

백엔드 6a(AI 하루 카드 레벨 0, card-sessions 계약, AiQuota)의 설계다. 근거는 같은 폴더의 `requirements.md`(승인됨)와 `docs/02` §2.2–§2.10, `docs/03` §3.2·§3.3·§3.6, `docs/04` §4.3–§4.6, `docs/06` BE-AI·BE-PLAN-03·BE-INFRA-05–08, `docs/07` §7.3 6a다.

설계 원칙
- 계약(docs/03)과 DynamoDB 키 설계(docs/02 §2.6)는 바꾸지 않는다. 3단계 `claim_service`·`transact_with_retry`(G1–G4)는 손대지 않는다.
- 모델은 초안만 만든다. 판정(스키마·원문 대조·개인정보)은 코드가 하고, 저장은 핸들러가 하고, 공개는 계획자가 `POST /plans`로만 한다(G6).
- 레벨 0도 6b와 같은 `StateGraph` 골격·상태 이름·설정 전달 방식을 쓴다. 6b는 `rules` 자리에 `decide`를 연결하고 체크포인터를 붙인다.
- 외부 전송은 기본으로 막는다. 개발·테스트는 Fake 채팅 모델과 로컬 HTTP 스텁으로 하고, BE-Q6·BE-Q7·BE-Q10 확정 전에는 실제 사용자 사연을 외부 LLM으로 보내지 않는다.
- 시간 설계는 강제 종료 가능성을 줄일 뿐 없애지 못한다. 남는 결과(세션 없음, 할당량 1 소모)는 문서에 적는다.

### 이번 설계의 결정 (사용자 지시 반영)

| # | 결정 |
|---|---|
| BE-Q87 | `AGENT_MODE`가 없으면 `pipeline`. `pipeline`이 아닌 값(`agent` 포함, 알 수 없는 값)은 **조용히 레벨 0으로 바꾸지 않는다.** 할당량을 쓰기 전에 설정 오류로 503 `AI_UNAVAILABLE`(사유 `CONFIG_AGENT_MODE`)을 돌려주고, 템플릿 파라미터는 6a에서 `AllowedValues: [pipeline]`로 배포 단계에서도 막는다. 기존 비종료 세션과 6b 전환 호환성은 미결로 남긴다 |
| BE-Q88 | Final_Check는 "플래그가 하나도 없어야 통과"가 아니다. `MISSING`, Fallback이 `KEPT_FLAGGED`로 명시한 활동의 `NOT_IN_SOURCE`, `MEDIUM` 개인정보(`PRIVACY` 플래그)는 남을 수 있다. 차단: 스키마 오류, `HIGH` 개인정보, 장소(`places[i].name`·`activity`)의 비공개 장소, 원문에 없는 장소 이름, 명시적 허용이 없는 활동 `NOT_IN_SOURCE` |
| BE-Q79 | 지표별 계산식과 비교 단위를 §16에 고정한다. `firstProposal`·`firstReport`는 첫 값으로 보존하고, `privacyDetected`는 세션 종료 때 한 번 계산해 AiSession에 저장한 값을 쓴다(Gate·Final_Check 재검사는 세지 않는다) |
| BE-Q85 | 5단계 사진 처리 Lambda와 같은 방식으로 AI Lambda 전용 botocore `Config`를 둔다(DynamoDB·SSM·체크포인터 모두 connect 1초, read 2초, standard 모드 총 시도 2회). 공통 설정(BE-Q48)은 바꾸지 않는다 |
| 시간 부족 | 남은 시간이 부족해 첫 LLM 호출을 시작하지 못하면 LLM_Error `TIME_BUDGET`으로 보고 Candidate_Card가 없으므로 `FAILED` + 503 `AI_UNAVAILABLE` |
| BE-Q78 | 전체 deadline은 `asyncio.wait_for`로 비동기 호출을 취소해 지킨다(§12, 로컬 스텁으로 확인) |
| BE-Q80 | SAM Makefile 커스텀 빌드(`CodeUri: src/`, `BuildMethod: makefile`). `--use-container`에서 동작함을 확인했다(§17) |
| BE-Q76 | `places`는 항상 배열이고 모두 빠지면 `[]` + `MISSING(places)`. 프론트 `types.ts`(`places: … [] \| null`)와 맞다. trace 단계 이름은 §10.4 제안(프론트 리뷰 대상) |
| BE-Q89 | 저장 요청이 타임아웃·오류로 끝나도 실제로는 커밋됐을 수 있다. 남은 시간이 있으면 강한 일관성 조회로 확인하고, 확정하지 못하면 500 `INTERNAL_ERROR`. 할당량은 환불하지 않는다(§4.4) |
| BE-Q91 | 정상적인 `null`(키 없음·`null`·빈 문자열)과 스키마 위반(타입·범위·길이·개수·모양)을 구분한다. 위반만 시간 예산 안에서 최대 1회 재시도하고, 유효한 후보가 없으면 502(§3.1) |
| BE-Q92 | 429 세 종류를 구분한다: API Gateway 스로틀(계약 형식 아님, 계약 예외·프론트 리뷰), `AI_QUOTA_EXCEEDED`(계약), 공급자 429(→ LLM_Error `HTTP_429` → 503 `AI_UNAVAILABLE`)(§19.1) |
| `llmMode` | AiSession 내부 속성과 테스트 결과 파일에만 둔다. SessionView·Plan `metrics`에는 넣지 않는다(계약 변경 없음). Fake 세션은 품질 평가에서 뺀다(§15.1) |
| 배포 형식 | SAM ZIP 배포를 유지한다(컨테이너 이미지 배포 안 함). 전체 의존성 잠금 파일로 설치하고, 최종 빌드에서 크기·import 시간을 다시 잰다(§17) |

### 설계 검증 결과 (2026-11-26, 개발 PC, 저장소 밖 `/tmp/haru6a-probe`에서 확인, 제품 코드 아님)

| 항목 | 방법 | 결과 |
|---|---|---|
| 의존성 해석 | `uv pip compile`(대상 `--python-version 3.12 --python-platform x86_64-manylinux_2_28`), 직접 의존성 docs/02 값 + `pydantic==2.14.4`·`python-ulid==4.2.0`(공통과 같게) | 충돌 없이 52개로 해석. `boto3==1.44.12`, `openai==3.59.0`, `httpx==0.28.1`, `langsmith==0.16.2`, `tiktoken==0.14.0`, `langgraph-prebuilt==1.1.3`, `langgraph-sdk==0.4.14`, `ormsgpack==1.13.1`, `xxhash==4.1.0`, `zstandard==0.25.0` 등 |
| Makefile 빌드 + `--use-container` | 임시 SAM 프로젝트(일반 함수 + `BuildMethod: makefile` 함수, 둘 다 `CodeUri: src/`), SAM CLI 1.174.1, `sam/build-python3.12` 이미지 | **성공**(22초). Makefile 함수에 공통 폴더 복사 + 잠금 파일 `--only-binary=:all: --no-deps` 설치. 일반 함수 산출물에는 AI 패키지 0개(대신 `Makefile`·잠금 파일 몇 KB가 같이 복사됨) |
| 패키지 크기 | 산출물 측정 | 압축 해제 **125.4MB**(한도 250MB), zip **49.8MB**. 큰 패키지: `openai` 28M, `botocore` 28M, `zstandard` 23M, `langsmith` 11M, `langchain_core` 5.6M, `pydantic_core` 5.3M, `tiktoken` 3.7M |
| import | `public.ecr.aws/lambda/python:3.12`(Python 3.12.16) 런타임 이미지에 산출물을 `/var/task`로 붙여 import | 성공. `langgraph.graph`·`langchain_openai`·`langgraph_checkpoint_aws` import **0.74–0.91초**(개발 PC CPU 기준. Lambda Init Duration은 AWS 담당이 측정, BE-Q18) |
| 시간대 데이터 | 같은 런타임 이미지 | `/usr/share/zoneinfo/Asia/Seoul` 있음, `zoneinfo.ZoneInfo("Asia/Seoul")` 동작(UTC 2026-11-26 15:00 → KST 11-27 00:00) |
| `ChatOpenAI` 요청 형태 | 실제 `ChatOpenAI`(langchain-openai 1.8.5) → 프로세스 안 로컬 HTTP 스텁 | 경로 `/v1/chat/completions`(Responses API 아님). `max_tokens=800` → `max_completion_tokens: 800`, `extra_body={"max_tokens":800}`은 본문에 그대로 합쳐짐. `temperature`는 넘기지 않으면 본문에 없음. usage가 없으면 `usage_metadata = None`. 재시도 0(호출 1회) |
| 오류 클래스 | 스텁이 상태 코드를 돌려줌 | 400·401·403·404·429·500·503 모두 langchain-openai의 래퍼(`OpenAIInvalidRequestError`, `OpenAIAuthenticationError`, …)이고 전부 `openai.APIStatusError` 하위 타입. 연결 거부 → `OpenAIConnectionError`(`APIConnectionError` 하위). 연결 타임아웃 → 2.0초에 `OpenAITimeoutError`(`APITimeoutError`이면서 `APIConnectionError`) |
| 느린 응답 | 스텁이 응답 바이트를 0.5초마다 1바이트씩 보냄 | 동기 호출은 12초가 지나도 끝나지 않음(read 8초 타임아웃이 걸리지 않음, **BE-Q78 위험 확인**). `asyncio.wait_for(ainvoke, 3초)`는 **3.00초에 끊겼고, 스텁 쪽에서 연결이 닫힘(3.54초)** |
| 이벤트 루프 | `asyncio.run`을 호출마다 새로 함(Lambda 호출마다 하는 방식) | 모듈 전역 `ChatOpenAI` 하나를 재사용하면 두 번째 실행에서 `RuntimeError: Event loop is closed`. 호출마다 `httpx.AsyncClient`를 만들어 `http_async_client`로 넘기고 닫으면 매번 성공 |
| LangGraph 골격 | `StateGraph` 6노드(조건부 엣지 2개), 체크포인터 없이 `compile()`, `ainvoke` | 동작. `checkpointer = None`, `config["configurable"]` 값이 노드에 전달됨. `LANGSMITH_TRACING=true`로 바꿔도 `tracing_context(enabled=False)` 안에서 정상 실행 |
| Floci `DynamoDBSaver` | `floci/floci:2.5.0-compat`(실행 중인 로컬 compose)의 `HaruAgentCheckpoints`, `consistent_read=True`, `ttl_seconds`, 짧은 `boto_config` | **동기·비동기 모두 성공**: `interrupt` → `get_state`의 대기 interrupt 확인 → `Command(resume)` → 결과, 항목마다 `ttl` 있음, `delete_thread` 뒤 0건. 짧은 스레드 1개가 항목 18개(`CHECKPOINT_`·`CHUNK_`·`WRITES_`)를 씀. 시험 항목은 지웠다 |
| SecureString | AWS 문서 `AWS::SSM::Parameter` | "Parameters of type `SecureString` are not supported by AWS CloudFormation"(`Type`은 `String`·`StringList`만) |
| `aws/ssm` 키 | AWS 문서 Parameter Store 접근 제어 | 기본 AWS 관리형 키는 계정 안 모든 IAM 주체에 `Decrypt`를 허용한다. 그래서 `kms:Decrypt`를 따로 주지 않아도 되고, **SSM 권한을 가진 주체는 누구나 키를 읽을 수 있으므로** 다른 함수에는 SSM 권한을 주지 않는다 |
| 경로 스로틀 | `AWS::Serverless::HttpApi.RouteSettings` + `sam validate --lint`, samtranslator 변환 | 통과. `$default` 스테이지 `RouteSettings`에 route key(`POST /ai/card-sessions`)별 `ThrottlingBurstLimit`·`ThrottlingRateLimit`로 들어감 |

### 요구사항 매핑

| requirements.md | 이 문서 |
|---|---|
| Req 1–3 API | §4 |
| Req 4 SessionView | §3.3, §10 |
| Req 5–6 저장·할당량 | §5, §6 |
| Req 7–8 LLM·Fake·스텁 | §11, §12 |
| Req 9–11 그래프·프롬프트·검사 | §7, §8, §9, §10 |
| Req 12 시간 | §13 |
| Req 13 로그·전송 제한 | §15 |
| Req 14 Plan 지표 | §16 |
| Req 15–17 인프라·빌드·로컬 | §14, §17, §18, §19 |
| Req 18 지표 | §19 |
| Req 19 테스트 | §20 |
| Req 20 범위·병합 | §21 |

## 1. 아키텍처와 6b 확장

```
브라우저 ──HTTP API(JWT authorizer, 경로 스로틀)──▶ AiCardFunction (27s, 1024MB, VPC 밖)
                                                   handlers/ai_card.py
                                                     ├ 입력 검증(pydantic) · AGENT_MODE 확인
                                                     ├ AiQuota 조건부 갱신 ─────────▶ HaruTable AIQUOTA#…
                                                     ├ asyncio.run(graph.ainvoke)   (tracing_context(enabled=False))
                                                     │    draft ─▶ check_draft ─▶ rules ─▶ gate ─┬─▶ final_check ─▶ END
                                                     │      │ (후보 없음)                          └─▶ fallback ─▶ final_check
                                                     │      └──────────────────────────────▶ END
                                                     │    draft만 LLM 호출: ChatOpenAI(호출마다 AsyncClient) / Fake
                                                     │      └─ 키: SSM GetParameter(1회 캐시) / 로컬 .env
                                                     ├ AiSession 최종 상태 PutItem ─▶ HaruTable AISESSION#…
                                                     └ SessionView 또는 계약 에러 + EMF
PlansFunction POST /plans ── AiSession GetItem(ConsistentRead, 읽기만) ─▶ AI 세션 지표 계산(domain/ai_metrics.py)
```

6b 확장 지점(6a는 만들지 않음)
- `rules` 노드 → `decide`(LLM, `bind_tools([check_draft, ask_planner, submit_card])`)로 교체. `gate` 거부 2회까지 `decide`로 되돌리는 엣지, `ask_planner`·`pause` 노드, 예산 조건부 엣지를 더한다.
- 체크포인터: `compile(checkpointer=DynamoDBSaver(...))`, `thread_id = sessionId`, `durability="sync"`. §18에서 Floci 연결을 확인했다.
- 핸들러: 턴 잠금(조건부 갱신), `AI_SESSION_BUSY`, `Command(resume=…)`. 세션 저장 시점(BE-Q74)은 6b에서 잠금과 함께 다시 정한다.
- 상태 필드·`config["configurable"]`의 마감 시각·`llmError` 처리·`fallback`·`final_check`는 그대로 쓴다.

## 2. 모듈과 파일

```
backend/
  src/
    Makefile                      (신규) build-AiCardFunction 타깃
    ai-requirements.in            (신규) 직접 의존성
    ai-requirements.lock          (신규) 전이 포함 == + 해시, 생성 명령을 머리 주석에
    requirements.txt              (변경 없음) 다른 함수용
    common/
      errors.py                   (수정) AI 코드 6개 추가
      validation.py               (수정) AiPlaceDraft, AiCardDraft(Card_Schema), AiSessionCreate, AiTurn, AiAnswer
      ids.py                      (수정) new_session_id() = "ais_" + ULID, is_session_id()
      metrics.py                  (수정) emit(..., unit="Count") — 5단계와 같은 시그니처
      ddb.py                      (수정) use_table(t)만 추가 — 5단계와 같은 함수
    domain/
      ai_session_service.py       (신규) AiSession·AiQuota 저장/조회, KST 날짜, Live_Session 판정, SessionView 직렬화
      ai_metrics.py               (신규) POST /plans용 AI 세션 지표(순수 함수)
      plan_service.py             (수정) compute_metrics가 ai_metrics를 부름
      fidelity.py, privacy.py     (변경 없음)
    agent/                        (신규, AiCardFunction에서만 import)
      state.py                    AgentState(TypedDict), 상수
      card.py                     content → JSON 추출·정규화·Card_Schema 검증
      tools.py                    check_draft, gate_verdict, final_check (순수)
      repair.py                   apply_rules, apply_fallback, 경로·인덱스 계산 (순수)
      prompt.py                   day_card.md 로드, 데이터 블록 조립, prompt_version
      llm.py                      설정 읽기, SSM 키 캐시, ChatOpenAI/Fake 생성, 오류 분류, deadline 호출
      fake_llm.py                 FakeScenarioChatModel
      nodes.py                    draft, check_draft, rules, gate, fallback, final_check 노드
      graph.py                    build_pipeline_graph() (체크포인터 없이 compile)
      timebudget.py               Remaining_Time·LLM_Deadline 계산
    handlers/
      ai_card.py                  (신규) 3개 경로
      routes.py                   (수정) AI 경로 3개
    prompts/day_card.md           (신규)
  template.yaml, samconfig.toml   (수정)
  docker-compose.yml, .env.example, local/adapter/Dockerfile   (수정)
  scripts/check_ai_build.py       (신규) 빌드 산출물 검사·크기·import
  tests/unit/…, tests/local/test_local_ai.py, tests/local/test_local_checkpointer.py, tests/integration/test_ai.py
```

- `domain/ai_session_service.py`·`domain/ai_metrics.py`·`common/*`는 **AI 패키지 없이 import된다.** `PlansFunction`(AI 패키지 없음)이 AiSession을 읽고 지표를 계산하기 때문이다. 단위 테스트가 `sys.modules`에서 `langgraph*`·`langchain*`·`openai`를 막고 두 모듈을 import해 확인한다.
- `agent/`는 `handlers/ai_card.py`만 import한다. 다른 핸들러가 `agent`를 import하지 않는지 테스트로 확인한다.

## 3. 스키마

### 3.1 Card_Schema (`common/validation.py`)

```python
class AiPlaceDraft(BaseModel):       # strict=True, extra="ignore"
    name: str | None       # 있으면 1–30
    activity: str | None   # 있으면 1–60
    whyChosen: str | None  # 있으면 0–120

class AiCardDraft(BaseModel):        # strict=True, extra="ignore"
    title: str | None              # 1–40
    summary: str | None            # 1–120
    reason: str | None             # 1–300
    estimatedMinutes: int | None   # 10–240, bool·float·문자열 거부
    places: list[AiPlaceDraft]     # 0–3
    question: str | None           # 1–80
```

검증 전 정규화(`agent/card.py`, 결정적)
- 알려진 키만 남기고 없는 키는 `null`. `places`가 없거나 `null`이면 `[]`. `places`가 배열이 아니거나 원소가 객체가 아니면 스키마 오류.
- 문자열은 앞뒤 공백을 지우고, 빈 문자열은 `null`(단 `whyChosen`은 `""`를 그대로 둔다. Plan이 0자를 허용하므로).
- 길이·범위·타입 위반은 고치지 않는다(자르거나 바꾸지 않는다). 위반이면 스키마 오류 → 재시도 규칙(§8).

정상적인 빈 값과 스키마 위반의 구분 (BE-Q91)

| 입력 | 판정 |
|---|---|
| 키 없음, `null`, 공백뿐인 문자열(`whyChosen` 제외) | **정상 `null`**(Candidate 통과, `MISSING` 플래그) |
| `places` 키 없음·`null`·`[]` | 정상(`[]`, `MISSING(places)`) |
| 장소 객체의 `name`·`activity`가 `null` | 정상(그 경로 `MISSING`) |
| 문자열 자리에 숫자·불리언·객체·배열 | 위반 `SCHEMA` |
| `estimatedMinutes`가 문자열(`"45"`), 실수(`45.5`, `45.0`), 불리언, 10 미만·240 초과 | 위반 `SCHEMA` |
| 길이 초과(예: `title` 41자) | 위반 `SCHEMA` |
| `places`가 배열이 아님, 원소가 객체가 아님, 4개 이상 | 위반 `SCHEMA` |
| 최상위가 객체가 아님, JSON 아님 | 위반 `NOT_JSON` |
| 알 수 없는 키 | 무시(위반 아님) |

위반만 재시도한다(남은 시간 12초 이상일 때 최대 1회). 두 번째도 위반이거나 시간이 없으면 Candidate_Card가 없으므로 502 `AI_INVALID_OUTPUT`이다. 위반 필드만 `null`로 바꿔 통과시키지 않는다(docs/03 레벨 0 규칙).

### 3.2 Plan_Create_Schema

1·2단계 `PlanCreate` 그대로다(모든 필드 필수, `places` 1–3, `whyChosen` 0–120). READY 카드가 이 스키마를 만족한다고 가정하지 않는다. 빈칸은 `MISSING`으로 알리고, 계획자가 채운 뒤 `POST /plans`에서 1·2단계 검증을 통과해야 Plan이 된다.

| 필드 | Card_Schema | Plan_Create_Schema | `MISSING` 대상 |
|---|---|---|---|
| `title`·`summary`·`reason`·`question` | `null` 허용 | 필수 | 예 |
| `estimatedMinutes` | `null` 허용 | 필수 | 예 |
| `places` | 0–3 | 1–3 | 빈 배열이면 `places` |
| `places[i].name`·`activity` | `null` 허용 | 필수 | 예 |
| `places[i].whyChosen` | `null`·`""` 허용 | `""` 허용 | 아니오 |

### 3.3 SessionView

```json
{ "sessionId": "ais_01J…", "status": "READY", "turn": 1,
  "trace": [ { "step": 1, "tool": "draft", "summary": "초안 작성" }, … ],
  "question": null,
  "card": { "title": …, "summary": …, "reason": …, "estimatedMinutes": …, "places": [ { "name": …, "activity": …, "whyChosen": … } ], "question": … },
  "flags": [ { "path": "estimatedMinutes", "type": "MISSING" } ],
  "notes": [ { "path": "places[1].name", "action": "REMOVED", "reason": "비공개 장소라 동선에서 뺐어요.", "source": "STORY" } ],
  "degraded": false }
```

- `serialize_session_view(item)`이 허용 목록 9개 키만 만든다. `status != READY`면 `card: null`, `flags: []`, `notes: []`. `question`은 6a에서 항상 `null`.
- `card`의 `places`는 항상 배열이다(빈 배열 포함). 장소 하위 필드 `null`은 그대로 내보낸다.

### 3.4 요청 모델

- `AiSessionCreate { story: str(1–1000) }`(strict, extra ignore). `details` 키 `story`.
- `AiTurn { expectedTurn: int(≥1), answer: AiAnswer | None, finish: bool | None }`. `AiAnswer { questionId: str(1–64), choice?: str(1–15), text?: str(1–100), skipped?: Literal[True] }` — `choice`·`text`·`skipped` 중 정확히 하나(모델 검증기). `choice` 15자는 docs/03 `options` 각 15자 이하와 같다. 형태 오류는 400 `VALIDATION_ERROR`(경로 `answer.text` 등).

## 4. API와 오류 분기

### 4.1 `POST /ai/card-sessions`

```
user = get_user(event)                                    # 401은 authorizer/auth.py
body = AiSessionCreate(json)                              # 400 VALIDATION_ERROR (할당량 안 씀)
mode = agent_mode()                                       # 없음→pipeline, 그 밖 → 503 AI_UNAVAILABLE(CONFIG_AGENT_MODE), 할당량 안 씀
now  = utc_now(); budget = TimeBudget(context, event)     # §13
quota.consume(user.id, now)                               # 조건 실패 → 429 AI_QUOTA_EXCEEDED(모델·세션 없음)
                                                          # 스로틀·네트워크 → transact 규칙과 같게 500 INTERNAL_ERROR(사유 QUOTA_WRITE_FAILED)
session_id = new_session_id()
with tracing_context(enabled=False):
    state = asyncio.run(graph.ainvoke(initial_state(body.story), config={"configurable": {"deadline": budget, "finish_requested": False}}))
outcome = decide_outcome(state)                           # READY | FAILED(503) | FAILED(502)
item = build_session_item(user, session_id, body.story, state, outcome, now, ready_at=utc_now())
put_session(item)                                         # attribute_not_exists(PK); 실패 → 500 INTERNAL_ERROR(SESSION_SAVE_FAILED)
emit metrics; return 200 SessionView | 503 | 502
```

결과 판정 `decide_outcome(state)`

| 그래프 결과 | 세션 | 응답 |
|---|---|---|
| `final_card` 있음, Final_Check 통과 | `READY`(`degraded` = Fallback 거침 여부) | 200 SessionView |
| Final_Check 차단(BE-Q88 차단 사유) | `FAILED`(`failureCode = FALLBACK_INVARIANT`) | 502 `AI_INVALID_OUTPUT` |
| Candidate_Card 없음, 마지막 시도 원인 LLM_Error(`TIME_BUDGET`·`KEY_READ_FAILED`·`CONFIG` 포함) | `FAILED`(`failureCode = LLM_ERROR`, `llmError` 분류) | 503 `AI_UNAVAILABLE` |
| Candidate_Card 없음, 마지막 시도 원인 검증 실패 | `FAILED`(`failureCode = INVALID_OUTPUT`) | 502 `AI_INVALID_OUTPUT` |

- 세션 저장 실패·불확실: §4.4. 저장을 확정하지 못하면 카드를 돌려주지 않고 500(BE-Q89). 할당량은 이미 소모됐고 환불하지 않는다.
- 그 밖의 예상하지 못한 예외: 500 `INTERNAL_ERROR`, 로그에는 예외 클래스 이름만.

### 4.2 `GET /ai/card-sessions/{sessionId}`

```
user = get_user(event)
if not is_session_id(id): 404
item = get_live_session(id)            # ConsistentRead, ttl <= now면 None
if item is None or item.ownerId != user.id: 404
return 200 serialize_session_view(item)
```
세 경우의 404는 같은 본문(`error_body(ApiError(NOT_FOUND))`)이다.

### 4.3 `POST /ai/card-sessions/{sessionId}/turns`

```
user; body = AiTurn(json) → 400
if not is_session_id(id): 404
item = get_live_session(id); if None or owner ≠ me: 404              # ①
if item.turn != body.expectedTurn: 200 SessionView                    # ②
if item.status in (READY, FAILED): 409 AI_SESSION_CLOSED              # ③
# 여기부터 6a에서는 생기지 않는 경로
log(NON_TERMINAL_SESSION); 500 INTERNAL_ERROR                         # BE-Q87 미결
```
- 모델 호출·AiSession·AiQuota 쓰기가 없다. `questionId` 일치 같은 상태 기댄 검증은 ③ 뒤에 둔다(레벨 0에서는 도달하지 않는다).

### 4.4 세션 저장의 불확실성 (BE-Q89)

`PutItem`이 예외로 끝나도 DynamoDB에는 커밋됐을 수 있다(응답 읽기 타임아웃, 연결 끊김). SDK가 같은 요청을 재시도하면 두 번째 시도가 `ConditionalCheckFailedException`(이미 있음)으로 끝나기도 한다.

```
try: put_session(item)                                   → 성공: 저장됨
except ConditionalCheckFailed | 타임아웃 | BotoCoreError | 그 밖 ClientError:
    if budget.remaining_ms() >= VERIFY_MIN_MS(1_500):
        got = get_item(key, ConsistentRead=True)          # AI 전용 SDK 설정
        if got and got.ownerId == item.ownerId and got.createdAt == item.createdAt: → 저장됨(SAVE_VERIFIED)
    → 저장 미확정: 500 INTERNAL_ERROR (사유 SESSION_SAVE_UNCERTAIN 또는 SESSION_SAVE_FAILED)
```
- `ConditionalCheckFailed`인데 다시 읽은 항목이 우리 것(같은 `ownerId`·`createdAt`)이면 SDK 재시도로 인한 것이므로 저장됨으로 본다. 다른 항목이면(ULID 충돌, 사실상 없음) 500.
- 확인 조회도 실패하거나 시간이 없으면 500이다. 이때 실제로는 나중에 저장돼 있을 수 있다(그 세션은 GET에 보이지만 클라이언트는 받지 못했다). 프론트는 500을 AI 실패로 처리해 직접 작성으로 가고, 남은 세션은 TTL 30일 뒤 지워진다. `POST /plans`는 `aiSessionId`를 받지 못했으므로 지표가 없다.
- 할당량은 어떤 경우에도 자동으로 되돌리지 않는다(되돌리는 쓰기도 불확실해지고, 모델 비용은 이미 들었다).

### 4.5 오류 코드

`common/errors.py`에 추가: `AI_QUOTA_EXCEEDED` 429, `AI_SESSION_CLOSED` 409, `AI_SESSION_BUSY` 409(6a 미사용), `AI_INVALID_OUTPUT` 502, `AI_UNAVAILABLE` 503. 메시지는 docs/03 성격에 맞춘 짧은 한국어. 기존 코드·상태 조합은 바꾸지 않는다.

## 5. 데이터 모델

### 5.1 AiSession (`AISESSION#{sessionId}` / `META`)

| 속성 | 값 |
|---|---|
| `sessionId`, `ownerId` | `ais_…`, JWT `sub` |
| `story` | 사연 원문(소유자만, TTL 30일) |
| `answers` | `[]`(레벨 0) |
| `status` | `READY` \| `FAILED` |
| `turn`, `version` | 1, 1 |
| `agentMode` | `PIPELINE` |
| `finishRequested` | `false` |
| `modelCalls`, `tokenIn`, `tokenOut`, `tokenEstimated` | 호출 수, 합계, usage가 없어 추정했는지 |
| `firstProposal`, `firstReport` | 첫 Candidate_Card와 첫 Check_Report(§8.3). 후보가 없으면 없음 |
| `card`, `flags`, `notes`, `degraded` | 최종 카드와 Final_Check 결과(`READY`만) |
| `trace` | §10.4 |
| `privacyDetected` | §16 계산식의 세션 값(한 번 계산) |
| `failureCode`, `llmError` | `FAILED`일 때 분류 코드(원문 없음) |
| `promptVersion` | `day_card.md`의 SHA-256 앞 12자 |
| `llmMode`, `llmProviderLabel` | `fake` \| `openai_compat`, 표시 이름(내부 속성, SessionView·Plan 지표에 없음, §15.1) |
| `createdAt`, `readyAt` | 요청 수신 시각, READY 확정 시각(밀리초 3자리 UTC) |
| `ttl` | `createdAt` + 30일(epoch 초, 정수) |

- 저장: `PutItem`, `ConditionExpression = attribute_not_exists(PK)`(ULID 충돌 방어). 숫자는 `Decimal`, `null`은 DynamoDB NULL.
- Live_Session: 항목이 있고 `int(ttl) > now_epoch`. `ttl`이 없거나 숫자가 아니면 데이터 이상으로 보고 Expired와 같게 404(로그 `SESSION_TTL_INVALID`).

### 5.2 AiQuota (`AIQUOTA#{userId}#{yyyymmdd}` / `META`)

```
UpdateItem
  UpdateExpression: ADD #s :one SET #ttl = if_not_exists(#ttl, :ttl)
  ConditionExpression: attribute_not_exists(#s) OR #s < :limit
  names: #s = sessions, #ttl = ttl
  values: :one = 1, :limit = AI_DAILY_SESSION_LIMIT(기본 10), :ttl = KST 그날 00:00의 epoch + 2일
```
- 한 항목의 조건부 갱신은 DynamoDB가 직렬화하므로 동시 요청에서도 성공 건수 ≤ 한도다. 읽고 나서 쓰지 않는다.
- 되돌리지 않는다(502·503·저장 실패도 1건).
- `ConditionalCheckFailedException`만 429. 그 밖의 `ClientError`·`BotoCoreError`는 500 `INTERNAL_ERROR`(사유 `QUOTA_WRITE_FAILED`). 할당량을 썼는지 모르는 상태에서 모델을 부르지 않는다.

## 6. Asia/Seoul 날짜

```python
SEOUL = ZoneInfo("Asia/Seoul")            # 모듈 로드 때 1회
def quota_day(now_utc: datetime) -> tuple[str, int]:
    local = now_utc.astimezone(SEOUL)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local.strftime("%Y%m%d"), int(start.timestamp()) + 2 * 86400
```
- Lambda Python 3.12 런타임에 `/usr/share/zoneinfo/Asia/Seoul`이 있음을 확인했다(§검증). `ZoneInfo` 생성이 실패하면(시간대 데이터 없음) 콜드 스타트에서 실패시키지 않고 고정 오프셋 `timezone(timedelta(hours=9), "KST")`로 대신하고 경고 로그를 한 번 남긴다. 한국은 1988년 이후 일광 절약 시간이 없어 결과가 같다.
- 경계: UTC `14:59:59.999` → 그날, `15:00:00.000` → 다음 날(KST 00:00). 단위 테스트로 확인한다.
- 로컬 어댑터 이미지(`python:3.12-slim`)에 시간대 데이터가 없을 수 있으므로 Dockerfile에서 확인하고, 없으면 위 대체 경로로 동작한다(결과 같음).

## 7. LangGraph 그래프

### 7.1 상태 (`agent/state.py`)

```python
class AgentState(TypedDict, total=False):
    story: str
    sources: list[str]                  # [story] (6b: + 답변)
    attempts: int                       # draft 시도 수(1–2)
    last_failure: str | None            # "LLM_ERROR" | "INVALID_OUTPUT"
    llm_error: str | None               # 분류 코드
    invalid_kinds: list[str]            # ["NOT_JSON"|"SCHEMA"], 원문 없음
    candidate: dict | None              # 첫 Candidate_Card (정규화 후)
    first_proposal: dict | None         # 한 번만 씀
    first_report: dict | None           # 한 번만 씀
    card: dict | None                   # 작업 카드(장소마다 내부 키 _src = Candidate 인덱스)
    report: dict | None                 # 가장 최근 Check_Report
    gate_ok: bool
    degraded: bool
    notes: list[dict]
    masked_paths: list[str]             # Fallback이 가린 경로(작업 카드 기준)
    allowed_nis_activities: list[int]   # KEPT_FLAGGED로 허용한 장소의 _src
    final_card: dict | None
    flags: list[dict]
    blocked: list[str] | None           # Final_Check 차단 사유
    trace: list[dict]                   # {tool, summary} (step은 핸들러가 매김)
    model_calls: int; token_in: int; token_out: int; token_estimated: bool
```
- 6b는 `messages`, `questions`, 예산 카운터 등을 더한다. 같은 이름을 다른 뜻으로 쓰지 않는다.
- `first_proposal`·`first_report`를 쓰는 곳은 `check_draft` 노드의 첫 실행 하나뿐이다(이미 값이 있으면 쓰지 않는다).

### 7.2 노드와 엣지 (`agent/graph.py`)

| 노드 | 종류 | 하는 일 |
|---|---|---|
| `draft` | async, LLM | §8. 후보·실패 원인·호출 수·토큰 |
| `check_draft` | 순수 | `check_draft(card, sources)` → `report`. 첫 실행이면 `first_proposal`·`first_report` |
| `rules` | 순수 | §9.1 |
| `gate` | 순수 | `check_draft`를 다시 돌려 `gate_verdict` |
| `fallback` | 순수 | §9.3, `degraded = True` |
| `final_check` | 순수 | §9.4 |

```
START → draft
draft      ─(candidate 있음)→ check_draft ; (없음) → END
check_draft → rules → gate
gate       ─(gate_ok)→ final_check ; (거부) → fallback
fallback   → final_check → END
```
- `compile()`은 체크포인터 없이 한다. 그래프는 모듈 로드 때 한 번 만들어 재사용한다(상태를 들고 있지 않다).
- 노드는 DB·네트워크(LLM 제외)를 쓰지 않는다. 예외를 노드 밖으로 내보내는 것은 코드 결함뿐이고, 핸들러가 500으로 바꾼다.

### 7.3 설정 전달

`config["configurable"] = {"deadline": TimeBudget, "finish_requested": False, "llm_factory": …(테스트 주입용)}`. 노드는 `TimeBudget.remaining_ms()`와 `call_deadline_s()`만 쓴다(§13). 6b도 같은 키를 쓴다.

## 8. 첫 모델 응답과 재시도

### 8.1 메시지

- `SystemMessage(day_card.md)` + `HumanMessage("<story>\n" + neutralize(story) + "\n</story>")`.
- `neutralize`: 대소문자 무시 정규식 `<\s*/?\s*(story|answer)\b`의 `<`를 `＜`(U+FF1C)로 바꾼다. 그 밖의 글자는 원문 그대로다. 모델에 보내는 사연만 바뀌고 Sources(원문 대조 근거)는 원문이다. 마스킹은 하지 않는다(BE-Q10).
- 재시도 메시지: 같은 두 메시지 뒤에 `HumanMessage("앞 응답이 형식에 맞지 않았다: <오류 종류와 경로 목록>. 같은 규칙으로 JSON 객체 하나만 다시 출력하라.")`. 실패한 응답 원문은 다시 보내지 않는다(토큰·유출 줄임).

### 8.2 응답 해석 (`agent/card.py`)

1. `content`가 문자열이 아니면(블록 목록) 텍스트 블록만 이어 붙인다.
2. 코드 펜스(```` ```json … ``` ````)가 있으면 안쪽만 쓴다.
3. 첫 `{` 위치에서 `json.JSONDecoder().raw_decode`로 객체 하나를 읽는다. 객체가 아니거나 실패하면 `NOT_JSON`.
4. §3.1 정규화 → `AiCardDraft` 검증. 실패면 `SCHEMA`(오류 경로만 기록).

### 8.3 draft 노드 알고리즘

```
for attempt in (1, 2):
    if attempt == 2 and not (last_failure == "INVALID_OUTPUT" and budget.remaining_ms() >= 12_000): break
    if budget.remaining_ms() < 12_000: llm_error = "TIME_BUDGET"; last_failure = "LLM_ERROR"; break
    try:   msg = await call_llm(messages, deadline=budget.call_deadline_s())     # §12
    except LlmError as e: llm_error = e.code; last_failure = "LLM_ERROR"; model_calls += e.called; break   # 재시도 없음
    model_calls += 1; tokens += usage_or_estimate(msg)
    parsed = parse_card(msg)
    if parsed.ok: candidate = parsed.card; last_failure = None; break
    invalid_kinds.append(parsed.kind); last_failure = "INVALID_OUTPUT"
```
- LLM_Error는 재시도하지 않는다(`max_retries=0`과 같은 원칙). 재시도는 검증 실패일 때만이고 남은 시간이 12초 이상일 때만이다.
- `model_calls`는 실제로 요청을 보낸 수다(`TIME_BUDGET`·`CONFIG`·`KEY_READ_FAILED`는 보내기 전이므로 세지 않는다).
- 실패 원문은 상태·로그·세션 어디에도 남기지 않는다.
- `firstProposal`은 이 `candidate`(정규화 뒤, 내부 키 없음), `firstReport`는 `check_draft` 노드 첫 실행 결과다. 이후 어떤 노드도 두 값을 바꾸지 않는다. 6b에서 `check_draft`가 여러 번 돌아도 첫 값만 남는다.

## 9. 규칙 노드, Gate, Fallback, Final_Check

공통: 검사 함수는 `check_draft(card, sources) -> Report`

```
Report = { schemaErrors: [path], notInSource: [path], privacy: [{path, kind, severity}], missing: [path] }
```
- `schemaErrors`: 작업 카드에서 내부 키(`_src`)를 뺀 뒤 `AiCardDraft` 검증 경로.
- `notInSource`: `find_not_in_source(sources, [(places[i].name), (places[i].activity)])`의 경로(텍스트는 Report에 넣지 않는다).
- `privacy`: `scan_privacy({경로: 문자열})` — 대상은 카드의 모든 문자열 필드(`title`, `summary`, `reason`, `question`, `places[i].name/activity/whyChosen`).
- `missing`: §3.2 표의 대상 중 `null`, 장소가 없으면 `places`.
- 경로의 인덱스는 **작업 카드의 현재 순서**다.

### 9.1 `rules` (레벨 0)

```
for place in card.places (앞에서부터):
    kinds = scan_privacy({name, activity}) 의 kind
    if "PRIVATE_PLACE" in kinds:
        remove place; notes.append(REMOVED, path=f"places[{place._src}].{name|activity 중 걸린 필드}", source=STORY,
                                   reason="비공개 장소라 동선에서 뺐어요.")
```
- 비공개 장소가 `whyChosen`·`title` 등 다른 필드에만 있으면 빼지 않는다(`MEDIUM`, `PRIVACY` 플래그로 남음, BE-Q22).
- 그 밖에는 카드를 바꾸지 않는다.

### 9.2 `gate`

`report = check_draft(card)`를 **다시** 계산한다(이전 결과를 쓰지 않는다). 거부 조건: `schemaErrors`가 있음, `notInSource`에 `places[`로 시작하는 경로가 있음(이름·활동 모두), `privacy`에 `HIGH`가 있음. 레벨 0은 거부되면 재시도 없이 `fallback`.

### 9.3 `fallback`

```
1. 가리기: 모든 문자열 필드에 privacy.mask(HIGH만 "***"). 바뀐 필드를 masked_paths에 (장소는 _src 기준으로) 기록.
   가린 뒤 최대 길이를 넘으면(이론상 "1호"(2자) → "***"(3자)) 그 필드의 최대 길이로 자른다.
2. 다시 검사: report = check_draft(card)   # 가린 "***"는 원문에 없으므로 이름에 연락처가 있던 장소는 여기서 NOT_IN_SOURCE가 된다
3. 이름 NOT_IN_SOURCE인 장소 제거: notes.append(REMOVED, path=f"places[{_src}].name", reason="사연에 없는 장소라 뺐어요.", source=STORY)
4. 남은 장소 중 활동만 NOT_IN_SOURCE: 유지, allowed_nis_activities += [_src],
   notes.append(KEPT_FLAGGED, path=f"places[{최종 인덱스}].activity", reason="사연에서 확인하지 못한 활동이에요. 확인해 주세요.", source=STORY)
5. degraded = True
```
- 결정적이다(입력 순서대로, 난수·시간 없음). 위반을 지우거나 플래그로 남길 뿐 조용히 통과시키지 않는다.
- 비공개 장소는 `rules`가 이미 뺐다. Fallback은 비공개 장소를 다루지 않고, 남아 있으면 Final_Check가 막는다(코드 결함 신호).

### 9.4 `final_check` (BE-Q88)

`check_draft(final_card)`를 처음부터 다시 돌린 뒤:

| 검사 | 처리 |
|---|---|
| `schemaErrors` 있음 | 차단 `SCHEMA` |
| `privacy` `HIGH` 있음 | 차단 `HIGH_PRIVACY` |
| `PRIVATE_PLACE`가 `places[i].name`·`activity`에 있음 | 차단 `PRIVATE_PLACE_IN_PLACES` |
| `places[i].name` NOT_IN_SOURCE | 차단 `NIS_PLACE_NAME` |
| `places[i].activity` NOT_IN_SOURCE이고 그 장소 `_src`가 `allowed_nis_activities`에 없음 | 차단 `NIS_ACTIVITY_UNFLAGGED` |
| `places[i].activity` NOT_IN_SOURCE이고 허용됨 | 플래그 `NOT_IN_SOURCE` |
| `missing` | 플래그 `MISSING` |
| `masked_paths`(최종 인덱스로 바꾼 것) | 플래그 `PRIVACY` |
| `MEDIUM` 탐지(`PLATE`, `LOT`, 장소 밖 `PRIVATE_PLACE`) | 플래그 `PRIVACY` |

- 차단이 하나라도 있으면 `blocked`를 채우고 카드를 버린다 → 502(§4.1). 정상 코드에서는 생기지 않아야 하고 속성 테스트(P29)로 확인한다.
- 플래그는 `(path, type)`으로 중복을 없애고 카드 필드 순서(`title`, `summary`, `reason`, `estimatedMinutes`, `places`, `places[0].*`, …, `question`)로 정렬한다.
- Gate 통과 경로에서도 Final_Check를 거친다(규칙 노드가 바꾼 카드와 플래그를 한 함수로 만든다).

## 10. 장소 제거 뒤 인덱스와 flags·notes

### 10.1 두 기준

| 대상 | 인덱스 기준 |
|---|---|
| `flags[].path` | 최종 카드(제거 뒤 다시 매김) |
| `notes[].path` 중 `REMOVED` | Candidate_Card(`_src`, 제거 전) — BE-Q13 제안안 |
| `notes[].path` 중 그 밖(`KEPT_FLAGGED`) | 최종 카드 |
| `firstReport` 경로 | Candidate_Card(그때의 순서 그대로) |

### 10.2 계산

- 작업 카드의 장소는 `_src`(Candidate_Card에서의 인덱스)를 들고 다닌다. 최종 인덱스는 `final_card.places`에서의 위치다. `_src`는 직렬화 전에 지운다.
- `masked_paths`는 `_src` 기준으로 모았다가 Final_Check에서 최종 인덱스로 바꾼다. 가린 뒤 제거된 장소의 경로는 버린다.
- `flags`는 Final_Check가 최종 카드에서 만들므로 뺀 장소를 가리킬 수 없다(Req 4.8).

### 10.3 예

Candidate `places = [A(원문 있음), B(비공개 장소), C(이름 원문 없음), D(활동만 원문 없음)]`, Gate 거부:
- `rules`: B 제거 → notes `REMOVED places[1].name`
- `fallback`: C 제거 → `REMOVED places[2].name`, D 유지 → `KEPT_FLAGGED places[1].activity`(최종 `[A, D]`에서 D는 1번)
- `final_check`: flags `NOT_IN_SOURCE places[1].activity`

### 10.4 trace (BE-Q76, 프론트 리뷰 대상)

| 순서 | `tool` | `summary` 예 |
|---|---|---|
| 1 | `draft` | "초안 작성" / 재시도 때 "초안 형식 오류, 다시 작성" |
| 2 | `check_draft` | "원문에 없음 2건, 빈칸 1건, 개인정보 1건(연락처)" |
| (있으면) | `rules` | "비공개 장소 1곳 뺌" |
| 3 | `submit_card` | "제출, 서버 검사 통과" / "서버 검사에서 걸림: 원문에 없음 1건, 개인정보 1건" |
| (있으면) | `fallback` | "자동 정리: 장소 1곳 뺌, 연락처 가림" |

- `summary`는 고정 문구 + 개수 + 유형 이름(연락처·동호수·차량번호·번지·비공개 장소)뿐이고 사연·카드 문자열을 인용하지 않는다(계약 예시의 장소 인용은 6b 에이전트 메모에서 다시 정한다). `step`은 핸들러가 1부터 매긴다.
- `FAILED`도 그때까지의 trace를 저장한다(GET이 돌려준다).

## 11. ChatOpenAI, Fake 모델, 로컬 HTTP 스텁

### 11.1 설정 (`agent/llm.py`)

| 환경 변수 | 처리 |
|---|---|
| `LLM_PROVIDER` | `fake` \| `openai_compat`, 그 밖은 `CONFIG` |
| `LLM_BASE_URL`, `LLM_MODEL` | `openai_compat`이면 필수(빈 값 → `CONFIG`) |
| `LLM_API_KEY_PARAM` / `LLM_API_KEY` | AWS는 이름만(§14), 로컬은 값 |
| `LLM_CONNECT_TIMEOUT_S`, `LLM_READ_TIMEOUT_S` | 기본 2, 8. `LLM_CALL_MAX_S = connect + read` |
| `LLM_MAX_RETRIES` | 기본 0(0이 아니면 경고, 6a는 0만 허용) |
| `LLM_MAX_TOKENS` | 기본 800 |
| `LLM_TEMPERATURE` | 빈 값이면 넘기지 않음, 그 밖은 float |
| `LLM_EXTRA_BODY` | JSON 객체 문자열 → `extra_body`. 객체가 아니면 `CONFIG` |
| `LLM_TOOL_CHOICE`, `LLM_PARALLEL_TOOL_CALLS` | 읽어서 보관만(6b `bind_tools`용) |
| `LLM_PROVIDER_LABEL` | 로그·동의 문구용 표시 이름 |
| `FAKE_LLM_SCENARIO` | Fake 시나리오 |
| `FAKE_LLM_ALLOWED` | `fake`를 쓸 수 있는지(§14.4) |

설정 오류는 콜드 스타트에서 실패시키지 않고 요청마다 `CONFIG`(LLM_Error → 503)로 처리한다. 로그에는 키 이름만 남긴다(값 없음).

### 11.2 모델 생성

```python
async with httpx.AsyncClient(timeout=httpx.Timeout(read_s, connect=connect_s)) as http:   # 호출(요청)마다
    model = ChatOpenAI(base_url=…, api_key=SecretStr(key), model=…, timeout=httpx.Timeout(read_s, connect=connect_s),
                       max_retries=0, max_tokens=800, use_responses_api=False, http_async_client=http,
                       **({"temperature": t} if t is not None else {}), **({"extra_body": eb} if eb else {}))
    msg = await asyncio.wait_for(model.ainvoke(messages), timeout=deadline_s)
```
- 호출마다 `AsyncClient`를 새로 만들고 닫는다. 모듈 전역 모델을 재사용하면 `asyncio.run`이 바뀔 때 `Event loop is closed`가 나는 것을 확인했다.
- 도구를 묶지 않는다(`bind_tools` 없음). `tool_choice`·`parallel_tool_calls`는 보내지 않는다.

### 11.3 오류 분류

| 예외 | 코드 |
|---|---|
| `asyncio.TimeoutError`(전체 deadline) | `TIMEOUT` |
| `openai.APITimeoutError` | `TIMEOUT`(APIConnectionError보다 먼저 검사) |
| `openai.APIConnectionError` | `CONNECTION` |
| `openai.APIStatusError` 401·403 | `HTTP_401`·`HTTP_403` |
| `openai.APIStatusError` 429 | `HTTP_429` |
| `openai.APIStatusError` 400 | `HTTP_400` |
| `openai.APIStatusError` ≥500 | `HTTP_5XX` |
| `openai.APIStatusError` 그 밖(404 등) | `HTTP_OTHER` |
| SSM 읽기 실패 | `KEY_READ_FAILED` |
| 설정 오류 | `CONFIG` |
| 남은 시간 부족 | `TIME_BUDGET` |
| 응답 객체가 Chat Completions 모양이 아님(`openai` 파싱 오류 등) | `PROVIDER_RESPONSE` |

모두 LLM_Error다(어떤 공급자 오류도 코드 없는 500이 되지 않는다). langchain-openai가 쓰는 래퍼 클래스 이름에 기대지 않고 `openai`의 기반 클래스와 `status_code`로 나눈다.

### 11.4 Fake 모델 (`agent/fake_llm.py`)

- `FakeScenarioChatModel(BaseChatModel)`: `_agenerate`가 시나리오의 다음 단계를 돌려준다. 단계는 `("content", 문자열)`, `("raise", 예외)`, `("sleep", 초)` 중 하나이고, 호출마다 받은 메시지·인자를 `calls`에 기록한다.
- 예외는 실제 `openai` 예외를 만든다(`httpx.Request`·`httpx.Response`로 `openai.AuthenticationError` 등 생성, 타임아웃은 `openai.APITimeoutError`). 분류 경로가 실제와 같다.
- `slow`는 `asyncio.sleep`으로 기다려 `wait_for` 취소가 그대로 적용된다(T21 성격의 시험은 6b, 6a는 deadline 동작 확인용).
- usage: `happy`류는 `usage_metadata`를 채우고, `no_usage`는 비운다(추정 경로 확인).
- 시나리오(레벨 0): `happy`, `not_in_source`, `privacy_high`, `private_place`, `missing`, `all_places_removed`, `bad_json`, `bad_json_then_ok`, `schema_error`, `schema_error_then_ok`, `timeout`, `http_400`, `http_401`, `http_429`, `http_500`, `slow`, `no_usage`, `fenced_json`.

### 11.5 로컬 HTTP 스텁 (`tests/unit/llm_stub.py`)

- 테스트 프로세스 안 `ThreadingHTTPServer`(127.0.0.1, 임의 포트)로 `POST /v1/chat/completions`를 흉내 낸다. 외부 네트워크 없음.
- 모드: `ok`(usage 포함), `no_usage`, `fenced`, `prose_around_json`, `status:<code>`, `drip`(바이트를 느리게), `hang`(헤더 뒤 멈춤), `close`(연결 끊기). 받은 요청 경로·본문·`Authorization` 앞부분을 기록한다(키 원문은 비교만 하고 저장하지 않는다).
- 실제 `ChatOpenAI`로 확인하는 것: 요청 형태(§검증 표), 오류 분류, `drip`·`hang`에서 deadline으로 끊김과 늦은 응답 무시, usage 추정, JSON 추출. Fake와 같은 시나리오를 스텁에서도 돌려 결과(상태 코드·세션 상태·지표)가 같은지 비교한다.

### 11.6 토큰

`usage_metadata`의 `input_tokens`·`output_tokens`를 더한다. 없으면 입력은 메시지 글자 수 합 / 2, 출력은 content 글자 수 / 2(올림)로 추정하고 `tokenEstimated = true`. `get_num_tokens`(tiktoken 인코딩 다운로드)는 쓰지 않는다.

## 12. 전체 LLM 호출 deadline과 취소 (BE-Q78)

- 방식: 노드를 `async`로 두고 `asyncio.wait_for(model.ainvoke(...), timeout=deadline_s)`. 핸들러는 `asyncio.run(graph.ainvoke(...))`.
- 확인한 사실: 동기 호출은 느린 응답에 read 타임아웃이 걸리지 않아 12초 넘게 이어졌고, `wait_for`는 정해진 시간에 끊었으며 httpx가 연결을 닫았다(서버가 닫힘을 0.5초 안에 감지).
- `deadline_s = min(LLM_CALL_MAX_S(10), (remaining_ms − SAVE_RESERVE_MS) / 1000)`. 호출을 시작할 조건은 `remaining_ms ≥ 12_000`이다(§13).
- 취소 뒤: `CancelledError`가 httpx 요청을 끝내고 `async with` 블록이 클라이언트를 닫는다. 늦게 온 응답은 쓰이지 않는다(코루틴이 이미 끝남). 스레드를 쓰지 않으므로 떠도는 스레드가 없다.
- **취소 완료 시간은 deadline을 넘을 수 있다.** `wait_for`는 시간이 되면 작업을 취소하고 **취소가 끝날 때까지 기다린 뒤** 돌아온다. 그 뒤 `async with`가 `AsyncClient.aclose()`를 기다린다. 프로토타입에서 `wait_for` 반환은 3.00초(deadline 3초)였고 연결 정리는 서버 기준 0.5초 안이었지만, 이 값은 보장이 아니다. 그래서 `SAVE_RESERVE_MS`(4초)에 취소·종료 시간이 포함된다고 보고, 시험으로 상한을 잰다(아래).
- 한계: 이벤트 루프를 막는 동기 코드(예: 큰 JSON 파싱)가 있으면 취소가 늦어진다. 응답 크기는 `max_tokens` 800으로 제한되고, 파싱은 호출이 끝난 뒤 한다. DNS 조회는 httpx 기본(스레드 풀)이라 취소가 늦을 수 있다 — 연결 2초 타임아웃이 상한이다.
- 6b도 같은 방식을 쓴다(`decide`도 async).

시험(작업 목록에서 필수)
- 느린 응답(`drip`)·멈춤(`hang`)·연결 직후 끊김에서 `call_llm`이 돌아오기까지의 전체 시간(취소 + `aclose` 포함)이 `deadline + CANCEL_SLACK_MS(500)` 안인지 20회 반복해 최댓값을 기록한다.
- 같은 프로세스에서 핸들러를 연속 30회 호출(Warm 호출, 매번 `asyncio.run`)해 `Event loop is closed`·미완료 태스크 경고·열린 소켓 수 증가가 없는지 확인한다(`ResourceWarning`을 오류로 바꿔 실행).
- 취소된 호출 뒤 같은 프로세스의 다음 호출이 정상인지 확인한다.

## 13. 실행 시간 예산과 SDK 설정

### 13.1 Remaining_Time (`agent/timebudget.py`)

```
lambda_ms = context.get_remaining_time_in_millis()
api_ms    = (event.requestContext.timeEpoch + API_BUDGET_MS(29_000)) − now_epoch_ms   # 없으면 무시
remaining = min(lambda_ms, api_ms)
```
- HTTP API 통합 상한 30초에는 콜드 스타트의 Init 시간도 들어간다. Lambda 타임아웃(27초)만 보면 Init이 3초를 넘는 콜드 스타트에서 API Gateway가 먼저 끊을 수 있으므로, API가 요청을 받은 시각(`timeEpoch`)부터 29초를 함께 본다(BE-Q90, AWS에서 시계 차이와 동작 확인).
- 로컬 어댑터는 `timeEpoch`(요청 시각)와 27초 `FakeContext`를 이미 넣는다.
- `timeEpoch` 검증: 정수(밀리초)이고 `now − 30_000 − SKEW_MS ≤ timeEpoch ≤ now + SKEW_MS`(`SKEW_MS = 2_000`)일 때만 쓴다. 없거나, 숫자가 아니거나, 범위 밖이면(시계 오류·조작) 무시하고 Lambda 남은 시간만 쓰며 사유 코드 `TIME_EPOCH_IGNORED`를 로그에 남긴다. 범위 밖 값으로 남은 시간을 0으로 만들어 모든 요청을 503으로 만드는 일을 막기 위해서다.
- 시험: `timeEpoch` 없음·문자열·음수·미래(+10초)·오래됨(−40초)·정상(−3초 → 남은 시간 26초)에서 계산 결과.

### 13.2 예산 표

| 단계 | 보통 | 상한(설정 기준) | 비고 |
|---|---|---|---|
| Init(콜드 스타트) | 측정 필요(개발 PC import 0.7–0.9초) | — | Lambda 27초 밖, API 30초 안 → `timeEpoch` 기준으로 흡수 |
| 입력 검증·설정 확인 | <10ms | — | |
| AiQuota `UpdateItem` | 수십 ms | 2회 × (1+2초) + 백오프 ≈ 6.5초 | AI 전용 `Config` |
| SSM `GetParameter`(콜드만) | 수십 ms | ≈ 6.5초 | 실패는 캐시 안 함 → `KEY_READ_FAILED` |
| LLM 호출 1 | 공급자별(BE-Q12) | `min(10, remaining − 4)` 초 | 시작 조건 remaining ≥ 12초 |
| LLM 호출 2(검증 실패 때만) | 〃 | 〃 | 시작 조건 remaining ≥ 12초 |
| 검사·폴백·Final_Check | <50ms | — | 순수 함수 |
| AiSession `PutItem` | 수십 ms | `SAVE_RESERVE_MS` 4초 안(1회 3초 + 여유) | 재시도까지 가면 넘을 수 있음 |
| 직렬화·EMF | <10ms | — | |

- 상수: `MIN_CALL_START_MS = 12_000`, `SAVE_RESERVE_MS = 4_000`(취소·`aclose`, `PutItem` 1회, 확인 조회의 일부를 포함), `VERIFY_MIN_MS = 1_500`, `CANCEL_SLACK_MS = 500`(시험 기준), `LLM_CALL_MAX_S = 10`. 첫 호출 전에 remaining이 12초 미만이면 호출하지 않는다 → `TIME_BUDGET` → 503.
- 최악 조합 예: 할당량·SSM이 상한까지 걸려 13초를 쓰면 남은 14초 → 호출 1 deadline 10초 → 남은 4초 → 재시도 불가, 저장 4초. 저장이 4초를 넘으면 강제 종료될 수 있다(Req 12.6, BE-Q74 결과).
- 강제 종료를 완전히 막지 못하는 경우: SDK 재시도 누적, 콜드 스타트가 길어 `timeEpoch` 기준이 먼저 줄어듦, 이벤트 루프가 막혀 취소가 늦음, DynamoDB 지연. 결과는 세션 없음 + 할당량 1 소모 + 프론트 타임아웃 처리.

### 13.3 AI 전용 SDK 설정 (BE-Q85)

```python
AI_SDK = Config(connect_timeout=float(env("AI_SDK_CONNECT_TIMEOUT_S", 1)), read_timeout=float(env("AI_SDK_READ_TIMEOUT_S", 2)),
                retries={"mode": "standard", "total_max_attempts": int(env("AI_SDK_MAX_ATTEMPTS", 2))})
```
- `handlers/ai_card.py`가 콜드 스타트 때 `boto3.resource("dynamodb", config=AI_SDK).Table(TABLE_NAME)`을 만들어 `ddb.use_table`로 꽂는다(5단계 사진 처리 Lambda와 같은 함수, 병합 때 하나로). SSM 클라이언트도 같은 `Config`.
- `PlansFunction` 등 다른 함수는 지금 설정 그대로다(BE-Q48 미결 유지).
- 6b 체크포인터도 `DynamoDBSaver(boto_config=AI_SDK)`로 같은 설정을 쓸 수 있음을 확인했다(§18).

## 14. SSM SecureString, 캐시, KMS, IAM

### 14.1 키 읽기

```python
_key_cache: str | None = None
def api_key() -> str:
    if os.environ.get("LLM_API_KEY_PARAM"):
        global _key_cache
        if _key_cache is None:
            try: _key_cache = ssm.get_parameter(Name=…, WithDecryption=True)["Parameter"]["Value"]
            except (ClientError, BotoCoreError): raise LlmError("KEY_READ_FAILED")   # 캐시하지 않음
        return _key_cache
    key = os.environ.get("LLM_API_KEY", ""); if not key: raise LlmError("CONFIG"); return key
```
- 키는 `pydantic.SecretStr`로 `ChatOpenAI`에 넘긴다(repr에 나오지 않음). 예외 메시지·로그에 넣지 않는다.
- AWS 배포에는 `LLM_API_KEY` 환경 변수를 정의하지 않는다(템플릿 단위 테스트로 확인). `fake` 모드는 키를 읽지 않는다.

### 14.2 SecureString 생성 (AWS 담당, BE-Q81)

- CloudFormation은 SecureString을 만들 수 없다(문서 확인). 배포 전에 AWS 담당이 표준 계층·`aws/ssm` 키로 만든다. 이름 예: `/haru/dev/llm/api-key`.
- 값이 셸 기록에 남지 않게 콘솔이나 `read -s`로 받은 변수를 `--value file://`·표준 입력으로 넘기는 방법을 런북에 적는다.

### 14.3 IAM (`AiCardFunction`)

```yaml
- Statement:
  - Effect: Allow
    Action: [dynamodb:GetItem, dynamodb:PutItem, dynamodb:UpdateItem]
    Resource: !GetAtt HaruTable.Arn
    Condition:
      ForAllValues:StringLike:
        dynamodb:LeadingKeys: ["AISESSION#*", "AIQUOTA#*"]
- !If
  - HasLlmKeyParam
  - Statement:
    - Effect: Allow
      Action: ssm:GetParameter
      Resource: !Sub "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter${LlmApiKeyParam}"
  - !Ref AWS::NoValue
```
- `Query`·`Scan`·`TransactWriteItems`·`index/*`·`GetParameters`·`GetParametersByPath`·`kms:*` 없음. `aws/ssm` 관리형 키는 계정 주체에게 `Decrypt`를 허용하므로 KMS 권한이 필요 없다(문서 확인). 고객 관리형 키로 바꾸면 그 키 ARN에 `kms:Decrypt` + `kms:ViaService = ssm.${AWS::Region}.amazonaws.com`만 더한다.
- 이름은 `/`로 시작해야 한다(`AllowedPattern: ^$|^(/[A-Za-z0-9_.-]+)+$`). 빈 값이면 SSM 문장과 `LLM_API_KEY_PARAM`을 넣지 않는다(Fake 전용 dev 배포).
- `dynamodb:LeadingKeys`가 실제로 막는지(`PLAN#` 쓰기 거부)는 AWS 판정 항목이다(§2.4.4 3번).
- 다른 함수는 SSM 권한이 없다. `aws/ssm` 키 특성상 SSM 권한이 곧 키 읽기 권한이기 때문이다.

### 14.4 `dev`의 Fake 허용 (BE-Q86 권장안)

5단계 `FaultInject`(BE-Q59)과 같은 세 겹으로 막는다.
1. Parameters: `Stage`(`dev`·`demo`, 기본 `demo` — 5단계 브랜치와 같은 정의), `LlmProvider`(`openai_compat`·`fake`, 기본 `openai_compat`). `Rules`: `Stage = dev`이거나 `LlmProvider = openai_compat`.
2. Condition `FakeAllowed = Stage == dev ∧ AWS::StackName == haru-dev`. 환경 변수 `LLM_PROVIDER: !If [FakeAllowed, !Ref LlmProvider, openai_compat]`, `FAKE_LLM_ALLOWED: !If [FakeAllowed, "true", "false"]`.
3. 런타임: `fake`는 `FAKE_LLM_ALLOWED == "true"`이고 (함수 이름이 `haru-dev-`로 시작, 또는 함수 이름이 없고 `STAGE == local`)일 때만. 아니면 `CONFIG`(→ 503).
- Fake 결과는 S4 연동·AWS 경로 확인용이다. 판정 기록에 `llmMode: fake`를 남기고 T12·BE-Q9·BE-Q12 근거로 쓰지 않는다.

## 15. 외부 전송 제한, 로그, LangSmith

### 15.1 `llmMode`
- AiSession에 `llmMode`(`fake` \| `openai_compat`)와 `llmProviderLabel`(표시 이름, 비밀 아님)을 내부 속성으로 저장한다. SessionView 허용 목록과 Plan `metrics`에는 넣지 않는다(승인 없이 계약·응답을 바꾸지 않는다. 템플릿·직렬화 테스트로 확인).
- 테스트 결과 파일(로컬·AWS)에 `llmMode`를 적는다. Fake 세션과 Fake `dev` 스택 결과는 실제 공급자의 품질 평가(오프라인 평가, 리허설, 시범 운영 지표)에서 뺀다. 시범 운영은 `demo` 스택(Fake 불가)에서 하므로 Plan 지표에 Fake 세션이 섞이지 않는다. `dev`의 Plan 지표는 품질 분석에 쓰지 않는다고 README에 적는다.

### 15.2 전송 제한·로그

- 기본값: 로컬 compose `LLM_PROVIDER=fake`, 템플릿 `LlmBaseUrl`·`LlmModel` 빈 값(`samconfig.toml`에 공급자 값 없음). 공급자 값이 없으면 `openai_compat`은 `CONFIG`로 503이 되어 사연이 나가지 않는다.
- 실제 공급자 호출은 LLM 담당이 합성 사연(`tests/fixtures`)으로 하는 실측과 T12에만 쓴다. BE-Q6·BE-Q7·BE-Q10 확정 전에는 실제 사용자 사연을 보내지 않는다.
- 로그(`haru.ai` 로거): 남기는 것 — `sessionId`, `status`, `failureCode`, `llmError`, 시도 수, `invalid_kinds`, 개수(원문에 없음·빈칸·개인정보 유형별), 시간, 프롬프트 버전. 남기지 않는 것 — 사연, 답변, 프롬프트, 모델 응답(성공·실패 모두), 카드 문자열, 개인정보 일치 문자열, 예외 객체·`str(e)`·`repr(e)`, 공급자 오류 본문, 키, `Authorization`, Base URL.
- 예외 처리 규칙: `except Exception as e: log.warning("ai_error type=%s", type(e).__name__)`. `logger.exception`·`exc_info=True`를 쓰지 않는다(정적 검사 테스트로 `agent/`·`handlers/ai_card.py`에서 금지).
- 라이브러리 로거: `openai`, `httpx`, `httpcore`, `langchain`, `langchain_core`, `langchain_openai`, `langgraph`, `langsmith` 수준을 `WARNING`으로 고정(`httpx` INFO는 요청 URL을 찍는다). `OPENAI_LOG`를 정의하지 않는다.
- LangSmith: 템플릿 Globals와 compose의 두 변수 `false` 유지, `LANGSMITH_API_KEY`·`LANGCHAIN_API_KEY` 미정의, 그래프 실행을 `tracing_context(enabled=False)`로 감싼다. 단위 테스트는 두 변수를 `true`로 두고 `langsmith` 클라이언트 전송 함수를 막아 호출 0회를 확인한다.
- AiSession의 `story`·`firstProposal`·`card`는 사연과 개인정보를 담을 수 있다. 소유자만 읽고 TTL 30일 뒤 지워진다(BE-NFR-03). SessionView 허용 목록 밖이다.

## 16. `POST /plans` AI 지표 (BE-Q79)

### 16.1 세션 선택

```
if mode != AI_EDITED or not aiSessionId: AI 지표 없음
try: s = get_live_session(aiSessionId)        # ConsistentRead, ttl 확인, PlansFunction 기존 클라이언트
except (ClientError, BotoCoreError): log(AI_METRICS_READ_FAILED); AI 지표 없음
if s is None or s.ownerId != user.id or s.status != READY: log(사유); AI 지표 없음
```
Plan 생성·응답은 어느 경우에도 지금과 같다. 지표 계산 예외도 Plan 생성을 막지 않는다(지표 없이 저장, 로그).

### 16.2 계산식 (`domain/ai_metrics.py`, 순수 함수)

`story` = 요청 `authoring.story`, `places` = 요청 최종 장소, `S` = 세션.

| 지표 | 계산 |
|---|---|
| `addedNotInSource` | (기존) `len(find_not_in_source([story], places))` |
| `privacyInPublished` | (기존) 최종 Plan 텍스트 `scan_privacy` 수 |
| `addedNotInSourceOrAnswers` | `len(find_not_in_source([story] + 답변 근거, places))`. 답변 근거 = `S.answers`의 `choice`·`text` 중 개인정보 없는 것(레벨 0은 없음 → `addedNotInSource`와 같음) |
| `firstProposalNotInSource` | `len(S.firstReport.notInSource)`(없으면 0) |
| `deliveredNotInSource` | `S.flags` 중 `NOT_IN_SOURCE` 수 |
| `agentSelfRepairs` | `S.notes` 중 `REWRITTEN`·`REMOVED` 수 |
| `missingFirst` | `len(S.firstReport.missing)` |
| `missingDelivered` | `S.flags` 중 `MISSING` 수 |
| `questionsAsked` | `len(S.answers)` |
| `questionsSkipped` | `S.answers` 중 `skipped` 수 |
| `privacyDetected` | `S.privacyDetected`(세션이 끝날 때 한 번 계산: 사연 `scan_privacy` 수 + 답변 각각의 수 + `firstReport.privacy` 수). Gate·Fallback·Final_Check의 재검사는 세지 않는다 |
| `agentWaitMs` | `max(0, ms(S.readyAt) − ms(S.createdAt) − answerWaitMs)` |
| `answerWaitMs` | `Σ max(0, answeredAt − askedAt)`(레벨 0은 0) |
| `editMs` | `max(0, ms(Plan createdAt) − ms(S.readyAt))` (Lambda 사이 시계 차이로 음수면 0) |
| `fieldsEditedAfterHandoff` | 아래 비교 단위의 "다름" 개수 |
| `modelCalls` | `S.modelCalls` |
| `agentMode` | `S.agentMode`가 `PIPELINE`이면 `PIPELINE`, `AGENT`이면 `S.degraded ? DEGRADED : AGENT`(6b) |

`fieldsEditedAfterHandoff` 비교 단위
- 스칼라 5개: `title`, `summary`, `reason`, `estimatedMinutes`, `question` — 각 1개.
- 장소: `i = 0 … max(len(S.card.places), len(places)) − 1`마다 `name`, `activity`, `whyChosen` 각 1개. 한쪽에 장소가 없으면 그쪽 값은 `null`.
- 같음 판정: 문자열은 정확히 같음(공백 포함, 프론트가 카드를 그대로 초기값으로 쓰므로), 숫자는 값 비교, `null`과 값은 다름. `whyChosen`만 `null`과 `""`를 같게 본다.
- 예: 카드 장소 2개 → 계획자가 1개를 지우고 제목만 고침 → 제목 1 + 지운 장소 3 = 4.

### 16.3 호환성

- `compute_metrics(body)`의 기존 네 값은 그대로이고, AI 지표는 같은 `metrics` 맵에 더한다. `MANUAL`이면 세션을 읽지 않는다.
- 멱등 재요청은 저장된 Plan을 돌려주므로 지표가 바뀌지 않는다(1·2단계 코드 경로 그대로).
- `PlansFunction` 권한은 지금의 `GetItem`으로 충분하다(테이블 전체 `GetItem`). 템플릿 변경 없음.
- 본문 해시(`body_hash`)는 바뀌지 않는다(지표는 해시 대상이 아니다).

## 17. 빌드와 의존성 (BE-Q80, BE-Q18)

### 17.1 Makefile 빌드

```make
# src/Makefile (sam build가 AiCardFunction에만 쓴다)
build-AiCardFunction:
	cp -r common domain handlers agent prompts "$(ARTIFACTS_DIR)/"
	python -m pip install --no-cache-dir --only-binary=:all: --no-deps --require-hashes -r ai-requirements.lock -t "$(ARTIFACTS_DIR)"
	find "$(ARTIFACTS_DIR)" -name "__pycache__" -prune -exec rm -rf {} +
```
```yaml
AiCardFunction:
  Type: AWS::Serverless::Function
  Metadata: { BuildMethod: makefile }
  Properties: { CodeUri: src/, Handler: handlers.ai_card.handler, Timeout: 27, MemorySize: 1024, Architectures: [x86_64], … }
```
- 공통 코드는 저장소에 하나만 있고 빌드 때만 산출물로 모은다. 다른 함수는 지금처럼 `CodeUri: src/` + `src/requirements.txt`.
- 확인한 사실: `--use-container`(sam/build-python3.12 이미지)에서 `make`가 동작하고 산출물이 맞게 나온다. 다른 함수 산출물에 `Makefile`·`ai-requirements.*`가 함께 복사된다(몇 KB, 실행되지 않음). 이를 막으려고 코드 폴더를 나누지 않는다(공통 코드 복제가 생기므로).
- `--require-hashes`는 구현 때 잠금 파일 생성(`--generate-hashes`)과 함께 확인한다. 안 되면 해시 없이 `==` 고정으로 두고 README에 적는다.

### 17.2 잠금 파일

```
uv pip compile src/ai-requirements.in --python-version 3.12 --python-platform x86_64-manylinux_2_28 --generate-hashes -o src/ai-requirements.lock
```
- `ai-requirements.in`: docs/02의 직접 의존성 5개 + `boto3>=1.43.64` + 공통 `pydantic==2.14.4`·`python-ulid==4.2.0`. 구현 시점에 PyPI를 다시 확인한다(2026-11-26 확인: 해석 성공, `langchain-core` 최신 1.8.5는 쓰지 않고 docs 값 1.8.4 유지 — 올릴지는 구현 때 변경 내역을 보고 정한다).
- 단위 테스트: 잠금 파일의 모든 줄이 `==`, `pydantic`·`python-ulid` 버전이 `src/requirements.txt`와 같음, `.in`의 직접 의존성이 모두 잠금에 있음.
- 개발 PC의 `.venv`는 `requirements-dev.txt`에 `-r src/ai-requirements.lock`(해시 없는 설치용 별도 파일이 필요하면 같은 명령으로 생성)을 더해 같은 버전을 쓴다. `boto3`는 개발 의존성(1.44.10)과 잠금(1.44.12)이 다르므로 개발 쪽을 잠금에 맞춘다.

### 17.3 빌드 검사 (`scripts/check_ai_build.py`)

`sam build --use-container` 뒤 실행:
1. `.aws-sam/build/` 아래 AiCardFunction이 아닌 함수 디렉터리에 금지 패키지(`langgraph*`, `langchain*`, `langsmith`, `openai`, `tiktoken`, `httpx*`, `httpcore*`, `ormsgpack`, `xxhash`, `zstandard`, `jiter`, `orjson`)가 없음.
2. AiCardFunction: 압축 해제 크기·zip 크기·상위 10개 패키지 크기 출력, 250MB 한도 확인.
3. `public.ecr.aws/lambda/python:3.12` 컨테이너에 산출물을 읽기 전용으로 붙여 `handlers.ai_card` import 시간(5회), `agent.graph.build_pipeline_graph()`와 Fake 모델로 그래프 1회 실행(DB 없이), `zoneinfo("Asia/Seoul")` 확인.
4. **각 Lambda 산출물의 독립 import·실행**: 함수마다 그 산출물 디렉터리 하나만 `/var/task`로 붙인 런타임 컨테이너에서 (a) 핸들러 모듈 import (b) 인증 없는 API 이벤트로 핸들러 호출 → 401 계약 응답(DB 없이 끝나는 경로) (c) import 뒤 `sys.modules`에 `langgraph*`·`langchain*`·`openai`·`langsmith`가 없음(AiCardFunction 제외). `PlansFunction`은 추가로 `domain.ai_metrics`로 표본 AiSession(딕셔너리)의 지표를 계산해 AI 패키지 없이 돈다는 것을 확인한다. `PreSignUpFunction`은 PreSignUp 표본 이벤트.
5. **최종 측정**: 구현 마지막 빌드에서 AiCardFunction 압축 해제·zip 크기, 상위 패키지, import 시간(5회 중앙값·최댓값)을 다시 재고 README의 설계 단계 값(125.4MB, 49.8MB, 0.74–0.91초)과 비교한다.
결과는 README에 적는다. AWS Init Duration·최대 메모리는 AWS 담당이 첫 `dev` 배포 뒤 CloudWatch로 측정한다(BE-Q18).
- 배포 형식은 지금의 SAM ZIP(S3 업로드)이다. 컨테이너 이미지 배포로 바꾸지 않는다. zip 49.8MB는 콘솔 직접 업로드 한도(50MB)에 가깝지만 SAM은 S3로 올리므로 상관없고, 한도는 압축 해제 250MB다.

### 17.4 로컬 어댑터

`local/adapter/Dockerfile`이 `src/requirements.txt`와 `src/ai-requirements.lock`을 함께 설치한다(`python:3.12-slim`, manylinux wheel 사용). 이미지가 커지지만 같은 핸들러를 같은 의존성으로 부르기 위해서다.

## 18. Floci `DynamoDBSaver` 연결 확인 (BE-Q21, BE-Q84)

- 설계 단계에서 확인했다(§검증): Floci 2.5.0-compat 기본 엔진에서 `DynamoDBSaver(table_name="HaruAgentCheckpoints", region_name, endpoint_url, ttl_seconds=30*86400, consistent_read=True, boto_config=AI_SDK)`로 동기·비동기 모두 interrupt → `get_state` → `Command(resume)` → `delete_thread`가 동작했다. 대안(`FLOCI_SERVICES_DYNAMODB_BACKEND=local`, `amazon/dynamodb-local:3.3.2`)은 필요 없었다.
- 구현: 같은 확인을 `tests/local/test_local_checkpointer.py`(마커 `local`)로 남긴다. 스레드 ID는 `t6a_` + 임의값, 끝나면 `delete_thread`하고 그 스레드 항목 0건을 확인한다. 제품 경로(레벨 0 그래프)에는 연결하지 않는다.
- 6b 참고: 짧은 스레드 하나가 항목 18개를 썼다(체크포인트·청크·쓰기). 6b의 IAM(`BatchWriteItem` 등)과 400KB 한도 감시는 6b에서 정한다. `HaruAgentCheckpoints` SAM 리소스도 6b다.
- AWS 실제 테이블의 `consistent_read` 재개는 6b AWS 판정 항목(docs/02 §2.4.4 3번)이다.

## 19. EMF, AiQuota, 경로 스로틀

### 19.1 429 세 종류 (BE-Q92)

| 출처 | 상태·본문 | 서버 처리 | 프론트 |
|---|---|---|---|
| API Gateway 경로 스로틀 | 429, 본문 `{"message":"Too Many Requests"}`(계약 에러 형식 아님) | Lambda가 실행되지 않음. 할당량·세션 변화 없음 | **계약 예외**로 관리(docs/03 401 행과 같은 성격). 상태 코드로 AI 실패와 같게 처리하는지 프론트 리뷰 대상 |
| `AI_QUOTA_EXCEEDED` | 429, 계약 에러 형식 | 모델·세션 없음 | 사연 유지, 직접 작성(§3.7) |
| 외부 LLM 공급자 429 | (응답 아님) | LLM_Error `HTTP_429` → 후보 없음 → `FAILED` + 503 `AI_UNAVAILABLE` | 사연 유지, 직접 작성 |

- 공급자 429를 클라이언트 429로 그대로 내보내지 않는다(사용자 한도와 혼동). `AiFailure` 지표와 로그 `llmError=HTTP_429`로 구분한다.
- 시험: 세 경우를 각각 만든다(스로틀은 템플릿 단위 테스트와 AWS 판정, 할당량은 moto, 공급자 429는 Fake·스텁).

### 19.2 EMF·할당량·스로틀 값

- EMF(`common/metrics.emit`): `AiLatencyMs`(단위 Milliseconds, 세션 생성의 `graph.ainvoke` 시간), `AiFailure`(LLM_Error 1회마다 1, `TIME_BUDGET`·`CONFIG`·`KEY_READ_FAILED` 포함), `AiInvalidOutput`(검증 실패 출력 1회마다 1, `FALLBACK_INVARIANT`도 1). 네임스페이스 `Haru`, 차원 없음. 분류 코드는 로그 필드로만.
- `emit(name, value=1, unit="Count")`로 넓힌다. 5단계 브랜치의 같은 변경과 시그니처를 맞춰 병합 충돌을 줄인다. 기존 3종 출력은 바이트 단위로 같다(테스트).
- AiQuota: §5.2.
- 경로 스로틀(BE-Q82, 임시값): `POST /ai/card-sessions` rate 2/s·burst 5, `POST …/turns` rate 5/s·burst 10, `GET …/{sessionId}` rate 10/s·burst 20. 근거: 한 사용자가 하루 10세션이고 시범 운영 인원이 적다. 계정 기본 한도를 넘지 않는다. 초과 응답은 §19.1의 계약 예외다.

## 20. 테스트 전략

### 20.1 단위 (`tests/unit/`)

| 파일 | 내용 |
|---|---|
| `test_ai_card_schema.py` | 정규화(빈 문자열 → null, whyChosen ""), 경계값, strict 타입, JSON 추출(펜스·앞뒤 설명문·여러 객체·배열·잘림) |
| `test_ai_checks.py` | `check_draft`·`gate_verdict`·`rules`·`fallback`·`final_check` 표 사례(§9), 인덱스(§10.3), 마스킹 뒤 길이 |
| `test_ai_graph.py` | Fake 시나리오별 그래프 결과(호출 수, 상태, trace, first 보존), `TIME_BUDGET`, 12초 미만 재시도 생략 |
| `test_ai_llm.py` | 설정 파싱·`CONFIG`, SSM 캐시(성공 1회, 실패 미캐시, 다음 호출 재시도, Stubber), 오류 분류, `fake` 런타임 차단 |
| `test_ai_llm_stub.py` | 실제 `ChatOpenAI` + 로컬 스텁: 요청 형태, 오류 분류, `drip`·`hang` deadline(정해진 시간 ± 0.5초 안에 끊김), JSON 추출, usage 추정, Fake와 결과 비교 |
| `test_ai_session_service.py` | moto: AiSession `PutItem` 조건, Live_Session(ttl 경계), SessionView 허용 목록, AiQuota(§20.3) |
| `test_handlers_ai_card.py` | 3개 경로 분기 전체(§4), 404 본문 동일, 400 할당량 미사용, `AGENT_MODE` 오류 503 할당량 미사용, 저장 실패 500 |
| `test_ai_metrics.py` | §16 계산식, 비교 단위 예, 세션 제외 사유, 읽기 실패, `MANUAL`, 멱등 |
| `test_ai_logging.py` | 모든 시나리오에서 로그·trace·응답·AiSession 로그 필드에 사연 표본·카드 문자열·가짜 키·모델 응답이 없음, `logger.exception` 금지(AST 검사), 라이브러리 로거 수준 |
| `test_ai_tracing.py` | 두 변수를 `true`로 두어도 LangSmith 전송 0회 |
| `test_ai_isolation.py` | `domain/ai_*`·`common/*`가 AI 패키지 없이 import, 다른 핸들러가 `agent`를 import하지 않음 |
| `test_ai_lock.py` | 잠금 파일 규칙(§17.2) |
| `test_ai_timebudget.py` | `timeEpoch` 없음·문자열·음수·미래·오래됨·정상(§13.1), 12초·4초 경계, `call_deadline_s` |
| `test_ai_cancel.py` | 스텁 `drip`·`hang`·`close`에서 `call_llm` 전체 반환 시간 ≤ deadline + 500ms(20회 최댓값 기록), 취소 뒤 다음 호출 정상, Warm 30회(`asyncio.run` 반복)에서 `Event loop is closed`·`ResourceWarning`·미완료 태스크 없음 |
| `test_ai_save_uncertain.py` | `PutItem` 타임아웃 후 조회로 확인됨 → 200, 조건 실패인데 우리 항목 → 200, 다른 항목 → 500, 조회 실패·시간 부족 → 500, 할당량 그대로 |
| `test_ai_429.py` | 공급자 429 → 503 `AI_UNAVAILABLE`(Fake·스텁), 할당량 429 계약 형식, 템플릿 RouteSettings |
| `test_template.py`(수정) | AiCardFunction(27초, 1024MB, `BuildMethod: makefile`, 경로 3개, 환경 변수, `LLM_API_KEY` 없음, LangSmith 변수 2개), IAM(LeadingKeys, SSM 하나, 금지 권한 없음, 조건부 SSM 문장), RouteSettings, Rules·Conditions(Fake), `AgentMode` AllowedValues, 다른 함수 불변 |
| `test_local_init.py`·`test_adapter.py`(필요 시) | 변경 없음 확인 또는 AI 경로 디스패치 |

### 20.2 속성 기반 (hypothesis, 5단계 P25–P28 다음 번호)

| # | 성질 |
|---|---|
| P29 | 임의의 카드(장소 0–3, 임의 문자열·개인정보 표본·원문 일부)에 `rules` → (Gate 거부 시) `fallback` → `final_check`: 통과하면 `HIGH` 0, 스키마 오류 0, 장소 이름 NOT_IN_SOURCE 0, 장소의 비공개 장소 0, 활동 NOT_IN_SOURCE는 모두 `KEPT_FLAGGED` 메모와 플래그가 있음. 정상 코드에서 차단(BE-Q88)이 나오지 않음 |
| P30 | `flags[].path`는 모두 최종 카드에 있는 경로, `REMOVED` 메모 경로는 Candidate_Card에 있는 경로, `KEPT_FLAGGED` 경로는 최종 카드 경로 |
| P31 | SessionView: 상태별 `question`·`card`·`flags`·`notes` 규칙, 허용 목록 밖 키 없음, `places`는 배열 |
| P32 | 임의의 사연(블록 태그·유니코드 포함): 조립한 사용자 메시지에 `<story>`·`</story>`가 정확히 한 번씩, 사연 부분에 `<story`·`</story`·`<answer` 패턴 없음, `<`·태그 외 글자는 원문과 같음 |
| P33 | AiQuota: 임의의 요청 순서·한도 1–20·동시 수에서 성공 ≤ 한도, 성공 수 = 모델 호출 세션 수 |
| P34 | 임의의 사연·카드·시나리오: 로그와 trace에 사연·카드 문자열(4자 이상 부분 문자열) 없음 |
| P35 | `draft` 호출 수 ∈ {0, 1, 2}, 2회면 첫 실패가 검증 실패이고 두 번째 시작 때 remaining ≥ 12초 |
| P36 | `firstProposal`·`firstReport`는 그래프가 끝난 뒤에도 첫 `check_draft` 입력·출력과 같다 |

### 20.3 AiQuota·동시성

- 10건 성공·11번째 429, 429에서 Fake 호출 0·세션 없음, KST 경계(UTC 14:59:59.999 / 15:00:00.000, 키 이름과 `ttl`), 400은 할당량 미사용, 502·503도 1건, 사용자 분리.
- 스레드 동시: 남은 10에서 15건 → 성공 10·429 5·모델 호출 10, 남은 0에서 15건 → 성공 0·호출 0. moto·Floci는 실제 병렬성을 재현하지 않으므로 조건식 확인이다.

### 20.4 로컬 통합 (`tests/local/test_local_ai.py`, 마커 `local`)

Fake(`happy`)로 생성 → GET → turns(같은 turn 409, 다른 turn 200) → `POST /plans`(`AI_EDITED`, DynamoDB에서 지표 확인), 남의 세션 404, 11번째 429(테스트 전용 사용자), 만료 세션(ttl을 과거로 바꾼 항목) 404. `FAKE_LLM_SCENARIO`를 바꿔 띄웠을 때만 도는 사례: `http_401` → 503, `bad_json` → 502, `privacy_high` → degraded(가림·플래그). `test_local_checkpointer.py`는 §18.

### 20.5 AWS 통합 (`tests/integration/test_ai.py`, 작성·수집만)

- `test_T12_invalid_key`(`fault`): 함수 환경 `LLM_PROVIDER = openai_compat`이고 `LLM_API_KEY_PARAM`이 있을 때만 판정(아니면 사유 있는 skip). 합성 사연 → 503 `AI_UNAVAILABLE`, AiSession `FAILED`(`llmError = HTTP_401`), 그 사용자 GSI2 Plan 0건. 결과 파일 `scenario: "T12"`.
- `test_T12_aux_ssm_missing`(`fault`): 파라미터 없음 → 503 `KEY_READ_FAILED`. 결과 파일 `scenario: "T12-aux-ssm-missing"`, T12 통과로 세지 않음.
- `test_ai_routes_fake`(기본, `llmMode = fake`인 dev에서만): 생성·GET·turns·남의 세션 404·11번째 429. 결과 파일에 `llmMode: fake`.
- T1은 `ROUTES`를 돌므로 AI 경로 3개가 자동으로 포함된다.
- `_cleanup`: 테스트가 받은 `sessionId`와 `AIQUOTA#{sub}#{날짜}`를 등록해 지운다(테스트 실행 주체 권한에 `DeleteItem` 이미 있음).

### 20.6 회귀

1–3단계 단위 296건·로컬 16건 그대로 통과. `test_concurrency.py`는 AWS 담당이 6a 배포 때 다시 돈다.

## 21. 1–3단계 회귀와 4·5단계 통합

- 바꾸는 기존 파일과 방식: `errors.py`(상수·표 추가), `validation.py`(모델 추가), `ids.py`(함수 추가), `metrics.py`(`unit` 인자, 5단계와 같은 시그니처), `ddb.py`(`use_table`, 5단계와 같은 함수), `plan_service.py`(`compute_metrics`에 AI 지표 호출), `routes.py`(3줄), `template.yaml`(파라미터·함수·스로틀, `Stage`는 5단계와 같은 정의), `docker-compose.yml`(환경 변수), `local/adapter/Dockerfile`(설치 줄), `.env.example`, `requirements-dev.txt`, `test_template.py`, `README.md`, `docs/08`.
- 바꾸지 않는 것: `claim_service.py`, `ddb.transact_with_retry`, `fidelity.py`, `privacy.py`, `docs/03`, `frontend/`.
- 4·5단계 병합 뒤 할 일(README에 둔다): 기준 브랜치(4·5단계가 들어간 쪽)로 병합(rebase 없음) → 충돌 해결(`metrics.py`·`ddb.py`는 같은 함수로 하나, `Stage` 파라미터 하나, `routes.py`·`errors.py`·`test_template.py`는 합치기, docs/08 번호는 이미 BE-Q73부터라 충돌 없음) → 단위·로컬 전체 회귀 → `scripts/check_ai_build.py`(사진 Pillow 레이어 포함 모든 함수에 AI 패키지 없음) → AWS 판정(T1·T2·T12와 이전 단계 회귀).

## 22. 정확성·개인정보 불변식

1. AI 세션 경로는 Plan·Claim·Inbox·멱등 키를 만들거나 바꾸지 않는다(코드 + IAM LeadingKeys). (G6)
2. READY 카드에는 `HIGH` 개인정보, 스키마 오류, 원문에 없는 장소 이름, 장소의 비공개 장소가 없다. 남는 활동 `NOT_IN_SOURCE`는 반드시 `KEPT_FLAGGED` 메모와 플래그가 있다.
3. `flags`는 최종 카드의 경로만 가리키고, `REMOVED` 메모는 Candidate_Card 경로를 가리킨다.
4. `firstProposal`·`firstReport`는 첫 값에서 바뀌지 않는다.
5. 하루 성공한 세션 생성 수 ≤ `AI_DAILY_SESSION_LIMIT`(Asia/Seoul 날짜별, 사용자별). 429에서 모델을 부르지 않는다.
6. 세션 생성의 모델 호출은 0–2회이고, 2회째는 검증 실패 뒤 남은 시간 12초 이상일 때만이다.
7. 모든 정상 종료 응답은 SessionView 또는 계약 에러 형식이다. 공급자 오류는 503으로 끝난다.
8. 남의 세션·없는 세션·만료 세션은 같은 404이고 모델·DB 쓰기가 없다.
9. 사연·답변·프롬프트·모델 응답·카드 문자열·개인정보 일치 문자열·키·예외 메시지는 로그와 trace에 나오지 않는다. LangSmith로 아무것도 보내지 않는다.
10. 키는 메모리 캐시에만 있고, 읽기 실패는 캐시되지 않는다. AWS 설정에는 키 이름만 있다.
11. `MANUAL` 작성과 `POST /plans`는 AI 세션 상태와 무관하게 막히지 않는다.
12. AI 패키지는 AiCardFunction 산출물에만 있고, 다른 함수 산출물은 각각 혼자 import·실행된다.
13. SessionView와 Plan `metrics`에 `llmMode` 같은 내부 속성이 나가지 않는다.
14. 저장을 확정하지 못한 세션 생성은 200을 돌려주지 않는다. 할당량은 되돌리지 않는다.

## 미결 사항

### 이번 설계에서 상태가 바뀐 것

| # | 상태 | 내용 |
|---|---|---|
| BE-Q18 | 일부 확인 | 압축 해제 125.4MB·zip 49.8MB, 개발 PC import 0.74–0.91초. AWS Init Duration·메모리는 AWS 측정 대기 |
| BE-Q21 | 로컬 확인 | Floci 기본 엔진에서 `DynamoDBSaver` 동작(동기·비동기, interrupt·resume·TTL·delete_thread). 대안 불필요. AWS 테이블 재개는 6b 판정 |
| BE-Q76 | 일부 결정 | `places`는 항상 배열(빈 배열 + `MISSING(places)`). trace 단계 이름·문구(§10.4)와 메모 문구는 **프론트 리뷰 대상** |
| BE-Q78 | 설계 확정 | async + `asyncio.wait_for`, 호출마다 `AsyncClient`. 로컬 스텁으로 확인 |
| BE-Q79 | 설계 확정 | §16 계산식·비교 단위. 리뷰 대상 |
| BE-Q80 | 설계 확정 | Makefile 빌드, `--use-container` 확인. `--require-hashes`는 구현 때 확인 |
| BE-Q81 | 확인 | CloudFormation은 SecureString 미지원(문서), `aws/ssm`은 KMS 권한 불필요(문서) |
| BE-Q82 | 임시값 | §19 값. BE-Q8 결과로 확정 |
| BE-Q85 | 설계 확정(값은 측정으로 조정) | AI 전용 `Config` connect 1·read 2·시도 2 |
| BE-Q87 | 일부 결정 | 미설정 → `pipeline`, 그 밖 → 503(할당량 전), 템플릿 `AllowedValues: [pipeline]`. 비종료 세션 처리(6a 임시 500)와 6b 전환 호환성은 **미결** |
| BE-Q88 | 결정 | §9.4 차단·허용 표 |

### 그대로 남는 것

BE-Q6(공급자·모델), BE-Q7(동의 문구), BE-Q8(동시 실행 한도), BE-Q9(공급자 파라미터 실측), BE-Q10(전송 전 마스킹), BE-Q11(단가), BE-Q12(지연), BE-Q13·FE-Q7(`REMOVED` 원래 값), BE-Q14(T22), BE-Q73(Asia/Seoul 권장안, 팀 리뷰), BE-Q86(Fake dev 허용 권장안, 팀 리뷰).

### 새로 생긴 것

| # | 질문 | 임시 기본안 |
|---|---|---|
| BE-Q89 | 모델 호출 뒤 AiSession 저장이 실패·불확실할 때 | **결정**: 남은 시간 1.5초 이상이면 강한 일관성 조회로 확인, 확정 못 하면 500 `INTERNAL_ERROR`. 할당량 환불 없음. 클라이언트가 500을 받았는데 세션이 남는 경우가 있다(TTL로 삭제) |
| BE-Q90 | HTTP API 30초에 콜드 스타트 Init이 포함되므로 `requestContext.timeEpoch` + 29초를 함께 쓰는 방식이 AWS에서 맞는지(시계 차이, Init 포함 여부) | 그렇게 구현하고, 값이 없거나 범위 밖이면 무시(§13.1). AWS 첫 배포에서 Init Duration과 함께 확인 |
| BE-Q91 | 정상 `null`과 스키마 위반의 구분, 위반 처리 | **결정**: §3.1 표. 위반만 시간 예산 안에서 최대 1회 재시도, 유효 후보가 없으면 502. 위반 필드를 `null`로 바꿔 통과시키지 않는다. 리허설에서 502가 잦으면 다시 검토 |
| BE-Q92 | 429 세 종류의 구분 | **결정**: §19.1. 공급자 429는 503 `AI_UNAVAILABLE`. API Gateway 스로틀 본문은 계약 예외로 관리하고 **프론트 리뷰 대상** |
