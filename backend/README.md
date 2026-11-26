# 이어온 하루 백엔드 — 인계 문서

AWS 계정 없이 개발한 백엔드를 AWS 담당이 배포·판정할 수 있도록 정리한 문서다. 역할 분담은 [docs/07 §7.8](../docs/07-development-plan.md), 명세는 [docs/](../docs/)와 spec(`.kiro/specs/`)이 기준이다.

## 1. 인계 상태 요약

| 항목 | 상태 |
|---|---|
| 범위 | 백엔드 1·2단계(인증, `GET /me`, 계획 생성·목록·상세, 멱등 키, 원문 충실도·개인정보 함수), **3단계**(이어받기·포기·완료 트랜잭션, 방문 기록 글 저장 최소 구현, `GET /me/claims`, EMF 지표 3종), **4단계**(수신함 4종, `GET /me`의 `unreadInboxCount`, `InboxFunction`), **5단계**(사진 업로드 URL·교체, 사진 처리 Lambda·큐·DLQ, 수신함 `photoUrl`·`photoCaption`, 운영자 복구 스크립트, 10절). 4단계의 `GET /claims/{claimId}/record`는 계약 변경 승인 대기(BE-Q46, 3.3절·8절) |
| 브랜치 | 4단계 수신함: `feat/be-4-inbox`(`fix/be-3-local-verify` `8fcf239` 위, 이 PR). `GET /claims/{claimId}/record`는 이 브랜치에 없고 `feat/be-4-record-inbox`의 `f3626c0`에만 있다(BE-Q46 승인 전 PR 제외). 3단계까지: `feat/be-3-claim-transaction` ← `feat/be-1-2-foundation` ← `docs/monorepo-stage1-2-spec` |
| 브랜치(5단계) | `feat/be-5-photo-pipeline`(`feat/be-4-inbox` `dc3af68` 위, 커밋 8개). **push·PR 전**(사용자 확인 대기). 묶음 B(`f3626c0`)는 들어 있지 않다 |
| spec | `.kiro/specs/backend-stage1-2-foundation/`, `.kiro/specs/backend-stage3-claim/`, `.kiro/specs/backend-stage4-record-inbox/`, `.kiro/specs/backend-stage5-photo-pipeline/` |
| 단위 테스트 | `pytest tests/unit` 전부 통과(2026-11-25 로컬 검증: 289건, `_cleanup` 회귀 테스트 추가 후 296건). moto(인프로세스 DynamoDB 흉내)로 실제 조건식·갱신식·GSI 조회·트랜잭션 취소 사유를 확인. 3단계는 상태 전이 속성 테스트 포함 |
| 단위 테스트(4단계) | 2026-11-25 수신함 묶음까지 385건 통과(속성 기반 Property 18–23 포함) |
| 단위 테스트(5단계) | 2026-11-25 `pytest tests/unit` **625건 통과**, `pytest -m slow tests/unit` 2건 통과(40MP 메모리 측정). 속성 기반 Property 25–28 각 100예시 통과(P27은 600예시로 한 번 더 통과) |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build` 성공. **2026-11-25 AWS 담당이 `haru-dev`에 배포**(3.1절). 4단계 템플릿은 2026-11-25 개발 담당이 SAM CLI 1.174.1로 `sam validate --lint`·`sam build`까지 확인했고 배포하지 않았다. 5단계 템플릿은 `cfn-lint` 0건, `sam validate --lint` 통과, **`sam build --use-container` 성공**(Pillow 레이어, 10.2절), 배포하지 않았다 |
| 로컬 환경(Docker) | **2026-11-25 첫 구동 성공**, `pytest -m local tests/local` 16건 통과(5절). 4단계 수신함 추가 후 23건 통과(5.4절). 5단계 추가 후 28건 통과·8건 사유 skip(5.5절). 판정 근거는 아니다(BE-Q15) |
| AWS 판정 | T1·T13·T3·T4·T5·T6·T7·T14·T16 **15건 모두 통과**(2026-11-25, `haru-dev`, AWS 담당). 첫 실행에서 T1 액세스 토큰 1건이 실패해 `common/auth.py`를 고친 뒤 다시 통과했다(3.1절) |
| AWS 판정(4단계) | T1 확장·T2·T17 테스트 코드 작성, **미실행**(3.3절). 배포와 실행은 AWS 담당 |
| AWS 판정(5단계) | T8·T9·T10·T11·T15, 재업로드, IAM·CORS, 주입 차단 테스트 코드 작성, 수집만 확인하고 **미실행**(3.4절) |
| 다음 단계 조건 | T3–T7이 AWS에서 통과해야 4단계를 시작한다(docs/07 §7.2). **2026-11-25 충족**. 4단계 이후 PR마다 `tests/integration/test_concurrency.py`를 다시 돌린다(docs/07 §7.2) |
| PR | 2026-11-25 6개 열림(#1–#6), 병합 전(8절) |

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

4단계에서 넘긴 항목(BE-Q34·BE-Q42 해제, 사진 처리 Lambda의 `complete_claim` 호출)은 5단계에서 구현했다(10절). 포기·기한 대체 뒤의 Record `photoStatus`는 여전히 `DISCARDED`로 바꾸지 않고, 처리 Lambda가 Claim 상태(`ABANDONED`·`EXPIRED`)를 보고 "전달 안 됨"으로 끝낸다. 5단계 미결 질문은 10.6절.

## 8. 리뷰가 필요한 것과 PR

2026-11-25 아래 PR 6개를 열었다. **아직 병합하지 않았다.** 위에서부터 차례로 병합하고, 하나가 병합되면 다음 PR의 base를 병합된 쪽(결국 `main`)으로 바꾼다. 병합 전 리뷰와 승인은 docs/07 §7.2·§7.8을 따른다.

| 순서 | PR | head → base | 내용 | 단위 테스트(head에서 2026-11-25 재실행) | AWS 판정 |
|---|---|---|---|---|---|
| 1 | [#2](https://github.com/creatingweb123/knu-aws-2026/pull/2) | `docs/monorepo-stage1-2-spec` → `main` | 문서·steering·1·2단계 spec | 해당 없음 | 해당 없음 |
| 2 | [#3](https://github.com/creatingweb123/knu-aws-2026/pull/3) | `feat/be-1-2-foundation` → `docs/monorepo-stage1-2-spec` | 1·2단계 코드, SAM, 로컬 환경 | 225 passed | T1·T13 통과(2026-11-25) |
| 3 | [#4](https://github.com/creatingweb123/knu-aws-2026/pull/4) | `feat/be-3-claim-transaction` → `feat/be-1-2-foundation` | 3단계 트랜잭션 G1–G4 | 284 passed | T3–T7·T14·T16 통과 |
| 4 | [#5](https://github.com/creatingweb123/knu-aws-2026/pull/5) | `fix/be-3-aws-verify` → `feat/be-3-claim-transaction` | `token_use` 확인, 판정 기록(3.1절) | 289 passed | 수정 후 15건 통과 |
| 5 | [#6](https://github.com/creatingweb123/knu-aws-2026/pull/6) | `fix/be-3-local-verify` → `fix/be-3-aws-verify` | 로컬 테스트 수정, `_cleanup` 보완(3.2절), 로컬 기록(5절) | 296 passed | `_cleanup` 보완은 미실행 |
| 6 | [#1](https://github.com/creatingweb123/knu-aws-2026/pull/1) | `feat/be-4-inbox` → `fix/be-3-local-verify` | 4단계 수신함(묶음 A, 계약 변경 없음) | 385 passed | 미실행(3.3절) |

- 묶음 B(`GET /claims/{claimId}/record`, `feat/be-4-record-inbox`의 `f3626c0`)는 PR을 열지 않았다. BE-Q46 승인과 docs/03 §3.4 수정 PR이 먼저다.
- 5단계(`feat/be-5-photo-pipeline`, base 예정 `feat/be-4-inbox`)는 **push·PR 전**이다. 사용자 확인 뒤 연다(작업 19). PR 본문에는 10.8절 변경 범위 확인 결과를 넣는다.
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

## 10. 5단계 사진 파이프라인

spec: `.kiro/specs/backend-stage5-photo-pipeline/`(requirements·design·tasks). 흐름은 docs/02 §2.7: `PUT /record`(photo) → presigned PUT → S3 알림 → `PhotoQueue` → `PhotoProcessorFunction` → 3단계 `complete_claim(WITH_PHOTO)`. 전달 1회는 3단계 완료 트랜잭션이 지킨다(G2·G4). 처리 Lambda는 그 앞에서 처리해도 되는지 거르고, 뒤에서 `ConsistentRead`로 결과를 확인해 자기 처리본만 정리한다.

### 10.1 현황 (2026-11-25)

| 항목 | 상태 |
|---|---|
| 브랜치·커밋 | `feat/be-5-photo-pipeline`: `819dcfb` spec, `74c92dd` 공통·이미지, `430dc8f` API, `593a8f6` 처리 Lambda, `6cd4178` 복구 스크립트, `25ded68` 템플릿, `cfc65a7` 로컬, `40a767f` AWS 테스트, 이 문서 커밋. push 안 함 |
| 단위 테스트 | 625건 통과, `-m slow` 2건 통과. Property 25(처리본 규칙)·26(거부 사유)·27(전달 1회·현재 사진)·28(업로드 URL·교체) 각 100예시 |
| 이미지 측정(`test_photo_memory.py`, 별도 프로세스) | 40MP JPEG 최대 상주 104.8MB·303ms, 40MP PNG 325.3MB·947ms. 한도 717MB(1024MB의 70%) 안(BE-Q56) |
| 중첩 재시도 상한(`test_photo_retry_budget.py`) | 완료 호출 1번이 최대 GetItem 16회·TransactWriteItems 12회(합 28회), SDK 총 시도 2회면 56회. 시간 guard는 완료를 시작할지만 정한다(BE-Q71) |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build --use-container` 성공. 레이어에 Pillow 13.0.0 cp312 manylinux x86_64. Lambda 빌드 이미지 안에서 `process_image`(EXIF 제거)와 핸들러 import 확인. 다른 함수 빌드 결과에 Pillow 없음 |
| 로컬 | 5.5절 |
| AWS 판정 | 미실행(3.4절) |

