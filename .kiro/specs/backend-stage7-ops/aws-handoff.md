# AWS 담당 인계 — 배포, 환경 설정, 인수 판정

작성: 2026-11-27, 브랜치 `feat/be-7-completion`(기준 `main` `17486ed`). **이 환경에서는 실제 AWS에 접속·배포하지 않았다.** 아래는 모두 AWS 담당이 실행할 일이다. 계정 ID·이메일·비밀 값은 저장소에 없고 실행할 때 넣는다.

## 0. 개발 쪽에서 끝낸 것과 아직 아닌 것

| 구분 | 내용 |
|---|---|
| 구현 + 단위 테스트 + 로컬 통합 | 1–6b, `GET /record`, 사진 폴링, `seed.py`, `report.py`, `photo_orphans.py`, `deploy_web.py` |
| SAM 정적 검증 | `cfn-lint template.yaml` 통과(SAM 변환 포함). `sam validate`·`sam build --use-container`는 이 환경에 SAM CLI가 없어 실행하지 못했다 → 3.1 |
| 승인 대기 | BE-Q46(`GET /record` 503), BE-Q65(`UploadIfNoneMatch`), BE-Q130–132(알람 임계값·예산·가격 등급), BE-Q6·Q7·Q10·Q26(AI 운영 정책) |
| 실제 AWS 배포 대기 | 웹 버킷·CloudFront·알람·대시보드·Budgets 전부 |
| 실제 AWS 인수 판정 대기 | T2·T8–T12·T15·T17–T22와 7단계 항목(아래 4절) |

## 1. 사전 준비 (한 번)

1. AWS CLI 프로필(`aws login` 또는 SSO)과 `ap-northeast-2`. 배포 권한: CloudFormation, IAM(역할 생성, `CAPABILITY_IAM`), Lambda, API Gateway, DynamoDB, S3, SQS, Cognito, CloudFront, CloudWatch, Budgets(`budgets:*`는 Budgets를 켤 때만).
2. **Bedrock 모델 접근**: 콘솔 Model catalog에서 쓸 모델의 접근을 켜고 **모델 ID 또는 추론 프로필 ID**를 복사한다(`LlmModel`). 운영 모델은 개발 쪽이 정하지 않았다(BE-Q6). 호출 리전은 `LlmRegion`(비우면 함수 리전).
3. 도구: Python 3.12, `pip install -r backend/requirements-dev.txt`, SAM CLI, Docker(`sam build --use-container`), Node 22(프론트 빌드).

## 2. 배포 (dev → demo)

```bash
cd backend
sam build --use-container
sam deploy --config-env dev   # 먼저 dev. confirm_changeset이 켜져 있어 변경 세트를 확인한 뒤 진행한다
```

추가 파라미터는 `--parameter-overrides`로 **기존 값 뒤에 이어 붙인다**(`samconfig.toml`의 값을 덮어쓰지 않도록 전체를 다시 적는다).

| 파라미터 | 기본 | 이 단계에서 정할 값 | 비고 |
|---|---|---|---|
| `LlmProvider` / `LlmModel` / `LlmRegion` | bedrock / 빈 값 / 빈 값 | 모델 ID, 리전 | 모델 ID가 비면 AI 경로는 503 `AI_UNAVAILABLE`(설정 오류). 키는 필요 없다(IAM) |
| `AgentMode` | pipeline | dev 판정을 통과한 뒤 `agent` | 바꾸면 진행 중 에이전트 세션은 다음 요청에서 닫힌다 |
| `AlarmApi5xxThreshold` 등 `Alarm*` | 5 / 1 / 8000 / 22000 / 24000 | dev 부하를 본 뒤 | **임시값**(BE-Q130) |
| `BudgetMonthlyUsd`, `BudgetNotificationEmail` | 0, 빈 값 | 팀이 정한 금액과 수신 이메일 | **둘 다** 주면 Budgets가 생긴다(BE-Q131). 이메일은 수신 확인 메일이 온다 |
| `UploadIfNoneMatch` | false | **프론트 승인(BE-Q65) 전에는 false** | 켜면 `upload.headers`·버킷 CORS·정책이 바뀐다 |
| `AiMaskBeforeSend` | false | **BE-Q10 결정 전에는 false** | |
| `FaultInject`, `AiFaultInject` | 빈 값 | T9·T10·T15 지연 사례와 T21에서만 `Stage=dev`·스택 이름 `haru-dev` | demo에서는 템플릿 규칙이 거부한다 |

