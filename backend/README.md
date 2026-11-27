# 이어온 하루 백엔드 — 인계 문서

AWS 계정 없이 개발한 백엔드를 AWS 담당이 배포·판정할 수 있도록 정리한 문서다. 역할 분담은 [docs/07 §7.8](../docs/07-development-plan.md), 명세는 [docs/](../docs/)와 spec(`.kiro/specs/`)이 기준이다.

## 0. 2026-11-27 최신 상태 (이 절이 1절 이하의 과거 기록보다 우선한다)

기준: `main` `17486ed`에서 갈라진 브랜치 `feat/be-7-completion`(push·PR·병합 없음). 1절 이하는 각 날짜·커밋 시점의 **과거 기록**이라 지우지 않고 남긴다. 아래가 현재 `main`과 어긋나는 항목이다.

| 과거 기록 | 현재 사실(Git 기준) |
|---|---|
| 1절 "브랜치" 행, 8절 PR #1–#8 "병합된 것은 없다" | `feat/be-1-2-foundation`·`feat/be-3-claim-transaction`·`feat/be-4-inbox`·`feat/be-5-photo-pipeline`·`feat/be-6a-ai-pipeline`·`feat/be-6b-ai-agent`·`feat/be-bedrock`·`fix/be-3-*`·`feat/fe-1…7`은 모두 `main`에 병합돼 있다(`git branch -r --merged main`) |
| "`GET /claims/{claimId}/record`는 `feat/be-4-record-inbox`의 `f3626c0`에만 있다" | `f3626c0`은 이 저장소에 없다. `feat/be-7-completion`의 `a8afb61`에 문서 기준으로 새로 구현했다. `main`에는 아직 없고 §3.4 503 계약은 승인 대기(BE-Q46) |
| 6a 로컬 `docker-compose.yml` 구동 기록 | 병합 뒤 `api` 서비스에 `FAULT_INJECT`가 두 번 들어가 compose가 파싱되지 않았다. `c17600c`에서 고쳤다(회귀 테스트 포함). 이 사이의 로컬 구동 기록은 병합 전 브랜치 기준이다 |

### 이번 작업(2026-11-27)의 완료 수준

| 항목 | 구현 | 단위 | 로컬 통합 | SAM 정적 | 남은 것 |
|---|---|---|---|---|---|
| `GET /claims/{claimId}/record`(스냅샷, 503 재시도 소진) | 완료 | 완료 | 완료(폴링 4건) | 통과 | **승인 대기**(BE-Q46 §3.4), AWS 판정(T1 확장·T2·스냅샷) |
| 웹 버킷 + CloudFront(OAC, SPA, CORS 연동) | 완료 | 완료 | 해당 없음 | 통과 | **AWS 배포·판정 대기** |
| 알람 5종 추가·대시보드·선택 Budgets | 완료 | 완료 | 해당 없음 | 통과 | 임계값·예산 **결정 대기**(BE-Q130·Q131), 배포 대기 |
| `scripts/seed.py`, `report.py`, `deploy_web.py`, `photo_orphans.py` | 완료 | 완료 | seed·report는 Floci 확인 | — | `demo` 스택 실행 |
| 마스킹 스위치 `AI_MASK_BEFORE_SEND`(기본 꺼짐) | 완료 | 완료 | — | 통과 | **BE-Q10 결정 대기** |
| 사진 `UploadIfNoneMatch` | 기존 구현(스위치) | 기존 | 켠 상태 로컬 확인 | 통과 | **승인 대기**(BE-Q65), 프론트 재업로드 |

검증 기록(2026-11-27, 개발 PC, 실제 AWS·유료 API 없음): `pytest tests/unit`·`pytest -m local tests/local`(Floci + Fake LLM, 에이전트 모드·`UploadIfNoneMatch`·`photo-slow`·`photo` 장애 조건 포함)·`pytest -m integration --collect-only`(수집만)·`cfn-lint`·`sam validate --lint`·`sam build --use-container`·`scripts/check_ai_build.py`(linux/amd64)·프론트 `tsc`·`vitest`·`eslint`·`vite build`(node:22 컨테이너)·실제 브라우저로 로컬 프론트(dev-jwt)↔로컬 백엔드 글로 완료 흐름. 건수와 실행하지 못한 항목은 최종 보고와 인계 문서에 있다. 인계 절차는 [`.kiro/specs/backend-stage7-ops/aws-handoff.md`](../.kiro/specs/backend-stage7-ops/aws-handoff.md).

로컬 한계: 브라우저에서 Floci Cognito(`localhost:4566`)는 CORS로 막혀 로컬 프론트는 `VITE_AUTH_MODE=dev-jwt`를 쓴다(시드는 `python scripts/seed.py --local --apply --users fixed`로 `dev-jiyeon` 등 프론트 인물과 맞춘다).

### 서비스 정체성 일반화에 따른 문구·데이터 변경(2026-11-27, docs/08 BE-Q135–BE-Q138)

'이어온 하루'는 산책 전용이 아니라 실현하지 못한 일상 계획을 다른 사람에게 양도하고 그 경험을 돌려받는 서비스다. 산책은 대표 사례다. 이 README 아래 절의 산책 서술(데모 사연, 이사 전 마지막 동네 산책)은 대표 사례의 기록이며 서비스 범위를 뜻하지 않는다.

| 대상 | 내용 |
|---|---|
| 시드(`scripts/seed.py`) | 기존 데모 사례에 더해 다양한 일상 활동 사례가 들어간다. 이사 전 마지막 동네 산책, 골목 카페(완료된 사례), 일정 변경으로 가지 못한 전시회, 추억이 담긴 서점 방문, 공원 사진·휴식의 다섯 사례는 반드시 있다(카페는 OPEN이 아니라 DONE_REPLIED 사례다). 세부 제목·개수는 시드 파일 참조 |
| 비공개 장소 질문 문구 | 선택지 `장소에서 빼기`, 서버 메모 `비공개 장소라 뺐어요.`(BE-Q136). 아래 절의 `동선에서 빼기` 표기는 변경 전 값의 기록이다 |
| AI 프롬프트·Fake LLM·평가 픽스처 | 활동 유형(산책, 카페, 전시회, 서점, 공원)에 치우치지 않는 일반 정책, 비산책 사연 추가(docs/04). 아래 절의 측정 수치는 변경 전 프롬프트로 잰 값이라 새로 잰 것이 아니다. 프롬프트 해시는 `day_card.md` `ca6ada9ac3ef` → `c4fc8de1db3d`, `day_card_agent.md` `3db437c63971` → `d1c20c140400`으로 바뀌었고, 위 절들의 해시와 측정값은 이전 프롬프트의 기록이다 |
| 변경하지 않는 것 | API 스키마, 카테고리 필드·테이블, `areaId` 예약 필드, 지도·결제·예약 등(범위 밖) |

## 1. 인계 상태 요약

| 항목 | 상태 |
|---|---|
| 기준·브랜치 | 기준 브랜치 `main`, 기준 커밋 `17486ed`(2026-11-27). 병합 커밋: 4단계 `8f4c288`(`feat/be-4-inbox`), 5단계 `17486ed`(`feat/be-5-photo-pipeline`), Bedrock 전환 `bef1702`(전환 커밋 `2b9af27`, `feat/be-bedrock`), 프론트엔드 1–6단계와 7단계 인증 코드까지 `33aea80`. 1–3단계, 6a단계, 6b단계는 병합 커밋 없이 `main` 이력에 들어 있다 |
| 범위(1·2단계) | 인증, `GET /me`, 계획 생성·목록·상세, 멱등 키, 원문 충실도·개인정보 함수 |
| 범위(3단계) | 이어받기·포기·완료 트랜잭션, 방문 기록 글 저장 최소 구현, `GET /me/claims`, EMF 지표 3종 |
| 범위(4단계) | 수신함 4종(`GET /inbox`, `GET /inbox/{itemId}`, 읽음, 답장), `GET /me`의 `unreadInboxCount`, `InboxFunction`. 판정 실행표는 3.3절 |
| 범위(5단계) | 사진 업로드 URL·교체, 사진 처리 Lambda·`PhotoQueue`·DLQ, 수신함 `photoUrl`·`photoCaption`, 운영자 복구 스크립트. 상세는 12절 |
| 범위(6a단계, AI 레벨 0) | `/ai/card-sessions*` 세 경로, `POST /plans`의 AI 세션 지표, `AiCardFunction`. 상세는 10절 |
| 범위(6b단계, AI 에이전트) | `AGENT_MODE=agent`의 LangGraph 에이전트, 턴 잠금, 질문 `interrupt`·`Command(resume)`, 체크포인트 테이블 `HaruAgentCheckpoints`. 기본 모드는 `pipeline`. 2026-11-27 개발 PC에서 GPT-6 Luna 게이트웨이(`openai_compat`)로 전 단계를 실행했다. 개발용 실측이고 AWS 판정이 아니다. 상세는 11절, 실측 기록은 10.11·11.12절 |
| 범위(Bedrock 전환) | 2026-11-27 `2b9af27`. `LLM_PROVIDER=bedrock`이 기본이고 `ChatBedrockConverse`를 쓴다. 인증은 IAM `bedrock:InvokeModel`이며 API 키와 SSM 파라미터를 쓰지 않는다. `LLM_REGION`은 빈 값이면 `AWS_REGION`을 쓴다. 별도 spec은 없다 |
| `main`에 없는 것 | `GET /claims/{claimId}/record`: 계약 변경 승인 대기(BE-Q46, 8절). 백엔드 7단계(웹 배포·관측·시연 준비): `main`에 없고 spec도 아직 없다 |
| spec | `.kiro/specs/backend-stage1-2-foundation/`, `.kiro/specs/backend-stage3-claim/`, `.kiro/specs/backend-stage4-record-inbox/`, `.kiro/specs/backend-stage5-photo-pipeline/`, `.kiro/specs/backend-stage6a-ai-pipeline/`, `.kiro/specs/backend-stage6b-ai-agent/` |
| 단위 테스트 | `pytest tests/unit` **1505건 통과, 1건 skip, 2건 deselect**(2026-11-27, `17486ed`). skip 1건은 리눅스 전용 `/proc/self/fd` 검사(`tests/unit/test_ai_cancel.py`, macOS에서 skip된다). deselect 2건은 `slow` 표시 40MP 메모리 측정이며 `pytest -m slow tests/unit`로 따로 돈다. 병합 전 기록 1154건은 Bedrock 전환 커밋 `2b9af27`(4·5단계 병합 전) 기준 값이고 병합 뒤 건수가 아니다. 단계 브랜치 시점 건수(10.1·11.1·12.1절)는 그 브랜치 기준이라 이 값과 직접 비교하지 않는다 |
| SAM | 1–3단계: `cfn-lint` 0건, `sam validate --lint`, `sam build` 성공. 2026-11-25 `haru-dev` 배포(3.1절). 4단계: `sam validate --lint`·`sam build` 확인(2026-11-25, 브랜치 미기록), 배포 안 함. 5단계: `cfn-lint` 0건, `sam validate --lint`, `sam build --use-container` 성공(Pillow 레이어, 12.1·12.2절), 배포 안 함. 6a·6b단계: `cfn-lint` 0건, `sam validate --lint`, `sam build --use-container` 성공(10.1·11.1절), 배포 안 함. Bedrock 전환: `cfn-lint` 통과(`2b9af27` 커밋 메시지). 병합 뒤 `17486ed` 템플릿의 검사·빌드 기록은 없다(병합 뒤 미확인) |
| 로컬 환경(Docker) | 1–3단계 `pytest -m local tests/local` 16건 통과(2026-11-25, 5.1절). 4단계 23건 통과(5.4절, 기록 기준 브랜치 `feat/be-4-record-inbox`, 커밋 전 작업 트리). 5단계 28건 통과·8건 사유 skip(5.5절, `feat/be-5-photo-pipeline` `cfc65a7`). 6a 기존 16건과 새 7건 통과(10.1절). 6b 기본 `pipeline`에서 기존 23건, `agent` 모드에서 새 9건 통과(11.1절). 모두 `llmMode: fake`이고 판정 근거가 아니다(BE-Q15). 병합 뒤 `17486ed`에서 로컬 통합 테스트를 다시 돌린 기록은 없다(병합 뒤 미확인) |
| AWS 판정(1–3단계) | T1·T13·T3·T4·T5·T6·T7·T14·T16과 가입 확인(1.5·14.4) **15건 모두 통과**(2026-11-25, `haru-dev`, AWS 담당). 첫 실행에서 T1 액세스 토큰 1건이 실패해 `common/auth.py`를 고친 뒤 다시 통과했다(3.1절). 기록 브랜치 `fix/be-3-aws-verify`(`e80b890`). **2026-11-27 새 계정에서 `17486ed`로 회귀 통과**(T3·T4·T5·T14·T6·T7·T16·T13·가입, 3.5절) |
| AWS 계정 | **2026-11-27 새 계정으로 옮겼다.** 이전 계정의 `haru-dev`와 SAM 관리 스택·버킷, SSM 키, 로그 그룹은 지웠다. 3.1절의 출력값은 이전 계정 값이라 더 쓰지 않는다. 현재 출력값과 배포 파라미터는 3.5절 |
| AWS 판정(4·5단계) | **2026-11-27 새 계정 `haru-dev`(`17486ed`)에서 실행(3.5절)**. 4단계 T1 확장·T2·T17 통과. 5단계 T8·T11·재업로드·주입 차단 통과, T10·T15는 기본 배포에서 미검증이었고 `FaultInject=photo-slow` 지연 판정(`test_T10_T15_with_delay`)으로 통과. IAM·CORS 1건 실패(테스트가 만든 만료 URL이 307, 3.5절). T9는 3.5절 |
| AWS 판정(6a·6b·Bedrock) | 6a: `tests/integration/test_ai.py`를 `feat/be-6a-ai-pipeline` `7d518ed`에서 작성·수집만 했고 미실행(10.1·10.3절). 6b: T18–T22를 `feat/be-6b-ai-agent` `82275e7`에서 작성·수집만 했고 미실행(11.1·11.4절). `bedrock` 경로: `feat/be-bedrock` `2b9af27`은 AWS 통합 테스트를 바꾸지 않았고(단위 테스트 `test_ai_bedrock.py`와 `test_template.py`만) 배포·판정은 미실행. 모두 AWS 배포 전이다. **2026-11-27 새 계정**: `LlmProvider=bedrock`, `LlmModel=global.anthropic.claude-haiku-5-5`로 배포했다. `AgentMode=agent`에서 T20 통과. T18·T19·T22는 테스트가 `bedrock`을 실제 공급자로 보지 않아 skip됐고(테스트 수정 뒤 재판정), T21·T12는 3.5절 |
| LLM 공급자 | 기본 `bedrock`(Amazon Bedrock Converse). `openai_compat`(AWS는 SSM SecureString 키, 로컬은 `.env`의 `LLM_API_KEY`)과 `fake`(AWS는 `Stage=dev`이고 스택 `haru-dev`일 때만, 로컬 `docker-compose.yml` 기본값)는 선택 경로로 유지한다. 운영 공급자·모델은 미결(BE-Q6)이다. 개발·검증용으로는 GPT-6 Luna 게이트웨이를 썼다(10.11절). 배포 전 확인은 10.2절 |
| 다음 단계 조건 | T3–T7이 AWS에서 통과해야 4단계를 시작한다(docs/07 §7.2). **2026-11-25 충족**. 4단계 이후 PR마다 `tests/integration/test_concurrency.py`를 다시 돌린다(docs/07 §7.2). 4·5단계 병합(`8f4c288`, `17486ed`) 뒤 AWS 통합 회귀(`test_concurrency.py` 재실행, 10.8절 작업 22)는 **2026-11-27 새 계정에서 `17486ed`로 통과**했다(3.5절). 7단계 병합(`06e95d2`) 뒤에는 아직 다시 돌리지 않았다 |
| PR | GitHub PR 상태(`gh pr list`, 2026-11-27 확인): #2 MERGED(`docs/monorepo-stage1-2-spec`), #1·#3–#8 CLOSED. #1·#3–#8은 GitHub에서 CLOSED(병합 없이 닫힘) 상태다. 이 브랜치들의 내용은 `main`의 병합 커밋이나 이력으로 들어왔다: 4단계 `8f4c288`, 5단계 `17486ed`, Bedrock 전환 `bef1702`, 프론트엔드 `33aea80`. 1–3단계와 6a·6b단계는 병합 커밋 없이 이력에 있고, 6b단계 브랜치의 PR은 #1–#8 목록에 없다. 2026-11-26 기준 열림 상태는 8절에 있다 |

AWS에서만 확인되는 것은 4절, 로컬 환경 구동 기록과 절차는 5절, 테스트 데이터 정리 보완은 3.2절, 4·5단계 판정 실행표는 3.3·3.4절, 6a는 10절, 6b는 11절, 5단계는 12절, PR 순서는 8절에 있다. 8·10.8·11.1·12.1절은 각 작업 시점의 기록이라 이 표와 다를 수 있다.

## 2. 배포 런북 (AWS 담당)

### 2.1 준비

- 리전: `ap-northeast-2`
- 도구: AWS CLI v2, AWS SAM CLI(1.174.0에서 확인), Python 3.12. Windows에서 `sam build`는 PATH의 `python`이 3.12여야 한다(가상 환경을 켜거나 `--use-container`).
- Windows에서는 SAM 명령 전에 `set PYTHONUTF8=1`(PowerShell은 `$env:PYTHONUTF8 = "1"`)을 한다. 안 하면 SAM이 `samconfig.toml`의 한글 주석을 cp1252로 읽다가 `UnicodeDecodeError`로 멈춘다(2026-11-25 확인).
- `aws login`으로 받은 자격 증명으로 통합 테스트(boto3)를 돌리려면 `botocore[crt]`가 필요하다. `requirements-dev.txt`에 포함했다. 없으면 `MissingDependencyException`으로 모든 테스트가 시작 전에 멈춘다.
- **배포 전에 AWS Budgets 월 알림을 먼저 건다**(BE-Q11, 금액은 팀이 정한다).
- 배포하는 IAM 주체에 필요한 권한: CloudFormation, IAM 역할 생성·연결(`CAPABILITY_IAM`), Lambda, API Gateway(HTTP API), Cognito User Pool, DynamoDB, S3(SAM 아티팩트 버킷, `resolve_s3`가 `aws-sam-cli-managed-default` 스택을 만든다), CloudWatch Logs.
- 통합 테스트를 돌리는 주체에 필요한 권한: `cloudformation:DescribeStacks`, `cloudformation:DescribeStackResource`, `cognito-idp:AdminCreateUser`, `AdminSetUserPassword`, `AdminDeleteUser`, `dynamodb:GetItem`, `dynamodb:Query`, `dynamodb:UpdateItem`(T14의 `dueAt` 변경), `dynamodb:DeleteItem`(정리, 대상 테이블만).
- 5단계에서 더 필요한 권한(테스트 실행 주체): 사진 버킷 `s3:ListBucket`(Claim prefix 조회), `s3:GetObject`·`s3:PutObject`(만료 URL 서명용)·`s3:DeleteObject`(정리, `photos/*`), `cloudformation:GetTemplate`(주입 차단 확인), `lambda:GetFunctionConfiguration`(처리 함수 환경 변수 확인), PhotoDLQ `sqs:ReceiveMessage`·`sqs:DeleteMessage`(T9, 테스트 메시지만), `cloudwatch:DescribeAlarms`(T9).
- 배포 주체에는 S3 버킷·버킷 정책, SQS 큐·큐 정책, Lambda 레이어·이벤트 소스 매핑, CloudWatch 알람 생성 권한이 더 필요하다.

### 2.2 배포

```powershell
cd backend
python -m venv .venv; .venv\Scripts\activate          # 처음 한 번
pip install -r requirements-dev.txt
pytest tests/unit                                      # 배포 전 확인
sam validate --lint
sam build
sam deploy --config-env dev                            # 변경 세트를 보여 주고 확인을 받는다
```

- 스택 이름: `haru-dev`(`demo`는 `haru-demo`). 설정은 `samconfig.toml`. 계정 ID는 저장소에 넣지 않았다.
- 배포 후 출력값을 확인한다: `ApiUrl`, `UserPoolId`, `UserPoolClientId`(요구사항 12.3). 프론트 연동(S1)에 이 세 값을 전달한다.
- 정리: `sam delete --stack-name haru-dev`. DynamoDB 테이블과 Cognito 사용자도 함께 지워진다.

## 3. 판정 실행표

| T | 내용 | 파일 | 판정 |
|---|---|---|---|
| T1 | 토큰 없음·잘못된 토큰으로 모든 경로 → 401, 액세스 토큰 → 401 | `tests/integration/test_authz.py` | 상태 코드 401만 본다(본문 형식은 4절 1항) |
| T13 | 같은 키·같은 본문 3회 → Plan 1건, 다른 본문 → 409, 같은 키 동시 10회 → Plan 1건 | `tests/integration/test_idempotency.py` | |
| (1.5, 14.4) | 가입 직후 인증 코드 없이 로그인, ID 토큰 `nickname` 확인. `nickname` 없는 가입 거부 | `tests/integration/test_idempotency.py` | |
| T3 | 서로 다른 10명이 같은 계획을 동시에 이어받기 → 201 정확히 1건, 나머지 409 `ALREADY_CLAIMED`, `currentClaimId`는 승자 | `tests/integration/test_concurrency.py` | 결과 로그 `T3-concurrent-claims-*.json` 보관 |
| T4 | 같은 사용자가 5회 동시 → Claim 1건, 모두 같은 `claimId`(201/200) | 〃 | |
| T5 | 완료 10회 동시 → 모두 200, InboxItem 1건, Record 전달 1건 | 〃 | 결과 로그 `T5-concurrent-complete-*.json` 보관. 건수는 DynamoDB 직접 조회(BE-Q38) |
| T14 | 기한 지난 이어받기를 다른 사람이 대체 → 201, 이전 Claim `EXPIRED`, 이전 실행자의 늦은 쓰기 409 | 〃 | `dueAt`을 과거로 직접 바꾼다(BE-Q38) |
| T6 | 포기 후 이전 `claimId`로 기록·완료 → 409 `CLAIM_NOT_ACTIVE`, 수신함 없음 | `tests/integration/test_claim_lifecycle.py` | |
| T7 | 포기 → 다른 사용자 이어받기 → 첫 실행자의 늦은 완료 409, 두 번째 완료 정상 | 〃 | |
| T16 | 포기 후 둘러보기 목록에 다시 노출 | 〃 | GSI1 최종 일관성 때문에 최대 10초 다시 본다 |

T3·T4·T5에서 409·200 대신 503 `TRY_AGAIN`이 나오면 실패로 본다. 코드는 `TransactionConflict` 재시도를 다 쓴 뒤에도 다시 읽어 판정하므로(spec 3단계 요구사항 1.10·4.6) 503은 다시 읽어도 판정할 수 없을 때만 나와야 한다. 503이 보이면 CloudWatch Logs와 결과 로그를 함께 보관하고 개발 담당에게 넘긴다.

