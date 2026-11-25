import { useMutation, useQueryClient } from '@tanstack/react-query';

import { request } from '../client';
import type { ClaimResponse } from '../types';
import { meKey } from '../queries/useMe';
import { planKey, plansKey } from '../queries/usePlans';

/**
 * 이어받기 `POST /plans/{planId}/claims` (FE-PLN-03). 201(새 Claim)과 200(본인의 기존 Claim)은 같게 다룬다.
 * 성공하면 목록·상세·`['me']` 접두 키(내 정보, 4단계의 내 하루 `['me', 'claims', …]`)를 무효화한다.
 * 실패 분기(ALREADY_CLAIMED 등)는 화면이 `error.code`로 한다.
 */
export function useClaim(planId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<ClaimResponse>(`/plans/${encodeURIComponent(planId)}/claims`, { method: 'POST' }),
    // 무효화를 기다리지 않는다. 기다리면 현재 상세를 다시 읽는 동안 화면 이동이 늦어진다
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: plansKey });
      void queryClient.invalidateQueries({ queryKey: planKey(planId) });
      void queryClient.invalidateQueries({ queryKey: meKey });
    },
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: plansKey });
      void queryClient.invalidateQueries({ queryKey: planKey(planId) });
    },
  });
}
