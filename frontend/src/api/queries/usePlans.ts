import { useQuery } from '@tanstack/react-query';

import { request } from '../client';
import type { PlanDetailResponse, PlanListResponse } from '../types';

export const plansKey = ['plans', 'OPEN'] as const;
export const planKey = (planId: string) => ['plan', planId] as const;

/** 첫 페이지만 표시한다(FE-Q1) */
export function usePlans() {
  return useQuery({ queryKey: plansKey, queryFn: () => request<PlanListResponse>('/plans?status=OPEN') });
}

export function usePlan(planId: string) {
  return useQuery({
    queryKey: planKey(planId),
    queryFn: () => request<PlanDetailResponse>(`/plans/${encodeURIComponent(planId)}`),
  });
}