### 10.2 배포 전 주의

- **`sam build --use-container`로 빌드한다.** Pillow 레이어(`layers/pillow/requirements.txt`)는 Lambda 빌드 이미지(python3.12, x86_64)에서 받아야 한다. 로컬 Docker가 없는 환경을 위해 `samconfig.toml`에는 넣지 않았다.
- 사진 버킷 이름은 `{스택 이름}-photos-{계정 ID}`로 고정이다. 스택 이름은 소문자·하이픈이어야 한다. 같은 이름의 버킷이 남아 있으면 배포가 실패한다. `sam delete` 전에 버킷을 비워야 한다(CloudFormation은 빈 버킷만 지운다. 비우는 것은 데이터 삭제이므로 AWS 담당이 확인 뒤 한다).
- `Stage` 파라미터: `samconfig.toml`의 dev는 `Stage=dev`, demo는 `Stage=demo`. 템플릿 기본값은 `demo`라 주입이 기본으로 막힌다.
- `FaultInject`는 `haru-dev`에서 판정할 때만 넘기고 판정 뒤 복원 배포한다(3.4절). 세 겹 차단(BE-Q59): `Rules FaultInjectOnlyInDev`, 조건 `FaultAllowed`(`Stage = dev` ∧ 실제 스택 이름 `haru-dev`), 런타임(`FAULT_INJECT_ALLOWED = "true"`이고 함수 이름이 `haru-dev-`로 시작). 다른 이름의 개인 dev 스택에서는 주입이 켜지지 않는다.
- `UploadIfNoneMatch`는 **프론트엔드 승인 전까지 `false`**다(BE-Q65). 켜면 `upload.headers`에 `If-None-Match: *`, 버킷 CORS 허용 헤더, 헤더 없는 원본 PUT을 거부하는 버킷 정책이 함께 켜진다.
- `PhotoDLQNotEmpty` 알람에는 알림 대상이 없다(BE-Q62). 콘솔·API로 상태를 본다.

