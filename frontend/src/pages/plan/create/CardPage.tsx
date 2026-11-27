import { useState } from 'react';
import type { ReactNode } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';

import type { AiAnswer, AiCard, AiNote, AiQuestion, Flag, SessionView } from '../../../api/types';
import { PageTitle } from '../../../components/PageTitle';
import { PrimaryButton } from '../../../components/PrimaryButton';
import { TextField } from '../../../components/TextField';
import { emptyForm, usePlanDraft, withoutAi } from '../../../state/planDraft';
import type { PlanDraft } from '../../../state/planDraft';
import { charCount } from '../../../utils/validation';
import styles from './Card.module.css';
import { cardToForm, restorePlace } from './cardForm';
import { useAiSession } from './useAiSession';

/**
 * 3-1. AI와 함께 정리하기(FE-CRT-02–04, 12–14). 시안 없음: 큰 제목 + 단계 칩 + 질문 말풍선 +
 * 카드 미리보기·메모 + 하단 고정 "폼에서 다듬기"(READY) 또는 "이대로 카드 받기"(FE-NFR-02).
 */
export function CardPage() {
  const { draft, update } = usePlanDraft();
  if (!draft || !draft.story.trim()) return <Navigate to="/plans/new" replace />;
  return <CardSession draft={draft} update={update} />;
}

type Update = (fn: (d: PlanDraft) => PlanDraft) => PlanDraft | null;

function savedReadyView(d: PlanDraft): SessionView | null {
  if (!d.sessionId || !d.card) return null;
  return {
    sessionId: d.sessionId,
    status: 'READY',
    turn: d.turn ?? 1,
    trace: [],
    question: null,
    card: d.card,
    flags: d.flags,
    notes: d.notes,
    degraded: false,
  };
}

function CardSession({ draft, update }: { draft: PlanDraft; update: Update }) {
  const navigate = useNavigate();
  const [readyView] = useState(() => savedReadyView(draft));

  const ai = useAiSession({
    story: draft.story.trim(),
    sessionId: draft.sessionId,
    readyView,
    onView: (v) =>
      update((d) => ({
        ...d,
        sessionId: v.sessionId,
        turn: v.turn,
        // READY 카드는 처음 받을 때만 저장한다(다시 넣기 결과를 덮지 않게)
        ...(v.status === 'READY' && !d.card ? { card: v.card, flags: v.flags, notes: v.notes } : {}),
      })),
    onFailed: () => {
      // 사연은 유지하고 빈 폼·MANUAL로(FE-CRT-04, FE-Q25)
      update((d) => ({ ...withoutAi(d), mode: 'MANUAL', form: emptyForm(), aiFailed: true }));
      navigate('/plans/new/form', { replace: true });
    },
  });

  const view = ai.view;
  const ready = view?.status === 'READY';

  const toForm = () => {
    update((d) => {
      if (d.cardApplied || !d.card) return { ...d, mode: 'AI_EDITED' };
      return { ...d, form: cardToForm(d.card), mode: 'AI_EDITED', cardApplied: true, aiFailed: false };
    });
    navigate('/plans/new/form');
  };

  const onRestore = (index: number, note: AiNote) => {
    if (!note.restore) return;
    const { value, type } = note.restore;
    update((d) => {
      if (d.cardApplied) {
        const next = restorePlace(d.form.places, d.flags, value, type);
        if (!next) return d;
        return {
          ...d,
          form: { ...d.form, places: next.places },
          flags: next.flags,
          restoredNotes: [...(d.restoredNotes ?? []), index],
        };
      }
      if (!d.card) return d;
      const places = (d.card.places ?? []).map((p) => ({
        name: p.name ?? '',
        activity: p.activity ?? '',
        whyChosen: p.whyChosen ?? '',
      }));
      const next = restorePlace(places, d.flags, value, type);
      if (!next) return d;
      return {
        ...d,
        card: { ...d.card, places: next.places },
        flags: next.flags,
        restoredNotes: [...(d.restoredNotes ?? []), index],
      };
    });
  };

  const placeCount = draft.cardApplied ? draft.form.places.length : (draft.card?.places?.length ?? 0);

  return (
    <section data-testid="screen-3-1">
      <PageTitle
        title={ready ? '하루 카드가\n준비됐어요' : 'AI와 함께\n하루를 정리하고 있어요'}
        description={
          ready
            ? '바뀐 내용을 확인하고 폼에서 다듬어 주세요.'
            : '사연에 있는 장소와 하고 싶었던 일로 카드를 만들어요.'
        }
      />

      <ol className={styles.chips} aria-label="정리 단계" aria-live="polite">
        {(view?.trace ?? []).map((t) => (
          <li key={t.step} className={styles.chip}>
            {t.summary}
          </li>
        ))}
        {ai.busy ? <li className={`${styles.chip} ${styles.chipWorking}`}>정리하는 중이에요</li> : null}
      </ol>

      {view?.status === 'ASKING' && view.question ? (
        <QuestionBubble question={view.question} disabled={ai.busy} onAnswer={ai.answer} />
      ) : null}

      {ready && draft.card ? (
        <>
          <CardPreview card={draft.card} flags={draft.flags} />
          <Notes
            notes={draft.notes}
            restored={draft.restoredNotes ?? []}
            full={placeCount >= 3}
            onRestore={onRestore}
          />
        </>
      ) : null}

      {ready ? (
        <PrimaryButton onClick={toForm}>폼에서 다듬기</PrimaryButton>
      ) : (
        <PrimaryButton variant="secondary" onClick={ai.finishNow} disabled={ai.finishReserved || !view}>
          {ai.finishReserved ? '카드를 받을게요' : '이대로 카드 받기'}
        </PrimaryButton>
      )}
    </section>
  );
}

