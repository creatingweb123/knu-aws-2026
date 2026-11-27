# Requirements Document

## Introduction

`main` 브랜치 HEAD `17486ed`("Merge branch 'feat/be-5-photo-pipeline'")에 병합된 상태를 기준으로 저장소 문서를 갱신한다. `bef1702` 뒤에 `main`에는 `8f4c288`(백엔드 4단계 수신함 병합)과 `17486ed`(백엔드 5단계 사진 파이프라인 병합)가 더해졌다. 그래서 `17486ed`의 `main`에는 다음이 모두 들어 있다.

- 백엔드 1·2단계, 3단계, 4단계(수신함), 5단계(사진 파이프라인), 6a단계(AI 레벨 0), 6b단계(AI 에이전트)
- LLM 기본 공급자의 Amazon Bedrock(Converse) 전환(`2b9af27`, 병합 `bef1702`)
- 프론트엔드 1–6단계와 7단계 인증 코드(병합 `33aea80`)

`main`에 없는 것은 백엔드 7단계(웹 배포·관측·시연 준비, spec 없음), 프론트엔드 7단계의 실제 Cognito 연동·실제 API 전환·배포, 4단계 묶음 B의 `GET /claims/{claimId}/record`(BE-Q46, 계약 변경 승인 대기)다.

`17486ed`의 `backend/README.md` §1은 병합 과정에서 4·5단계 브랜치 쪽 행이 합쳐졌다. 그러나 브랜치·PR 행은 병합 전 상태를 그대로 적고 있고, Bedrock 전환 행과 병합 뒤 단위 테스트 건수가 없다. 저장소에 기록된 가장 최근 단위 테스트 건수는 Bedrock 전환 커밋 메시지의 1154건(`2b9af27`, 4·5단계 병합 전)이다. 4·5단계 병합 뒤의 건수는 저장소 어디에도 기록되어 있지 않다. 이 요구사항을 쓰면서 `17486ed` 작업 트리에서 `pytest tests/unit`를 돌린 결과는 1505건 통과, 1건 skip, 2건 deselect(`slow` 표시)였다.

갱신 대상은 다음과 같다.

- 루트 `README.md`의 "구성" 표 AI 행, "참고 자료" 아래 AI 구현 방식 안내 문장, "진행 현황", "최근 변경"
- `backend/README.md` §1 "인계 상태 요약" 표와 바로 뒤 안내 문단
- `frontend/README.md`의 머리말과 "상태"
- `docs/02-architecture.md`와 `docs/04-ai-agent.md`의 LLM 공급자 설명(Bedrock 기본, `openai_compat`·`fake` 유지, 로컬 compose 기본값 `fake`)

코드는 바꾸지 않고 문서만 바꾼다. 작업 시작 시 작업 트리는 깨끗하고 병합 중인 변경이 없다.

## Glossary

- **Main_Snapshot**: 커밋 `17486ed`의 파일 트리와 그 커밋까지의 기록(`git show 17486ed:<파일>`, `git log 17486ed`). 모든 문서 내용의 사실 기준이다.
- **Root_README**: 저장소 루트의 `README.md`.
- **Backend_README**: `backend/README.md`.
- **Backend_Summary**: Backend_README의 §1 "인계 상태 요약" 표와 그 바로 뒤 안내 문단.
- **Frontend_README**: `frontend/README.md`.
- **Frontend_Status**: Frontend_README의 "상태" 절.
- **Architecture_Doc**: `docs/02-architecture.md`.
- **Agent_Doc**: `docs/04-ai-agent.md`.
- **Target_Docs**: Root_README, Backend_README, Frontend_README, Architecture_Doc, Agent_Doc를 함께 이르는 말.
- **Doc_Updater**: 이 작업에서 Target_Docs를 고치는 작업자(개발자 또는 에이전트).
- **Unit_Test_Run**: Doc_Updater가 Main_Snapshot 작업 트리의 `backend/`에서 `pytest tests/unit`를 실행한 결과(통과·skip·deselect 건수와 실행 날짜).
- **Merged_Backend_Stages**: Main_Snapshot에 병합된 백엔드 단계. 1·2단계, 3단계, 4단계, 5단계, 6a단계, 6b단계와 Bedrock 전환이다.
- **Unmerged_Items**: Main_Snapshot에 없는 항목. 백엔드 7단계, 프론트엔드 7단계의 실제 Cognito 연동·실제 API 전환·배포, `GET /claims/{claimId}/record`(BE-Q46)다.
- **Bedrock_Provider**: `LLM_PROVIDER=bedrock` 경로. langchain-aws의 `ChatBedrockConverse`로 Amazon Bedrock Converse API를 부른다. 인증은 함수 실행 역할의 IAM 권한 `bedrock:InvokeModel`이고 API 키와 SSM 파라미터를 쓰지 않는다. `LLM_MODEL`은 Bedrock 모델 ID 또는 추론 프로필 ID, 호출 리전은 `LLM_REGION`(빈 값이면 `AWS_REGION`)이다. 로컬 실모델 경로는 호스트에서 AWS 프로필을 켜고 `scripts/eval_agent.py --env-file .env`로 실행할 때다. 로컬 `docker-compose.yml` 컨테이너 안에서는 AWS 자격 증명이 Floci용 고정 `test` 값이라 호출이 401로 끝난다.
- **OpenAI_Compat_Provider**: `LLM_PROVIDER=openai_compat` 경로. `ChatOpenAI`로 외부 OpenAI 호환 Chat Completions API를 부르고, AWS에서는 키를 SSM SecureString에서, 로컬에서는 `.env`의 `LLM_API_KEY`에서 읽는다.
- **Fake_Provider**: `LLM_PROVIDER=fake` 경로. 시나리오별로 미리 정한 응답을 돌려주는 Fake 채팅 모델이다. 로컬 `docker-compose.yml`의 기본값이다.

