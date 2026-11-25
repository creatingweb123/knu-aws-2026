import { describe, expect, it } from 'vitest';

import type { PlanFormValues } from './validation';
import {
  charCount,
  parseMinutes,
  summaryFromStory,
  validatePlace,
  validatePlanForm,
  validateStory,
} from './validation';

const valid = (): PlanFormValues => ({
  title: '이사 전, 마지막 동네 산책',
  summary: '출근길 빵집에 들르고 싶었어요.',
  reason: '이삿짐 정리가 길어졌어요.',
  estimatedMinutes: '45',
  places: [{ name: '출근길 빵집', activity: '들러서 빵 사기', whyChosen: '' }],
  question: '어떤 소리가 들렸나요?',
});

const s = (n: number) => '가'.repeat(n);

describe('폼 검증(FE-CRT-06, 백엔드 validation.py와 같은 경계)', () => {
  it('올바른 폼은 오류가 없다', () => {
    expect(validatePlanForm(valid())).toEqual({});
  });

  it.each([
    ['title', 40],
    ['summary', 120],
    ['reason', 300],
    ['question', 80],
  ] as const)('%s: 1–%i자', (key, max) => {
    expect(validatePlanForm({ ...valid(), [key]: s(max) })[key]).toBeUndefined();
    expect(validatePlanForm({ ...valid(), [key]: s(max + 1) })[key]).toBeDefined();
    expect(validatePlanForm({ ...valid(), [key]: '' })[key]).toBeDefined();
  });

  it('앞뒤 공백을 빼고 센다: 공백만이면 오류(FE-Q19)', () => {
    expect(validatePlanForm({ ...valid(), title: '   ' }).title).toBe('1–40자로 입력해 주세요.');
    expect(validatePlanForm({ ...valid(), title: `  ${s(40)}  ` }).title).toBeUndefined();
  });

  it('글자 수는 코드 포인트로 센다', () => {
    expect(charCount('🙂🙂')).toBe(2);
    expect(validatePlanForm({ ...valid(), title: '🙂'.repeat(40) }).title).toBeUndefined();
  });

  it('예상 소요 시간 10–240 정수', () => {
    for (const ok of ['10', '240', ' 45 '])
      expect(validatePlanForm({ ...valid(), estimatedMinutes: ok }).estimatedMinutes).toBeUndefined();
    for (const bad of ['9', '241', '', '4.5', '-10', '45분'])
      expect(validatePlanForm({ ...valid(), estimatedMinutes: bad }).estimatedMinutes).toBe(
        '10–240 사이의 정수로 입력해 주세요.',
      );
    expect(parseMinutes('045')).toBe(45);
  });

  it('장소 1–3곳, 장소별 오류는 places[i].필드 경로', () => {
    expect(validatePlanForm({ ...valid(), places: [] }).places).toBe('장소는 1–3곳이어야 해요.');
    const p = valid().places[0];
    expect(validatePlanForm({ ...valid(), places: [p, p, p, p] }).places).toBeDefined();
    const errs = validatePlanForm({
      ...valid(),
      places: [p, { name: '', activity: s(61), whyChosen: s(121) }],
    });
    expect(errs).toMatchObject({
      'places[1].name': '1–30자로 입력해 주세요.',
      'places[1].activity': '1–60자로 입력해 주세요.',
      'places[1].whyChosen': '0–120자로 입력해 주세요.',
    });
    expect(errs['places[0].name']).toBeUndefined();
  });

  it('장소 단독 검증: 고른 이유는 비어도 된다', () => {
    expect(validatePlace({ name: '빵집', activity: '빵 사기', whyChosen: '' })).toEqual({});
    expect(validatePlace({ name: s(31), activity: '빵 사기', whyChosen: '' })).toHaveProperty('name');
  });

  it('사연 1–1000자', () => {
    expect(validateStory(s(1000))).toEqual({});
    expect(validateStory(s(1001))).toHaveProperty('story');
    expect(validateStory('  ')).toHaveProperty('story');
  });

  it('summary 기본값은 사연 앞 120자(FE-CRT-05)', () => {
    expect(summaryFromStory('  짧은 사연  ')).toBe('짧은 사연');
    expect(charCount(summaryFromStory(s(500)))).toBe(120);
  });
});
