import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { CreatePlanRequest, TurnRequest } from '../../../api/types';
import { loadDraft } from '../../../state/planDraft';
import { renderApp } from '../../../test/renderApp';
import { server } from '../../../test/server';

const STORY =
  '이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사고, 저녁마다 걷던 하천 벤치에 앉아 쉬려고 했는데 이삿짐 정리가 길어져서 못 갔어요.';
const SLOW = { timeout: 15_000 };

const scenario = (s: string) => sessionStorage.setItem('haru.mock.scenario', s);

/** 사연 입력 → AI와 함께 정리하기 → 3-1 */
async function startAi() {
  const app = renderApp('/plans/new', 'u-jiyeon');
  await screen.findByTestId('screen-3');
  fireEvent.change(screen.getByLabelText('사연'), { target: { value: STORY } });
  fireEvent.click(screen.getByRole('button', { name: 'AI와 함께 정리하기' }));
  await screen.findByTestId('screen-3-1');
  return app;
}

/** turns 요청 본문을 모은다 */
function recordTurns() {
  const bodies: TurnRequest[] = [];
  server.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && request.url.includes('/turns')) {
      bodies.push((await request.clone().json()) as TurnRequest);
    }
  });
  return bodies;
}

describe('레벨 0(시나리오 없음)', () => {
  it('생성 응답이 바로 READY: 카드 미리보기·원문 대조 통과·메모', async () => {
    await startAi();
    const card = await screen.findByTestId('card-preview');
    expect(card).toHaveTextContent('이사 전, 마지막 동네 산책');
    expect(card).toHaveTextContent('원문 대조 통과');
    expect(within(card).getAllByText('비어 있어요').length).toBeGreaterThan(0); // estimatedMinutes null
    const notes = screen.getByTestId('ai-notes');
    expect(notes).toHaveTextContent("'골목 빵집' 대신 원문의 '출근길 빵집'으로 적었어요.");
    expect(notes).toHaveTextContent('원문');
    expect(screen.queryByTestId('ai-question')).not.toBeInTheDocument();
    expect(loadDraft()?.sessionId).toMatch(/^ais_/);
  });
});

describe('ai-ask(FE-CRT-12)', () => {
  it('질문 → 선택지 → READY → 폼에서 다듬기 → 공개 본문 AI_EDITED + aiSessionId', async () => {
    scenario('ai-ask');
    const turns = recordTurns();
    const { router } = await startAi();
    const q = await screen.findByTestId('ai-question');
    expect(q).toHaveTextContent('빵집과 하천 벤치까지, 산책은 대략 얼마나 걸릴 예정이었나요?');
    expect(q).toHaveTextContent('사연에 소요 시간이 없어요.');
    expect(screen.getByText('소요 시간 질문')).toBeInTheDocument(); // 단계 칩
    fireEvent.click(within(q).getByRole('button', { name: '45분' }));

    const notes = await screen.findByTestId('ai-notes');
    expect(notes).toHaveTextContent("답변 '45분'으로 채웠어요.");
    expect(notes).toHaveTextContent('내 답변');
    expect(turns).toEqual([{ expectedTurn: 1, answer: { questionId: 'q1', choice: '45분' } }]);

    fireEvent.click(screen.getByRole('button', { name: '폼에서 다듬기' }));
    await screen.findByTestId('screen-3-2');
    expect(router.state.location.pathname).toBe('/plans/new/form');
    expect(screen.getByLabelText('하루 제목')).toHaveValue('이사 전, 마지막 동네 산책');
    expect(screen.getByLabelText('예상 소요 시간(분)')).toHaveValue('45');
    const sessionId = loadDraft()?.sessionId;

    const sent: { body: CreatePlanRequest | null } = { body: null };
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/plans')) {
        sent.body = (await request.clone().json()) as CreatePlanRequest;
      }
    });
    fireEvent.click(screen.getByRole('button', { name: '이 하루 공개하기' }));
    await screen.findByTestId('screen-3-4');
    server.events.removeAllListeners();
    expect(sent.body?.authoring).toMatchObject({ mode: 'AI_EDITED', aiSessionId: sessionId, story: STORY });
  });

  it('건너뛰기 → MISSING 안내가 폼에 보이고, 입력하면 사라진다', async () => {
    scenario('ai-ask');
    await startAi();
    fireEvent.click(
      within(await screen.findByTestId('ai-question')).getByRole('button', { name: '건너뛰기' }),
    );
    await screen.findByTestId('card-preview');
    fireEvent.click(screen.getByRole('button', { name: '폼에서 다듬기' }));
    await screen.findByTestId('screen-3-2');
    expect(screen.getByText('직접 채워주세요')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('예상 소요 시간(분)'), { target: { value: '40' } });
    expect(screen.queryByText('직접 채워주세요')).not.toBeInTheDocument();
    expect(loadDraft()?.flags).toEqual([]);
  });

  it('직접 입력은 1–100자', async () => {
    scenario('ai-ask');
    await startAi();
    const q = await screen.findByTestId('ai-question');
    fireEvent.click(within(q).getByRole('button', { name: '보내기' }));
    expect(await screen.findByText('1–100자로 입력해 주세요.')).toBeInTheDocument();
    fireEvent.change(within(q).getByLabelText('직접 입력'), { target: { value: '70분' } });
    fireEvent.click(within(q).getByRole('button', { name: '보내기' }));
    expect(await screen.findByText('약 70분')).toBeInTheDocument();
  });

  it('"이대로 카드 받기" → finish: true, 질문은 건너뛴다', async () => {
    scenario('ai-ask');
    const turns = recordTurns();
    await startAi();
    await screen.findByTestId('ai-question');
    fireEvent.click(screen.getByRole('button', { name: '이대로 카드 받기' }));
    await screen.findByTestId('card-preview');
    server.events.removeAllListeners();
    expect(turns).toEqual([{ expectedTurn: 1, finish: true }]);
  });

  it('새로고침하면 GET으로 세션을 복구한다', async () => {
    scenario('ai-ask');
    await startAi();
    await screen.findByTestId('ai-question');
    cleanup();
    renderApp('/plans/new/card', 'u-jiyeon');
    expect(await screen.findByTestId('ai-question')).toHaveTextContent('빵집과 하천 벤치까지');
  });
});

