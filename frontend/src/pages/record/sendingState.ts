/**
 * 보내는 중(5-1) 폴링 응답 판정(FE-REC-06, 07, docs/05 §5.2.5, docs/02 §2.10 `decideSendingState`).
 * 위에서부터 먼저 맞는 하나:
 * 1. delivered → 완료(사진 문구는 photoStatus === 'READY')
 * 2. claimStatus ABANDONED·EXPIRED, 또는 403·404·409 → 종료(화면 8)
 * 3. FAILED, 브라우저 업로드 실패, UPLOAD_PENDING 30초 초과, 보낼 사진 없음(NONE·DISCARDED, FE-Q23) → 실패(5-2)
 * 4. 그 외 → 대기. 60초가 지나면 "글로 완료하기" 강조. 데이터 없이 네트워크 오류 등이면 대기를 유지한다
 */
import { isApiError } from '../../api/client';
import type { GetRecordResponse } from '../../api/types';

export const UPLOAD_PENDING_LIMIT_MS = 30_000;
export const EMPHASIZE_AFTER_MS = 60_000;

export type SendingState =
  | { kind: 'done'; hasPhoto: boolean }
  | { kind: 'ended' }
  | { kind: 'failed' }
  | { kind: 'waiting'; emphasize: boolean };

export function decideSendingState(
  input: { data?: GetRecordResponse; error?: unknown },
  elapsedMs: number,
  uploadFailed = false,
): SendingState {
  const { data, error } = input;
  if (data?.delivered) return { kind: 'done', hasPhoto: data.photoStatus === 'READY' };
  if (data && (data.claimStatus === 'ABANDONED' || data.claimStatus === 'EXPIRED')) return { kind: 'ended' };
  if (isApiError(error) && [403, 404, 409].includes(error.status)) return { kind: 'ended' };
  if (data) {
    const s = data.photoStatus;
    if (s === 'FAILED' || uploadFailed || s === 'NONE' || s === 'DISCARDED') return { kind: 'failed' };
    if (s === 'UPLOAD_PENDING' && elapsedMs > UPLOAD_PENDING_LIMIT_MS) return { kind: 'failed' };
  } else if (uploadFailed) {
    return { kind: 'failed' };
  }
  return { kind: 'waiting', emphasize: elapsedMs >= EMPHASIZE_AFTER_MS };
}
