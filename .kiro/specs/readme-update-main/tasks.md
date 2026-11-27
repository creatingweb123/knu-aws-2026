# Implementation Plan: readme-update-main

## Overview

`main` HEAD `17486ed` 기준으로 Target_Docs 다섯 곳(루트 `README.md`, `backend/README.md` §1, `frontend/README.md` 머리말·상태, `docs/02-architecture.md`, `docs/04-ai-agent.md`)의 지정된 절만 고친다. 코드·설정·테스트 파일은 바꾸지 않는다. 먼저 선행 조건을 확인하고 단위 테스트를 다시 돌려 정본 값을 확정한 뒤, 문서마다 하나의 작업으로 고치고, 마지막에 design.md의 Correctness Properties 1–8 셸 검사와 Prettier 검사로 확인한다.

모든 사실 값은 design.md "정본 값 표"를 따른다. 측정 결과와 범위 밖 불일치는 `.kiro/specs/readme-update-main/review-notes.md`(커밋하지 않음, PR 설명에 옮김)에 적는다.

## Tasks

- [x] 1. 선행 조건 확인과 사전 측정
  - [x] 1.1 HEAD와 작업 트리를 확인하고 작업 브랜치를 만든다
    - `git rev-parse --short main`이 `17486ed`인지 확인한다. 다르면 문서를 고치지 않고 `git log --oneline 17486ed..main` 결과를 보고한 뒤 멈춘다
    - `.git/MERGE_HEAD`가 없고 `git status --porcelain`이 `.kiro/specs/readme-update-main/` 밖에 변경을 보이지 않는지 확인한다. 조건을 어기면 병합·리셋을 대신 실행하지 않고 사용자에게 정리를 요청한 뒤 멈춘다
    - 통과하면 `17486ed`에서 작업 브랜치를 만든다(예: `git switch -c docs/readme-update-main 17486ed`, 이름은 사용자가 정한다)
    - _Requirements: 1.1, 1.2, 1.6_
  - [x] 1.2 단위 테스트를 다시 돌리고 결과를 기록한다
    - `backend/`에서 `.venv/bin/pytest tests/unit -q -rs`를 실행한다
    - 통과·skip·deselect 건수, skip 1건의 사유, 실행 날짜, 기준 커밋 `17486ed`를 `review-notes.md`에 적는다
    - 결과가 1505/1/2와 다르면 재실행 값을 정본으로 쓰고 차이를 `review-notes.md`에 적는다. 실행이 실패하거나 실패 테스트가 있으면 건수를 정본으로 쓰지 않고 실패 내용을 보고한 뒤 멈춘다
    - _Requirements: 1.3, 3.7, 3.8_
  - [x] 1.3 GitHub PR 상태를 읽기 전용으로 확인한다
    - `gh pr list --repo creatingweb123/knu-aws-2026 --state all --limit 20 --json number,state,title,headRefName`을 실행한다
    - 성공하면 #1–#8의 번호별 상태와 확인 날짜를, 실패하면 "미확인"을 `review-notes.md`에 적는다
    - _Requirements: 3.14, 3.15_

- [x] 2. 루트 `README.md`를 고친다
  - "구성" 표 AI 행(43행): 기본 공급자 `bedrock`(Amazon Bedrock Converse, IAM 인증), 선택 `openai_compat`·`fake`, `AGENT_MODE=pipeline`(레벨 0)으로 낮추기를 적는다(design.md 1.1)
  - "참고 자료" 아래 안내 문장(83행): 2026-11-21 외부 OpenAI 호환 API·LangGraph 전환, 2026-11-27부터 `bedrock` 기본, 루프는 LangGraph로 고친다. 그림 다시 생성 문장은 그대로 둔다(design.md 1.2)
  - "진행 현황"(90–96행): 제목 날짜를 2026-11-27로 바꾸고, 93행 "구현"을 백엔드(`main`에 병합됨)·백엔드(`main`에 없음, 7단계와 BE-Q46)·백엔드 AWS 검증(1–3단계 15건 통과, 4·5·6a·6b·Bedrock 판정 전)·프론트엔드(1–6단계 완료, 7단계 인증 코드까지, `33aea80`) 항목으로 나눈다. 95행 LLM 공급자 항목을 `bedrock` 기본, `openai_compat`·`fake` 선택, 운영 공급자·모델 미결(BE-Q6)로 고친다. 각 항목에 `backend/README.md` §1 또는 `frontend/README.md` "상태" 링크를 단다. 92·94·96행은 그대로 둔다(design.md 1.3)
  - "최근 변경" 표: 구분선 바로 아래에 2026-11-27 행을 넣고 기존 102–104행은 글자 그대로 둔다(design.md 1.4)
  - 57·70행 등 지정 절 밖 불일치는 고치지 않고 `review-notes.md`에 적는다(design.md 1.5)
  - 문체는 본문 "~합니다", 표 칸 "~다"를 유지한다
  - _Requirements: 1.3, 1.4, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 7.1, 7.2, 7.4, 7.5_

