/**
 * AI 정리 세션의 턴 진행 엔진(FE-CRT-02, 12, 13, docs/02 §2.10 `useAiSession`).
 * 받은 SessionView마다 `decideAiNextStep`으로 다음 요청을 정하고, BUSY·CLOSED·네트워크 오류는 GET으로 재동기화한다.
 * 화면 상태 저장(sessionId·turn·카드)과 실패 이동은 호출자 콜백(onView, onFailed)이 한다.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { getSession, sendTurn, startSession } from '../../../api/ai';
import { isApiError } from '../../../api/client';
import type { AiAnswer, SessionView, TurnRequest } from '../../../api/types';
import { useToast } from '../../../components/useToast';
import { decideAiNextStep } from './aiNextStep';

export const RESYNC_DELAY_MS = 2000;
/** 같은 턴의 WORKING이 이 시간 넘게 계속되면 turns를 다시 보낸다(서버 잠금 30초) */
export const LOCK_MS = 30_000;

interface Options {
  story: string;
  sessionId: string | null;
  /** 저장된 READY 카드가 있으면 요청 없이 이 view로 시작한다 */
  readyView: SessionView | null;
  onView: (view: SessionView) => void;
  onFailed: () => void;
}

export function useAiSession({ story, sessionId, readyView, onView, onFailed }: Options) {
  const toast = useToast();
  const [view, setView] = useState<SessionView | null>(readyView);
  const [busy, setBusy] = useState(false);
  const [finishReserved, setFinishReserved] = useState(false);

  const alive = useRef(true);
  const started = useRef(false);
  const consecutive = useRef(0);
  const reserved = useRef(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const callbacks = useRef({ onView, onFailed, toast });
  useEffect(() => {
    callbacks.current = { onView, onFailed, toast };
  });

  const later = (ms: number, fn: () => void) => {
    timers.current.push(
      setTimeout(() => {
        if (alive.current) fn();
      }, ms),
    );
  };

  const reserve = () => {
    reserved.current = true;
    setFinishReserved(true);
  };

  const fail = () => {
    if (!alive.current) return;
    setBusy(false);
    callbacks.current.onFailed();
  };

  const handle = (v: SessionView) => {
    if (!alive.current) return;
    setView(v);
    callbacks.current.onView(v);
    const step = decideAiNextStep(v, consecutive.current, reserved.current);
    consecutive.current = step.consecutiveWorking;
    if (step.next === 'turn') {
      if (step.finish) reserve();
      void turn(v, {});
      return;
    }
    setBusy(false);
    if (step.next === 'failed') fail();
  };

  /** 재동기화 GET 한 번. 실패하면 직접 작성으로(FE-CRT-04) */
  const resyncOnce = async (sid: string) => {
    setBusy(true);
    try {
      handle(await getSession(sid));
    } catch (e) {
      if (isApiError(e) && e.code === 'UNAUTHORIZED') return;
      fail();
    }
  };

  /** BUSY 뒤 재동기화: 같은 턴의 WORKING이면 2초 간격 반복(연속 횟수에 넣지 않음), 30초 넘으면 turns 재전송 */
  const resyncWhileLocked = async (sid: string, sentTurn: number, since: number) => {
    try {
      const v = await getSession(sid);
      if (!alive.current) return;
      if (v.status === 'WORKING' && v.turn === sentTurn) {
        setView(v);
        if (Date.now() - since > LOCK_MS) {
          void turn(v, {});
          return;
        }
        later(RESYNC_DELAY_MS, () => void resyncWhileLocked(sid, sentTurn, since));
        return;
      }
      handle(v);
    } catch (e) {
      if (isApiError(e) && e.code === 'UNAUTHORIZED') return;
      fail();
    }
  };

  const turn = async (v: SessionView, extra: { answer?: AiAnswer; finish?: boolean }) => {
    setBusy(true);
    const body: TurnRequest = { expectedTurn: v.turn };
    if (extra.answer) body.answer = extra.answer;
    if (extra.finish || reserved.current) body.finish = true;
    try {
      handle(await sendTurn(v.sessionId, body));
    } catch (e) {
      if (!alive.current) return;
      if (!isApiError(e)) {
        void resyncOnce(v.sessionId); // 네트워크 오류·타임아웃: GET으로 한 번 맞춰 본다
        return;
      }
      switch (e.code) {
        case 'AI_SESSION_BUSY': {
          const since = Date.now();
          later(RESYNC_DELAY_MS, () => void resyncWhileLocked(v.sessionId, v.turn, since));
          return;
        }
        case 'AI_SESSION_CLOSED':
          void resyncOnce(v.sessionId);
          return;
        case 'VALIDATION_ERROR':
          callbacks.current.toast('답변을 다시 확인해 주세요.');
          void resyncOnce(v.sessionId);
          return;
        case 'UNAUTHORIZED':
          setBusy(false);
          return;
        default:
          fail(); // 404·503 AI_UNAVAILABLE·5xx 등
      }
    }
  };

  const start = async () => {
    setBusy(true);
    try {
      handle(await startSession(story));
    } catch (e) {
      if (isApiError(e) && e.code === 'UNAUTHORIZED') return;
      fail(); // 429·502·503·네트워크·타임아웃
    }
  };

  useEffect(() => {
    alive.current = true;
    if (!started.current) {
      started.current = true;
      if (!readyView) {
        if (sessionId) void resyncOnce(sessionId);
        else void start();
      }
    }
    const pending = timers.current;
    return () => {
      alive.current = false;
      pending.forEach(clearTimeout);
    };
    // 처음 한 번만 시작한다(개발 모드 이중 실행에도 started로 한 번)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 질문 답하기·건너뛰기 */
  const answer = useCallback(
    (a: AiAnswer) => {
      if (busy || !view || view.status !== 'ASKING') return;
      void turn(view, { answer: a });
    },
    // turn은 ref와 setter만 쓴다
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [busy, view],
  );

  /** "이대로 카드 받기": 요청 중이면 예약만 한다(FE-NFR-03) */
  const finishNow = useCallback(() => {
    if (reserved.current && busy) return;
    reserve();
    if (!busy && view && (view.status === 'ASKING' || view.status === 'WORKING'))
      void turn(view, { finish: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, view]);

  return { view, busy, finishReserved, answer, finishNow };
}
