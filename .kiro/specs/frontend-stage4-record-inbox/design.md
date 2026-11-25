# Design: frontend-stage4-record-inbox

## 파일

| 파일 | 내용 |
|---|---|
| `src/api/queries/useMyClaims.ts` | `['me', 'claims', status]` |
| `src/api/queries/useRecord.ts` | `['record', claimId]` (5단계에서 폴링 옵션 추가) |
| `src/api/queries/useInbox.ts` | `useInbox` `['inbox']`, `useInboxItem` `['inbox', itemId]` |
| `src/api/mutations/useAbandon.ts` | 포기 |
| `src/api/mutations/useCompleteText.ts` | `PUT /record` → `complete`(RECORD_REQUIRED·네트워크 오류 1회 재시도) |
| `src/api/mutations/useInboxActions.ts` | `useMarkRead`, `useReply` |
| `src/state/letterDraft.ts` | localStorage `haru.letterDraft.{claimId}` 읽기·쓰기·지우기 |
| `src/utils/claim.ts` | `dueText(dueAt, now)`, `recordPath(claimId, photoStatus)` |
| `src/pages/me/MyDayPage.tsx`, `AbandonPage.tsx` | 화면 4, 4-1 |
| `src/pages/record/RecordPage.tsx`, `DonePage.tsx`, `EndedNotice.tsx` | 화면 5, 5-4, 8 |
| `src/pages/inbox/InboxPage.tsx`, `InboxDetailPage.tsx` | 화면 6, 7, 7-1 |
| `src/mocks/handlers/claims.ts`, `inbox.ts` | 목업 |

## 캐시 무효화

| 동작 | 무효화 |
|---|---|
| 포기 | `plans`, `['me']` 접두(내 정보·내 하루), `plan(planId)` |
| 글로 완료 | `['me']` 접두, `['record', claimId]`, `plan(planId)` |
| 읽음 | `['inbox']` 접두, `['me']`(헤더 점) |
| 답장 | `['inbox']` 접두 |

`['me']` 접두는 `useMe`(`['me']`)와 `useMyClaims`(`['me','claims',…]`)를 함께 무효화한다.

## 글로 완료 흐름

```ts
async function completeText(claimId, letter) {
  await putRecord(claimId, letter);
  try { return await completeOnce(); }
  catch (e) {
    if (code === 'RECORD_REQUIRED') { await putRecord(claimId, letter); return completeOnce(); }
    if (!isApiError(e)) return completeOnce();   // 네트워크 오류(서버 멱등)
    throw e;
  }
}
```

## 작성 화면 상태

- 글 초기값은 `useRecord`가 끝난 뒤 한 번만 정한다(`record.letter` → 임시 글 → 빈 문자열). 이후 입력은 로컬 상태 + 임시 글 저장.
- `ended` 로컬 상태: `CLAIM_NOT_ACTIVE`를 받거나 `claimStatus`가 `ABANDONED`·`EXPIRED`면 화면 8을 같은 경로에서 그린다.

## 목업

- `claims.ts`: `lookupClaim(db, claimId, userId)` → `{ claim, plan }` 또는 404/403. `assertWritable(claim, plan)` → 409. 판정 함수(`abandonClaim`, `putRecord`, `getRecord`, `completeClaim`)는 순수 함수로 두고 핸들러가 `updateDb`로 감싼다.
- `inbox.ts`: `listInbox`, `inboxDetail`, `markRead`, `replyInbox`.
- `photoUrl`은 5단계 전까지 항상 `null`.

## 테스트

- `claims.test.ts`(목업): 포기·기록·완료 멱등·RECORD_REQUIRED·CLAIM_NOT_ACTIVE·403/404, `GET /me/claims`.
- `inbox.test.ts`(목업): 목록·상세 소유자·읽음·답장 409.
- `claim.test.ts`: `dueText`, `recordPath`.
- `MyDayFlow.test.tsx`: 내 하루 → 작성(임시 글 복원) → 글로 완료 → 5-4, 포기, 종료 안내, `RECORD_REQUIRED` 재시도.
- `InboxFlow.test.tsx`: 수신함 → 상세 읽음(점 사라짐) → 답장 → 7-1, 이미 답장한 항목, 409.
- `DemoScenario.test.tsx`: 지연 공개 → 수현 이어받기 → 글로 완료 → 지연 수신함 → 답장.
