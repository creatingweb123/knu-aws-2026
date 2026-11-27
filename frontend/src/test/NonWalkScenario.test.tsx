/**
 * 산책이 아닌 일상 활동(전시 한 곳)도 같은 흐름을 타는지 확인한다.
 * 이어온 하루의 본질은 취소된 하루의 양도와 반환이고, 동네 산책(데모 시나리오)은 대표 사례일 뿐이다.
 * 그래서 데모 계획이 아닌 흐름의 화면에는 '산책'이 새어 나오면 안 된다.
 */
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { loadDraft } from '../state/planDraft';
import { loadDb } from '../mocks/db';
import { renderApp } from './renderApp';

const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
const noWalk = () => expect(document.body).not.toHaveTextContent(/산책|동선/);

const STORY = '이번 주에 끝나는 시립 미술관 사진 전시를 보려 했는데 몸이 안 좋아 못 갔어요.';

describe('산책이 아닌 사연(전시 한 곳)', () => {
  it('AI 정리 → 카드(장소 1곳) → 폼 → 공개', async () => {
    const { router } = renderApp('/plans/new', 'u-jiyeon');
    await screen.findByTestId('screen-3');
    noWalk();
    expect(screen.getByLabelText('사연')).toHaveAttribute('placeholder', expect.stringContaining('서점'));
    type('사연', STORY);
    click('AI와 함께 정리하기');
    const card = await screen.findByTestId('card-preview');
    expect(card).toHaveTextContent('끝나기 전에 보고 싶던 전시');
    expect(card).toHaveTextContent('시립 미술관 작은 전시실');
    expect(card).toHaveTextContent('방문할 장소');
    noWalk();

    click('폼에서 다듬기');
    await screen.findByTestId('screen-3-2');
    expect(loadDraft()?.form.places).toHaveLength(1);
    type('예상 소요 시간(분)', '60');
    noWalk();
    click('이 하루 공개하기');
    await screen.findByTestId('screen-3-4');
    const planId = router.state.location.pathname.split('/')[2];
    expect(loadDb().plans.find((p) => p.planId === planId)?.places).toHaveLength(1);
    noWalk();
  }, 60_000);

  it('상세 → 이어받기 → 경험 기록 → 수신함·답장까지 산책 표현이 없다', async () => {
    const browse = renderApp('/', 'u-suhyun');
    const list = await screen.findByTestId('plan-list');
    fireEvent.click(within(list).getByText('끝나기 전에 보고 싶던 전시').closest('a')!);
    await screen.findByRole('button', { name: '이 하루 이어받기' });
    expect(screen.getByText('약 60분 · 장소 1곳')).toBeInTheDocument();
    noWalk();
    click('이 하루 이어받기');
    await waitFor(() => expect(browse.router.state.location.pathname).toBe('/me'));
    cleanup();

    const me = renderApp('/me', 'u-suhyun');
    const myCard = (await screen.findByText('끝나기 전에 보고 싶던 전시')).closest('li')!;
    noWalk();
    fireEvent.click(within(myCard).getByRole('button', { name: '다녀온 이야기 쓰기' }));
    await screen.findByText('지연에게');
    noWalk();
    type('다녀온 이야기', '작은 전시실 안쪽 흑백 사진 앞에 가장 오래 서 있었어요.');
    click('글로 완료하기');
    expect(await screen.findByText('경험 기록을 보냈어요')).toBeInTheDocument();
    noWalk();
    await waitFor(() => expect(me.router.state.location.pathname).toMatch(/done$/));
    cleanup();

    renderApp('/inbox', 'u-jiyeon');
    const row = within(await screen.findByTestId('inbox-list'))
      .getByText('끝나기 전에 보고 싶던 전시')
      .closest('a')!;
    expect(row).toHaveTextContent('수현님이 경험 기록을 보냈어요');
    fireEvent.click(row);
    expect(await screen.findByText(/흑백 사진/)).toBeInTheDocument();
    noWalk();
  }, 120_000);

  it('이미 이어받은 하루 안내도 산책으로 한정하지 않는다', async () => {
    renderApp('/plans/pln_market', 'u-suhyun');
    expect(await screen.findByTestId('claimed-notice')).toHaveTextContent('이어받을 하루를 골라');
    noWalk();
  });
});
