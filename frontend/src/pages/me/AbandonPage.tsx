import { useNavigate, useParams } from 'react-router-dom';

import { isApiError } from '../../api/client';
import { errorMessage } from '../../api/errors';
import { useAbandon } from '../../api/mutations/useAbandon';
import { useMyClaims } from '../../api/queries/useMyClaims';
import { BottomActions, PrimaryButton } from '../../components/PrimaryButton';
import { ResultScreen } from '../../components/ResultScreen';
import { useToast } from '../../components/useToast';
import { clearLetter } from '../../state/letterDraft';
import { dDayText } from '../../utils/claim';
import { planMetaText } from '../../utils/plan';
import styles from './Me.module.css';

/** 4-1. 이어받기 포기 확인(FE-ME-04). 성공하면 둘러보기로, CLAIM_NOT_ACTIVE면 안내 후 내 하루로 */
export function AbandonPage() {
  const { claimId = '' } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { data } = useMyClaims('ACTIVE');
  const abandon = useAbandon(claimId);
  const item = data?.items.find((i) => i.claim.claimId === claimId);
  const plan = item?.plan;

  const onAbandon = () => {
    abandon.mutate(undefined, {
      onSuccess: () => {
        clearLetter(claimId);
        toast('이어받기를 포기했어요. 이 하루는 다시 공개돼요.');
        navigate('/', { replace: true });
      },
      onError: (e) => {
        if (isApiError(e) && e.code === 'CLAIM_NOT_ACTIVE') {
          toast('이미 종료된 이어받기예요.');
          navigate('/me', { replace: true });
        } else {
          toast(errorMessage(e));
          if (isApiError(e) && (e.code === 'FORBIDDEN' || e.code === 'NOT_FOUND'))
            navigate('/', { replace: true });
        }
      },
    });
  };

  return (
    <section data-testid="screen-4-1" className={styles.twoButtons}>
      <ResultScreen
        icon="notice"
        title={'이어받기를\n포기할까요?'}
        description="포기하면 이 하루는 다시 공개되어 다른 사람이 이어받을 수 있어요."
        summary={
          item && plan ? (
            <div className={styles.confirmPlan}>
              <div className={styles.confirmHead}>
                <p className={styles.confirmTitle}>{plan.title}</p>
                <span className={styles.dday}>{dDayText(item.claim.dueAt)}</span>
              </div>
              <p className={styles.meta}>
                {plan.owner.nickname} · {planMetaText(plan.estimatedMinutes, plan.places.length)}
              </p>
            </div>
          ) : undefined
        }
      />
      <BottomActions>
        <PrimaryButton fixed={false} onClick={() => navigate('/me')}>
          계속 이어가기
        </PrimaryButton>
        <PrimaryButton fixed={false} variant="danger" onClick={onAbandon} loading={abandon.isPending}>
          이어받기 포기
        </PrimaryButton>
      </BottomActions>
    </section>
  );
}
