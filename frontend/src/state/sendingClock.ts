/**
 * 보내는 중(5-1) 판정의 기준 시각과 브라우저 업로드 실패 여부(FE-Q23).
 * sessionStorage `haru.sending.{claimId}` = { startedAt, uploadFailed }. 탭을 닫으면 사라지고,
 * 그때는 화면이 `record.updatedAt`을 기준으로 쓴다.
 */
export interface SendingClock {
  startedAt: number;
  uploadFailed: boolean;
}

const key = (claimId: string) => `haru.sending.${claimId}`;

export function loadSending(claimId: string): SendingClock | null {
  try {
    const raw = sessionStorage.getItem(key(claimId));
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<SendingClock>;
    return typeof v.startedAt === 'number'
      ? { startedAt: v.startedAt, uploadFailed: !!v.uploadFailed }
      : null;
  } catch {
    return null;
  }
}

export function startSending(claimId: string, now: number = Date.now()): void {
  sessionStorage.setItem(key(claimId), JSON.stringify({ startedAt: now, uploadFailed: false }));
}

export function markUploadFailed(claimId: string): void {
  const v = loadSending(claimId) ?? { startedAt: Date.now(), uploadFailed: false };
  sessionStorage.setItem(key(claimId), JSON.stringify({ ...v, uploadFailed: true }));
}

export function clearSending(claimId: string): void {
  sessionStorage.removeItem(key(claimId));
}
