import { describe, expect, it } from 'vitest';

import type { SessionView } from '../../api/types';
import { createSeed } from '../db';
import { createSession, getSession, turnSession } from './ai';

const ME = 'u-jiyeon';
const STORY = '출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했어요.';

function start(scenario: string | null) {
  const db = createSeed();
  const out = createSession(db, ME, { story: STORY }, scenario);
  return { db, out };
}

const viewOf = (o: unknown) => (o as { view: SessionView }).view;

describe('AI 세션 목업 공통(docs/03 §3.2)', () => {
  it('사연 길이 400, 남의 세션 404', () => {
    const db = createSeed();
    expect(createSession(db, ME, { story: '' }, null)).toMatchObject({
      error: 'VALIDATION_ERROR',
      status: 400,
    });
    const { db: db2, out } = start('ai-ask');
    const v = viewOf(out);
    expect(getSession(db2, 'u-suhyun', v.sessionId)).toMatchObject({ error: 'NOT_FOUND', status: 404 });
    expect(turnSession(db2, 'u-suhyun', v.sessionId, { expectedTurn: 1, finish: true })).toMatchObject({
      status: 404,
    });
  });

  it('시나리오 없음: 레벨 0, 생성 응답이 바로 READY(MISSING)', () => {
    const v = viewOf(start(null).out);
    expect(v).toMatchObject({ status: 'READY', turn: 1, question: null, degraded: false });
    expect(v.card?.places?.[0].name).toBe('출근길 빵집');
    expect(v.flags).toEqual([{ path: 'estimatedMinutes', type: 'MISSING' }]);
  });

  it('turn ≠ expectedTurn이면 현재 view 200, READY 뒤 같은 턴은 CLOSED, ASKING에 빈 요청은 400', () => {
    const { db, out } = start('ai-ask');
    const v = viewOf(out);
    expect(turnSession(db, ME, v.sessionId, { expectedTurn: 1 })).toMatchObject({
      error: 'VALIDATION_ERROR',
    });
    expect(viewOf(turnSession(db, ME, v.sessionId, { expectedTurn: 7, finish: true })).turn).toBe(1);
    turnSession(db, ME, v.sessionId, { expectedTurn: 1, answer: { questionId: 'q1', choice: '45분' } });
    expect(turnSession(db, ME, v.sessionId, { expectedTurn: 2, finish: true })).toMatchObject({
      error: 'AI_SESSION_CLOSED',
      status: 409,
    });
    expect(viewOf(turnSession(db, ME, v.sessionId, { expectedTurn: 1, finish: true })).status).toBe('READY');
  });

  it('답변 형식: questionId·choice·text·skipped 중 하나', () => {
    const { db, out } = start('ai-ask');
    const id = viewOf(out).sessionId;
    for (const answer of [
      { questionId: 'q9', choice: '45분' },
      { questionId: 'q1', choice: '2시간' },
      { questionId: 'q1', choice: '45분', skipped: true },
      { questionId: 'q1', text: '' },
    ]) {
      expect(turnSession(db, ME, id, { expectedTurn: 1, answer })).toMatchObject({
        error: 'VALIDATION_ERROR',
      });
    }
  });
});

