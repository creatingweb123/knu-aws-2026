import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { PageTitle } from '../../../components/PageTitle';
import { BottomActions, PrimaryButton } from '../../../components/PrimaryButton';
import { TextArea } from '../../../components/TextArea';
import { startDraft, usePlanDraft } from '../../../state/planDraft';
import { LIMITS, summaryFromStory, validateStory } from '../../../utils/validation';
import styles from './Create.module.css';

/**
 * 3. 사연 입력(FE-CRT-01, FE-CRT-05).
 * 처음 들어올 때 startedAt을 한 번만 기록하고(FE-CRT-09), 입력할 때마다 초안에 저장한다.
 * "AI와 함께 정리하기"는 6단계에서 연결한다. 외부 AI 전송 안내의 공급자명·처리 국가·보관 기간은 FE-Q6.
 */
export function StoryPage() {
  const navigate = useNavigate();
  const { draft, update } = usePlanDraft(() => startDraft());
  const [error, setError] = useState<string>();
  const story = draft?.story ?? '';

  const onManual = () => {
    const errs = validateStory(story);
    if (errs.story) {
      setError(errs.story);
      return;
    }
    update((d) => ({
      ...d,
      mode: 'MANUAL',
      form: d.form.summary.trim() ? d.form : { ...d.form, summary: summaryFromStory(d.story) },
    }));
    navigate('/plans/new/form');
  };

  return (
    <section data-testid="screen-3" className={styles.twoButtons}>
      <PageTitle
        title={'하지 못한 하루를\n들려주세요'}
        description="가고 싶었던 곳과 하고 싶었던 일, 못 가게 된 이유를 자유롭게 적어 주세요."
      />
      <div className={styles.form}>
        <TextArea
          label="사연"
          rows={8}
          value={story}
          maxLength={LIMITS.story}
          error={error}
          hint="집 주소나 개인 정보는 적지 말아주세요."
          placeholder="예: 이사 전에 5년 살던 동네를 마지막으로 걷고 싶었어요."
          onChange={(e) => {
            const value = e.target.value;
            update((d) => ({ ...d, story: value }));
            if (error) setError(undefined);
          }}
        />
        <div className={styles.notice}>
          <p>
            AI와 함께 정리하기를 누르면 사연이 외부 AI 서비스로 전송되고, 공급자 정책에 따라 일정 기간 보관될
            수 있어요.
          </p>
          {/* 6단계에서 AI 정리를 연결하면 지운다 */}
          <p id="ai-pending" className={styles.pending}>
            AI 정리는 준비 중이에요. 지금은 직접 작성해 주세요.
          </p>
        </div>
      </div>
      <BottomActions>
        <PrimaryButton fixed={false} disabled aria-describedby="ai-pending">
          AI와 함께 정리하기
        </PrimaryButton>
        <PrimaryButton fixed={false} variant="secondary" onClick={onManual}>
          직접 작성하기
        </PrimaryButton>
      </BottomActions>
    </section>
  );
}
