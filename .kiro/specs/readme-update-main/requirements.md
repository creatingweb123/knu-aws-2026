# Requirements Document

## Introduction

`main` 브랜치(HEAD `bef1702`, "Merge branch 'feat/be-bedrock'")에 병합된 상태를 기준으로 저장소 문서를 갱신한다. `main`에는 백엔드 1·2단계, 3단계, 6a단계, 6b단계와 LLM 기본 공급자 Amazon Bedrock 전환(`2b9af27`), 프론트엔드 1–7단계(7단계는 인증 코드까지, `33aea80`)가 들어 있다. 백엔드 4단계(수신함)와 5단계(사진)는 `main`에 없다.

갱신 대상은 다섯 곳이다.

- 루트 `README.md`의 "진행 현황"과 "최근 변경"
- `backend/README.md` §1 "인계 상태 요약" (병합 상태로 덮어쓰되 단계별 범위, AWS 검증 상태, 단위 테스트 1154건을 유지)
- `frontend/README.md`의 "상태"
- `docs/02-architecture.md`와 `docs/04-ai-agent.md`의 LLM 공급자 설명 (Bedrock 기본, `openai_compat`·`fake` 유지)

작업 시점의 작업 트리는 `origin/feat/be-4-inbox`(`dc3af68`)를 `main`에 병합하는 중이며 그 변경이 스테이징되어 있다. 이 병합 중인 내용은 기준에 포함하지 않는다. 코드는 바꾸지 않고 문서만 바꾼다.

## Glossary

- **Main_Snapshot**: 커밋 `bef1702`의 파일 트리. 모든 문서 내용의 사실 기준이다.
- **Pending_Merge**: 작업 트리에 스테이징된 `origin/feat/be-4-inbox` 병합 변경. Main_Snapshot에 속하지 않는다.
- **Root_README**: 저장소 루트의 `README.md`.
- **Backend_README**: `backend/README.md`.
- **Backend_Summary**: Backend_README의 §1 "인계 상태 요약" 표와 그 바로 뒤 안내 문단.
- **Frontend_README**: `frontend/README.md`.
- **Frontend_Status**: Frontend_README의 "상태" 절.
- **Architecture_Doc**: `docs/02-architecture.md`.
- **Agent_Doc**: `docs/04-ai-agent.md`.
- **Target_Docs**: Root_README, Backend_README, Frontend_README, Architecture_Doc, Agent_Doc를 함께 이르는 말.
- **Doc_Updater**: 이 작업에서 Target_Docs를 고치는 작업자(개발자 또는 에이전트).
- **Bedrock_Provider**: `LLM_PROVIDER=bedrock` 경로. langchain-aws의 `ChatBedrockConverse`로 Amazon Bedrock Converse API를 부르고, 인증은 함수 실행 역할의 IAM 권한 `bedrock:InvokeModel`이며 API 키와 SSM 파라미터를 쓰지 않는다. `LLM_MODEL`은 Bedrock 모델 ID 또는 추론 프로필 ID, 호출 리전은 `LLM_REGION`(빈 값이면 `AWS_REGION`)이다.
- **OpenAI_Compat_Provider**: `LLM_PROVIDER=openai_compat` 경로. `ChatOpenAI`로 외부 OpenAI 호환 Chat Completions API를 부르고 키는 SSM SecureString에서 읽는다.
- **Fake_Provider**: `LLM_PROVIDER=fake` 경로. 시나리오별로 미리 정한 응답을 돌려주는 Fake 채팅 모델이다.

## Requirements

### Requirement 1: 사실 기준

**User Story:** 팀원으로서, 문서가 `main`에 실제로 병합된 내용만 설명하기를 원한다. 그래야 문서를 보고 `main`의 상태를 판단할 수 있다.

#### Acceptance Criteria

1. THE Doc_Updater SHALL Target_Docs에 적는 단계 범위, 커밋, 브랜치, 테스트 건수, 설정 기본값을 Main_Snapshot의 파일 내용과 커밋 기록에서 확인한 값으로 적는다.
2. IF 어떤 내용이 Pending_Merge에만 있고 Main_Snapshot에 없으면, THEN THE Doc_Updater SHALL 그 내용을 `main`에 병합된 것으로 적지 않는다.
3. THE Doc_Updater SHALL 이 작업에서 Target_Docs 밖의 파일과 Target_Docs의 지정되지 않은 절을 바꾸지 않는다.
4. WHEN Target_Docs의 기존 문장이 Main_Snapshot과 다를 때, THE Doc_Updater SHALL 그 문장을 Main_Snapshot에 맞게 고치고 새 상태가 시작된 날짜(2026-11-27)를 함께 적는다.

### Requirement 2: 루트 README 진행 현황

**User Story:** 저장소를 처음 보는 사람으로서, 루트 README에서 현재 어디까지 구현되었는지 알고 싶다. 그래야 각 하위 README로 바로 찾아갈 수 있다.

#### Acceptance Criteria

