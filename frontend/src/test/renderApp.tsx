import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { RouterProvider, createMemoryRouter } from 'react-router-dom';

import { setTokenProvider } from '../auth/tokens';
import { ToastProvider } from '../components/Toast';
import { mockTokenFor } from '../mocks/session';
import { createQueryClient } from '../queryClient';
import { routes } from '../routes';

/** 앱 라우트 전체를 메모리 라우터로 그린다. `userId`를 주면 그 목업 사용자로 요청한다 */
export function renderApp(path: string, userId?: string) {
  if (userId) setTokenProvider(async () => mockTokenFor(userId));
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const utils = render(
    <QueryClientProvider client={createQueryClient()}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { router, ...utils };
}
