/**
 * AI 하루 카드 정리 세션 목업(docs/03 §3.2, docs/02 §2.10, FE-Q25).
 * 시나리오는 세션을 만들 때 `?mock=`으로 정해 세션에 저장한다(같은 세션은 끝까지 같은 경로).
 * - 없음: 레벨 0처럼 생성 응답이 바로 READY(estimatedMinutes MISSING)
 * - ai-ask: ASKING(소요 시간 질문) → 답변 → READY(REWRITTEN·ASKED)
 * - ai-working: WORKING → WORKING → finish → READY
 * - ai-degraded: READY + degraded, NOT_IN_SOURCE·PRIVACY flags, REMOVED(restore)·KEPT_FLAGGED 메모
 * - ai-busy: 첫 turns 409 BUSY, 첫 GET은 같은 turn의 WORKING, 다음 GET은 READY. READY 뒤 turns는 409 CLOSED
 * - ai-fail: 생성 503. ai-fail-turn: 생성 ASKING, 답변 503, 이후 GET FAILED
 * - ai-quota: 생성 429. ai-invalid: 생성 502
 */
import { HttpResponse, http } from 'msw';

import type { AiCard, AiNote, AiQuestion, AiTraceStep, ErrorCode, Flag, SessionView } from '../../api/types';
import type { DbAiSession, MockDb } from '../db';
import { updateDb } from '../db';
import { getMockScenario } from '../session';
import { api, apiError, currentUser, unauthorized } from './common';

type Outcome =
  { view: SessionView } | { error: ErrorCode; status: number; details?: { [path: string]: string } };

const MESSAGES: Partial<{ [code in ErrorCode]: string }> = {
  NOT_FOUND: '찾을 수 없어요.',
  VALIDATION_ERROR: '입력값을 확인해 주세요.',
  AI_SESSION_BUSY: '이전 요청을 처리하고 있어요.',
  AI_SESSION_CLOSED: '이미 끝난 정리예요.',
  AI_QUOTA_EXCEEDED: '오늘은 AI 정리를 더 쓸 수 없어요.',
  AI_INVALID_OUTPUT: 'AI 카드를 만들지 못했어요.',
  AI_UNAVAILABLE: 'AI 서비스에 연결하지 못했어요.',
};

// ---------------------------------------------------------------- 데모 데이터(§3.2 예시)

const QUESTION: AiQuestion = {
  questionId: 'q1',
  path: 'estimatedMinutes',
  text: '빵집과 하천 벤치까지, 산책은 대략 얼마나 걸릴 예정이었나요?',
  reason: '사연에 소요 시간이 없어요.',
  options: ['30분', '45분', '1시간'],
  allowFreeText: true,
};

const TRACE_CHECK: AiTraceStep[] = [
  { step: 1, tool: 'check_draft', summary: "'골목 빵집' 원문에 없음, 소요 시간 정보 없음" },
  { step: 2, tool: 'check_draft', summary: "'출근길 빵집'으로 고침, 개인정보 확인 통과" },
];
const TRACE_ASK: AiTraceStep[] = [
  ...TRACE_CHECK,
  { step: 3, tool: 'ask_planner', summary: '소요 시간 질문' },
];
const submitStep = (step: number): AiTraceStep => ({
  step,
  tool: 'submit_card',
  summary: '제출, 서버 검사 통과',
});

function demoCard(minutes: number | null): AiCard {
  return {
    title: '이사 전, 마지막 동네 산책',
    summary: '출근길 빵집에 들르고, 저녁마다 걷던 하천 벤치에 앉아 쉬고 싶었어요.',
    reason: '이삿짐 정리가 길어져 5년간 살던 동네에서 마지막 산책을 하지 못했어요.',
    estimatedMinutes: minutes,
    places: [
      { name: '출근길 빵집', activity: '들러서 빵 사기', whyChosen: '출근길에 지나치던 곳이에요.' },
      { name: '하천 산책로 벤치', activity: '벤치에 앉아 쉬기', whyChosen: '저녁마다 걷던 길이에요.' },
    ],
    question: '하천 벤치에 앉았을 때 어떤 풍경이 보였나요?',
  };
}

const NOTE_REWRITTEN: AiNote = {
  path: 'places[0].name',
  action: 'REWRITTEN',
  reason: "'골목 빵집' 대신 원문의 '출근길 빵집'으로 적었어요.",
  source: 'STORY',
};
const missingMinutes: Flag = { path: 'estimatedMinutes', type: 'MISSING' };

// ---------------------------------------------------------------- 상태 전이

function toView(s: DbAiSession): SessionView {
  const ready = s.status === 'READY';
  return {
    sessionId: s.sessionId,
    status: s.status,
    turn: s.turn,
    trace: s.trace.map((t) => ({ ...t })),
    question: s.status === 'ASKING' ? s.question : null,
    card: ready ? s.card : null,
    flags: ready ? s.flags : [],
    notes: ready ? s.notes : [],
    degraded: s.degraded,
  };
}

