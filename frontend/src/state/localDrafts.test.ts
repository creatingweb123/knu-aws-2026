import { describe, expect, it } from 'vitest';

import { saveLetter } from './letterDraft';
import { clearLocalDrafts, hasLocalDrafts } from './localDrafts';
import { DRAFT_KEY, newDraft, saveDraft } from './planDraft';
import { startSending } from './sendingClock';

describe('이 기기의 보내지 않은 글(로그아웃, docs/05 §5.2.4)', () => {
  it('아무것도 없으면 false', () => {
    expect(hasLocalDrafts()).toBe(false);
  });

  it('사연이 빈 작성 상태는 글로 보지 않는다', () => {
    saveDraft(newDraft(0));
    expect(hasLocalDrafts()).toBe(false);
  });

  it('사연이 있는 작성 상태나 경험 기록 임시 글이 있으면 true', () => {
    saveDraft({ ...newDraft(0), story: '동네 서점에 가려 했어요' });
    expect(hasLocalDrafts()).toBe(true);
    sessionStorage.clear();
    saveLetter('c1', '귤 상자');
    expect(hasLocalDrafts()).toBe(true);
  });

  it('지우면 작성 상태·임시 글·보내는 중 시각이 모두 사라지고 다른 키는 남는다', () => {
    saveDraft({ ...newDraft(0), story: '사연' });
    saveLetter('c1', '글');
    startSending('c1', 1);
    localStorage.setItem('haru.mock.db', '{}');
    clearLocalDrafts();
    expect(sessionStorage.getItem(DRAFT_KEY)).toBeNull();
    expect(localStorage.getItem('haru.letterDraft.c1')).toBeNull();
    expect(sessionStorage.getItem('haru.sending.c1')).toBeNull();
    expect(localStorage.getItem('haru.mock.db')).toBe('{}');
    expect(hasLocalDrafts()).toBe(false);
  });
});
