import { describe, expect, it } from 'vitest';

import { claimStep, dDayText, dueText, recordPath } from './claim';

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

describe('남은 날 칩(docs/05 §5.2.4, KST)', () => {
  // KST 11/20 12:00
  const now = Date.parse('2026-11-20T03:00:00.000Z');

  it('KST 날짜 차이로 센다', () => {
    // UTC 11/21 15:30 = KST 11/22 00:30 → 2일 남음
    expect(dDayText('2026-11-21T15:30:00.000Z', now)).toBe('D-2');
  });

  it('기한 당일은 D-day', () => {
    expect(dDayText('2026-11-20T10:00:00.000Z', now)).toBe('D-day');
  });

  it('기한이 지났으면 "기한 지남"', () => {
    expect(dDayText('2026-11-20T02:00:00.000Z', now)).toBe('기한 지남');
  });
});

describe('내 하루 진행 단계(docs/05 §5.2.4)', () => {
  it('기록이 없으면 다녀오기 단계', () => {
    expect(claimStep(undefined, false)).toBe(1);
    expect(claimStep('NONE', false)).toBe(1);
  });

  it('저장된 기록이 있거나 사진 처리 중이면 경험 기록 보내기 단계', () => {
    expect(claimStep('NONE', true)).toBe(2);
    expect(claimStep('PROCESSING', true)).toBe(2);
    expect(claimStep('FAILED', true)).toBe(2);
  });
});
