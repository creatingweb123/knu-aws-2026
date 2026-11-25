/** 경로별 목업 핸들러. 1단계는 /me, /plans, /plans/{planId}. 나머지는 2–6단계에서 추가한다. */
import { meHandlers } from './me';
import { planHandlers } from './plans';

export const handlers = [...meHandlers, ...planHandlers];
