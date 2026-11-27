import { Icon } from '../../components/Icon';
import { PrimaryButton } from '../../components/PrimaryButton';
import styles from './PlanDetailPage.module.css';

/** 2-1 이미 이어받은 하루 안내(FE-PLN-04). 409 ALREADY_CLAIMED와 남의 CLAIMED 상세에서 같이 쓴다 */
export function ClaimedNotice({ onBrowse }: { onBrowse: () => void }) {
  return (
    <div className={styles.notice} role="status" data-testid="claimed-notice">
      <div className={styles.noticeHead}>
        <span className={styles.noticeIcon}>
          <Icon name="alert" size={22} strokeWidth={2.2} />
        </span>
        <div>
          <p className={styles.noticeTitle}>이미 다른 사람이 이어받았어요</p>
          <p className={styles.noticeText}>다른 하루를 둘러보고 이어받을 하루를 골라 보세요.</p>
        </div>
      </div>
      <PrimaryButton fixed={false} onClick={onBrowse}>
        다른 하루 둘러보기
      </PrimaryButton>
    </div>
  );
}
