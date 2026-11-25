/** 경로별 목업 핸들러. AI 세션(6단계)·사진(5단계)은 그 단계에서 추가한다. */
import { claimHandlers } from './claims';
import { inboxHandlers } from './inbox';
import { meHandlers } from './me';
import { planHandlers } from './plans';

// `/me/claims`가 `/me`보다 구체적이지만 MSW는 경로 전체로 맞추므로 순서는 상관없다
export const handlers = [...meHandlers, ...claimHandlers, ...planHandlers, ...inboxHandlers];