function setReady(s: DbAiSession, card: AiCard, flags: Flag[], notes: AiNote[], extraTrace: AiTraceStep[]) {
  s.status = 'READY';
  s.question = null;
  s.card = card;
  s.flags = flags;
  s.notes = notes;
  s.trace = [...s.trace, ...extraTrace];
}

/** 답변 값을 분으로. 범위(10–240)를 벗어나거나 읽을 수 없으면 null */
function minutesFrom(answer: { choice?: string; text?: string }): number | null {
  const raw = answer.choice ?? answer.text ?? '';
  const m = /(\d+)/.exec(raw);
  if (!m) return null;
  let n = Number(m[1]);
  if (raw.includes('시간') && !raw.includes('분')) n *= 60;
  return n >= 10 && n <= 240 ? n : null;
}

/** ai-ask 계열: 답변·건너뛰기·finish로 READY를 만든다 */
function readyFromAnswer(
  s: DbAiSession,
  answer: { choice?: string; text?: string; skipped?: boolean } | null,
) {
  const minutes = answer && !answer.skipped ? minutesFrom(answer) : null;
  const label = answer?.choice ?? answer?.text;
  const notes: AiNote[] = [NOTE_REWRITTEN];
  if (minutes !== null && label) {
    notes.push({
      path: 'estimatedMinutes',
      action: 'ASKED',
      reason: `답변 '${label}'으로 채웠어요.`,
      source: 'ANSWER',
    });
  }
  setReady(s, demoCard(minutes), minutes === null ? [missingMinutes] : [], notes, [
    submitStep(s.trace.length + 1),
  ]);
}

function newSession(ownerId: string, story: string, scenario: string | null): DbAiSession {
  return {
    sessionId: `ais_${crypto.randomUUID().replace(/-/g, '').slice(0, 24).toUpperCase()}`,
    ownerId,
    story,
    scenario,
    status: 'WORKING',
    turn: 1,
    trace: [],
    question: null,
    card: null,
    flags: [],
    notes: [],
    degraded: false,
    finishRequested: false,
  };
}

export function createSession(db: MockDb, ownerId: string, body: unknown, scenario: string | null): Outcome {
  const story = (body as { story?: unknown } | null)?.story;
  if (typeof story !== 'string' || [...story].length < 1 || [...story].length > 1000) {
    return { error: 'VALIDATION_ERROR', status: 400, details: { story: '1–1000자로 입력해 주세요.' } };
  }
  if (scenario === 'ai-quota') return { error: 'AI_QUOTA_EXCEEDED', status: 429 };
  if (scenario === 'ai-invalid') return { error: 'AI_INVALID_OUTPUT', status: 502 };

  const s = newSession(ownerId, story, scenario);
  db.aiSessions.push(s);
  switch (scenario) {
    case 'ai-fail':
      s.status = 'FAILED';
      return { error: 'AI_UNAVAILABLE', status: 503 };
    case 'ai-ask':
    case 'ai-busy':
    case 'ai-fail-turn':
      s.status = 'ASKING';
      s.trace = [...TRACE_ASK];
      s.question = QUESTION;
      break;
    case 'ai-working':
      s.trace = [{ step: 1, tool: 'check_draft', summary: "'골목 빵집' 원문에 없음" }];
      break;
    case 'ai-degraded':
      s.degraded = true;
      s.trace = [...TRACE_CHECK];
      setReady(
        s,
        {
          ...demoCard(45),
          places: [demoCard(45).places![0], { name: '골목 카페', activity: '커피 마시기', whyChosen: '' }],
        },
        [
          { path: 'places[1].name', type: 'NOT_IN_SOURCE' },
          { path: 'reason', type: 'PRIVACY' },
        ],
        [
          NOTE_REWRITTEN,
          {
            path: 'places[2].name',
            action: 'REMOVED',
            reason: "'민지네 집 앞'은 비공개 장소라 동선에서 뺐어요.",
            source: 'STORY',
            restore: {
              value: { name: '민지네 집 앞', activity: '잠깐 인사하기', whyChosen: '' },
              type: 'PRIVACY',
            },
          },
          {
            path: 'places[1].name',
            action: 'KEPT_FLAGGED',
            reason: "'골목 카페'는 원문에서 찾지 못했어요. 확인해 주세요.",
            source: 'STORY',
          },
        ],
        [
          { step: 3, tool: 'submit_card', summary: '제출, 서버 검사 거부(원문에 없음)' },
          { step: 4, tool: 'fallback', summary: '자동 정리로 마무리, 확인 필요 2건' },
        ],
      );
      break;
    default:
      // 레벨 0: 질문 없이 바로 READY
      s.trace = [...TRACE_CHECK];
      setReady(s, demoCard(null), [missingMinutes], [NOTE_REWRITTEN], [submitStep(3)]);
  }
  return { view: toView(s) };
}

type AnswerIn = { questionId?: unknown; choice?: unknown; text?: unknown; skipped?: unknown };

