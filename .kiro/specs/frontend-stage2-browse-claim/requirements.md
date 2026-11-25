# Requirements: frontend-stage2-browse-claim

## Introduction

프론트엔드 2단계(docs/07 §7.4 "둘러보기 → 하루 상세 → 이어받기")를 만든다. 화면 1(둘러보기), 2(하루 들여다보기), 2-1(이미 이어받은 하루)이 대상이고, 요구사항은 FE-BRW-01–04, FE-PLN-01–05다. 모든 동작은 MSW 목업으로 확인한다. 실제 API 연동은 백엔드 S2(계획 API)·S3(이어받기) 이후 7단계에서 한다.

계약은 docs/03 §3.3(`GET /plans`, `GET /plans/{planId}`, `POST /plans/{planId}/claims`)을 그대로 따른다. 문서에 없는 결정은 docs/08 FE-Q17(목업 시나리오)을 따른다.

## Glossary

- **Browse_Page**: 화면 1, `/`.
- **Detail_Page**: 화면 2·2-1, `/plans/:planId`.
- **Claimed_Notice**: 2-1 안내 박스("이미 다른 사람이 이어받았어요" + "다른 하루 둘러보기").
- **Mock_Claim_Handler**: `POST /plans/{planId}/claims` 목업. 백엔드 `claim_service.claim_plan`과 같은 판정을 한다.

## Requirements

### Requirement 1: 둘러보기 카드 목록 [FE-BRW-01, FE-BRW-04]

**User Story:** 실행자로서, 이어받을 수 있는 하루를 한눈에 보고 싶다.

#### Acceptance Criteria

1. WHEN Browse_Page가 열리면 THE Browse_Page SHALL `GET /plans?status=OPEN` 결과를 응답 순서(서버가 최신순으로 준다) 그대로 카드로 보여 준다.
2. THE 카드 SHALL "이어받기 가능" 배지, 제목, `summary`(2줄 말줄임), `약 {estimatedMinutes}분 · 장소 {placeCount}곳`을 보여 준다.
3. WHEN 카드를 누르면 THE Browse_Page SHALL `/plans/{planId}`로 간다. 카드는 링크로 만들어 키보드로도 열 수 있다.
4. THE Browse_Page SHALL 내가 남긴 하루도 다른 카드와 같게 보여 주고, 이어받기 가능 여부를 목록에서 판단하지 않는다.
5. THE Browse_Page SHALL 첫 페이지만 보여 주고 `nextCursor`는 쓰지 않는다(FE-Q1).
6. WHILE 불러오는 중이면 THE Browse_Page SHALL 불러오는 중 표시를, 실패하면 공통 오류 문구와 "다시 시도" 버튼을 보여 준다.

### Requirement 2: 빈 상태와 하루 남기기 버튼 [FE-BRW-02, FE-BRW-03]

#### Acceptance Criteria

1. WHEN 목록이 비면 THE Browse_Page SHALL "아직 남겨진 하루가 없어요"와 하루 남기기 유도 문구를 보여 준다.
2. THE Browse_Page SHALL 제목 아래 "취소된 하루 남기기" 버튼으로 `/plans/new`에 간다(목록이 비어도 같다). 하단 탭이 있는 화면이라 하단 고정 버튼으로 두지 않는다(탭과 겹친다).

### Requirement 3: 하루 상세 내용 [FE-PLN-01]

#### Acceptance Criteria

1. THE Detail_Page SHALL 제목, `summary`, `약 {n}분 · 장소 {k}곳`을 보여 준다.
2. THE Detail_Page SHALL 계획자 박스("{계획자 닉네임} · 취소한 이유" + `reason`)를 `--color-plan` 배경으로 보여 준다.
3. THE Detail_Page SHALL 산책 동선을 RouteTimeline(장소 이름·하고 싶었던 일·고른 이유)으로 보여 준다. `whyChosen`이 빈 문자열이면 그 줄을 생략한다.
4. THE Detail_Page SHALL 대표 사진 자리에 장식용 플레이스홀더를 둔다(docs/05 §5.6 4번, 스크린 리더에는 숨김).

### Requirement 4: 상세 상태 분기 [FE-PLN-02]

위에서부터 먼저 맞는 하나만 적용한다. 분기 판단은 순수 함수 `decideDetailView`로 두고 단위 테스트한다.

#### Acceptance Criteria