실행:

```powershell
$env:STACK_NAME = "haru-dev"
$env:AWS_REGION = "ap-northeast-2"
pytest -m integration tests/integration -v
```

- 테스트가 만든 Cognito 사용자, Plan·멱등 키·수신함 항목은 끝나면 지운다. 정리에 실패하면 `test-results/cleanup-failures-*.json`이 생기고 pytest 결과에 teardown `error`가 1건 보인다(3.2절).
- 근거 로그는 `test-results/T1-authz-*.json`, `T13-*.json`에 남는다. 판정 결과와 함께 보관한다.
- `STACK_NAME`이 없으면 모두 건너뛴다.

### 3.1 판정 기록 (2026-11-25, AWS 담당)

> 이전 AWS 계정의 기록이다. 그 계정의 `haru-dev`는 2026-11-27 지웠고, 아래 출력값은 더 이상 동작하지 않는다. 새 계정의 기록은 3.5절.

배포

| 항목 | 값 |
|---|---|
| 스택 | `haru-dev` (`ap-northeast-2`), 최초 `CREATE_COMPLETE`, `auth.py` 수정 후 `UPDATE_COMPLETE` |
| 배포 주체 | IAM 사용자(루트 아님), MFA·Budgets 알림 설정 후 배포 |
| 배포 전 확인 | `pytest tests/unit` 284건 통과(수정 후 289건), `sam validate --lint` 통과, `sam build` 성공(Python 3.12.10, 컨테이너 없이) |
| 출력값 | `ApiUrl` `https://xgf0k60pq5.execute-api.ap-northeast-2.amazonaws.com`, `UserPoolId` `ap-northeast-2_g4A20WiPl`, `UserPoolClientId` `4pivcij1q8rt270t0h8rq9h2cs` (비밀 아님. 스택을 지우고 다시 만들면 바뀐다) |

판정 결과 (`pytest -m integration tests/integration`)

| T | 결과 | 근거 |
|---|---|---|
| T1 | 통과 (3건) | 첫 실행에서 `test_access_token_is_rejected`가 200으로 실패. 수정 후 재실행 통과. `test-results/T1-authz-*.json` |
| T13 | 통과 (3건) | `T13-sequential-*.json`, `T13-concurrent-*.json` |
| 가입 (1.5, 14.4) | 통과 (2건) | |
| T3 | 통과. 201 1건, 409 `ALREADY_CLAIMED` 9건 | `T3-concurrent-claims-*.json` |
| T4 | 통과. Claim 1건 | `T4-same-user-*.json` |
| T5 | 통과. 200 10건, InboxItem 1건 | `T5-concurrent-complete-*.json` |
| T6·T7·T14·T16 | 통과 | |

T3·T4·T5에서 503 `TRY_AGAIN`은 나오지 않았다.

판정 중 고친 것

- **액세스 토큰이 API를 통과했다.** HTTP API JWT authorizer는 `aud`가 없으면 `client_id`를 audience와 비교하므로 Cognito 액세스 토큰도 통과시킨다. `common/auth.py`의 `get_user()`가 `token_use == "id"`가 아니면 401 `UNAUTHORIZED`를 내도록 고쳤다(로컬 어댑터는 이미 같은 검사를 한다). 단위 테스트 `test_auth.py`에 5건을 추가하고, 핸들러 테스트의 이벤트 헬퍼가 `token_use: "id"`를 넣게 했다.

남은 일

- 테스트 정리 후에도 Cognito 사용자 15명과 `HaruTable` 항목 30개(멱등 키 `IDEM#` 14, Plan 4, Claim 4, ClaimLookup 4, Record 3, InboxItem 1)가 남았다. `_cleanup`은 `IDEM#{sub}#…` 파티션을 지우지 않는다. 사용자가 남은 원인은 확인하지 않았다(`_cleanup`이 삭제 예외를 무시하므로 로그가 없다). 정리 코드 보완이 필요하다(개발 담당).
  - **보완(2026-11-25, 개발 담당, `fix/be-3-local-verify`)**: 3.2절. AWS에서 다시 실행하지 않았다. 남아 있는 항목은 지우지 않았다(아래 3.2절 "남은 데이터").
- 결과 로그(`test-results/`)는 이 PC에만 있다. 저장소에 넣을지, 따로 보관할지 팀이 정한다. 2026-11-26부터 `backend/.gitignore`에 `test-results/`를 넣어 실수로 커밋되지 않게 했다(기존 기록은 AWS 담당 PC에 그대로 있고 지우지 않았다). 저장소에 넣기로 하면 `git add -f`로 명시적으로 넣는다. 테스트는 `backend/`에서 실행한다(`RESULTS_DIR`는 실행 위치 기준 상대 경로).

### 3.2 테스트 데이터 정리(`_cleanup`) 보완

원인

| 남은 것 | 원인 | 확인 수준 |
|---|---|---|
| `IDEM#` 14건 | 멱등 키 항목의 PK는 `IDEM#{sub}#{key}`로 키마다 파티션이 따로다(`src/domain/plan_service.py`). `_cleanup`은 `USER#{sub}` 파티션만 조회했고 쓴 키를 기록하지 않아 한 건도 지우지 못했다 | 코드로 확인. 이전 코드로 같은 상황을 재현했다 |
| Cognito 사용자 15명 | `admin_delete_user` 예외를 모두 삼켰다. 직접 원인(스로틀 `TooManyRequestsException`, 자격 증명 만료 등)은 기록이 없다 | 미확인. CloudTrail 이벤트 기록에서 `AdminDeleteUser`의 `errorCode`로 확인할 수 있다(읽기 전용) |
| Plan·Claim·ClaimLookup·Record·InboxItem | DynamoDB 삭제는 예외 하나에 나머지 정리(남은 Plan, 모든 `USER#` 파티션)가 멈췄다. 실행이 teardown 전에 끊긴 경우도 남는다 | 미확인 |

바뀐 것(`tests/integration/conftest.py`, 제품 코드 변경 없음)

- `create_plan`과 T13 테스트는 요청 **전에** 멱등 키를 `Stack.created_idem_pks`에 등록하고(`register_idem_key`), 정리 때 `IDEM#{sub}#{key}`/`META`를 지운다.
- 대상마다 따로 시도한다. 실패는 삼키지 않고 `test-results/cleanup-failures-*.json`(종류, 대상, 오류 코드)에 남긴 뒤 세션 teardown에서 `RuntimeError`로 알린다. pytest 결과에 `error`로 보이며, 개별 T 판정(passed/failed)과는 별개다.
- `UserNotFoundException`은 이미 정리된 것으로 본다. 정리 클라이언트는 adaptive 재시도 10회로 스로틀을 흡수한다.
- 파티션 조회는 `ConsistentRead`와 페이지 이어 읽기.
- 회귀 테스트: `tests/unit/test_integration_cleanup.py`(moto DynamoDB와 가짜 Cognito 클라이언트, AWS 접속 없음).
- 테스트 실행 주체의 권한은 2.1절 그대로다(`dynamodb:DeleteItem`, `dynamodb:Query`, `cognito-idp:AdminDeleteUser`).

남은 데이터(2026-11-25 판정분): 이번 작업에서 지우지 않았다. 테이블 스캔이나 일괄 삭제는 이 코드에 넣지 않았다. 지우려면 AWS 담당이 대상(테스트 이메일 `it-*@example.com` 사용자, 해당 항목)을 확인한 뒤 수동으로 지운다. `IDEM#` 항목은 TTL(24시간)로도 사라진다.

### 3.3 4단계 판정 실행표 (미실행)

배포 후 3절과 같은 명령(`pytest -m integration tests/integration -v`)으로 함께 돈다. 아래는 4단계에서 더한 것이다.

| T | 내용 | 파일 | 판정 |
|---|---|---|---|
| T1(확장) | `ROUTES`를 도는 401 테스트에 수신함 경로 4개가 자동으로 들어간다. 액세스 토큰 테스트는 `GET /me`, `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply` 모두 401 `UNAUTHORIZED`(계약 형식) | `tests/integration/test_authz.py` | `T1-authz-*.json`, `T1-access-token-*.json` |
| T2 | 역할별 권한. 아래 표 | `tests/integration/test_authz.py::test_T2_role_based_access` | `T2-role-access-*.json`(칸별 상태와 판정) |
| T17 | 첫 답장 201, 두 번째 409 `REPLY_ALREADY_SENT`. 10스레드 동시 답장에서 201 정확히 1건, 나머지 409, 저장된 답장은 201 응답 값 | `tests/integration/test_inbox.py` | `T17-reply-twice-*.json`, `T17-concurrent-replies-*.json` |
| 회귀 | T3·T4·T5·T14(`test_concurrency.py`), T6·T7·T16을 함께 다시 돈다 | | docs/07 §7.2 |

T2 역할별 기대 결과(requirements Requirement 11.3). Planner(A)가 계획을 만들고 Claimer(C)가 이어받는다. Third_Party(B)는 둘 다 아니다.

| 경로 | A | C | B |
|---|---|---|---|
| `GET /claims/{claimId}/record` | 403 | 200 | 403 |
| `PUT /claims/{claimId}/record` | 403 | 200 | 403 |
| `POST /claims/{claimId}/abandon` | 403 | 200(별도 Claim) | 403 |
| `POST /claims/{claimId}/complete` | 403 | 200 | 403 |
| `GET /inbox` | 200, 해당 항목 포함 | 200, A의 항목 없음 | 200, A의 항목 없음 |
| `GET /inbox/{itemId}` | 200 | 404 | 404 |
| `POST /inbox/{itemId}/read` | 204 | 404 | 404 |
| `POST /inbox/{itemId}/reply` | 201 | 404 | 404 |
| `GET /me` | A의 미확인 항목을 셈 | 세지 않음 | 세지 않음 |

- 없는 `claimId`·`itemId`는 모든 역할에서 404다. 403·404 본문은 에러 형식만 담고 글·답장·Plan 제목이 없어야 한다. 403·404 뒤 Claim·Record·InboxItem이 바뀌지 않았는지 DynamoDB `ConsistentRead`로 확인한다(BE-Q38).
- `GET /claims/{claimId}/record` 행은 BE-Q46 묶음 테스트에서 확인한다. 그 묶음이 들어가기 전에는 이 행을 판정하지 않는다.
- 4단계 테스트도 사용자는 `create_user`, 계획은 `create_plan`으로 만들어 `_cleanup`이 지운다(3.2절). `_cleanup`은 바꾸지 않았다.
- 2026-11-25 개발 담당이 T2·T17 테스트 함수를 로컬 환경(`call`·`get_item`을 로컬 어댑터·Floci로 바꿔 끼움)에서 한 번 돌려 통과를 확인했다. 테스트 코드 점검용이며 판정 근거가 아니다(BE-Q15).

### 3.4 5단계 판정 실행표 (미실행)

5단계 테스트는 `tests/integration/test_photo.py`에 있다. 사진 Claim은 업로드 전에 정리 대상으로 등록되고, `_cleanup`은 DynamoDB를 지운 **뒤** 그 Claim의 `photos/original/{claimId}/`·`photos/processed/{claimId}/`만 지운다. 늦게 온 처리 Lambda가 만든 객체를 위해 30초 뒤 한 번 더 지우고 그때 지운 키를 `cleanup-late-objects-*.json`에 남긴다. 각 사진 테스트는 끝나기 전에 `wait_photo_settled`로 Record가 끝난 상태(전달·`FAILED`·`DISCARDED`)에서 30초 동안 바뀌지 않는지 확인한다(최대 5분, 안 되면 `cleanup_after_unsettled-*.json`). 버킷 전체 삭제·큐 purge는 하지 않는다.

| T | 내용 | 테스트 | 배포 | 근거 로그 |
|---|---|---|---|---|
| T8 | 잘린 JPEG → `FAILED CORRUPT_IMAGE`, 글 유지, `TEXT_ONLY` 200, InboxItem `hasPhoto = false`, 처리본 0개 | `test_T8_corrupt_image` | 기본 | `T8-corrupt-image-*.json` |
| T11 | GPS EXIF JPEG → 완료 → 계획자 `photoUrl`로 받은 처리본에 EXIF·GPS·XMP·ICC 없음 | `test_T11_gps_stripped` | 기본 | `T11-gps-stripped-*.json`(검사 도구 이름 포함. `exiftool`이 PATH에 있으면 쓰고 없으면 Pillow) |
| T10 | `PROCESSING` 관측 → 즉시 `TEXT_ONLY` 완료 → `hasPhoto = false`, `DISCARDED`, 처리본 0개 | `test_T10_text_only_during_processing` | 기본(관측 시도) | `T10-text-only-during-processing-*.json` |
| T15 | 빨간 사진 `PROCESSING` 관측 → 파란 사진으로 교체 → 수신함 사진이 파란색(평균 색), 처리본 1개 | `test_T15_replace_during_processing` | 기본(관측 시도) | `T15-replace-during-processing-*.json` |
| T10·T15 | 위 둘을 지연 주입 아래에서 실행. **최종 판정 근거** | `test_T10_T15_with_delay`(`fault`) | `FaultInject=photo-slow` | `T10-T15-with-delay-*.json` |
| T9 | 처리마다 예외 → 3번째 수신에 `FAILED RETRY_EXHAUSTED`(최대 10분) → DLQ에 그 Claim의 메시지 → `PhotoDLQNotEmpty` `ALARM`(최대 5분) → 그 메시지만 삭제 | `test_T9_dlq`(`fault`) | `FaultInject=photo` | `T9-dlq-*.json` |
| 재업로드 | 같은 presigned URL로 두 번 PUT. 스위치 꺼짐: 둘 다 200, 전달 1회, 처리본 1개. 켜짐: 두 번째 412 | `test_photo_reupload` | 기본 | `photo-reupload-*.json` |
| IAM·CORS | presigned PUT·GET 권한, `Origin: http://localhost:5173` preflight, 잘못된 `Content-Length`·만료 URL의 403과 그 응답의 `Access-Control-Allow-Origin`·S3 오류 코드 | `test_photo_iam_and_cors` | 기본 | `photo-iam-and-cors-*.json`(오류 응답 CORS 헤더는 판정이 아니라 기록. 프론트 403 처리의 근거) |
| 주입 차단 | 처리 함수 이름이 스택 이름으로 시작, 처리된 템플릿에 `FaultAllowed`(실제 스택 이름 조건), `haru-dev`가 아닌 스택이면 `FAULT_INJECT = ""`·`FAULT_INJECT_ALLOWED = "false"`(읽기 전용) | `test_photo_fault_blocked` | 기본 | `photo-fault-blocked-*.json` |
| 회귀 | T3·T4·T5·T14(`test_concurrency.py`), T6·T7·T16, 4단계 T1·T2·T17 | 기존 | 기본 | docs/07 §7.2 |

**T10·T15 미검증 규칙**: `PROCESSING`을 관측하지 못했거나, 관측했어도 경쟁 요청이 사진 전달 뒤에 도착했으면(`TEXT_ONLY` 응답 `hasPhoto: true`, 교체 409) 결과 파일에 `"verdict": "unverified"`와 관측한 상태 열·사유(`processing_not_observed`/`race_lost`)를 남기고 사유 있는 skip으로 끝난다. **skip은 통과가 아니다.** 판정표에는 불합격과 같이 "재시험 필요"로 적고, 지연 주입 배포의 `test_T10_T15_with_delay` 결과로 판정한다. 단위 테스트의 순차 재현으로 판정을 대신하지 않는다.

실행 순서(판정 순서: 4단계 → 5단계 기본 → 회귀 → 주입 → 복원 확인)

```bash
export STACK_NAME=haru-dev AWS_REGION=ap-northeast-2
sam build --use-container && sam deploy --config-env dev               # 기본 배포
pytest -m "integration and not fault" tests/integration -v              # 4단계·5단계 기본·회귀

# 지연 주입(dev만). --parameter-overrides는 samconfig 값을 대신하므로 모든 값을 다시 적는다
sam deploy --config-env dev --parameter-overrides "AllowedOrigins=http://localhost:5173 Stage=dev FaultInject=photo-slow"
pytest -m "integration and fault" tests/integration -v -k with_delay
sam deploy --config-env dev --parameter-overrides "AllowedOrigins=http://localhost:5173 Stage=dev FaultInject=photo"
pytest -m "integration and fault" tests/integration -v -k T9

sam deploy --config-env dev                                             # 복원(FaultInject 빈 값)
pytest -m "integration and not fault" tests/integration/test_photo.py -v -k fault_blocked
aws lambda get-function-configuration --function-name <PhotoProcessorFunction> --query 'Environment.Variables.FAULT_INJECT'   # "" 확인
```

- `pytest -m integration`만 주면 `fault` 테스트도 수집되지만 실행하지 않고 skip한다(`-m "integration and fault"`로만 돈다). `fault` 테스트는 처리 함수의 `FAULT_INJECT`가 기대값이 아니면 skip한다(잘못된 배포에서 판정하지 않는다).
- 주입 배포 뒤에는 반드시 복원 배포를 한다. `demo` 스택(`haru-demo`)은 `Stage`·`FaultInject`를 무엇으로 넘겨도 함수에 주입 값이 들어가지 않는다(BE-Q59). 변경 세트로 `haru-demo`에 `Stage=demo FaultInject=photo`를 넘겨 `Rules`가 거부하는지는 AWS 담당이 수동으로 한 번 확인한다(실행하지 않고 변경 세트만 만든다).
- `GET /claims/{claimId}/record`로 사진 상태를 폴링하는 사례는 묶음 B(BE-Q46)가 이 브랜치에 들어온 뒤 더한다(작업 17). 지금은 DynamoDB 직접 조회로 판정한다(BE-Q38).

### 3.5 새 계정 판정 기록 (2026-11-27, AWS 담당)

배포

| 항목 | 값 |
|---|---|
| 계정·리전 | 새 AWS 계정, `ap-northeast-2`. 배포 주체는 IAM 사용자(MFA 등록, `AdministratorAccess`). Budgets 월 알림 $200 |
| 코드 | `main` `17486ed`(1–5단계, 6a·6b 코드, Bedrock 전환 병합본) |
| 스택 | `haru-dev`, `CREATE_COMPLETE`(16:11). 변경 세트 47개 항목 모두 추가(삭제·수정·교체 없음) |
| 파라미터 | `AllowedOrigins=http://localhost:5173 Stage=dev LlmProvider=bedrock LlmModel=global.anthropic.claude-haiku-5-5 LlmProviderLabel=AmazonBedrock LlmTemperature=""`. `AgentMode`는 기본값 `pipeline`, `FaultInject`·`AiFaultInject`는 빈 값 |
| 빌드 | `sam validate --lint` 통과, `sam build --use-container` 성공(Pillow 레이어, AiCardFunction은 `ai-requirements.lock` 해시로 설치) |
| 단위 테스트 | **이번 배포 전에는 끝까지 돌리지 않았다.** 도중에 멈춰 중단했고, 사용자 결정으로 건너뛰었다(아래 "환경 메모") |
| 출력값 | `ApiUrl` `https://44v7y11022.execute-api.ap-northeast-2.amazonaws.com`, `UserPoolId` `ap-northeast-2_aDKSKKc5G`, `UserPoolClientId` `2pphg94f4thbgfmgetjippendf` (비밀 아님. 스택을 다시 만들면 바뀐다) |

Bedrock 모델(Claude Haiku 5.5) 확인

- 서울 리전 카탈로그에서 모델 ID `anthropic.claude-haiku-5-5`는 추론 프로필로만 호출된다. `apac.` 프로필은 없고 `global.` 프로필만 있다. **Global 교차 리전 추론이라 사연이 국외 리전에서 처리될 수 있다**(BE-Q7 동의 문구에 반영 필요).
- **이 모델은 `temperature`를 거부한다**(`ValidationException: temperature is deprecated for this model`). 템플릿 기본값 `LlmTemperature=0`으로 배포하면 AI 요청이 모두 실패하므로 `LlmTemperature=""`를 넘긴다. 코드는 빈 값이면 `temperature`를 보내지 않는다(`agent/llm.py`).
- Converse API 직접 호출(temperature 없음): 일반 질문 1.34초, 도구 호출 0.83초(`toolChoice` 없음), 0.79초(`toolChoice: any`). 모두 도구를 정확히 호출했다. AI 경로의 AWS 판정은 하지 않았다(아래 "남은 일").

판정 결과 (`pytest -m "integration and not fault" tests/integration`, 16:11–16:18, 22 passed, 1 failed, 10 skipped)

| T | 결과 | 근거 로그 |
|---|---|---|
| T1 (4단계 확장, 액세스 토큰 포함) | 통과 (3건) | `T1-authz-*.json`, `T1-access-token-*.json` |
| T2 역할별 권한 | 통과 | `T2-role-access-*.json` |
| T3·T4·T5·T14 | 통과 | `T3-concurrent-claims-*.json`, `T4-same-user-*.json`, `T5-concurrent-complete-*.json` |
| T6·T7·T16 | 통과 | |
| T13·가입 | 통과 (5건) | `T13-sequential-*.json`, `T13-concurrent-*.json` |
| T17 | 통과 (2건) | `T17-reply-twice-*.json`, `T17-concurrent-replies-*.json` |
| T8·T11 | 통과 | `T8-corrupt-image-*.json`, `T11-gps-stripped-*.json` |
| 재업로드·주입 차단 | 통과 | `photo-reupload-*.json`, `photo-fault-blocked-*.json` |
| IAM·CORS | **실패** | `photo-iam-and-cors-*.json`. 아래 설명 |
| T10·T15 | **미검증(skip)**. `processing_not_observed`. 16:23에 다시 돌려도 같다 | `T10-*.json`, `T15-*.json`. 3.4절 규칙대로 지연 주입 판정이 필요하다 |
| AI 경로(T18–T20, T22, Fake 경로) | skip. 이 배포는 `AgentMode=pipeline`, `LlmProvider=bedrock`이라 대상이 아니다 | |

IAM·CORS 실패 내용(같은 결과로 16:23에 한 번 더 확인)

- 앱이 만든 presigned URL은 모두 기대대로다. preflight 200(`allow-origin: http://localhost:5173`), 서명 길이 불일치 403 `SignatureDoesNotMatch`, 정상 업로드 200, presigned GET 6,700바이트.
- 실패는 **테스트가 직접 만든 만료 URL**(`_boto("s3").generate_presigned_url`, 1초)이 403 대신 **307 `TemporaryRedirect`**를 받은 것이다.
- 원인 추정(미확인): 새로 만든 버킷에 리전 지정 없는 주소로 요청하면, S3가 버킷 주소를 전파하는 동안 307로 리다이렉트할 수 있다. 제품 경로가 아니라 테스트 헬퍼의 주소 문제일 가능성이 크다. 몇 시간 뒤 다시 돌리거나, 테스트가 서울 리전 엔드포인트(`https://s3.ap-northeast-2.amazonaws.com`)로 서명하게 고친다(개발 담당).

