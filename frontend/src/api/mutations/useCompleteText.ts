import { useMutation, useQueryClient } from '@tanstack/react-query';

import { isApiError, request } from '../client';
import { meKey } from '../queries/useMe';
import { recordKey } from '../queries/useRecord';
import type { CompleteResponse, PutRecordResponse } from '../types';

function putRecord(claimId: string, letter: string) {
  return request<PutRecordResponse>(`/claims/${encodeURIComponent(claimId)}/record`, {
    method: 'PUT',
    body: { letter },
  });
}

function complete(claimId: string) {
  return request<CompleteResponse>(`/claims/${encodeURIComponent(claimId)}/complete`, {
    method: 'POST',
    body: { mode: 'TEXT_ONLY' },
  });
}

/**
 * 글로 완료(FE-REC-05): 항상 `PUT /record { letter }`로 현재 글을 먼저 저장하고 `complete(TEXT_ONLY)`.
 * - 400 RECORD_REQUIRED → `PUT /record` 후 `complete` 1회 재시도
 * - 네트워크 오류 → `complete` 1회 재시도(서버 멱등). 503 TRY_AGAIN 1회 재시도는 Client가 한다
 */
export async function completeWithText(claimId: string, letter: string): Promise<CompleteResponse> {
  await putRecord(claimId, letter);
  try {
    return await complete(claimId);
  } catch (e) {
    if (isApiError(e) && e.code === 'RECORD_REQUIRED') {
      await putRecord(claimId, letter);
      return complete(claimId);
    }
    if (!isApiError(e)) return complete(claimId);
    throw e;
  }
}

export function useCompleteText(claimId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (letter: string) => completeWithText(claimId, letter),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: meKey });
      void queryClient.invalidateQueries({ queryKey: recordKey(claimId) });
      void queryClient.invalidateQueries({ queryKey: ['plan'] });
    },
  });
}
