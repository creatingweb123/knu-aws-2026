import { describe, expect, it } from 'vitest';

import { formatDateTime, formatMonthDay, kstDateKey } from './date';

describe('KST 표시(FE-COM-06)', () => {
  it('UTC 15:00 이후는 한국 날짜로 다음 날이다', () => {
    expect(formatMonthDay('2026-11-20T15:30:00.000Z')).toBe('11월 21일');
    expect(kstDateKey('2026-11-20T15:30:00.000Z')).toBe('2026-11-21');
    expect(kstDateKey('2026-11-20T14:59:59.999Z')).toBe('2026-11-20');
  });

  it('시각까지 표시한다', () => {
    expect(formatDateTime('2026-11-17T09:00:00.000Z')).toMatch(/11월 17일 오후 6:00/);
  });

  it('잘못된 값은 RangeError', () => {
    expect(() => formatMonthDay('not-a-date')).toThrow(RangeError);
  });
});
