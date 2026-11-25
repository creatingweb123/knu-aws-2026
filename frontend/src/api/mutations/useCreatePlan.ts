import { useMutation, useQueryClient } from '@tanstack/react-query';

import { newUuid } from '../../utils/uuid';
import { isApiError, request } from '../client';
import { plansKey } from '../queries/usePlans';
import type { CreatePlanRequest, CreatePlanResponse } from '../types';

export interface CreatePlanVars {
  body: CreatePlanRequest;
  key: string;
}

function post({ body, key }: CreatePlanVars) {
  return request<CreatePlanResponse>('/plans', {
    method: 'POST',
    body,
    headers: { 'Idempotency-Key': key },
  });
}

/**
 * 하루 공개 `POST /plans` (FE-CRT-10). 409 IDEMPOTENCY_CONFLICT면 새 키로 같은 본문을 한 번 다시 보낸다.
 * 키를 언제 재사용할지는 화면(publish.ts)이 정한다. 성공하면 둘러보기 목록을 무효화한다.
 */
export function useCreatePlan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: CreatePlanVars) => {
      try {
        return await post(vars);
      } catch (e) {
        if (isApiError(e) && e.code === 'IDEMPOTENCY_CONFLICT') return post({ ...vars, key: newUuid() });
        throw e;
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: plansKey });
    },
  });
}