describe('시나리오(docs/02 §2.10)', () => {
  it('ai-ask: ASKING(질문 1개) → 선택지 → READY(REWRITTEN·ASKED)', () => {
    const { db, out } = start('ai-ask');
    const v = viewOf(out);
    expect(v).toMatchObject({ status: 'ASKING', turn: 1, card: null, flags: [], notes: [] });
    expect(v.question?.options).toEqual(['30분', '45분', '1시간']);
    expect(v.trace.map((t) => t.tool)).toEqual(['check_draft', 'check_draft', 'ask_planner']);
    const r = viewOf(
      turnSession(db, ME, v.sessionId, { expectedTurn: 1, answer: { questionId: 'q1', choice: '45분' } }),
    );
    expect(r).toMatchObject({ status: 'READY', turn: 2, question: null, flags: [] });
    expect(r.card?.estimatedMinutes).toBe(45);
    expect(r.notes.map((n) => [n.action, n.source])).toEqual([
      ['REWRITTEN', 'STORY'],
      ['ASKED', 'ANSWER'],
    ]);
    expect(r.trace.at(-1)?.tool).toBe('submit_card');
  });

  it('ai-ask: 직접 입력 "1시간 반" 대신 "70분", 건너뛰기·finish는 MISSING', () => {
    const a = start('ai-ask');
    const id = viewOf(a.out).sessionId;
    expect(
      viewOf(turnSession(a.db, ME, id, { expectedTurn: 1, answer: { questionId: 'q1', text: '70분' } })).card
        ?.estimatedMinutes,
    ).toBe(70);
    const b = start('ai-ask');
    const skipped = viewOf(
      turnSession(b.db, ME, viewOf(b.out).sessionId, {
        expectedTurn: 1,
        answer: { questionId: 'q1', skipped: true },
      }),
    );
    expect(skipped.flags).toEqual([{ path: 'estimatedMinutes', type: 'MISSING' }]);
    const c = start('ai-ask');
    const finished = viewOf(
      turnSession(c.db, ME, viewOf(c.out).sessionId, { expectedTurn: 1, finish: true }),
    );
    expect(finished).toMatchObject({ status: 'READY', card: { estimatedMinutes: null } });
  });

  it('ai-working: WORKING → WORKING → finish → READY', () => {
    const { db, out } = start('ai-working');
    const v = viewOf(out);
    expect(v).toMatchObject({ status: 'WORKING', turn: 1 });
    const w2 = viewOf(turnSession(db, ME, v.sessionId, { expectedTurn: 1 }));
    expect(w2).toMatchObject({ status: 'WORKING', turn: 2 });
    const r = viewOf(turnSession(db, ME, v.sessionId, { expectedTurn: 2, finish: true }));
    expect(r).toMatchObject({ status: 'READY', turn: 3 });
  });

  it('ai-degraded: READY degraded, NOT_IN_SOURCE·PRIVACY, REMOVED(restore)·KEPT_FLAGGED', () => {
    const v = viewOf(start('ai-degraded').out);
    expect(v).toMatchObject({ status: 'READY', degraded: true });
    expect(v.flags.map((f) => f.type).sort()).toEqual(['NOT_IN_SOURCE', 'PRIVACY']);
    const removed = v.notes.find((n) => n.action === 'REMOVED');
    expect(removed?.restore).toEqual({
      value: { name: '민지네 집 앞', activity: '잠깐 인사하기', whyChosen: '' },
      type: 'PRIVACY',
    });
    expect(v.notes.some((n) => n.action === 'KEPT_FLAGGED')).toBe(true);
  });

  it('ai-busy: 첫 turns 409 BUSY → GET 같은 턴 WORKING → GET READY → turns CLOSED', () => {
    const { db, out } = start('ai-busy');
    const id = viewOf(out).sessionId;
    expect(
      turnSession(db, ME, id, { expectedTurn: 1, answer: { questionId: 'q1', choice: '30분' } }),
    ).toMatchObject({
      error: 'AI_SESSION_BUSY',
      status: 409,
    });
    expect(viewOf(getSession(db, ME, id))).toMatchObject({ status: 'WORKING', turn: 1 });
    expect(viewOf(getSession(db, ME, id))).toMatchObject({
      status: 'READY',
      turn: 2,
      card: { estimatedMinutes: 30 },
    });
    expect(turnSession(db, ME, id, { expectedTurn: 1, finish: true })).toMatchObject({
      error: 'AI_SESSION_CLOSED',
    });
  });

  it('ai-fail: 생성 503, ai-quota: 429, ai-invalid: 502', () => {
    expect(start('ai-fail').out).toMatchObject({ error: 'AI_UNAVAILABLE', status: 503 });
    expect(start('ai-quota').out).toMatchObject({ error: 'AI_QUOTA_EXCEEDED', status: 429 });
    expect(start('ai-invalid').out).toMatchObject({ error: 'AI_INVALID_OUTPUT', status: 502 });
  });

  it('ai-fail-turn: 생성 ASKING, 답변 503, 이후 GET FAILED', () => {
    const { db, out } = start('ai-fail-turn');
    const id = viewOf(out).sessionId;
    expect(viewOf(out).status).toBe('ASKING');
    expect(
      turnSession(db, ME, id, { expectedTurn: 1, answer: { questionId: 'q1', choice: '45분' } }),
    ).toMatchObject({
      error: 'AI_UNAVAILABLE',
      status: 503,
    });
    expect(viewOf(getSession(db, ME, id)).status).toBe('FAILED');
  });
});
