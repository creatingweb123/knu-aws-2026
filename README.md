# 이어온 하루 — 취소된 하루를 양도합니다

AWS Skill Training 1조 프로젝트 저장소입니다. 기획·명세 문서와 백엔드·프론트엔드 코드를 모두 이 저장소에서 관리합니다.

**이어온 하루**는 사정이 생겨 실현하지 못한 일상 계획(취소된 하루)을 다른 사람에게 양도하고, 그 사람이 직접 경험한 기록과 이야기를 돌려받는 모바일 웹입니다. 핵심 가치는 계획의 양도, 경험의 공유, 경험의 반환입니다. 계획을 남기는 사람을 **계획자**, 이어받아 실행하는 사람을 **실행자**라고 부릅니다.

```
[계획자] 취소된 하루를 남긴다 → [실행자] 한 명이 이어받는다 → 경험 기록을 보낸다 → [계획자] 수신함에서 읽고 답장한다
```

이 README는 세 가지를 구분해서 씁니다.

| 구분 | 내용 |
|---|---|
| 서비스의 본질 | 실현하지 못한 계획을 다른 사람에게 양도하고, 그 사람이 직접 경험한 결과와 이야기를 원래 계획자에게 돌려줍니다. 계획 종류가 아니라 **취소된 하루가 한 사람에게서 다른 사람에게 넘어가고, 그 경험이 돌아오는 것**이 중심입니다 |
| MVP 적용 범위 | 다른 사람이 대신 경험할 수 있는 짧은 일상 활동. 공개 장소 중심, 장소 1–3곳, 계획 하나당 실행자 한 명, 기한 3일, 경험 기록은 글 + 선택 사진 1장. 시범 운영은 한 동네로 한정합니다(운영 범위 정책이며 서비스가 동네 산책이어야 한다는 뜻이 아닙니다) |
| 대표 활용 사례 | 동네 산책, 카페·음식점 방문, 서점·소품점 둘러보기, 전시회·문화공간 관람, 공원에서 쉬기, 특정 장소 사진 촬영, 추억의 장소 다시 가 보기, 여러 곳을 잇는 짧은 나들이 등. 예시일 뿐 고정 목록이 아닙니다 |

산책 경로를 공유하는 서비스가 아닙니다. 지도, 경로 탐색, 결제, 예약, 실시간 위치, 다중 실행자, 장기 여행은 만들지 않으며, 장소를 모아 보여주는 것도 목적이 아닙니다. 문서의 '동네 산책'(지연·수현·민준) 시나리오는 이 흐름을 보여 주는 대표 사례 하나일 뿐입니다.

## 핵심

| 핵심 | 내용 |
|---|---|
| 양도와 반환 | 취소된 계획과 그 계획에 담긴 사연(왜 이 계획을 세웠는지)을 공개하고, 한 명이 이어받고, 실행자가 직접 경험한 기록(글 + 선택 사진 1장)이 원래 계획자에게 돌아간다 |
| 정합성 | 여러 사람이 동시에 요청해도 **한 명만 확정**한다. 같은 완료 요청을 재시도해도 경험 기록과 수신함 알림은 **한 건**이다. 포기한 뒤 들어온 이전 요청은 거부한다 (DynamoDB 조건부 갱신·트랜잭션, 보장 G1–G4, 검증 시나리오 T3–T7) |
| AI 정리 | 계획자가 적은 사연을 세션형 에이전트가 활동 목록, 계획 이유, 방문 질문 한 개로 정리한다. 장소가 한 곳이어도, 걷지 않는 활동이어도 같은 규칙으로 정리한다. 원문에 없는 내용은 에이전트가 검사 도구로 점검해 고치고, 꼭 필요한 빈칸만 최대 2번 묻는다. 사용자가 확인한 카드만 저장한다 |

## 사용자와 흐름

| 역할 | 설명 |
|---|---|
| 계획자 | 이사, 일정 변경 등 사정으로 계획했던 일상 활동을 하지 못한 사람 |
| 실행자 | 남이 남긴 계획을 이어받아 직접 경험해 보고 싶은 사람 |

1. 계획자가 사연을 입력하면 AI가 하루 카드로 정리하고, 계획자가 폼에서 다듬어 공개합니다. AI가 실패하면 직접 작성으로 넘어갑니다.
2. 실행자가 둘러보기에서 하루를 읽고 이어받습니다. 확정되는 사람은 한 명이며, 포기하면 다시 공개됩니다. 기한은 이어받은 뒤 3일입니다.
3. 실행자가 직접 경험한 일을 경험 기록(글 + 선택 사진 1장)으로 보냅니다. 사진은 비동기로 처리하면서 위치 정보를 지우고, 처리에 실패하면 글만으로 완료할 수 있습니다.
4. 계획자가 수신함에서 원래 계획과 경험 기록을 나란히 읽고 한 줄 답장을 보냅니다.

동네 문화공간을 초기 도입 후보로 검토합니다. 운영자용 기능은 MVP에 넣지 않습니다.

