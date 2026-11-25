import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';

import { setUnauthorizedHandler } from '../api/client';
import { setTokenProvider } from '../auth/tokens';
import { server } from './server';

// jsdom은 location.assign 이동을 지원하지 않는다. 401 이동은 테스트마다 필요하면 바꿔 확인한다
const noRedirect = () => undefined;

// 테스트 파일을 병렬로 돌리면 첫 렌더·첫 요청이 1초(기본값)를 넘길 때가 있어 findBy/waitFor 대기를 늘린다
configure({ asyncUtilTimeout: 5000 });

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => setUnauthorizedHandler(noRedirect));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  setTokenProvider(null);
  localStorage.clear();
  sessionStorage.clear();
});
afterAll(() => server.close());
