# Implementation Plan: frontend-stage4-record-inbox

- [x] 1. docs/08 FE-Q21·FE-Q22 추가, FE-Q19 적용 범위 확장
- [x] 2. 목업: `claims.ts`(내 하루·포기·기록·완료), `inbox.ts`(목록·상세·읽음·답장)
  - _Requirements: 7_
- [x] 3. 쿼리·뮤테이션, `letterDraft`, `utils/claim.ts`
  - _Requirements: 1.3, 1.4, 3.2, 3.5_
- [x] 4. 내 하루(4), 포기(4-1)
  - _Requirements: 1, 2_
- [x] 5. 방문 기록 작성(5), 전송 완료(5-4), 종료 안내(8)
  - _Requirements: 3, 4_
- [x] 6. 수신함(6), 돌아온 하루(7, 7-1)
  - _Requirements: 5, 6_
- [x] 7. 테스트와 검증: lint, tsc, test(18파일 180건, 시연 시나리오 포함), build, format:check
  - _Requirements: 8_
- [x] 8. push `feat/fe-4-record-inbox`

## 구현 중 바뀐 것

- 포기 성공 때 "이어받기를 포기했어요. 이 하루는 다시 공개돼요." 토스트를 띄운다(요구사항에는 이동만 있었다).
- 전송 완료(5-4)에서 새로고침 후 `GET /record`를 읽지 못하면(404 등) "전송 결과를 확인하고 있어요"와 둘러보기 버튼만 보여 준다.
- 돌아온 하루의 사진(`photoUrl`)과 로드 실패 시 1회 재조회는 화면에 넣었지만, 목업은 5단계 전까지 `photoUrl: null`이라 사진 경로는 5단계에서 확인한다.
