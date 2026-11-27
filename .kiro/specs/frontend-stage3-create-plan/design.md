# Design: frontend-stage3-create-plan

## 파일

| 파일 | 내용 |
|---|---|
| `src/state/planDraft.ts` | Plan_Draft 타입, `loadDraft`/`saveDraft`/`clearDraft`/`startDraft`, `usePlanDraft()` |
| `src/utils/validation.ts` | `validateStory`, `validatePlace`, `validatePlanForm` → `{ [path]: message }`. 문구는 백엔드 `_FIELD_MESSAGES`와 같다 |
| `src/utils/hash.ts` | `canonicalJson`, `hashString`(cyrb53, 동기) |
| `src/utils/uuid.ts` | `newUuid()` = `crypto.randomUUID()` |
| `src/pages/plan/create/publish.ts` | `buildPlanContent(draft)`, `preparePublish(draft, now)` → `{ body, key, draftPatch }` |
| `src/api/mutations/useCreatePlan.ts` | `POST /plans` + `Idempotency-Key`, `IDEMPOTENCY_CONFLICT`면 새 키로 1회 |
| `src/pages/plan/create/StoryPage.tsx` | 화면 3 |
| `src/pages/plan/create/PlanFormPage.tsx` | 화면 3-2 |
| `src/pages/plan/create/PlacePage.tsx` | 화면 3-3 |
| `src/pages/plan/create/PublishedPage.tsx` | 화면 3-4 |
| `src/pages/plan/create/Create.module.css` | 3·3-2·3-3 공통 스타일 |
| `src/mocks/handlers/plans.ts` | `createPlan()`과 `POST /plans` 핸들러 |
| `src/mocks/db.ts` | `idempotency` 항목 추가, `DB_VERSION` 2(이전 버전 저장값은 새 시드로 바뀐다) |

2단계의 `api/queries/useClaimPlan.ts`는 docs/02 §2.10 구조에 맞춰 `api/mutations/useClaim.ts`로 옮긴다.

## Plan_Draft

```ts
interface PlanForm {
  title: string; summary: string; reason: string;
  estimatedMinutes: string;          // 입력칸 값 그대로. 공개 때 정수로 바꾼다
  places: PlaceInput[]; question: string;
}
interface PlanDraft {
  story: string;
  sessionId: string | null; turn: number | null;   // 6단계
  card: AiCard | null; flags: Flag[]; notes: AiNote[]; // 6단계
  form: PlanForm;
  mode: AuthoringMode;               // 기본 MANUAL
  startedAt: number;                 // epoch ms
  idempotencyKey: string | null;
  keyBodyHash: string | null;
  keyDurationMs: number | null;
}
```

- 키 `haru.planDraft`. `version` 필드로 형태를 확인하고, 다르면 버린다.
- `startDraft(now)`: 저장된 초안이 있으면 그대로, 없으면 `startedAt = now`로 새로 만들어 저장한다. Story_Page만 부른다.
- `usePlanDraft()`: 마운트 때 읽고, `update(fn)`은 상태와 sessionStorage를 함께 바꾼다. 화면마다 따로 마운트되므로 화면 사이 공유는 sessionStorage로 한다.

## 공개 키 규칙 (FE-Q18)

`durationMs`는 누를 때마다 바뀌므로 본문 전체를 비교하면 재전송도 새 키가 되어 Plan이 두 번 생길 수 있다. 그래서:

1. `content` = 공개 본문에서 `authoring.durationMs`를 뺀 값. `hash = hashString(canonicalJson(content))`.
2. `hash === draft.keyBodyHash`이고 키가 있으면 저장된 `idempotencyKey`·`keyDurationMs`로 본문을 만든다(서버가 보는 본문이 같다).
3. 아니면 `key = newUuid()`, `durationMs = max(0, now − startedAt)`를 만들어 Plan_Draft에 저장한 뒤 보낸다.
4. 409 `IDEMPOTENCY_CONFLICT` → 새 키(같은 본문)로 1회. 성공하면 새 키는 저장할 필요가 없다(초안을 지운다).

## 공백 (FE-Q19)

검증과 전송 모두 앞뒤 공백을 뺀 값을 쓴다. 공백만 입력하면 "필수"와 같은 길이 오류가 된다. 글자 수는 코드 포인트(`[...s].length`)로 센다(백엔드 pydantic과 같음).

## 폼 오류 표시

- 클라이언트 오류와 서버 `details`를 같은 `{ [path]: message }` 모양으로 합쳐 보여 준다. 입력을 고치면 그 경로의 오류만 지운다.
- 장소 오류(`places[i].name` 등)는 i번째 장소 항목 아래에, `places`(개수)는 '방문할 장소' 제목 아래에 보여 준다.

## 목업 `POST /plans`

`createPlan(db, user, key, body, nowMs)`:
1. 키 없음/공백 → `VALIDATION_ERROR { "Idempotency-Key": "필수 헤더예요." }`
2. `validateCreatePlan(body)`(타입 엄격, 경로·문구는 백엔드와 같음) 오류 → `VALIDATION_ERROR`
3. `db.idempotency["{userId}#{key}"]`가 있으면 해시 비교 → 같으면 기존 Plan, 다르면 `IDEMPOTENCY_CONFLICT`
4. 새 Plan 저장, 키 항목 저장 → 201

## 테스트

- `validation.test.ts`, `planDraft.test.ts`, `publish.test.ts`(키 재사용·새 키·aiSessionId 규칙)
- `plans.test.ts` 추가: `createPlan` 201/재요청/409/400
- `CreatePlanFlow.test.tsx`: 사연 → 직접 작성 → 폼 기본값 → 장소 추가·고치기·빼기 → 공개 → 3-4 → 둘러보기 맨 앞. 새로고침(다시 렌더) 뒤 값·`startedAt` 유지. 서버 `VALIDATION_ERROR` 표시. `IDEMPOTENCY_CONFLICT` 재요청.
