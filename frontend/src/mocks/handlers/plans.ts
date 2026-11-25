/**
 * 계획 목록·상세 목업(docs/03 §3.3). 상태 표시 규칙은 백엔드 plan_service와 같다.
 * - 기한 지난 CLAIMED는 현재 실행자가 아닌 요청자에게 OPEN으로 보인다.
 * - COMPLETED는 소유자와 그 실행자만 볼 수 있고, 그 외는 404.
 * - myClaim은 요청자의 ACTIVE·COMPLETED Claim만. claimable = !isOwner && myClaim == null && (OPEN 또는 기한 지난 CLAIMED).
 *
 * 이어받기(`POST /plans/{planId}/claims`)는 백엔드 claim_service.claim_plan과 같은 순서로 판정한다.
 * 시나리오(FE-Q17): `?mock=claim-conflict`는 항상 409 ALREADY_CLAIMED, `?mock=browse-empty`는 빈 목록.
 */
import { HttpResponse, http } from 'msw';

import type {
  Claim,
  ClaimResponse,
  ErrorCode,
  Plan,
  PlanDetailResponse,
  PlanListResponse,
  PlanSummary,
} from '../../api/types';
import type { DbClaim, DbPlan, MockDb } from '../db';
import { CLAIM_DURATION_DAYS, DAY_MS, iso, loadDb, updateDb } from '../db';
import { getMockScenario } from '../session';
import { api, apiError, currentUser, unauthorized } from './common';

const isOverdue = (p: DbPlan, nowIso: string) => p.status === 'CLAIMED' && !!p.dueAt && p.dueAt < nowIso;

export function toPlan(p: DbPlan, viewerId: string, nowIso: string): Plan {
  const isCurrentClaimer = p.claimerId === viewerId;
  const status = isOverdue(p, nowIso) && !isCurrentClaimer ? 'OPEN' : p.status;
  const plan: Plan = {
    planId: p.planId,
    areaId: p.areaId,
    owner: { userId: p.ownerId, nickname: p.ownerNickname },
    title: p.title,
    summary: p.summary,
    reason: p.reason,
    estimatedMinutes: p.estimatedMinutes,
    places: p.places.map((x) => ({ ...x })),
    question: p.question,
    status,
    createdAt: p.createdAt,
    completedAt: p.completedAt,
  };
  if (p.ownerId === viewerId) plan.metrics = { ...p.metrics };
  return plan;
}

export function toClaim(c: DbClaim): Claim {
  return {
    claimId: c.claimId,
    planId: c.planId,
    claimer: { userId: c.claimerId, nickname: c.claimerNickname },
    status: c.status,
    claimedAt: c.claimedAt,
    dueAt: c.dueAt,
    completedAt: c.completedAt,
    late: c.late,
  };
}

export function listOpenPlans(db: MockDb, nowIso: string): PlanSummary[] {
  return db.plans
    .filter((p) => p.status === 'OPEN' || isOverdue(p, nowIso))
    .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
    .map((p) => ({
      planId: p.planId,
      title: p.title,
      summary: p.summary,
      estimatedMinutes: p.estimatedMinutes,
      placeCount: p.places.length,
      status: 'OPEN',
      ownerNickname: p.ownerNickname,
      createdAt: p.createdAt,
    }));
}

export function planDetail(
  db: MockDb,
  planId: string,
  viewerId: string,
  nowIso: string,
): PlanDetailResponse | null {
  const p = db.plans.find((x) => x.planId === planId);
  if (!p) return null;
  const isOwner = p.ownerId === viewerId;
  if (p.status === 'COMPLETED' && !isOwner && p.claimerId !== viewerId) return null;
  const mine = db.claims
    .filter(
      (c) =>
        c.planId === planId &&
        c.claimerId === viewerId &&
        (c.status === 'ACTIVE' || c.status === 'COMPLETED'),
    )
    .sort((a, b) => (a.claimedAt < b.claimedAt ? 1 : -1))[0];
  const myClaim = mine ? toClaim(mine) : null;
  const claimable = !isOwner && myClaim === null && (p.status === 'OPEN' || isOverdue(p, nowIso));
  return { plan: toPlan(p, viewerId, nowIso), isOwner, myClaim, claimable };
}

export type ClaimOutcome = { status: 200 | 201; claim: Claim } | { error: ErrorCode };

