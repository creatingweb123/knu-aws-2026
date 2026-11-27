import { useNavigate } from 'react-router-dom';

import { usePlans } from '../../api/queries/usePlans';
import { errorMessage } from '../../api/errors';
import { PageTitle } from '../../components/PageTitle';
import { Icon } from '../../components/Icon';
import styles from './BrowsePage.module.css';
import { PlanCard } from './PlanCard';

/**
 * 1. 둘러보기(FE-BRW-01–04, docs/05 §5.2.1).
 * 목록은 서버가 준 순서(최신순) 그대로, 첫 페이지만 보여 준다(FE-Q1).
 * 하단 탭이 있는 화면이라 "취소된 하루 남기기"는 고정하지 않고 제목 아래에 둔다.
 */
export function BrowsePage() {
  const navigate = useNavigate();
  const { data, error, isPending, refetch, isFetching } = usePlans();

  return (
    <section data-testid="screen-1">
      <PageTitle
        title={'이어받을 수 있는\n하루를 둘러보세요'}
        description="누군가 하지 못한 하루를 이어받아요."
      />
      {/* 목록과 구분되는 점선 카드. 버튼 이름은 제목만 두고 보조 문구는 설명으로 연결한다 */}
      <button
        type="button"
        className={styles.create}
        aria-label="취소된 하루 남기기"
        aria-describedby="browse-create-desc"
        onClick={() => navigate('/plans/new')}
      >
        <span className={styles.createIcon}>
          <Icon name="plus" size={20} strokeWidth={2} />
        </span>
        <span className={styles.createText}>
          <span className={styles.createTitle}>취소된 하루 남기기</span>
          <span id="browse-create-desc" className={styles.createDesc}>
            사연만 적으면 AI가 하루 카드로 정리해요
          </span>
        </span>
        <Icon name="chevron" size={18} strokeWidth={2} />
      </button>

      {isPending ? <p className={styles.status}>불러오는 중…</p> : null}

      {error ? (
        <div className={styles.status} role="alert">
          <p>{errorMessage(error)}</p>
          <button type="button" className={styles.retry} onClick={() => void refetch()} disabled={isFetching}>
            다시 시도
          </button>
        </div>
      ) : null}

      {data && data.items.length === 0 ? (
        <div className={styles.empty} data-testid="browse-empty">
          <p className={styles.emptyTitle}>아직 남겨진 하루가 없어요</p>
          <p className={styles.emptyText}>하지 못한 하루가 있다면 첫 하루를 남겨 보세요.</p>
        </div>
      ) : null}

      {data && data.items.length > 0 ? (
        <ul className={styles.list} aria-label="이어받을 수 있는 하루" data-testid="plan-list">
          {data.items.map((p, i) => (
            <PlanCard key={p.planId} plan={p} index={i} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
