import type { PhotoStatus } from '../api/types';
import { formatMonthDay } from './date';

/** 내 하루 기한 문구(FE-ME-02). 날짜는 KST */
export function dueText(dueAt: string, nowMs: number = Date.now()): string {
  if (Date.parse(dueAt) <= nowMs) return '기한이 지났어요. 다른 사람이 이어받기 전까지는 보낼 수 있어요.';
  return `${formatMonthDay(dueAt)}까지 다녀온 이야기를 보내주세요.`;
}

/**
 * "다녀온 이야기 쓰기" 이동 경로(FE-ME-03). 사진 처리 중·실패면 보내는 중(5-1, 실패는 같은 경로의 5-2),
 * 그 외(기록 없음, NONE, READY 미전달, DISCARDED)는 작성 화면(FE-Q22).
 */
export function recordPath(claimId: string, photoStatus: PhotoStatus | null | undefined): string {
  const id = encodeURIComponent(claimId);
  if (photoStatus === 'UPLOAD_PENDING' || photoStatus === 'PROCESSING' || photoStatus === 'FAILED') {
    return `/claims/${id}/sending`;
  }
  return `/claims/${id}/record`;
}
