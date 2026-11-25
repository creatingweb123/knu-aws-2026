import { useQuery } from '@tanstack/react-query';

import { request } from '../client';
import type { GetRecordResponse } from '../types';

export const recordKey = (claimId: string) => ['record', claimId] as const;

/** 방문 기록·`claimStatus`·사진 상태. 보내는 중(5-1)의 폴링은 5단계에서 추가한다 */
export function useRecord(claimId: string, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: recordKey(claimId),
    queryFn: () => request<GetRecordResponse>(`/claims/${encodeURIComponent(claimId)}/record`),
    staleTime: 0,
    enabled: options.enabled ?? true,
  });
}
