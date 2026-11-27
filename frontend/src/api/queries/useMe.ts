import { useQuery } from '@tanstack/react-query';

import { request } from '../client';
import type { Me } from '../types';

export const meKey = ['me'] as const;

export function useMe() {
  return useQuery({ queryKey: meKey, queryFn: () => request<Me>('/me') });
}
