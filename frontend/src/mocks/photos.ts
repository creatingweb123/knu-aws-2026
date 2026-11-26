/**
 * 사진 경로 목업(FE-Q24). 실제로는 S3 → SQS → 사진 처리 Lambda가 하는 일을 시각으로 계산한다.
 * - 업로드 URL: `https://mock-upload.haru.local/{photoKey}` (MSW가 PUT을 받는다)
 * - 업로드가 끝나면 PROCESSING, `processReadyAt`이 지나면 다음 조회·쓰기 때 결과를 반영한다
 * - `?mock=photo-fail` → FAILED, `?mock=photo-slow` → 90초, 기본 3초
 * 결과 반영은 사진 처리 Lambda처럼 키가 같고 미전달일 때만 하고, Claim이 쓰기 불가면 무시한다(docs/02 §2.7).
 */
import type { DbRecord, MockDb } from './db';
import { iso } from './db';

export const UPLOAD_ORIGIN = 'https://mock-upload.haru.local';
export const PHOTO_MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_PROCESS_MS = 3000;
const SLOW_PROCESS_MS = 90_000;

let processMs = DEFAULT_PROCESS_MS;

/** 테스트용: 처리 지연을 바꾼다(0이면 업로드 직후 첫 조회에서 끝난다) */
export function setPhotoProcessMs(ms: number | null): void {
  processMs = ms ?? DEFAULT_PROCESS_MS;
}

export function processDelay(scenario: string | null): number {
  return scenario === 'photo-slow' ? Math.max(processMs, SLOW_PROCESS_MS) : processMs;
}

/** 돌아온 하루의 고정 그림(presigned GET 대신) */
export const MOCK_PHOTO_URL =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">' +
      '<rect width="800" height="600" fill="#e4ede5"/>' +
      '<rect y="380" width="800" height="220" fill="#9fbfa8"/>' +
      '<circle cx="600" cy="170" r="70" fill="#f0b86e"/>' +
      '<rect x="160" y="330" width="220" height="24" rx="6" fill="#234d3a"/>' +
      '</svg>',
  );

export function newPhotoKey(claimId: string, contentType: string): string {
  const ext = contentType === 'image/png' ? 'png' : 'jpg';
  return `photos/original/${claimId}/${crypto.randomUUID()}.${ext}`;
}

export const uploadUrl = (photoKey: string) => `${UPLOAD_ORIGIN}/${photoKey}`;

/** 처리가 끝난 기록을 반영한다. 반영할 것이 있으면 true */
export function advancePhotos(db: MockDb, nowMs: number): boolean {
  let changed = false;
  for (const record of db.records) {
    if (record.photoStatus !== 'PROCESSING' || record.deliveredAt || !record.processReadyAt) continue;
    if (Date.parse(record.processReadyAt) > nowMs) continue;
    finishProcessing(db, record, nowMs);
    changed = true;
  }
  return changed;
}

function finishProcessing(db: MockDb, record: DbRecord, nowMs: number): void {
  delete record.processReadyAt;
  if (record.photoOutcome === 'FAILED') {
    record.photoStatus = 'FAILED';
    return;
  }
  const claim = db.claims.find((c) => c.claimId === record.claimId);
  const plan = db.plans.find((p) => p.planId === record.planId);
  if (
    !claim ||
    !plan ||
    claim.status !== 'ACTIVE' ||
    plan.status !== 'CLAIMED' ||
    plan.currentClaimId !== claim.claimId
  ) {
    return; // 사진 처리 Lambda의 WITH_PHOTO 완료가 CLAIM_NOT_ACTIVE로 거부되는 경우와 같다
  }
  const now = iso(nowMs);
  record.photoStatus = 'READY';
  record.deliveredAt = now;
  plan.status = 'COMPLETED';
  plan.completedAt = now;
  claim.status = 'COMPLETED';
  claim.completedAt = now;
  claim.late = now > claim.dueAt;
  db.inbox.push({
    ownerId: plan.ownerId,
    itemId: claim.claimId,
    planId: plan.planId,
    planTitle: plan.title,
    claimerNickname: claim.claimerNickname,
    hasPhoto: true,
    read: false,
    createdAt: now,
    reply: null,
  });
}
