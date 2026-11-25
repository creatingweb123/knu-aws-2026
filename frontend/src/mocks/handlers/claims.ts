/**
 * 내 하루·포기·방문 기록·완료 목업(docs/03 §3.1, §3.4). 판정 순서는 백엔드 claim_service와 같다.
 * - `_lookup`: 없는 Claim 404, 남의 Claim 403
 * - 쓰기 조건: Claim ACTIVE, Plan CLAIMED, `currentClaimId = claimId` (아니면 409 CLAIM_NOT_ACTIVE, G3)
 * - 완료: 이미 COMPLETED면 멱등 200, 기록 없으면 400 RECORD_REQUIRED, InboxItem 1건(G2, G4)
 * 4단계 목업은 글만 다룬다. 사진(`photo`, upload)은 5단계에서 추가한다.
 */
import { HttpResponse, http } from 'msw';

import type {
  ClaimResponse,
  ClaimStatus,
  CompleteResponse,
  ErrorCode,
  GetRecordResponse,
  MyClaimsResponse,
  PutRecordResponse,
  Record as VisitRecord,
} from '../../api/types';
import type { DbClaim, DbPlan, DbRecord, MockDb } from '../db';
import { iso, loadDb, updateDb } from '../db';
import { api, apiError, currentUser, unauthorized } from './common';
import { toClaim, toPlan } from './plans';

type Fail = { error: ErrorCode; details?: { [path: string]: string } };
type Result<T> = T | Fail;

const MESSAGES: Partial<{ [code in ErrorCode]: string }> = {
  NOT_FOUND: '찾을 수 없어요.',
  FORBIDDEN: '이 요청을 할 권한이 없어요.',
  CLAIM_NOT_ACTIVE: '이미 종료된 이어받기예요.',
  RECORD_REQUIRED: '방문 기록을 먼저 저장해 주세요.',
  VALIDATION_ERROR: '입력값을 확인해 주세요.',
};

export const isFail = (r: unknown): r is Fail => !!r && typeof r === 'object' && 'error' in r;

export function toRecord(r: DbRecord): VisitRecord {
  return {
    claimId: r.claimId,
    planId: r.planId,
    letter: r.letter,
    photoStatus: r.photoStatus,
    updatedAt: r.updatedAt,
    deliveredAt: r.deliveredAt,
  };
}

const findRecord = (db: MockDb, claimId: string) => db.records.find((r) => r.claimId === claimId);

/** 백엔드 `_lookup` */
export function lookupClaim(
  db: MockDb,
  claimId: string,
  userId: string,
): Result<{ claim: DbClaim; plan: DbPlan }> {
  const claim = db.claims.find((c) => c.claimId === claimId);
  if (!claim) return { error: 'NOT_FOUND' };
  if (claim.claimerId !== userId) return { error: 'FORBIDDEN' };
  const plan = db.plans.find((p) => p.planId === claim.planId);
  if (!plan) return { error: 'NOT_FOUND' };
  return { claim, plan };
}

const writable = (claim: DbClaim, plan: DbPlan) =>
  claim.status === 'ACTIVE' && plan.status === 'CLAIMED' && plan.currentClaimId === claim.claimId;

export function listMyClaims(db: MockDb, userId: string, status: string | null, nowIso: string) {
  if (status !== 'ACTIVE' && status !== 'COMPLETED') {
    return { error: 'VALIDATION_ERROR', details: { status: 'ACTIVE 또는 COMPLETED여야 해요.' } } as Fail;
  }
  const items = db.claims
    .filter((c) => c.claimerId === userId && c.status === (status as ClaimStatus))
    .sort((a, b) => (a.claimedAt < b.claimedAt ? 1 : -1))
    .flatMap((c) => {
      const plan = db.plans.find((p) => p.planId === c.planId);
      if (!plan) return [];
      const record = findRecord(db, c.claimId);
      return [
        { claim: toClaim(c), plan: toPlan(plan, userId, nowIso), record: record ? toRecord(record) : null },
      ];
    });
  const body: MyClaimsResponse = { items };
  return body;
}

export function abandonClaim(db: MockDb, claimId: string, userId: string): Result<ClaimResponse> {
  const found = lookupClaim(db, claimId, userId);
  if (isFail(found)) return found;
  const { claim, plan } = found;
  if (!writable(claim, plan)) return { error: 'CLAIM_NOT_ACTIVE' };
  claim.status = 'ABANDONED';
  plan.status = 'OPEN';
  delete plan.currentClaimId;
  delete plan.claimerId;
  delete plan.dueAt;
  const record = findRecord(db, claimId);
  if (record) record.photoStatus = 'DISCARDED';
  return { claim: toClaim(claim) };
}

