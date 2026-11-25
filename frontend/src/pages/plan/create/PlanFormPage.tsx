import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';

import { isApiError } from '../../../api/client';
import { errorMessage, fieldErrors } from '../../../api/errors';
import { useCreatePlan } from '../../../api/mutations/useCreatePlan';
import { PageTitle } from '../../../components/PageTitle';
import { PrimaryButton } from '../../../components/PrimaryButton';
import { TextArea } from '../../../components/TextArea';
import { TextField } from '../../../components/TextField';
import { useToast } from '../../../components/useToast';
import { clearDraft, usePlanDraft } from '../../../state/planDraft';
import type { PlanForm } from '../../../state/planDraft';
import { LIMITS, validatePlanForm } from '../../../utils/validation';
import type { FieldErrors } from '../../../utils/validation';
import styles from './Create.module.css';
import { preparePublish } from './publish';

type TextKey = Exclude<keyof PlanForm, 'places'>;

/**
 * 3-2. 하루 남기기 폼(FE-CRT-06, FE-CRT-10, FE-COM-04).
 * 클라이언트 검증과 서버 `VALIDATION_ERROR.details`를 같은 경로 키로 입력칸에 보여 준다.
 * 공개 키 재사용은 publish.ts(FE-Q18). 장소 고치기·빼기는 FE-Q20.
 */
export function PlanFormPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { draft, update } = usePlanDraft();
  const createPlan = useCreatePlan();
  const [errors, setErrors] = useState<FieldErrors>({});

  if (!draft || !draft.story.trim()) return <Navigate to="/plans/new" replace />;

  const { form } = draft;

  const clearErrors = (match: (path: string) => boolean) =>
    setErrors((prev) => Object.fromEntries(Object.entries(prev).filter(([p]) => !match(p))));

  const setField = (key: TextKey, value: string) => {
    update((d) => ({ ...d, form: { ...d.form, [key]: value } }));
    if (errors[key]) clearErrors((p) => p === key);
  };

  const removePlace = (index: number) => {
    update((d) => ({ ...d, form: { ...d.form, places: d.form.places.filter((_, i) => i !== index) } }));
    clearErrors((p) => p.startsWith('places'));
  };

  const onPublish = () => {
    const errs = validatePlanForm(form);
    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      return;
    }
    const prepared = preparePublish(draft, Date.now());
    update((d) => ({
      ...d,
      idempotencyKey: prepared.key,
      keyBodyHash: prepared.keyBodyHash,
      keyDurationMs: prepared.keyDurationMs,
    }));
    createPlan.mutate(
      { body: prepared.body, key: prepared.key },
      {
        onSuccess: ({ plan }) => {
          clearDraft();
          navigate(`/plans/${encodeURIComponent(plan.planId)}/published`, { replace: true, state: { plan } });
        },
        onError: (e) => {
          if (isApiError(e) && e.code === 'VALIDATION_ERROR') {
            setErrors(fieldErrors(e));
            toast('입력값을 확인해 주세요.');
          } else {
            toast(errorMessage(e));
          }
        },
      },
    );
  };

  const placeErrors = (i: number) =>
    Object.entries(errors)
      .filter(([p]) => p.startsWith(`places[${i}]`))
      .map(([, m]) => m);

  return (
    <section data-testid="screen-3-2">
      <PageTitle
        title={'이어받을 수 있게\n하루를 정리해 주세요'}
        description="다른 사람이 보고 따라 걸을 수 있게 적어 주세요."
      />

      <div className={styles.form}>
        <div className={styles.storyRef}>
          <p className={styles.storyRefLabel}>내 사연 (참고용)</p>
          <p className={styles.storyRefText}>{draft.story}</p>
        </div>

        <TextField
          label="하루 제목"
          value={form.title}
          maxLength={LIMITS.title}
          error={errors.title}
          onChange={(e) => setField('title', e.target.value)}
        />
        <TextArea
          label="하고 싶었던 일 요약"
          rows={3}
          value={form.summary}
          maxLength={LIMITS.summary}
          error={errors.summary}
          onChange={(e) => setField('summary', e.target.value)}
        />
        <TextArea
          label="취소한 이유"
          rows={3}
          value={form.reason}
          maxLength={LIMITS.reason}
          error={errors.reason}
          onChange={(e) => setField('reason', e.target.value)}
        />
        <TextField
          label="예상 소요 시간(분)"
          inputMode="numeric"
          value={form.estimatedMinutes}
          error={errors.estimatedMinutes}
          hint="10–240분"
          onChange={(e) => setField('estimatedMinutes', e.target.value)}
        />

        <div>
          <h3 className={styles.sectionTitle}>산책 동선</h3>
          {errors.places ? (
            <p className={styles.errorText} role="alert">
              {errors.places}
            </p>
          ) : null}
          {form.places.length === 0 ? (
            <p className={styles.emptyPlaces}>장소를 1곳 이상 추가해 주세요(최대 3곳).</p>
          ) : (
            <ol className={styles.places} aria-label="산책 동선">
              {form.places.map((p, i) => {
                const errs = placeErrors(i);
                return (
                  <li
                    key={`${i}-${p.name}`}
                    className={`${styles.place} ${errs.length ? styles.placeInvalid : ''}`}
                    data-testid={`place-${i}`}
                  >
                    <span className={styles.placeNo} aria-hidden="true">
                      {i + 1}
                    </span>
                    <div className={styles.placeBody}>
                      <p className={styles.placeName}>{p.name || '(이름 없음)'}</p>
                      <p className={styles.placeActivity}>{p.activity}</p>
                      {p.whyChosen ? <p className={styles.placeWhy}>{p.whyChosen}</p> : null}
                      {errs.map((m, k) => (
                        <p key={k} className={styles.errorText} role="alert">
                          {m}
                        </p>
                      ))}
                      <div className={styles.placeActions}>
                        <button
                          type="button"
                          className={styles.smallButton}
                          aria-label={`${i + 1}번 장소 고치기`}
                          onClick={() => navigate(`/plans/new/place?index=${i}`)}
                        >
                          고치기
                        </button>
                        <button
                          type="button"
                          className={styles.smallButton}
                          aria-label={`${i + 1}번 장소 빼기`}
                          onClick={() => removePlace(i)}
                        >
                          빼기
                        </button>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
          {form.places.length < LIMITS.maxPlaces ? (
            <button type="button" className={styles.addPlace} onClick={() => navigate('/plans/new/place')}>
              + 장소 추가
            </button>
          ) : null}
        </div>

        <TextField
          label="방문 질문"
          value={form.question}
          maxLength={LIMITS.question}
          error={errors.question}
          hint="이어받은 사람에게 물어보고 싶은 것 하나"
          onChange={(e) => setField('question', e.target.value)}
        />
      </div>

      <PrimaryButton onClick={onPublish} loading={createPlan.isPending}>
        이 하루 공개하기
      </PrimaryButton>
    </section>
  );
}