- [x] 3. `backend/README.md` §1 "인계 상태 요약"을 고친다
  - 7–26행(표와 안내 문단)을 design.md 2.2의 행 순서대로 다시 쓴다. 3행 머리말과 5행 제목, §1 밖의 절은 바꾸지 않는다
  - 표는 `| 항목 | 상태 |` 2열 형식을 유지한다
  - 기준·브랜치 행: `main`, HEAD `17486ed`, 4단계 `8f4c288`, 5단계 `17486ed`, Bedrock 전환 `bef1702`(전환 커밋 `2b9af27`), 1–3·6a·6b단계 fast-forward
  - 범위 행: 1·2단계, 3단계, 4단계, 5단계(12절), 6a단계(10절), 6b단계(11절), Bedrock 전환으로 나눈다
  - `main`에 없는 것 행: `GET /claims/{claimId}/record`(BE-Q46, `f3626c0`에만 있음), 백엔드 7단계(spec 없음)
  - spec 행: 백엔드 spec 폴더 여섯 개
  - 단위 테스트 행: 작업 1.2의 건수·날짜·`17486ed`. 1154건은 `2b9af27`, 4·5단계 병합 전 값으로만 적는다
  - SAM·로컬 환경(Docker) 행: 단계별 기록과 그 브랜치를 적고, `17486ed` 결과가 없으면 "병합 뒤 미확인"을 붙인다
  - AWS 판정 행: 1–3단계 15건 통과(2026-11-25, `haru-dev`), 4·5단계와 6a·6b·Bedrock은 테스트 작성 여부와 배포·판정 전 상태를 단계별로 적는다
  - LLM 공급자 행: `bedrock` 기본, `openai_compat`·`fake` 유지, BE-Q6 미결, 10.2절 참조
  - 다음 단계 조건 행: 기존 문장 유지, 병합 뒤 AWS 통합 회귀(`tests/integration/test_concurrency.py`, 10.8절 작업 22) 미실행 추가
  - PR 행: 병합 커밋으로 들어온 사실과 작업 1.3의 PR 상태(확인 날짜 또는 "미확인"), 8절 참조
  - 안내 문단: 절 번호를 `17486ed` 실제 번호(3.2·3.3·3.4·4·5·8·10·11·12절)로 고친다
  - 8·10.8·11.1·12.1절의 시점 기록은 고치지 않고 `review-notes.md`에 적는다
  - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 7.1, 7.2, 7.4, 7.5_

- [-] 4. `frontend/README.md` 머리말과 "상태"를 고친다
  - 3행 머리말의 "이번 단계 spec은 `.kiro/specs/frontend-stage1-setup/`이다"를 `.kiro/specs/frontend-stage*/`(1–6단계 `frontend-stage1-setup`–`frontend-stage6-ai-card`, 7단계 `frontend-stage7a-auth`)를 가리키는 문장으로 바꾼다(design.md 3.1)
  - "상태" 표 단계 행 앞에 "1–7단계 `main` 병합(`33aea80`, 2026-11-27)."을 더하고 나머지 문장은 유지한다. 연동 행은 내용을 유지하고 `dev` 코드 표기만 허용한다. 스타일 행은 글자 그대로 둔다(design.md 3.2)
  - `frontend/`에서 `npx prettier --write README.md`로 표 열 너비를 맞추고, 표 정렬 외 변경이 생기면 되돌린다
  - _Requirements: 1.6, 1.7, 4.1, 4.2, 4.3, 4.4, 4.5, 7.1, 7.4_

