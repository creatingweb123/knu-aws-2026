/**
 * 경험 기록 임시 글(FE-REC-02, docs/02 §2.10). localStorage `haru.letterDraft.{claimId}`.
 * 입력할 때마다 저장하고, 전송 완료·종료 안내·포기 때 지운다. 서버에 저장된 글이 있으면 그쪽이 먼저다.
 */
export const LETTER_PREFIX = 'haru.letterDraft.';
const key = (claimId: string) => `${LETTER_PREFIX}${claimId}`;

export function loadLetter(claimId: string): string | null {
  try {
    return localStorage.getItem(key(claimId));
  } catch {
    return null;
  }
}

export function saveLetter(claimId: string, letter: string): void {
  try {
    localStorage.setItem(key(claimId), letter);
  } catch {
    // 저장 공간이 없으면 임시 글만 잃는다. 서버 저장(PUT /record)은 그대로다
  }
}

export function clearLetter(claimId: string): void {
  try {
    localStorage.removeItem(key(claimId));
  } catch {
    // 무시
  }
}
