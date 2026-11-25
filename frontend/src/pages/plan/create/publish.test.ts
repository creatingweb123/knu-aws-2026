import { describe, expect, it } from 'vitest';

import type { PlanDraft } from '../../../state/planDraft';
import { newDraft } from '../../../state/planDraft';
import { buildPlanContent, preparePublish } from './publish';

function draft(over: Partial<PlanDraft> = {}): PlanDraft {
  return {
    ...newDraft(1_000),
    story: '  이사 전에 동네를 걷고 싶었어요.  ',
    form: {
      title: ' 마지막 산책 ',
      summary: '빵집에 들르고 싶었어요.',
      reason: '이사 준비',
      estimatedMinutes: ' 45 ',
      places: [{ name: ' 출근길 빵집 ', activity: '빵 사기', whyChosen: '' }],
      question: '무엇이 보였나요?',
    },
    ...over,
  };
}

describe('공개 본문(FE-CRT-09)', () => {
  it('앞뒤 공백을 빼고 분은 정수, authoring에 mode·story', () => {
    const c = buildPlanContent(draft());
    expect(c).toEqual({
      title: '마지막 산책',
      summary: '빵집에 들르고 싶었어요.',
      reason: '이사 준비',
      estimatedMinutes: 45,
      places: [{ name: '출근길 빵집', activity: '빵 사기', whyChosen: '' }],
      question: '무엇이 보였나요?',
      authoring: { mode: 'MANUAL', story: '이사 전에 동네를 걷고 싶었어요.' },
    });
  });

  it('aiSessionId는 AI_EDITED이고 sessionId가 있을 때만', () => {
    expect(buildPlanContent(draft({ sessionId: 'ais_1' })).authoring).not.toHaveProperty('aiSessionId');
    expect(buildPlanContent(draft({ mode: 'AI_EDITED', sessionId: 'ais_1' })).authoring.aiSessionId).toBe(
      'ais_1',
    );
    expect(buildPlanContent(draft({ mode: 'AI_EDITED' })).authoring).not.toHaveProperty('aiSessionId');
  });

  it('durationMs = 누른 시각 − startedAt', () => {
    expect(preparePublish(draft(), 184_000).body.authoring.durationMs).toBe(183_000);
  });
});

describe('Idempotency-Key 재사용(FE-CRT-10, FE-Q18)', () => {
  it('처음에는 새 키를 만든다', () => {
    const p = preparePublish(draft(), 5_000);
    expect(p.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(p.keyDurationMs).toBe(4_000);
  });

  it('본문이 같으면 시간이 지나도 같은 키·같은 durationMs로 같은 본문을 보낸다', () => {
    const first = preparePublish(draft(), 5_000);
    const saved = draft({
      idempotencyKey: first.key,
      keyBodyHash: first.keyBodyHash,
      keyDurationMs: first.keyDurationMs,
    });
    const again = preparePublish(saved, 60_000);
    expect(again.key).toBe(first.key);
    expect(again.body).toEqual(first.body);
  });

  it('공백만 바뀌어 보낼 본문이 같으면 같은 키', () => {
    const first = preparePublish(draft(), 5_000);
    const d = draft({
      idempotencyKey: first.key,
      keyBodyHash: first.keyBodyHash,
      keyDurationMs: first.keyDurationMs,
    });
    d.form = { ...d.form, title: '마지막 산책   ' };
    expect(preparePublish(d, 9_000).key).toBe(first.key);
  });

  it('폼이 바뀌면 새 키와 새 durationMs', () => {
    const first = preparePublish(draft(), 5_000);
    const d = draft({
      idempotencyKey: first.key,
      keyBodyHash: first.keyBodyHash,
      keyDurationMs: first.keyDurationMs,
    });
    d.form = { ...d.form, title: '다른 제목' };
    const next = preparePublish(d, 9_000);
    expect(next.key).not.toBe(first.key);
    expect(next.keyDurationMs).toBe(8_000);
  });
});
