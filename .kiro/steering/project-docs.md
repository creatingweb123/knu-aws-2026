---
inclusion: always
---

# 이어온 하루: 프로젝트 문서 기준

## 기준 문서

- 명세의 기준은 `docs/`다. 문서에 없는 결정을 새로 만들지 않는다. 필요한 결정이 문서에 없으면 `docs/08-open-questions.md`의 해당 질문 번호(`BE-Q*`, `FE-Q*`)와 함께 미결로 표시한다.
- API 계약의 기준은 `docs/03-api-contract.md`다. 요청·응답 형태, 에러 코드, 필드 이름을 임의로 바꾸지 않는다.
- 요구사항 ID(`BE-*`, `FE-*`), 보장(G1–G8), 검증 시나리오(T1–T22), 연동 지점(S0–S5) 번호를 spec과 코드, PR에서 그대로 쓴다.
- `references/`의 초안 PDF와 권고안은 작성 시점의 기록이다. 현재 설계(LangGraph + 외부 OpenAI 호환 LLM, 로컬 Docker 개발 환경)와 다르면 `docs/`를 따른다.

## 서비스 정체성

- 이어온 하루는 **취소된 하루를 양도하는 서비스**다. 산책 경로·코스 공유 서비스가 아니다. 문서와 코드, 문구를 쓸 때 계획을 '산책 코스'로 한정하거나 경로·동선 공유처럼 읽히게 쓰지 않는다. '동네 산책'은 데모 예시일 뿐이다.

## 저장소 구조

- 문서와 코드를 한 저장소에 둔다. 백엔드 코드는 `backend/`, 프론트엔드 코드는 `frontend/` 아래에 만든다.
- 문서에 나오는 코드 경로는 영역 폴더 기준이다. 백엔드 경로(`src/...`, `tests/...`, `scripts/seed.py` 등)는 `backend/` 아래, 프론트엔드 경로(`src/api/client.ts` 등)는 `frontend/` 아래다. 루트 `scripts/`는 문서용이다.
- 상세 구조는 `docs/02-architecture.md` §2.10을 따른다.

## 필요할 때 읽을 문서

| 작업 | 문서 |
|---|---|
| 아키텍처, 데이터 모델, 로컬 환경, 권한 | `docs/02-architecture.md` |
| AI 하루 카드 에이전트 | `docs/04-ai-agent.md` |
| 화면과 분기 | `docs/05-screens.md` |
| 요구사항과 인수 기준 | `docs/06-requirements.md` |
| 단계별 범위, 테스트, 완료 기준 | `docs/07-development-plan.md` |
| 미결 사항 | `docs/08-open-questions.md` |

## 항상 참고하는 문서

#[[file:docs/01-overview.md]]
#[[file:docs/03-api-contract.md]]
