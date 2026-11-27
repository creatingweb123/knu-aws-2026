/**
 * 에러 코드별 공통 안내 문구와 VALIDATION_ERROR `details` 매핑(FE-COM-04, docs/03 §3.7).
 * 화면별 분기(ALREADY_CLAIMED → 2-1 등)는 각 화면이 `error.code`로 한다.
 */
import { isApiError } from './client';
import type { ErrorCode } from './types';

const MESSAGES: Partial<{ [code in ErrorCode]: string }> = {
  NOT_FOUND: '찾을 수 없어요.',
  FORBIDDEN: '볼 수 있는 권한이 없어요.',
  TRY_AGAIN: '잠시 후 다시 시도해 주세요.',
  INTERNAL_ERROR: '문제가 생겼어요. 잠시 후 다시 시도해 주세요.',
  ALREADY_CLAIMED: '이미 다른 사람이 이어받았어요.',
  CANNOT_CLAIM_OWN_PLAN: '내가 남긴 하루는 이어받을 수 없어요.',
  CLAIM_NOT_ACTIVE: '이 이어받기는 종료되었어요.',
  REPLY_ALREADY_SENT: '이미 답장을 보냈어요.',
};

const FALLBACK = '문제가 생겼어요. 잠시 후 다시 시도해 주세요.';

/** 토스트 등에 쓸 문구. 서버 `message`보다 화면 문구를 우선한다 */
export function errorMessage(e: unknown): string {
  if (isApiError(e)) return MESSAGES[e.code] ?? (e.message && e.message !== e.code ? e.message : FALLBACK);
  return FALLBACK;
}

/**
 * `details`를 입력칸별 메시지로 돌려준다. 키는 요청 본문 경로(`places[0].name`, `flags[].path`와 같은 표기).
 * `prefix`를 주면 그 아래 경로만 상대 경로로 돌려준다(예: `places[0]` → `{ name: … }`).
 */
export function fieldErrors(e: unknown, prefix?: string): { [path: string]: string } {
  if (!isApiError(e) || e.code !== 'VALIDATION_ERROR' || !e.details) return {};
  const out: { [path: string]: string } = {};
  for (const [path, message] of Object.entries(e.details)) {
    if (!prefix) out[path] = message;
    else if (path.startsWith(`${prefix}.`)) out[path.slice(prefix.length + 1)] = message;
  }
  return out;
}
