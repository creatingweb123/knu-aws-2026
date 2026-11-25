/**
 * 하루 남기기 작성 상태(FE-CRT-08, docs/02 §2.10). sessionStorage 한 항목에 묶어 둔다.
 * 하위 경로 이동·새로고침에도 유지되고, 공개에 성공하면 지운다.
 * `startedAt`은 사연 입력 화면에 처음 들어올 때 한 번만 기록한다(FE-CRT-09).
 * AI 필드(sessionId, turn, card, flags, notes)는 6단계에서 채운다.
 */
import { useCallback, useRef, useState } from 'react';

import type { AiCard, AiNote, AuthoringMode, Flag, PlaceInput } from '../api/types';
import type { PlanFormValues } from '../utils/validation';

export const DRAFT_KEY = 'haru.planDraft';
const DRAFT_VERSION = 1;

export type PlanForm = PlanFormValues;

export interface PlanDraft {
  version: number;
  story: string;
  sessionId: string | null;
  turn: number | null;
  card: AiCard | null;
  flags: Flag[];
  notes: AiNote[];
  form: PlanForm;
  mode: AuthoringMode;
  /** epoch ms */
  startedAt: number;
  /** 공개 키와 그 키를 만든 본문(durationMs 제외)의 해시, 그때의 durationMs(FE-Q18) */
  idempotencyKey: string | null;
  keyBodyHash: string | null;
  keyDurationMs: number | null;
}

export const emptyPlace = (): PlaceInput => ({ name: '', activity: '', whyChosen: '' });

export function emptyForm(): PlanForm {
  return { title: '', summary: '', reason: '', estimatedMinutes: '', places: [], question: '' };
}

export function newDraft(now: number): PlanDraft {
  return {
    version: DRAFT_VERSION,
    story: '',
    sessionId: null,
    turn: null,
    card: null,
    flags: [],
    notes: [],
    form: emptyForm(),
    mode: 'MANUAL',
    startedAt: now,
    idempotencyKey: null,
    keyBodyHash: null,
    keyDurationMs: null,
  };
}

function isDraft(v: unknown): v is PlanDraft {
  if (!v || typeof v !== 'object') return false;
  const d = v as Partial<PlanDraft>;
  return (
    d.version === DRAFT_VERSION &&
    typeof d.story === 'string' &&
    typeof d.startedAt === 'number' &&
    !!d.form &&
    Array.isArray(d.form.places)
  );
}

export function loadDraft(): PlanDraft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isDraft(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveDraft(draft: PlanDraft): void {
  sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
}

export function clearDraft(): void {
  sessionStorage.removeItem(DRAFT_KEY);
}

/** 사연 입력 화면 진입: 있으면 그대로, 없으면 지금을 startedAt으로 새로 만든다 */
export function startDraft(now: number = Date.now()): PlanDraft {
  const existing = loadDraft();
  if (existing) return existing;
  const draft = newDraft(now);
  saveDraft(draft);
  return draft;
}

/**
 * 화면용 훅. `initial`은 저장된 초안이 없을 때 쓸 값을 만든다(사연 입력 화면은 startDraft).
 * `update`는 상태와 sessionStorage를 함께 바꾼다.
 */
export function usePlanDraft(initial: () => PlanDraft | null = loadDraft) {
  const [draft, setDraft] = useState<PlanDraft | null>(initial);
  // update 직후 navigate해도 다음 화면이 바뀐 값을 읽도록 sessionStorage에는 바로 쓴다
  const current = useRef(draft);
  const update = useCallback((fn: (d: PlanDraft) => PlanDraft): PlanDraft | null => {
    const prev = current.current;
    if (!prev) return null;
    const next = fn(prev);
    current.current = next;
    saveDraft(next);
    setDraft(next);
    return next;
  }, []);
  return { draft, update };
}