## 구성

React 모바일 웹과 AWS 서버리스 API로 이루어집니다. 구성도는 [§2.1](./docs/02-architecture.md)에 있습니다.

| 영역 | 기술 |
|---|---|
| 프론트엔드 | React 18, TypeScript, Vite, React Router, TanStack Query, Amplify Auth, MSW(개발용 목업) |
| 백엔드 | API Gateway(HTTP API) + Lambda(Python 3.12), DynamoDB 단일 테이블, Cognito, S3 + SQS(사진 처리) |
| AI | LangGraph `StateGraph` 에이전트가 LLM을 호출한다. 기본 공급자는 `bedrock`(Amazon Bedrock Converse, IAM 인증)이고 설정으로 `openai_compat`(외부 OpenAI 호환 API)·`fake`를 고를 수 있다. 문제가 있으면 `AGENT_MODE=pipeline`(레벨 0)으로 낮춘다 |
| 개발 환경 | docker compose(AWS 호환 에뮬레이터, HTTP 어댑터, Fake LLM). 개발과 단위·로컬 통합 테스트용 |
| 배포·검증 | AWS SAM, CloudFront + S3, CloudWatch. 데모와 T1–T22 검증은 실제 AWS 스택에서 한다 |

## 저장소 구조

```
docs/         # 기획·명세·API 계약·개발 계획 (기준 문서)
references/   # 초안 PDF, 화면 시안, AI 에이전트 권고안
scripts/      # 문서용 스크립트 (아키텍처 그림 생성)
backend/      # 백엔드 코드: Python 3.12, AWS SAM (구조는 §2.10)
frontend/     # 프론트엔드 코드: React, TypeScript, Vite (구조는 §2.10)
```

`backend/`와 `frontend/`는 구현을 시작하면서 만듭니다.

## 문서

| 장 | 문서 | 내용 |
|---|---|---|
| 1 | [`docs/01-overview.md`](./docs/01-overview.md) | 서비스의 본질·MVP 적용 범위·대표 활용 사례, 문제 정의, 목표, 사용자와 핵심 흐름, MVP 범위, 백엔드가 보장하는 것(G1–G8) |
| 2 | [`docs/02-architecture.md`](./docs/02-architecture.md) | 아키텍처, 기술 스택, Lambda 구성, 로컬 개발 환경, 도메인 모델, DynamoDB 설계, 사진 처리, 권한, 관측, 저장소 구조 |
| 3 | [`docs/03-api-contract.md`](./docs/03-api-contract.md) | **API 계약**: 요청·응답 형식, AI 세션 동작 규칙, 에러 코드, 프론트엔드의 에러 처리 |
| 4 | [`docs/04-ai-agent.md`](./docs/04-ai-agent.md) | AI 하루 카드 정리 에이전트: 도입 결정, 그래프 설계, 구현 선택, 가드레일, 평가 |
| 5 | [`docs/05-screens.md`](./docs/05-screens.md) | 화면 목록, 화면별 동작과 분기, 공통 문구와 데모 사례 문구, 디자인 가이드, 화면 시안 |
| 6 | [`docs/06-requirements.md`](./docs/06-requirements.md) | 요구사항 목록(`BE-*`, `FE-*`), 비기능 요구사항, 인수 기준 |
| 7 | [`docs/07-development-plan.md`](./docs/07-development-plan.md) | 단계별 계획, 연동 지점 S0–S5, 테스트 전략, 검증 시나리오 T1–T22, 완료 기준, 위험 |
| 8 | [`docs/08-open-questions.md`](./docs/08-open-questions.md) | 확인이 필요한 사항(`BE-Q1`–`BE-Q33`, `FE-Q1`–`FE-Q9`), 문서 사이의 불일치 |

절 번호는 문서 전체에서 하나만 씁니다. 첫 숫자가 장(문서) 번호이므로 `§3.2`는 `03-api-contract.md`의 3.2절입니다.

참고 자료

| 파일 | 내용 |
|---|---|
| [`references/aws1조_초안.pdf`](./references/aws1조_초안.pdf) | 프로젝트 초안: 문제 정의, 목표, 아키텍처, 주요 기능, 데모 계획 |
| [`references/이어온 하루-동네산책.pdf`](./references/이어온%20하루-동네산책.pdf) | 최신 화면 시안 (MVP 기준, 대표 사례인 동네 산책 문구로 그려짐) |
| [`references/이어온 하루.pdf`](./references/이어온%20하루.pdf) | 이전 화면 시안 (레이아웃 참고용) |
| [`references/AI_AGENT_PROPOSAL.md`](./references/AI_AGENT_PROPOSAL.md) | AI 에이전트 도입 권고안 (2026-11-21) |