배포 직후 출력 확인(`aws cloudformation describe-stacks --stack-name haru-dev --query 'Stacks[0].Outputs'`): `ApiUrl`, `UserPoolId`, `UserPoolClientId`, `WebBucketName`, `DistributionId`, `DistributionDomain`.

### 2.1 프론트 배포 (S5)

```bash
cd backend
python scripts/deploy_web.py --stack haru-dev --print-env > ../frontend/.env.production.local   # 공개 설정값만(비밀 없음)
cd ../frontend && npm ci && npm run build                                                       # VITE_* 가 빌드에 들어간다
cd ../backend
python scripts/deploy_web.py --stack haru-dev --dist ../frontend/dist                           # dry-run으로 목록 확인
python scripts/deploy_web.py --stack haru-dev --dist ../frontend/dist --apply --confirm-stack haru-dev --prune
```

CloudFront 첫 배포는 몇 분 걸린다. `https://<DistributionDomain>/` 접속 후 하위 경로 새로고침이 200인지 확인한다.

### 2.2 데모 데이터

```bash
python scripts/seed.py --stack haru-demo                                                         # 계획만 출력(읽기만)
SEED_PASSWORD='<새 비밀번호>' python scripts/seed.py --stack haru-demo --apply --create-users --confirm-stack haru-demo
python scripts/seed.py --stack haru-demo --apply --reset --confirm-stack haru-demo               # 데모 데이터만 지우고 다시 만든다
```

- 데모 이메일은 기본 `jiyeon/suhyun/minjun@example.com`(환경 변수 `SEED_*_EMAIL`로 바꾼다). 비밀번호는 저장소·출력에 없다.
- 시드 Plan은 `Plan.seed` 태그로 `report.py`에서 빠진다. 사진 객체는 만들지 않는다.

## 3. 배포 전·직후 점검

### 3.1 SAM 검증 (이 환경에서 못 한 것)
```bash
cd backend
cfn-lint template.yaml                 # 이 환경에서 통과
sam validate --lint                    # 실행 필요(자격 증명이 있는 환경)
sam build --use-container && python scripts/check_ai_build.py   # AI 함수 산출물 검사
```
`sam validate`가 자격 증명을 요구하면 AWS 담당 프로필로 실행한다. 템플릿을 바꾼 뒤에는 `sam deploy`의 변경 세트에서 **삭제·교체**되는 리소스가 없는지 확인한다(웹 버킷·Distribution은 신규).

### 3.2 알람·대시보드 확인
- 콘솔 CloudWatch → Dashboards → `haru-dev-ops`. 지표는 트래픽이 있어야 나온다. "AI 세션 상태 분포" 위젯은 근사이고 텍스트 위젯에 한계가 적혀 있다.
- 알람 7개(`PhotoDLQNotEmpty`, `AgentTokensAlarm`, `HttpApi5xxAlarm`, `LambdaErrorsAlarm`, `ApiLambdaDurationAlarm`, `AiCardLambdaDurationAlarm`, `PhotoLambdaDurationAlarm`)가 `OK`/`INSUFFICIENT_DATA`인지 본다. **알림 대상(SNS)은 없다**(BE-Q62): 알람 상태를 콘솔에서 본다. 알림이 필요하면 팀이 SNS 주제를 정한 뒤 `AlarmActions`를 추가한다.
- Budgets는 계정 전체 비용 기준이다(스택 태그 필터 없음).

## 4. 인수 판정 (실행 순서와 합격 기준)

테스트 실행: `STACK_NAME=haru-dev pytest -m integration tests/integration -q`(결과 로그는 `test-results/`). 지연·장애 주입 사례는 `-m "integration and fault"`를 따로 실행한다.

