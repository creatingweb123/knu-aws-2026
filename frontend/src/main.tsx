import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { config } from './config';
import './styles/global.css';

async function start() {
  // 목업 모드에서만 MSW를 불러온다(FE-TECH-04). 그 외에는 번들에 들어가지 않는다
  if (config.useMock) {
    const { startMockWorker } = await import('./mocks/browser');
    await startMockWorker();
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
