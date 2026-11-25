import { setupWorker } from 'msw/browser';

import { handlers } from './handlers';
import { captureScenarioFromUrl } from './session';

export async function startMockWorker(): Promise<void> {
  captureScenarioFromUrl();
  const worker = setupWorker(...handlers);
  await worker.start({ onUnhandledRequest: 'bypass', quiet: true });
}