- [x] 5. `docs/02-architecture.md`의 LLM 공급자 설명을 고친다
  - design.md 4절 표의 행만 고친다: 11행 그림 안내, 21–22행 텍스트 도식, 37행 요청 경로, 46행 리전, 48행 모델 연결, 50행 의존성(`langchain-aws==1.10.0` 추가), 97행 `AiCardFunction`, 111·124·142행 로컬 LLM 표기, 143행 SSM, 186행 다음 `LLM_REGION` compose 줄, 223–225행 환경 변수 표와 새 `LLM_REGION` 행, 247행 §2.4.5, 497–501행 §2.8 IAM(`bedrock:InvokeModel` 추가, "네 가지"), 561·587행 `llm.py` 설명
  - 고치기 전에 근거 값을 `git show 17486ed:backend/template.yaml`, `git show 17486ed:backend/docker-compose.yml`, `git show 17486ed:backend/src/ai-requirements.in`으로 다시 확인한다
  - 로컬 실모델 경로는 호스트에서 `bedrock`(AWS 프로필, `scripts/eval_agent.py --env-file .env`, 합성 사연만)으로 적는다. 컨테이너 기본은 `fake`이고, 컨테이너 안의 `bedrock`은 401이라는 내용을 `docker-compose.yml` 63–64행 주석을 근거로 적는다. 컨테이너 실모델은 `openai_compat`으로 적는다. `.env` 공유 주의(design.md 4절)를 적고, 아직 정하지 않았다고 표시한다. 불일치 메모는 쓰지 않는다(출처 정리로 해결)
  - 다른 절과 LLM 공급자와 무관한 문장은 바꾸지 않는다
  - _Requirements: 1.3, 1.6, 1.7, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 7.1, 7.2, 7.4_

- [x] 6. `docs/04-ai-agent.md`의 LLM 공급자 설명을 고친다
  - design.md 5절 표의 행만 고친다: 5행 도입 배경 인용문("3.5절"을 "4.5절"로), 24행 "현재" 행을 2026-11-21 기록으로 바꾸고 새 "현재(2026-11-27)" 행 추가, 26행 "세 번째·네 번째 변경", 147행 모델 연결, 148행 공급자 교체(`LLM_PROVIDER`, `LLM_REGION` 규칙), 150행 API 키(IAM `bedrock:InvokeModel`, 키·SSM 없음), 153행 로컬 개발(`docker-compose.yml` 기본값 `fake`, 호스트 실모델 `bedrock`, 컨테이너 안 bedrock은 401), 155행 의존성(`==` 버전 6개, `langchain-aws==1.10.0` 포함), 157행 모델(BE-Q6 미결)
  - 151·166행과 4.2–4.4, 4.6–4.9절은 바꾸지 않는다
  - 의존성 값은 `git show 17486ed:backend/src/ai-requirements.in`으로 다시 확인한다
  - _Requirements: 1.3, 1.6, 1.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.3, 7.4_

