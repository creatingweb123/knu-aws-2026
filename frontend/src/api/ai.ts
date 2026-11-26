/**
 * AI 하루 카드 정리 세션 API(docs/03 §3.2). HTTP 요청 1번이 에이전트 1턴이다.
 * 서버는 30초 안에 정해진 코드로 응답하므로 클라이언트 타임아웃은 그보다 긴 35초(FE-CRT-04, FE-Q25).
 */
import { request } from './client';
import type { SessionView, TurnRequest } from './types';

export const AI_TIMEOUT_MS = 35_000;

export function startSession(story: string) {
  return request<SessionView>('/ai/card-sessions', {
    method: 'POST',
    body: { story },
    timeoutMs: AI_TIMEOUT_MS,
  });
}

export function sendTurn(sessionId: string, body: TurnRequest) {
  return request<SessionView>(`/ai/card-sessions/${encodeURIComponent(sessionId)}/turns`, {
    method: 'POST',
    body,
    timeoutMs: AI_TIMEOUT_MS,
  });
}

export function getSession(sessionId: string) {
  return request<SessionView>(`/ai/card-sessions/${encodeURIComponent(sessionId)}`, {
    timeoutMs: AI_TIMEOUT_MS,
  });
}
