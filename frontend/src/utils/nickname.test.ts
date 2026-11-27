import { describe, expect, it } from 'vitest';

import { CLAIMER_FALLBACK_NAME, OWNER_FALLBACK_NAME, displayNickname, initialOf } from './nickname';

describe('닉네임 표시(BE-Q45)', () => {
  it('닉네임이 있으면 그대로 쓴다', () => {
    expect(displayNickname('지연', OWNER_FALLBACK_NAME)).toBe('지연');
  });

  it('null·빈 문자열·공백만 있으면 기본 표시명을 쓴다', () => {
    expect(displayNickname(null, OWNER_FALLBACK_NAME)).toBe(OWNER_FALLBACK_NAME);
    expect(displayNickname('', CLAIMER_FALLBACK_NAME)).toBe(CLAIMER_FALLBACK_NAME);
    expect(displayNickname('   ', CLAIMER_FALLBACK_NAME)).toBe(CLAIMER_FALLBACK_NAME);
    expect(displayNickname(undefined, CLAIMER_FALLBACK_NAME)).toBe(CLAIMER_FALLBACK_NAME);
  });

  it('아바타 글자는 코드 포인트 기준 첫 글자이고 빈 문자열이면 빈 문자열이다', () => {
    expect(initialOf('지연')).toBe('지');
    expect(initialOf('🙂수현')).toBe('🙂');
    expect(initialOf('')).toBe('');
  });
});
