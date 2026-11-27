import { describe, expect, it } from 'vitest';

import type { Claim, PlanDetailResponse, PlanStatus } from '../../api/types';
import { decideDetailView } from './detailView';

const claim = (status: Claim['status']): Claim => ({
  claimId: 'clm_1',
  planId: 'pln_1',
  claimer: { userId: 'u-suhyun', nickname: '수현' },
  status,
  claimedAt: '2026-11-20T03:00:00.000Z',
  dueAt: '2026-11-23T03:00:00.000Z',
  completedAt: null,
  late: false,
});

function detail(
  status: PlanStatus,
  over: Partial<Omit<PlanDetailResponse, 'plan'>> = {},
): PlanDetailResponse {
  return {
    plan: {
      planId: 'pln_1',
      areaId: 'default',
      owner: { userId: 'u-jiyeon', nickname: '지연' },
      title: 't',
      summary: 's',
      reason: 'r',
      estimatedMinutes: 30,
      places: [],
      question: 'q',
      status,
      createdAt: '2026-11-20T03:00:00.000Z',
      completedAt: null,
    },
    isOwner: false,
    myClaim: null,
    claimable: false,
    ...over,
  };
}

const plain = { notFound: false, conflict: false };

describe('decideDetailView(FE-PLN-02, 위에서부터 먼저 맞는 하나)', () => {
  it('1. 404 → notFound', () => {
    expect(decideDetailView(undefined, { notFound: true, conflict: false })).toBe('notFound');
  });

  it('2. myClaim ACTIVE → myClaim (기한 지난 CLAIMED도 본인에게는 CLAIMED)', () => {
    expect(decideDetailView(detail('CLAIMED', { myClaim: claim('ACTIVE') }), plain)).toBe('myClaim');
  });

  it('3. isOwner → owner (상태와 무관)', () => {
    for (const s of ['OPEN', 'CLAIMED', 'COMPLETED'] as const)
      expect(decideDetailView(detail(s, { isOwner: true }), plain)).toBe('owner');
  });

  it('4. claimable → claimable', () => {
    expect(decideDetailView(detail('OPEN', { claimable: true }), plain)).toBe('claimable');
  });

  it('5. 남의 CLAIMED → claimed(2-1)', () => {
    expect(decideDetailView(detail('CLAIMED'), plain)).toBe('claimed');
  });

  it('6. COMPLETED(내가 완료한 하루) → completed', () => {
    expect(decideDetailView(detail('COMPLETED', { myClaim: claim('COMPLETED') }), plain)).toBe('completed');
  });

  it('7. 그 외 → other (예: OPEN인데 claimable이 아님)', () => {
    expect(decideDetailView(detail('OPEN'), plain)).toBe('other');
  });

  it('ALREADY_CLAIMED를 받으면 claimable·other를 claimed로 바꾼다(FE-PLN-04)', () => {
    const c = { notFound: false, conflict: true };
    expect(decideDetailView(detail('OPEN', { claimable: true }), c)).toBe('claimed');
    expect(decideDetailView(detail('OPEN'), c)).toBe('claimed');
  });

  it('conflict여도 다시 읽은 상세가 내 이어받기·소유자를 말하면 서버 상태를 따른다', () => {
    const c = { notFound: false, conflict: true };
    expect(decideDetailView(detail('CLAIMED', { myClaim: claim('ACTIVE') }), c)).toBe('myClaim');
    expect(decideDetailView(detail('OPEN', { isOwner: true }), c)).toBe('owner');
  });
});