초안 PDF, 화면 시안 PDF, 권고안은 작성 시점의 기록입니다. 시안과 초안에 나오는 '산책' 문구와 인물은 대표 사례이며, 서비스의 정의와 범위는 현행 명세(`docs/`)가 우선합니다. AI 구현 방식은 그 뒤에 바뀌었습니다. 2026-11-21에 외부 OpenAI 호환 API(`openai_compat`)와 LangGraph로 바꿨고, 2026-11-27부터는 Amazon Bedrock Converse(`bedrock`)가 다시 기본 공급자입니다. 에이전트 루프는 계속 LangGraph가 맡습니다. 현재 설계는 `docs/`를 따릅니다. `docs/images/architecture-ai-agent.png`도 이전 설계로 그려져 있어 다시 생성해야 합니다.

## 문서 사이의 우선순위

- **API 계약의 기준은 [`docs/03-api-contract.md`](./docs/03-api-contract.md)입니다.** 프론트엔드의 타입과 MSW 목업은 이 계약을 따릅니다. 계약을 바꿀 때는 이 문서를 먼저 고치고 프론트엔드 담당의 리뷰를 받은 뒤 코드에 반영합니다.
- 요구사항 목록(6장)과 명세(2–5장)가 다르면 명세가 우선합니다.

## 진행 현황 (2026-11-27)

상태 용어는 [`.kiro/specs/backend-stage7-ops/requirements.md`](./.kiro/specs/backend-stage7-ops/requirements.md)의 표를 따릅니다(구현·단위·로컬 통합·SAM 정적 검증·승인 대기·실제 AWS 배포 대기·실제 AWS 인수 판정 대기).

- 문서: 명세, 요구사항, 개발 계획 작성 완료. 백엔드 7단계 spec은 [`.kiro/specs/backend-stage7-ops/`](./.kiro/specs/backend-stage7-ops/)입니다.
- 백엔드(`main`에 병합): 1–6b단계(6a·6b는 AI 레벨 0·에이전트)와 LLM 공급자 Amazon Bedrock 전환(`bedrock` 기본, `openai_compat`·`fake` 선택). 이 중 1–3단계 15건만 2026-11-25 `haru-dev`에서 AWS 판정을 통과했고 나머지는 AWS 판정 전입니다.
- 백엔드(2026-11-27 `main`에 병합, AWS 배포 전): `GET /claims/{claimId}/record`(BE-Q46 권장안, §3.4 503 계약은 **프론트엔드 담당 승인 대기**), 7단계 웹 버킷·CloudFront(OAC)·알람·대시보드·선택 Budgets, `scripts/seed.py`·`report.py`·`deploy_web.py`·`photo_orphans.py`. 단위·로컬 통합·`cfn-lint`·`sam validate --lint`·`sam build --use-container` 통과, **실제 AWS 배포·인수 판정 대기**([인계 문서](./.kiro/specs/backend-stage7-ops/aws-handoff.md)).
- 프론트엔드: 1–6단계 완료, 7단계는 로그인·Amplify 연동 코드까지이며(MSW 목업·로컬 백엔드 dev-jwt 연동 확인), 실제 Cognito·API 전환과 배포는 AWS 스택 배포 뒤입니다.
- 일정: 담당자와 날짜는 아직 정해지지 않았습니다([`docs/07-development-plan.md`](./docs/07-development-plan.md)).
- LLM 운영 공급자·모델·외부 전송 동의 문구·마스킹 정책: 팀 결정 대기(BE-Q6·Q7·Q10, [`docs/08-open-questions.md`](./docs/08-open-questions.md)).
- 데모 링크: 배포 후 기재합니다.

## 최근 변경

| 날짜 | 내용 |
|---|---|
| 2026-11-27 | 서비스 정의를 '취소된 하루의 양도와 경험의 반환'으로 일반화하고(본질·MVP 적용 범위·대표 활용 사례 구분), 명세 문서(docs/01·02·05–07)의 산책 종속 문구를 정리했다. 코드·목업 문구와 검증 상태는 backend/README, frontend/README를 따른다 |
| 2026-11-27 | LLM 기본 공급자를 Amazon Bedrock(Converse, `bedrock`)으로 전환(`openai_compat`·`fake` 경로 유지). 프론트엔드 1–7단계(7단계는 인증 코드까지)와 백엔드 4단계(수신함), 5단계(사진 파이프라인), 6a단계(AI 레벨 0), 6b단계(AI 에이전트)를 `main`에 병합했다 |
| 2026-11-27 | 백엔드 7단계(웹 호스팅·알람·대시보드·시드·성과 집계)와 `GET /record`를 `feat/be-7-completion`에 구현(AWS 배포 전). 병합 충돌로 깨진 `docker-compose.yml` 수정. 상세는 backend/README 0절 |
| 2026-11-21 | LLM을 Amazon Bedrock에서 외부 OpenAI 호환 API로, 에이전트를 직접 구현한 루프에서 LangGraph 그래프로, 개발 환경을 로컬 Docker(AWS 호환 에뮬레이터)로 전환. 데모와 검증은 계속 실제 AWS에서 한다 |
| 2026-11-21 | AI 하루 카드를 단발 생성에서 세션형 정리 에이전트로 전환 |
| 2026-11-20 | 명세, 요구사항, 개발 계획 작성 |
