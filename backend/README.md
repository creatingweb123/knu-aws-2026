# 이어온 하루 백엔드 — 인계 문서

AWS 계정 없이 개발한 백엔드를 AWS 담당이 배포·판정할 수 있도록 정리한 문서다. 역할 분담은 [docs/07 §7.8](../docs/07-development-plan.md), 명세는 [docs/](../docs/)와 spec(`.kiro/specs/`)이 기준이다.

## 1. 인계 상태 요약

| 항목 | 상태 |
|---|---|
| 범위 | 백엔드 1·2단계(인증, `GET /me`, 계획 생성·목록·상세, 멱등 키, 원문 충실도·개인정보 함수)와 **3단계**(이어받기·포기·완료 트랜잭션, 방문 기록 글 저장 최소 구현, `GET /me/claims`, EMF 지표 3종) |
| 브랜치 | 3단계까지: `feat/be-3-claim-transaction` ← `feat/be-1-2-foundation` ← `docs/monorepo-stage1-2-spec` |
| spec | `.kiro/specs/backend-stage1-2-foundation/`, `.kiro/specs/backend-stage3-claim/` |
| 단위 테스트 | `pytest tests/unit` 전부 통과(2026-11-25 로컬 검증: 289건, `_cleanup` 회귀 테스트 추가 후 296건). moto(인프로세스 DynamoDB 흉내)로 실제 조건식·갱신식·GSI 조회·트랜잭션 취소 사유를 확인. 3단계는 상태 전이 속성 테스트 포함 |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build` 성공. **2026-11-25 AWS 담당이 `haru-dev`에 배포**(3.1절) |
| 로컬 환경(Docker) | **2026-11-25 첫 구동 성공**, `pytest -m local tests/local` 16건 통과(5절). 판정 근거는 아니다(BE-Q15) |
| AWS 판정 | T1·T13·T3·T4·T5·T6·T7·T14·T16 **15건 모두 통과**(2026-11-25, `haru-dev`, AWS 담당). 첫 실행에서 T1 액세스 토큰 1건이 실패해 `common/auth.py`를 고친 뒤 다시 통과했다(3.1절) |
| 다음 단계 조건 | T3–T7이 AWS에서 통과해야 4단계를 시작한다(docs/07 §7.2). **2026-11-25 충족** |
| PR | 1–3단계 PR #2–#6, 6a Draft PR #8이 열려 있다. 병합된 것은 없다(2026-11-26, 8절) |
| **6a단계(AI 레벨 0)** | 브랜치 `feat/be-6a-ai-pipeline`(기준 `fix/be-3-local-verify`), **Draft PR #8**(https://github.com/creatingweb123/knu-aws-2026/pull/8, 2026-11-26 생성, 리뷰 전), spec `.kiro/specs/backend-stage6a-ai-pipeline/`. 개발 PC에서 구현·검증까지 마쳤고 **AWS 배포·판정은 아직 없다**(10절) |
| **6b단계(AI 에이전트)** | 브랜치 `feat/be-6b-ai-agent`(기준 `feat/be-6a-ai-pipeline`), spec `.kiro/specs/backend-stage6b-ai-agent/`. 작업 1–19 구현·개발 PC 검증까지. **PR·AWS 배포·판정은 아직 없다**. 실제 공급자 검증(작업 20.2–20.4)은 2026-11-27에 GPT-6 Luna 게이트웨이로 끝냈다(11.12절, 출시 모드 제안 11.13절) |

AWS에서만 확인되는 것은 4절, 로컬 환경 구동 기록과 절차는 5절, 테스트 데이터 정리 보완은 3.2절에 있다.

## 2. 배포 런북 (AWS 담당)

### 2.1 준비

- 리전: `ap-northeast-2`
- 도구: AWS CLI v2, AWS SAM CLI(1.174.0에서 확인), Python 3.12. Windows에서 `sam build`는 PATH의 `python`이 3.12여야 한다(가상 환경을 켜거나 `--use-container`).
- Windows에서는 SAM 명령 전에 `set PYTHONUTF8=1`(PowerShell은 `$env:PYTHONUTF8 = "1"`)을 한다. 안 하면 SAM이 `samconfig.toml`의 한글 주석을 cp1252로 읽다가 `UnicodeDecodeError`로 멈춘다(2026-11-25 확인).
- `aws login`으로 받은 자격 증명으로 통합 테스트(boto3)를 돌리려면 `botocore[crt]`가 필요하다. `requirements-dev.txt`에 포함했다. 없으면 `MissingDependencyException`으로 모든 테스트가 시작 전에 멈춘다.
- **배포 전에 AWS Budgets 월 알림을 먼저 건다**(BE-Q11, 금액은 팀이 정한다).
- 배포하는 IAM 주체에 필요한 권한: CloudFormation, IAM 역할 생성·연결(`CAPABILITY_IAM`), Lambda, API Gateway(HTTP API), Cognito User Pool, DynamoDB, S3(SAM 아티팩트 버킷, `resolve_s3`가 `aws-sam-cli-managed-default` 스택을 만든다), CloudWatch Logs.
- 통합 테스트를 돌리는 주체에 필요한 권한: `cloudformation:DescribeStacks`, `cloudformation:DescribeStackResource`, `cognito-idp:AdminCreateUser`, `AdminSetUserPassword`, `AdminDeleteUser`, `dynamodb:GetItem`, `dynamodb:Query`, `dynamodb:UpdateItem`(T14의 `dueAt` 변경), `dynamodb:DeleteItem`(정리, 대상 테이블만).

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
- 결과 로그(`test-results/`)는 이 PC에만 있다. 저장소에 넣을지, 따로 보관할지 팀이 정한다.

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
| `local/init/01_haru.py` | 테이블 2개, 유저 풀(ID 고정), 시드 사용자 3명 | `tests/unit/test_local_init.py` |
| `local/adapter/app.py` | payload 2.0 변환, JWT 검증, `/dev/token`, CORS | `tests/unit/test_adapter.py` |
| `tests/local/` | 로컬 통합 테스트(`pytest -m local`) | — |

실행하며 확인할 것:

1. `docker pull floci/floci:2.5.0-compat`가 받아지는지. 안 되면 Docker Desktop 프록시·로그인, 네트워크를 확인한다.
2. `cp .env.example .env`(Windows `copy`) 후 `docker compose up -d --build`.
3. `docker compose logs aws`에 `ok step=...` 다섯 줄과 `LOCAL_USER_POOL_ID=ap-northeast-2_haruLocal`이 보이는지. `WARNING 고정 ID가 적용되지 않았다`가 나오면 로그의 값으로 `.env`를 고친 뒤 `docker compose up -d`로 `api`를 다시 띄운다.
4. `docker compose logs api`에 `listening port=3000`이 보이는지.
5. `pytest -m local tests/local -s`가 통과하는지. `test_seed_user_login_and_me_nickname`이 BE-Q17(Floci ID 토큰의 `nickname`·`aud`·`token_use`) 결과를 출력한다. 실패하면 dev JWT 경로(`POST /dev/token`)만 쓰고 결과를 docs/08 BE-Q17·FE-Q8에 적는다.
6. 끄기: `docker compose down`(데이터 유지), `docker compose down -v`(데이터 삭제).

Docker 없이 확인한 대체 수단: moto 테스트(`tests/unit/test_plan_service_moto.py`, `test_claim_service_moto.py`, `test_claim_properties.py`, `test_handlers_claims.py`)가 실제 DynamoDB 조건식·취소 사유 코드·GSI 조회를 확인한다. moto와 Floci 모두 실제 병렬성은 재현하지 않으므로 동시성 판정은 AWS에서만 한다.

## 6. 함수별 IAM 권한

| 함수 | 권한 | 이유 |
|---|---|---|
| `MeFunction` | `HaruTable`과 `index/*`에 `dynamodb:GetItem`, `Query` | `GET /me/claims`(GSI2 조회 + Plan·Record 읽기). `GET /me`는 4단계 전까지 DB를 읽지 않는다(BE-Q30) |
| `PlansFunction` | `HaruTable`과 `index/*`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `Query` | 생성(Plan + 멱등 키 트랜잭션), 상세(ConsistentRead), 목록(GSI1), 내 Claim 조회, 이어받기(Plan Update + Claim·ClaimLookup Put + 이전 Claim Update) |
| `ClaimsFunction` | `HaruTable`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `ConditionCheckItem` | 포기·기록·완료 트랜잭션(Update, InboxItem Put, 기록 저장의 ConditionCheck)과 ConsistentRead |
| `AiCardFunction`(6a) | `HaruTable`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`, 조건 `dynamodb:LeadingKeys` = `AISESSION#*`·`AIQUOTA#*`. `LlmApiKeyParam`이 있으면 그 파라미터 ARN 하나에 `ssm:GetParameter` | 세션 저장·조회, 하루 할당량 조건부 갱신. `Query`·`Scan`·트랜잭션·`index/*`·`kms:*` 없음(`aws/ssm` 관리형 키는 KMS 권한이 따로 필요 없다). Plan·User·Claim·Idem 키에는 쓰지 못한다(G6) |
| `AiCardFunction`(6b 추가) | `HaruAgentCheckpoints`에만 `dynamodb:GetItem`, `PutItem`, `Query`, `BatchGetItem`, `BatchWriteItem`(조건 없음, `index/*` 없음) | 체크포인트 라이브러리(`langgraph-checkpoint-aws` 1.3.0)가 쓰는 연산 5개뿐이다(프로토타입 V9). `delete_thread`는 BatchWriteItem의 DeleteRequest를 쓴다. `DeleteItem`·`Scan`·`UpdateItem` 없음. 다른 함수에는 이 테이블 권한이 없다 |
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
| BE-Q30 | `unreadInboxCount` 0 고정 |
| BE-Q33 | `currentClaimId`는 응답에 내보내지 않음 |
| BE-Q34 | 3단계 `PUT /record`에 `photo`가 오면 400(`details.photo`). 5단계에서 해제 |
| BE-Q35 | `GET /me/claims`의 `status` 누락·잘못된 값은 400 |
| BE-Q36 | `claimId = clm_ + ULID`, 실행자 닉네임 속성 `claimerNickname` |
| BE-Q37 | EMF는 라이브러리 없이 직접 출력, 네임스페이스 `Haru`, 차원 없음 |
| BE-Q38 | AWS 판정 테스트가 DynamoDB를 직접 조회·갱신(T5·T6 건수, T14 `dueAt`) |
| BE-Q39 | `COMPLETED` 계획 이어받기는 409 `ALREADY_CLAIMED` |
| BE-Q40 | 완료 Record 조건에 방어 조건 2개 추가(`deliveredAt` 없음, 읽은 `photoStatus` 일치) |
| BE-Q41 | `GET /me/claims`는 GSI2라 방금 이어받은 Claim이 잠깐 빠질 수 있음 |

### 4·5단계로 넘기는 것

- 4단계: `GET /claims/{claimId}/record`(BE-Q1 403 포함), 수신함 API, `unreadInboxCount`. 3단계의 `put_record`를 이어받아 완성한다. 3단계는 수신함 항목을 만들기만 한다.
- 5단계: `PUT /record`의 `photo`(BE-Q34 해제), 사진 교체, 사진 처리 Lambda는 `claim_service.complete_claim(claim_id, "WITH_PHOTO", key, processed_key)`를 부른다. 사진 키가 다르거나 `PROCESSING`이 아니면 `CLAIM_NOT_ACTIVE`가 오므로 "무시하고 처리본 삭제"로 처리한다(docs/02 §2.7).
- 5단계 주의: 포기 트랜잭션 직전에 생긴 Record와 기한 지난 대체(`EXPIRED`)는 Record의 `photoStatus`를 `DISCARDED`로 바꾸지 않는다. 사진 처리는 Claim 상태를 확인하므로 전달되지는 않는다.

## 8. 리뷰가 필요한 것과 PR

2026-11-26 기준 아래 PR이 모두 열려 있고 병합된 것은 없다(1번부터 PR #2–#6, 6번이 Draft PR #8). 4단계는 PR #1, 5단계는 Draft PR #7이다. 리뷰·병합은 아래 순서로 한다.

1. `docs/monorepo-stage1-2-spec` → `main`: 문서·spec
2. `feat/be-1-2-foundation` → `docs/monorepo-stage1-2-spec`(1이 병합되면 `main`): 1·2단계 코드
3. (3단계 인계 후) `feat/be-3-claim-transaction` → `feat/be-1-2-foundation`
4. `fix/be-3-aws-verify` → `feat/be-3-claim-transaction`: AWS 판정 중 고친 `token_use` 확인과 판정 기록(3.1절)
5. `fix/be-3-local-verify` → `fix/be-3-aws-verify`: 로컬 테스트 수정, `_cleanup` 보완(3.2절), 로컬 구동 기록(5절)
6. (6a) `feat/be-6a-ai-pipeline` → `fix/be-3-local-verify`: **Draft PR #8**. 4단계(PR #1)·5단계(PR #7)와 독립 브랜치이고, 선행 PR이 병합되면 merge로 통합한다(10.8절)

비교 링크: `https://github.com/creatingweb123/knu-aws-2026/compare/<기준>...<브랜치>`

3번 PR에는 3단계 spec(`.kiro/specs/backend-stage3-claim/`)과 docs/08 BE-Q34–BE-Q41 추가가 함께 들어 있다. spec은 리뷰 에이전트 검토를 한 번 거쳤다(지적 16건 반영, 반영 결과는 spec 미결 사항에 있다).

계약 변경(docs/07 §7.2, §7.8에 따라 다른 팀원 한 명이 리뷰):

- 시간 형식을 밀리초 3자리로 고정(docs/03 공통 규칙에 반영)
- API Gateway가 거부한 401은 본문 형식이 다르다(requirements 1.7, docs/03 §3.6 401 행에 반영)
- BE-Q23·BE-Q24·BE-Q29·BE-Q33의 임시 결정

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

1. **SecureString을 먼저 만든다**(템플릿이 만들지 않는다, BE-Q81). CloudFormation은 SecureString을 만들 수 없다. 표준 계층, AWS 관리형 키 `aws/ssm`, 이름 `/haru/<stage>/llm/api-key`. 값이 셸 기록에 남지 않게 한다.
   ```bash
   read -rs LLM_KEY && printf '%s' "$LLM_KEY" > /dev/shm/k && \
   aws ssm put-parameter --name /haru/dev/llm/api-key --type SecureString --value file:///dev/shm/k && rm -f /dev/shm/k; unset LLM_KEY
   ```
2. 빌드는 **`sam build --use-container`**(AiCardFunction은 `Metadata.BuildMethod: makefile`, `src/Makefile`).
3. `AgentMode`는 6a에서 `pipeline`만 허용했다. 6b 브랜치는 `agent`를 연다(11.2절). 그 밖의 값은 배포가 거부되고, 함수 환경 값이 다르면 할당량 전에 503.
4. 공급자 값(`LlmBaseUrl`·`LlmModel`·`LlmApiKeyParam`·`LlmProviderLabel`)은 BE-Q6 전까지 비어 있다. 비어 있으면 `openai_compat`은 `CONFIG`로 503이 되고 사연은 나가지 않는다.
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
# 끝나면 기본 설정(pipeline, fake)으로 되돌린다
docker compose up -d --no-deps --force-recreate api
```

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

