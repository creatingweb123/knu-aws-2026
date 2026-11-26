import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';

import type { CreatePlanRequest } from '../../../api/types';
import { loadDb } from '../../../mocks/db';
import { loadDraft, newDraft, saveDraft } from '../../../state/planDraft';
import { renderApp } from '../../../test/renderApp';
import { server } from '../../../test/server';

const STORY = '이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요. 출근길 빵집에 들러 빵을 사려고 했어요.';

const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

async function fillPlace(name: string, activity: string, why = '') {
  await screen.findByTestId('screen-3-3');
  type('장소 이름', name);
  type('하고 싶었던 일', activity);
  type('이 장소를 고른 이유', why);
}

/** 사연 입력 → 직접 작성 → 폼 */
async function startManual() {
  const app = renderApp('/plans/new', 'u-jiyeon');
  await screen.findByTestId('screen-3');
  type('사연', STORY);
  fireEvent.click(screen.getByRole('button', { name: '직접 작성하기' }));
  await screen.findByTestId('screen-3-2');
  return app;
}

async function fillForm() {
  type('하루 제목', '이사 전, 마지막 동네 산책');
  type('취소한 이유', '이삿짐 정리가 길어졌어요.');
  type('예상 소요 시간(분)', '45');
  type('방문 질문', '빵집에서 무엇을 샀나요?');
  fireEvent.click(screen.getByRole('button', { name: '+ 장소 추가' }));
  await fillPlace('출근길 빵집', '들러서 빵 사기', '출근길에 지나치던 곳이에요.');
  fireEvent.click(screen.getByRole('button', { name: '동선에 추가하기' }));
  await screen.findByTestId('screen-3-2');
}

describe('사연 입력(FE-CRT-01, FE-CRT-05)', () => {
  it('안내 문구와 두 버튼', async () => {
    renderApp('/plans/new', 'u-jiyeon');
    await screen.findByTestId('screen-3');
    expect(screen.getByText('집 주소나 개인 정보는 적지 말아주세요.')).toBeInTheDocument();
    expect(screen.getByText(/외부 AI 서비스로 전송/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'AI와 함께 정리하기' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '직접 작성하기' })).toBeEnabled();
  });

  it('사연이 비면 직접 작성으로 가지 않고 오류를 보여 준다', async () => {
    const { router } = renderApp('/plans/new', 'u-jiyeon');
    await screen.findByTestId('screen-3');
    fireEvent.click(screen.getByRole('button', { name: '직접 작성하기' }));
    expect(await screen.findByText('1–1000자로 입력해 주세요.')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/plans/new');
  });

  it('직접 작성: MANUAL, summary 기본값은 사연 앞부분', async () => {
    await startManual();
    expect(screen.getByLabelText('하고 싶었던 일 요약')).toHaveValue(STORY);
    expect(loadDraft()?.mode).toBe('MANUAL');
    expect(screen.getByText(STORY, { selector: 'p' })).toBeInTheDocument(); // 사연 참고 박스
  });

  it('startedAt은 처음 들어올 때 한 번만 기록한다(FE-CRT-09)', async () => {
    saveDraft({ ...newDraft(1234), story: '이전 사연' });
    renderApp('/plans/new', 'u-jiyeon');
    await screen.findByTestId('screen-3');
    expect(screen.getByLabelText('사연')).toHaveValue('이전 사연');
    expect(loadDraft()?.startedAt).toBe(1234);
  });

  it('사연 없이 폼·장소 추가로 들어오면 사연 입력으로 보낸다', async () => {
    const { router } = renderApp('/plans/new/form', 'u-jiyeon');
    await screen.findByTestId('screen-3');
    expect(router.state.location.pathname).toBe('/plans/new');
  });
});