## Requirements

### Requirement 1: 사실 기준과 전제 조건

**User Story:** 팀원으로서, 문서가 `main`에 실제로 병합된 내용만 설명하기를 원한다. 그래야 문서를 보고 `main`의 상태를 판단할 수 있다.

#### Acceptance Criteria

1. WHEN 문서 수정을 시작할 때, THE Doc_Updater SHALL `main`의 HEAD가 `17486ed`인지 확인한다.
2. IF `main`의 HEAD가 `17486ed`가 아니면, THEN THE Doc_Updater SHALL 문서를 고치기 전에 작업을 멈추고 새 HEAD와 `17486ed` 사이의 커밋 목록을 보고한다.
3. THE Doc_Updater SHALL Target_Docs에 적는 단계 범위, 커밋, 브랜치, 테스트 건수, 설정 기본값을 Main_Snapshot의 파일 내용, 커밋 기록, Unit_Test_Run에서 확인한 값으로 적는다.
4. IF 어떤 내용이 Main_Snapshot에 없는 브랜치나 커밋에만 있으면, THEN THE Doc_Updater SHALL 그 내용을 `main`에 병합된 것으로 적지 않는다.
5. IF 어떤 검증 결과(로컬 통합 테스트, SAM 빌드, AWS 판정, PR 상태)가 4·5단계 병합 뒤에 기록되지 않았으면, THEN THE Doc_Updater SHALL 그 항목을 마지막으로 기록된 결과와 기록 시점의 브랜치로 적고 병합 뒤에는 확인하지 않았다고 적는다.
6. THE Doc_Updater SHALL 이 작업에서 Target_Docs 밖의 파일과 Target_Docs의 지정되지 않은 절을 바꾸지 않는다.
7. WHEN Target_Docs의 기존 문장이 Main_Snapshot과 다를 때, THE Doc_Updater SHALL 그 문장을 Main_Snapshot에 맞게 고치고 새 상태가 시작된 날짜(2026-11-27)를 함께 적는다.
8. IF 갱신에 필요한 결정이 `docs/`에 없으면, THEN THE Doc_Updater SHALL 그 항목을 `docs/08-open-questions.md`의 해당 질문 번호와 함께 미결로 적는다.

### Requirement 2: 루트 README

**User Story:** 저장소를 처음 보는 사람으로서, 루트 README에서 현재 어디까지 구현되었고 AI가 어떤 공급자를 쓰는지 알고 싶다. 그래야 각 하위 README로 바로 찾아갈 수 있다.

#### Acceptance Criteria

