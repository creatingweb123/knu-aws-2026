import type { PhotoStatus } from '../api/types';
import { formatMonthDay, kstDateKey } from './date';

/** 내 하루 기한 문구(FE-ME-02). 날짜는 KST */
export function dueText(dueAt: string, nowMs: number = Date.now()): string {
  if (Date.parse(dueAt) <= nowMs) return '기한이 지났어요. 다른 사람이 이어받기 전까지는 보낼 수 있어요.';
  return `${formatMonthDay(dueAt)}까지 다녀온 이야기를 보내주세요.`;
}

/**
 * 내 하루 카드의 남은 날 칩(docs/05 §5.2.4). KST 날짜 기준으로 센다.
 * 기한 당일은 "D-day", 기한이 지났으면 "기한 지남".
 */
export function dDayText(dueAt: string, nowMs: number = Date.now()): string {
  if (Date.parse(dueAt) <= nowMs) return '기한 지남';
  const dayMs = 24 * 60 * 60 * 1000;
  const due = Date.parse(`${kstDateKey(dueAt)}T00:00:00Z`);
  const today = Date.parse(`${kstDateKey(new Date(nowMs).toISOString())}T00:00:00Z`);
  const days = Math.round((due - today) / dayMs);
  return days <= 0 ? 'D-day' : `D-${days}`;
}

/**
 * 내 하루 카드의 진행 단계(docs/05 §5.2.4). 0 이어받음 → 1 다녀오기 → 2 경험 기록 보내기.
 * 서버에 저장된 기록(사진 처리 중 포함)이 있으면 마지막 단계로 본다.
 */
export function claimStep(photoStatus: PhotoStatus | null | undefined, hasRecord: boolean): 1 | 2 {
  if (photoStatus === 'UPLOAD_PENDING' || photoStatus === 'PROCESSING' || photoStatus === 'FAILED') return 2;
  return hasRecord ? 2 : 1;
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