const CLAIM_MESSAGES: Partial<{ [code in ErrorCode]: string }> = {
  NOT_FOUND: '찾을 수 없어요.',
  CANNOT_CLAIM_OWN_PLAN: '내가 남긴 하루는 이어받을 수 없어요.',
  ALREADY_CLAIMED: '이미 다른 사람이 이어받았어요.',
};

function newClaimId(): string {
  return `clm_${crypto.randomUUID().replace(/-/g, '').slice(0, 26).toUpperCase()}`;
}

/**
 * 이어받기 판정과 쓰기(백엔드 `_decide_claim`·`claim_plan`과 같은 순서). `db`를 직접 바꾼다.
 * 1. 계획 없음 → NOT_FOUND
 * 2. 소유자 → CANNOT_CLAIM_OWN_PLAN
 * 3. 본인의 현재 ACTIVE Claim → 200 기존 Claim(기한이 지났어도)
 * 4. OPEN 또는 기한 지난 CLAIMED → 201 새 Claim(이전 Claim은 EXPIRED)
 * 5. 그 외 → ALREADY_CLAIMED
 */
export function claimPlan(
  db: MockDb,
  planId: string,
  user: { userId: string; nickname: string },
  nowMs: number,
): ClaimOutcome {
  const nowIso = iso(nowMs);
  const plan = db.plans.find((p) => p.planId === planId);
  if (!plan) return { error: 'NOT_FOUND' };
  if (plan.ownerId === user.userId) return { error: 'CANNOT_CLAIM_OWN_PLAN' };

  const current = plan.currentClaimId ? db.claims.find((c) => c.claimId === plan.currentClaimId) : undefined;
  if (plan.status === 'CLAIMED' && plan.claimerId === user.userId && current?.status === 'ACTIVE') {
    return { status: 200, claim: toClaim(current) };
  }
  if (plan.status !== 'OPEN' && !isOverdue(plan, nowIso)) return { error: 'ALREADY_CLAIMED' };

  if (plan.status === 'CLAIMED' && current?.status === 'ACTIVE') current.status = 'EXPIRED';
  const dueAt = iso(nowMs + CLAIM_DURATION_DAYS * DAY_MS);
  const claim: DbClaim = {
    claimId: newClaimId(),
    planId,
    claimerId: user.userId,
    claimerNickname: user.nickname,
    status: 'ACTIVE',
    claimedAt: nowIso,
    dueAt,
    completedAt: null,
    late: false,
  };
  db.claims.push(claim);
  plan.status = 'CLAIMED';
  plan.currentClaimId = claim.claimId;
  plan.claimerId = user.userId;
  plan.dueAt = dueAt;
  return { status: 201, claim: toClaim(claim) };
}

export const planHandlers = [
  http.get(api('/plans'), ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const status = new URL(request.url).searchParams.get('status');
    if (status !== 'OPEN') {
      return apiError('VALIDATION_ERROR', '입력값을 확인해 주세요.', 400, { status: 'OPEN만 쓸 수 있어요.' });
    }
    const items =
      getMockScenario() === 'browse-empty' ? [] : listOpenPlans(loadDb(), new Date().toISOString());
    const body: PlanListResponse = { items, nextCursor: null };
    return HttpResponse.json(body);
  }),

  http.post(api('/plans/:planId/claims'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    if (getMockScenario() === 'claim-conflict') {
      return apiError('ALREADY_CLAIMED', CLAIM_MESSAGES.ALREADY_CLAIMED!);
    }
    // 읽기·판정·쓰기를 한 번의 갱신으로 한다. 이 구간에 await가 없어 두 탭의 요청은 차례로 처리된다
    const outcome = updateDb((db) => claimPlan(db, String(params.planId), user, Date.now()));
    if ('error' in outcome) return apiError(outcome.error, CLAIM_MESSAGES[outcome.error] ?? '');
    const body: ClaimResponse = { claim: outcome.claim };
    return HttpResponse.json(body, { status: outcome.status });
  }),

  http.get(api('/plans/:planId'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const detail = planDetail(loadDb(), String(params.planId), user.userId, new Date().toISOString());
    if (!detail) return apiError('NOT_FOUND', '찾을 수 없어요.');
    return HttpResponse.json(detail);
  }),
];