1. THE Root_README SHALL "구성" 표의 AI 행에 LangGraph `StateGraph` 에이전트의 기본 LLM이 Amazon Bedrock(Converse)이고 `openai_compat`과 `fake`를 설정으로 고를 수 있으며 `AGENT_MODE=pipeline`(레벨 0)으로 낮출 수 있다는 사실을 적는다.
2. THE Root_README SHALL "참고 자료" 아래 AI 구현 방식 안내 문장을 Bedrock Converse가 2026-11-27부터 기본 공급자라는 사실과 일치하게 고친다.
3. THE Root_README SHALL "진행 현황" 제목의 날짜를 2026-11-27로 표시한다.
4. THE Root_README SHALL "진행 현황"에 Merged_Backend_Stages와 `main`에 병합되지 않은 백엔드 7단계를 구분해 적는다.
5. THE Root_README SHALL "진행 현황"에 프론트엔드 1–6단계 완료와 7단계 인증 코드까지의 구현 상태를 적는다.
6. THE Root_README SHALL "진행 현황"의 LLM 공급자 항목에 기본 공급자가 Amazon Bedrock(Converse)이고 `openai_compat`과 `fake`가 선택 경로로 남아 있다는 사실과, 사용할 모델이 미결(BE-Q6)인지 여부를 `docs/08-open-questions.md`의 상태대로 적는다.
7. THE Root_README SHALL "진행 현황"에 백엔드 1–3단계의 AWS 판정 결과(2026-11-25 `haru-dev` 15건 통과)와 4단계, 5단계, 6a단계, 6b단계, Bedrock 경로의 AWS 배포·판정 미실시 상태를 적는다.
8. THE Root_README SHALL "진행 현황"의 각 항목에서 세부 근거로 Backend_README 또는 Frontend_README의 해당 절을 링크한다.
9. THE Root_README SHALL "최근 변경" 표의 맨 위에 2026-11-27 행을 추가하고, 그 행에 LLM 기본 공급자의 Amazon Bedrock 전환과 프론트엔드 1–7단계(7단계는 인증 코드까지), 백엔드 4단계, 5단계, 6a단계, 6b단계의 `main` 병합을 적는다.
10. THE Root_README SHALL "최근 변경" 표의 기존 행을 유지한다.

### Requirement 3: 백엔드 인계 상태 요약

**User Story:** AWS 담당으로서, 백엔드 README §1에서 `main`에 있는 백엔드의 범위와 검증 상태를 한 표로 보고 싶다. 그래야 무엇을 배포하고 판정해야 하는지 알 수 있다.

#### Acceptance Criteria

