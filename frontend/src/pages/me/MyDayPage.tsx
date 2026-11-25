import { useNavigate } from 'react-router-dom';

import { errorMessage } from '../../api/errors';
import { useMyClaims } from '../../api/queries/useMyClaims';
import type { MyClaimItem } from '../../api/types';
import { PageTitle } from '../../components/PageTitle';
import { PrimaryButton } from '../../components/PrimaryButton';
import { RouteTimeline } from '../../components/RouteTimeline';
import { dueText, recordPath } from '../../utils/claim';
import { planMetaText } from '../../utils/plan';
import styles from './Me.module.css';

/**
 * 4. 내 하루(FE-ME-01–03). 진행 중인 이어받기를 모두 카드로 보여 준다(FE-Q21).
 * 하단 탭이 있는 화면이라 버튼은 카드 안에 둔다.
 */
export function MyDayPage() {
  const navigate = useNavigate();
  const { data, error, isPending, refetch } = useMyClaims('ACTIVE');

  return (
    <section data-testid="screen-4">
      <PageTitle
        title={'내가 이어받은\n하루예요'}
        description="기한 안에 다녀와서 그날의 이야기를 보내 주세요."
      />

      {isPending ? <p className={styles.status}>불러오는 중…</p> : null}
      {error ? (
        <div className={styles.status} role="alert">
          <p>{errorMessage(error)}</p>
          <PrimaryButton fixed={false} variant="secondary" onClick={() => void refetch()}>
            다시 시도
          </PrimaryButton>
        </div>
      ) : null}

      {data && data.items.length === 0 ? (
        <div className={styles.empty} data-testid="me-empty">
          <p className={styles.emptyTitle}>아직 이어받은 하루가 없어요</p>
          <PrimaryButton fixed={false} onClick={() => navigate('/')}>
            하루 둘러보기
          </PrimaryButton>
        </div>
      ) : null}

      {data && data.items.length > 0 ? (
        <ul className={styles.list} aria-label="이어받은 하루">
          {data.items.map((item) => (
            <ClaimCard key={item.claim.claimId} item={item} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function ClaimCard({ item }: { item: MyClaimItem }) {
  const navigate = useNavigate();
  const { claim, plan, record } = item;
  const overdue = Date.parse(claim.dueAt) <= Date.now();
  return (
    <li className={styles.card} data-testid={`claim-${claim.claimId}`}>
      <h3 className={styles.title}>{plan.title}</h3>
      <p className={styles.meta}>
        {plan.owner.nickname} · {planMetaText(plan.estimatedMinutes, plan.places.length)}
      </p>
      <p className={`${styles.due} ${overdue ? styles.overdue : ''}`}>{dueText(claim.dueAt)}</p>
      <div className={styles.route}>
        <RouteTimeline places={plan.places} />
      </div>
      <div className={styles.actions}>
        <PrimaryButton fixed={false} onClick={() => navigate(recordPath(claim.claimId, record?.photoStatus))}>
          다녀온 이야기 쓰기
        </PrimaryButton>
        <PrimaryButton
          fixed={false}
          variant="secondary"
          onClick={() => navigate(`/claims/${encodeURIComponent(claim.claimId)}/abandon`)}
        >
          이어받기 포기
        </PrimaryButton>
      </div>
    </li>
  );
}
