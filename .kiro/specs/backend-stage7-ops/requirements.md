# Requirements Document — 백엔드 7단계 (웹 배포 인프라, 관측, 시연 준비) 와 미완료 기능 마무리

작성: 2026-11-27. 기준 브랜치 `main`(`17486ed`)에서 갈라진 `feat/be-7-completion`. 요구사항 ID는 `docs/06-requirements.md`의 BE-INFRA-01–04, BE-OBS-01–05, BE-NFR-06, BE-REC-05를 그대로 쓴다.

## Introduction

백엔드 1–6b와 Amazon Bedrock 공급자 전환은 `main`에 있다. 이 문서는 **실제 AWS 계정에 접근하지 않고** 끝낼 수 있는 남은 개발을 정리한다. 실제 배포·AWS 판정·팀 정책 결정은 범위 밖이며 각각 "승인 대기" 또는 "AWS 담당 인계"로 분리한다.

### 완료 상태 용어 (이 spec과 README·docs에서 같은 뜻으로 쓴다)

| 용어 | 뜻 |
|---|---|
| 구현 완료 | 코드·템플릿·스크립트가 작성돼 있다 |
| 단위 테스트 완료 | `pytest tests/unit`(moto·Stubber·정적 템플릿 검사)이 통과한다 |
| 로컬 통합 검증 완료 | docker compose(Floci, Fake LLM)에서 `pytest -m local`이 통과한다. T 시나리오 합격 근거가 아니다(BE-Q15) |
| SAM 정적 검증 완료 | `cfn-lint`(SAM 변환 포함)가 통과한다. `sam validate`·`sam build`는 별도 표기 |
| 승인 대기 | 계약·정책 결정이 필요해 기본 동작을 바꾸지 않았다 |
| 실제 AWS 배포 대기 | 스택에 배포하지 않았다 |
| 실제 AWS 인수 판정 대기 | 배포된 스택에서 `tests/integration`·수동 확인으로 판정해야 한다 |

### 범위

- 작업 A: `GET /claims/{claimId}/record` (BE-REC-05, BE-Q46)
- 작업 B: 사진 파이프라인 검증 보강(폴링, 업로드 덮어쓰기 방지 점검, 복구·점검 스크립트)
- 작업 C: 통합 회귀(병합 결함 수정 포함)
- 작업 D: 웹 호스팅 인프라(BE-INFRA-02–04)
- 작업 E: 알람·대시보드·Budgets(BE-OBS-01–03)
- 작업 F: `scripts/seed.py`, `scripts/report.py`(BE-OBS-04·05, BE-NFR-06)
- 작업 G: AI 안정화 점검, 개인정보 전송 전 마스킹 스위치(BE-Q10, 기본 꺼짐)

## Requirements

### Requirement 1: 방문 기록 조회 [BE-REC-05, BE-Q46]
1. WHEN 실행자가 `GET /claims/{claimId}/record`를 호출하면, THE Claim_Service SHALL Claim과 Record를 `TransactGetItems` 한 번으로 읽어 200 `{record, claimStatus, delivered, photoStatus}`를 반환한다.
2. IF Record가 없으면, THEN SHALL `{record: null, claimStatus, delivered: false, photoStatus: "NONE"}`을 반환한다.
3. WHILE Claim이 ABANDONED·EXPIRED·COMPLETED이면 SHALL 같은 형식의 200을 반환한다.
4. IF 요청자가 실행자가 아니면 SHALL 트랜잭션 전에 403 `FORBIDDEN`을 낸다(본문에 기록 없음). IF Claim 조회가 없으면 404.
5. THE `record` SHALL `serialize_record` 허용 목록으로만 직렬화한다(`photoKey`·`processedKey`·`authorId` 없음).
6. WHEN 취소 사유가 `TransactionConflict`뿐이면 SHALL 최초 1회 + 재시도 3회(50·100·200ms 상한, equal jitter)하고 소진하면 503 `TRY_AGAIN`. 다른 사유가 섞이거나 다른 사유만 있으면 재시도 없이 500 `INTERNAL_ERROR`. GetItem으로 폴백하지 않는다.
7. THE 조회 SHALL 아무것도 쓰지 않는다. `ClaimsFunction` IAM은 바꾸지 않는다(`TransactGetItems`는 `GetItem` 권한).
8. **계약 상태**: 503을 `docs/03 §3.4`에 적는 계약 변경은 **프론트엔드 담당 승인 대기**다. 승인 전에는 §3.4를 고치지 않는다. 거부되면 대안 A(ConsistentRead GetItem 2회)로 `get_record`만 바꾼다.