- [ ] 7. 최종 검증
  - 각 검사는 `$T`=`README.md backend/README.md frontend/README.md docs/02-architecture.md docs/04-ai-agent.md`로 저장소 루트에서 돌린다. 명령과 출력, 눈으로 판정한 결과를 `review-notes.md`에 붙인다. 검사 스크립트는 커밋하지 않는다
  - [ ] 7.1 변경 범위 보존 검사
    - **Property 1: 변경 범위 보존**
    - `git diff --name-only 17486ed..HEAD`가 Target_Docs만 보이는지, `git diff -U0 17486ed..HEAD -- $T | grep '^@@'`의 `-a,b` 범위가 design.md Components 절의 지정 위치 안인지 확인한다
    - **Validates: Requirements 1.6**
  - [ ] 7.2 미병합 항목 표기 검사
    - **Property 2: 미병합 항목은 미병합으로만 적힘**
    - `git diff -U0 17486ed..HEAD -- $T | grep '^+' | grep -nE '7단계|/record|BE-Q46|Cognito'`의 각 줄이 "`main`에 없다/시작 전/승인 대기/남아 있다" 문맥인지 확인한다
    - **Validates: Requirements 1.4, 2.4, 3.5, 3.6**
  - [ ] 7.3 병합 뒤 미기록 결과 표기 검사
    - **Property 3: 병합 뒤 미기록 결과는 기록 시점과 함께 적힘**
    - `git show HEAD:backend/README.md | sed -n '/^## 1\./,/^## 2\./p' | grep -E '^\| (SAM|로컬|AWS 판정|다음 단계|PR)'`의 각 행에 브랜치·커밋 표기와 "병합 뒤 미확인"·"미실행"·"미확인" 중 하나가 있는지 확인한다
    - **Validates: Requirements 1.5, 3.11, 3.13, 3.14, 3.15**
  - [ ] 7.4 사실 값 일관성 검사
    - **Property 4: 사실 값 일관성**
    - `git diff -U0 17486ed..HEAD -- $T | grep '^+' | grep -nE '[0-9]{3,4}건|1505|1154|17486ed|bef1702|15건|LLM_PROVIDER|langchain-aws'`를 정본 값 표와 대조하고, `... | grep 1154 | grep -v 2b9af27`이 빈 출력인지 확인한다
    - **Validates: Requirements 1.3, 3.7, 3.8, 5.5, 5.11, 6.3, 6.7, 7.1**
  - [ ] 7.5 공급자 표기 통일 검사
    - **Property 5: 공급자 표기 통일**
    - `git diff -U0 17486ed..HEAD -- $T | grep '^+' | grep -nE 'OpenAI 호환|Bedrock|Fake'`의 각 줄에 해당 설정 값(`bedrock`, `openai_compat`, `fake`) 표기가 함께 있는지 확인한다
    - **Validates: Requirements 7.2, 2.1, 2.6, 3.12, 5.2, 6.6**
  - [x] 7.6 참조 유효성 검사
    - **Property 6: 참조 유효성**
    - 고친 줄의 상대 링크마다 `git cat-file -e 17486ed:<경로>`, 인용한 절 번호를 `git show 17486ed:<파일> | grep '^#'`과, spec 경로를 `git ls-tree -d 17486ed .kiro/specs/`와 대조한다. 루트 README "진행 현황"의 구현·검증·공급자 항목마다 하위 README 링크가 있는지 확인한다
    - **Validates: Requirements 7.3, 2.8, 3.3, 3.16, 4.5**
  - [x] 7.7 기존 기록 보존과 표 형식 검사
    - **Property 7: 기존 기록 보존과 표 형식**
    - `git show 17486ed:README.md | sed -n '102,104p'`의 각 줄을 `grep -Fx`로 결과 `README.md`에서 찾는다. frontend README 스타일 행이 그대로인지 확인한다. 고친 표 줄마다 `awk -F'|' '{print NF}'`를 머리 줄과 비교한다
    - **Validates: Requirements 2.10, 4.4, 7.4**
  - [x] 7.8 식별자 표기 보존 검사
    - **Property 8: 식별자 표기 보존**
    - `git diff -U0 17486ed..HEAD -- $T | grep '^+' | grep -oE '\b(BE|FE)-Q?[0-9A-Z-]+|\bT[0-9]+|\bG[0-9]\b|\bS[0-9]\b'`에 범위 밖 번호(`T23`, `G9`, `S6` 등)나 `docs/08-open-questions.md`에 없는 질문 번호가 없는지 확인한다
    - **Validates: Requirements 7.5, 1.8**
  - [~] 7.9 Prettier 형식 검사
    - `frontend/`에서 `npx prettier --check README.md`가 통과하는지 확인한다
    - _Requirements: 7.4_

- [~] 8. Checkpoint - 검증 결과 확인
  - Ensure all tests pass, ask the user if questions arise.
  - 작업 7의 검사가 모두 통과했는지, `review-notes.md`에 단위 테스트 결과·PR 상태·범위 밖 불일치가 정리됐는지 확인한다

## Notes

- 이 작업은 문서만 바꾼다. 코드, 설정, 테스트, `backend/.env.example`, Target_Docs의 지정되지 않은 절은 바꾸지 않는다(요구사항 1.6).
- 결과물이 문서라 PBT 라이브러리는 쓰지 않는다. 작업 7의 속성 검사는 design.md Correctness Properties의 결정적 셸 명령이다. 사용자 지시에 따라 선택(`*`) 표시 없이 필수로 둔다.
- 단위 테스트는 정본 건수를 얻기 위해 작업 1.2에서 한 번만 돈다. SAM·로컬 통합·AWS 회귀는 새로 실행하지 않고 마지막 기록과 "병합 뒤 미확인"으로 적는다(요구사항 1.5).
- 운영 공급자·모델(BE-Q6), 외부 전송 동의 문구(BE-Q7), `GET /claims/{claimId}/record`(BE-Q46)는 미결로만 적는다.
- 로컬 실모델 경로는 호스트 `bedrock`(`scripts/eval_agent.py --env-file .env`, 합성 사연만), 컨테이너 기본은 `fake`, 컨테이너 실모델은 `openai_compat`이다. `backend/.env.example` 29–37행과 `docker-compose.yml` 63–64행은 실행 위치가 다른 같은 내용이라 불일치 메모를 만들지 않는다. `.env`를 compose가 함께 읽는 문제(컨테이너도 bedrock이 됨)는 정하지 않았다.
- `review-notes.md`는 커밋하지 않는다. 내용은 PR 설명에 옮긴다.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2", "3", "4", "5", "6"] },
    { "id": 3, "tasks": ["7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "7.9"] },
    { "id": 4, "tasks": ["8"] }
  ]
}
```
