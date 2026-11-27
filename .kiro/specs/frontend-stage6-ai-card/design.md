# Design: frontend-stage6-ai-card

## 파일

| 파일 | 내용 |
|---|---|
| `src/api/ai.ts` | `startSession`, `sendTurn`, `getSession`(공통 클라이언트, 타임아웃 35초) |
| `src/pages/plan/create/aiNextStep.ts` | `decideAiNextStep` |
| `src/pages/plan/create/useAiSession.ts` | 턴 진행 엔진(요청·재동기화·예약·실패) |
| `src/pages/plan/create/CardPage.tsx` (+ css) | 화면 3-1 |
| `src/pages/plan/create/cardForm.ts` | `cardToForm`, `restorePlace`, `flagMessage`, flag 경로 이동(`shiftPlaceFlags`) |
| `src/mocks/handlers/ai.ts` | MSW 세션 상태 머신 |
| `src/mocks/db.ts` | `aiSessions` 추가, `DB_VERSION` 3 |
| `src/state/planDraft.ts` | 선택 필드 `cardApplied`, `restoredNotes`, `aiFailed` |
| `src/api/types.ts` | `AiNote.restore?`(FE-Q7, MSW 임시 필드) |

## 턴 진행 엔진 (`useAiSession`)

상태: `view`, `busy`(요청 중), `consecutiveWorking`, `finishReserved`, `phase`.

```
start()            POST → handle | fail
resume(sessionId)  GET  → handle | fail
handle(view):
  저장(sessionId, turn, READY면 card·flags·notes)
  step = decideAiNextStep(view, consecutive, finishReserved)
  turn  → sendTurn({ expectedTurn: view.turn, finish? })
  ask   → 대기
  ready → 대기(화면이 카드 표시)
  failed→ fail()
sendTurn(body):
  200 → handle
  409 BUSY   → 2초 뒤 resync(sentTurn)
  409 CLOSED → resync(sentTurn, once)
  네트워크/타임아웃 → resync(sentTurn, once)
  VALIDATION_ERROR → 토스트 + resync
  그 외(404·503·502·429·5xx) → fail()
resync(sentTurn): GET
  WORKING && turn === sentTurn → 2초 뒤 다시(30초 넘으면 sendTurn 재전송)
  그 외 → handle (같은 턴 WORKING이 아니므로 연속 횟수 규칙 그대로)
```

- 언마운트 뒤 응답은 무시한다(`alive` ref). 시작 요청은 `started` ref로 한 번만.
- 예약: `busy` 중 "이대로 카드 받기" → `finishReserved = true`. 다음 `turn` 단계에 `finish: true`가 실리고, `ASKING`을 받으면 바로 `finish` 턴을 보낸다.

## 폼 연결

- `flags`는 Plan_Draft에 그대로 두고 폼이 경로로 찾는다. 입력을 고치면 그 경로 flag를 지운다.
- 장소 빼기: `places[i].*` flag 삭제, `places[j>i]` → `places[j-1]`로 경로 이동.
- 메시지 매핑 `flagMessage(type)`과 서버 `details`는 같은 경로 키를 쓴다(docs/07 §7.4 6단계 주석).

## MSW 상태 머신

세션 `{ sessionId, ownerId, story, scenario, status, turn, trace, question, card, flags, notes, degraded, pending? }`. 시나리오는 생성 때 정해 세션에 저장한다. `ai-busy`는 첫 `turns`에 409를 주고 내부적으로 READY(turn 2)를 `pending`으로 두고, 첫 `GET`은 turn 1 `WORKING`, 다음 `GET`에서 `pending`을 반영한다. READY 뒤 같은 `expectedTurn`의 `turns`는 409 CLOSED(§2.10 그대로).
