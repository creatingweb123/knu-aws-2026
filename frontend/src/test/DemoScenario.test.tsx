/**
 * 90초 시연 시나리오(docs/01 §1.7) 글 경로를 목업에서 처음부터 끝까지 돌린다(docs/07 §7.4 4단계 완료 조건).
 * 사진(3번의 사진)은 5단계, AI 정리(1번의 질문 답하기)는 6단계에서 더한다.
 */
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderApp } from './renderApp';

const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));

describe('시연 시나리오(글 경로)', () => {
  it('지연 공개 → 수현·민준 경합 → 수현 경험 기록 → 지연 수신함·답장', async () => {
    // 1. 지연이 사연을 쓰고 직접 정리해 공개한다
    const create = renderApp('/plans/new', 'u-jiyeon');
    await screen.findByTestId('screen-3');
    type('사연', '이사 전에 시장 골목을 마지막으로 걷고 싶었어요. 떡집에서 인절미를 사려고 했어요.');
    click('직접 작성하기');
    await screen.findByTestId('screen-3-2');
    type('하루 제목', '이사 전, 시장 골목 산책');
    type('취소한 이유', '이삿짐 정리가 길어졌어요.');
    type('예상 소요 시간(분)', '30');
    type('방문 질문', '떡집 앞은 어떤 냄새가 났나요?');
    click('장소 추가하기');
    await screen.findByTestId('screen-3-3');
    type('장소 이름', '시장 떡집');
    type('하고 싶었던 일', '인절미 사기');
    click('장소 추가하기');
    await screen.findByTestId('screen-3-2');
    click('이 하루 공개하기');
    await screen.findByTestId('screen-3-4');
    const planPath = create.router.state.location.pathname.replace(/\/published$/, '');
    expect(planPath).toMatch(/^\/plans\/pln_[A-Z0-9]+$/);
    cleanup();

    // 2. 수현과 민준이 같은 하루를 이어받으려 한다. 수현이 먼저, 민준은 2-1 안내
    const browse = renderApp('/', 'u-suhyun');
    const list = await screen.findByTestId('plan-list');
    const card = within(list).getByText('이사 전, 시장 골목 산책').closest('a')!;
    const href = card.getAttribute('href')!;
    expect(href).toBe(planPath);
    fireEvent.click(card);
    await screen.findByRole('button', { name: '이 하루 이어받기' });
    click('이 하루 이어받기');
    await waitFor(() => expect(browse.router.state.location.pathname).toBe('/me'));
    cleanup();

    renderApp(href, 'u-minjun');
    expect(await screen.findByTestId('claimed-notice')).toHaveTextContent('이미 다른 사람이 이어받았어요');
    cleanup();

    // 3. 수현이 내 하루에서 경험 기록을 쓰고 글로 완료한다
    renderApp('/me', 'u-suhyun');
    const myCard = (await screen.findByText('이사 전, 시장 골목 산책')).closest('li')!;
    fireEvent.click(within(myCard).getByRole('button', { name: '다녀온 이야기 쓰기' }));
    await screen.findByText('지연에게');
    type('다녀온 이야기', '떡집 앞은 고소한 콩고물 냄새가 났어요. 인절미 한 팩을 샀어요.');
    click('글로 완료하기');
    expect(await screen.findByText('경험 기록을 보냈어요')).toBeInTheDocument();
    cleanup();

    // 4. 지연이 수신함에서 돌아온 하루를 읽고 답장한다
    renderApp('/inbox', 'u-jiyeon');
    const inbox = await screen.findByTestId('inbox-list');
    const row = within(inbox).getByText('이사 전, 시장 골목 산책').closest('a')!;
    expect(row).toHaveTextContent('새 편지');
    expect(row).toHaveTextContent('수현님이 경험 기록을 보냈어요');
    fireEvent.click(row);
    expect(await screen.findByText(/고소한 콩고물 냄새/)).toBeInTheDocument();
    type('한 줄 답장', '덕분에 마지막 산책을 한 것 같아요. 고마워요.');
    click('답장 보내기');
    expect(await screen.findByTestId('sent-reply')).toHaveTextContent('고마워요');
  }, 120_000);
});