function badAnswer(s: DbAiSession, a: AnswerIn): boolean {
  const q = s.status === 'ASKING' ? s.question : null;
  if (!q || a.questionId !== q.questionId) return true;
  const kinds = [a.choice !== undefined, a.text !== undefined, a.skipped !== undefined].filter(
    Boolean,
  ).length;
  if (kinds !== 1) return true;
  if (a.choice !== undefined) return typeof a.choice !== 'string' || !q.options.includes(a.choice);
  if (a.text !== undefined) {
    return (
      !q.allowFreeText || typeof a.text !== 'string' || [...a.text].length < 1 || [...a.text].length > 100
    );
  }
  return a.skipped !== true;
}

export function turnSession(db: MockDb, ownerId: string, sessionId: string, body: unknown): Outcome {
  const s = db.aiSessions.find((x) => x.sessionId === sessionId && x.ownerId === ownerId);
  if (!s) return { error: 'NOT_FOUND', status: 404 };
  const b = (body ?? {}) as { expectedTurn?: unknown; answer?: AnswerIn; finish?: unknown };
  const closed = s.status === 'READY' || s.status === 'FAILED';
  // ai-busy는 §2.10대로 READY 뒤 같은 expectedTurn에도 CLOSED
  if (s.scenario === 'ai-busy' && closed) return { error: 'AI_SESSION_CLOSED', status: 409 };
  if (typeof b.expectedTurn !== 'number') {
    return { error: 'VALIDATION_ERROR', status: 400, details: { expectedTurn: '필수 항목이에요.' } };
  }
  if (b.expectedTurn !== s.turn) return { view: toView(s) }; // 같은 턴 재전송 멱등
  if (closed) return { error: 'AI_SESSION_CLOSED', status: 409 };
  if (s.pending) return { error: 'AI_SESSION_BUSY', status: 409 };

  const finish = b.finish === true;
  if (b.answer !== undefined && badAnswer(s, b.answer)) {
    return { error: 'VALIDATION_ERROR', status: 400, details: { answer: '답변 형식이 올바르지 않아요.' } };
  }
  if (s.status === 'ASKING' && b.answer === undefined && !finish) {
    return {
      error: 'VALIDATION_ERROR',
      status: 400,
      details: { answer: '답변하거나 finish를 보내 주세요.' },
    };
  }
  if (finish) s.finishRequested = true;
  const answer = b.answer
    ? {
        choice: b.answer.choice as string | undefined,
        text: b.answer.text as string | undefined,
        skipped: b.answer.skipped === true,
      }
    : null;

  if (s.scenario === 'ai-fail-turn') {
    s.status = 'FAILED';
    s.question = null;
    return { error: 'AI_UNAVAILABLE', status: 503 };
  }

  if (s.scenario === 'ai-busy') {
    // 다른 요청이 잠금을 잡은 것처럼: 지금은 WORKING(turn 그대로), 결과는 GET에서 반영한다
    const result: DbAiSession = { ...s, trace: [...s.trace] };
    readyFromAnswer(result, answer);
    result.turn = s.turn + 1;
    s.status = 'WORKING';
    s.question = null;
    delete result.pending;
    s.pending = { view: result, workingGets: 1 };
    return { error: 'AI_SESSION_BUSY', status: 409 };
  }

  if (s.scenario === 'ai-working' && s.status === 'WORKING') {
    s.turn += 1;
    if (s.finishRequested) {
      setReady(s, demoCard(null), [missingMinutes], [NOTE_REWRITTEN], [submitStep(s.trace.length + 1)]);
    } else {
      s.trace = [
        ...s.trace,
        { step: s.trace.length + 1, tool: 'check_draft', summary: "'출근길 빵집'으로 고침" },
      ];
    }
    return { view: toView(s) };
  }

  // ASKING(ai-ask): 답변·건너뛰기·finish(답변 없으면 건너뜀) → READY
  s.turn += 1;
  readyFromAnswer(s, answer);
  return { view: toView(s) };
}

export function getSession(db: MockDb, ownerId: string, sessionId: string): Outcome {
  const s = db.aiSessions.find((x) => x.sessionId === sessionId && x.ownerId === ownerId);
  if (!s) return { error: 'NOT_FOUND', status: 404 };
  if (s.pending) {
    if (s.pending.workingGets > 0) {
      s.pending.workingGets -= 1;
      return { view: toView(s) };
    }
    Object.assign(s, s.pending.view);
    delete s.pending;
  }
  return { view: toView(s) };
}

// ---------------------------------------------------------------- 핸들러

function respond(out: Outcome) {
  if ('view' in out) return HttpResponse.json(out.view);
  return apiError(out.error, MESSAGES[out.error] ?? '', out.status, out.details);
}

async function readBody(request: Request): Promise<unknown> {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

export const aiHandlers = [
  http.post(api('/ai/card-sessions'), async ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const body = await readBody(request);
    return respond(updateDb((db) => createSession(db, user.userId, body, getMockScenario())));
  }),

  http.post(api('/ai/card-sessions/:sessionId/turns'), async ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const body = await readBody(request);
    return respond(updateDb((db) => turnSession(db, user.userId, String(params.sessionId), body)));
  }),

  http.get(api('/ai/card-sessions/:sessionId'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    return respond(updateDb((db) => getSession(db, user.userId, String(params.sessionId))));
  }),
];
