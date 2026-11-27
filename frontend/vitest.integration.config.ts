/**
 * API 통합 테스트 설정(7b Phase 3). 실제 백엔드에 HTTP로 요청하므로 jsdom과 MSW를 쓰지 않는다.
 * 실행: `npm run test:integration`. 대상 백엔드는 `.env.local`의 `VITE_API_BASE_URL`이다.
 * 기본 `npm test`는 이 파일과 `tests/integration/`을 제외한다(vite.config.ts).
 */
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/integration/**/*.test.ts'],
    testTimeout: 15_000,
    // 같은 백엔드와 같은 사용자 데이터를 쓰므로 파일을 병렬로 돌리지 않는다
    fileParallelism: false,
  },
});
