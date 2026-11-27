/** 경로별 목업 핸들러 */
import { aiHandlers } from './ai';
import { claimHandlers } from './claims';
import { inboxHandlers } from './inbox';
import { meHandlers } from './me';
import { planHandlers } from './plans';

// MSW는 경로 전체로 맞추므로 `/me/claims`와 `/me`의 순서는 상관없다
export const handlers = [...meHandlers, ...claimHandlers, ...planHandlers, ...inboxHandlers, ...aiHandlers];