1. THE Backend_Summary SHALL Main_Snapshot에 병합된 상태를 기준으로 다시 쓴 내용을 담는다.
2. THE Backend_Summary SHALL 범위 항목을 1·2단계, 3단계, 4단계, 5단계, 6a단계, 6b단계, Bedrock 전환으로 나누어 각 단계의 기능 범위를 적는다.
3. THE Backend_Summary SHALL spec 항목에 Main_Snapshot의 백엔드 spec 경로 6개(`.kiro/specs/backend-stage1-2-foundation/`, `backend-stage3-claim/`, `backend-stage4-record-inbox/`, `backend-stage5-photo-pipeline/`, `backend-stage6a-ai-pipeline/`, `backend-stage6b-ai-agent/`)를 적는다.
4. THE Backend_Summary SHALL 브랜치 항목에 기준 브랜치 `main`, HEAD 커밋 `17486ed`, 4단계 병합 커밋 `8f4c288`, 5단계 병합 커밋 `17486ed`, Bedrock 전환 병합 커밋 `bef1702`를 적는다.
5. THE Backend_Summary SHALL `GET /claims/{claimId}/record`가 Main_Snapshot에 없고 계약 변경 승인 대기(BE-Q46)라는 사실을 적는다.
6. THE Backend_Summary SHALL 백엔드 7단계가 `main`에 없고 spec도 아직 없다는 사실을 적는다.
7. THE Backend_Summary SHALL 단위 테스트 항목에 Unit_Test_Run의 통과·skip·deselect 건수, 실행 날짜, 기준 커밋 `17486ed`를 적는다.
8. THE Backend_Summary SHALL 단위 테스트 항목에서 이전 기록 1154건을 4·5단계 병합 전 Bedrock 전환 커밋 `2b9af27` 기준 값으로만 표시한다.
9. THE Backend_Summary SHALL AWS 판정 항목에 1–3단계 판정 결과(T1·T13·T3·T4·T5·T6·T7·T14·T16 15건 통과, 2026-11-25, `haru-dev`)를 적는다.
10. THE Backend_Summary SHALL AWS 판정 항목에 4단계(T1 확장·T2·T17), 5단계(T8·T9·T10·T11·T15), 6a단계, 6b단계, Bedrock 경로의 테스트 작성 여부와 AWS 배포·판정 미실시 상태를 단계별로 구분해 적는다.
11. THE Backend_Summary SHALL 다음 단계 조건 항목에 병합 뒤 AWS 통합 회귀(`tests/integration/test_concurrency.py` 재실행, 10.8절 작업 22)가 아직 실행되지 않았다는 사실을 적는다.
12. THE Backend_Summary SHALL LLM 공급자 항목에 Bedrock_Provider가 기본값이고 OpenAI_Compat_Provider와 Fake_Provider가 유지된다는 사실과 배포 전 확인 절(10.2절)로 가는 참조를 적는다.
13. THE Backend_Summary SHALL SAM 항목과 로컬 환경(Docker) 항목에 Main_Snapshot의 Backend_README에 기록된 단계별 결과만 적고, 4·5단계 병합 뒤 결과가 없는 항목에는 병합 뒤 미확인이라고 적는다.
14. THE Backend_Summary SHALL PR 항목에 4·5단계와 Bedrock 전환이 Main_Snapshot에 병합 커밋으로 들어왔다는 사실을 적고, GitHub PR(#1–#8)의 열림·닫힘 상태는 Doc_Updater가 직접 확인한 경우에만 확인 날짜와 함께 적는다.
15. IF Doc_Updater가 GitHub PR 상태를 확인하지 못하면, THEN THE Backend_Summary SHALL PR 상태를 미확인으로 적는다.
16. THE Backend_Summary SHALL 표 뒤 안내 문단에서 참조하는 절 번호를 Main_Snapshot Backend_README의 실제 절 번호(6a는 10절, 6b는 11절, 5단계는 12절)와 일치시킨다.

### Requirement 4: 프론트엔드 상태

**User Story:** 프론트엔드 담당으로서, 프론트엔드 README의 상태 절이 `main` 병합 상태를 보여 주기를 원한다. 그래야 다음 연동 작업의 출발점을 알 수 있다.

#### Acceptance Criteria

1. THE Frontend_Status SHALL 1–6단계가 완료되어 `main`에 병합되었다는 사실(병합 커밋 `33aea80`)을 적는다.
2. THE Frontend_Status SHALL 7단계가 로그인·Amplify 연동 코드까지 구현되었고 실제 Cognito 연동과 배포가 AWS 계정을 필요로 한다는 사실을 적는다.
3. THE Frontend_Status SHALL 연동 항목에 MSW 목업 모드 확인 상태와 실제 API·Cognito 전환이 백엔드 `dev` 스택 배포 뒤(S1–S5)라는 조건을 적는다.
4. THE Frontend_Status SHALL 스타일 항목의 기존 결정(CSS Modules, FE-Q3, FE-Q5, FE-Q14)을 유지한다.
5. WHEN Frontend_README 머리말이 특정 단계 spec 하나만 "이번 단계 spec"으로 가리킬 때, THE Frontend_README SHALL 그 문장을 Main_Snapshot에 있는 프론트엔드 spec 경로(`.kiro/specs/frontend-stage*`, 7단계는 `frontend-stage7a-auth`)를 가리키는 문장으로 바꾼다.

### Requirement 5: 아키텍처 문서의 LLM 공급자 설명

**User Story:** 아키텍처를 읽는 팀원으로서, docs/02의 LLM 설명이 실제 기본 공급자를 반영하기를 원한다. 그래야 배포 구성과 권한을 잘못 이해하지 않는다.

#### Acceptance Criteria

1. THE Architecture_Doc SHALL AWS 배포의 기본 LLM 경로를 Bedrock_Provider로 설명한다.
2. THE Architecture_Doc SHALL OpenAI_Compat_Provider와 Fake_Provider를 선택 경로로 설명한다.
3. THE Architecture_Doc SHALL 그림 안내 문단에서 Bedrock Converse 경로와 현재 설계의 관계를 Main_Snapshot의 구현과 일치하게 고친다.
4. THE Architecture_Doc SHALL 텍스트 도식의 LLM 호출 대상을 Main_Snapshot의 기본 공급자와 일치시킨다.
5. THE Architecture_Doc SHALL 환경 변수 표의 `LLM_PROVIDER` 행에 허용 값 `bedrock`, `openai_compat`, `fake`와 기본값(로컬 `docker-compose.yml`은 `fake`, AWS `template.yaml`의 `LlmProvider`는 `bedrock`)을 적는다.
6. THE Architecture_Doc SHALL 환경 변수 표에 `LLM_REGION` 행을 두고, 빈 값이면 `AWS_REGION`을 쓴다는 규칙을 적는다.
7. THE Architecture_Doc SHALL `LLM_MODEL` 설명에 Bedrock_Provider에서는 Bedrock 모델 ID 또는 추론 프로필 ID를 넣는다는 규칙을 적는다.
8. THE Architecture_Doc SHALL `LLM_API_KEY`와 `LLM_API_KEY_PARAM`이 OpenAI_Compat_Provider 전용이라는 사실을 적는다.
9. THE Architecture_Doc SHALL AI 함수의 IAM 권한 설명에 `bedrock:InvokeModel`을 적는다.
10. THE Architecture_Doc SHALL `agent/llm.py` 설명에 Bedrock_Provider가 `ChatBedrockConverse`를, OpenAI_Compat_Provider가 `ChatOpenAI`를 쓴다는 사실을 적는다.
11. THE Architecture_Doc SHALL 로컬 LLM 절(2.4.5)에 호스트와 컨테이너를 나누어 적는다. (a) 호스트 실모델 경로는 `LLM_PROVIDER=bedrock`을 AWS 프로필을 켠 호스트에서 `scripts/eval_agent.py --env-file .env`로 실행하는 것이며 합성 사연만 쓴다. `LLM_MODEL`과 `LLM_REGION`은 `.env`에 둔다. (b) 로컬 `docker-compose.yml` 컨테이너의 기본값은 Fake_Provider이고, 컨테이너 안의 Bedrock 호출은 Floci용 고정 `test` 자격 증명 때문에 401로 끝난다(Main_Snapshot의 `docker-compose.yml` 63–64행 주석). 컨테이너에서 실모델을 쓰면 OpenAI_Compat_Provider(Ollama 포함)를 쓴다. `.env`는 compose에도 읽히므로 `.env`의 `LLM_PROVIDER=bedrock`은 컨테이너도 401로 만든다는 점을 함께 적는다.

### Requirement 6: AI 에이전트 문서의 LLM 공급자 설명

**User Story:** AI 에이전트를 맡은 개발자로서, docs/04가 현재 공급자 구성과 의존성을 정확히 설명하기를 원한다. 그래야 빌드와 배포 설정을 문서만 보고 맞출 수 있다.

#### Acceptance Criteria

1. THE Agent_Doc SHALL 설계 변경 이력 표에 2026-11-27 Bedrock 전환 내용을 반영해, 현재 구현이 LangGraph `StateGraph`와 Bedrock_Provider 기본값을 쓴다고 적는다.
2. THE Agent_Doc SHALL 도입 배경 인용문의 "구현 수단이 바뀌었다"는 설명을 Bedrock Converse가 기본 공급자로 돌아왔다는 사실과 일치하게 고친다.
3. THE Agent_Doc SHALL 의존성 목록에 `langchain-aws==1.10.0`을 추가하고 기존 고정 의존성을 유지한다.
4. THE Agent_Doc SHALL Bedrock_Provider의 인증이 IAM `bedrock:InvokeModel`이고 API 키와 SSM 파라미터를 쓰지 않는다는 사실을 적는다.
5. THE Agent_Doc SHALL Bedrock_Provider의 호출 리전이 `LLM_REGION`이고 빈 값이면 `AWS_REGION`이라는 규칙을 적는다.
6. THE Agent_Doc SHALL OpenAI_Compat_Provider와 Fake_Provider가 선택 경로로 유지된다는 사실을 적는다.
7. THE Agent_Doc SHALL 로컬 개발 행에 로컬 `docker-compose.yml`의 기본값이 Fake_Provider라는 사실을 적고, 실모델 확인은 호스트에서 Bedrock_Provider(`scripts/eval_agent.py --env-file .env`)로 한다는 사실과, 컨테이너 안에서는 Bedrock 호출이 401이라는 사실을 적는다.

### Requirement 7: 문서 일관성

**User Story:** 리뷰어로서, 고친 문서끼리 용어와 숫자가 맞기를 원한다. 그래야 문서마다 다른 상태를 읽지 않는다.

#### Acceptance Criteria

1. THE Target_Docs SHALL 같은 사실(Unit_Test_Run 건수, HEAD `17486ed`, 기본 공급자 Bedrock, AWS 판정 15건, Merged_Backend_Stages 목록)을 모든 위치에서 같은 값으로 적는다.
2. THE Target_Docs SHALL 공급자 이름을 `bedrock`, `openai_compat`, `fake`의 설정 값 표기로 통일한다.
3. THE Doc_Updater SHALL 고친 문단의 상대 링크가 Main_Snapshot에 있는 파일과 제목을 가리키는지 확인한다.
4. THE Target_Docs SHALL 기존 문서의 문체(루트 README는 "~합니다", 나머지는 "~다")와 표 형식을 유지한다.
5. THE Target_Docs SHALL 요구사항 ID(`BE-*`, `FE-*`), 보장(G1–G8), 검증 시나리오(T1–T22), 연동 지점(S0–S5), 미결 질문 번호(`BE-Q*`, `FE-Q*`)를 원래 표기대로 쓴다.