export function putRecord(
  db: MockDb,
  claimId: string,
  userId: string,
  body: unknown,
  nowMs: number,
): Result<PutRecordResponse> {
  const found = lookupClaim(db, claimId, userId);
  if (isFail(found)) return found;
  const b = (body ?? {}) as { letter?: unknown; photo?: unknown };
  const details: { [path: string]: string } = {};
  if (typeof b.letter !== 'string' || [...b.letter].length < 1 || [...b.letter].length > 1000) {
    details.letter = '1–1000자로 입력해 주세요.';
  }
  if (b.photo !== undefined) details.photo = '목업은 5단계부터 사진을 받아요.';
  if (Object.keys(details).length) return { error: 'VALIDATION_ERROR', details };

  const { claim, plan } = found;
  if (!writable(claim, plan)) return { error: 'CLAIM_NOT_ACTIVE' };
  let record = findRecord(db, claimId);
  if (record?.deliveredAt) return { error: 'CLAIM_NOT_ACTIVE' };
  if (!record) {
    record = {
      claimId,
      planId: plan.planId,
      letter: '',
      photoStatus: 'NONE',
      updatedAt: iso(nowMs),
      deliveredAt: null,
    };
    db.records.push(record);
  }
  record.letter = b.letter as string;
  record.updatedAt = iso(nowMs);
  return { record: toRecord(record), upload: null };
}

export function getRecord(db: MockDb, claimId: string, userId: string): Result<GetRecordResponse> {
  const found = lookupClaim(db, claimId, userId);
  if (isFail(found)) return found;
  const record = findRecord(db, claimId);
  return {
    record: record ? toRecord(record) : null,
    claimStatus: found.claim.status,
    delivered: !!record?.deliveredAt,
    photoStatus: record?.photoStatus ?? 'NONE',
  };
}

export function completeClaim(
  db: MockDb,
  claimId: string,
  userId: string,
  body: unknown,
  nowMs: number,
): Result<CompleteResponse> {
  const found = lookupClaim(db, claimId, userId);
  if (isFail(found)) return found;
  if ((body as { mode?: unknown } | null)?.mode !== 'TEXT_ONLY') {
    return { error: 'VALIDATION_ERROR', details: { mode: 'TEXT_ONLY여야 해요.' } };
  }
  const { claim, plan } = found;
  const record = findRecord(db, claimId);
  if (claim.status === 'COMPLETED') {
    return { claim: toClaim(claim), delivered: true, hasPhoto: record?.photoStatus === 'READY' };
  }
  if (!writable(claim, plan)) return { error: 'CLAIM_NOT_ACTIVE' };
  if (!record || !record.letter) return { error: 'RECORD_REQUIRED' };

  const now = iso(nowMs);
  record.photoStatus = record.photoStatus === 'NONE' ? 'NONE' : 'DISCARDED';
  record.deliveredAt = now;
  plan.status = 'COMPLETED';
  plan.completedAt = now;
  claim.status = 'COMPLETED';
  claim.completedAt = now;
  claim.late = now > claim.dueAt;
  db.inbox.push({
    ownerId: plan.ownerId,
    itemId: claimId,
    planId: plan.planId,
    planTitle: plan.title,
    claimerNickname: claim.claimerNickname,
    hasPhoto: false,
    read: false,
    createdAt: now,
    reply: null,
  });
  return { claim: toClaim(claim), delivered: true, hasPhoto: false };
}

function respond<T>(result: Result<T>, status = 200) {
  if (isFail(result)) return apiError(result.error, MESSAGES[result.error] ?? '', undefined, result.details);
  return HttpResponse.json(result as object, { status });
}

async function readBody(request: Request): Promise<unknown> {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

const id = (params: { [k: string]: unknown }) => String(params.claimId);

export const claimHandlers = [
  http.get(api('/me/claims'), ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const status = new URL(request.url).searchParams.get('status');
    return respond(listMyClaims(loadDb(), user.userId, status, new Date().toISOString()));
  }),

  http.post(api('/claims/:claimId/abandon'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    return respond(updateDb((db) => abandonClaim(db, id(params), user.userId)));
  }),

  http.put(api('/claims/:claimId/record'), async ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const body = await readBody(request);
    return respond(updateDb((db) => putRecord(db, id(params), user.userId, body, Date.now())));
  }),

  http.get(api('/claims/:claimId/record'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    return respond(getRecord(loadDb(), id(params), user.userId));
  }),

  http.post(api('/claims/:claimId/complete'), async ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const body = await readBody(request);
    return respond(updateDb((db) => completeClaim(db, id(params), user.userId, body, Date.now())));
  }),
];
