import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderApp } from '../../test/renderApp';

describe('둘러보기(FE-BRW-01–04)', () => {
  it('OPEN 하루를 최신순 카드로: 배지·제목·요약·약 n분 · 장소 k곳', async () => {
    renderApp('/', 'u-suhyun');
    const list = await screen.findByTestId('plan-list');
    const cards = within(list).getAllByRole('link');
    expect(cards).toHaveLength(6); // 데모 2건 + 산책이 아닌 활동 예시 4건
    expect(cards[0]).toHaveAttribute('href', '/plans/pln_demo');
    expect(cards[0]).toHaveTextContent('이어받기 가능');
    expect(cards[0]).toHaveTextContent('이사 전, 마지막 동네 산책');
    expect(cards[0]).toHaveTextContent('출근길 빵집에 들르고');
    expect(cards[0]).toHaveTextContent('약 45분 · 장소 2곳');
    expect(cards[1]).toHaveAttribute('href', '/plans/pln_library');
  });

  it('산책이 아닌 일상 활동(카페·전시·서점·공원 사진)도 같은 카드로, 장소 1곳도 자연스럽다', async () => {
    renderApp('/', 'u-suhyun');
    const list = await screen.findByTestId('plan-list');
    const exhibit = within(list).getByText('끝나기 전에 보고 싶던 전시').closest('a')!;
    expect(exhibit).toHaveTextContent('약 60분 · 장소 1곳');
    expect(within(list).getByText('친구와 가려던 골목 카페')).toBeInTheDocument();
    expect(within(list).getByText('이사 전에 들르려던 동네 서점')).toBeInTheDocument();
    expect(within(list).getByText('벚나무 아래 공원 사진')).toBeInTheDocument();
  });

  it('내가 남긴 하루도 같은 카드로 보인다(지연)', async () => {
    renderApp('/', 'u-jiyeon');
    const list = await screen.findByTestId('plan-list');
    expect(within(list).getByText('이사 전, 마지막 동네 산책')).toBeInTheDocument();
  });

  it('카드를 누르면 상세로 간다', async () => {
    const { router } = renderApp('/', 'u-suhyun');
    const list = await screen.findByTestId('plan-list');
    fireEvent.click(within(list).getAllByRole('link')[0]);
    await waitFor(() => expect(router.state.location.pathname).toBe('/plans/pln_demo'));
  });

  it('목록이 비면 빈 상태 안내(?mock=browse-empty)', async () => {
    sessionStorage.setItem('haru.mock.scenario', 'browse-empty');
    renderApp('/', 'u-suhyun');
    expect(await screen.findByTestId('browse-empty')).toHaveTextContent('아직 남겨진 하루가 없어요');
    expect(screen.getByTestId('browse-empty')).toHaveTextContent('하지 못한 하루가 있다면 첫 하루를 남겨 보세요.');
    expect(screen.getByTestId('browse-empty')).not.toHaveTextContent('산책');
    expect(screen.queryByTestId('plan-list')).not.toBeInTheDocument();
  });

  it('"취소된 하루 남기기"는 사연 입력으로 간다(FE-BRW-03)', async () => {
    const { router } = renderApp('/', 'u-suhyun');
    fireEvent.click(await screen.findByRole('button', { name: '취소된 하루 남기기' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/plans/new'));
  });
});
