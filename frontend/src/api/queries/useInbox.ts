import { useQuery } from '@tanstack/react-query';

import { request } from '../client';
import type { InboxDetailResponse, InboxListResponse } from '../types';

export const inboxKey = ['inbox'] as const;
export const inboxItemKey = (itemId: string) => ['inbox', itemId] as const;

export function useInbox() {
  return useQuery({ queryKey: inboxKey, queryFn: () => request<InboxListResponse>('/inbox') });
}

export function useInboxItem(itemId: string) {
  return useQuery({
    queryKey: inboxItemKey(itemId),
    queryFn: () => request<InboxDetailResponse>(`/inbox/${encodeURIComponent(itemId)}`),
  });
}
