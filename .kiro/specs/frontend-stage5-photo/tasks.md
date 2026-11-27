# Implementation Plan: frontend-stage5-photo

- [x] 1. docs/08 FE-Q23·FE-Q24
- [x] 2. 목업: `photos.ts`, `claims.ts`(photo·교체·업로드·처리), 수신함 `photoUrl`
  - _Requirements: 6_
- [x] 3. `utils/photo.ts`, `api/upload.ts`, `usePhotoSend`, `sendingClock`, `sendingState`
  - _Requirements: 1.1, 2, 3_
- [x] 4. 화면: `PhotoPicker`, 작성 화면 사진, 보내는 중·실패(5-1·5-2), 교체(5-3), 라우트
  - _Requirements: 1, 2, 3, 4_
- [x] 5. 테스트와 검증: lint, tsc, test(21파일 204건), build, format:check
  - _Requirements: 5, 7_
- [x] 6. push `feat/fe-5-photo`

## 구현 중 바뀐 것

- 목업 핸들러의 DB 접근은 모두 `withDb`(사진 처리 결과를 먼저 반영)를 거친다. `GET /me`도 포함해 사진으로 완료된 편지가 헤더 점에 바로 보인다.
- `useRecord`의 폴링은 4xx 오류가 나면 멈춘다(판정이 종료로 끝나므로).
- 테스트 환경(jsdom)의 `Blob`에 `stream()`이 없어 Node fetch가 업로드 본문을 보내지 못하므로 `src/test/setup.ts`에 채웠다. 테스트는 사진 처리 지연을 0으로 둔다.
- 업로드 함수는 `fetch`를 직접 쓴다(presigned URL, 토큰 없음). FE-COM-05("모든 API 호출은 공통 클라이언트")의 예외로 `api/upload.ts` 주석에 적었다.