describe('ai-working·ai-busy(FE-CRT-13)', () => {
  it('ai-working: 자동 turns, 연속 2회 WORKING이면 finish', async () => {
    scenario('ai-working');
    const turns = recordTurns();
    await startAi();
    await screen.findByTestId('card-preview', {}, SLOW);
    server.events.removeAllListeners();
    expect(turns).toEqual([{ expectedTurn: 1 }, { expectedTurn: 2, finish: true }]);
  });

  it('ai-busy: 409 BUSY → 2초 뒤 GET(같은 턴 WORKING) → GET READY', async () => {
    scenario('ai-busy');
    await startAi();
    fireEvent.click(within(await screen.findByTestId('ai-question')).getByRole('button', { name: '30분' }));
    expect(await screen.findByText('약 30분', {}, SLOW)).toBeInTheDocument();
  }, 60_000);
});

describe('ai-degraded·다시 넣기(FE-CRT-03, 14)', () => {
  it('원문 대조 통과 배지 없음, 다시 넣기 → 장소 추가 + PRIVACY 안내가 폼에', async () => {
    scenario('ai-degraded');
    await startAi();
    const card = await screen.findByTestId('card-preview');
    expect(card).not.toHaveTextContent('원문 대조 통과');
    const restore = screen.getByRole('button', { name: '다시 넣기' });
    fireEvent.click(restore);
    expect(await screen.findByRole('button', { name: '다시 넣었어요' })).toBeDisabled();
    expect(card).toHaveTextContent('민지네 집 앞');

    fireEvent.click(screen.getByRole('button', { name: '폼에서 다듬기' }));
    await screen.findByTestId('screen-3-2');
    expect(
      within(screen.getByTestId('place-1')).getByText('원문에 없던 내용이에요, 확인해 주세요'),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId('place-2')).getByText('공개하기 어려운 정보일 수 있어요'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('공개하기 어려운 정보일 수 있어요', { selector: 'p[id$="-hint"]' }),
    ).toBeInTheDocument(); // reason
    // 장소를 빼면 뒤 장소 안내가 당겨진다
    fireEvent.click(screen.getByRole('button', { name: '2번 장소 빼기' }));
    expect(
      within(screen.getByTestId('place-1')).getByText('공개하기 어려운 정보일 수 있어요'),
    ).toBeInTheDocument();
  });
});

describe('AI 실패 → 직접 작성(FE-CRT-04)', () => {
  it.each(['ai-fail', 'ai-quota', 'ai-invalid'])('%s: 사연 유지, 빈 폼, 안내, MANUAL', async (s) => {
    scenario(s);
    const { router } = await startAi();
    expect(await screen.findByTestId('ai-failed')).toHaveTextContent(
      'AI 카드를 만들지 못했어요. 직접 정리해 주세요',
    );
    expect(router.state.location.pathname).toBe('/plans/new/form');
    expect(screen.getByLabelText('하루 제목')).toHaveValue('');
    expect(screen.getByText(STORY, { selector: 'p' })).toBeInTheDocument();
    const d = loadDraft();
    expect(d).toMatchObject({ mode: 'MANUAL', sessionId: null, story: STORY });
  });

  it('ai-fail-turn: 답변에 503이면 직접 작성', async () => {
    scenario('ai-fail-turn');
    await startAi();
    fireEvent.click(within(await screen.findByTestId('ai-question')).getByRole('button', { name: '45분' }));
    expect(await screen.findByTestId('ai-failed')).toBeInTheDocument();
    await waitFor(() => expect(loadDraft()?.mode).toBe('MANUAL'));
  });
});
