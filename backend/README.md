# 이어온 하루 백엔드 — 인계 문서

AWS 계정 없이 개발한 백엔드를 AWS 담당이 배포·판정할 수 있도록 정리한 문서다. 역할 분담은 [docs/07 §7.8](../docs/07-development-plan.md), 명세는 [docs/](../docs/)와 spec(`.kiro/specs/`)이 기준이다.

## 1. 인계 상태 요약

| 항목 | 상태 |
|---|---|
| 범위 | 백엔드 1·2단계(인증, `GET /me`, 계획 생성·목록·상세, 멱등 키, 원문 충실도·개인정보 함수), **3단계**(이어받기·포기·완료 트랜잭션, 방문 기록 글 저장 최소 구현, `GET /me/claims`, EMF 지표 3종), **4단계**(수신함 4종, `GET /me`의 `unreadInboxCount`, `InboxFunction`). 4단계의 `GET /claims/{claimId}/record`는 계약 변경 승인 대기(BE-Q46, 3.3절·8절) |
| 브랜치 | 4단계 수신함: `feat/be-4-inbox`(`fix/be-3-local-verify` `8fcf239` 위, 이 PR). `GET /claims/{claimId}/record`는 이 브랜치에 없고 `feat/be-4-record-inbox`의 `f3626c0`에만 있다(BE-Q46 승인 전 PR 제외). 3단계까지: `feat/be-3-claim-transaction` ← `feat/be-1-2-foundation` ← `docs/monorepo-stage1-2-spec` |
| spec | `.kiro/specs/backend-stage1-2-foundation/`, `.kiro/specs/backend-stage3-claim/`, `.kiro/specs/backend-stage4-record-inbox/` |
| 단위 테스트 | `pytest tests/unit` 전부 통과(2026-11-25 로컬 검증: 289건, `_cleanup` 회귀 테스트 추가 후 296건). moto(인프로세스 DynamoDB 흉내)로 실제 조건식·갱신식·GSI 조회·트랜잭션 취소 사유를 확인. 3단계는 상태 전이 속성 테스트 포함 |
| 단위 테스트(4단계) | 2026-11-25 수신함 묶음까지 385건 통과(속성 기반 Property 18–23 포함) |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build` 성공. **2026-11-25 AWS 담당이 `haru-dev`에 배포**(3.1절). 4단계 템플릿은 2026-11-25 개발 담당이 SAM CLI 1.174.1로 `sam validate --lint`·`sam build`까지 확인했고 배포하지 않았다 |
| 로컬 환경(Docker) | **2026-11-25 첫 구동 성공**, `pytest -m local tests/local` 16건 통과(5절). 4단계 수신함 추가 후 23건 통과(5.4절). 판정 근거는 아니다(BE-Q15) |
| AWS 판정 | T1·T13·T3·T4·T5·T6·T7·T14·T16 **15건 모두 통과**(2026-11-25, `haru-dev`, AWS 담당). 첫 실행에서 T1 액세스 토큰 1건이 실패해 `common/auth.py`를 고친 뒤 다시 통과했다(3.1절) |
| AWS 판정(4단계) | T1 확장·T2·T17 테스트 코드 작성, **미실행**(3.3절). 배포와 실행은 AWS 담당 |
| 다음 단계 조건 | T3–T7이 AWS에서 통과해야 4단계를 시작한다(docs/07 §7.2). **2026-11-25 충족**. 4단계 이후 PR마다 `tests/integration/test_concurrency.py`를 다시 돌린다(docs/07 §7.2) |
| PR | 아직 열지 않았다(8절) |

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

### 5.4 4단계 로컬 통합 테스트 결과 (2026-11-25, 개발 담당)

| 항목 | 값 |
|---|---|
| 기준 | `feat/be-4-record-inbox`, `8fcf239` 위 4단계 수신함 묶음(커밋 전 작업 트리) |
| 실행 | `docker compose up -d --build`(api 이미지 재빌드) 후 `pytest -m local tests/local` |
| 결과 | **23건 통과**(기존 16건 + `test_local_inbox.py` 7건) |
| 확인한 것 | 완료 → 계획자 `GET /me` 미확인 1 → `GET /inbox` 1건 → 상세(사진 필드 null) → 읽음 204(재요청도 204) → 미확인 0 → 답장 201 → 두 번째 409. 실행자·제3자의 수신함 경로 404와 404 뒤 불변, 토큰 없음 401 |
| 고친 테스트 | `test_local_flow.py::test_me_with_dev_jwt`가 고정 사용자 ID 대신 새 사용자로 `unreadInboxCount == 0`을 확인한다(4단계부터 계산값) |

- Floci에서 수신함의 조건부 `UpdateItem`(읽음 `attribute_exists(PK) AND ownerId = :me`, 답장 `ownerId = :me AND attribute_not_exists(reply)`)이 계약대로 돈다. T 판정 근거는 아니다(BE-Q15).

## 6. 함수별 IAM 권한

| 함수 | 권한 | 이유 |
|---|---|---|
| `MeFunction` | `HaruTable`과 `index/*`에 `dynamodb:GetItem`, `Query` | `GET /me/claims`(GSI2 조회 + Plan·Record 읽기), `GET /me`의 미확인 수(기본 테이블 Query, `ConsistentRead`). 권한은 3단계 그대로다 |
| `PlansFunction` | `HaruTable`과 `index/*`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `Query` | 생성(Plan + 멱등 키 트랜잭션), 상세(ConsistentRead), 목록(GSI1), 내 Claim 조회, 이어받기(Plan Update + Claim·ClaimLookup Put + 이전 Claim Update) |
| `ClaimsFunction` | `HaruTable`에 `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `ConditionCheckItem` | 포기·기록·완료 트랜잭션(Update, InboxItem Put, 기록 저장의 ConditionCheck)과 ConsistentRead |
| `InboxFunction`(4단계) | `HaruTable`에 `dynamodb:GetItem`, `Query`, `UpdateItem`(`index/*` 없음) | 수신함 Query, 상세의 InboxItem·Plan·Record GetItem(ConsistentRead), 읽음·답장의 조건부 UpdateItem. InboxItem을 만들거나 지우지 않는다 |
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
| BE-Q34 | 3단계 `PUT /record`에 `photo`가 오면 400(`details.photo`). 5단계에서 해제 |
| BE-Q35 | `GET /me/claims`의 `status` 누락·잘못된 값은 400 |
| BE-Q36 | `claimId = clm_ + ULID`, 실행자 닉네임 속성 `claimerNickname` |
| BE-Q37 | EMF는 라이브러리 없이 직접 출력, 네임스페이스 `Haru`, 차원 없음 |
| BE-Q38 | AWS 판정 테스트가 DynamoDB를 직접 조회·갱신(T5·T6 건수, T14 `dueAt`) |
| BE-Q39 | `COMPLETED` 계획 이어받기는 409 `ALREADY_CLAIMED` |
| BE-Q40 | 완료 Record 조건에 방어 조건 2개 추가(`deliveredAt` 없음, 읽은 `photoStatus` 일치) |
| BE-Q41 | `GET /me/claims`는 GSI2라 방금 이어받은 Claim이 잠깐 빠질 수 있음 |
| BE-Q42 | `GET /inbox/{itemId}`의 `photoUrl`·`photoCaption`은 5단계 전까지 null |
| BE-Q43 | InboxItem 응답에 `ownerId`를 내보내지 않음 |
| BE-Q44 | 이미 읽은 항목의 읽음 재요청도 204 |
| BE-Q45 | InboxItem `claimerNickname`은 null일 수 있다(프론트 타입은 `string`). 계약·프론트 타입은 바꾸지 않았고 팀이 정한다 |
| BE-Q46 | `GET /claims/{claimId}/record`는 TransactGetItems 스냅샷 + 충돌 재시도 소진 시 503 `TRY_AGAIN`(권장안). docs/03 §3.4 명시는 **프론트엔드 담당 승인 대기**(8절) |
| BE-Q47 | InboxItem은 있는데 Plan·Record가 없는 등 정상 경로에 없는 상태는 500 `INTERNAL_ERROR` |
| BE-Q48 | botocore `Config`(연결·읽기 타임아웃, 재시도)와 Lambda 타임아웃 10초. 지정하지 않음(기존 상태 유지). 연결이 멈추거나 스로틀링이 길면 10초를 넘어 코드 없는 500이 될 수 있다 |

### S2(프론트 글 경로 실제 API 전환)에 넘기는 경로

- 지금 쓸 수 있는 것: `GET /me`(`unreadInboxCount` 계산), `GET /me/claims`, `PUT /claims/{claimId}/record`(글만), `POST /claims/{claimId}/complete`, `POST /claims/{claimId}/abandon`, `GET /inbox`, `GET /inbox/{itemId}`, `POST /inbox/{itemId}/read`, `POST /inbox/{itemId}/reply`.
- 승인 대기: `GET /claims/{claimId}/record`(BE-Q46). 503 `TRY_AGAIN`이 나올 수 있어 프론트 처리 확인이 필요하다(8절).

### 5단계로 넘기는 것

- 4단계에서 끝낸 것: 수신함 API, `unreadInboxCount`. `GET /claims/{claimId}/record`는 BE-Q46 결정 뒤 반영한다.
- `GET /inbox/{itemId}`의 `photoUrl`(15분 presigned GET)·`photoCaption`(BE-Q42 해제).
- 5단계: `PUT /record`의 `photo`(BE-Q34 해제), 사진 교체, 사진 처리 Lambda는 `claim_service.complete_claim(claim_id, "WITH_PHOTO", key, processed_key)`를 부른다. 사진 키가 다르거나 `PROCESSING`이 아니면 `CLAIM_NOT_ACTIVE`가 오므로 "무시하고 처리본 삭제"로 처리한다(docs/02 §2.7).
- 5단계 주의: 포기 트랜잭션 직전에 생긴 Record와 기한 지난 대체(`EXPIRED`)는 Record의 `photoStatus`를 `DISCARDED`로 바꾸지 않는다. 사진 처리는 Claim 상태를 확인하므로 전달되지는 않는다.

## 8. 리뷰가 필요한 것과 PR

PR은 아직 열지 않았다. 리뷰할 때 아래 순서로 연다.

1. `docs/monorepo-stage1-2-spec` → `main`: 문서·spec
2. `feat/be-1-2-foundation` → `docs/monorepo-stage1-2-spec`(1이 병합되면 `main`): 1·2단계 코드
3. (3단계 인계 후) `feat/be-3-claim-transaction` → `feat/be-1-2-foundation`
4. `fix/be-3-aws-verify` → `feat/be-3-claim-transaction`: AWS 판정 중 고친 `token_use` 확인과 판정 기록(3.1절)
5. `fix/be-3-local-verify` → `fix/be-3-aws-verify`: 로컬 테스트 수정, `_cleanup` 보완(3.2절), 로컬 구동 기록(5절)

6. (4단계) `feat/be-4-inbox` → `fix/be-3-local-verify`: 수신함 묶음(계약 변경 없음). `GET /claims/{claimId}/record` 구현(`feat/be-4-record-inbox`의 `f3626c0`)은 BE-Q46 승인 전에는 이 PR에 넣지 않는다

비교 링크: `https://github.com/creatingweb123/knu-aws-2026/compare/<기준>...<브랜치>`

3번 PR에는 3단계 spec(`.kiro/specs/backend-stage3-claim/`)과 docs/08 BE-Q34–BE-Q41 추가가 함께 들어 있다. spec은 리뷰 에이전트 검토를 한 번 거쳤다(지적 16건 반영, 반영 결과는 spec 미결 사항에 있다).

계약 변경(docs/07 §7.2, §7.8에 따라 다른 팀원 한 명이 리뷰):

- 시간 형식을 밀리초 3자리로 고정(docs/03 공통 규칙에 반영)
- API Gateway가 거부한 401은 본문 형식이 다르다(requirements 1.7, docs/03 §3.6 401 행에 반영)
- BE-Q23·BE-Q24·BE-Q29·BE-Q33의 임시 결정
- **BE-Q46(4단계, 프론트엔드 담당 승인 필요)**: docs/03 §3.4 `GET /claims/{claimId}/record`에 "Claim·Record를 한 시점으로 읽는 트랜잭션 조회가 충돌 재시도(최초 1회 + 재시도 최대 3회, 누적 대기 175–350ms)를 모두 소진하면 503 `TRY_AGAIN`"을 적는 변경. 함께 볼 것: 스로틀링이나 충돌과 다른 사유가 섞인 취소를 503으로 볼지(지금은 500), 거부하면 대안 A(GetItem 2회, 불일치 허용)로 설계를 바꾼다. 승인 전에는 docs/03을 고치지 않았다
- BE-Q45: InboxItem `claimerNickname` null 가능과 프론트 타입 `string`의 불일치

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
