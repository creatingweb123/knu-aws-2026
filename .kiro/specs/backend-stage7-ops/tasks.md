# Implementation Plan — 백엔드 7단계와 미완료 기능 마무리

상태 표기: `[x]` 구현·단위 테스트 완료, `[~]` 로컬 통합까지 완료, `[ ]` 대기(사유 표기). 커밋은 `feat/be-7-completion`에 있다(push·PR·병합 안 함).

- [x] 1. 작업 A: `GET /claims/{claimId}/record` — `transact_get_with_retry`, `serialize_record_view`, `get_record`, 핸들러·경로·`GetRecord` 이벤트, 단위 테스트 26건
  - [~] 1.1 로컬 어댑터 연동과 사진 상태 폴링 로컬 사례 4건
  - [ ] 1.2 **[승인 대기: BE-Q46]** `docs/03 §3.4`에 503 `TRY_AGAIN` 추가(프론트엔드 담당 승인 뒤)
  - [ ] 1.3 **[AWS 인수 판정 대기]** `test_T2_role_based_access`의 GET 행, `test_get_record_snapshot_during_writes`
- [x] 2. 작업 B: 사진 파이프라인 — 폴링 검증, `photo_orphans.py`(읽기 전용), 기존 S2–S7·G1–G4 회귀 유지
  - [ ] 2.1 **[승인 대기: BE-Q65]** `UploadIfNoneMatch` 활성화와 프론트 재업로드
  - [ ] 2.2 **[AWS 인수 판정 대기]** T8–T11, T15, 재업로드·IAM·CORS
- [x] 3. 작업 C: `docker-compose.yml` 중복 키 수정과 회귀 테스트
- [x] 4. 작업 D: 웹 호스팅 템플릿, `deploy_web.py`, 정적 테스트
  - [ ] 4.1 **[실제 AWS 배포 대기]** 배포, `scripts/deploy_web.py --apply`, `tests/integration/test_web.py`
- [x] 5. 작업 E: 알람 5종, 대시보드, 선택 Budgets
  - [ ] 5.1 **[승인 대기: BE-Q130·BE-Q131]** 임계값·예산 금액·수신자
  - [ ] 5.2 **[실제 AWS 배포 대기]** 알람·대시보드 표시 확인
- [x] 6. 작업 F: `seed.py`, `report.py`(Fake 구분은 환경 단위, Plan 지표는 바꾸지 않음)
  - [ ] 6.1 **[AWS 인수 판정 대기]** `demo` 스택에서 seed·report 실행
- [x] 7. 작업 G: 공급자 계층 점검(기존 테스트로 충족), 마스킹 스위치(기본 꺼짐)
  - [ ] 7.1 **[승인 대기: BE-Q6·Q7·Q10·Q26]** 운영 모델·동의 문구·마스킹 정책·실명 탐지
  - [ ] 7.2 **[실제 Bedrock 평가 대기]** `scripts/eval_agent.py`의 reason·summary·question 충실도 확장은 측정 방법이 없어 하지 않았다(README 참고)
- [x] 8. 문서: docs/07·08, README·backend README(작업 트리 변경과 함께), 이 spec
