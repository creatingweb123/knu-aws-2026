# Implementation Plan: backend-stage3-claim

## Overview

이어받기·포기·기록(글)·완료 트랜잭션과 `GET /me/claims`를 `backend/`에 구현한다. 순서는 공통 모듈 → claim_service(moto 테스트) → 속성 테스트 → 핸들러 → 템플릿 → AWS 대상 테스트 → 인계 문서다. 판정(T3–T7, T14, T16)은 AWS 담당이 한다.

## Tasks

- [x] 1. 공통 모듈 확장
  - `errors.py`: `FORBIDDEN`, `ALREADY_CLAIMED`, `CANNOT_CLAIM_OWN_PLAN`, `CLAIM_NOT_ACTIVE`, `RECORD_REQUIRED`
  - `ids.py`: `new_claim_id()`; `metrics.py`: `emit(name)`(EMF)
  - `validation.py`: `RecordPut`(`letter` 1–1,000자, `photo` 금지), `CompleteIn`(`mode = TEXT_ONLY`)
  - `responses.py`: `serialize_record`; `plan_service.plan_update`에 `condition_names`
  - 단위 테스트 갱신(`test_errors.py` 코드 표, EMF 형식, 직렬화 허용 목록)
  - _Requirements: 6.1, 6.2, 8.1, 8.2_

- [x] 2. claim_service
  - [x] 2.1 `claim_plan`(신규·본인 재요청·소유자·확정됨·기한 지난 대체·재조회 분기, 이어받을 수 있게 바뀌면 최대 3회 재시도, 503 전 재조회, `ClaimConflict`)
    - _Requirements: 1.1–1.11_
  - [x] 2.2 `abandon`(404·403·409, Record 유무, `StaleRequestRejected`)
    - _Requirements: 2.1–2.5_
  - [x] 2.3 `put_record`(글만, 최소 구현. `GET /record`는 4단계)
    - _Requirements: 3.1–3.5_
  - [x] 2.4 `complete_claim`, `complete_by_user`(사진 상태 규칙, 멱등, 3회 재판정 후 503)
    - _Requirements: 4.1–4.11_
  - [x] 2.5 `list_my_claims`
    - _Requirements: 5.1–5.3_
  - [x] 2.6 moto 단위 테스트(`tests/unit/test_claim_service_moto.py`): 위 모든 분기, T6·T7·T14·T16 시나리오의 순차판
    - _Requirements: 9.1_
  - [x]* 2.7 속성 테스트(`tests/unit/test_claim_properties.py`): Property 13·14·15를 Hypothesis 연산 순서로
    - _Requirements: 9.1_

- [x] 3. 핸들러와 라우트
  - `handlers/_http.py`(헤더·본문 헬퍼 공유), `plans.py`(이어받기 201/200), `claims.py`(새), `me.py`(`/me/claims`), `routes.py`
  - 핸들러 테스트(`test_handlers_claims.py`), `test_handlers.py`의 라우트 목록 갱신
  - _Requirements: 7.1_

- [x] 4. 템플릿
  - `ClaimsFunction` 추가, Plans·Me 이벤트와 권한 확장, `test_template.py` 갱신
  - `cfn-lint`, `sam validate --lint`, `sam build`
  - _Requirements: 7.1–7.3, 9.3_

- [x] 5. AWS 스택 대상 테스트(작성 완료, 실행은 AWS 담당)
  - `tests/integration/test_concurrency.py`: T3(10명 동시), T4(본인 5회 동시), T5(완료 10회 동시), T14(`dueAt` 직접 변경, BE-Q38). 결과 로그 저장
  - `tests/integration/test_claim_lifecycle.py`: T6, T7, T16
  - InboxItem·Record·Claim 건수는 DynamoDB 직접 조회로 확인(BE-Q38)
  - conftest 정리 대상에 ClaimLookup·InboxItem 추가
  - _Requirements: 9.2_

- [x] 6. 로컬 통합 테스트(작성 완료, 실행은 Docker 확보 후)
  - `tests/local/test_local_claims.py`: 이어받기 → 기록 → 완료, 동시 이어받기 조건식 로직
  - _Requirements: 9.1_

- [x] 7. Checkpoint와 인계
  - 단위 테스트 전체, `sam validate --lint`, `sam build`
  - `backend/README.md` 3단계 런북·판정 실행표·IAM 표·미결 질문, "T3–T7 통과 전 4단계 금지"
  - `docs/08-open-questions.md`에 BE-Q34–BE-Q41 추가
  - README에 5단계 주의(포기 직전 생긴 Record, BE-Q34 해제)
  - push
  - _Requirements: 9.4_
