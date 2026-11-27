/**
 * 받은 SessionView로 다음 행동을 정한다(FE-CRT-02, 12, 13, docs/02 §2.10 `decideAiNextStep`).
 * - WORKING: 자동으로 turns. 연속 2회부터(또는 finish 요청·예약이 있으면) finish: true
 * - ASKING: 사용자 입력 대기. finish 예약이 있으면 바로 finish turns(답변 없이 = 현재 질문 건너뜀)
 * - READY: 카드 표시, FAILED: 실패 처리
 * `consecutiveWorking`은 이 응답을 받기 전까지의 연속 WORKING 수다. 같은 턴 재동기화 GET은 세지 않는다(호출자가 거른다).
 */
import type { SessionView } from '../../../api/types';

export type AiNextStep =
  | { next: 'turn'; finish: boolean; consecutiveWorking: number }
  | { next: 'ask'; consecutiveWorking: 0 }
  | { next: 'ready'; consecutiveWorking: 0 }
  | { next: 'failed'; consecutiveWorking: 0 };

export const FINISH_AFTER_WORKING = 2;

export function decideAiNextStep(
  view: Pick<SessionView, 'status'>,
  consecutiveWorking: number,
  finishRequested: boolean,
): AiNextStep {
  switch (view.status) {
    case 'WORKING': {
      const count = consecutiveWorking + 1;
      return {
        next: 'turn',
        finish: finishRequested || count >= FINISH_AFTER_WORKING,
        consecutiveWorking: count,
      };
    }
    case 'ASKING':
      return finishRequested
        ? { next: 'turn', finish: true, consecutiveWorking: 0 }
        : { next: 'ask', consecutiveWorking: 0 };
    case 'READY':
      return { next: 'ready', consecutiveWorking: 0 };
    default:
      return { next: 'failed', consecutiveWorking: 0 };
  }
}