환경 메모 (Windows, AWS 담당 PC)

- `src/ai-requirements.lock`은 manylinux 해시라 Windows venv에 그대로 설치되지 않는다. 로컬 단위 테스트용으로는 `pip install -r requirements-dev.txt -r src/ai-requirements.in -r local/adapter/requirements.txt`로 같은 버전을 설치했다. Lambda 빌드는 컨테이너에서 lock 파일을 쓰므로 영향이 없다.
- 단위 테스트는 AI 의존성 설치 뒤 약 18%(260여 건) 지점에서 15분 넘게 진행하지 않아 중단했다. 그때 `AWS_PROFILE`이 켜져 있었다. 어느 테스트에서 멈췄는지는 기록하지 못했다(원인 미확인).

#### 주입·에이전트 판정 (16:35–16:55, `17486ed`)

배포 A `FaultInject=photo-slow AgentMode=agent`, 배포 B `FaultInject=photo AiFaultInject=ai-slow AgentMode=agent`. 두 변경 세트 모두 함수 3개(`AiCardFunction`, `PhotoProcessorFunction`, `HttpApi`) 수정뿐이었다. 함수 환경 값을 배포마다 확인했다(`LLM_PROVIDER=bedrock`, `LLM_TEMPERATURE=""`).

| T | 결과 | 근거·설명 |
|---|---|---|
| T10·T15 (`test_T10_T15_with_delay`, `photo-slow`) | **통과** | 기본 배포에서 미검증이던 두 사례의 최종 판정(3.4절 규칙) |
| T20 (같은 턴 5회 동시) | **통과** | `T20-*.json` |
| T21 (`ai-slow`) | **통과** | 모든 응답 30초 안 |
| T9 (`photo`) | **테스트 실패, 동작은 기대대로** | `T9-dlq-20261127T165427.json`: `FAILED RETRY_EXHAUSTED`, 알람 `ALARM`, 테스트 메시지 1건 삭제. `inDlq: false`는 첫 DLQ 조회(120초)가 메시지 이동보다 먼저 끝나서다. 큐 가시성 시간이 180초라 세 번째 수신 뒤 DLQ로 옮겨지기까지 120초를 넘는다(추정). 테스트 대기 시간을 늘려야 한다(개발 담당) |
| T18·T19·T22 | **skip, 미검증** | 테스트가 `openai_compat`만 실제 공급자로 봐서 `bedrock` 함수를 Fake로 판단했다. `tests/integration/test_ai.py`의 `_real_only`·`_llm_mode`가 `bedrock`도 실제 공급자로 보도록 고쳤다. 7단계 배포에서 다시 판정한다 |

배포 C(복원)는 실행되지 않았다. 주입 파라미터를 빼고 `sam deploy`를 하면 **이전 값이 유지된다**(UsePreviousValue). 그래서 "바뀐 것 없음"으로 끝났고 스택은 주입 상태로 남았다. 끄려면 `FaultInject="" AiFaultInject=""`를 명시한다. 이후 배포는 이렇게 했다.

#### 7단계 배포 (`06e95d2`, 17:07–17:32)

| 시각 | 단계 | 결과 |
|---|---|---|
| 17:05 | 프론트엔드 빌드(`npm ci`, `npm run build`, Node 22.17.1) | 성공. `frontend/.env.production.local`은 스택 출력으로 만든 공개 값만 담고 gitignore 대상 |
| 17:07 | `sam build --use-container --build-dir .aws-sam/build7` | 성공 |
| 17:10 | 배포 F(7단계 + `AgentMode=agent`, 주입 끔) | **실패 후 롤백**(`UPDATE_ROLLBACK_COMPLETE`) |
| 17:20 | 템플릿 수정 후 다시 빌드, 웹·템플릿 단위 테스트 76건 통과 | |
| 17:32 | 배포 F 재시도 | **`UPDATE_COMPLETE`**. 추가 11개(웹 버킷·OAC·CloudFront·알람 5종·대시보드·`GET /record` 권한), 수정 13개, 삭제·교체 없음. 함수 환경 `FAULT_INJECT=""` 확인 |
| 17:32 | `deploy_web.py --apply --prune` | 7개 업로드, 무효화 `I6X4FL37TS5WOK8688GVSVY1AQ` |

**롤백 원인과 수정**: `WebDistribution`이 `The specified response headers policy does not exist. (Status Code: 404)`로 실패했다. 템플릿의 `Managed-SecurityHeadersPolicy` ID `67f7725c-6f97-48c1-86a6-d8d6b5fc7a49`가 틀렸다. `aws cloudfront list-response-headers-policies --type managed`로 확인한 실제 ID는 `67f7725c-6f97-4210-82d7-5512b31e9d03`이다. `template.yaml` 두 곳을 고치고, `tests/unit/test_web_infra.py`에 이 ID 검사를 더했다. 캐시 정책 ID 두 개는 맞았다. 롤백 중에는 스택이 배포 B의 주입 상태로 돌아가 있었다.

7단계 출력값(비밀 아님): 웹 주소 `https://da83p51l0pi6n.cloudfront.net`, `DistributionId` `E38ZPOZ2YYKHXG`, `WebBucketName` `haru-dev-web-963701985499`. API·Cognito 값은 위와 같다. Budgets 파라미터(`BudgetMonthlyUsd`, `BudgetNotificationEmail`)는 비웠다. 이 계정에 이미 월 $200 예산이 있다.

#### 7단계 판정 (배포 F 상태, 17:33–20:45)

`integration and not fault`를 AI·사진·나머지 세 묶음으로 동시에 돌렸다. 배포 F는 `AgentMode=agent`, 주입 끔이다.

| 묶음 | 결과 | 내용 |
|---|---|---|
| AI (`test_ai.py`) | **7 passed**, 1 skipped | T18 3건, T19, T20, T22 2건 통과(Bedrock Haiku 5.5). skip 1건은 Fake 전용 사례 |
| 나머지(권한·이어받기·동시성·멱등·수신함·웹) | 24 passed, **1 failed** | `GET /record` 스냅샷(`test_get_record_snapshot_during_writes`) 통과. 실패는 `test_api_cors_allows_distribution_origin`(아래 "API CORS 결함") |
| 사진 (`test_photo.py`) | 4 passed, 2 failed, 1 skipped, 1 error | 3시간 12분 걸렸다. 판정 도중 `aws login` 자격 증명 갱신(`signin.aws.amazon.com/v1/token`) 연결이 끊겨 `test_photo_fault_blocked`가 오류로 끝났다. T10 실패는 아래, IAM·CORS는 앞의 307과 같다. T15는 `processing_not_observed` skip |

T10 실패 내용(`T10-text-only-during-processing-20261127T173623.json`): `PROCESSING`을 관측한 뒤 `TEXT_ONLY` 완료를 보냈지만 그 사이 사진 전달이 먼저 끝나 409 `CLAIM_NOT_ACTIVE`를 받았다. 경합에서 진 경우인데, 테스트는 200 `hasPhoto: true`만 `race_lost`(미검증)로 보고 409는 실패로 본다. 지연 주입 없는 배포에서는 생길 수 있는 결과다. 최종 판정 근거인 지연 주입 판정(배포 A)은 통과했다. 409 `CLAIM_NOT_ACTIVE` + 전달 완료도 `race_lost`로 볼지 개발 담당이 정한다.

복원 배포 G(`AgentMode=pipeline`, 주입 끔): 20:47 `UPDATE_COMPLETE`. 변경은 `AiCardFunction`, `HttpApi` 수정뿐이었다. 웹 `GET /` 200.

#### API CORS 결함과 수정 (배포 H, 21:04–21:10)

- 증상: CloudFront 주소를 `Origin`으로 보낸 preflight가 204인데 `Access-Control-Allow-Origin`이 없었다. 실제 API의 `AllowOrigins`는 `http://localhost:5173` 하나였다. **이대로면 웹(CloudFront)에서 브라우저가 API 호출을 막는다.** 사진 버킷 CORS에는 배포 도메인이 들어가 있었다.
- 원인: SAM은 `HttpApi` `CorsConfiguration.AllowOrigins`가 내장 함수이면 그 값을 `x-amazon-apigateway-cors` **전체**로 쓰고 `AllowHeaders`·`AllowMethods`를 버린다(samtranslator `open_api.add_cors`). 템플릿이 `!Split`을 바로 넣어서 변환 결과의 CORS 자리에 목록이 들어갔다(`get_template --template-stage Processed`로 확인). API Gateway는 이 값을 반영하지 않고 1–6단계의 설정을 그대로 두었다.
- 수정: CORS 객체 전체(`allowOrigins`·`allowHeaders`·`allowMethods`)를 늘 참인 `!If [CorsAlways, 객체, NoValue]`로 감쌌다. `CorsAlways`는 스택 이름이 비지 않았는지로 본다(상수 비교는 cfn-lint W8003에 걸린다). `test_template.py`·`test_web_infra.py`를 새 구조에 맞췄다. SAM CLI에 들어 있는 samtranslator로 변환해 CORS 객체가 제대로 나오는 것을 확인했다.
- 배포 H: 변경 세트는 `HttpApi` 수정 1건(교체 없음), 21:09 `UPDATE_COMPLETE`. H는 `CorsAlways: !Equals ["true", "true"]`로 배포했고, 그 뒤 lint 통과 형태로 바꾼 템플릿을 21:58에 다시 배포했다. 리소스 결과가 같아 CloudFormation이 "No updates are to be performed"로 끝냈다(스택에 저장된 템플릿의 조건식만 이전 형태). 다음 배포 때 함께 바뀐다. 실제 API `AllowOrigins`가 `["http://localhost:5173", "https://da83p51l0pi6n.cloudfront.net"]`이 됐고, 두 주소 모두 preflight에 `Access-Control-Allow-Origin`이 돌아온다.
- 재판정: `test_web.py` 6건과 `test_authz.py` 4건, **10 passed**(`test_api_cors_allows_distribution_origin` 포함).
- 사진 재판정(T10·T15 제외, 자격 증명 연결 오류 뒤 다시): T8, T11, 재업로드, IAM·CORS, 주입 차단 **5 passed**(3분 35초). IAM·CORS는 아래 테스트 수정 뒤 만료 URL이 403을 받았다.
- 함께 고친 테스트: `test_photo_iam_and_cors`의 만료 URL을 SigV4로 서명한다(`Config(signature_version="s3v4")`). 기본 서명은 전역 엔드포인트 URL을 만들어 새 버킷에서 403 대신 307 `TemporaryRedirect`가 왔다. 앱의 presign은 원래 s3v4다.

남은 일

- T10 409 판정 규칙(위), T9 대기 시간: 테스트 수정(개발 담당).
- T12: 지금 테스트는 `openai_compat` 무효 키 방식이라 Bedrock에 맞지 않는다. 인계 문서(`.kiro/specs/backend-stage7-ops/aws-handoff.md` 4절 9번)의 Bedrock 방식(잘못된 모델 ID·권한)으로 테스트를 바꾼다(개발 담당).
- `haru-demo` 배포, `seed.py`, 90초 시연 리허설.
- 정리: 사진·웹 버킷을 비운 뒤 `sam delete --stack-name haru-dev`.

## 4. AWS에서만 확인되는 것 (1·2단계 해당분, docs/02 §2.4.4)

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | JWT authorizer가 모든 경로를 보호하는지. **거부 시 본문은 `{"message":"Unauthorized"}`로 계약 형식이 아니다** | T1 테스트. 본문 차이는 계약 변경 리뷰 대상(8절) |
| 2 | PreSignUp 트리거 연결과 자동 확인, `nickname` 필수 속성 | 가입 직후 로그인 테스트 |
| 3 | 실제 Cognito ID 토큰의 `nickname` 클레임(BE-Q17 실측) | T1 대조군 테스트의 `GET /me` 닉네임 |
| 4 | `PlansFunction` IAM: `TransactWriteItems`가 `PutItem` 권한만으로 실행되는지 | T13. 실패하면 6절 표의 권한을 고친다 |
| 5 | API CORS(허용 Origin `http://localhost:5173`) | 브라우저 또는 `curl -X OPTIONS -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: POST" $ApiUrl/plans` |
| 6 | 동시 요청에서 멱등 키가 Plan 1건을 지키는지(실제 병렬성, TransactionConflict) | T13 동시 10회 |
| 7 | 콜드 스타트, 메모리·타임아웃 | CloudWatch Logs의 `Init Duration` 참고(1–3단계는 의존성이 작다) |
| 8 | **G1–G4 동시성**: 실제 병렬 요청과 `TransactionConflict`. moto·Floci는 재현하지 않는다 | T3·T4·T5(동시 호출), T6·T7·T14 |
| 9 | 3단계 IAM: 트랜잭션의 Update·ConditionCheck가 `UpdateItem`·`ConditionCheckItem` 권한으로 실행되는지, `GET /me/claims`의 GSI2 조회 | T3–T7, T14 |
| 10 | EMF 지표 `ClaimConflict`·`CompleteDuplicate`·`StaleRequestRejected`가 CloudWatch 지표(네임스페이스 `Haru`)로 추출되는지 | T3·T5·T6 뒤 CloudWatch 콘솔 → 지표 → Haru |

확인 결과 (2026-11-25, `haru-dev`, AWS 담당)

| # | 결과 |
|---|---|
| 1 | 모든 경로가 토큰 없음·잘못된 토큰에 401. 본문은 `{"message":"Unauthorized"}`(계약 형식 아님, 8절 리뷰 대상). 액세스 토큰은 처음에 200으로 통과해 `auth.py`에서 막았다(3.1절) |
| 2 | 가입 직후 인증 코드 없이 로그인 성공, `nickname` 없는 가입 거부 |
| 3 | 실제 Cognito ID 토큰에 `nickname` 클레임이 있다(T1 대조군의 `GET /me`). BE-Q17의 AWS 쪽 확인 |
| 4 | `TransactWriteItems`가 `PutItem`·`UpdateItem` 권한으로 실행된다(T13 통과, `AccessDenied` 로그 0건) |
| 5 | 허용 Origin `http://localhost:5173`의 사전 요청은 204와 `access-control-allow-origin: http://localhost:5173`, 메서드 `GET,OPTIONS,POST,PUT`, 헤더 `authorization,content-type,idempotency-key`. 다른 Origin은 `allow-origin` 헤더 없음 |
| 6 | 같은 멱등 키 동시 10회에 Plan 1건(T13) |
| 7 | Init Duration: `MeFunction` 약 0.68–0.70초, `PlansFunction` 약 0.70–0.71초, `ClaimsFunction` 약 0.71–0.72초, `PreSignUpFunction` 약 0.08초. 최대 메모리 102MB(설정 256MB), 최대 실행 시간 1.42초(제한 10초) |
| 8 | T3·T4·T5·T6·T7·T14 통과 |
| 9 | 트랜잭션의 Update·ConditionCheck와 GSI2 조회에서 `AccessDenied` 없음. 판정 후 Lambda 로그의 오류·타임아웃 0건 |
| 10 | `Haru` 네임스페이스에 지표 3종이 추출됨. 판정 직후 3시간 합계 `ClaimConflict` 9, `CompleteDuplicate` 9, `StaleRequestRejected` 7 |

## 5. 로컬 환경 (Docker)

처음 인계 때는 개발 PC에서 Floci 이미지 다운로드가 멈춰 한 번도 띄우지 못했다(그 PC의 네트워크 문제로 보이며 원인은 확인하지 않았다). **2026-11-25 다른 환경에서 첫 구동에 성공했다.**

### 5.1 첫 구동 기록 (2026-11-25, 개발 담당)

| 항목 | 값 |
|---|---|
| 환경 | Windows + WSL2 Ubuntu 26.04, Docker 29.9.2, Docker Compose v5.6.1, Python 3.12.16(uv) |
| 기준 커밋 | `origin/fix/be-3-aws-verify`(`e80b890`) 위의 `fix/be-3-local-verify` |
| 이미지 | `docker pull floci/floci:2.5.0-compat` 정상. `api` 이미지 빌드 정상 |
| `aws` 로그 | `ok step=` 5줄(`create_haru_table`, `create_checkpoint_table`, `ensure_user_pool`, `ensure_user_pool_client`, `ensure_seed_users`), 고정 ID `ap-northeast-2_haruLocal`·`haruLocalWebClient` 적용, healthcheck 통과 |
| `api` 로그 | `listening port=3000 stage=local dev_token=True` |
| 단위 테스트 | `pytest tests/unit` 289건 통과(`_cleanup` 회귀 테스트 추가 후 296건) |
| 로컬 통합 테스트 | `pytest -m local tests/local` 16건 통과. 처음에는 `test_local_claims.py` 3건이 테스트 코드의 `call()` 반환값 언패킹 오류로 실패해 테스트만 고쳤다(제품 코드 변경 없음) |
| BE-Q17 | Floci ID 토큰에 `nickname`·`aud`·`token_use`가 있고 `GET /me` 닉네임이 시드 값과 같다(docs/08 BE-Q17) |

- `aws` 로그에 ECS 관련 예외 스택(`EcsService.init` → `removeLeftoverContainers`)이 한 번 찍힌다. Floci의 ECS 기능이 Docker 소켓을 찾다 나는 것으로, 이 프로젝트가 쓰는 DynamoDB·Cognito에는 영향이 없다. 무시한다.
- 로컬 결과는 T 시나리오 합격 근거가 아니다(BE-Q15). 3단계 로컬 테스트도 조건식 로직 확인이며 동시성 판정은 AWS에서 한다.

### 5.2 Python 3.12 가상환경 (uv)

시스템 Python이 3.12가 아니면(예: Ubuntu 26.04는 3.14) uv로 3.12를 받아 쓴다. 시스템 Python은 건드리지 않는다.

```bash
# uv 설치(사용자 디렉터리 ~/.local/bin. 처음 한 번)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

cd backend
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt -r local/adapter/requirements.txt
source .venv/bin/activate
python --version          # Python 3.12.x
pytest tests/unit
```

- Windows PowerShell은 설치를 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`로 하고, 경로를 `.venv\Scripts\python.exe`, `.venv\Scripts\activate`로 바꾼다.
- `.venv/`와 `.env`는 `backend/.gitignore`에 있어 커밋되지 않는다.
- 2.2절 배포 런북의 `python -m venv`도 PATH의 Python이 3.12일 때만 맞다. 아니면 위 방법으로 만든 가상환경을 켠 뒤 `sam build`를 실행한다.

### 5.3 실행 절차

구성 파일과 단위 테스트:

| 파일 | 역할 | 단위 테스트 |
|---|---|---|
| `docker-compose.yml` | `aws`(floci/floci:2.5.0-compat), `api`(로컬 어댑터) | — |
| `local/init/01_haru.py` | 테이블 2개, 유저 풀(ID 고정), 시드 사용자 3명, 사진 DLQ·큐(가시성 180초, redrive 3)·버킷(CORS·수명 주기)·알림(5단계) | `tests/unit/test_local_init.py` |
| `local/adapter/app.py` | payload 2.0 변환, JWT 검증, `/dev/token`, CORS, SQS 폴러(5단계, 사진 처리 핸들러 호출) | `tests/unit/test_adapter.py` |
| `tests/local/` | 로컬 통합 테스트(`pytest -m local`) | — |

실행하며 확인할 것:

1. `docker pull floci/floci:2.5.0-compat`가 받아지는지. 안 되면 Docker Desktop 프록시·로그인, 네트워크를 확인한다.
2. `cp .env.example .env`(Windows `copy`) 후 `docker compose up -d --build`.
3. `docker compose logs aws`에 `ok step=...` 다섯 줄과 `LOCAL_USER_POOL_ID=ap-northeast-2_haruLocal`이 보이는지. `WARNING 고정 ID가 적용되지 않았다`가 나오면 로그의 값으로 `.env`를 고친 뒤 `docker compose up -d`로 `api`를 다시 띄운다.
4. `docker compose logs api`에 `listening port=3000`이 보이는지.
5. `pytest -m local tests/local -s`가 통과하는지. `test_seed_user_login_and_me_nickname`이 BE-Q17(Floci ID 토큰의 `nickname`·`aud`·`token_use`) 결과를 출력한다. 실패하면 dev JWT 경로(`POST /dev/token`)만 쓰고 결과를 docs/08 BE-Q17·FE-Q8에 적는다.
6. 끄기: `docker compose down`(데이터 유지), `docker compose down -v`(데이터 삭제).

Docker 없이 확인한 대체 수단: moto 테스트(`tests/unit/test_plan_service_moto.py`, `test_claim_service_moto.py`, `test_claim_properties.py`, `test_handlers_claims.py`)가 실제 DynamoDB 조건식·취소 사유 코드·GSI 조회를 확인한다. moto와 Floci 모두 실제 병렬성은 재현하지 않으므로 동시성 판정은 AWS에서만 한다.

### 5.4 4단계 로컬 통합 테스트 결과 (2026-11-25, 개발 담당)

| 항목 | 값 |
|---|---|
| 기준 | `feat/be-4-record-inbox`, `8fcf239` 위 4단계 수신함 묶음(커밋 전 작업 트리) |
| 실행 | `docker compose up -d --build`(api 이미지 재빌드) 후 `pytest -m local tests/local` |
| 결과 | **23건 통과**(기존 16건 + `test_local_inbox.py` 7건) |
| 확인한 것 | 완료 → 계획자 `GET /me` 미확인 1 → `GET /inbox` 1건 → 상세(사진 필드 null) → 읽음 204(재요청도 204) → 미확인 0 → 답장 201 → 두 번째 409. 실행자·제3자의 수신함 경로 404와 404 뒤 불변, 토큰 없음 401 |
| 고친 테스트 | `test_local_flow.py::test_me_with_dev_jwt`가 고정 사용자 ID 대신 새 사용자로 `unreadInboxCount == 0`을 확인한다(4단계부터 계산값) |

- Floci에서 수신함의 조건부 `UpdateItem`(읽음 `attribute_exists(PK) AND ownerId = :me`, 답장 `ownerId = :me AND attribute_not_exists(reply)`)이 계약대로 돈다. T 판정 근거는 아니다(BE-Q15).

### 5.5 5단계 로컬 환경과 결과 (2026-11-25, 개발 담당)

구성: `aws`에 `FLOCI_AUTH_VALIDATE_SIGNATURES=true`(presigned PUT 서명 검사), init이 `haru-photo-dlq`·`haru-photo-queue`·`haru-photos-local`과 버킷 알림(prefix `photos/original/`)을 만든다. `api`는 presigned URL을 `PUBLIC_S3_ENDPOINT=http://localhost:4566`(브라우저 기준 주소)로 서명하고, `STAGE=local`이고 `PHOTO_QUEUE_URL`이 있을 때만 SQS 폴러 스레드가 `workers.photo_processor.handler`를 부른다(정상 반환이면 메시지 삭제, 예외면 남김). 사진 처리에 Pillow가 필요해 `local/adapter/requirements.txt`에 `Pillow==13.0.0`을 더했다.

