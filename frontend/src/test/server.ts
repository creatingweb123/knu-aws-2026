import { setupServer } from 'msw/node';

import { handlers } from '../mocks/handlers';

/** 테스트는 앱과 같은 MSW 핸들러를 Node에서 쓴다 */
export const server = setupServer(...handlers);
