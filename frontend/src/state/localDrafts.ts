/**
 * 이 기기에만 저장된, 아직 서버에 보내지 않은 글(docs/05 §5.2.4 로그아웃).
 * - 하루 남기기 작성 상태: sessionStorage `haru.planDraft`(사연이 비어 있지 않을 때만 '글'로 본다)
 * - 경험 기록 임시 글: localStorage `haru.letterDraft.{claimId}`
 * - 보내는 중 기준 시각: sessionStorage `haru.sending.{claimId}`(글은 아니지만 사용자 상태라 함께 지운다)
 * 로그아웃할 때 지워서 공용 기기의 다음 사람이 앞사람의 글을 보지 않게 한다.
 * 목업 데이터(`haru.mock.db`)는 사용자 상태가 아니라서 건드리지 않는다.
 */
import { LETTER_PREFIX } from './letterDraft';
import { clearDraft, loadDraft } from './planDraft';
import { SENDING_PREFIX } from './sendingClock';

function keysWithPrefix(storage: Storage, prefix: string): string[] {
  const keys: string[] = [];
  for (let i = 0; i < storage.length; i += 1) {
    const k = storage.key(i);
    if (k && k.startsWith(prefix)) keys.push(k);
  }
  return keys;
}

/** 보내지 않은 글이 있으면 true(로그아웃 확인 시트의 경고 여부) */
export function hasLocalDrafts(): boolean {
  try {
    if (loadDraft()?.story.trim()) return true;
    return keysWithPrefix(localStorage, LETTER_PREFIX).some((k) => (localStorage.getItem(k) ?? '').trim());
  } catch {
    return false;
  }
}

/** 이 기기의 작성 중 상태를 모두 지운다 */
export function clearLocalDrafts(): void {
  try {
    clearDraft();
    keysWithPrefix(localStorage, LETTER_PREFIX).forEach((k) => localStorage.removeItem(k));
    keysWithPrefix(sessionStorage, SENDING_PREFIX).forEach((k) => sessionStorage.removeItem(k));
  } catch {
    // 저장소를 쓸 수 없으면 지울 것도 없다
  }
}
