import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { isApiError } from '../../api/client';
import { errorMessage } from '../../api/errors';
import { useClaim } from '../../api/mutations/useClaim';
import { usePlan } from '../../api/queries/usePlans';
import type { PlanStatus } from '../../api/types';
import { PrimaryButton } from '../../components/PrimaryButton';
import { ResultScreen } from '../../components/ResultScreen';
import { RouteTimeline } from '../../components/RouteTimeline';
import { StatusBadge } from '../../components/StatusBadge';
import type { BadgeKind } from '../../components/StatusBadge';
import { useToast } from '../../components/useToast';
import { planMetaText } from '../../utils/plan';
import { ClaimedNotice } from './ClaimedNotice';
import { decideDetailView } from './detailView';
import styles from './PlanDetailPage.module.css';

/** 소유자에게 보여 줄 상태 배지(공개/이어받음/완료, docs/05 §5.2.2 3번) */
const OWNER_STATUS: { [s in PlanStatus]: BadgeKind } = {
  OPEN: 'published',
  CLAIMED: 'claimed',
  COMPLETED: 'completed',
};

/**
 * 2. 하루 들여다보기 / 2-1 이미 이어받은 하루(FE-PLN-01–05, docs/05 §5.2.2).
 * 분기는 `decideDetailView`가 정한다. 409 ALREADY_CLAIMED는 페이지 이동 없이 같은 화면에 2-1 안내를 띄운다.
 */
export function PlanDetailPage() {
  const { planId = '' } = useParams();
  // 다른 하루로 옮기면 화면 상태(conflict)를 새로 시작한다
  return <PlanDetail key={planId} planId={planId} />;
}

function PlanDetail({ planId }: { planId: string }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { data, error, isPending, refetch, isFetching } = usePlan(planId);
  const claim = useClaim(planId);
  const [conflict, setConflict] = useState(false);

  const notFound = isApiError(error) && error.code === 'NOT_FOUND';
  const browse = () => navigate('/');

  if (isPending) {
    return (
      <section data-testid="screen-2">
        <p className={styles.status}>불러오는 중…</p>
      </section>
    );
  }

  if (error && !notFound) {
    return (
      <section data-testid="screen-2">
        <div className={styles.status} role="alert">
          <p>{errorMessage(error)}</p>
          <button type="button" className={styles.retry} onClick={() => void refetch()} disabled={isFetching}>
            다시 시도
          </button>
        </div>
      </section>
    );
  }

  const view = decideDetailView(data, { notFound, conflict });

  if (view === 'notFound' || !data) {
    return (
      <section data-testid="screen-2">
        <ResultScreen
          icon="alert"
          title="이 하루는 더 이상 볼 수 없어요"
          description="완료되었거나 사라진 하루예요. 다른 하루를 둘러보세요."
          action={<PrimaryButton onClick={browse}>둘러보기로 가기</PrimaryButton>}
        />
      </section>
    );
  }

  const { plan } = data;

  const onClaim = () => {
    claim.mutate(undefined, {
      onSuccess: () => navigate('/me'),
      onError: (e) => {
        if (isApiError(e) && e.code === 'ALREADY_CLAIMED') setConflict(true);
        else toast(errorMessage(e));
      },
    });
  };

  return (
    <section data-testid={view === 'claimed' ? 'screen-2-1' : 'screen-2'}>
      <div className={styles.cover} aria-hidden="true" />

      <div className={styles.badges} data-testid="detail-badges">
        {view === 'myClaim' ? <StatusBadge kind="myClaim" /> : null}
        {view === 'owner' ? (
          <>
            <StatusBadge kind="mine" />
            <StatusBadge kind={OWNER_STATUS[plan.status]} />
          </>
        ) : null}
        {view === 'claimable' ? <StatusBadge kind="claimable" /> : null}
        {view === 'claimed' ? <StatusBadge kind="claimed" /> : null}
        {view === 'completed' ? <StatusBadge kind="completed" /> : null}
      </div>

      <h2 className={styles.title}>{plan.title}</h2>
      <p className={styles.summary}>{plan.summary}</p>
      <p className={styles.meta}>{planMetaText(plan.estimatedMinutes, plan.places.length)}</p>

      <div className={styles.planner}>
        <p className={styles.plannerLabel}>{plan.owner.nickname} · 취소한 이유</p>
        <p className={styles.plannerReason}>{plan.reason}</p>
      </div>

      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>산책 동선</h3>
        <RouteTimeline places={plan.places} />
      </div>

      {view === 'claimed' ? <ClaimedNotice onBrowse={browse} /> : null}

      {view === 'myClaim' ? (
        <PrimaryButton onClick={() => navigate('/me')}>내 하루로 가기</PrimaryButton>
      ) : null}
      {view === 'claimable' ? (
        <PrimaryButton onClick={onClaim} loading={claim.isPending}>
          이 하루 이어받기
        </PrimaryButton>
      ) : null}
      {view === 'other' ? <PrimaryButton onClick={browse}>다른 하루 둘러보기</PrimaryButton> : null}
    </section>
  );
}
