import type { PlanDetailResponse } from '../../api/types';

/** 하루 상세 분기(FE-PLN-02, docs/05 §5.2.2) */
export type DetailView = 'notFound' | 'myClaim' | 'owner' | 'claimable' | 'claimed' | 'completed' | 'other';

export interface DetailViewOptions {
  /** `GET /plans/{planId}`가 404 NOT_FOUND */
  notFound: boolean;
  /** 이어받기 요청이 409 ALREADY_CLAIMED를 받았다(FE-PLN-04) */
  conflict: boolean;
}

/**
 * 위에서부터 먼저 맞는 하나만 고른다.
 * `conflict`는 `claimable`·`other`만 `claimed`로 바꾼다. 다시 읽은 상세가 다른 상태를 말하면 서버 상태를 따른다.
 */
export function decideDetailView(
  detail: PlanDetailResponse | null | undefined,
  { notFound, conflict }: DetailViewOptions,
): DetailView {
  if (notFound || !detail) return 'notFound';
  const view = baseView(detail);
  if (conflict && (view === 'claimable' || view === 'other')) return 'claimed';
  return view;
}

function baseView({ plan, isOwner, myClaim, claimable }: PlanDetailResponse): DetailView {
  if (myClaim?.status === 'ACTIVE') return 'myClaim';
  if (isOwner) return 'owner';
  if (claimable) return 'claimable';
  if (plan.status === 'CLAIMED') return 'claimed';
  if (plan.status === 'COMPLETED') return 'completed';
  return 'other';
}
