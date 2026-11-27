import { useQuery } from '@tanstack/react-query';

import { isApiError, request } from '../client';
import type { GetRecordResponse } from '../types';

export const recordKey = (claimId: string) => ['record', claimId] as const;

/** 방문 기록·`claimStatus`·사진 상태 */
export function useRecord(
  claimId: string,
  options: { enabled?: boolean; refetchInterval?: number | false } = {},
) {
  return useQuery({
    queryKey: recordKey(claimId),
    queryFn: () => request<GetRecordResponse>(`/claims/${encodeURIComponent(claimId)}/record`),
    staleTime: 0,
    enabled: options.enabled ?? true,
    // 보내는 중(5-1)은 2초 간격 폴링(FE-REC-06). 4xx면 판정이 끝나므로 멈춘다
    refetchInterval: (query) => {
      const err = query.state.error;
      if (isApiError(err) && err.status >= 400 && err.status < 500) return false;
      return options.refetchInterval ?? false;
    },
    refetchIntervalInBackground: false,
  });
}
