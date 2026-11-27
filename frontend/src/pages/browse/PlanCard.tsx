import { Link } from 'react-router-dom';

import type { PlanSummary } from '../../api/types';
import { Icon } from '../../components/Icon';
import { StatusBadge } from '../../components/StatusBadge';
import { planMetaText } from '../../utils/plan';
import styles from './PlanCard.module.css';
import { OWNER_FALLBACK_NAME, displayNickname } from '../../utils/nickname';

/**
 * 둘러보기 카드(FE-BRW-01). 목록의 항목은 모두 이어받기 가능으로 내려온다(기한 지난 CLAIMED도 OPEN).
 * 내가 남긴 하루도 같은 모양이고, 이어받을 수 있는지는 상세의 `claimable`로만 판단한다(FE-BRW-04).
 *
 * 모양은 '넘겨받는 티켓'이다(docs/05 §5.3): 위쪽 칸(계획자·장소 번호)과 점선 절취선 아래 본문.
 * 대표 사진은 하지 않으므로(docs/05 §5.6 4번) 위쪽 칸이 그 자리를 대신한다. 목록 응답에는 장소 이름이 없어
 * 장소 수만큼 번호 원만 그린다. 번호는 순서 표시이며 경로가 아니라서 원끼리 선으로 잇지 않는다.
 */
export function PlanCard({ plan, index = 0 }: { plan: PlanSummary; index?: number }) {
  const tone = index % 2 === 0 ? styles.plan : styles.record;
  const numbers = Array.from({ length: plan.placeCount }, (_, i) => i + 1);
  return (
    <li>
      <Link to={`/plans/${encodeURIComponent(plan.planId)}`} className={styles.card}>
        <div className={`${styles.stub} ${tone}`}>
          <div className={styles.stubRow}>
            <StatusBadge kind="claimable" />
            <span className={styles.owner}>
              {displayNickname(plan.ownerNickname, OWNER_FALLBACK_NAME)}의 하루
            </span>
          </div>
          <div className={styles.numbers} aria-hidden="true">
            {numbers.map((n) => (
              <span key={n} className={`${styles.num} ${n === numbers.length ? styles.last : ''}`}>
                {n}
              </span>
            ))}
          </div>
        </div>
        <div className={styles.perforation} aria-hidden="true" />
        <div className={styles.body}>
          <h3 className={styles.title}>{plan.title}</h3>
          <p className={styles.summary}>{plan.summary}</p>
          <p className={styles.meta}>
            <Icon name="clock" size={13} strokeWidth={2} />
            {planMetaText(plan.estimatedMinutes, plan.placeCount)}
          </p>
        </div>
      </Link>
    </li>
  );
}
