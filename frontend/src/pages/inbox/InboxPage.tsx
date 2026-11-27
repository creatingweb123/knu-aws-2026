import { Link } from 'react-router-dom';

import { errorMessage } from '../../api/errors';
import { useInbox } from '../../api/queries/useInbox';
import type { InboxItem } from '../../api/types';
import { PageTitle } from '../../components/PageTitle';
import { Icon } from '../../components/Icon';
import { PrimaryButton } from '../../components/PrimaryButton';
import { StatusBadge } from '../../components/StatusBadge';
import { formatDateTime } from '../../utils/date';
import styles from './Inbox.module.css';

/** 6. 수신함(FE-INB-01). 서버가 준 최신순 그대로 보여 준다 */
export function InboxPage() {
  const { data, error, isPending, refetch } = useInbox();

  return (
    <section data-testid="screen-6">
      <PageTitle
        title={'돌아온 하루를\n읽어 보세요'}
        description="누군가 내 하루를 다녀와 이야기를 보내왔어요."
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
        <p className={styles.empty} data-testid="inbox-empty">
          아직 돌아온 하루가 없어요
        </p>
      ) : null}

      {data && data.items.length > 0 ? (
        <ul className={styles.list} aria-label="수신함" data-testid="inbox-list">
          {data.items.map((item) => (
            <InboxRow key={item.itemId} item={item} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function sentLine(item: Pick<InboxItem, 'claimerNickname' | 'hasPhoto'>): string {
  return `${item.claimerNickname}님이 ${item.hasPhoto ? '사진과 경험 기록을' : '경험 기록을'} 보냈어요`;
}

function InboxRow({ item }: { item: InboxItem }) {
  return (
    <li>
      <Link
        to={`/inbox/${encodeURIComponent(item.itemId)}`}
        className={`${styles.item} ${item.read ? styles.itemRead : ''}`}
      >
        <span className={styles.tile} aria-hidden="true">
          <Icon name="mail" />
          {item.read ? null : <span className={styles.dot} data-testid="item-unread-dot" />}
        </span>
        <span className={styles.itemBody}>
          <span className={styles.head}>
            <span className={styles.title}>{item.planTitle}</span>
            <StatusBadge kind={item.read ? 'read' : 'newLetter'} />
          </span>
          <span className={styles.line}>{sentLine(item)}</span>
          <span className={styles.time}>{formatDateTime(item.createdAt)}</span>
        </span>
      </Link>
    </li>
  );
}
