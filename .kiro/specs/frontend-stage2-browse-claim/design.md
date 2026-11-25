# Design: frontend-stage2-browse-claim

## 개요

1단계 골격 위에 화면 1·2·2-1을 채운다. 새 공통 컴포넌트는 만들지 않고 StatusBadge, RouteTimeline, PrimaryButton, ResultScreen, Toast를 쓴다. 상세 분기는 순수 함수로 떼어 테스트하고, 이어받기 목업은 백엔드 `claim_service`와 같은 판정을 순수 함수로 구현한다.

## 파일

| 파일 | 내용 |
|---|---|
| `src/utils/plan.ts` | `planMetaText(minutes, placeCount)` → `약 45분 · 장소 2곳` |
| `src/pages/browse/BrowsePage.tsx` (+ `.module.css`) | 화면 1. 카드 목록, 빈 상태, 오류·다시 시도 |
| `src/pages/browse/PlanCard.tsx` (+ `.module.css`) | 카드(`<Link>`) |
| `src/pages/plan/detailView.ts` | `decideDetailView(detail, { conflict })` → 7가지 중 하나 |
| `src/pages/plan/PlanDetailPage.tsx` (+ `.module.css`) | 화면 2·2-1 |
| `src/pages/plan/ClaimedNotice.tsx` | 2-1 안내 박스 |
| `src/api/queries/useClaimPlan.ts` | `POST /plans/{planId}/claims` 뮤테이션, 캐시 무효화 |
| `src/mocks/handlers/plans.ts` | `claimPlan()` 판정 함수와 핸들러, `?mock=claim-conflict`·`?mock=browse-empty` |
| `src/routes.tsx` | `/plans/:planId` → `PlanDetailPage` |

## 상세 분기

```ts
type DetailView = 'notFound' | 'myClaim' | 'owner' | 'claimable' | 'claimed' | 'completed' | 'other';
decideDetailView(detail: PlanDetailResponse | null, opts: { notFound: boolean; conflict: boolean }): DetailView
```

- 순서는 docs/05 §5.2.2 그대로: notFound → `myClaim?.status === 'ACTIVE'` → `isOwner` → `claimable` → `status === 'CLAIMED'` → `status === 'COMPLETED'` → other.
- `conflict`는 이어받기 요청이 409 `ALREADY_CLAIMED`를 받았다는 화면 상태다. 결과가 `claimable`이나 `other`일 때만 `claimed`로 바꾼다. 다시 읽은 상세가 `myClaim`·`owner`·`completed`를 말하면 그쪽을 따른다(서버 상태가 우선).

| 분기 | 배지 | 하단 |
|---|---|---|
| notFound | — | ResultScreen("이 하루는 더 이상 볼 수 없어요") + 둘러보기로 가기 |
| myClaim | 내가 이어받은 하루 | 내 하루로 가기 → `/me` |
| owner | 내가 남긴 하루 + 공개/이어받음/완료 | 없음 |
| claimable | 이어받기 가능 | 이 하루 이어받기 |
| claimed | 이어받음 | ClaimedNotice(박스 안에 "다른 하루 둘러보기") |
| completed | 완료 | 없음 |
| other | — | 다른 하루 둘러보기 |

## 이어받기 흐름

`useClaimPlan(planId)`:
- 성공(201/200): `plans`, `plan(planId)`, `['me']` 접두 키(내 정보·내 하루)를 무효화하고 `navigate('/me')`.
- `ALREADY_CLAIMED`: `conflict = true`, `plans`·`plan(planId)` 무효화.
- `CANNOT_CLAIM_OWN_PLAN`: `toast(errorMessage(e))`.
- 그 외: `toast(errorMessage(e))`, `plan(planId)` 무효화.
- 버튼은 `mutation.isPending` 동안 `loading`.

`/me/claims` 쿼리 키는 4단계에서 `['me', 'claims', status]`로 만든다. 여기서는 `['me']` 접두로 무효화해 미리 맞춘다.

## 이어받기 목업

`claimPlan(db, planId, user, nowMs)`는 DB를 직접 바꾸고 `{ status: 201 | 200, claim }` 또는 `{ error: code }`를 돌려준다. 핸들러는 `updateDb` 안에서 부르므로 읽기·판정·쓰기가 한 번의 localStorage 갱신이다. 브라우저 탭은 단일 스레드이고 MSW 핸들러의 이 구간에 `await`가 없으므로, 두 탭의 요청은 차례로 처리되고 두 번째는 갱신된 DB를 읽는다.

판정 순서(백엔드 `_decide_claim`):
1. 계획 없음 → `NOT_FOUND`
2. `ownerId === me` → `CANNOT_CLAIM_OWN_PLAN`
3. `CLAIMED`이고 `claimerId === me`이고 현재 Claim이 ACTIVE → 200 기존 Claim(기한이 지났어도)
4. `OPEN` 또는 기한 지난 `CLAIMED` → 201 새 Claim. 이전 Claim이 있으면 `EXPIRED`
5. 그 외(기한 내 남의 CLAIMED, COMPLETED) → `ALREADY_CLAIMED`

## 목업 시나리오 (FE-Q17)

| 값 | 동작 |
|---|---|
| `?mock=claim-conflict` | `POST /plans/{planId}/claims`가 판정 없이 409 `ALREADY_CLAIMED` |
| `?mock=browse-empty` | `GET /plans?status=OPEN`이 빈 `items` |

두 탭 경합은 시나리오 없이 재현한다: 탭 A 수현, 탭 B 민준으로 같은 OPEN 하루를 열고 A → B 순서로 누른다.

## 테스트

- `detailView.test.ts`: 분기 7개와 `conflict` 덮어쓰기 규칙.
- `plans.test.ts`(추가): `claimPlan` 201/200/404/두 종 409, 수현 → 민준 차례 경합, 기한 지난 대체(EXPIRED), 시나리오 두 개.
- `BrowsePage.test.tsx`: 카드 내용·링크, 빈 상태, 하루 남기기 이동.
- `PlanDetailPage.test.tsx`: 사용자별 분기 화면, 이어받기 → `/me`, `claim-conflict` → 안내 박스, 소유자 강제 요청 → 토스트.
