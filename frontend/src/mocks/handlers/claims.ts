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
  ReplacePhotoResponse,
  UploadInstruction,
  Record as VisitRecord,
} from '../../api/types';
import type { DbClaim, DbPlan, DbRecord, MockDb } from '../db';
import { iso, updateDb } from '../db';
import {
  PHOTO_MAX_BYTES,
  UPLOAD_ORIGIN,
  advancePhotos,
  newPhotoKey,
  processDelay,
  uploadUrl,
} from '../photos';
import { getMockScenario } from '../session';
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
  const photo = b.photo === undefined ? null : validPhoto(b.photo);
  if (b.photo !== undefined && !photo) details.photo = PHOTO_MESSAGE;
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
  // 사진 없이 요청하면 진행 중이던 사진은 그대로 둔다(docs/03 §3.4)
  const upload = photo ? startPhoto(record, photo.contentType, nowMs) : null;
  return { record: toRecord(record), upload };
}

const PHOTO_MESSAGE = 'JPEG 또는 PNG, 10MB 이하 사진만 보낼 수 있어요.';

function validPhoto(raw: unknown): { contentType: string; size: number } | null {
  const p = raw as { contentType?: unknown; size?: unknown } | null;
  if (!p || (p.contentType !== 'image/jpeg' && p.contentType !== 'image/png')) return null;
  if (typeof p.size !== 'number' || !Number.isInteger(p.size) || p.size < 1 || p.size > PHOTO_MAX_BYTES)
    return null;
  return { contentType: p.contentType, size: p.size };
}

/** 새 사진 키로 바꾸고 UPLOAD_PENDING. 이전 키에서 오는 처리 결과는 무시된다 */
function startPhoto(record: DbRecord, contentType: string, nowMs: number): UploadInstruction {
  record.photoKey = newPhotoKey(record.claimId, contentType);
  record.photoContentType = contentType;
  record.photoStatus = 'UPLOAD_PENDING';
  delete record.processReadyAt;
  delete record.photoOutcome;
  return {
    url: uploadUrl(record.photoKey),
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    expiresAt: iso(nowMs + 10 * 60 * 1000),
  };
}

/** POST /claims/{claimId}/record/photo — 사진 교체 */
export function replacePhoto(
  db: MockDb,
  claimId: string,
  userId: string,
  body: unknown,
  nowMs: number,
): Result<ReplacePhotoResponse> {
  const found = lookupClaim(db, claimId, userId);
  if (isFail(found)) return found;
  const photo = validPhoto(body);
  if (!photo) return { error: 'VALIDATION_ERROR', details: { photo: PHOTO_MESSAGE } };
  if (!writable(found.claim, found.plan)) return { error: 'CLAIM_NOT_ACTIVE' };
  const record = findRecord(db, claimId);
  if (!record) return { error: 'RECORD_REQUIRED' };
  if (record.deliveredAt) return { error: 'CLAIM_NOT_ACTIVE' };
  return { upload: startPhoto(record, photo.contentType, nowMs) };
}

/**
 * 업로드 PUT을 받는다. 현재 키이고 UPLOAD_PENDING일 때만 PROCESSING으로 바꾼다.
 * 교체 전 키·이미 처리 중인 키는 무시한다. Content-Type이 서명과 다르면 S3처럼 403.
 */
export function receiveUpload(
  db: MockDb,
  photoKey: string,
  contentType: string | null,
  scenario: string | null,
  nowMs: number,
): 'ok' | 'ignored' | 'forbidden' {
  const record = db.records.find((r) => r.photoKey === photoKey);
  if (!record) return 'ignored';
  if (contentType !== record.photoContentType) return 'forbidden';
  if (record.photoStatus !== 'UPLOAD_PENDING' || record.deliveredAt) return 'ignored';
  record.photoStatus = 'PROCESSING';
  record.processReadyAt = iso(nowMs + processDelay(scenario));
  record.photoOutcome = scenario === 'photo-fail' ? 'FAILED' : 'READY';
  return 'ok';
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
  // 진행 중이거나 처리 끝났지만 미전달인 사진은 폐기한다(docs/03 §3.4)
  record.photoStatus = record.photoStatus === 'NONE' ? 'NONE' : 'DISCARDED';
  delete record.processReadyAt;
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

/** 사진 처리 결과를 먼저 반영하고 읽거나 쓴다(FE-Q24). 핸들러의 DB 접근은 모두 이 함수를 거친다 */
export function withDb<T>(fn: (db: MockDb, nowMs: number) => T): T {
  return updateDb((db) => {
    const now = Date.now();
    advancePhotos(db, now);
    return fn(db, now);
  });
}

export const claimHandlers = [
  http.get(api('/me/claims'), ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const status = new URL(request.url).searchParams.get('status');
    return respond(withDb((db, now) => listMyClaims(db, user.userId, status, iso(now))));
  }),

  http.post(api('/claims/:claimId/abandon'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    return respond(withDb((db) => abandonClaim(db, id(params), user.userId)));
  }),

  http.put(api('/claims/:claimId/record'), async ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const body = await readBody(request);
    return respond(withDb((db, now) => putRecord(db, id(params), user.userId, body, now)));
  }),

  http.post(api('/claims/:claimId/record/photo'), async ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const body = await readBody(request);
    return respond(withDb((db, now) => replacePhoto(db, id(params), user.userId, body, now)));
  }),

  http.get(api('/claims/:claimId/record'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    return respond(withDb((db) => getRecord(db, id(params), user.userId)));
  }),

  http.post(api('/claims/:claimId/complete'), async ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const body = await readBody(request);
    return respond(withDb((db, now) => completeClaim(db, id(params), user.userId, body, now)));
  }),

  // presigned PUT 대신(인증 헤더 없음). 키는 URL 경로에서 읽는다
  http.put(`${UPLOAD_ORIGIN}/*`, ({ request }) => {
    const scenario = getMockScenario();
    if (scenario === 'photo-upload-fail') return new HttpResponse(null, { status: 500 });
    const photoKey = decodeURIComponent(new URL(request.url).pathname.replace(/^\//, ''));
    const result = withDb((db, now) =>
      receiveUpload(db, photoKey, request.headers.get('Content-Type'), scenario, now),
    );
    return new HttpResponse(null, { status: result === 'forbidden' ? 403 : 200 });
  }),
];