1. THE Root_README SHALL "진행 현황" 제목의 날짜를 Main_Snapshot 기준 날짜(2026-11-27)로 표시한다.
2. THE Root_README SHALL "진행 현황"에 `main`에 병합된 백엔드 단계(1·2단계, 3단계, 6a단계, 6b단계)와 병합되지 않은 백엔드 단계(4단계, 5단계, 7단계)를 구분해 적는다.
3. THE Root_README SHALL "진행 현황"에 프론트엔드 1–6단계 완료와 7단계 인증 코드까지의 구현 상태를 적는다.
4. THE Root_README SHALL "진행 현황"의 LLM 공급자 항목에 기본 공급자가 Amazon Bedrock(Converse)이고 `openai_compat`과 `fake`가 선택 경로로 남아 있다는 사실을 적는다.
5. THE Root_README SHALL "진행 현황"에 백엔드 1–3단계의 AWS 판정 결과(2026-11-25 `haru-dev` 15건 통과)와 6a·6b단계의 AWS 배포·판정 미실시 상태를 적는다.
6. THE Root_README SHALL "진행 현황"의 각 항목에서 세부 근거로 Backend_README 또는 Frontend_README의 해당 절을 링크한다.
7. THE Root_README SHALL "최근 변경" 표의 맨 위에 2026-11-27 행을 추가하고, 그 행에 LLM 기본 공급자의 Amazon Bedrock 전환과 프론트엔드 1–7단계·백엔드 6b단계의 `main` 병합을 적는다.
8. THE Root_README SHALL "최근 변경" 표의 기존 행을 유지한다.

### Requirement 3: 백엔드 인계 상태 요약

**User Story:** AWS 담당으로서, 백엔드 README §1에서 `main`에 있는 백엔드의 범위와 검증 상태를 한 표로 보고 싶다. 그래야 무엇을 배포하고 판정해야 하는지 알 수 있다.

#### Acceptance Criteria

1. THE Backend_Summary SHALL Main_Snapshot에 병합된 상태로 덮어써진 내용을 담는다.
2. THE Backend_Summary SHALL 단계별 범위 행을 1·2단계, 3단계, 6a단계, 6b단계, Bedrock 전환으로 나누어 각 단계의 기능 범위와 spec 경로(`.kiro/specs/...`)를 적는다.
3. THE Backend_Summary SHALL 4단계와 5단계가 `main`에 병합되지 않았다는 사실과 해당 작업 브랜치 이름을 적는다.
4. THE Backend_Summary SHALL 브랜치 행에 기준 브랜치 `main`과 HEAD 커밋 `bef1702`를 적는다.
5. THE Backend_Summary SHALL 단위 테스트 행에 `pytest tests/unit` 1154건 통과(2026-11-27, Bedrock 전환 커밋 `2b9af27` 기준)를 적는다.
6. THE Backend_Summary SHALL AWS 검증 행에 1–3단계 판정 결과(T1·T13·T3·T4·T5·T6·T7·T14·T16 15건 통과, 2026-11-25, `haru-dev`)와 6a·6b단계 및 Bedrock 경로의 AWS 배포·판정 미실시 상태를 구분해 적는다.
7. THE Backend_Summary SHALL LLM 공급자 행에 Bedrock_Provider가 기본값이고 OpenAI_Compat_Provider와 Fake_Provider가 유지된다는 사실, 그리고 배포 전 확인 절(10.2절)로 가는 참조를 적는다.
8. THE Backend_Summary SHALL SAM 행과 로컬 환경(Docker) 행에 Main_Snapshot에서 확인된 검증 결과만 적는다.
9. THE Backend_Summary SHALL PR 행에 Main_Snapshot 시점의 병합 방식과 열린 PR 상태를 Main_Snapshot의 커밋 기록과 일치하게 적는다.
10. THE Backend_Summary SHALL 표 뒤 안내 문단에서 참조하는 절 번호를 Backend_README의 실제 절 번호와 일치시킨다.

### Requirement 4: 프론트엔드 상태

**User Story:** 프론트엔드 담당으로서, 프론트엔드 README의 상태 절이 `main` 병합 상태를 보여 주기를 원한다. 그래야 다음 연동 작업의 출발점을 알 수 있다.

#### Acceptance Criteria

1. THE Frontend_Status SHALL 1–6단계가 완료되어 `main`에 병합되었다는 사실(병합 커밋 `33aea80`)을 적는다.
2. THE Frontend_Status SHALL 7단계가 로그인·Amplify 연동 코드까지 구현되었고 실제 Cognito 연동과 배포가 AWS 계정을 필요로 한다는 사실을 적는다.
3. THE Frontend_Status SHALL 연동 항목에 MSW 목업 모드 확인 상태와 실제 API·Cognito 전환이 백엔드 `dev` 스택 배포 뒤(S1–S5)라는 조건을 적는다.
4. THE Frontend_Status SHALL 스타일 항목의 기존 결정(CSS Modules, FE-Q3, FE-Q5, FE-Q14)을 유지한다.
5. WHEN Frontend_README 머리말이 특정 단계 spec 하나만 "이번 단계 spec"으로 가리킬 때, THE Frontend_README SHALL 그 문장을 Main_Snapshot에 있는 프론트엔드 spec 경로(`.kiro/specs/frontend-stage*`)를 가리키는 문장으로 바꾼다.

