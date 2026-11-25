import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { setTokenProvider } from './auth/tokens';
import { ToastProvider } from './components/Toast';
import { mockTokenFor } from './mocks/session';
import { createQueryClient } from './queryClient';
import { SCREENS, routes } from './routes';

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return router;
}

const sample = (path: string) =>
  path.replace(':planId', 'pln_demo').replace(':claimId', 'clm_x').replace(':itemId', 'clm_y');

describe('라우트 골격(docs/05 §5.1)', () => {
  it('경로 표는 15개 화면 + /login + 404 = 17개', () => {
    expect(SCREENS).toHaveLength(15);
  });

  it.each(SCREENS.map((s) => [s.screen, s.path]))('화면 %s (%s)가 열린다', async (screenNo, path) => {
    setTokenProvider(async () => mockTokenFor('u-suhyun'));
    renderAt(sample(path));
    expect(await screen.findByTestId(`screen-${screenNo}`)).toBeInTheDocument();
  });

  it('/plans/new는 상세(/plans/:planId)가 아니라 사연 입력으로 간다', async () => {
    setTokenProvider(async () => mockTokenFor('u-suhyun'));
    renderAt('/plans/new');
    expect(await screen.findByTestId('screen-3')).toBeInTheDocument();
  });

  it('/login은 토큰 없이 열린다', async () => {
    setTokenProvider(async () => null);
    renderAt('/login');
    expect(await screen.findByTestId('screen-0')).toBeInTheDocument();
  });

  it('모르는 경로는 404 안내', async () => {
    setTokenProvider(async () => mockTokenFor('u-suhyun'));
    renderAt('/nope');
    expect(await screen.findByText('찾을 수 없어요')).toBeInTheDocument();
  });

  it('토큰이 없으면 /login?redirect=현재 경로로 보낸다(FE-AUTH-03)', async () => {
    setTokenProvider(async () => null);
    const router = renderAt('/inbox/clm_y');
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(router.state.location.search).toBe(`?redirect=${encodeURIComponent('/inbox/clm_y')}`);
  });
});

describe('레이아웃(FE-COM-01, FE-COM-02, FE-Q12)', () => {
  it('하단 탭은 목록형 화면에만 보인다', async () => {
    setTokenProvider(async () => mockTokenFor('u-suhyun'));
    renderAt('/me');
    await screen.findByTestId('screen-4');
    expect(screen.getByRole('navigation', { name: '주요 화면' })).toBeInTheDocument();
  });

  it('상세 화면에는 하단 탭이 없다', async () => {
    setTokenProvider(async () => mockTokenFor('u-suhyun'));
    renderAt('/plans/pln_demo');
    await screen.findByTestId('screen-2');
    expect(screen.queryByRole('navigation', { name: '주요 화면' })).not.toBeInTheDocument();
  });

  it('안 읽은 편지가 있으면 편지 아이콘에 점을 표시한다(지연)', async () => {
    setTokenProvider(async () => mockTokenFor('u-jiyeon'));
    renderAt('/');
    expect(await screen.findByTestId('unread-dot')).toBeInTheDocument();
  });

  it('안 읽은 편지가 없으면 점이 없다(민준)', async () => {
    setTokenProvider(async () => mockTokenFor('u-minjun'));
    renderAt('/');
    await screen.findByTestId('plan-count');
    expect(screen.queryByTestId('unread-dot')).not.toBeInTheDocument();
  });

  it('둘러보기는 GET /plans 목업 응답 건수를 보여준다', async () => {
    setTokenProvider(async () => mockTokenFor('u-suhyun'));
    renderAt('/');
    expect(await screen.findByTestId('plan-count')).toHaveTextContent('2개');
  });
});
