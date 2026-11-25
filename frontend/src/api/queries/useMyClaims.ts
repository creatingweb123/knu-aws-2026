import { useQuery } from '@tanstack/react-query';

import { request } from '../client';
import type { MyClaimsResponse } from '../types';

/** `['me']` 접두라 `meKey` 무효화에 함께 걸린다 */
export const myClaimsKey = (status: 'ACTIVE' | 'COMPLETED') => ['me', 'claims', status] as const;

export function useMyClaims(status: 'ACTIVE' | 'COMPLETED' = 'ACTIVE') {
  return useQuery({
    queryKey: myClaimsKey(status),
    queryFn: () => request<MyClaimsResponse>(`/me/claims?status=${status}`),
  });
}
