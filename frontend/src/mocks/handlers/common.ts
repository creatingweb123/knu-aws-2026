import { HttpResponse } from 'msw';

import type { ErrorCode } from '../../api/types';
import { mockUserFromAuthHeader } from '../session';

/** 목업 요청 경로. 앱의 `config.apiBaseUrl`과 무관하게 경로만 맞춘다 */
export const api = (path: string) => `*${path}`;

const STATUS: Partial<{ [code in ErrorCode]: number }> = {
  VALIDATION_ERROR: 400,
  RECORD_REQUIRED: 400,
  FORBIDDEN: 403,
  NOT_FOUND: 404,
  TRY_AGAIN: 503,
};

/** docs/03 에러 형식 */
export function apiError(
  code: ErrorCode,
  message: string,
  status: number = STATUS[code] ?? 409,
  details?: Record<string, string>,
) {
  return HttpResponse.json({ error: { code, message, ...(details ? { details } : {}) } }, { status });
}

/** API Gateway authorizer와 같은 401 본문(docs/03 §3.6) */
export function unauthorized() {
  return HttpResponse.json({ message: 'Unauthorized' }, { status: 401 });
}

export function currentUser(request: Request) {
  return mockUserFromAuthHeader(request.headers.get('Authorization'));
}
