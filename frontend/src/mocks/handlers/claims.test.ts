import { describe, expect, it } from 'vitest';

import { request } from '../../api/client';
import type { CompleteResponse, MyClaimsResponse } from '../../api/types';
import { setTokenProvider } from '../../auth/tokens';
import { DAY_MS, createSeed, iso, resetDb } from '../db';
import { mockTokenFor } from '../session';
import { abandonClaim, completeClaim, getRecord, listMyClaims, putRecord } from './claims';
import { claimPlan } from './plans';

const NOW = Date.parse('2026-11-20T03:00:00.000Z');
const SUHYUN = { userId: 'u-suhyun', nickname: '수현' };

/** 수현이 pln_demo를 이어받은 DB와 claimId */
function claimed() {
  const db = createSeed(NOW);
  const out = claimPlan(db, 'pln_demo', SUHYUN, NOW);
  if (!('claim' in out)) throw new Error('claim 없음');
  return { db, claimId: out.claim.claimId };
}

describe('GET /me/claims', () => {
  it('요청자의 그 상태 Claim만, plan·record 포함', () => {
    const { db, claimId } = claimed();
    const active = listMyClaims(db, 'u-suhyun', 'ACTIVE', iso(NOW)) as MyClaimsResponse;
    expect(active.items.map((i) => i.claim.claimId)).toEqual([claimId]);
    expect(active.items[0].plan.planId).toBe('pln_demo');
    expect(active.items[0].record).toBeNull();
    const done = listMyClaims(db, 'u-suhyun', 'COMPLETED', iso(NOW)) as MyClaimsResponse;
    expect(done.items.map((i) => i.plan.planId)).toEqual(['pln_bridge']);
    expect(done.items[0].record?.deliveredAt).not.toBeNull();
  });

  it('status가 ACTIVE·COMPLETED가 아니면 VALIDATION_ERROR', () => {
    expect(listMyClaims(createSeed(NOW), 'u-suhyun', 'ABANDONED', iso(NOW))).toMatchObject({
      error: 'VALIDATION_ERROR',
    });
  });
});

describe('포기(G3)', () => {
  it('Claim ABANDONED, Plan OPEN, 다시 이어받을 수 있다', () => {
    const { db, claimId } = claimed();
    putRecord(db, claimId, 'u-suhyun', { letter: '쓰던 글' }, NOW);
    expect(abandonClaim(db, claimId, 'u-suhyun')).toMatchObject({ claim: { status: 'ABANDONED' } });
    const plan = db.plans.find((p) => p.planId === 'pln_demo')!;
    expect(plan.status).toBe('OPEN');
    expect(plan.currentClaimId).toBeUndefined();
    expect(db.records.find((r) => r.claimId === claimId)?.photoStatus).toBe('DISCARDED');
    expect(claimPlan(db, 'pln_demo', { userId: 'u-minjun', nickname: '민준' }, NOW)).toMatchObject({
      status: 201,
    });
  });

  it('포기 뒤 이전 Claim의 쓰기는 CLAIM_NOT_ACTIVE, 남의 Claim은 403, 없으면 404', () => {
    const { db, claimId } = claimed();
    abandonClaim(db, claimId, 'u-suhyun');
    expect(abandonClaim(db, claimId, 'u-suhyun')).toEqual({ error: 'CLAIM_NOT_ACTIVE' });
    expect(putRecord(db, claimId, 'u-suhyun', { letter: '늦은 글' }, NOW)).toEqual({
      error: 'CLAIM_NOT_ACTIVE',
    });
    expect(completeClaim(db, claimId, 'u-suhyun', { mode: 'TEXT_ONLY' }, NOW)).toEqual({
      error: 'CLAIM_NOT_ACTIVE',
    });
    expect(getRecord(db, claimId, 'u-suhyun')).toMatchObject({ claimStatus: 'ABANDONED', delivered: false });
    expect(abandonClaim(db, claimId, 'u-minjun')).toEqual({ error: 'FORBIDDEN' });
    expect(abandonClaim(db, 'clm_none', 'u-suhyun')).toEqual({ error: 'NOT_FOUND' });
  });
});

