import { describe, expect, it } from 'vitest';

import { DRAFT_KEY, clearDraft, loadDraft, newDraft, saveDraft, startDraft } from './planDraft';

describe('작성 상태(FE-CRT-08, FE-CRT-09)', () => {
  it('startDraft는 처음 한 번만 startedAt을 기록한다', () => {
    const first = startDraft(1000);
    expect(first.startedAt).toBe(1000);
    saveDraft({ ...first, story: '사연' });
    const again = startDraft(9999);
    expect(again.startedAt).toBe(1000);
    expect(again.story).toBe('사연');
  });

  it('sessionStorage 한 항목에 저장하고 복원한다', () => {
    const d = { ...newDraft(5), story: 's', idempotencyKey: 'k', keyBodyHash: 'h', keyDurationMs: 7 };
    saveDraft(d);
    expect(sessionStorage.length).toBe(1);
    expect(sessionStorage.key(0)).toBe(DRAFT_KEY);
    expect(loadDraft()).toEqual(d);
  });

  it('손상되거나 형태가 다른 값은 버린다', () => {
    sessionStorage.setItem(DRAFT_KEY, '{not json');
    expect(loadDraft()).toBeNull();
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ version: 99, story: 's' }));
    expect(loadDraft()).toBeNull();
  });

  it('clearDraft로 지운다(공개 성공)', () => {
    saveDraft(newDraft(1));
    clearDraft();
    expect(loadDraft()).toBeNull();
  });
});