| 순서 | 대상 | 방법 | 합격 기준 | 상태(2026-11-27) |
|---|---|---|---|---|
| 1 | T1, T13, T3, T4, T5, T6, T7, T14, T16 | 기존 15건(재실행) | 전부 통과 | 2026-11-25 `haru-dev` 통과. **7단계 변경 뒤 회귀로 재실행 필요** |
| 2 | T1 확장 | `test_access_token_is_rejected`(GET /record 추가) | 액세스 토큰 401 | 코드 작성, **미실행** |
| 3 | T2 | `test_T2_role_based_access`(GET /record 행 추가) | 역할별 기대 결과 일치, 403 뒤 불변 | **미실행** |
| 4 | T17 | 답장 첫/두 번째 | 201 / 409 | **미실행** |
| 5 | `GET /record` 스냅샷 | `test_get_record_snapshot_during_writes` | 불일치 0건. 503 비율을 로그로 남겨 BE-Q46·BE-Q48 자료로 쓴다 | **미실행** |
| 6 | T8, T10, T11, T15 | 사진 테스트(`test_photo.py`) | 문서의 기대 결과 | **미실행** |
| 7 | T9 | `FaultInject=photo` 스택(`dev`·`haru-dev`) | 3회 재시도 후 DLQ, `FAILED`, `PhotoDLQNotEmpty` 알람 | **미실행** |
| 8 | 재업로드·IAM·CORS | `test_photo_reupload`, `test_photo_iam_and_cors` | 스위치 꺼짐: 같은 URL 덮어쓰기 가능(한계), 켬: 412 | **미실행** |
| 9 | T12 | 잘못된 모델 ID/권한으로 AI 세션 | 503 `AI_UNAVAILABLE`, 세션 `FAILED`, Plan 없음 | **미실행**(Bedrock 설정 필요) |
| 10 | T18–T22 | AI 테스트(`test_ai.py`) | 문서의 기대 결과. T20 잠금, T21 `AiFaultInject=ai-slow` | **미실행** |
| 11 | 웹(7단계) | `pytest -m integration tests/integration/test_web.py` | HTTPS 리다이렉트, SPA 200, S3 직접 접근 403, API·사진 CORS에 배포 도메인 | **미실행** |
| 12 | 시연 리허설 | 프론트와 90초 시연, AI 10회 | docs/07 7단계 항목 | 대기 |

재검증이 필요한 이유 요약: **1번 15건**은 2026-11-25 통과 기록이 있으나 이후 4·5·6a·6b·Bedrock·7단계 코드가 들어갔다. **2–12번**은 한 번도 AWS에서 실행하지 않았다.

### 로컬 결과와 AWS 판정의 차이
Floci는 CORS preflight, 버킷 정책 강제, 수명 주기 만료, 실제 SQS 이벤트 소스 매핑, Lambda 강제 종료, CloudFront, 알람을 흉내 내지 못한다. 로컬 통과는 흐름·조건식 확인일 뿐 T 시나리오 합격이 아니다(BE-Q15).

## 5. 측정해야 정할 수 있는 값 (근거 없이 바꾸지 않았다)
- 공통 SDK 타임아웃·재시도(BE-Q48): 함수별 제한 설정만 있고 공통 값은 기본 SDK 설정이다. 5번 스냅샷 테스트의 503 비율과 콜드 스타트 지연으로 정한다.
- 사진 처리 SDK·시간 예산(BE-Q70·71·72), 에이전트 턴 p95 15초·`read_timeout` 8초(BE-Q12): dev 측정 뒤.
- 알람 임계값(BE-Q130)과 월 예산(BE-Q131): dev 부하와 팀 예산.

## 6. 운영 스크립트
- `scripts/photo_dlq_recover.py`: DLQ 복구(기본 dry-run, 안전 확인 통과 시 `--apply`). 런북은 `backend/README.md` "사진 DLQ 복구".
- `scripts/photo_orphans.py --stack haru-dev`: 전달되지 않은 처리본 후보 점검(읽기 전용, 삭제하지 않는다). `orphan_candidate`는 운영자가 확인한 뒤 직접 처리한다.
- `scripts/report.py --stack haru-demo [--check-invariants] [--json out.json]`: 성과 집계. `Stage=demo` 스택만 성과 근거(`pilotEligible`)로 출력하고, dev·Fake는 `--allow-non-pilot-env`가 있어야 출력하며 `formatCheckOnly`로 표시된다. 시드는 기본 제외.
- 정리: 데모 데이터는 `seed.py --clean`, 웹 버킷은 스택 삭제 전에 비워야 한다(`aws s3 rm s3://<WebBucketName> --recursive`; 파괴적이므로 대상 확인 뒤 AWS 담당이 실행).
