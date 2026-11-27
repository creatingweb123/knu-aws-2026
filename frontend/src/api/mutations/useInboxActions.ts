import { useMutation, useQueryClient } from '@tanstack/react-query';

import { request } from '../client';
import { inboxKey } from '../queries/useInbox';
import { meKey } from '../queries/useMe';
import type { ReplyResponse } from '../types';

/** 읽음 처리(FE-INB-02). 수신함 목록과 헤더 점(`GET /me`)을 다시 읽게 한다 */
export function useMarkRead(itemId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => request<void>(`/inbox/${encodeURIComponent(itemId)}/read`, { method: 'POST' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: inboxKey, exact: true });
      void queryClient.invalidateQueries({ queryKey: meKey, exact: true });
    },
  });
}

/** 한 줄 답장(FE-INB-05). 409 REPLY_ALREADY_SENT 분기는 화면이 한다 */
export function useReply(itemId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      request<ReplyResponse>(`/inbox/${encodeURIComponent(itemId)}/reply`, {
        method: 'POST',
        body: { text },
      }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: inboxKey });
    },
  });
}
