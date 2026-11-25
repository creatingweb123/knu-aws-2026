import { Link } from 'react-router-dom';

import type { PlanSummary } from '../../api/types';
import { StatusBadge } from '../../components/StatusBadge';
import { planMetaText } from '../../utils/plan';
import styles from './PlanCard.module.css';

/**
 * 둘러보기 카드(FE-BRW-01). 목록의 항목은 모두 이어받기 가능으로 내려온다(기한 지난 CLAIMED도 OPEN).
 * 내가 남긴 하루도 같은 모양이고, 이어받을 수 있는지는 상세의 `claimable`로만 판단한다(FE-BRW-04).
 * 대표 사진은 이번 일정에서 하지 않으므로 장식용 자리만 둔다(docs/05 §5.6 4번).
 */
export function PlanCard({ plan }: { plan: PlanSummary }) {
  return (
    <li>
      <Link to={`/plans/${encodeURIComponent(plan.planId)}`} className={styles.card}>
        <div className={styles.cover} aria-hidden="true" />
        <div className={styles.body}>
          <StatusBadge kind="claimable" />
          <h3 className={styles.title}>{plan.title}</h3>
          <p className={styles.summary}>{plan.summary}</p>
          <p className={styles.meta}>{planMetaText(plan.estimatedMinutes, plan.placeCount)}</p>
        </div>
      </Link>
    </li>
  );
}