describe('기록·완료(G2, G4)', () => {
  it('기록 없이 완료하면 RECORD_REQUIRED', () => {
    const { db, claimId } = claimed();
    expect(completeClaim(db, claimId, 'u-suhyun', { mode: 'TEXT_ONLY' }, NOW)).toEqual({
      error: 'RECORD_REQUIRED',
    });
  });

  it('PUT /record는 덮어쓰고, 글 검증·사진은 400', () => {
    const { db, claimId } = claimed();
    putRecord(db, claimId, 'u-suhyun', { letter: '첫 글' }, NOW);
    const second = putRecord(db, claimId, 'u-suhyun', { letter: '고친 글' }, NOW + 1000);
    expect(second).toMatchObject({ record: { letter: '고친 글', photoStatus: 'NONE' }, upload: null });
    expect(db.records.filter((r) => r.claimId === claimId)).toHaveLength(1);
    expect(putRecord(db, claimId, 'u-suhyun', { letter: '' }, NOW)).toMatchObject({
      error: 'VALIDATION_ERROR',
      details: { letter: '1–1000자로 입력해 주세요.' },
    });
  });

  it('완료: Plan·Claim COMPLETED, 기록 전달, 수신함 1건. 다시 불러도 1건(멱등)', () => {
    const { db, claimId } = claimed();
    putRecord(db, claimId, 'u-suhyun', { letter: '소금빵을 샀어요' }, NOW);
    const first = completeClaim(
      db,
      claimId,
      'u-suhyun',
      { mode: 'TEXT_ONLY' },
      NOW + 1000,
    ) as CompleteResponse;
    expect(first).toMatchObject({
      delivered: true,
      hasPhoto: false,
      claim: { status: 'COMPLETED', late: false },
    });
    const again = completeClaim(db, claimId, 'u-suhyun', { mode: 'TEXT_ONLY' }, NOW + 5000);
    expect(again).toMatchObject({ delivered: true, hasPhoto: false });
    expect(db.plans.find((p) => p.planId === 'pln_demo')?.status).toBe('COMPLETED');
    const inbox = db.inbox.filter((i) => i.itemId === claimId);
    expect(inbox).toHaveLength(1);
    expect(inbox[0]).toMatchObject({
      ownerId: 'u-jiyeon',
      read: false,
      claimerNickname: '수현',
      hasPhoto: false,
    });
    expect(getRecord(db, claimId, 'u-suhyun')).toMatchObject({ delivered: true, claimStatus: 'COMPLETED' });
    expect(putRecord(db, claimId, 'u-suhyun', { letter: '완료 뒤' }, NOW)).toEqual({
      error: 'CLAIM_NOT_ACTIVE',
    });
  });

  it('기한이 지나 완료하면 late = true', () => {
    const { db, claimId } = claimed();
    putRecord(db, claimId, 'u-suhyun', { letter: '늦었어요' }, NOW);
    const out = completeClaim(
      db,
      claimId,
      'u-suhyun',
      { mode: 'TEXT_ONLY' },
      NOW + 4 * DAY_MS,
    ) as CompleteResponse;
    expect(out.claim.late).toBe(true);
  });

  it('mode는 TEXT_ONLY만', () => {
    const { db, claimId } = claimed();
    expect(completeClaim(db, claimId, 'u-suhyun', { mode: 'WITH_PHOTO' }, NOW)).toMatchObject({
      error: 'VALIDATION_ERROR',
    });
  });
});

describe('핸들러', () => {
  it('이어받기 → PUT /record → complete → GET /record (HTTP 상태 코드)', async () => {
    resetDb();
    setTokenProvider(async () => mockTokenFor('u-suhyun'));
    const { claim } = await request<{ claim: { claimId: string } }>('/plans/pln_demo/claims', {
      method: 'POST',
    });
    const path = `/claims/${claim.claimId}`;
    await expect(
      request(`${path}/complete`, { method: 'POST', body: { mode: 'TEXT_ONLY' } }),
    ).rejects.toMatchObject({
      status: 400,
      code: 'RECORD_REQUIRED',
    });
    await request(`${path}/record`, { method: 'PUT', body: { letter: '글' } });
    const done = await request<CompleteResponse>(`${path}/complete`, {
      method: 'POST',
      body: { mode: 'TEXT_ONLY' },
    });
    expect(done.delivered).toBe(true);
    setTokenProvider(async () => mockTokenFor('u-minjun'));
    await expect(request(`${path}/record`)).rejects.toMatchObject({ status: 403, code: 'FORBIDDEN' });
  });
});