### Requirement 2: 사진 상태 폴링과 파이프라인 점검 [BE-PHOTO-01–09]
1. THE 폴링(`GET /record`) SHALL `UPLOAD_PENDING → PROCESSING → READY`, `FAILED`, `DISCARDED`(글만 완료·포기)를 관측하게 한다. 로컬 통합에서 이 순서와 `claimStatus`·`delivered`의 일치를 확인한다.
2. THE `UploadIfNoneMatch`(BE-Q65) SHALL 승인 전까지 `false`를 기본으로 유지한다. 켤 때 필요한 presign 서명·`upload.headers`·버킷 CORS·버킷 정책 변경은 이미 한 스위치 뒤에 있고 단위 테스트가 있다.
3. THE 프론트 재업로드 SHALL 스위치가 켜지면 같은 URL 재사용이 412가 된다는 점을 알고 새 업로드 URL을 받아야 한다(프론트 변경은 하지 않고 승인 대기 항목으로 보고한다).
4. THE `scripts/photo_orphans.py` SHALL 전달되지 않은 처리본 후보를 **읽기 전용**으로 분류한다. 삭제·이동·태그 변경은 하지 않는다.

### Requirement 3: 통합 회귀
1. THE docker-compose.yml SHALL 중복 키 없이 파싱된다(병합 결함 수정, 회귀 테스트 포함).
2. THE 기존 단위·속성 기반·로컬 통합 테스트 SHALL 기대값을 완화하지 않고 통과한다. 새 경로·출력 추가로 바뀐 기대 집합(경로 목록, 출력값 목록, 버킷 목록)만 갱신한다.

### Requirement 4: 웹 호스팅 [BE-INFRA-02–04]
1. THE 템플릿 SHALL 비공개 웹 버킷(Public Access Block 4종, BucketOwnerEnforced, SSE-S3)과 CloudFront 배포(OAC, SigV4)를 만든다. 정적 웹사이트 엔드포인트·OAI를 쓰지 않는다.
2. THE 웹 버킷 정책 SHALL TLS 아닌 요청을 거부하고 `cloudfront.amazonaws.com`의 `s3:GetObject`만 이 배포 ARN 조건으로 허용한다.
3. THE 배포 SHALL HTTPS로 리다이렉트하고, 403·404를 `/index.html`(200, 오류 캐시 0초)로 돌려주며, `/assets/*`는 장기 캐시(Managed-CachingOptimized), 나머지는 Managed-CachingDisabled로 한다.
4. THE API CORS와 사진 버킷 CORS SHALL `AllowedOrigins` 파라미터 + `https://<배포 도메인>`을 쓴다. 리소스 의존에 순환이 없다(정적 테스트가 그래프로 검사한다).
5. THE 출력 SHALL `ApiUrl`, `UserPoolId`, `UserPoolClientId`, `WebBucketName`, `DistributionId`, `DistributionDomain`이다.
6. THE `scripts/deploy_web.py` SHALL dist를 assets 먼저·index.html 마지막으로 올리고 Cache-Control을 정하며 `/*` 무효화를 만든다. 기본 dry-run, `--apply`는 `--confirm-stack` 필요. 실제 배포는 AWS 담당이 실행한다.