describe('폼·장소(FE-CRT-06, FE-CRT-07, FE-Q20)', () => {
  it('클라이언트 검증 오류는 요청 없이 입력칸에 보인다', async () => {
    let posted = false;
    server.use(
      http.post('*/plans', () => {
        posted = true;
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    await startManual();
    fireEvent.click(screen.getByRole('button', { name: '이 하루 공개하기' }));
    expect(await screen.findByText('1–40자로 입력해 주세요.')).toBeInTheDocument();
    expect(screen.getByText('장소는 1–3곳이어야 해요.')).toBeInTheDocument();
    expect(screen.getByLabelText('하루 제목')).toHaveAttribute('aria-invalid', 'true');
    expect(posted).toBe(false);
  });

  it('장소 추가 → 고치기 → 빼기, 3곳이면 추가 버튼이 사라진다', async () => {
    await startManual();
    for (const name of ['빵집', '하천 벤치', '공원']) {
      fireEvent.click(screen.getByRole('button', { name: '+ 장소 추가' }));
      await fillPlace(name, '들르기');
      fireEvent.click(screen.getByRole('button', { name: '동선에 추가하기' }));
      await screen.findByTestId('screen-3-2');
    }
    expect(screen.queryByRole('button', { name: '+ 장소 추가' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '2번 장소 고치기' }));
    await screen.findByTestId('screen-3-3');
    expect(screen.getByLabelText('장소 이름')).toHaveValue('하천 벤치');
    type('장소 이름', '하천 산책로 벤치');
    fireEvent.click(screen.getByRole('button', { name: '저장하기' }));
    await screen.findByTestId('screen-3-2');
    expect(within(screen.getByTestId('place-1')).getByText('하천 산책로 벤치')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '1번 장소 빼기' }));
    expect(loadDraft()?.form.places.map((p) => p.name)).toEqual(['하천 산책로 벤치', '공원']);
    expect(screen.getByRole('button', { name: '+ 장소 추가' })).toBeInTheDocument();
  });

  it('장소 입력 검증: 이름·하고 싶었던 일은 필수', async () => {
    await startManual();
    fireEvent.click(screen.getByRole('button', { name: '+ 장소 추가' }));
    await screen.findByTestId('screen-3-3');
    fireEvent.click(screen.getByRole('button', { name: '동선에 추가하기' }));
    expect(await screen.findByText('1–30자로 입력해 주세요.')).toBeInTheDocument();
    expect(screen.getByText('1–60자로 입력해 주세요.')).toBeInTheDocument();
  });

  it('새로고침(다시 렌더)해도 폼 값과 startedAt이 유지된다(FE-CRT-08)', async () => {
    await startManual();
    await fillForm();
    const startedAt = loadDraft()?.startedAt;
    cleanup();
    renderApp('/plans/new/form', 'u-jiyeon');
    await screen.findByTestId('screen-3-2');
    expect(screen.getByLabelText('하루 제목')).toHaveValue('이사 전, 마지막 동네 산책');
    expect(within(screen.getByTestId('place-0')).getByText('출근길 빵집')).toBeInTheDocument();
    expect(loadDraft()?.startedAt).toBe(startedAt);
  });
});

describe('공개(FE-CRT-09–11)', () => {
  it('공개 → 3-4 → 초안 삭제, 본문에 authoring, 둘러보기 맨 앞', async () => {
    const sent: { value: { body: CreatePlanRequest; key: string | null } | null } = { value: null };
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/plans')) {
        sent.value = {
          body: (await request.clone().json()) as CreatePlanRequest,
          key: request.headers.get('Idempotency-Key'),
        };
      }
    });
    const { router } = await startManual();
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: '이 하루 공개하기' }));

    await screen.findByTestId('screen-3-4');
    expect(screen.getByText('하루를 공개했어요')).toBeInTheDocument();
    expect(screen.getByText('약 45분 · 장소 1곳')).toBeInTheDocument();
    expect(router.state.location.pathname).toMatch(/^\/plans\/pln_[A-Z0-9]+\/published$/);
    expect(loadDraft()).toBeNull();
    server.events.removeAllListeners();

    await waitFor(() => expect(sent.value).not.toBeNull());
    const { body, key } = sent.value!;
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(body.authoring).toMatchObject({ mode: 'MANUAL', story: STORY });
    expect(body.authoring).not.toHaveProperty('aiSessionId');
    expect(body.authoring.durationMs).toBeGreaterThanOrEqual(0);
    expect(body.estimatedMinutes).toBe(45);

    const created = loadDb().plans.find(
      (p) => p.title === '이사 전, 마지막 동네 산책' && p.status === 'OPEN' && p.planId !== 'pln_demo',
    );
    expect(created?.metrics.authoringMode).toBe('MANUAL');

    fireEvent.click(screen.getByRole('button', { name: '둘러보기로 가기' }));
    const list = await screen.findByTestId('plan-list');
    expect(within(list).getAllByRole('link')[0]).toHaveAttribute('href', `/plans/${created?.planId}`);
  });

  it('공개 완료 화면을 새로고침하면 GET /plans/{planId}로 다시 읽는다(FE-Q2)', async () => {
    renderApp('/plans/pln_demo/published', 'u-jiyeon');
    expect(await screen.findByText('이사 전, 마지막 동네 산책')).toBeInTheDocument();
  });

  it('서버 VALIDATION_ERROR details를 같은 입력칸에 보여 준다', async () => {
    server.use(
      http.post('*/plans', () =>
        HttpResponse.json(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: '',
              details: { title: '서버가 거절한 제목', 'places[0].name': '서버가 거절한 장소' },
            },
          },
          { status: 400 },
        ),
      ),
    );
    await startManual();
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: '이 하루 공개하기' }));
    expect(await screen.findByText('서버가 거절한 제목')).toBeInTheDocument();
    expect(within(screen.getByTestId('place-0')).getByText('서버가 거절한 장소')).toBeInTheDocument();
    expect(loadDraft()).not.toBeNull();
  });

  it('409 IDEMPOTENCY_CONFLICT면 새 키로 한 번 다시 보낸다', async () => {
    const keys: (string | null)[] = [];
    server.use(
      http.post('*/plans', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        if (keys.length === 1) {
          return HttpResponse.json({ error: { code: 'IDEMPOTENCY_CONFLICT', message: '' } }, { status: 409 });
        }
        return undefined; // 기본 목업 핸들러로 넘긴다
      }),
    );
    await startManual();
    await fillForm();
    fireEvent.click(screen.getByRole('button', { name: '이 하루 공개하기' }));
    await screen.findByTestId('screen-3-4');
    expect(keys).toHaveLength(2);
    expect(keys[1]).not.toBe(keys[0]);
  });

  it('실패 뒤 같은 내용으로 다시 누르면 같은 키를 쓴다(FE-CRT-10)', async () => {
    const keys: (string | null)[] = [];
    server.use(
      http.post('*/plans', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        return HttpResponse.json({ error: { code: 'INTERNAL_ERROR', message: '' } }, { status: 500 });
      }),
    );
    await startManual();
    await fillForm();
    const button = screen.getByRole('button', { name: '이 하루 공개하기' });
    fireEvent.click(button);
    await waitFor(() => expect(keys).toHaveLength(1));
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[1]).toBe(keys[0]);

    await waitFor(() => expect(button).toBeEnabled());
    type('하루 제목', '바뀐 제목');
    fireEvent.click(button);
    await waitFor(() => expect(keys).toHaveLength(3));
    expect(keys[2]).not.toBe(keys[0]);
  });
});
