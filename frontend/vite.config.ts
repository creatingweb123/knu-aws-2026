import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  css: {
    modules: { localsConvention: 'camelCaseOnly' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
    restoreMocks: true,
    // 화면 흐름 테스트는 여러 화면을 오가므로 기본 5초보다 길게 둔다(findBy 대기 5초, src/test/setup.ts)
    testTimeout: 30_000,
  },
});
