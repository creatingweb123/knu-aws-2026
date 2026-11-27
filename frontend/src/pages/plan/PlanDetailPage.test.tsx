import { fireEvent, screen, waitFor } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';

import { loadDb, resetDb, updateDb } from '../../mocks/db';
import { claimPlan } from '../../mocks/handlers/plans';
import { server } from '../../test/server';
import { renderApp } from '../../test/renderApp';

const claimButton = () => screen.findByRole('button', { name: '이 하루 이어받기' });

describe('하루 상세 내용(FE-PLN-01)', () => {
  it('계획자·취소한 이유·동선(장소·하고 싶었던 일·고른 이유)', async () => {
    renderApp('/plans/pln_demo', 'u-suhyun');
    expect(await screen.findByText('지연 · 취소한 이유')).toBeInTheDocument();
    expect(screen.getByText(/이삿짐 정리가 길어져/)).toBeInTheDocument();
    expect(screen.getByText('출근길 빵집')).toBeInTheDocument();
    expect(screen.getByText('들러서 빵 사기')).toBeInTheDocument();
    expect(screen.getByText('출근길에 지나치던 곳이에요.')).toBeInTheDocument();
    expect(screen.getByText('약 45분 · 장소 2곳')).toBeInTheDocument();
  });
});

describe('상세 분기(FE-PLN-02)', () => {
  it('없는 하루 → "이 하루는 더 이상 볼 수 없어요"', async () => {
    renderApp('/plans/pln_none', 'u-suhyun');
    expect(await screen.findByText('이 하루는 더 이상 볼 수 없어요')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '둘러보기로 가기' })).toBeInTheDocument();
  });

  it('남의 완료된 하루도 404라 같은 안내(민준 → pln_bridge)', async () => {
    renderApp('/plans/pln_bridge', 'u-minjun');
    expect(await screen.findByText('이 하루는 더 이상 볼 수 없어요')).toBeInTheDocument();
  });

  it('내가 이어받은 하루(민준 → pln_market): 배지 + 내 하루로 가기', async () => {
    const { router } = renderApp('/plans/pln_market', 'u-minjun');
    const go = await screen.findByRole('button', { name: '내 하루로 가기' });
    expect(screen.getByTestId('detail-badges')).toHaveTextContent('내가 이어받은 하루');
    fireEvent.click(go);
    await waitFor(() => expect(router.state.location.pathname).toBe('/me'));
  });

  it('내가 남긴 하루(지연 → pln_market): 배지 + 상태(이어받음), 버튼 없음', async () => {
    renderApp('/plans/pln_market', 'u-jiyeon');
    await screen.findByText('지연 · 취소한 이유');
    const badges = screen.getByTestId('detail-badges');
    expect(badges).toHaveTextContent('내가 남긴 하루');
    expect(badges).toHaveTextContent('이어받음');
    expect(screen.queryByRole('button', { name: '이 하루 이어받기' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('claimed-notice')).not.toBeInTheDocument();
  });

  it('내가 남긴 OPEN 하루는 "공개" 상태', async () => {
    renderApp('/plans/pln_demo', 'u-jiyeon');
    await screen.findByText('지연 · 취소한 이유');
    expect(screen.getByTestId('detail-badges')).toHaveTextContent('공개');
  });

  it('이어받을 수 있는 하루(수현 → pln_demo): 이어받기 버튼', async () => {
    renderApp('/plans/pln_demo', 'u-suhyun');
    expect(await claimButton()).toBeEnabled();
    expect(screen.getByTestId('detail-badges')).toHaveTextContent('이어받기 가능');
  });

  it('남이 이어받은 하루(수현 → pln_market): 2-1 안내', async () => {
    const { router } = renderApp('/plans/pln_market', 'u-suhyun');
    const notice = await screen.findByTestId('claimed-notice');
    expect(notice).toHaveTextContent('이미 다른 사람이 이어받았어요');
    expect(screen.getByTestId('screen-2-1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다른 하루 둘러보기' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
  });

  it('내가 완료한 하루(수현 → pln_bridge): 완료 배지, 버튼 없음', async () => {
    renderApp('/plans/pln_bridge', 'u-suhyun');
    await screen.findByText('지연 · 취소한 이유');
    expect(screen.getByTestId('detail-badges')).toHaveTextContent('완료');
    for (const name of ['이 하루 이어받기', '내 하루로 가기', '다른 하루 둘러보기'])
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
  });
});

describe('이어받기(FE-PLN-03–05)', () => {
  it('성공하면 /me로 이동하고 목업 DB에 내 이어받기가 생긴다', async () => {
    resetDb();
    const { router } = renderApp('/plans/pln_demo', 'u-suhyun');
    fireEvent.click(await claimButton());
    await waitFor(() => expect(router.state.location.pathname).toBe('/me'));
    const plan = loadDb().plans.find((p) => p.planId === 'pln_demo');
    expect(plan).toMatchObject({ status: 'CLAIMED', claimerId: 'u-suhyun' });
  });

  it('요청 중에는 버튼이 비활성화된다', async () => {
    let release: () => void = () => undefined;
    server.use(
      http.post('*/plans/:planId/claims', async () => {
        await new Promise<void>((r) => (release = r));
        return HttpResponse.json({ error: { code: 'ALREADY_CLAIMED', message: '' } }, { status: 409 });
      }),
    );
    renderApp('/plans/pln_demo', 'u-suhyun');
    const button = await claimButton();
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    release();
    expect(await screen.findByTestId('claimed-notice')).toBeInTheDocument();
  });

  it('409 ALREADY_CLAIMED면 이동 없이 같은 화면에 2-1 안내(?mock=claim-conflict)', async () => {
    sessionStorage.setItem('haru.mock.scenario', 'claim-conflict');
    const { router } = renderApp('/plans/pln_demo', 'u-suhyun');
    fireEvent.click(await claimButton());
    expect(await screen.findByTestId('claimed-notice')).toHaveTextContent('이미 다른 사람이 이어받았어요');
    expect(router.state.location.pathname).toBe('/plans/pln_demo');
    expect(screen.queryByRole('button', { name: '이 하루 이어받기' })).not.toBeInTheDocument();
  });

  it('다른 사용자가 먼저 이어받은 뒤 누르면 2-1 안내(두 탭 경합)', async () => {
    resetDb();
    const { router } = renderApp('/plans/pln_demo', 'u-minjun');
    const button = await claimButton();
    // 다른 탭의 수현이 먼저 이어받는다(같은 localStorage DB)
    updateDb((db) => claimPlan(db, 'pln_demo', { userId: 'u-suhyun', nickname: '수현' }, Date.now()));
    fireEvent.click(button);
    expect(await screen.findByTestId('claimed-notice')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/plans/pln_demo');
  });

  it('409 CANNOT_CLAIM_OWN_PLAN은 토스트', async () => {
    server.use(
      http.post('*/plans/:planId/claims', () =>
        HttpResponse.json(
          { error: { code: 'CANNOT_CLAIM_OWN_PLAN', message: '내가 남긴 하루는 이어받을 수 없어요.' } },
          { status: 409 },
        ),
      ),
    );
    renderApp('/plans/pln_demo', 'u-suhyun');
    fireEvent.click(await claimButton());
    expect(await screen.findByText('내가 남긴 하루는 이어받을 수 없어요.')).toBeInTheDocument();
    expect(screen.queryByTestId('claimed-notice')).not.toBeInTheDocument();
  });
});