### 10.3 운영자 복구 런북 (PhotoDLQ, BE-Q68)

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

### 10.4 알려진 한계

- **스위치 꺼짐 동안 원본 불변성 미보장**(BE-Q65): presigned URL 유효 10분 동안 같은 키를 다시 PUT할 수 있다. 처리 Lambda의 ETag `IfMatch`는 "읽은 바이트 = 그 이벤트가 가리킨 객체"만 보장한다. 그래서 전달 뒤 원본이 다른 내용으로 바뀌어 있을 수 있고(원본은 응답에 나가지 않는다), 나중에 올린 사진이 아니라 먼저 올린 사진이 전달될 수 있다. 서명이 `Content-Type`·`Content-Length`를 고정하므로 길이가 같은 내용으로만 덮어쓸 수 있다. 스위치를 켜야 없어진다.
- **고아 처리본**(BE-Q67): 완료 결과가 불확실한 시도, 강제 종료, 진 시도의 삭제 실패로 `photos/processed/`에 전달되지 않은 객체가 남을 수 있다. 수신함에는 보이지 않는다. 자동 정리와 `processed/` 일괄 만료는 두지 않았다(전달된 처리본을 지우지 않기 위해). 확인하려면 Claim prefix의 객체 목록을 Record `processedKey`와 대조한다.
- **강제 종료**: Lambda 타임아웃·메모리 부족이면 코드가 `FAILED`를 쓰지 못한다. 3회 뒤 DLQ로 가고 Record는 `PROCESSING`으로 남는다(10.3절).
- **중첩 재시도**(BE-Q71): `complete_claim` 루프 × `transact_with_retry` × SDK 재시도로 완료 호출 1번이 시간 예산을 크게 넘을 수 있다. guard는 완료를 시작할지만 정하므로 이 경우 Lambda가 타임아웃으로 끝날 수 있다(결과는 재전달 뒤 재조회로 판정). 3단계 코드는 바꾸지 않았다.
- presigned URL은 Lambda 역할의 임시 자격 증명으로 서명하므로 실제 유효 시간이 10분보다 짧을 수 있다(BE-Q72). 업로드 403이면 `POST /record/photo`로 새 URL을 받는다.

