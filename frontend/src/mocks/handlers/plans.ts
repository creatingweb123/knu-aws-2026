/**
 * 계획 목록·상세 목업(docs/03 §3.3). 상태 표시 규칙은 백엔드 plan_service와 같다.
 * - 기한 지난 CLAIMED는 현재 실행자가 아닌 요청자에게 OPEN으로 보인다.
 * - COMPLETED는 소유자와 그 실행자만 볼 수 있고, 그 외는 404.
 * - myClaim은 요청자의 ACTIVE·COMPLETED Claim만. claimable = !isOwner && myClaim == null && (OPEN 또는 기한 지난 CLAIMED).
 * 이어받기 등 쓰기 경로는 2단계에서 추가한다.
 */
import { HttpResponse, http } from 'msw';

import type { Claim, Plan, PlanDetailResponse, PlanListResponse, PlanSummary } from '../../api/types';
import type { DbClaim, DbPlan, MockDb } from '../db';
import { loadDb } from '../db';
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

export const planHandlers = [
  http.get(api('/plans'), ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const status = new URL(request.url).searchParams.get('status');
    if (status !== 'OPEN') {
      return apiError('VALIDATION_ERROR', '입력값을 확인해 주세요.', 400, { status: 'OPEN만 쓸 수 있어요.' });
    }
    const body: PlanListResponse = {
      items: listOpenPlans(loadDb(), new Date().toISOString()),
      nextCursor: null,
    };
    return HttpResponse.json(body);
  }),

  http.get(api('/plans/:planId'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const detail = planDetail(loadDb(), String(params.planId), user.userId, new Date().toISOString());
    if (!detail) return apiError('NOT_FOUND', '찾을 수 없어요.');
    return HttpResponse.json(detail);
  }),
];
