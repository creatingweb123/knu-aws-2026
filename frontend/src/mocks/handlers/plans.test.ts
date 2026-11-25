import { describe, expect, it } from 'vitest';

import { setTokenProvider } from '../../auth/tokens';
import { request } from '../../api/client';
import type { Me, PlanDetailResponse, PlanListResponse } from '../../api/types';
import { DAY_MS, createSeed, iso, loadDb, saveDb } from '../db';
import { mockTokenFor } from '../session';
import { listOpenPlans, planDetail } from './plans';

const NOW = Date.parse('2026-11-20T03:00:00.000Z');
const nowIso = iso(NOW);
const as = (userId: string) => setTokenProvider(async () => mockTokenFor(userId));

describe('시드(FE-TECH-04, FE-Q15)', () => {
  it('지연·수현·민준과 데모 계획(출근길 빵집)을 가진다', () => {
    const db = createSeed(NOW);
    const demo = db.plans.find((p) => p.planId === 'pln_demo');
    expect(demo?.ownerNickname).toBe('지연');
    expect(demo?.places.map((p) => p.name)).toEqual(['출근길 빵집', '하천 산책로 벤치']);
    expect(db.claims.map((c) => c.claimerNickname).sort()).toEqual(['민준', '수현']);
  });

  it('시각은 밀리초 3자리 UTC다', () => {
    for (const p of createSeed(NOW).plans)
      expect(p.createdAt).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
  });

  it('localStorage에 저장되고 다시 읽힌다(탭 공유)', () => {
    const db = createSeed(NOW);
    db.plans[0].title = '바뀐 제목';
    saveDb(db);
    expect(loadDb().plans[0].title).toBe('바뀐 제목');
  });
});

describe('목록 규칙(docs/03 §3.3)', () => {
  it('OPEN과 기한 지난 CLAIMED를 최신순으로, 모두 OPEN으로 돌려준다', () => {
    const db = createSeed(NOW);
    expect(listOpenPlans(db, nowIso).map((p) => p.planId)).toEqual(['pln_demo', 'pln_library']);

    const market = db.plans.find((p) => p.planId === 'pln_market')!;
    market.dueAt = iso(NOW - DAY_MS);
    const ids = listOpenPlans(db, nowIso).map((p) => p.planId);
    expect(ids).toContain('pln_market');
    expect(listOpenPlans(db, nowIso).every((p) => p.status === 'OPEN')).toBe(true);
  });
});

describe('상세 분기 값(docs/03 §3.3)', () => {
  const db = createSeed(NOW);

  it('소유자: isOwner, claimable=false, metrics 포함', () => {
    const d = planDetail(db, 'pln_demo', 'u-jiyeon', nowIso)!;
    expect(d.isOwner).toBe(true);
    expect(d.claimable).toBe(false);
    expect(d.plan.metrics).toBeDefined();
  });

  it('다른 사용자: OPEN이면 claimable, metrics·currentClaimId 없음', () => {
    const d = planDetail(db, 'pln_demo', 'u-suhyun', nowIso)!;
    expect(d).toMatchObject({ isOwner: false, myClaim: null, claimable: true });
    expect(d.plan.metrics).toBeUndefined();
    expect('currentClaimId' in d.plan).toBe(false);
  });

  it('남이 기한 내 이어받은 계획: CLAIMED, claimable=false(2-1)', () => {
    const d = planDetail(db, 'pln_market', 'u-suhyun', nowIso)!;
    expect(d.plan.status).toBe('CLAIMED');
    expect(d.claimable).toBe(false);
    expect(d.myClaim).toBeNull();
  });

  it('현재 실행자: myClaim ACTIVE', () => {
    const d = planDetail(db, 'pln_market', 'u-minjun', nowIso)!;
    expect(d.myClaim?.status).toBe('ACTIVE');
    expect(d.claimable).toBe(false);
  });

  it('COMPLETED는 소유자·실행자만, 그 외는 404', () => {
    expect(planDetail(db, 'pln_bridge', 'u-jiyeon', nowIso)).not.toBeNull();
    expect(planDetail(db, 'pln_bridge', 'u-suhyun', nowIso)?.myClaim?.status).toBe('COMPLETED');
    expect(planDetail(db, 'pln_bridge', 'u-minjun', nowIso)).toBeNull();
  });

  it('기한 지난 CLAIMED는 다른 사용자에게 OPEN이고 claimable', () => {
    const late = createSeed(NOW);
    late.plans.find((p) => p.planId === 'pln_market')!.dueAt = iso(NOW - DAY_MS);
    const d = planDetail(late, 'pln_market', 'u-suhyun', nowIso)!;
    expect(d.plan.status).toBe('OPEN');
    expect(d.claimable).toBe(true);
    // 현재 실행자에게는 CLAIMED 그대로
    expect(planDetail(late, 'pln_market', 'u-minjun', nowIso)!.plan.status).toBe('CLAIMED');
  });
});

describe('핸들러(MSW, 계약 형태)', () => {
  it('GET /me: 지연은 안 읽은 편지 1건', async () => {
    as('u-jiyeon');
    const me = await request<Me>('/me');
    expect(me).toEqual({ userId: 'u-jiyeon', nickname: '지연', unreadInboxCount: 1 });
  });

  it('GET /plans?status=OPEN: items와 nextCursor null', async () => {
    as('u-suhyun');
    const res = await request<PlanListResponse>('/plans?status=OPEN');
    expect(res.nextCursor).toBeNull();
    expect(res.items.length).toBeGreaterThanOrEqual(2);
    expect(Object.keys(res.items[0]).sort()).toEqual(
      [
        'createdAt',
        'estimatedMinutes',
        'ownerNickname',
        'placeCount',
        'planId',
        'status',
        'summary',
        'title',
      ].sort(),
    );
  });

  it('GET /plans/{planId}: 없는 계획은 404 NOT_FOUND', async () => {
    as('u-suhyun');
    await expect(request<PlanDetailResponse>('/plans/pln_none')).rejects.toMatchObject({
      status: 404,
      code: 'NOT_FOUND',
    });
  });

  it('모르는 토큰은 401(API Gateway 본문)', async () => {
    setTokenProvider(async () => 'not-a-mock-token');
    await expect(request<Me>('/me')).rejects.toMatchObject({ status: 401, code: 'UNAUTHORIZED' });
  });
});
