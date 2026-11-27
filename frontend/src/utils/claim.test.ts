import { describe, expect, it } from 'vitest';

import { dueText, recordPath } from './claim';

describe('기한 문구(FE-ME-02, KST)', () => {
  const now = Date.parse('2026-11-20T03:00:00.000Z');

  it('기한 전: KST 날짜로 "{M}월 {D}일까지"', () => {
    // UTC 11/21 15:30 = KST 11/22 00:30
    expect(dueText('2026-11-21T15:30:00.000Z', now)).toBe('11월 22일까지 다녀온 이야기를 보내주세요.');
  });

  it('기한 후', () => {
    expect(dueText('2026-11-19T03:00:00.000Z', now)).toBe(
      '기한이 지났어요. 다른 사람이 이어받기 전까지는 보낼 수 있어요.',
    );
  });
});

describe('다녀온 이야기 쓰기 이동(FE-ME-03, FE-Q22)', () => {
  it.each([
    [undefined, '/claims/c1/record'],
    ['NONE', '/claims/c1/record'],
    ['READY', '/claims/c1/record'],
    ['DISCARDED', '/claims/c1/record'],
    ['UPLOAD_PENDING', '/claims/c1/sending'],
    ['PROCESSING', '/claims/c1/sending'],
    ['FAILED', '/claims/c1/sending'],
  ] as const)('%s → %s', (status, path) => {
    expect(recordPath('c1', status)).toBe(path);
  });
});
