# Design Document — 백엔드 7단계와 미완료 기능 마무리

## 구조 결정

| 결정 | 근거 |
|---|---|
| 기록 조회는 `claim_service.get_record`에 두고 `common/ddb.transact_get_with_retry`로 한 시점 스냅샷을 읽는다 | 4단계 design(묶음 B)의 BE-Q46 권장안. Git 이력에 구현이 남아 있지 않아(`f3626c0`이 저장소에 없다) 문서대로 새로 구현했다 |
| 읽기 트랜잭션 재시도는 쓰기(`transact_with_retry`)와 같은 상수를 쓰되 equal jitter를 더한다 | 설계 문서의 읽기 재시도 규칙. 사유가 충돌뿐일 때만 재시도해 스로틀·검증 오류를 숨기지 않는다 |
| 웹 도메인은 `AllowedOrigins`에 넣지 않고 템플릿이 `!Split/!Join`으로 덧붙인다 | 배포 도메인은 Distribution 생성 뒤에야 알 수 있다. Distribution이 API·사진 버킷을 참조하지 않으므로 순환이 없다 |
| `/assets/*`와 나머지를 다른 Managed 캐시 정책으로 나눈다 | Vite 해시 파일은 장기 캐시, index.html은 항상 원본 확인. 배포 직후 새 해시를 바로 받는다. 정책 ID는 AWS Managed 값 |
| 대시보드 본문은 `!Sub` JSON 한 덩어리이고 테스트가 JSON으로 읽어 지표 이름을 코드 상수와 대조한다 | 존재하지 않는 지표를 연결하지 않는다는 요구를 기계적으로 보장 |
| Lambda Errors는 지표 수식(`SUM(METRICS())`) 한 알람으로 | 함수 7개 × 알람 대신 하나. Duration은 타임아웃이 달라 API 함수 묶음·AiCard·사진 처리로 나눈다 |
| Budgets는 `Condition: CreateBudget`(금액>0 AND 이메일 있음) | 값 없이 배포가 실패하지 않고 저장소에 값이 들어가지 않는다 |
| `seed.py`는 서비스 계층을 호출하고 매니페스트(`SEED#demo-v1/MANIFEST`)에 만든 Plan만 적는다 | API와 같은 항목 모양 보장, 운영 데이터 보호. 테이블 전체 스캔·삭제 없음 |
| `report.py`는 `ProjectionExpression`으로 필요한 속성만 읽고 이름은 전부 자리표시자로 쓴다 | `metrics`·`status`가 DynamoDB 예약어라 로컬 검증에서 실패가 드러났다. 본문·닉네임 미조회로 개인정보 최소화 |
| Fake/실제 구분은 `Plan.metrics.llmMode`(AiSession.llmMode 복사) | 기존 Plan에는 값이 없으므로 `unknown`이고 실제 모델로 치지 않는다. API 응답 허용 목록(`METRIC_FIELDS`)에는 넣지 않는다 |
| 전송 전 마스킹은 `agent.prompt.neutralize` 한 곳에서 환경 변수로 켠다 | 사연·답변이 모델로 들어가는 유일한 경로. 대조 원문(state)은 건드리지 않는다 |
| 고아 처리본은 점검만 하고 삭제하지 않는다 | 정상 전달된 사진을 지울 위험이 있는 자동 정리를 도입하지 않는다 |

## 테스트 전략 (이 단계에서 추가)

| 파일 | 내용 |
|---|---|
| `tests/unit/test_get_record.py` | 재시도·대기 상한·로그, 속성 기반 재시도 한도, 핸들러 분기(없음·남·포기·만료·완료·사진 상태 순서·충돌 소진 503·비충돌 500·읽기 시 불변) |
| `tests/unit/test_web_infra.py` | 순환 없음, 비공개·암호화, OAC·HTTPS·SPA, 캐시, CORS 연동, 알람, 대시보드(실제 지표만), Budgets 조건 |
| `tests/unit/test_deploy_web.py`, `test_seed.py`, `test_report.py`, `test_photo_orphans.py` | moto·가짜 클라이언트로 스크립트 동작 |
| `tests/unit/test_ai_prompt.py` | 마스킹 스위치 기본 꺼짐·정확히 `true`만 켜짐·오탐 없음 |
| `tests/local/test_local_photo.py` | `GET /record` 폴링(로컬 어댑터) |
| `tests/integration/test_web.py`, `test_authz.py`·`test_concurrency.py` 추가 | AWS 담당 실행. 이 환경에서는 `--collect-only`만 |

## G-3 조사 결과: 원문 충실도를 reason·summary·question으로 넓힐 수 있는가 (확장하지 않음)

- 현재 판정(`domain/fidelity.find_not_in_source`)은 **장소 이름·활동**만 본다. 토큰(조사 제거, 서술어 꼴 제외)이 근거 텍스트에 부분 문자열로 있는지 보는 규칙 기반이다(BE-Q25).
- `reason`·`summary`·`question`은 사연을 **요약·추상화·질문으로 바꾼** 문장이다. 정상적인 요약("이삿짐 정리가 길어져서" → "바쁜 시간이 이어져서")은 근거에 같은 토큰이 없어도 충실하다. 같은 규칙을 적용하면 정상 문장을 근거 없음으로 잘못 걸러 내는 오탐이 많아지고, 반대로 근거에 있는 단어만 붙여 쓴 허위는 통과한다.
- 따라서 문자열 일치 확장은 하지 않았고 **측정한 것으로 주장하지도 않는다**. 현재 `eval_agent.py`가 보증하는 것은 "장소·활동의 원문 근거"와 규칙 기반 개인정보 잔존이다. 문장 수준 충실도는 현재 측정 수단이 없다.
- 필요하다면(팀 결정 후): ① 합성 사연마다 사람이 라벨한 "허용 요약/금지 주장" 쌍을 `tests/fixtures`에 추가, ② 모델 판정(LLM-as-judge)은 비결정적이고 비용이 들어 AWS 담당·팀 결정 뒤 별도 spec, ③ 그때까지 `reason` 등은 개인정보 검사와 길이·스키마 검증만 한다. 기존 호출 예산·질문 예산·타임아웃·게이트 기준은 바꾸지 않았다.