1. WHEN `GET /plans/{planId}`가 404 `NOT_FOUND`이면 THE Detail_Page SHALL "이 하루는 더 이상 볼 수 없어요"와 "둘러보기로 가기" 버튼만 보여 준다.
2. WHEN `myClaim?.status === 'ACTIVE'`이면 THE Detail_Page SHALL "내가 이어받은 하루" 배지와 "내 하루로 가기"(`/me`) 버튼을 보여 준다.
3. WHEN `isOwner`이면 THE Detail_Page SHALL "내가 남긴 하루" 배지와 상태 배지(OPEN → 공개, CLAIMED → 이어받음, COMPLETED → 완료)를 보여 주고 버튼을 두지 않는다.
4. WHEN `claimable`이면 THE Detail_Page SHALL "이어받기 가능" 배지와 "이 하루 이어받기" 버튼을 보여 준다.
5. WHEN `plan.status === 'CLAIMED'`이면 THE Detail_Page SHALL "이어받음" 배지와 Claimed_Notice를 보여 준다.
6. WHEN `plan.status === 'COMPLETED'`이면 THE Detail_Page SHALL "완료" 배지만 보여 주고 버튼을 두지 않는다(읽기 전용).
7. OTHERWISE THE Detail_Page SHALL 동선과 "다른 하루 둘러보기"(`/`) 버튼을 보여 준다(방어용).
8. IF 404 외의 오류이면 THE Detail_Page SHALL 공통 오류 문구와 "다시 시도" 버튼을 보여 준다.

### Requirement 5: 이어받기 [FE-PLN-03, FE-PLN-04, FE-PLN-05]

#### Acceptance Criteria

1. WHEN "이 하루 이어받기"를 누르면 THE Detail_Page SHALL `POST /plans/{planId}/claims`를 보내고, 요청 중에는 버튼을 비활성화한다(FE-NFR-03).
2. WHEN 응답이 201 또는 200이면 THE Detail_Page SHALL 목록·상세·내 하루 캐시를 무효화하고 `/me`로 이동한다.
3. WHEN 응답이 409 `ALREADY_CLAIMED`이면 THE Detail_Page SHALL 페이지를 옮기지 않고 같은 화면에 Claimed_Notice를 띄우고 이어받기 버튼을 숨긴다. 목록·상세 캐시는 무효화한다.
4. WHEN 응답이 409 `CANNOT_CLAIM_OWN_PLAN`이면 THE Detail_Page SHALL 토스트("내가 남긴 하루는 이어받을 수 없어요.")를 띄운다.
5. WHEN 그 밖의 오류(404 포함)이면 THE Detail_Page SHALL 공통 오류 문구를 토스트로 띄우고 상세를 다시 읽는다. `TRY_AGAIN`의 1회 재시도는 Client가 한다(FE-COM-04).
6. WHEN Claimed_Notice의 "다른 하루 둘러보기"를 누르면 THE Detail_Page SHALL `/`로 간다.

### Requirement 6: 이어받기 목업 [FE-TECH-04, docs/03 §3.3, FE-Q17]

#### Acceptance Criteria

1. THE Mock_Claim_Handler SHALL 백엔드 판정 순서를 따른다: 계획 없음 → 404 `NOT_FOUND` / 소유자 → 409 `CANNOT_CLAIM_OWN_PLAN` / 본인의 현재 ACTIVE Claim → 200과 기존 Claim / OPEN 또는 기한 지난 CLAIMED → 201과 새 Claim / 그 외 → 409 `ALREADY_CLAIMED`.
2. WHEN 새 Claim을 만들면 THE Mock_Claim_Handler SHALL `claimId = "clm_" + 고유값`, `dueAt = 지금 + 3일`, Plan을 `CLAIMED`(`currentClaimId`·`claimerId`·`dueAt`)로 바꾸고, 기한 지난 이전 Claim은 `EXPIRED`로 바꾼다.
3. THE Mock_Claim_Handler SHALL 읽기·판정·쓰기를 localStorage DB 한 번의 갱신 안에서 해서, 두 탭이 순서대로 요청하면 두 번째가 409 `ALREADY_CLAIMED`를 받는다.
4. WHERE `?mock=claim-conflict`이면 THE Mock_Claim_Handler SHALL 판정 없이 409 `ALREADY_CLAIMED`를 돌려준다(한 탭에서 2-1 확인용).
5. WHERE `?mock=browse-empty`이면 THE 목록 목업 SHALL 빈 `items`를 돌려준다(빈 상태 확인용).

### Requirement 7: 검증

#### Acceptance Criteria

1. THE 테스트 SHALL `decideDetailView`의 7가지 분기, Mock_Claim_Handler의 판정(201/200/409 두 종/404, 두 사용자 순차 경합, 기한 지난 대체), Browse_Page의 카드·빈 상태, Detail_Page의 이어받기 성공 이동·`ALREADY_CLAIMED` 안내·`CANNOT_CLAIM_OWN_PLAN` 토스트를 확인한다.
2. THE Frontend SHALL `npm run lint`, `npm run test`, `npm run build`, `npm run format:check`를 오류 없이 통과한다.
3. 두 브라우저 탭(수현/민준) 경합의 실제 브라우저 확인은 개발 담당이 한다. 자동 테스트는 같은 DB에 두 사용자가 차례로 요청하는 것으로 대신한다.