### Requirement 5: 알람·대시보드·Budgets [BE-OBS-01–03]
1. THE 알람 SHALL API 5xx, Lambda Errors(전 함수 합), Lambda Duration(API 함수 묶음·AiCard·사진 처리)을 추가한다. `PhotoDLQNotEmpty`·`AgentTokensAlarm`은 그대로다(중복 생성 없음). 알림 대상(SNS)은 두지 않는다(BE-Q62).
2. THE 임계값 SHALL 명세에 값이 없어 파라미터(`Alarm*`)로 분리하고 **임시값**임을 설명에 적는다(BE-Q130).
3. THE 대시보드 SHALL API 요청·오류율, Lambda 호출·오류·응답 시간, 이어받기 충돌·중복 완료, 사진 처리 시간·실패, DLQ 깊이, AI 응답 시간·오류, 에이전트 모델 호출·토큰·질문·자체 수정을 보인다. 코드가 내지 않는 지표를 연결하지 않는다(테스트가 EMF 이름 상수와 대조한다).
4. THE 대시보드 SHALL **AI 세션 상태 분포**를 CloudWatch 지표로 정확히 표현할 수 없음을 텍스트 위젯에 적고 근사 위젯을 둔다. 정확한 분포는 `report.py`가 DynamoDB 값으로 낸다.
5. THE AWS Budgets SHALL 월 금액(`BudgetMonthlyUsd`)과 수신 이메일(`BudgetNotificationEmail`)이 **둘 다** 주어질 때만 만든다. 저장소에 이메일·금액을 넣지 않는다(BE-Q131).

### Requirement 6: 시연 데이터와 성과 집계 [BE-OBS-04·05, BE-NFR-06]
1. THE `seed.py` SHALL 대상(`--local`/`--stack`)을 명시해야 하고 기본 dry-run이며, 매니페스트로 멱등하고, `--reset`·`--clean`은 매니페스트의 Plan만 지우며, 데모 사용자가 아닌 사람의 Claim이 있는 Plan은 지키고, 서비스 계층으로 데이터를 만든다.
2. THE `report.py` SHALL 읽기 전용이고 필요한 속성만 Scan하며(본문·닉네임·제목·답장 본문 미조회), 지표별 분모·제외·누락값을 docstring에 정의하고, 빈 데이터는 null로 내며, 콘솔·JSON·CSV를 지원한다.
3. THE 집계 SHALL Fake 모델 데이터와 실제 모델 데이터를 섞지 않는다. Plan 지표에는 공급자 구분이 없으므로(6a design §15.1 유지) **환경 단위**로 막는다: `--stack`은 `Stage`·`LlmProvider`를 읽어 `demo` 스택만 `pilotEligible`로 표시하고, 그 밖(dev·Fake·로컬)은 `formatCheckOnly`이며 명시 플래그 없이는 출력하지 않는다(BE-Q133).
4. THE 시드 데이터 SHALL 집계에서 기본 제외된다(`Plan.seed` 태그).

### Requirement 7: AI 안정화 [BE-Q10, BE-Q26]
1. THE 공급자 계층(bedrock·openai_compat·fake) SHALL 설정 검증, 모델 ID 누락, 인증 실패, 타임아웃, 429, 잘못된 응답, 도구 호출 형식, 토큰 집계, 오류 코드 변환을 기존 단위 테스트(Stubber 포함)로 이미 확인한다. 실제 Bedrock·유료 API는 호출하지 않는다.
2. THE 전송 전 마스킹 SHALL `AI_MASK_BEFORE_SEND=true`일 때만 사연·답변의 HIGH 개인정보를 모델 입력에서 가린다. **기본은 꺼짐**(BE-Q10 미결). 켜도 대조 원문·저장 값은 바뀌지 않고 정상 문장("2호선", "1호점")은 가리지 않는다.
3. THE 제3자 실명 탐지(BE-Q26)는 구현하지 않는다(미결 유지).

## 범위 밖 / 승인 대기

| 항목 | 상태 |
|---|---|
| `GET /record` 503 계약(§3.4) | 프론트엔드 담당 승인 대기(BE-Q46) |
| `UploadIfNoneMatch` 활성화, 프론트 재업로드 | 프론트엔드 담당 승인 대기(BE-Q65) |
| 알람 임계값, 예산 금액·수신자, CloudFront 가격 등급 | 팀 결정(BE-Q130–BE-Q132) |
| 운영 모델·추론 프로필, 외부 전송 동의, 마스킹 정책 | 팀 결정(BE-Q6·Q7·Q10) |
| 실제 배포, T1–T22 판정, 실제 Bedrock 평가 | AWS 담당(인계 문서 `aws-handoff.md`) |
