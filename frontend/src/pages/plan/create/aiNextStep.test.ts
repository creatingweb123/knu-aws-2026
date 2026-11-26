import { describe, expect, it } from 'vitest';

import { flagFor, placeFlags, removePlaceFlags, restorePlace, cardToForm } from './cardForm';
import { decideAiNextStep } from './aiNextStep';

describe('decideAiNextStep(FE-CRT-13)', () => {
  it('WORKING 1회는 finish 없이, 2회째부터 finish', () => {
    expect(decideAiNextStep({ status: 'WORKING' }, 0, false)).toEqual({
      next: 'turn',
      finish: false,
      consecutiveWorking: 1,
    });
    expect(decideAiNextStep({ status: 'WORKING' }, 1, false)).toEqual({
      next: 'turn',
      finish: true,
      consecutiveWorking: 2,
    });
    expect(decideAiNextStep({ status: 'WORKING' }, 5, false)).toMatchObject({ finish: true });
  });

  it('finish 요청·예약이 있으면 첫 WORKING부터 finish', () => {
    expect(decideAiNextStep({ status: 'WORKING' }, 0, true)).toMatchObject({ next: 'turn', finish: true });
  });

  it('ASKING은 대기, 예약이 있으면 바로 finish turns(질문 건너뜀)', () => {
    expect(decideAiNextStep({ status: 'ASKING' }, 1, false)).toEqual({ next: 'ask', consecutiveWorking: 0 });
    expect(decideAiNextStep({ status: 'ASKING' }, 1, true)).toEqual({
      next: 'turn',
      finish: true,
      consecutiveWorking: 0,
    });
  });

  it('READY·FAILED, 다른 상태면 연속 횟수를 0으로', () => {
    expect(decideAiNextStep({ status: 'READY' }, 3, true)).toEqual({ next: 'ready', consecutiveWorking: 0 });
    expect(decideAiNextStep({ status: 'FAILED' }, 3, false)).toEqual({
      next: 'failed',
      consecutiveWorking: 0,
    });
  });
});

describe('카드 ↔ 폼(FE-CRT-02, 03, 14)', () => {
  it('null은 빈칸, 분은 문자열', () => {
    expect(
      cardToForm({
        title: '제목',
        summary: null,
        reason: '이유',
        estimatedMinutes: null,
        places: [{ name: '빵집', activity: null, whyChosen: null }],
        question: null,
      }),
    ).toEqual({
      title: '제목',
      summary: '',
      reason: '이유',
      estimatedMinutes: '',
      places: [{ name: '빵집', activity: '', whyChosen: '' }],
      question: '',
    });
    expect(
      cardToForm({
        title: null,
        summary: null,
        reason: null,
        estimatedMinutes: 45,
        places: null,
        question: null,
      }).estimatedMinutes,
    ).toBe('45');
  });

  it('flag 문구와 장소 flag', () => {
    const flags = [
      { path: 'estimatedMinutes', type: 'MISSING' as const },
      { path: 'places[1].name', type: 'NOT_IN_SOURCE' as const },
      { path: 'places[1].activity', type: 'PRIVACY' as const },
    ];
    expect(flagFor(flags, 'estimatedMinutes')).toBe('직접 채워주세요');
    expect(flagFor(flags, 'title')).toBeUndefined();
    expect(placeFlags(flags, 1)).toEqual([
      '원문에 없던 내용이에요, 확인해 주세요',
      '공개하기 어려운 정보일 수 있어요',
    ]);
    expect(placeFlags(flags, 0)).toEqual([]);
  });

  it('장소를 빼면 그 flag를 지우고 뒤 인덱스를 당긴다', () => {
    const flags = [
      { path: 'places[0].name', type: 'PRIVACY' as const },
      { path: 'places[2].name', type: 'NOT_IN_SOURCE' as const },
      { path: 'title', type: 'MISSING' as const },
    ];
    expect(removePlaceFlags(flags, 0)).toEqual([
      { path: 'places[1].name', type: 'NOT_IN_SOURCE' },
      { path: 'title', type: 'MISSING' },
    ]);
  });

  it('다시 넣기: 끝에 넣고 이름 경로에 경고, 3곳이면 null(FE-Q7)', () => {
    const value = { name: '민지네 집 앞', activity: '인사', whyChosen: '' };
    const places = [{ name: 'a', activity: 'b', whyChosen: '' }];
    expect(restorePlace(places, [], value, 'PRIVACY')).toEqual({
      places: [places[0], value],
      flags: [{ path: 'places[1].name', type: 'PRIVACY' }],
    });
    expect(restorePlace([places[0], places[0], places[0]], [], value, 'PRIVACY')).toBeNull();
  });
});