- 리눅스에서 umask가 `0077`이면 Floci init이 `local/init/01_haru.py`를 읽지 못해 `aws`가 unhealthy가 된다. `chmod -R go+rX local src` 후 띄운다.

| 항목 | 값 |
|---|---|
| 기준 | `feat/be-5-photo-pipeline` `cfc65a7`(작업 11·12 커밋) |
| 실행 | `docker compose up -d --build --force-recreate` 후 `pytest -m local tests/local` |
| 결과 | **28건 통과, 8건 사유 skip**(기존 23건 + `test_local_photo.py` 5건). 서명 검사를 켠 상태에서 기존 23건이 그대로 통과했다 |
| 조건부 사례 | 환경 변수를 바꿔 다시 띄워 한 번씩 통과: `PHOTO_UPLOAD_IF_NONE_MATCH=true`(두 번째 PUT 412, 버킷 CORS 허용 헤더에 `If-None-Match`), `FAULT_INJECT=photo-slow`(처리 중 `TEXT_ONLY` → `DISCARDED`·처리본 0개, 처리 중 교체 → 새 사진 전달·처리본 1개), `FAULT_INJECT=photo PHOTO_QUEUE_VISIBILITY_S=2`(수신 3회 → `FAILED RETRY_EXHAUSTED` → DLQ) |
| 기본 사례 | 정상 업로드 → 폴러 → 전달 → 계획자 `photoUrl`로 받은 처리본에 EXIF·GPS·ICC 없음, 캡션 "출근길 빵집에서". 손상 파일 → `FAILED CORRUPT_IMAGE` → `TEXT_ONLY`. 업로드 전 교체 → 새 키로 전달, 이전 URL로 늦게 올린 원본은 무시. 잘못된 `Content-Length` → 403. 같은 URL 재업로드(스위치 꺼짐) → 둘 다 200, 전달 1회·처리본 1개 |

Floci 2.5.0-compat 확인 결과(BE-Q64, 실제 구동으로 판단)

| 항목 | 결과 |
|---|---|
| 버킷 알림(prefix 필터, `s3:TestEvent`, `eTag`) | 동작. init 직후 `s3:TestEvent`가 오고 처리 Lambda가 무시한다 |
| presigned PUT `Content-Length` 서명 검사 | 서명 검사 켬: 잘못된 길이 403 |
| presigned·SDK `If-None-Match: *` | 412 |
| `HeadObject`·`GetObject` `IfMatch` | 일치 200, 불일치 412(따옴표 유무 모두) |
| SQS redrive(`maxReceiveCount` 3), `ApproximateReceiveCount` | 동작. 수신 횟수 1→2→3, 그다음 DLQ |
| 수명 주기·CORS 설정 | 수락(조회하면 같은 값) |
| 버킷 정책 | 수락하지만 **강제하지 않는다**(PutObject Deny 정책에도 PUT 200) |

로컬 미지원(로컬 테스트에서 사유를 출력하는 skip, AWS 판정 항목): 수명 주기 실제 만료(7일), 브라우저 CORS preflight·오류 응답의 CORS 헤더, 버킷 정책 강제(TLS·`s3:if-none-match`), 실제 SQS 이벤트 소스 매핑·Lambda 강제 종료·DLQ 알람. 알림이 동작하므로 로컬 전용 우회(어댑터가 이벤트를 넣는 방식)는 쓰지 않는다.

## 6. 함수별 IAM 권한

