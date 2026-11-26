# Design: frontend-stage5-photo

## 파일

| 파일 | 내용 |
|---|---|
| `src/utils/photo.ts` | `validatePhoto(file)`, `PHOTO_MAX_BYTES`, `photoMeta(file)` |
| `src/api/upload.ts` | `uploadPhoto(upload, file)` — `client.ts`를 거치지 않는 presigned PUT(토큰 없음) |
| `src/api/mutations/usePhotoSend.ts` | `useSendWithPhoto`(PUT /record + 업로드), `useReplacePhoto`(POST /record/photo + 업로드) |
| `src/state/sendingClock.ts` | sessionStorage `haru.sending.{claimId}` `{ startedAt, uploadFailed }` |
| `src/pages/record/sendingState.ts` | `decideSendingState` |
| `src/pages/record/PhotoPicker.tsx` | 파일 입력·검사·미리보기·빼기(5, 5-3 공용) |
| `src/pages/record/SendingPage.tsx` | 5-1 / 5-2 (같은 경로, 상태 분기) |
| `src/pages/record/PhotoReplacePage.tsx` | 5-3 |
| `src/pages/record/useFinishText.ts` | 5-1·5-2·5-3의 "글로 완료하기"(서버 글 → 임시 글) |
| `src/mocks/photos.ts` | 처리 지연·결과 계산(`advancePhotos`), 업로드 URL, 고정 그림 |

`useRecord`에 `refetchInterval` 옵션을 더한다. 업로드 함수는 `fetch`를 직접 쓰므로 FE-COM-05("API 호출은 공통 클라이언트")의 예외다. 업로드 대상은 우리 API가 아니라 S3 presigned URL이고, 토큰을 붙이면 안 된다.

## 업로드 성공·실패 처리

```
markSending(claimId, now)                // startedAt
try { await uploadPhoto(upload, file) } catch { markUploadFailed(claimId) }
navigate(`/claims/${id}/sending`, { replace: true })
```

`PUT /record`가 실패하면(409·400 등) 보내는 중으로 가지 않는다.

## 보내는 중 화면

- `useRecord(claimId, { refetchInterval: 2000 })`, 1초 타이머로 경과 시간을 다시 그린다.
- 판정 결과가 완료면 effect에서 정리 후 이동, 종료면 `EndedNotice`, 실패면 5-2, 대기면 5-1.
- `testid`: 바깥 `screen-5-1`(라우트 테스트), 실패 안쪽 `screen-5-2`.

## 목업 처리 계산

`advancePhotos(db, nowMs)`는 `PROCESSING`이고 `processReadyAt <= now`인 기록을 끝낸다. 시나리오는 처리를 시작할 때(업로드 PUT) 정해 `photoOutcome`에 저장한다(탭마다 시나리오가 달라도 결과가 고정된다). 핸들러는 `GET /record`, `GET /me/claims`, `GET /me`, `GET /inbox*`, `PUT /record`, `POST /record/photo`, `POST /complete` 전에 `advancePhotos`를 부른다. 테스트는 `setPhotoProcessMs(0)`으로 지연을 없앤다.