### Requirement 5: 아키텍처 문서의 LLM 공급자 설명

**User Story:** 아키텍처를 읽는 팀원으로서, docs/02의 LLM 설명이 실제 기본 공급자를 반영하기를 원한다. 그래야 배포 구성과 권한을 잘못 이해하지 않는다.

#### Acceptance Criteria

1. THE Architecture_Doc SHALL AWS 배포의 기본 LLM 경로를 Bedrock_Provider로 설명한다.
2. THE Architecture_Doc SHALL OpenAI_Compat_Provider와 Fake_Provider를 선택 경로로 설명한다.
3. THE Architecture_Doc SHALL 그림 안내 문단에서 Bedrock Converse 경로와 현재 설계의 관계를 Main_Snapshot의 구현과 일치하게 고친다.
4. THE Architecture_Doc SHALL 텍스트 도식의 LLM 호출 대상을 Main_Snapshot의 기본 공급자와 일치시킨다.
5. THE Architecture_Doc SHALL 환경 변수 표의 `LLM_PROVIDER` 행에 허용 값 `bedrock`, `openai_compat`, `fake`와 로컬·AWS 각각의 기본값을 Main_Snapshot의 `docker-compose.yml`과 `template.yaml` 기본값대로 적는다.
6. THE Architecture_Doc SHALL 환경 변수 표에 `LLM_REGION` 행을 두고, 빈 값이면 `AWS_REGION`을 쓴다는 규칙을 적는다.
7. THE Architecture_Doc SHALL `LLM_MODEL` 설명에 Bedrock 모델 ID 또는 추론 프로필 ID를 넣는다는 규칙을 적는다.
8. THE Architecture_Doc SHALL `LLM_API_KEY`와 `LLM_API_KEY_PARAM`이 OpenAI_Compat_Provider 전용이라는 사실을 적는다.
9. THE Architecture_Doc SHALL AI 함수의 IAM 권한 설명에 `bedrock:InvokeModel`을 적는다.
10. THE Architecture_Doc SHALL `agent/llm.py` 설명에 Bedrock_Provider가 `ChatBedrockConverse`를, OpenAI_Compat_Provider가 `ChatOpenAI`를 쓴다는 사실을 적는다.
11. THE Architecture_Doc SHALL 로컬 LLM 절(2.4.5)의 Fake_Provider 기본값 설명을 Main_Snapshot의 `docker-compose.yml` 기본값과 일치시킨다.

### Requirement 6: AI 에이전트 문서의 LLM 공급자 설명

**User Story:** AI 에이전트를 맡은 개발자로서, docs/04가 현재 공급자 구성과 의존성을 정확히 설명하기를 원한다. 그래야 빌드와 배포 설정을 문서만 보고 맞출 수 있다.

#### Acceptance Criteria

1. THE Agent_Doc SHALL 설계 변경 이력 표에 2026-11-27 Bedrock 전환 내용을 반영해, 현재 구현이 LangGraph `StateGraph`와 Bedrock_Provider 기본값을 쓴다고 적는다.
2. THE Agent_Doc SHALL 도입 배경 인용문의 "구현 수단이 바뀌었다"는 설명을 Bedrock Converse가 기본 공급자로 돌아왔다는 사실과 일치하게 고친다.
3. THE Agent_Doc SHALL 의존성 목록에 `langchain-aws==1.10.0`을 추가하고 기존 고정 의존성을 유지한다.
4. THE Agent_Doc SHALL Bedrock_Provider의 인증이 IAM `bedrock:InvokeModel`이고 API 키와 SSM 파라미터를 쓰지 않는다는 사실을 적는다.
5. THE Agent_Doc SHALL Bedrock_Provider의 호출 리전이 `LLM_REGION`이고 빈 값이면 `AWS_REGION`이라는 규칙을 적는다.
6. THE Agent_Doc SHALL OpenAI_Compat_Provider와 Fake_Provider가 선택 경로로 유지된다는 사실을 적는다.
7. THE Agent_Doc SHALL 로컬 개발 행의 Fake_Provider 기본값 설명을 Main_Snapshot의 `docker-compose.yml` 기본값과 일치시킨다.

### Requirement 7: 문서 일관성

**User Story:** 리뷰어로서, 고친 문서끼리 용어와 숫자가 맞기를 원한다. 그래야 문서마다 다른 상태를 읽지 않는다.

#### Acceptance Criteria

1. THE Target_Docs SHALL 같은 사실(단위 테스트 1154건, HEAD `bef1702`, 기본 공급자 Bedrock, AWS 판정 15건)을 모든 위치에서 같은 값으로 적는다.
2. THE Target_Docs SHALL 공급자 이름을 `bedrock`, `openai_compat`, `fake`의 설정 값 표기로 통일한다.
3. THE Doc_Updater SHALL 고친 문단의 상대 링크가 Main_Snapshot에 있는 파일과 제목을 가리키는지 확인한다.
4. THE Target_Docs SHALL 기존 문서의 한국어 평서체("~다") 문체와 표 형식을 유지한다.
