# 이어온 하루 백엔드 — 인계 문서

AWS 계정 없이 개발한 백엔드를 AWS 담당이 배포·판정할 수 있도록 정리한 문서다. 역할 분담은 [docs/07 §7.8](../docs/07-development-plan.md), 명세는 [docs/](../docs/)와 spec(`.kiro/specs/`)이 기준이다.

## 1. 인계 상태 요약

| 항목 | 상태 |
|---|---|
| 범위 | 백엔드 1·2단계(인증, `GET /me`, 계획 생성·목록·상세, 멱등 키, 원문 충실도·개인정보 함수) |
| 브랜치 | `feat/be-1-2-foundation` (문서는 `docs/monorepo-stage1-2-spec`) |
| 단위 테스트 | `pytest tests/unit` 전부 통과. moto(인프로세스 DynamoDB 흉내)로 실제 조건식·갱신식·GSI 조회도 확인 |
| SAM | `cfn-lint` 0건, `sam validate --lint` 통과, `sam build` 성공. **배포는 한 번도 하지 않았다** |
| 로컬 환경(Docker) | 코드는 작성했지만 **첫 실행 확인 필요**(5절) |
| AWS 판정 | T1·T13 테스트 코드 작성 완료, **미실행**(3절) |
| PR | 아직 열지 않았다(8절) |

확인하지 못한 것은 5절(로컬 환경)과 4절(AWS에서만 확인되는 것)에 모았다.

## 2. 배포 런북 (AWS 담당)

### 2.1 준비

- 리전: `ap-northeast-2`
- 도구: AWS CLI v2, AWS SAM CLI(1.174.0에서 확인), Python 3.12. Windows에서 `sam build`는 PATH의 `python`이 3.12여야 한다(가상 환경을 켜거나 `--use-container`).
- **배포 전에 AWS Budgets 월 알림을 먼저 건다**(BE-Q11, 금액은 팀이 정한다).
- 배포하는 IAM 주체에 필요한 권한: CloudFormation, IAM 역할 생성·연결(`CAPABILITY_IAM`), Lambda, API Gateway(HTTP API), Cognito User Pool, DynamoDB, S3(SAM 아티팩트 버킷, `resolve_s3`가 `aws-sam-cli-managed-default` 스택을 만든다), CloudWatch Logs.
- 통합 테스트를 돌리는 주체에 필요한 권한: `cloudformation:DescribeStacks`, `cloudformation:DescribeStackResource`, `cognito-idp:AdminCreateUser`, `AdminSetUserPassword`, `AdminDeleteUser`, `dynamodb:Query`, `dynamodb:DeleteItem`(대상 테이블만).

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

실행:

```powershell
$env:STACK_NAME = "haru-dev"
$env:AWS_REGION = "ap-northeast-2"
pytest -m integration tests/integration -v
```

- 테스트가 만든 Cognito 사용자와 Plan 항목은 끝나면 지운다.
- 근거 로그는 `test-results/T1-authz-*.json`, `T13-*.json`에 남는다. 판정 결과와 함께 보관한다.
- `STACK_NAME`이 없으면 모두 건너뛴다.

## 4. AWS에서만 확인되는 것 (1·2단계 해당분, docs/02 §2.4.4)

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | JWT authorizer가 모든 경로를 보호하는지. **거부 시 본문은 `{"message":"Unauthorized"}`로 계약 형식이 아니다** | T1 테스트. 본문 차이는 계약 변경 리뷰 대상(8절) |
| 2 | PreSignUp 트리거 연결과 자동 확인, `nickname` 필수 속성 | 가입 직후 로그인 테스트 |
| 3 | 실제 Cognito ID 토큰의 `nickname` 클레임(BE-Q17 실측) | T1 대조군 테스트의 `GET /me` 닉네임 |
| 4 | `PlansFunction` IAM: `TransactWriteItems`가 `PutItem` 권한만으로 실행되는지 | T13. 실패하면 6절 표의 권한을 고친다 |
| 5 | API CORS(허용 Origin `http://localhost:5173`) | 브라우저 또는 `curl -X OPTIONS -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: POST" $ApiUrl/plans` |
| 6 | 동시 요청에서 멱등 키가 Plan 1건을 지키는지(실제 병렬성, TransactionConflict) | T13 동시 10회 |
| 7 | 콜드 스타트, 메모리·타임아웃 | CloudWatch Logs의 `Init Duration` 참고(1·2단계는 의존성이 작다) |

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

Docker 없이 확인한 대체 수단: moto 테스트(`tests/unit/test_plan_service_moto.py`)가 실제 DynamoDB 조건식·취소 사유 코드·GSI 조회를 확인한다. moto와 Floci 모두 실제 병렬성은 재현하지 않으므로 동시성 판정은 AWS에서만 한다.

## 6. 함수별 IAM 권한

| 함수 | 권한 | 이유 |
|---|---|---|
| `MeFunction` | 없음 | 4단계 전까지 `GET /me`는 DB를 읽지 않는다(BE-Q30) |
| `PlansFunction` | `HaruTable`과 `index/*`에 `dynamodb:GetItem`, `PutItem`, `Query` | 생성(Plan + 멱등 키 트랜잭션), 상세(ConsistentRead), 목록(GSI1), 내 Claim 조회 |
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

## 8. 리뷰가 필요한 것과 PR

PR은 아직 열지 않았다. 리뷰할 때 아래 순서로 연다.

1. `docs/monorepo-stage1-2-spec` → `main`: 문서·spec
2. `feat/be-1-2-foundation` → `docs/monorepo-stage1-2-spec`(1이 병합되면 `main`): 1·2단계 코드
3. (3단계 인계 후) `feat/be-3-claim-transaction` → `feat/be-1-2-foundation`

비교 링크: `https://github.com/creatingweb123/knu-aws-2026/compare/<기준>...<브랜치>`

계약 변경(docs/07 §7.2, §7.8에 따라 다른 팀원 한 명이 리뷰):

- 시간 형식을 밀리초 3자리로 고정(docs/03 공통 규칙에 반영)
- API Gateway가 거부한 401은 본문 형식이 다르다(requirements 1.7, docs/03 §3.6 401 행에 반영)
- BE-Q23·BE-Q24·BE-Q29·BE-Q33의 임시 결정

## 9. 개발 메모

- 테스트: `pytest tests/unit`(기본, 약 2–3분), `pytest -m local tests/local`(Docker), `pytest -m integration tests/integration`(AWS).
- 경로 목록은 `src/handlers/routes.py` 한 곳에 있다. `template.yaml`·로컬 어댑터와 일치하는지 `tests/unit/test_template.py`가 확인한다.
- 시간은 `common.responses.iso_utc`(밀리초 고정 UTC). 저장한 시각을 문자열로 비교하므로 다른 형식을 섞지 않는다.
- Lambda 의존성은 `src/requirements.txt`(sam build가 CodeUri `src/`에서 읽는다). 개발 의존성은 `requirements-dev.txt`.
