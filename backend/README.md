# 이어온 하루 백엔드 — 인계 문서

AWS 계정 없이 개발한 백엔드를 AWS 담당이 배포·판정할 수 있도록 정리한 문서다. 역할 분담은 [docs/07 §7.8](../docs/07-development-plan.md), 명세는 [docs/](../docs/)와 spec(`.kiro/specs/`)이 기준이다.

## 1. 인계 상태 요약

| 항목 | 상태 |
|---|---|
| 범위 | 백엔드 1·2단계(인증, `GET /me`, 계획 생성·목록·상세, 멱등 키, 원문 충실도·개인정보 함수)와 **3단계**(이어받기·포기·완료 트랜잭션, 방문 기록 글 저장 최소 구현, `GET /me/claims`, EMF 지표 3종) |
| 브랜치 | 3단계까지: `feat/be-3-claim-transaction` ← `feat/be-1-2-foundation` ← `docs/monorepo-stage1-2-spec` |
| spec | `.kiro/specs/backend-stage1-2-foundation/`, `.kiro/specs/backend-stage3-claim/` |
| 단위 테스트 | `pytest tests/unit` 전부 통과. moto(인프로세스 DynamoDB 흉내)로 실제 조건식·갱신식·GSI 조회·트랜잭션 취소 사유를 확인. 3단계는 상태 전이 속성 테스트 포함 |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build` 성공. **2026-11-25 AWS 담당이 `haru-dev`에 배포**(3.1절) |
| 로컬 환경(Docker) | 코드는 작성했지만 **첫 실행 확인 필요**(5절) |
| AWS 판정 | T1·T13·T3·T4·T5·T6·T7·T14·T16 **15건 모두 통과**(2026-11-25, `haru-dev`, AWS 담당). 첫 실행에서 T1 액세스 토큰 1건이 실패해 `common/auth.py`를 고친 뒤 다시 통과했다(3.1절) |
| 다음 단계 조건 | T3–T7이 AWS에서 통과해야 4단계를 시작한다(docs/07 §7.2). **2026-11-25 충족** |
| PR | 아직 열지 않았다(8절) |

확인하지 못한 것은 5절(로컬 환경)과 4절(AWS에서만 확인되는 것)에 모았다.

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

- 테스트가 만든 Cognito 사용자와 Plan 항목은 끝나면 지운다.
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
- 결과 로그(`test-results/`)는 이 PC에만 있다. 저장소에 넣을지, 따로 보관할지 팀이 정한다.

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

## 5. 로컬 환경 첫 실행 확인 필요 (Docker)

개발 PC에서 `docker compose up -d --build`를 실행했지만 **Floci 이미지 다운로드에서 멈춰** 한 번도 띄우지 못했다(Docker Hub 접속 문제로 추정, 원인 미확인). 코드와 단위 테스트는 있다.

| 파일 | 역할 | 단위 테스트 |
|---|---|---|
| `docker-compose.yml` | `aws`(floci/floci:2.5.0-compat), `api`(로컬 어댑터) | — |
| `local/init/01_haru.py` | 테이블 2개, 유저 풀(ID 고정), 시드 사용자 3명 | `tests/unit/test_local_init.py` |
| `local/adapter/app.py` | payload 2.0 변환, JWT 검증, `/dev/token`, CORS | `tests/unit/test_adapter.py` |
| `tests/local/` | 로컬 통합 테스트(`pytest -m local`) | — |

처음 실행할 때 확인할 것:

1. `docker pull floci/floci:2.5.0-compat`가 받아지는지. 안 되면 Docker Desktop 프록시·로그인, 네트워크를 확인한다.
2. `copy .env.example .env` 후 `docker compose up -d --build`.
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
| `PreSignUpFunction` | 없음 | 이벤트만 바꾼다. Cognito 호출 권한은 `PreSignUpInvokePermission`(SourceArn은 순환 참조를 피하려고 `userpool/*`) |

권한 오류(`AccessDeniedException`)가 나면 CloudWatch Logs의 예외 유형과 이 표를 대조한다. 로그에는 예외 유형만 남긴다(응답에는 500 `INTERNAL_ERROR`).

## 7. 미결 질문과 임시 결정

구현은 spec이 정한 임시 기본안을 따랐다. 전체 목록은 [docs/08](../docs/08-open-questions.md) §8.1.

| # | 임시 결정 |
|---|---|
| BE-Q3, BE-Q32 | `limit` 기본 20·최대 50, 잘못된 값은 보정, `nextCursor: null` |
| BE-Q17 | 로컬·AWS 모두 실측 전. 4절 3항, 5절 5항 |
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

PR은 아직 열지 않았다. 리뷰할 때 아래 순서로 연다.

1. `docs/monorepo-stage1-2-spec` → `main`: 문서·spec
2. `feat/be-1-2-foundation` → `docs/monorepo-stage1-2-spec`(1이 병합되면 `main`): 1·2단계 코드
3. (3단계 인계 후) `feat/be-3-claim-transaction` → `feat/be-1-2-foundation`

비교 링크: `https://github.com/creatingweb123/knu-aws-2026/compare/<기준>...<브랜치>`

3번 PR에는 3단계 spec(`.kiro/specs/backend-stage3-claim/`)과 docs/08 BE-Q34–BE-Q41 추가가 함께 들어 있다. spec은 리뷰 에이전트 검토를 한 번 거쳤다(지적 16건 반영, 반영 결과는 spec 미결 사항에 있다).

계약 변경(docs/07 §7.2, §7.8에 따라 다른 팀원 한 명이 리뷰):

- 시간 형식을 밀리초 3자리로 고정(docs/03 공통 규칙에 반영)
- API Gateway가 거부한 401은 본문 형식이 다르다(requirements 1.7, docs/03 §3.6 401 행에 반영)
- BE-Q23·BE-Q24·BE-Q29·BE-Q33의 임시 결정

## 9. 개발 메모

- 테스트: `pytest tests/unit`(기본, 약 3–4분. moto 테스트는 `tests/unit/moto_table.py`가 boto3 리소스를 재사용해 빨라졌다), `pytest -m local tests/local`(Docker), `pytest -m integration tests/integration`(AWS).
- 경로 목록은 `src/handlers/routes.py` 한 곳에 있다. `template.yaml`·로컬 어댑터와 일치하는지 `tests/unit/test_template.py`가 확인한다.
- 시간은 `common.responses.iso_utc`(밀리초 고정 UTC). 저장한 시각을 문자열로 비교하므로 다른 형식을 섞지 않는다.
- Lambda 의존성은 `src/requirements.txt`(sam build가 CodeUri `src/`에서 읽는다). 개발 의존성은 `requirements-dev.txt`.
