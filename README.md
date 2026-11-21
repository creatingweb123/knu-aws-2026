# 이어온 하루 — 취소된 하루를 양도합니다

AWS Skill Training 1조 프로젝트의 문서 저장소입니다. 기획, 명세, API 계약, 개발 계획의 기준이 이 저장소입니다.

**이어온 하루**는 취소된 동네 산책을 이어받고, 그날의 이야기를 돌려주는 모바일 웹입니다. 계획자가 하지 못한 산책 계획(공개 장소 1–3곳)을 남기면 같은 동네의 실행자 한 명이 이어받아 다녀옵니다. 실행자의 방문 기록(글 + 선택 사진 1장)은 계획자의 수신함에 정확히 한 번 도착하고, 계획자는 한 줄 답장을 보냅니다.

| 저장소 | 역할 |
|---|---|
| 이 저장소 | 문서 (기준) |
| [knu-aws-2026-001/frontend](https://github.com/knu-aws-2026-001/frontend) | 프론트엔드 코드 (React, TypeScript, Vite) |
| [knu-aws-2026-001/backend](https://github.com/knu-aws-2026-001/backend) | 백엔드 코드 (Python, AWS SAM) |

## 문서

먼저 `docs/`의 여섯 문서로 전체를 파악하고, 구현할 때 `docs/spec/`의 세부 명세를 봅니다.

| 순서 | 문서 | 내용 |
|---|---|---|
| 1 | [`docs/01-overview.md`](./docs/01-overview.md) | 문제 정의, 목표, 사용자와 핵심 흐름, MVP 범위, 백엔드가 보장하는 것 |
| 2 | [`docs/02-system.md`](./docs/02-system.md) | 아키텍처, 기술 스택, 로컬 개발 환경, 도메인 모델, API 목록, 화면과 API·Lambda 대응표 |
| 3 | [`docs/03-ai-agent.md`](./docs/03-ai-agent.md) | AI 하루 카드 정리 에이전트: 도입 결정, 그래프 설계, 구현 선택, 가드레일, 평가 |
| 4 | [`docs/04-development-plan.md`](./docs/04-development-plan.md) | 프론트엔드·백엔드 단계별 계획, 연동 지점 S0–S5, 검증 시나리오 T1–T22, 위험 |
| 5 | [`docs/05-design-mockups.md`](./docs/05-design-mockups.md) | 화면 시안 정리, 디자인 가이드, 시안과 명세의 차이 |
| 6 | [`docs/06-open-questions.md`](./docs/06-open-questions.md) | 확인이 필요한 사항(백엔드 Q1–Q21, 프론트엔드 Q1–Q9)과 문서 사이의 불일치 |

세부 명세

| 영역 | 명세 | 요구사항 명세서 | 개발계획서 |
|---|---|---|---|
| 백엔드 | [`backend.md`](./docs/spec/backend.md) (도메인 모델, DynamoDB, **API 계약 §7**, 사진 처리, 검증 시나리오) | [`backend-requirements.md`](./docs/spec/backend-requirements.md) (`BE-*`) | [`backend-development-plan.md`](./docs/spec/backend-development-plan.md) (로컬 개발 환경 10장 포함) |
| 프론트엔드 | [`frontend.md`](./docs/spec/frontend.md) (화면 목록, 화면별 동작, 디자인 가이드) | [`frontend-requirements.md`](./docs/spec/frontend-requirements.md) (`FE-*`) | [`frontend-development-plan.md`](./docs/spec/frontend-development-plan.md) |

참고 자료

| 파일 | 내용 |
|---|---|
| [`references/aws1조_초안.pdf`](./references/aws1조_초안.pdf) | 프로젝트 초안: 문제 정의, 목표, 아키텍처, 주요 기능, 데모 계획 |
| [`references/이어온 하루-동네산책.pdf`](./references/이어온%20하루-동네산책.pdf) | 최신 화면 시안 (동네 산책 버전, MVP 기준) |
| [`references/이어온 하루.pdf`](./references/이어온%20하루.pdf) | 이전 화면 시안 (캠퍼스 산책 버전, 레이아웃 참고용) |
| [`references/AI_AGENT_PROPOSAL.md`](./references/AI_AGENT_PROPOSAL.md) | AI 에이전트 도입 권고안 (2026-11-21) |

초안 PDF와 권고안은 작성 시점의 기록입니다. AI 구현 방식이 그 뒤에 바뀌었으므로(Amazon Bedrock → 외부 OpenAI 호환 API와 LangGraph) 현재 설계는 `docs/`를 따릅니다.

## 문서 사이의 우선순위

- **API 계약의 기준은 [`docs/spec/backend.md`](./docs/spec/backend.md) §7입니다.** 프론트엔드의 타입과 MSW 목업은 이 계약을 따릅니다. 계약을 바꿀 때는 이 문서를 먼저 고치고 프론트엔드 담당의 리뷰를 받은 뒤 코드에 반영합니다.
- 요구사항 명세서와 명세(`backend.md`, `frontend.md`)가 다르면 명세가 우선합니다.
- `docs/01`–`06`은 요약입니다. 세부 명세와 다르면 세부 명세가 우선하고, 요약을 고칩니다.

## 진행 현황 (2026-11-21)

- 문서: 명세, 요구사항 명세서, 개발계획서 작성 완료.
- 구현: 프론트엔드 1–7단계, 백엔드 1–7단계(6단계는 6a·6b) 모두 시작 전입니다.
- 일정: 담당자와 날짜는 아직 정해지지 않았습니다([`docs/04-development-plan.md`](./docs/04-development-plan.md)).
- LLM 공급자와 모델: 아직 정해지지 않았습니다([`docs/06-open-questions.md`](./docs/06-open-questions.md)).
- 데모 링크: 배포 후 기재합니다.

## 최근 변경

| 날짜 | 내용 |
|---|---|
| 2026-11-21 | LLM을 Amazon Bedrock에서 외부 OpenAI 호환 API로, 에이전트를 직접 구현한 루프에서 LangGraph 그래프로, 개발 환경을 로컬 Docker(AWS 호환 에뮬레이터)로 전환. 데모와 검증은 계속 실제 AWS에서 한다 |
| 2026-11-21 | AI 하루 카드를 단발 생성에서 세션형 정리 에이전트로 전환 |
| 2026-11-20 | 명세, 요구사항 명세서, 개발계획서 작성 |