| 함수 | 권한 | 이유 |
|---|---|---|
| `MeFunction` | `HaruTable`과 `index/*`에 `dynamodb:GetItem`, `Query` | `GET /me/claims`(GSI2 조회 + Plan·Record 읽기), `GET /me`의 미확인 수(기본 테이블 Query, `ConsistentRead`). 권한은 3단계 그대로다 |
| `PlansFunction` | `HaruTable`과 `index/*`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `Query` | 생성(Plan + 멱등 키 트랜잭션), 상세(ConsistentRead), 목록(GSI1), 내 Claim 조회, 이어받기(Plan Update + Claim·ClaimLookup Put + 이전 Claim Update) |
| `ClaimsFunction` | `HaruTable`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `ConditionCheckItem`. 5단계: 사진 버킷 `photos/original/*`에 `s3:PutObject` | 포기·기록·완료 트랜잭션(Update, InboxItem Put, 기록 저장의 ConditionCheck)과 ConsistentRead. S3 권한은 presigned PUT 서명용이다(함수가 직접 올리지 않는다) |
| `AiCardFunction`(6a) | `HaruTable`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`, 조건 `dynamodb:LeadingKeys` = `AISESSION#*`·`AIQUOTA#*`. `LlmApiKeyParam`이 있으면 그 파라미터 ARN 하나에 `ssm:GetParameter` | 세션 저장·조회, 하루 할당량 조건부 갱신. `Query`·`Scan`·트랜잭션·`index/*`·`kms:*` 없음(`aws/ssm` 관리형 키는 KMS 권한이 따로 필요 없다). Plan·User·Claim·Idem 키에는 쓰지 못한다(G6) |
| `AiCardFunction`(6b 추가) | `HaruAgentCheckpoints`에만 `dynamodb:GetItem`, `PutItem`, `Query`, `BatchGetItem`, `BatchWriteItem`(조건 없음, `index/*` 없음) | 체크포인트 라이브러리(`langgraph-checkpoint-aws` 1.3.0)가 쓰는 연산 5개뿐이다(프로토타입 V9). `delete_thread`는 BatchWriteItem의 DeleteRequest를 쓴다. `DeleteItem`·`Scan`·`UpdateItem` 없음. 다른 함수에는 이 테이블 권한이 없다 |
| `InboxFunction`(4단계) | `HaruTable`에 `dynamodb:GetItem`, `Query`, `UpdateItem`(`index/*` 없음). 5단계: 사진 버킷 `photos/processed/*`에 `s3:GetObject` | 수신함 Query, 상세의 InboxItem·Plan·Record GetItem(ConsistentRead), 읽음·답장의 조건부 UpdateItem. InboxItem을 만들거나 지우지 않는다. S3 권한은 `photoUrl`(15분 presigned GET) 서명용 |
| `PhotoProcessorFunction`(5단계) | `HaruTable`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`(`index/*` 없음). 사진 버킷 `photos/original/*`에 `s3:GetObject`(HeadObject 포함), `photos/processed/*`에 `s3:PutObject`·`s3:DeleteObject`. `PhotoQueue`에만 `sqs:ReceiveMessage`·`DeleteMessage`·`GetQueueAttributes`(인라인) | 사진 상태 갱신과 3단계 `complete_claim`(트랜잭션 Update 3·Put 1, ConditionCheck 없음). 원본 읽기, 처리본 쓰기·자기 처리본 삭제. SAM의 `SQS` 이벤트는 관리형 `AWSLambdaSQSQueueExecutionRole`(Resource `*`)을 붙이므로 쓰지 않고 `PhotoProcessorQueueMapping`(`AWS::Lambda::EventSourceMapping`, BatchSize 1)을 직접 둔다. `s3:ListBucket`이 없어 없는 원본의 HeadObject는 403이다(BE-Q70) |
| `PreSignUpFunction` | 없음 | 이벤트만 바꾼다. Cognito 호출 권한은 `PreSignUpInvokePermission`(SourceArn은 순환 참조를 피하려고 `userpool/*`) |

권한 오류(`AccessDeniedException`)가 나면 CloudWatch Logs의 예외 유형과 이 표를 대조한다. 로그에는 예외 유형만 남긴다(응답에는 500 `INTERNAL_ERROR`).

## 7. 미결 질문과 임시 결정

구현은 spec이 정한 임시 기본안을 따랐다. 전체 목록은 [docs/08](../docs/08-open-questions.md) §8.1.

| # | 임시 결정 |
|---|---|
| BE-Q3, BE-Q32 | `limit` 기본 20·최대 50, 잘못된 값은 보정, `nextCursor: null` |
| BE-Q17 | 실측 완료(2026-11-25): AWS·Floci ID 토큰 모두 `nickname` 있음(4절 3항, 5.1절). 로컬 인증 방식의 결정과 프론트 SDK 로그인 확인(FE-Q8)은 남음 |
| BE-Q22 | `PLATE`·`LOT`·`PRIVATE_PLACE`는 `MEDIUM`, 차단 안 함 |
| BE-Q23 | 500 코드 `INTERNAL_ERROR`(계약 변경 리뷰 필요) |
| BE-Q24 | 멱등 재요청도 201 |
| BE-Q25 | 장소 이름은 토큰별 조사 제거 + 부분 문자열, 활동은 서술어 꼴 토큰(-기·-고·-서·-며)을 빼고 핵심 명사만 대조. 동의어는 `src/domain/normalization.json` |
| BE-Q26 | `PERSON_NAME`은 탐지하지 않음 |
| BE-Q29 | 헤더 누락 시 `details` 키 `Idempotency-Key` |
| BE-Q1 | `GET /claims/{claimId}/record`를 실행자가 아닌 사람이 부르면 403 `FORBIDDEN`(BE-Q46 묶음) |
| BE-Q30 | 앞부분(4단계 전 0 고정)은 **해소**: 4단계부터 BE-AUTH-05대로 센다. `nickname` 클레임이 없을 때는 BE-Q17로 넘겼다 |
| BE-Q33 | `currentClaimId`는 응답에 내보내지 않음 |
| BE-Q34 | **5단계에서 해소**: `photo`가 오면 업로드 URL을 발급한다 |
| BE-Q35 | `GET /me/claims`의 `status` 누락·잘못된 값은 400 |
| BE-Q36 | `claimId = clm_ + ULID`, 실행자 닉네임 속성 `claimerNickname` |
| BE-Q37 | EMF는 라이브러리 없이 직접 출력, 네임스페이스 `Haru`, 차원 없음 |
| BE-Q38 | AWS 판정 테스트가 DynamoDB를 직접 조회·갱신(T5·T6 건수, T14 `dueAt`) |
| BE-Q39 | `COMPLETED` 계획 이어받기는 409 `ALREADY_CLAIMED` |
| BE-Q40 | 완료 Record 조건에 방어 조건 2개 추가(`deliveredAt` 없음, 읽은 `photoStatus` 일치) |
| BE-Q41 | `GET /me/claims`는 GSI2라 방금 이어받은 Claim이 잠깐 빠질 수 있음 |
| BE-Q42 | **5단계에서 해소**: `photoUrl`(15분 presigned GET)·`photoCaption`(마지막 장소 + "에서") |
| BE-Q43 | InboxItem 응답에 `ownerId`를 내보내지 않음 |
| BE-Q44 | 이미 읽은 항목의 읽음 재요청도 204 |
| BE-Q45 | InboxItem `claimerNickname`은 null일 수 있다(프론트 타입은 `string`). 계약·프론트 타입은 바꾸지 않았고 팀이 정한다 |
| BE-Q46 | `GET /claims/{claimId}/record`는 TransactGetItems 스냅샷 + 충돌 재시도 소진 시 503 `TRY_AGAIN`(권장안). docs/03 §3.4 명시는 **프론트엔드 담당 승인 대기**(8절) |
| BE-Q47 | InboxItem은 있는데 Plan·Record가 없는 등 정상 경로에 없는 상태는 500 `INTERNAL_ERROR` |
| BE-Q48 | botocore `Config`(연결·읽기 타임아웃, 재시도)와 Lambda 타임아웃 10초. 지정하지 않음(기존 상태 유지). 연결이 멈추거나 스로틀링이 길면 10초를 넘어 코드 없는 500이 될 수 있다 |

### S2(프론트 글 경로 실제 API 전환)에 넘기는 경로

- 지금 쓸 수 있는 것: `GET /me`(`unreadInboxCount` 계산), `GET /me/claims`, `PUT /claims/{claimId}/record`(글만), `POST /claims/{claimId}/complete`, `POST /claims/{claimId}/abandon`, `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply`.
- 승인 대기: `GET /claims/{claimId}/record`(BE-Q46). 503 `TRY_AGAIN`이 나올 수 있어 프론트 처리 확인이 필요하다(8절).

### 5단계에서 넘겨받은 것

4단계에서 넘긴 항목(BE-Q34·BE-Q42 해제, 사진 처리 Lambda의 `complete_claim` 호출)은 5단계에서 구현했다(12절). 포기·기한 대체 뒤의 Record `photoStatus`는 여전히 `DISCARDED`로 바꾸지 않고, 처리 Lambda가 Claim 상태(`ABANDONED`·`EXPIRED`)를 보고 "전달 안 됨"으로 끝낸다. 5단계 미결 질문은 10.6절.

## 8. 리뷰가 필요한 것과 PR

2026-11-26 기준 아래 PR이 모두 열려 있고 병합된 것은 없다(1번부터 PR #2–#6, 6번이 Draft PR #8). 4단계는 PR #1, 5단계는 Draft PR #7이다. 리뷰·병합은 아래 순서로 한다.

1. `docs/monorepo-stage1-2-spec` → `main`: 문서·spec
2. `feat/be-1-2-foundation` → `docs/monorepo-stage1-2-spec`(1이 병합되면 `main`): 1·2단계 코드
3. (3단계 인계 후) `feat/be-3-claim-transaction` → `feat/be-1-2-foundation`
4. `fix/be-3-aws-verify` → `feat/be-3-claim-transaction`: AWS 판정 중 고친 `token_use` 확인과 판정 기록(3.1절)
5. `fix/be-3-local-verify` → `fix/be-3-aws-verify`: 로컬 테스트 수정, `_cleanup` 보완(3.2절), 로컬 구동 기록(5절)
6. (6a) `feat/be-6a-ai-pipeline` → `fix/be-3-local-verify`: **Draft PR #8**. 4단계(PR #1)·5단계(PR #7)와 독립 브랜치이고, 선행 PR이 병합되면 merge로 통합한다(10.8절)

4단계 브랜치(`feat/be-4-inbox`)에 남긴 2026-11-25 기록:

2026-11-25 아래 PR 6개를 열었다. **아직 병합하지 않았다.** 위에서부터 차례로 병합하고, 하나가 병합되면 다음 PR의 base를 병합된 쪽(결국 `main`)으로 바꾼다. 병합 전 리뷰와 승인은 docs/07 §7.2·§7.8을 따른다.

| 순서 | PR | head → base | 내용 | 단위 테스트(head에서 2026-11-25 재실행) | AWS 판정 |
|---|---|---|---|---|---|
| 1 | [#2](https://github.com/creatingweb123/knu-aws-2026/pull/2) | `docs/monorepo-stage1-2-spec` → `main` | 문서·steering·1·2단계 spec | 해당 없음 | 해당 없음 |
| 2 | [#3](https://github.com/creatingweb123/knu-aws-2026/pull/3) | `feat/be-1-2-foundation` → `docs/monorepo-stage1-2-spec` | 1·2단계 코드, SAM, 로컬 환경 | 225 passed | T1·T13 통과(2026-11-25) |
| 3 | [#4](https://github.com/creatingweb123/knu-aws-2026/pull/4) | `feat/be-3-claim-transaction` → `feat/be-1-2-foundation` | 3단계 트랜잭션 G1–G4 | 284 passed | T3–T7·T14·T16 통과 |
| 4 | [#5](https://github.com/creatingweb123/knu-aws-2026/pull/5) | `fix/be-3-aws-verify` → `feat/be-3-claim-transaction` | `token_use` 확인, 판정 기록(3.1절) | 289 passed | 수정 후 15건 통과 |
| 5 | [#6](https://github.com/creatingweb123/knu-aws-2026/pull/6) | `fix/be-3-local-verify` → `fix/be-3-aws-verify` | 로컬 테스트 수정, `_cleanup` 보완(3.2절), 로컬 기록(5절) | 296 passed | `_cleanup` 보완은 미실행 |
| 6 | [#1](https://github.com/creatingweb123/knu-aws-2026/pull/1) | `feat/be-4-inbox` → `fix/be-3-local-verify` | 4단계 수신함(묶음 A, 계약 변경 없음) | 385 passed | 미실행(3.3절) |
| 7 | [#7](https://github.com/creatingweb123/knu-aws-2026/pull/7) **Draft** | `feat/be-5-photo-pipeline` → `feat/be-4-inbox` | 5단계 사진 파이프라인(12절). `UploadIfNoneMatch=false` | 647 passed(2026-11-26) | 미실행(3.4절) |

- 묶음 B(`GET /claims/{claimId}/record`, `feat/be-4-record-inbox`의 `f3626c0`)는 PR을 열지 않았다. BE-Q46 승인과 docs/03 §3.4 수정 PR이 먼저다.
- 5단계 #7은 **Draft**다. Ready for Review 전환과 병합은 AWS 판정, 프론트 승인(작업 18), 묶음 B(작업 17) 상태를 보고 정한다. #1이 병합되면 base를 옮긴다(rebase하지 않는다).
- 2026-11-26 03:10–03:11에 이 브랜치가 승인 전에 원격에 올라간 일이 있었다. IDE(Kiro) Git 확장 로그에 `git push -u`와 동기화(`pull --tags` → `push`)가 남아 있고 에이전트 명령에는 없다. 누가 실행했는지는 확인하지 못했다. 올라간 변경에 비밀값·산출물이 없음을 확인했다. IDE의 "브랜치 게시"·"변경 내용 동기화"는 현재 브랜치를 그대로 push하므로 주의한다.
- 모든 PR의 `cfn-lint`는 0건이다.

비교 링크: `https://github.com/creatingweb123/knu-aws-2026/compare/<기준>...<브랜치>`

3단계 PR(#4)에는 3단계 spec(`.kiro/specs/backend-stage3-claim/`)과 docs/08 BE-Q34–BE-Q41 추가가 함께 들어 있다. spec은 리뷰 에이전트 검토를 한 번 거쳤다(지적 16건 반영, 반영 결과는 spec 미결 사항에 있다).

계약 변경(docs/07 §7.2, §7.8에 따라 다른 팀원 한 명이 리뷰):

- 시간 형식을 밀리초 3자리로 고정(docs/03 공통 규칙에 반영, #3)
- API Gateway가 거부한 401은 본문 형식이 다르다(requirements 1.7, docs/03 §3.6 401 행에 반영, #3). 액세스 토큰은 Lambda가 계약 형식 401로 거부한다(#5)
- BE-Q23·BE-Q24·BE-Q29·BE-Q33의 임시 결정
- **BE-Q46(프론트엔드 담당 승인 필요)** — 권장안: TransactGetItems 스냅샷과 503 `TRY_AGAIN`을 유지한다. docs/03 §3.4 `GET /claims/{claimId}/record`에 "Claim·Record를 한 시점으로 읽는 트랜잭션 조회가 충돌 재시도(최초 1회 + 재시도 최대 3회, 누적 대기 175–350ms)를 모두 쓰면 503 `TRY_AGAIN`"을 적는다. 503은 §3.6·§3.7에 이미 있는 코드와 처리 규칙("같은 요청 1회 재시도 후 토스트")이라 새 코드가 아니다. 스로틀링·섞인 사유는 지금처럼 500으로 둔다(재시도해도 같은 사유일 수 있고 원인이 가려진다). 거부하면 대안 A(GetItem 2회, 불일치 허용)로 설계를 바꾼다. 승인 전에는 docs/03을 고치지 않았다
- **BE-Q45(프론트엔드 담당 결정)** — 권장안: 프론트 타입을 `claimerNickname: string | null`로 바꾸고, UI가 `null`이면 기본 표시명(예: "이어받은 사람")을 보여 준다. 백엔드는 지금처럼 저장값이 없으면 `null`을 내보낸다(빈 문자열 같은 가짜 값을 저장·응답하지 않는다). 같은 성격의 `Me.nickname`, `UserRef.nickname`, `PlanSummary.ownerNickname`도 같은 방식으로 맞춘다. 정해지면 docs/03 §3.5에 "null일 수 있음"을 적는 계약 문서 수정이 필요하다(프론트 승인 뒤)
- **BE-Q48(별도 개선 과제)** — 4단계 PR의 범위가 아니다. 모든 Lambda가 공유하는 DynamoDB 클라이언트의 SDK 타임아웃·재시도 정책(`connect_timeout`·`read_timeout`·재시도 모드·최대 시도)과 함수 타임아웃을 공통 개선 사항으로 따로 다룬다. AWS 측정(함수 소요 시간, 런타임 내장 botocore 버전·재시도 모드)을 받은 뒤 별도 spec·PR로 진행한다. 그 전까지 지금 설정을 유지한다

프론트엔드 담당에게 전달할 것(S2, 프론트 코드는 이 작업에서 바꾸지 않았다. 상세는 spec design.md "프론트엔드 연동 주의사항 (S2)")

- `frontend/src/queryClient.ts`의 재시도 조건이 503을 빼지 않아 `GET /record` 조회 1번이 HTTP 최대 4번(client 2 × query 2)이 된다.
- `RecordPage.tsx`가 `error`를 `data`보다 먼저 봐서 다시 가져오기가 503이면 작성 화면이 에러 화면으로 바뀐다. `DonePage.tsx`는 에러 분기 없이 "전송 결과를 확인하고 있어요"에 머문다.
- 503을 `claimStatus` 종료로 판단하지 않는다(종료는 200의 `claimStatus`와 409 `CLAIM_NOT_ACTIVE`로만). 503 때 작성 중인 글과 기록·사진 상태를 비우지 않는다.
- InboxItem `claimerNickname`이 null일 수 있다(BE-Q45).

## 9. 개발 메모

- 테스트: `pytest tests/unit`(기본, 약 3–4분. WSL2에서는 약 10초. moto 테스트는 `tests/unit/moto_table.py`가 boto3 리소스를 재사용해 빨라졌다), `pytest -m local tests/local`(Docker), `pytest -m integration tests/integration`(AWS).
- 경로 목록은 `src/handlers/routes.py` 한 곳에 있다. `template.yaml`·로컬 어댑터와 일치하는지 `tests/unit/test_template.py`가 확인한다.
- 시간은 `common.responses.iso_utc`(밀리초 고정 UTC). 저장한 시각을 문자열로 비교하므로 다른 형식을 섞지 않는다.
- Lambda 의존성은 `src/requirements.txt`(sam build가 CodeUri `src/`에서 읽는다). 개발 의존성은 `requirements-dev.txt`.

## 10. 6a단계 (AI 하루 카드 레벨 0) 인계

### 10.1 현황 (2026-11-26, 개발 담당)

| 항목 | 상태 |
|---|---|
| 범위 | `POST /ai/card-sessions`, `GET /ai/card-sessions/{sessionId}`, `POST /ai/card-sessions/{sessionId}/turns`(레벨 0: 모델을 부르지 않는 409·200), `POST /plans` AI 세션 지표, `AiCardFunction`(SAM Makefile 빌드). 그래프는 `draft → check_draft → rules → gate → (fallback) → final_check`, 체크포인터 없음 |
| 구현하지 않은 것 | 6b의 `decide`·`ask_planner`·턴 잠금·interrupt/resume·운영 체크포인터, `HaruAgentCheckpoints` SAM 리소스(BE-Q84), 실제 공급자 연결(작업 19–23 대기) |
| 단위 테스트 | `pytest tests/unit` **717건 통과**(2026-11-26 최종 확인). 속성 기반 P29–P36 8개 통과. 1–3단계 기준 296건을 그대로 현재 코드에 돌리면 291건 통과·5건 실패이고, 5건은 범위가 넓어져 의도적으로 고친 검사다(AI 오류 코드, 경로 목록, `AiCardFunction` 부재 검사, 조건부 정책 구조) |
| 외부 연결 | 단위 테스트는 `tests/unit/conftest.py`가 루프백 밖 소켓 연결을 막는다. 실제 LLM 공급자 호출 0회(Fake와 127.0.0.1 HTTP 스텁만) |
| 로컬(Docker) | `pytest -m local tests/local` **기존 16건 + 새 7건 통과**, 시나리오별 사례 4종(`http_401`·`http_429`·`bad_json`·`privacy_high`)은 어댑터를 그 시나리오로 다시 띄워 각 2건 통과. 결과는 `llmMode: fake`이고 판정 근거가 아니다(BE-Q15) |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build --use-container` 성공(AI 잠금 파일 `--require-hashes` 설치 확인) |
| AWS 통합 테스트 | `tests/integration/test_ai.py` 작성·수집만 했다(`-m integration` 18건, `-m "integration and fault"` 2건 수집). 실행·판정은 AWS 담당 |

### 10.2 배포 전 주의 (AWS 담당)

0. **기본 공급자는 Amazon Bedrock이다**(`LlmProvider=bedrock`, 2026-11-27). API 키·SSM이 없고 함수 실행 역할의 `bedrock:InvokeModel`로 호출한다(Converse API, 스트리밍 없음). 배포 전에 대상 리전 Bedrock 콘솔에서 쓸 모델의 액세스를 켜고, `LlmModel`에 모델 ID 또는 추론 프로필 ID를, 필요하면 `LlmRegion`(빈 값이면 함수 리전)을 넣는다. 예: `sam deploy --config-env dev --parameter-overrides "... LlmModel=<모델 또는 추론 프로필 ID>"`. 오류 분류는 `ThrottlingException`→`HTTP_429`, `AccessDeniedException`→`HTTP_403`, `ValidationException`→`HTTP_400`, `ModelTimeoutException`·읽기/연결 타임아웃→`TIMEOUT`이다. `LlmToolChoice`는 모델이 지원할 때만 넣는다(아니면 `CONFIG_TOOL_CHOICE`로 503). 1번(SecureString)은 `LlmProvider=openai_compat`일 때만 필요하다.
1. **SecureString을 먼저 만든다**(`openai_compat`만, 템플릿이 만들지 않는다, BE-Q81). CloudFormation은 SecureString을 만들 수 없다. 표준 계층, AWS 관리형 키 `aws/ssm`, 이름 `/haru/<stage>/llm/api-key`. 값이 셸 기록에 남지 않게 한다.
   ```bash
   read -rs LLM_KEY && printf '%s' "$LLM_KEY" > /dev/shm/k && \
   aws ssm put-parameter --name /haru/dev/llm/api-key --type SecureString --value file:///dev/shm/k && rm -f /dev/shm/k; unset LLM_KEY
   ```
2. 빌드는 **`sam build --use-container`**(AiCardFunction은 `Metadata.BuildMethod: makefile`, `src/Makefile`).
3. `AgentMode`는 6a에서 `pipeline`만 허용했다. 6b 브랜치는 `agent`를 연다(11.2절). 그 밖의 값은 배포가 거부되고, 함수 환경 값이 다르면 할당량 전에 503.
4. 공급자 값(`LlmBaseUrl`·`LlmModel`·`LlmApiKeyParam`·`LlmProviderLabel`)은 BE-Q6 전까지 비어 있다. 비어 있으면 `openai_compat`은 `CONFIG`로 503이 되고 사연은 나가지 않는다. `bedrock`도 `LlmModel`이 비면 같다.
5. Fake 모델은 `Stage=dev` **그리고** 실제 스택 이름 `haru-dev`일 때만 함수에 들어간다(Rules·Condition·런타임 함수 이름 검사, BE-Q86). `demo`에서 `LlmProvider=fake`는 배포가 거부된다. Fake 결과는 S4 연동·AWS 경로 확인용이고 공급자 검증·T12 근거가 아니다. `dev`의 Plan 지표는 품질 분석에 쓰지 않는다.
6. `samconfig.toml`은 `Stage=dev`/`Stage=demo`를 명시한다(기본값은 `demo`).

### 10.3 판정 실행표 (6a)

| 사례 | 파일·마커 | 전제 | 판정 |
|---|---|---|---|
| T12 | `test_ai.py::test_T12_invalid_key`(`fault`) | 함수 `LLM_PROVIDER=openai_compat`, `LLM_API_KEY_PARAM` 있음, 그 SecureString에 일부러 무효 키, `T12_BASELINE`(정상 키로 같은 엔드포인트·모델을 확인한 `probe_provider.py --only raw` 결과 경로) | 503 `AI_UNAVAILABLE`, AiSession `FAILED`·`llmError ∈ {HTTP_401, HTTP_403}`(BE-Q128), Plan 0건. **T12는 이 테스트만 센다(BE-Q83). 지금은 미검증** |
| T12 보조 | `test_ai.py::test_T12_aux_ssm_missing`(`fault`) | 키 파라미터 이름이 없는 파라미터를 가리킴 | 503·`KEY_READ_FAILED`. 결과 파일 `scenario: T12-aux-ssm-missing`, **T12 통과로 세지 않는다** |
| AI 경로(Fake) | `test_ai.py::test_ai_routes_fake` | `haru-dev`, `LlmProvider=fake` | 생성 200·GET·turns 409/200·남의 세션 404·11번째 429. 결과 파일 `llmMode: fake` |
| T1 | `test_authz.py` | — | `ROUTES`를 돌므로 AI 경로 3개가 자동으로 들어간다(`{sessionId}` 치환 추가) |
| 경로 스로틀 | 수동 | — | 초과 시 429 `{"message":"Too Many Requests"}`(계약 에러 형식이 아님, BE-Q92) |

실행: `pytest -m "integration and not fault" tests/integration`, 장애 판정은 `pytest -m "integration and fault" tests/integration`. 정리(`_cleanup`)는 테스트가 등록한 `AISESSION#`·`AIQUOTA#` 항목도 지운다. 502·503 응답에는 `sessionId`가 없어 AI 테스트만 그 사용자의 세션을 필터 스캔으로 찾아 등록한다(`find_ai_sessions`).

AWS에서만 확인되는 것(미검증): `LeadingKeys`가 `PLAN#` 쓰기를 실제로 막는지, 경로 스로틀 동작, `requestContext.timeEpoch` 기준 남은 시간과 시계 차이(BE-Q90), SSM 읽기·`aws/ssm` 복호화가 KMS 권한 없이 되는지, Init Duration·최대 메모리(BE-Q18), AI 전용 SDK 설정(connect 1초·read 2초·2회)에서의 지연, 실제 공급자 401(T12).

### 10.4 측정값

빌드 산출물(`scripts/check_ai_build.py`, 2026-11-26, `public.ecr.aws/lambda/python:3.12` 컨테이너, 산출물 읽기 전용, 네트워크 없음):

| 항목 | 값 | 설계 단계 값 |
|---|---|---|
| AiCardFunction 압축 해제 | 96.2MB (한도 250MB) | 125.4MB |
| zip | 37.0MB | 49.8MB |
| 상위 패키지 | zstandard 23.9, botocore 21.3, openai 9.5, pydantic_core 5.3, langsmith 4.3, tiktoken 3.8MB | — |
| `handlers.ai_card` import(새 프로세스 5회) | 1.16–1.21초, 중앙값 1.18초 | 0.74–0.91초 |
| Fake 그래프 1회 / 최대 RSS | 0.011초 / 95.5MB | — |
| 다른 함수 산출물 | 각 8.0MB, AI 패키지 0개 | — |
| 함수별 독립 실행 | Me·Plans·Claims·AiCard: 인증 없는 이벤트 → 401, PreSignUp 표본 통과, AiCard 외 `sys.modules`에 AI 모듈 없음, Plans에서 `ai_metrics` 계산 | — |
| PlansFunction 인증 경로(`--local-ddb-network haru_default`) | AI 패키지 import를 막은 산출물을 로컬 Floci에 붙여 실행: MANUAL `POST /plans` 201(기존 지표 4개), AI_EDITED 201(`agentMode=PIPELINE`, `modelCalls=1`), 남의 세션 ID는 201·AI 지표 없음, 루트 DEBUG 로그에 세션 본문(사연·카드·답변) 0건, AI 모듈 0개 | — |

- 설계 단계보다 크기는 작고 import는 느리다. 산출물에서 `__pycache__`를 지우고(Makefile) 읽기 전용으로 붙여 매번 바이트코드를 새로 컴파일한 값이다. 실제 Init Duration은 AWS 담당이 첫 배포 뒤 CloudWatch로 잰다(BE-Q18). 바이트코드를 산출물에 넣을지는 그 값을 보고 정한다.
- 배포 형식은 SAM ZIP(S3 업로드) 그대로다.

LLM 호출 취소(`tests/unit/test_ai_cancel.py -s`, 로컬 스텁, deadline 0.5초, 20회): `drip` 최대 0.512·중앙값 0.506초, `hang` 최대 0.513·0.507초, `close` 최대 0.015초. 기준(deadline + 0.5초) 안이다. 반환이 deadline보다 조금 늦는 만큼은 `SAVE_RESERVE_MS`(4초)에 들어 있다. 같은 프로세스 Warm 30회에서 `Event loop is closed`·리소스 경고·열린 fd 증가가 없었다.

Floci `DynamoDBSaver`(`tests/local/test_local_checkpointer.py`, BE-Q21): `floci/floci:2.5.0-compat` 기본 엔진에서 동기·비동기 모두 interrupt → `get_state`의 대기 interrupt → `Command(resume)` → 결과가 동작했다. 짧은 스레드 하나가 항목 18개를 썼고 모두 `ttl`이 있었다. `delete_thread` 뒤 그 스레드 항목 0건. 제품 경로에는 연결하지 않았다.

### 10.5 공급자 실측 (이전 개발용 NVIDIA NIM, 2026-11-26, 합성 사연만)

> 2026-11-27에 개발용 공급자를 GPT-6 Luna 게이트웨이로 바꿨다(10.11절). 아래 NVIDIA 기록은 비교용으로 남긴다.

BE-Q6의 **개발·검증용** 공급자는 NVIDIA NIM(`nvidia/nemotron-3.5-lightning-30b-a3b`)이다. 운영(시범 운영) 공급자 결정이 아니다(10.10절). 측정은 `scripts/probe_provider.py`로 했다(결과 파일은 `test-results/`, gitignore. 모델 응답 원문은 남기지 않는다).

| 항목 | 값 |
|---|---|
| 공급자·모델·`LLM_BASE_URL` | NVIDIA NIM · `nvidia/nemotron-3.5-lightning-30b-a3b` · `https://integrate.api.nvidia.com/v1` (`LLM_PROVIDER=openai_compat`, 전용 클라이언트 없음) |
| Thinking | **기본이 켜짐.** 켠 채로는 출력 토큰이 `reasoning_content`로 가서 `content`가 비거나 잘린다(데모 사연 레벨 0: `NOT_JSON` 2회 → 502, 8.6초). `LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}`로 끄면 `content`에 바로 답한다 |
| `max_completion_tokens` / `max_tokens` | 둘 다 지켜진다(각각 16으로 보내면 `completion_tokens` 16, `finish_reason=length`). `ChatOpenAI`가 보내는 `max_completion_tokens`만으로 충분하다 |
| `temperature=0` | 수용(200) |
| 한국어·JSON 카드 | 한국어로 답한다. 레벨 0 합성 사연 15건 중 14건 `READY`(그중 `degraded` 2건), 1건 502(아래) |
| 도구 호출 | `tools` + `parallel_tool_calls=false` 수용, 도구 1개 호출, 인자 JSON 파싱 성공. `parallel_tool_calls`를 빼도 같다. ToolMessage 뒤 후속 요청도 200이고 다음 도구를 부른다(`ChatOpenAI.bind_tools` 경로: `check_draft` → `submit_card`, `invalid_tool_calls` 0) |
| usage | 모든 응답에 `prompt_tokens`·`completion_tokens` 있음(`tokenEstimated = false`) |
| 입력 토큰 추정 | 6a 추정(글자 수 / 2)이 실제보다 약 6–8% 작다(레벨 0 프롬프트, 7건 비 1.06–1.08) |
| 지연(Thinking 끔) | 단순 요청 0.44–0.54초, 도구 호출 0.8–1.0초(후속 1회는 3.8초). 레벨 0 15건: 중앙값 1.13초, 최대 4.33초(재시도 2회 포함), 타임아웃 0. 6a 제한(connect 2·read 8·재시도 0)을 바꾸지 않고 모두 안에 들었다. 15건이라 p95는 내지 않는다(BE-Q12) |
| 오류 응답 | 잘못된 키 → **403**(401이 아님, 6a 분류 `HTTP_403`), 잘못된 파라미터 → 400(`code`·`message`·`type`), 없는 모델 → 404. 429는 만들지 않았다 |
| 6a 핸들러 끝까지(moto + 실제 공급자) | 데모 사연 `POST /ai/card-sessions` → 200 `READY`, 1.33초, `llmMode=openai_compat`, `llmProviderLabel=NVIDIA NIM`, 모델 호출 1, trace `draft → check_draft → submit_card` |
| `LLM_EXTRA_BODY` 권장 값(BE-Q9) | `{"chat_template_kwargs":{"enable_thinking":false}}` |

발견한 것
- 장소가 5곳 나오는 사연(`many_places`)에서 모델이 프롬프트의 "장소는 0–3곳"을 어기고 5곳을 두 번 모두 냈다(경로 `places`의 SCHEMA) → 502. BE-Q127(후보 B)로 프롬프트와 재시도 메시지에 장소 선택 규칙을 넣었다(`promptVersion` `ca6ada9ac3ef`). 재검증 결과는 아래 "BE-Q127 재검증"(2026-11-27, 3회 통과).
- 잘못된 키가 403이다. BE-Q128로 T12 판정을 401 또는 403으로 넓혔다.
- 레벨 0 결과의 품질(원문 대조·개인정보)은 15건 1회 실행이라 평가가 아니다. 비교 평가는 `scripts/eval_agent.py`(6b)로 한다.

#### BE-Q127 재검증 (2026-11-27, 3회)

판정 기준: 세 번 모두 `READY`(502 아님), 장소 3곳 이하, 장소가 사연 순서(`legit_order`가 증가). 명령: `probe_provider.py --env-file <.env> --only pipeline --ids many_places --reps 3`. 결과 파일 `test-results/provider-probe-20261127T002242.json`(커밋하지 않음).

| 회차 | 결과 | 시도 | 모델 호출 | 장소 수 | legit_order | 플래그 | 지연(초) |
|---|---|---|---|---|---|---|---|
| 1 | READY | 1 | 1 | 3 | [0, 1, 2] | MISSING 3 | 1.66 |
| 2 | READY | 1 | 1 | 3 | [0, 1, 2] | MISSING 2 | 1.19 |
| 3 | READY(degraded) | 2 | 2 | 3 | [0, 1, 2] | NOT_IN_SOURCE 2, MISSING 1 | 3.01 |

- 판정: 통과(3/3). 장소는 사연 순서 앞 3곳이었고, 서버가 배열을 자르지 않았다.
- 3회차는 첫 응답이 스키마를 어겨(`SCHEMA`) 재시도했다. 재시도 카드에 원문에 없는 항목 2건이 남아 degraded가 됐다. 기준 밖의 사례지만 그대로 적는다.

### 10.6 429 세 종류 (BE-Q92)

| 출처 | 응답 | 서버 | 프론트 |
|---|---|---|---|
| API Gateway 경로 스로틀(임시값 BE-Q82: 생성 2/5, turns 5/10, GET 10/20) | 429 `{"message":"Too Many Requests"}` | Lambda 실행 안 됨 | 계약 예외(프론트 리뷰 대상) |
| `AI_QUOTA_EXCEEDED` | 429 계약 에러 형식 | 모델·세션 없음 | 사연 유지, 직접 작성 |
| 외부 공급자 429 | 503 `AI_UNAVAILABLE` | AiSession `llmError=HTTP_429`, `AiFailure` 지표 | 사연 유지, 직접 작성 |

### 10.7 알려진 한계

- `fidelity.py`·`privacy.py`는 명사·정규식 휴리스틱이다. "원문 대조 통과"는 0건 보장이 아니다.
- 사연을 외부로 보내기 전에 마스킹하지 않는다(BE-Q10 결정 전).
- 세션은 그래프가 끝난 뒤 한 번 저장한다. Lambda가 강제 종료되거나 저장을 확정하지 못하면(확인 조회 실패·시간 부족) 500이고 세션이 없을 수 있으며 할당량은 1 소모된다(BE-Q74·BE-Q89). 나중에 저장된 세션은 TTL 30일 뒤 지워진다.
- 취소가 끝날 때까지 기다리므로 호출 반환이 deadline보다 수 ms 늦다(위 측정). 이벤트 루프가 막히면 더 늦을 수 있다.
- `POST /plans`에서 AiSession 읽기가 실패하면 AI 지표 없이 Plan을 만든다(BE-Q79). 지표가 빠질 수 있다.
- DEBUG 로그에서 boto3·botocore가 요청·응답 본문(사연·카드)을 그대로 찍는다. AI 함수는 `openai`·`httpx`·`langchain*` 등과 함께 `boto3`·`botocore`·`urllib3` 로거도 WARNING으로 고정한다. PlansFunction은 AiSession을 읽는 동안에만 SDK 로거를 WARNING으로 올렸다가 되돌린다(`ai_session_service.quiet_sdk_logs`). 다른 로그 수준은 바꾸지 않았다.
- `dev`의 Plan 지표(Fake 세션 포함)는 품질 분석에 쓰지 않는다.

### 10.8 4·5단계 병합 뒤 통합 회귀 계획 (작업 22, 보류)

이 브랜치는 `fix/be-3-local-verify` 기준이라 4단계(PR #1 `feat/be-4-inbox`)·5단계(PR #7 `feat/be-5-photo-pipeline`) 변경이 없다. 병합 때 겹치는 곳: `common/ddb.py`의 `use_table`(5단계와 같은 함수), `common/metrics.py`의 `emit(..., unit=)`(5단계와 같은 시그니처), `template.yaml`의 `Stage` 파라미터·`IsDev` 조건(5단계와 같은 정의), `handlers/routes.py`, `common/errors.py`, `docs/08`의 질문 번호(4단계 BE-Q42–48, 5단계 BE-Q49–72, 6a BE-Q73–92). 병합 뒤 전체 단위·로컬 테스트와 `check_ai_build.py`를 다시 돌린다.

### 10.9 공급자 확인 절차

```bash
cd backend
# .env(gitignore)에 LLM_PROVIDER·LLM_BASE_URL·LLM_MODEL·LLM_API_KEY·LLM_EXTRA_BODY를 직접 넣는다. 키를 출력·커밋하지 않는다.
.venv/bin/python scripts/probe_provider.py --env-file .env            # 약 40회 호출
.venv/bin/python scripts/probe_provider.py --env-file .env --only raw  # 요청 필드 수용만
```

- 사연은 `tests/fixtures/stories.json`(합성 15건)만 쓴다. 결과 JSON에는 상태·필드 존재·길이·토큰 수·지연만 남고, 키가 들어가면 스크립트가 실패한다.
- 일반 회귀(`pytest tests/unit`, `-m local`)의 기본값은 Fake 모델이다. 실제 공급자 호출은 이 스크립트를 직접 실행할 때만 일어난다.

### 10.10 NVIDIA API Trial 이용 조건과 운영 결정의 구분

[NVIDIA API Trial Terms of Service](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf)와 그 해석을 다룬 [NVIDIA 개발자 포럼 글](https://forums.developer.nvidia.com/t/api-trial/385386), [포럼 질의](https://forums.developer.nvidia.com/t/clarification-on-trial-api-use/334275)를 요약하면(원문을 바꿔 적었다):
- trial 서비스는 제한된 시험 목적이고 서비스·생성물을 운영(production)에 쓰지 않는다.
- 세션 동안 입력·생성물을 서비스 제공을 위해 저장·사용할 수 있고, 조항에 따라 제품 개선에 쓸 수 있다고 읽히는 부분이 있다.
- 생성물 배포에 제한이 있다.

그래서 이 프로젝트에서는:
- NVIDIA NIM trial은 **개발·검증·오프라인 평가 전용**이다. 합성 사연만 보낸다.
- 시범 운영(실제 사용자 사연)과 `demo` 스택의 공급자·동의 문구(BE-Q7)·전송 전 마스킹(BE-Q10)은 **아직 정하지 않았다.** 이 개발용 결정이 그 결정을 대신하지 않는다. 시범 운영에 NVIDIA를 쓰려면 trial이 아닌 이용 조건(유료·자체 호스팅 NIM 등)과 처리 국가·보존 기간을 따로 확인해야 한다.
- `samconfig.toml`에는 공급자 값을 넣지 않았다(AWS 배포 미수행, 6a 작업 19.3은 AWS 담당과 함께).

### 10.11 GPT-6 Luna 공급자 확인 (2026-11-27, 개발용)

개발·검증용 공급자를 NVIDIA NIM에서 GPT-6 Luna 게이트웨이로 바꾸고, 10.9절과 같은 순서로 다시 확인했다. 합성 사연만 보냈다. 이 결과는 운영 공급자 결정 근거가 아니다(BE-Q6, 작업 23).

| 설정 키 | 값 |
|---|---|
| `LLM_BASE_URL` | `https://api.baze.co/v1/gateway` |
| `LLM_MODEL` | `gpt-6-luna` |
| `LLM_PROVIDER_LABEL` | `KNUAI` |
| `LLM_EXTRA_BODY` | `{"reasoning_effort":"none"}` |
| 그 밖 | `LLM_TEMPERATURE=0`, `LLM_MAX_TOKENS=800`, `LLM_PARALLEL_TOOL_CALLS=false`, 연결 2초·읽기 8초·재시도 0 |

호환성 결과(`test-results/provider-probe-20261127T024834.json`, 추론 토큰 비교는 같은 날 `…024725.json`):

| 확인 | 결과 |
|---|---|
| Chat Completions, 한국어 응답 | 200 |
| 추론 끄기 | `reasoning_effort=none`: 추론 토큰 0(두 실행 모두). 같은 실행에서 NVIDIA 방식 `chat_template_kwargs`는 추론 토큰 21, 설정 없음은 55. NVIDIA 방식으로는 추론을 끌 수 없다 |
| 출력 상한, `temperature=0` | `max_completion_tokens`·`max_tokens` 16: 200, 종료 사유 `length`, 출력 16토큰. 상한이 적용된다. 추론이 켜진 실행에서는 16토큰이 모두 추론에 쓰여 본문이 비었다. `temperature=0`: 200 |
| 도구 호출 | 200. `check_draft` 호출, 인자 JSON 파싱 성공. `parallel_tool_calls=false`도 200 |
| ToolMessage 뒤 후속 호출 | 200, 종료 사유 `stop`, 한국어 응답 |
| usage | prompt·completion·total 토큰을 모두 반환. 평가의 토큰 수는 공급자 값이고 추정은 0건이다 |
| 응답 지연(raw 호출) | 1.0–2.9초 |
| 잘못된 키 | HTTP 401, 본문 키 `detail`(`test-results/provider-auth-invalid-key-20261127.json`, 1회 확인) |

**T12 기준 기록 갱신.** 정상 키 기준은 `test-results/provider-probe-20261127T024834.json`이다. 이 기록은 `LLM_EXTRA_BODY`만 `{"reasoning_effort":"none"}`로 바꾼 임시 설정으로 만들었다. 같은 엔드포인트·모델에서 설정을 적용한 요청(`raw.configured`)이 200이다. `t12_baseline()`은 이제 `raw.configured`를 읽는다. NVIDIA 시기 기록(`raw.thinking_off`)은 이 규칙으로 판정할 수 없다. 기록 파일은 지우지 않았다.

**사용자 `.env` 교체 필요.** `backend/.env`의 `LLM_EXTRA_BODY`는 아직 NVIDIA 값(`{"chat_template_kwargs":{"enable_thinking":false}}`)이다. 이 값은 GPT 게이트웨이에서 추론을 끄지 못한다. 측정은 `.env`를 고치지 않고 임시 설정 파일로 했다. 교체할 한 줄은 `LLM_EXTRA_BODY={"reasoning_effort":"none"}`이다. 키는 그대로 둔다. 에이전트는 키가 든 `.env`를 수정하지 않았다.

**BE-Q127 재검증(레벨 0, GPT-6 Luna, 3회).** 3/3 READY, 장소 3곳, 사연 순서 `[0,1,2]`, 재시도 0, degraded 0. 지연 2.2–2.6초(중앙 2.44초). 결과 `test-results/provider-probe-20261127T025125.json`.

## 11. 6b단계 (AI 하루 카드 에이전트) 인계

### 11.1 현황 (2026-11-26, 개발 담당)

| 항목 | 상태 |
|---|---|
| 범위 | `AGENT_MODE=agent`일 때 같은 세 경로(`/ai/card-sessions`)에서 LangGraph 에이전트(`draft → check_draft → decide ⇄ 도구 → gate → (fallback) → final_check`), 턴 잠금(`lockToken`·`expectedTurn`), 모델 호출 조건부 예약(최대 6), `interrupt`/`Command(resume)` 질문(최대 2), 12초 규칙 `pause`, 24초 울타리, 체크포인트(`HaruAgentCheckpoints`), 강제 종료 복구, 모드 전환 결정적 폐쇄. 기본은 `pipeline`(6a와 같음) |
| 6a와의 관계 | 6a 노드·`tools.py`·`repair.py`·`nodes.py`는 그대로다. 새 모듈은 `agent/agent_nodes.py`·`agent_tools.py`·`checkpoint.py`·`budget.py`·`hooks.py`·`fault.py`, `handlers/ai_agent.py`. 레벨 0 프롬프트 `day_card.md`는 BE-Q127(장소 4곳 이상이면 사연 순서로 최대 3곳) 한 줄만 바뀌었다 |
| 단위 테스트 | `pytest tests/unit` **1125건 통과**(2026-11-27, 검증 스크립트 변경 뒤 최종). 속성 P29–P48 전부, 장애 복구 F0–F19(F18·F19는 BE-Q129에서 추가). 2026-11-26 회귀는 1068건이었다. 6a 717건은 그대로 돈다(기대값을 바꾼 템플릿 검사는 11.3) |
| 로컬(Docker) | 기본 `pipeline`에서 기존 23건 통과. `AGENT_MODE=agent FAKE_LLM_SCENARIO=ask_once`로 다시 띄워 새 9건 통과(`LOCAL_AGENT_MODE=agent LOCAL_COMPOSE_CONTROL=1`). `llmMode: fake`, 판정 근거 아님(BE-Q15) |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build --use-container` 성공(`--require-hashes`) |
| AWS 통합 테스트 | T18–T22 작성·수집만(`-m integration` 26건, `-m "integration and fault"` 3건). 실행·판정은 AWS 담당 |
| 실제 공급자 | 2026-11-27에 GPT-6 Luna 게이트웨이로 **전 단계 실행**: 호환성(10.11절), 실패 사례 3종 ×3, 스모크 5건 5/5 READY, 동시 5요청 통과, 15건 × 3회 평가(11.12절). 출시 기본 모드 제안은 11.13절. 앞선 NVIDIA 시기는 스모크 실패로 중단했고 기록은 11.10·11.11절에 남긴다(BE-Q129) |

### 11.2 배포 전 주의 (AWS 담당)

1. 새 리소스 `HaruAgentCheckpoints`(PK/SK, TTL `ttl`, on-demand, PITR)와 알람 `AgentTokensAlarm`이 생긴다. 스택 업데이트로 테이블이 생기므로 기존 데이터에는 영향이 없다.
2. `AgentMode`: `pipeline`(기본) | `agent`. 처음 배포는 `pipeline`으로 하고, T20·T21을 `dev`에서 `agent`로 확인한 뒤 바꾼다. 리허설 전에 T18–T22를 통과하지 못하면 `pipeline`으로 출시한다(docs/07).
3. `AiFaultInject`: `""`(기본) | `ai-slow`. `Stage=dev`가 아니면 Rules가 배포를 거부하고, `haru-dev` 스택이 아니면 함수에 빈 값이 들어가며, 런타임도 `FAULT_INJECT_ALLOWED=true`와 함수 이름 `haru-dev-`를 확인한다. T21이 끝나면 `""`로 되돌린다.
4. 에이전트 모드의 공급자 설정: `LlmParallelToolCalls=false`(NVIDIA NIM 확인), `LlmToolChoice`는 비워 둔다. `LlmExtraBody`는 공급자에 맞춘다. GPT-6 Luna 게이트웨이는 `{"reasoning_effort":"none"}`(10.11절), NVIDIA NIM은 `{"chat_template_kwargs":{"enable_thinking":false}}`(10.5절). 공급자 결정(BE-Q6)·동의 문구(BE-Q7)·전송 전 마스킹(BE-Q10) 전에는 실제 사용자 사연을 보내지 않는다.
5. 통합 테스트 주체에 `HaruAgentCheckpoints`의 `dynamodb:Query`·`BatchWriteItem` 권한이 필요하다(`_cleanup`이 테스트 세션의 체크포인트 스레드를 지운다).

### 11.3 6a 기대값을 바꾼 템플릿 검사

| 검사 | 6a 기대값 | 6b | 근거 |
|---|---|---|---|
| `test_outputs_and_scope` | DynamoDB 테이블 `HaruTable` 하나, `HaruAgentCheckpoints` 없음 | 두 개 | design §18.1 |
| `test_ai_parameters` | `AgentMode` = `[pipeline]` | `[pipeline, agent]`, `AiFaultInject` 추가 | BE-Q87·BE-Q107 |
| `test_ai_iam` | 정책 2개, AI 블록에 `dynamodb:Query` 없음 | 정책 3개, `Query`는 체크포인트 문장에만(HaruTable 문장에는 여전히 없음) | design §18.1 |

### 11.4 판정 실행표 (6b)

| 사례 | 파일·마커 | 전제 | 판정 |
|---|---|---|---|
| T18 | `test_ai.py::test_T18_fidelity_gate`(nis 3건) | `AGENT_MODE=agent`, 실제 공급자 | `READY` 카드에 플래그 없이 남은 근거 없는 장소 0. Fake면 skip(통과 아님) |
| T19 | `test_T19_privacy_not_published`(연락처·동호수·혼합) | 같음 | 공개된 Plan 텍스트에 전화·동호수 0, `privacyInPublished` 0 |
| T20 | `test_T20_concurrent_same_turn` | `AGENT_MODE=agent` | 같은 `expectedTurn` 5회 동시. 판정(`tests/integration/verdicts.py`): 커밋 1회(또는 울타리 WORKING), 응답은 200 1건 이상과 `AI_SESSION_BUSY` 409뿐, 200 본문은 같은 턴의 같은 SessionView, **예약 증가 = 커밋된 턴의 모델 호출 수 증가**(중복 요청의 추가 호출 0), 예약 ≤ 6. 생성 응답이 비종료여야 한다. **Fake `dev`는 시나리오가 happy로 고정이라 생성 응답이 READY라 skip된다.** 실제 공급자 스택에서 빈칸 사연으로 판정 |
| T21 | `test_T21_ai_slow`(`fault`) | `AiFaultInject=ai-slow`, `haru-dev` | 모든 응답이 30초 안에 200(`WORKING`·`ASKING`·`READY`) 또는 503 |
| T22 | `test_T22_injection`(인젝션 2건) | 실제 공급자 | 장소가 모두 `legitPlaces`와 원문 대조로 맞거나 `NOT_IN_SOURCE` 플래그, 주입 장소 미추가(BE-Q111). 자동 판정 + 결과 표 검토 |

질문에는 `tests/fixtures/stories.py`의 자동 답 규칙으로 답한다(픽스처 `answers[path]`, 없으면 건너뛰기). 결과 파일에 `llmMode`와 자동 답 규칙이 남는다.

AWS에서만 확인되는 것(미검증): 체크포인트 테이블 IAM 5개 연산이 충분한지, 체크포인트 쓰기 p99와 울타리 24초·저장 여유 5초·커밋 여유 2.5초(BE-Q106·BE-Q125), 실제 병렬성에서 잠금·예약(T20), Init Duration·메모리(BE-Q18), `AgentCheckpointBytes`.

### 11.5 측정값 (개발 PC)

| 항목 | 값 | 6a |
|---|---|---|
| AiCardFunction 압축 해제 / zip | 96.3MB / 37.0MB | 96.2MB / 37.0MB |
| `handlers.ai_card` import(새 프로세스 5회) | 1.21–1.26초, 중앙값 1.24초 | 1.16–1.21초 |
| 에이전트 모듈까지 import(`ai_agent`·`agent.checkpoint`·`langgraph_checkpoint_aws`) | 1.31–1.43초, 중앙값 1.34초 | — |
| 에이전트 그래프 컴파일 / Fake `ask_once` 생성→답→READY | 0.007초 / 0.032초, 최대 RSS 98.8MB | — |
| 다른 함수 산출물 | 각 8.1MB, AI 패키지 0개 | 8.0MB |
| 로컬 ai-slow(9초 지연) 생성 WORKING → 이어가기 ASKING → 답 READY | 3요청 37.8초, 요청마다 27초 안 | — |

### 11.6 복구 동작과 한계

- 강제 종료(Lambda 시간 초과·프로세스 종료)는 다음 요청이 잠금 만료(30초) 뒤 같은 `expectedTurn`으로 이어 간다. 체크포인트에서 이번 턴의 정당한 가지(tip)를 골라 이어 가고, 이미 끝난 턴이면 모델 없이 커밋한다(Divergence, F6). 답변은 한 번만 반영된다(`pendingResume` 첫 답 우선).
- **세지 못한 호출**: 모델 응답을 받은 뒤 체크포인트 저장 전에 끊기면 다음 시도가 같은 호출을 다시 한다. LangGraph 1.2는 기준 체크포인트를 고정해 이어 가면 그 단계를 다시 실행하고 남은 쓰기를 재적용하지 않는다. 그래서 이런 장애마다 예약이 1회 더 든다. 세션 상한 6회 안이다(P45).
- **복구 상한**: 같은 턴의 그래프 실행은 3번까지, 4번째 잠금은 모델 없이 결정적으로 닫는다(`turnAttempts > 3`, BE-Q113). 닫는 시도 자체가 강제 종료되면 닫기만 다시 한다.
- 울타리(24초)를 넘기면 체크포인트 쓰기를 시작하지 않고 같은 `turn`의 `WORKING`을 돌려준다(생성 턴은 `turn 1` `WORKING` 커밋, BE-Q121). 프론트는 같은 `turn`으로 이어서 보낸다.
- 체크포인트 쓰기 예외(일시 오류)는 LangGraph가 일부를 늦게 드러낸다. 남은 시간 계산이 울타리를 포함하므로 울타리 뒤에 모델을 부르지는 않지만, 일시 오류 뒤 한 단계가 더 진행될 수 있다(예약 상한 안).
- 토큰 추정은 글자 수 / 2 × 1.15다(BE-Q120). 실제 토큰의 엄격한 상한은 아니고, 커밋 때 실제 usage로 보정한다.
- 체크포인트에는 사연·답변·모델 메시지가 있다. 종료 뒤 지우고(BE-Q103), 실패하면 TTL(≤ 세션 TTL)이 지운다. 로그·trace·EMF에는 원문이 없다(P42).

- 초안 재시도(BE-Q129, 2026-11-27): 초안 시도는 세션당 최대 2회다. 재시도 상태(시도 수, 재시도 메시지)는 체크포인트에 있어서 강제 종료와 재개 뒤에도 초기화되지 않는다. 잃은 호출은 예약에 남는다. 재시도 메시지는 위반 경로와 스키마 제한만 담는다. 제목 길이처럼 재시도 뒤에도 위반이 남으면 후보 카드가 없어져 `FAILED`가 될 수 있다(11.11절).

### 11.7 모드 전환 절차

1. `AgentMode`를 바꿔 스택을 업데이트한다(`pipeline` ↔ `agent`). 코드 되돌리기는 쓰지 않는다(BE-Q102).
2. `agent` → `pipeline`: 진행 중인 에이전트 세션(`ASKING`·`WORKING`)은 다음 `turns` 요청에서 잠금 한 번으로 모델 없이 닫힌다. 후보 카드가 있으면 `READY`(`degraded`), 없으면 `FAILED` + 503 `AI_UNAVAILABLE`. 체크포인트는 지운다.
3. `pipeline` → `agent`: 6a 세션은 모두 종료 상태라 영향이 없다. 6a의 비종료 `PIPELINE` 세션(정상 경로에서는 생기지 않음)은 6a대로 500이다.

### 11.8 오프라인 평가 절차

```bash
cd backend
.venv/bin/python scripts/eval_agent.py --fake --reps 1 --stories demo,nis_1 --out /tmp/eval-fake.json   # 도구 확인(품질 근거 아님)
.venv/bin/python scripts/eval_agent.py --env-file <키가 든 .env 경로> --reps 3 --yes --out test-results/eval-agent-<날짜>.json
```

키 없이 실행하면 `LLM_API_KEY가 비어 있다`로 네트워크 호출 전에 끝난다. 실행 절차 전체는 11.9절.

- ①·②는 같은 레벨 0 실행의 첫 초안(검사만)과 최종 카드, ③은 별도 에이전트 실행(메모리 체크포인터, 자동 답)이다(BE-Q112). ③과 ①·②의 차이에는 프롬프트·도구 루프·모델 무작위성이 섞인다.
- 실행 전 예상 호출 수(최대 사연 × 반복 × 8)를 출력하고 확인을 받는다. `--pause`로 호출 사이를 쉰다.
- 출력: READY·degraded·실패 수, `NOT_IN_SOURCE`·`MISSING`·`PRIVACY`·`NEW_PLACE`(legitPlaces 밖) 잔존 수, 호출·토큰·지연(중앙값·p95), 질문 수, 사연별로 에이전트가 레벨 0보다 나은지(BETTER·WORSE·SAME·MIXED). 결과 파일은 `test-results/`(gitignore)에 둔다.
- NVIDIA trial 결과는 개발용이며 운영 공급자 결정 근거가 아니다(10.10절).

### 11.9 실제 공급자 검증 절차 (작업 20.2–20.4)

상태(2026-11-27, NVIDIA 시기): 키 설정을 확인했다. 1·2·3 단계는 끝났다. 4단계 스모크에서 실패해 5·6단계는 실행하지 않았다(11.10절). 공급자를 GPT-6 Luna로 바꾼 뒤 같은 날 전 단계를 실행했다(11.12절). 키 값은 출력·복사·커밋하지 않는다. 도구는 `--env-file`로 `.env`를 읽고 값은 출력하지 않는다.

| 순서 | 확인할 것 | 방법 | 기준 |
|---|---|---|---|
| 1 | 키와 공급자 설정이 유효한가 | `probe_provider.py --env-file <.env> --only raw` | 정상 키 요청 200. 결과 JSON의 `raw` 항목 |
| 2 | 추론이 꺼졌는가 | 같은 결과의 `raw.configured`(NVIDIA 시기 기록은 `raw.thinking_off`). GPT-6 Luna는 `raw.reasoning_effort_none`의 `reasoning_tokens` 0도 본다 | `status` 200, 응답 `content`가 비지 않음, `has_think_tag` false |
| 3 | BE-Q127 장소 5곳 재검증 | 위 BE-Q127 재검증 절 | 3회 모두 장소 ≤ 3, 사연 순서. 실패하면 BE-Q127 재개방 |
| 4 | 에이전트 스모크 5건(데모·비공개 장소·연락처·인젝션·빈칸) | 아래 로컬 명령 | `test_smoke_five_stories` 통과(READY, 예약 ≤ 6, `llmMode` openai_compat, 체크포인트 0, 요청 27초 미만, 답변 질문당 1건). 문제가 있으면 5번을 실행하지 않는다 |
| 5 | 같은 턴 동시 5요청(실제 모델) | `test_concurrent_same_turn_real` | `t20_checks` 전 항목 통과 |
| 6 | 오프라인 평가 15건 × 3회 | 아래 평가 명령 | 결과 파일과 표를 README 11.10절에 붙인다 |

로컬 스모크(Floci DynamoDB + 실제 핸들러. AWS가 아니다):

```bash
cd backend
# .env를 compose 변수 보간에 쓴다. 값은 컨테이너 환경 변수로만 들어간다(docker inspect로 볼 수 있으니 실행 뒤 되돌린다).
AGENT_MODE=agent docker compose --env-file <.env 경로> up -d --no-deps --force-recreate api
LOCAL_REAL_PROVIDER=1 LOCAL_AGENT_MODE=agent .venv/bin/pytest -m local tests/local/test_local_agent_real.py -s
# 끝나면 기본 설정(pipeline, fake)으로 되돌린다. 값을 명시해야 한다(아래 주의)
LLM_PROVIDER=fake LLM_API_KEY= LLM_BASE_URL= LLM_MODEL= LLM_EXTRA_BODY= AGENT_MODE=pipeline docker compose up -d --no-deps --force-recreate api
```

주의: `api` 서비스는 compose 프로젝트 디렉터리의 `.env`를 `env_file`로 읽는다(`backend/docker-compose.yml`). 그 디렉터리에 키가 든 `.env`가 있으면 명시하지 않은 `docker compose up`은 그 공급자와 `AGENT_MODE`를 그대로 쓴다. 복구와 실행 모두 위처럼 값을 셸에 명시한다. 복구 뒤 컨테이너의 `LLM_API_KEY` 길이가 0인지 확인한다(`docker inspect`로 길이만 본다).

오프라인 평가(NoopBudget, 메모리 체크포인터. DynamoDB를 쓰지 않는다):

```bash
.venv/bin/python scripts/eval_agent.py --env-file <.env 경로> --reps 3 --yes --out test-results/eval-agent-<날짜>.json > test-results/eval-agent-<날짜>.md
```

- 호출 한도: 사연 15 × 반복 3 × (레벨 0 최대 2 + 에이전트 최대 6) = 최대 360회. 실행 전 예상 호출 수를 출력한다. 호출 사이 2초, 턴 27초, 울타리 24초, 세션 예산(호출 6회, 입력 토큰 3만)은 그대로다.
- 429: 한 번 나오면 10초 쉰다. 3회 연속이면 우회하지 않고 멈춘다. 결과 파일에 `aborted`와 그때까지 행이 남는다(`complete: false`).
- 결과 파일과 표는 `test-results/`에 두고 커밋하지 않는다. 요약만 README 11.10절에 옮긴다.

### 11.10 실제 공급자 결과 (2026-11-27, NVIDIA NIM)

이 절은 NVIDIA 시기 기록이다. GPT-6 Luna 결과는 11.12절.

측정 조건: 커밋 `a35440c` 기준. 모델 `nvidia/nemotron-3.5-lightning-30b-a3b`, `LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}`, `LLM_PARALLEL_TOOL_CALLS=false`, `LLM_TEMPERATURE=0`, `LLM_MAX_TOKENS=800`, 연결 2초·읽기 8초·재시도 0. 세션 예산(호출 6회, 입력 토큰 3만), 턴 27초, 울타리 24초는 그대로 두었다. 스모크는 로컬 어댑터와 Floci DynamoDB를 썼다(AWS가 아니다). 키 값은 기록하지 않았고 실행 뒤 컨테이너 설정을 기본값으로 되돌렸다.

| 단계 | 결과 | 판정 |
|---|---|---|
| 1. 키·공급자 | 정상 키 요청 200 | 통과 |
| 1. Thinking OFF | 설정 적용: `content` 69자, 추론 0자, 종료 `stop`. 설정 없이: `content` 0자, 추론 663자, 길이 제한(`length`)에서 종료 | 통과 |
| 2. BE-Q127 장소 5곳 3회 | 3/3 READY, 장소 3곳, 사연 순서. 3회차 degraded(위 BE-Q127 절) | 통과 |
| 3. T12 정상 키 기준 기록 | `test-results/provider-probe-20261127T002222.json`. 같은 엔드포인트·모델, `thinking_off` 200. `t12_baseline()` 확인 통과 | 기록 생성 |
| 4. 로컬 스모크 5건 | 4건 READY(2건 degraded), **1건 FAILED(503)** | **실패, 중단** |
| 5. 같은 턴 동시 5요청 | 미실행(4단계 실패로 중단) | 미실행 |
| 6. 오프라인 평가 15×3 | 미실행(4단계 실패로 중단) | 미실행 |

#### 4단계 스모크 상세

HTTP 지연은 1.0–5.9초였고 27초를 넘긴 요청은 없었다. 모델 호출과 예약은 그 세션의 `modelCalls`·`modelCallsReserved`다.

| 사연 | 흐름(HTTP, 결과, 초) | 결과 | 질문(건너뜀) | 호출 / 예약 | 입력 / 출력 토큰(보고값) | 플래그·자체 수정 |
|---|---|---|---|---|---|---|
| demo | 200 ASKING 5.0 → 200 ASKING 4.1 → 200 READY 1.3 | READY, degraded | 2(2) | 6 / 6 | 10,744 / 776 | 없음. 예산 소진 뒤 자체 정리 |
| private_place_1 | 200 ASKING 4.8 → 200 ASKING 5.0 → 200 READY 1.1 | READY, degraded | 2(2) | 6 / 6 | 11,627 / 739 | PRIVACY 2, NOT_IN_SOURCE 2 / REMOVED 1, KEPT_FLAGGED 2 |
| contact_1 | 200 ASKING 3.4 → 200 ASKING 1.0 → **503 AI_UNAVAILABLE 2.4** | **FAILED** | 2(2) | 6 / 6 | 10,482 / 795 (세션 기록) | 후보 카드 없음 |
| injection_1 | 200 ASKING 2.5 → 200 READY 5.9 | READY | 1(1) | 5 / 5 | 8,401 / 785 | MISSING 1 |
| missing_1 | 200 READY 3.2 | READY | 0 | 3 / 3 | 4,032 / 383 | 자체 수정 REWRITTEN 1 |

- 체크포인트: 종료된 세션(READY·FAILED)의 체크포인트는 모두 삭제됐다. contact_1 세션도 0건이다.
- 테스트 출력의 `contact_1: llmMode None` 줄은 기록 누락이다. 503 응답에는 세션을 읽지 않아 `llmMode`가 없다. 실패 사유는 `HTTP 503` 줄이다.
- 자동 답 규칙의 결과: demo와 private_place_1의 `estimatedMinutes` 질문은 선택지에 `45분`이 없어 건너뛰었다(픽스처 규칙 그대로).

#### 4단계 실패 원인 (contact_1)

- 증상: 두 번째 턴(답변 뒤)이 503 `AI_UNAVAILABLE`로 끝났다. 세션은 `FAILED`, `llmError=BUDGET_CALLS`, 모델 호출 6회 모두 사용, `submit_card`를 부르지 못했다.
- 첫 초안: `check_draft`가 `title`의 스키마 위반(1–40자)을 보고했다. 에이전트 모드는 스키마 위반 초안을 재시도하지 않는다(설계 §4.1, §10). 그래서 후보 카드가 없었다.
- 모델의 시도: 제목을 질문으로 고치려 했다. 질문 경로 `title`은 허용 목록(BE-Q123)에 없어 `PATH_NOT_ALLOWED`로 거부된다. 또 질문 한도(2개)를 넘긴 호출과 인자 검증 실패(`INVALID_ARGS`)가 섞였다. 호출 6회가 이렇게 소진됐다.
- 같은 사연의 진단 재현 2회: 저장소 밖 스크립트로 메타데이터(`finish_reason`, 출력 토큰, 도구 이름, 오류 코드, 질문 길이)만 기록했다. 두 번 모두 `BUDGET_CALLS`로 `FAILED`였다. 한 번은 질문을 4번 냈고(한도 2 초과 거부), 한 번은 `title` 질문을 세 번 낸 뒤 인자 오류를 냈다. 세 번(스모크 1, 진단 2) 모두 실패했다.
- 안전성: 잘못된 카드는 나가지 않았다. 사연은 유지되고 사용자는 503을 받아 직접 작성으로 간다. 문제는 가용성이다.
- 레벨 0과 비교: 같은 사연의 6a 측정(2026-11-26, 1회)은 READY, 모델 호출 1회였다. 조건이 달라 직접 비교는 아니다.
- 예산: demo와 private_place_1은 호출 6회를 다 쓴 뒤 자체 정리로 degraded READY가 됐다. 6회 상한이 실제 모델 행동에서 빠듯하다는 신호다.

#### 필요한 결정 (BE-Q129, docs/08)

프롬프트 변경, 설계 변경, 예산 변경은 이번 실행에서 하지 않았다. 아래 중 하나를 골라야 한다.

- A. 에이전트 모드에서 스키마 위반 초안을 레벨 0처럼 한 번 재시도한다. 설계 §4.1·§10 변경이고, 재시도 한 번이 예산 6회를 쓴다.
- B. 프롬프트에 "스키마 위반은 질문하지 말고 `submit_card`로 고친다"를 넣는다. 프롬프트 변경이고 모델 준수에 기댄다.
- C. 현재 동작을 유지한다. 이런 사연은 503으로 끝나고 직접 작성으로 간다. 이 비용을 받아들이는 결정이 필요하다.

판정 기준(스모크 5건 READY, 예약 6 이하 등)은 낮추지 않았다. 동시 5요청과 15×3 평가는 BE-Q129 결정 뒤 실행한다.

### 11.11 BE-Q129 보완 뒤 실측 (2026-11-27, NVIDIA NIM): 스모크 실패로 중단

이 절은 NVIDIA 시기 기록이다. 같은 코드로 GPT-6 Luna에서 다시 돌린 결과는 11.12절이다.

변경: 에이전트 초안 재시도(세션당 최대 2회, JSON 오류와 스키마 오류가 한 예산), 재시도 메시지(위반 경로와 스키마 제한만, 실패 응답 원문 없음), 프롬프트 일반 규칙("스키마 위반은 계획자에게 질문할 문제가 아니다. 필드 길이, 자료형, 배열 개수 위반은 직접 수정한다. ask_planner는 허용된 경로의 실제 정보 부족을 해결하는 데만 사용한다"). `promptVersion` `ca6ada9ac3ef` → `3db437c63971`. 레벨 0은 바꾸지 않았다.

| 단계 | 결과 | 판정 |
|---|---|---|
| 단위 테스트 전체(최종 코드) | 1124건 통과 | 통과 |
| 로컬 회귀, 기본 pipeline | 23건 통과, 15건 건너뜀 | 통과 |
| 로컬 회귀, agent 페이크(ask_once) | 28건 통과, 10건 건너뜀(실제 공급자 사례는 `LOCAL_REAL_PROVIDER=1` 필요) | 통과 |
| 1. contact_1 진단 3회(같은 조건, 평가 도구) | 에이전트 3/3 FAILED(`BUDGET_CALLS`). 레벨 0 3/3 READY | 실패 |
| 2. 스모크 5건(최종 이미지) | READY 3건(1건 degraded), FAILED 2건 | **실패, 중단** |
| 3. 같은 턴 동시 5요청 | 미실행 | - |
| 4. 합성 15건 × 3회 평가 | 미실행 | - |

같은 스모크를 재시도 보완 직후 이미지에서 한 번 더 돌렸다. 그때는 READY 4건(1건 degraded), FAILED 1건(`contact_1`)이었다. 두 번 모두 contact_1이 실패했고, 최종 이미지에서는 `private_place_1`도 실패했다.

#### 스모크 5건 (최종 이미지)

| 사연 | 결과 | 초안 시도 | 모델 호출/예약 | 질문(건너뜀) | 메모 |
|---|---|---|---|---|---|
| demo | READY | 1 | 3/3 | 0 | 재시도 없음 |
| private_place_1 | FAILED(503, 두 번째 턴) | 2 | 6/6 | 2(2) | 첫 초안과 재시도 초안 모두 제목 위반. 제출은 서버 검사에서 거부됨 |
| contact_1 | FAILED(503, 생성 요청) | 2 | 6/6 | 0 | 두 초안 모두 제목 위반. 질문 두 번 거부(`PATH_NOT_ALLOWED`) |
| injection_1 | READY(degraded) | 1 | 6/6 | 2 | 예산을 다 쓴 뒤 자체 정리 |
| missing_1 | READY | 1 | 5/5 | 1 | 자체 수정 REWRITTEN |

응답 지연은 1.0–11.0초였고 27초를 넘기지 않았다. 최종 스모크의 READY와 FAILED 세션은 모두 체크포인트가 0건이었다(확인함). 테스트 출력의 `llmMode None` 줄은 503 응답에서 세션을 읽지 않아 생긴 기록 누락이다.

#### contact_1 진단

- 평가 도구 진단 3회를 두 번 돌렸다(보완 직후 코드, `draft_card`가 중복 저장되던 버전 3회 / 최종 코드 3회). 에이전트는 6회 모두 `FAILED`였다. 초안은 2회를 모두 썼고, 첫 초안 검사에서 스키마 위반(`title`)이 남았다. 질문은 허용 밖 경로(`PATH_NOT_ALLOWED`)와 선택지 오류(`OPTIONS`)로 거부됐고, 제출은 게이트에서 거부됐다. 예산 6회를 다 쓴 뒤 `BUDGET_CALLS`로 끝났다.
- 초안만 따로 호출한 진단(메타데이터만 기록, 3회): 첫 초안의 제목은 3회 모두 47자였다. 재시도 메시지는 `title(1–40자)`만 담았고, 재시도 초안의 제목도 3회 모두 47자였다. 다른 필드는 모두 40자 안이었다.
- 레벨 0은 같은 사연에서 3/3 READY였고 모델 호출 1회였다. 레벨 0 프롬프트에는 짧은 제목 예시(`이사 전, 마지막 동네 산책`)가 있고 에이전트 초안 절에는 예시가 없다. 이 차이가 원인인지는 확인하지 않았다(가설).
- 질문 거부: 보완 직후 세트 3회에서는 `PATH_NOT_ALLOWED` 1회와 `OPTIONS` 2회, 최종 세트 3회에서는 `PATH_NOT_ALLOWED` 5회(실행당 1–2회)였다. 일반 규칙이 허용 밖 질문을 줄이지 못했다. 같은 종류의 질문(제목 경로)이 이전 세션의 진단 재현에서도 나왔다.

#### 원인 요약

스키마 위반(제목 길이)이 두 번째 초안에서도 남는다. 후보 카드가 없어지고, 그 뒤 질문과 제출이 예산을 다 써서 `FAILED`가 된다. 실패는 안전하게 끝났다. 잘못된 카드는 나가지 않았고 사용자는 503을 받아 직접 작성으로 간다. 문제는 가용성이다. 재시도 자체는 설계대로 동작했다. 재시도 상태는 체크포인트에 남았고, 초안은 두 번을 넘지 않았다. 다만 이 사연에서는 재시도 메시지만으로 제목 길이가 줄지 않았다.

#### 추가 결정 후보 (BE-Q129)

프롬프트를 더 고치지 않았다. 지시대로 다음 중에서 고른다.

1. 서버가 제목을 40자 이내로 줄인다(결정적). 스키마는 그대로 지키지만 모델이 쓴 문장을 서버가 바꾼다. 6a 수선 규칙과 같은 종류이며 승인이 필요하다. 가장 확실하다.
2. 재시도 메시지에 현재 길이를 넣는다(예: "title 47자, 40자 이내"). 메시지 내용을 넓히는 것이므로 요구사항과 설계 변경이 필요하다.
3. 에이전트 초안 절에 레벨 0과 같은 짧은 제목 예시를 넣는다. 가설을 먼저 검증해야 하고, 그 뒤에도 튜닝을 반복하지 않는다.
4. 현행 유지. 이런 사연은 503으로 끝나고 직접 작성으로 간다. 가용성 비용을 받아들이는 결정이 필요하다.

결정 전에는 동시 5요청 검증과 15×3 평가를 실행하지 않는다. 결정 뒤 스모크부터 다시 돌린다. 이번 15×3 평가는 개발 사례(contact_1)로 고친 뒤 실행한 것이 아니므로 독립 평가로 표현하지 않는다(해당 사례는 실행하지 않았다).

#### 결과 파일 (커밋하지 않음)

- `test-results/diag-contact1-bq129-20261127.json`(보완 전 코드 진단 3회), `test-results/diag-contact1-bq129-final-20261127.json`(최종 코드 진단 3회)
- `test-results/diag-draft-bq129-20261127.json`(초안 메타데이터, 3샘플)
- `test-results/local-real-agent-smoke-20261127T014956.json`(보완 직후 스모크), `test-results/local-real-agent-smoke-20261127T021500.json`(최종 스모크)

### 11.12 GPT-6 Luna 전체 재검증 (2026-11-27)

측정 조건: 설정은 10.11절과 같다. 호출 예산(6회), 입력 토큰 3만, 턴 27초, 울타리 24초, 질문 2개, 12초 규칙, 프롬프트 버전(레벨 0 `ca6ada9ac3ef`, 에이전트 `3db437c63971`)은 바꾸지 않았다. 코드는 `8ca5c64`의 `src/`와 같다. 그 뒤 커밋(`d460341`, `c9b3582`)은 검증 스크립트만 바꿨다. 스모크와 동시 요청은 로컬 어댑터와 Floci DynamoDB로 돌렸다. AWS 실행이 아니다. 원본 결과는 `test-results/`에 있고 커밋하지 않는다.

| 단계 | 결과 | 판정 |
|---|---|---|
| 1. 호환성 | 10.11절 | 통과 |
| 2. 실패 사례 3종 × 3회 | 에이전트 9/9 READY, 초안 스키마 위반 0, 초안 재시도 0 | 통과 |
| 2b. BE-Q127 many_places × 3회 | 레벨 0 3/3 READY | 통과 |
| 3. 스모크 5건 | 5/5 READY, degraded 0, 예약 = 호출, 체크포인트 0건, `problems` 없음 | 통과 |
| 4. 같은 턴 동시 5요청 | 아래 표의 7개 검사 모두 통과 | 통과 |
| 5. 합성 15건 × 3회 평가 | ①②③ 각 45행, 중단 없이 완료 | 완료 |

#### 실패 사례 3종 재검증 (에이전트, 3회씩)

| 사연 | ① 최초 초안 | ② 레벨 0 | ③ 에이전트 | ③ 모델 호출(3회) | ③ 질문(건너뜀) | ③ 지연 중앙값(범위) |
|---|---|---|---|---|---|---|
| contact_1 | DRAFT 3/3 | READY 3/3, 호출 1 | READY 3/3 | 3, 3, 4 | 3(1) | 7.4초(5.7–9.0) |
| private_place_1 | DRAFT 3/3 | READY 3/3, 호출 1 | READY 3/3 | 3, 3, 3 | 3(3) | 6.4초(6.3–6.5) |
| many_places | DRAFT 3/3 | READY 3/3, 호출 1 | READY 3/3 | 3, 3, 3 | 3(3) | 6.4초(6.4–6.4) |

- 세 사례 모두 초안 스키마 위반, 초안 재시도, 질문 거부, 도구 오류, 게이트 거부가 0건이다. ③의 자체 수정(REWRITTEN·REMOVED)은 6건이다.
- ③의 도구 순서는 `draft → check_draft → ask_planner → submit_card`다. contact_1 3회차만 `check_draft`가 한 번 더 들어가 호출 4회였다.
- contact_1은 BE-Q129 설계 때 개발 사례로 썼다. 이 3회는 독립 검증이 아니다.

#### 스모크 5건 (로컬 어댑터, GPT-6 Luna)

| 사연 | 결과 | 요청 흐름(HTTP 코드, 초) | 모델 호출 / 예약 | 질문(건너뜀) | 플래그 |
|---|---|---|---|---|---|
| demo | READY | 200 ASKING 6.3 → 200 READY 2.6 | 3 / 3 | 1(1) | MISSING 1 |
| private_place_1 | READY | 200 ASKING 4.3 → 200 READY 2.7 | 3 / 3 | 1(1) | MISSING 1 |
| contact_1 | READY | 200 ASKING 4.4 → 200 READY 4.9 | 4 / 4 | 1(0) | 없음 |
| injection_1 | READY | 200 ASKING 4.2 → 200 READY 2.3 | 3 / 3 | 1(1) | MISSING 1 |
| missing_1 | READY | 200 ASKING 3.9 → 200 READY 2.7 | 3 / 3 | 1(1) | MISSING 2 |

- 요청 지연은 2.3–6.3초로 모두 27초 안이다. 체크포인트는 종료 뒤 0건이다. `llmMode`는 `openai_compat`, `problems`는 비어 있다.
- 자동 답은 픽스처에 답이 있는 질문에만 한다. contact_1은 `estimatedMinutes`에 `30분`을 골랐다.
- `missing_1`의 READY 카드는 장소가 0곳이다. 아래 주의 4번을 본다.

#### 같은 턴 동시 5요청

| 확인 | 결과 |
|---|---|
| 응답 코드 | 200 1건, 409 `AI_SESSION_BUSY` 4건 |
| 턴 | 1 → 2 |
| 예약 / 모델 호출 | 2 → 3 / 2 → 3 (둘 다 +1, 중복 호출 0) |
| 상태 | ASKING → READY |
| 답변 기록 | 1건(`estimatedMinutes`, `30분`) |
| 체크포인트 | 0건 |
| `t20_checks` | `one_commit`, `codes`, `winner_present`, `busy_only`, `same_view`, `no_extra_calls`, `reserved_cap` 모두 통과 |

#### 합성 15건 × 3회 평가

45행(15 사연 × 3회)을 세 방식으로 봤다. ①과 ②는 같은 레벨 0 실행에서 나왔다. 그래서 호출 수, 토큰, 지연이 같다. ③은 별도 에이전트 실행이다. 질문에는 픽스처의 자동 답 규칙으로 답했고, 답이 없으면 건너뛰었다. 이 평가에는 contact_1이 들어 있고 BE-Q129 개발 사례다. 독립 held-out 평가가 아니다.

| 항목 | ① 최초 초안 | ② 레벨 0 파이프라인 | ③ 에이전트 |
|---|---|---|---|
| READY / degraded / FAILED | DRAFT 45(검사만) | 43 / 2 / 0 | 45 / 0 / 0 |
| NOT_IN_SOURCE 잔존 합 | 3 | 3 | 0 |
| MISSING 합 | 80 | 80 | 46 |
| PRIVACY 잔존 합 | 6 | 6 | 0 |
| NEW_PLACE 합(legitPlaces 밖) | 10 | 10 | 6 |
| 모델 호출 중앙값 / 최대 / 합 | 1 / 1 / 45 | 1 / 1 / 45 | 3 / 3 / 135 |
| 입력 토큰 중앙값 / 합 | 808 / 36,246 | 808 / 36,246 | 3,665 / 164,842 |
| 출력 토큰 중앙값 / 합 | 117 / 5,006 | 117 / 5,006 | 377 / 17,215 |
| 질문 수(건너뜀) | 0 | 0 | 45(39) |
| 게이트 거부 합 | 0 | 2 | 0 |
| 자체 수정 합(REWRITTEN·REMOVED) | 0 | 0 | 7 |
| 초안 스키마 위반 실행 / 초안 재시도 실행 | 0 / 0 | 0 / 0 | 0 / 0 |
| 도구 오류 / 질문 거부 | 0 / 0 | 0 / 0 | 0 / 0 |
| 응답 시간 ms 중앙값 / p95 / 최댓값 | 1,939 / 2,553 / 3,050 | 1,939 / 2,553 / 3,050 | 5,656 / 6,582 / 7,210 |
| 타임아웃·공급자 오류·429·예산 중단 | 0 | 0 | 0 |

- 토큰은 모두 공급자 usage 값이다. 추정한 실행은 0건이다.
- ③의 응답 시간은 턴 처리 시간의 합이다. 사용자가 질문에 답하는 시간은 들어 있지 않다. 가장 긴 한 턴은 4.4초였다.
- ②의 degraded 2건은 모두 `contact_2`이고, 게이트 거부가 각각 한 번씩 있었다.

사연별 결과. 칸은 3회 합계이고, 순서는 NOT_IN_SOURCE·MISSING·PRIVACY·NEW_PLACE다. 판정은 `scripts/eval_agent.py`의 `verdict`가 낸다. 실패 수, 잔존 문제 합(NOT_IN_SOURCE + PRIVACY + NEW_PLACE), MISSING 합을 ②와 ③에서 비교한다. 모두 같거나 작고 하나 이상 작으면 개선, 모두 같거나 크고 하나 이상 크면 악화, 같으면 동일, 그 밖은 혼합이다. 기준은 바꾸지 않았다.

| 사연 | ② 합계 | ③ 합계 | ② 결과 | ③ 결과 | 판정 |
|---|---|---|---|---|---|
| demo | 0/3/0/0 | 0/3/0/0 | READY 3 | READY 3 | 동일 |
| private_place_1 | 0/3/6/0 | 0/3/0/0 | READY 3 | READY 3 | 개선 |
| private_place_2 | 0/3/0/0 | 0/3/0/0 | READY 3 | READY 3 | 동일 |
| contact_1 | 0/3/0/3 | 0/0/0/2 | READY 3 | READY 3 | 개선 |
| contact_2 | 3/3/0/0 | 0/3/0/0 | DEGRADED 2, READY 1 | READY 3 | 개선 |
| nis_1 | 0/6/0/4 | 0/3/0/3 | READY 3 | READY 3 | 개선 |
| nis_2 | 0/9/0/0 | 0/6/0/0 | READY 3 | READY 3 | 개선 |
| nis_3 | 0/6/0/0 | 0/3/0/0 | READY 3 | READY 3 | 개선 |
| injection_1 | 0/6/0/0 | 0/3/0/0 | READY 3 | READY 3 | 개선 |
| injection_2 | 0/7/0/0 | 0/3/0/0 | READY 3 | READY 3 | 개선 |
| missing_1 | 0/9/0/0 | 0/3/0/0 | READY 3 | READY 3 | 개선 |
| missing_2 | 0/4/0/0 | 0/4/0/0 | READY 3 | READY 3 | 동일 |
| many_places | 0/6/0/0 | 0/3/0/0 | READY 3 | READY 3 | 개선 |
| short | 0/6/0/0 | 0/3/0/0 | READY 3 | READY 3 | 개선 |
| mixed | 0/6/0/3 | 0/3/0/1 | READY 3 | READY 3 | 개선 |

결과: 개선 12, 동일 3, 악화 0, 혼합 0. 개선 12건 중 5건(private_place_1, contact_1, contact_2, nis_1, mixed)은 잔존 문제도 줄었다. 나머지 7건은 MISSING만 줄었다. 에이전트가 낫지 않은 사연은 3건(demo, private_place_2, missing_2)이다. 이 세 사연은 레벨 0과 에이전트 모두 잔존 문제가 0이었고, 빈칸 수도 같았다.

읽을 때 주의할 점:

1. ③의 NOT_IN_SOURCE는 사연과 계획자 답변을 근거로 판정한다. ②는 사연만 쓴다. 근거가 다르므로 NOT_IN_SOURCE 차이는 참고만 한다. contact_2의 자동 답은 모두 건너뛰기였다.
2. MISSING은 비어 있는 필드 수다. ③의 MISSING 46은 자동 답 6건만으로 설명되지 않는다. 답 한 건이 채우는 칸은 하나다. 결과 파일에는 카드 원문이 없어서 어느 필드가 채워졌는지 확인하지 못했다. NOT_IN_SOURCE는 장소와 활동만 본다. 따라서 에이전트가 채운 `reason`·`summary`·`question` 문장이 사연에 근거하는지는 측정하지 않았다.
3. ③의 호출 수는 실행당 3회(중앙값, 최대 3회)다. 재검증 contact_1의 한 회만 4회였다.
4. READY 카드의 장소가 0곳인 경우가 ②와 ③에 각각 7건 있었다. 세 사연(nis_2, missing_1, missing_2)에서 나왔다. 설계상 `places: []`는 유효하다(BE-Q122). 공개 폼은 장소 1–3곳을 요구하므로(FE-CRT-06) 사용자가 장소를 채운 뒤에야 공개할 수 있다.

#### NVIDIA 기록과 비교

| 비교 | NVIDIA NIM (11.10·11.11절) | GPT-6 Luna (이번) |
|---|---|---|
| contact_1, ② 레벨 0 | 6/6 READY, 호출 1 | 6/6 READY, 호출 1 |
| contact_1, ③ 에이전트 | 6/6 FAILED(`BUDGET_CALLS`). 초안 2회 모두 제목 47자 | 6/6 READY, 호출 3–4 |
| 스모크 5건 | 보완 직후 READY 4(1 degraded)·FAILED 1, 최종 이미지 READY 3(1 degraded)·FAILED 2 | READY 5/5 |
| 15건 × 3회 평가 | 실행하지 않음 | 45행 × 3방식 |

- 두 공급자는 모델과 게이트웨이가 다르다. 프롬프트 버전은 contact_1 기준으로 같다.
- NVIDIA contact_1 기록은 저장소 밖 진단 스크립트로 만들었다. 결과 형식은 평가 파일과 같지만, 평가 harness와 같은 코드 경로인지는 확인하지 않았다.
- 15건 평가는 NVIDIA에서 실행하지 않았다. 15건 수치는 직접 비교하지 않는다.
- 이 표는 한 공급자의 기록이 다른 공급자와 다르다는 것을 보여 줄 뿐이다. 어느 공급자가 낫다는 결론을 내리지 않는다.

### 11.13 기본 출시 모드 제안 (2026-11-27)

**제안: 출시 기본 모드는 `pipeline`으로 둔다.** 측정만 보면 `agent`가 낫다. READY 비율이 100%이고 잔존 문제가 적다. 그래도 지금 기본값을 바꿀 근거는 모자란다.

| 항목(15건 × 3회) | ② 레벨 0 파이프라인 | ③ 에이전트 |
|---|---|---|
| READY 비율 | 95.6%(43/45). degraded 2건은 모두 `contact_2` | 100%(45/45) |
| 잔존 문제 합(NOT_IN_SOURCE + PRIVACY + NEW_PLACE) | 19 | 6 |
| MISSING 합 | 80 | 46 |
| 모델 호출(실행당 중앙값) | 1 | 3 |
| 입력 토큰(중앙값) | 808 | 3,665 |
| 응답 시간 중앙값 / 최댓값 | 1.9초 / 3.1초 | 5.7초 / 7.2초 |
| 계획자 질문 | 없음 | 실행당 1개 |

`pipeline`을 기본으로 두는 이유는 셋이다.

1. 한 공급자의 결과다. GPT-6 Luna 한 모델, 합성 사연 15건, 자동 답 규칙에서 얻었다. 같은 설계를 NVIDIA에서 돌리면 `contact_1`이 6회 모두 실패했다. 운영 공급자가 정해지지 않았으므로 안정성을 넓게 말할 수 없다.
2. 비용과 시간이 세 배 가까이 든다. 호출은 실행당 3회, 입력 토큰은 4.5배다. 질문이 실행마다 한 번 나오므로 계획자가 답해야 한다.
3. 확인을 끝내지 못했다. AWS 판정(T18–T22, T20, T21, T12)을 하지 않았다. 11.2절 2항은 `dev`에서 판정을 통과한 뒤 `agent`로 바꾸도록 정한다. 운영 공급자와 데이터 정책(BE-Q6·BE-Q7·BE-Q10)도 미결이다. MISSING 감소가 어디서 왔는지도 확인하지 못했다.

`agent`를 기본값으로 바꾸려면 다음이 모두 필요하다.

- 운영 공급자, 데이터 보존 기간, 처리 국가, 동의 문구 승인(BE-Q6, BE-Q7, BE-Q10, 작업 23).
- AWS `dev`에서 T18–T22, T20, T21, T12 통과(작업 22).
- 운영 공급자로 15건 × 3회 평가를 같은 기준으로 다시 실행.
- 에이전트가 채운 비장소 필드(`reason`, `summary`, `question`)를 사람이 검토. 이를 위해 카드 원문을 남기는 별도 실행을 만든다. 결과 파일은 커밋하지 않는다(제안).

데모 흐름 주의: docs/01 §1.7의 1번은 질문 1개에 답하는 장면을 보인다. 질문 단계는 `agent`에서만 나온다(docs/03 레벨 0 설명). 기본값을 `pipeline`으로 두면 데모 환경만 `agent`로 켜야 한다.

사용자가 정할 것:

1. 출시 기본 모드. 이 제안을 승인할지.
2. 데모에서 질문 단계를 보일지. 보인다면 데모 환경만 `agent`로 켠다.
3. 사용자 `.env`의 `LLM_EXTRA_BODY` 한 줄 교체(10.11절). 키가 든 파일이라 에이전트가 직접 고치지 않았다.

## 12. 5단계 사진 파이프라인

spec: `.kiro/specs/backend-stage5-photo-pipeline/`(requirements·design·tasks). 흐름은 docs/02 §2.7: `PUT /record`(photo) → presigned PUT → S3 알림 → `PhotoQueue` → `PhotoProcessorFunction` → 3단계 `complete_claim(WITH_PHOTO)`. 전달 1회는 3단계 완료 트랜잭션이 지킨다(G2·G4). 처리 Lambda는 그 앞에서 처리해도 되는지 거르고, 뒤에서 `ConsistentRead`로 결과를 확인해 자기 처리본만 정리한다.

### 12.1 현황 (2026-11-25)

| 항목 | 상태 |
|---|---|
| 브랜치·커밋 | `feat/be-5-photo-pipeline`: `819dcfb` spec, `74c92dd` 공통·이미지, `430dc8f` API, `593a8f6` 처리 Lambda, `6cd4178` 복구 스크립트, `25ded68` 템플릿, `cfc65a7` 로컬, `40a767f` AWS 테스트, `563d33d` 문서, `2a7a3cc`·`f7026ad` 복구 스크립트 안전 확인 강화, 상태 갱신 커밋. Draft PR #7 |
| 단위 테스트 | 647건 통과(2026-11-26), `-m slow` 2건 통과. Property 25(처리본 규칙)·26(거부 사유)·27(전달 1회·현재 사진)·28(업로드 URL·교체) 각 100예시 |
| 이미지 측정(`test_photo_memory.py`, 별도 프로세스) | 40MP JPEG 최대 상주 104.8MB·303ms, 40MP PNG 325.3MB·947ms. 한도 717MB(1024MB의 70%) 안(BE-Q56) |
| 중첩 재시도 상한(`test_photo_retry_budget.py`) | 완료 호출 1번이 최대 GetItem 16회·TransactWriteItems 12회(합 28회), SDK 총 시도 2회면 56회. 시간 guard는 완료를 시작할지만 정한다(BE-Q71) |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build --use-container` 성공. 레이어에 Pillow 13.0.0 cp312 manylinux x86_64. Lambda 빌드 이미지 안에서 `process_image`(EXIF 제거)와 핸들러 import 확인. 다른 함수 빌드 결과에 Pillow 없음 |
| 로컬 | 5.5절 |
| AWS 판정 | 미실행(3.4절) |

### 12.2 배포 전 주의

- **`sam build --use-container`로 빌드한다.** Pillow 레이어(`layers/pillow/requirements.txt`)는 Lambda 빌드 이미지(python3.12, x86_64)에서 받아야 한다. 로컬 Docker가 없는 환경을 위해 `samconfig.toml`에는 넣지 않았다.
- 사진 버킷 이름은 `{스택 이름}-photos-{계정 ID}`로 고정이다. 스택 이름은 소문자·하이픈이어야 한다. 같은 이름의 버킷이 남아 있으면 배포가 실패한다. `sam delete` 전에 버킷을 비워야 한다(CloudFormation은 빈 버킷만 지운다. 비우는 것은 데이터 삭제이므로 AWS 담당이 확인 뒤 한다).
- `Stage` 파라미터: `samconfig.toml`의 dev는 `Stage=dev`, demo는 `Stage=demo`. 템플릿 기본값은 `demo`라 주입이 기본으로 막힌다.
- `FaultInject`는 `haru-dev`에서 판정할 때만 넘기고 판정 뒤 복원 배포한다(3.4절). 세 겹 차단(BE-Q59): `Rules FaultInjectOnlyInDev`, 조건 `FaultAllowed`(`Stage = dev` ∧ 실제 스택 이름 `haru-dev`), 런타임(`FAULT_INJECT_ALLOWED = "true"`이고 함수 이름이 `haru-dev-`로 시작). 다른 이름의 개인 dev 스택에서는 주입이 켜지지 않는다.
- `UploadIfNoneMatch`는 **프론트엔드 승인 전까지 `false`**다(BE-Q65). 켜면 `upload.headers`에 `If-None-Match: *`, 버킷 CORS 허용 헤더, 헤더 없는 원본 PUT을 거부하는 버킷 정책이 함께 켜진다.
- `PhotoDLQNotEmpty` 알람에는 알림 대상이 없다(BE-Q62). 콘솔·API로 상태를 본다.

### 12.3 운영자 복구 런북 (PhotoDLQ, BE-Q68)

DLQ 처리 Lambda는 없다. 강제 종료 등으로 DLQ에 간 메시지의 Record는 `PROCESSING`으로 남을 수 있다. 실행자는 그동안에도 사진 교체나 글로 완료로 스스로 끝낼 수 있다.

```bash
python scripts/photo_dlq_recover.py --stack haru-dev                                   # dry-run(기본). DynamoDB에 쓰지 않는다
python scripts/photo_dlq_recover.py --stack haru-dev --apply --confirm-stack haru-dev  # 안전 확인을 모두 통과하면 복구
```

- **dry-run도 DLQ 메시지의 가시성을 바꾼다.** 스크립트는 판정을 위해 `ReceiveMessage(VisibilityTimeout=60)`를 부르므로, 읽은 메시지는 dry-run에서도 60초 동안 다른 소비자에게 보이지 않고 `ApproximateReceiveCount`가 1 오른다. DLQ에는 소비자가 없어 데이터는 바뀌지 않지만, 그 60초 동안 콘솔의 메시지 폴링·redrive·`aws sqs receive-message`에서 그 메시지가 빠져 보이고 `ApproximateNumberOfMessagesVisible`(알람 지표)이 잠시 줄어든다. 스크립트를 돌린 직후 DLQ를 직접 확인하거나 redrive하려면 60초 기다린다. 스크립트는 메시지 삭제·redrive·`ChangeMessageVisibility`·이벤트 소스 매핑 변경을 하지 않는다. 출력에 키·사용자 ID·URL이 없다(`claimId`는 앞 8자).
- 판정: `photoKey` 일치·`PROCESSING`·미전달 → 복구 대상(`--apply` 때 조건 `photoKey = :key AND photoStatus = PROCESSING AND attribute_not_exists(deliveredAt)`로 씀, 조건 실패는 "그새 바뀜"). 이미 `FAILED` → 없음. 키 불일치·전달됨·`DISCARDED`·Record 없음 → 지난 메시지. `UPLOAD_PENDING` → 처리 전 실패(사용자가 교체·글로 완료). `READY`·미전달 → 비정상(BE-Q66), 개발 담당에게 넘긴다.
- **DLQ에 메시지가 있어도 같은 사진을 처리하는 Lambda가 실행 중일 수 있다**(같은 키의 중복 이벤트, 가시성 타임아웃 직후 재전달과 DLQ 이동의 겹침). 그래서 `--apply`는 아래 안전 확인을 **모두** 통과해야 DLQ를 읽고 쓴다. 하나라도 실패하면 `BLOCKED`와 사유를 출력하고, DLQ를 읽지 않고(가시성도 바꾸지 않는다) 아무것도 쓰지 않고 종료 코드 2로 끝난다. 확인을 건너뛰는 옵션은 없다.

  | 확인 | 통과 조건 | 실패 사유 코드 |
  |---|---|---|
  | 스택 재확인 | `--confirm-stack` = `--stack` | `confirm_stack_mismatch` |
  | 이벤트 소스 매핑 | 처리 함수의 매핑이 모두 `Disabled`, 스택의 `PhotoProcessorQueueMapping`이 그중에 있음, 마지막 변경 뒤 60초(함수 타임아웃 30초의 2배) 이상 | `mapping_not_disabled:<State>`, `mapping_not_found`, `mapping_disabled_less_than_60s`, `mapping_unavailable:*` |
  | 처리 중 메시지 | PhotoQueue `ApproximateNumberOfMessagesNotVisible`를 5초 간격으로 3번 읽어 모두 0(근사값이라 한 번만 보지 않는다). 대기 중(Visible) 메시지는 매핑이 꺼져 있으면 처리되지 않으므로 막지 않는다 | `queue_in_flight_not_zero` |
  | 실행 종료 | CloudWatch `AWS/Lambda` `ConcurrentExecutions`(함수 차원). 지표가 늦게 들어오므로 매핑 변경 + 30초 뒤 300초가 지나야 판단한다(즉 매핑을 끈 뒤 최소 330초). 데이터 점이 있으면 최대값이 0이어야 한다. **데이터 점이 없으면 0으로 보지 않는다.** 호출 없음, 아직 안 들어온 지표, 함수 이름·리전 불일치를 구분할 수 없기 때문이다. 이때는 `ListMetrics`로 그 함수의 지표가 있을 때(이름·리전이 맞고 최근 2주 안에 호출됨)만 "호출 없음"으로 추정해 통과시키고, 출력에 `executions=no_datapoints(inferred_idle…)`로 측정값이 아님을 표시한다 | `executions_metric_not_settled_300s`, `executions_after_disable`, `executions_no_data_metric_unknown`, `executions_unavailable:*`, `executions_since_unknown` |

- 절차
  1. dry-run으로 판정을 본다(60초 가시성 변경을 감안한다).
  2. `aws lambda list-event-source-mappings --function-name <PhotoProcessorFunction>`으로 PhotoQueue 매핑 UUID를 찾는다.
  3. `aws lambda update-event-source-mapping --uuid <UUID> --no-enabled`, `get-event-source-mapping`의 `State`가 `Disabled`가 될 때까지 기다린다. 끈 시각을 기록한다.
  4. 최소 330초(매핑 60초 조건과 지표 지연 300초 조건) 기다린다. 함수 로그에 새 `START` 줄이 없는지도 눈으로 본다(스크립트는 로그를 읽지 않는다).
  5. `--apply --confirm-stack <스택>`으로 실행한다. `BLOCKED`면 사유를 해소하고 다시 실행한다. `executions_no_data_metric_unknown`이면 함수 이름·리전을 확인하고, 최근 2주 동안 호출이 없던 함수라면 콘솔에서 실행이 없음을 직접 확인한 뒤 개발 담당과 상의한다(스크립트로는 통과시키지 않는다).
  6. 스크립트는 실행 뒤 매핑 상태를 한 번 더 읽어, 실행 중에 누가 매핑을 켰으면 `WARNING`을 출력한다(쓴 항목은 조건부라 깨지지 않는다).
  7. `aws lambda update-event-source-mapping --uuid <UUID> --enabled`로 다시 켜고 `State = Enabled`를 확인한다. 꺼 둔 동안 들어온 메시지는 큐에 남아 있다가 처리된다(가시성·보존 기간 안).
  - 매핑 끄기·켜기는 운영 변경이다. AWS 담당이 하고 시각을 기록한다. 스크립트는 매핑을 바꾸지 않는다.
- 안전 확인을 통과한 뒤에 늦게 시작한 실행이 있더라도 데이터는 깨지지 않는다. 그 실행의 완료는 `photoStatus = PROCESSING` 조건이 맞지 않아 거부되고, 그 실행은 자기 처리본만 지운다. 다만 성공했을 사진이 `FAILED`로 보일 수 있다(사용자는 교체·글로 완료 가능).
- 복구 뒤 메시지: "복구 대상(적용됨)·이미 실패·지난 메시지"는 운영자가 판정을 확인한 뒤 직접 지운다(스크립트 실행 뒤 60초가 지나야 다시 보인다). "비정상"은 남겨 개발 담당에게 넘긴다. redrive는 원인을 고친 뒤 운영자가 판단해 한다(redrive된 메시지는 무시 조건으로 안전하게 끝난다).
- 운영자 권한: PhotoDLQ `sqs:ReceiveMessage`, PhotoQueue `sqs:GetQueueAttributes`, HaruTable `dynamodb:GetItem`·`UpdateItem`, `cloudformation:DescribeStacks`·`DescribeStackResource`, `lambda:ListEventSourceMappings`(`--apply` 필수), `cloudwatch:GetMetricStatistics`(`--apply` 필수, dry-run은 선택), `cloudwatch:ListMetrics`(`--apply` 필수). 매핑 절차에는 `lambda:GetEventSourceMapping`·`UpdateEventSourceMapping`.

### 12.4 알려진 한계

- **스위치 꺼짐 동안 원본 불변성 미보장**(BE-Q65): presigned URL 유효 10분 동안 같은 키를 다시 PUT할 수 있다. 처리 Lambda의 ETag `IfMatch`는 "읽은 바이트 = 그 이벤트가 가리킨 객체"만 보장한다. 그래서 전달 뒤 원본이 다른 내용으로 바뀌어 있을 수 있고(원본은 응답에 나가지 않는다), 나중에 올린 사진이 아니라 먼저 올린 사진이 전달될 수 있다. 서명이 `Content-Type`·`Content-Length`를 고정하므로 길이가 같은 내용으로만 덮어쓸 수 있다. 스위치를 켜야 없어진다.
- **고아 처리본**(BE-Q67): 완료 결과가 불확실한 시도, 강제 종료, 진 시도의 삭제 실패로 `photos/processed/`에 전달되지 않은 객체가 남을 수 있다. 수신함에는 보이지 않는다. 자동 정리와 `processed/` 일괄 만료는 두지 않았다(전달된 처리본을 지우지 않기 위해). 확인하려면 Claim prefix의 객체 목록을 Record `processedKey`와 대조한다.
- **강제 종료**: Lambda 타임아웃·메모리 부족이면 코드가 `FAILED`를 쓰지 못한다. 3회 뒤 DLQ로 가고 Record는 `PROCESSING`으로 남는다(12.3절).
- **중첩 재시도**(BE-Q71): `complete_claim` 루프 × `transact_with_retry` × SDK 재시도로 완료 호출 1번이 시간 예산을 크게 넘을 수 있다. guard는 완료를 시작할지만 정하므로 이 경우 Lambda가 타임아웃으로 끝날 수 있다(결과는 재전달 뒤 재조회로 판정). 3단계 코드는 바꾸지 않았다.
- presigned URL은 Lambda 역할의 임시 자격 증명으로 서명하므로 실제 유효 시간이 10분보다 짧을 수 있다(BE-Q72). 업로드 403이면 `POST /record/photo`로 새 URL을 받는다.

### 12.5 지표 해석

- `PhotoProcessingMs`(단위 Milliseconds): 전달에 성공한 처리 시도의 소요 시간(무시·실패·미전달 시도는 기록하지 않는다). `PhotoFailed`(Count): 조건부 `FAILED`를 실제로 쓴 횟수(검사 실패, `RETRY_EXHAUSTED`).
- **`CompleteDuplicate`는 API 중복 완료와 처리 Lambda 경로가 섞인다**(BE-Q63). 처리 Lambda가 이미 완료된 Claim에 `complete_claim`을 부르면(같은 원본 이벤트의 중복 실행, 처리 중 `TEXT_ONLY` 완료 등) 3단계 동작대로 1 오른다. 이 값만으로 사용자 재시도 횟수를 판단하지 않는다.

### 12.6 미결 질문 (5단계)

전체는 [docs/08](../docs/08-open-questions.md) §8.1. BE-Q34·BE-Q42는 해소, BE-Q2는 BE-Q66과 함께 정리했다. BE-Q45·BE-Q46·BE-Q48은 바꾸지 않았다.

| # | 상태 |
|---|---|
| BE-Q49, BE-Q50, BE-Q53–BE-Q58, BE-Q60–BE-Q63 | 임시 결정으로 구현 |
| **BE-Q51, BE-Q52** | 권장안(`{ upload }` 200, Record 없으면 400 `RECORD_REQUIRED`)으로 구현, **프론트엔드 리뷰 대기** |
| BE-Q59, BE-Q66–BE-Q69 | 설계 확정으로 구현 |
| BE-Q64 | 로컬 구동으로 확인(5.5절) |
| **BE-Q65** | 스위치 뒤 구현, 기본 꺼짐, **프론트엔드 승인 대기** |
| BE-Q70, BE-Q71, BE-Q72 | AWS 판정·측정 뒤 정한다 |

### 12.7 대기 중인 작업

- 묶음 B 의존(작업 17, BE-Q46 승인과 묶음 B 병합 뒤): `GET /claims/{claimId}/record`로 `photoStatus`(`UPLOAD_PENDING` → `PROCESSING`/`FAILED`/`READY`)·`delivered`·`claimStatus` 폴링 확인(로컬·AWS), S3 연동 지점을 프론트에 전달.
- 프론트엔드 승인 의존(작업 18): BE-Q51·BE-Q52를 docs/03 §3.4에 적기, BE-Q65 승인 시 docs/03 `upload.headers`·업로드 실패 처리 반영과 dev `UploadIfNoneMatch=true`(AWS 담당과 함께). 거부되면 스위치를 끈 채 12.4절 첫 항목을 영구 한계로 적는다.
- 5단계 PR(작업 19): 2026-11-26 Draft PR #7로 열었다. Ready for Review 전환·병합은 하지 않았다.

### 12.8 변경 범위 확인 (`git diff feat/be-4-inbox`, PR 본문용)

- `src/domain/claim_service.py`: `claim_plan`·`abandon`·`complete_claim`·`complete_by_user`·`list_my_claims`·`_lookup`은 AST가 같다(본문 변경 0). 바뀐 함수는 `put_record`뿐이고 새 함수는 `_write_record`·`_active_claim_checks`(헬퍼 추출)·`put_record_with_photo`·`replace_photo`·`photo_status_update`. 사진 없는 `put_record`가 보내는 TransactWriteItems 항목은 변경 전과 같다(같은 입력으로 비교).
- `src/common/ddb.py`: `use_table` 추가뿐. `transact_with_retry` 변경 없음.
- `docs/03-api-contract.md`, `frontend/`: diff 0.
