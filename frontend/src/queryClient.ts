import { QueryClient } from '@tanstack/react-query';

import { isApiError } from './api/client';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        refetchOnWindowFocus: false,
        // 4xx는 다시 시도해도 결과가 같다. TRY_AGAIN은 Client가 이미 1회 재시도한다
        retry: (count, e) => !(isApiError(e) && e.status < 500) && count < 1,
      },
    },
  });
}