### 10.5 지표 해석

- `PhotoProcessingMs`(단위 Milliseconds): 전달에 성공한 처리 시도의 소요 시간(무시·실패·미전달 시도는 기록하지 않는다). `PhotoFailed`(Count): 조건부 `FAILED`를 실제로 쓴 횟수(검사 실패, `RETRY_EXHAUSTED`).
- **`CompleteDuplicate`는 API 중복 완료와 처리 Lambda 경로가 섞인다**(BE-Q63). 처리 Lambda가 이미 완료된 Claim에 `complete_claim`을 부르면(같은 원본 이벤트의 중복 실행, 처리 중 `TEXT_ONLY` 완료 등) 3단계 동작대로 1 오른다. 이 값만으로 사용자 재시도 횟수를 판단하지 않는다.

### 10.6 미결 질문 (5단계)

전체는 [docs/08](../docs/08-open-questions.md) §8.1. BE-Q34·BE-Q42는 해소, BE-Q2는 BE-Q66과 함께 정리했다. BE-Q45·BE-Q46·BE-Q48은 바꾸지 않았다.

| # | 상태 |
|---|---|
| BE-Q49, BE-Q50, BE-Q53–BE-Q58, BE-Q60–BE-Q63 | 임시 결정으로 구현 |
| **BE-Q51, BE-Q52** | 권장안(`{ upload }` 200, Record 없으면 400 `RECORD_REQUIRED`)으로 구현, **프론트엔드 리뷰 대기** |
| BE-Q59, BE-Q66–BE-Q69 | 설계 확정으로 구현 |
| BE-Q64 | 로컬 구동으로 확인(5.5절) |
| **BE-Q65** | 스위치 뒤 구현, 기본 꺼짐, **프론트엔드 승인 대기** |
| BE-Q70, BE-Q71, BE-Q72 | AWS 판정·측정 뒤 정한다 |

### 10.7 대기 중인 작업

- 묶음 B 의존(작업 17, BE-Q46 승인과 묶음 B 병합 뒤): `GET /claims/{claimId}/record`로 `photoStatus`(`UPLOAD_PENDING` → `PROCESSING`/`FAILED`/`READY`)·`delivered`·`claimStatus` 폴링 확인(로컬·AWS), S3 연동 지점을 프론트에 전달.
- 프론트엔드 승인 의존(작업 18): BE-Q51·BE-Q52를 docs/03 §3.4에 적기, BE-Q65 승인 시 docs/03 `upload.headers`·업로드 실패 처리 반영과 dev `UploadIfNoneMatch=true`(AWS 담당과 함께). 거부되면 스위치를 끈 채 10.4절 첫 항목을 영구 한계로 적는다.
- 5단계 PR(작업 19): 사용자 확인 뒤 push·PR.

### 10.8 변경 범위 확인 (`git diff feat/be-4-inbox`, PR 본문용)

- `src/domain/claim_service.py`: `claim_plan`·`abandon`·`complete_claim`·`complete_by_user`·`list_my_claims`·`_lookup`은 AST가 같다(본문 변경 0). 바뀐 함수는 `put_record`뿐이고 새 함수는 `_write_record`·`_active_claim_checks`(헬퍼 추출)·`put_record_with_photo`·`replace_photo`·`photo_status_update`. 사진 없는 `put_record`가 보내는 TransactWriteItems 항목은 변경 전과 같다(같은 입력으로 비교).
- `src/common/ddb.py`: `use_table` 추가뿐. `transact_with_retry` 변경 없음.
- `docs/03-api-contract.md`, `frontend/`: diff 0.
