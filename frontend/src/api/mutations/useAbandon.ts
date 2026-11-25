import { useMutation, useQueryClient } from '@tanstack/react-query';

import { request } from '../client';
import { meKey } from '../queries/useMe';
import { plansKey } from '../queries/usePlans';
import type { ClaimResponse } from '../types';

/** 이어받기 포기 `POST /claims/{claimId}/abandon` (FE-ME-04). 성공·실패 모두 내 하루와 목록을 다시 읽게 한다 */
export function useAbandon(claimId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: meKey });
    void queryClient.invalidateQueries({ queryKey: plansKey });
    void queryClient.invalidateQueries({ queryKey: ['plan'] });
  };
  return useMutation({
    mutationFn: () =>
      request<ClaimResponse>(`/claims/${encodeURIComponent(claimId)}/abandon`, { method: 'POST' }),
    onSettled: refresh,
  });
}