function QuestionBubble({
  question,
  disabled,
  onAnswer,
}: {
  question: AiQuestion;
  disabled: boolean;
  onAnswer: (a: AiAnswer) => void;
}) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string>();
  const id = question.questionId;

  const sendText = () => {
    const value = text.trim();
    const n = charCount(value);
    if (n < 1 || n > 100) {
      setError('1–100자로 입력해 주세요.');
      return;
    }
    onAnswer({ questionId: id, text: value });
  };

  return (
    <div
      className={`${styles.bubble} ${styles.section}`}
      role="group"
      aria-label="AI의 질문"
      data-testid="ai-question"
    >
      <p className={styles.bubbleText}>{question.text}</p>
      {question.reason ? <p className={styles.bubbleReason}>{question.reason}</p> : null}
      {question.options.length > 0 ? (
        <div className={styles.options}>
          {question.options.map((o) => (
            <button
              key={o}
              type="button"
              className={styles.option}
              disabled={disabled}
              onClick={() => onAnswer({ questionId: id, choice: o })}
            >
              {o}
            </button>
          ))}
        </div>
      ) : null}
      {question.allowFreeText ? (
        <div className={styles.free}>
          <TextField
            label="직접 입력"
            value={text}
            maxLength={100}
            error={error}
            onChange={(e) => {
              setText(e.target.value);
              if (error) setError(undefined);
            }}
          />
          <PrimaryButton fixed={false} variant="secondary" onClick={sendText} disabled={disabled}>
            보내기
          </PrimaryButton>
        </div>
      ) : null}
      <button
        type="button"
        className={styles.skip}
        disabled={disabled}
        onClick={() => onAnswer({ questionId: id, skipped: true })}
      >
        건너뛰기
      </button>
    </div>
  );
}

const EMPTY = <span className={styles.empty}>비어 있어요</span>;

function CardPreview({ card, flags }: { card: AiCard; flags: Flag[] }) {
  const passed = !flags.some((f) => f.type === 'NOT_IN_SOURCE');
  return (
    <div className={`${styles.card} ${styles.section}`} data-testid="card-preview">
      <div className={styles.cardHead}>
        <p className={styles.cardTitle}>{card.title ?? EMPTY}</p>
        {passed ? <span className={styles.passed}>원문 대조 통과</span> : null}
      </div>
      <Field label="하고 싶었던 일">{card.summary ?? EMPTY}</Field>
      <Field label="취소한 이유">{card.reason ?? EMPTY}</Field>
      <Field label="예상 소요 시간">
        {card.estimatedMinutes === null ? EMPTY : `약 ${card.estimatedMinutes}분`}
      </Field>
      <Field label="방문할 장소">
        {card.places && card.places.length > 0 ? (
          <ol className={styles.places}>
            {card.places.map((p, i) => (
              <li key={i}>
                {p.name ?? '(이름 없음)'} · {p.activity ?? '(할 일 없음)'}
                {p.whyChosen ? ` — ${p.whyChosen}` : ''}
              </li>
            ))}
          </ol>
        ) : (
          EMPTY
        )}
      </Field>
      <Field label="방문 질문">{card.question ?? EMPTY}</Field>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.field}>
      <p className={styles.fieldLabel}>{label}</p>
      <p>{children}</p>
    </div>
  );
}

const SOURCE_LABEL = { STORY: '원문', ANSWER: '내 답변' } as const;

function Notes({
  notes,
  restored,
  full,
  onRestore,
}: {
  notes: AiNote[];
  restored: number[];
  full: boolean;
  onRestore: (index: number, note: AiNote) => void;
}) {
  if (notes.length === 0) return null;
  return (
    <div className={styles.notes}>
      <p className={styles.notesTitle}>AI가 바꾼 것</p>
      <ul className={styles.noteList} data-testid="ai-notes">
        {notes.map((n, i) => {
          const done = restored.includes(i);
          return (
            <li key={i} className={styles.note}>
              {n.reason}
              <span className={styles.source}>{SOURCE_LABEL[n.source]}</span>
              {n.action === 'REMOVED' && n.restore ? (
                <div>
                  <button
                    type="button"
                    className={styles.restore}
                    disabled={done || full}
                    onClick={() => onRestore(i, n)}
                  >
                    {done ? '다시 넣었어요' : '다시 넣기'}
                  </button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
