import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { Icon } from '../../../components/Icon';
import { PageTitle } from '../../../components/PageTitle';
import { BottomActions, PrimaryButton } from '../../../components/PrimaryButton';
import { TextArea } from '../../../components/TextArea';
import { startDraft, usePlanDraft, withoutAi } from '../../../state/planDraft';
import { LIMITS, summaryFromStory, validateStory } from '../../../utils/validation';
import styles from './Create.module.css';

/**
 * 3. 사연 입력(FE-CRT-01, FE-CRT-05).
 * 처음 들어올 때 startedAt을 한 번만 기록하고(FE-CRT-09), 입력할 때마다 초안에 저장한다.
 * 외부 AI 전송 안내의 공급자명·처리 국가·보관 기간은 FE-Q6이 정해지면 채운다(백엔드 LLM_PROVIDER_LABEL과 같은 값).
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
      ...withoutAi(d),
      mode: 'MANUAL',
      form: d.form.summary.trim() ? d.form : { ...d.form, summary: summaryFromStory(d.story) },
    }));
    navigate('/plans/new/form');
  };

  /** AI와 함께 정리하기(FE-CRT-02): 이전 AI 상태를 지우고 3-1에서 새 세션을 시작한다 */
  const onAi = () => {
    const errs = validateStory(story);
    if (errs.story) {
      setError(errs.story);
      return;
    }
    update((d) => withoutAi(d));
    navigate('/plans/new/card');
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
          placeholder="예: 이사 전에 가 보려던 동네 서점에 일정이 바뀌어 못 갔어요."
          onChange={(e) => {
            const value = e.target.value;
            update((d) => ({ ...d, story: value }));
            if (error) setError(undefined);
          }}
        />
        <div className={styles.notice}>
          <Icon name="info" size={16} strokeWidth={2} />
          <p>
            AI와 함께 정리하기를 누르면 사연이 외부 AI 서비스로 전송되고, 공급자 정책에 따라 일정 기간 보관될
            수 있어요.
          </p>
        </div>
      </div>
      <BottomActions>
        <PrimaryButton fixed={false} onClick={onAi}>
          <Icon name="spark" size={18} strokeWidth={2} />
          AI와 함께 정리하기
        </PrimaryButton>
        <PrimaryButton fixed={false} variant="secondary" onClick={onManual}>
          직접 작성하기
        </PrimaryButton>
      </BottomActions>
    </section>
  );
}
