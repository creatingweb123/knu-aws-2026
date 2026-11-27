import { Link, useNavigate } from 'react-router-dom';

import { useMe } from '../api/queries/useMe';
import styles from './Header.module.css';

interface Props {
  title?: string;
  /** 뒤로가기 버튼. `true`면 브라우저 뒤로, 문자열이면 그 경로로 간다 */
  back?: boolean | string;
}

/** 상단 헤더: 뒤로가기 + 가운데 제목 + 편지 아이콘(미확인 점, FE-COM-02) */
export function Header({ title, back }: Props) {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const unread = (me?.unreadInboxCount ?? 0) > 0;

  return (
    <header className={styles.header}>
      <div className={styles.side}>
        {back ? (
          <button
            type="button"
            className={styles.iconButton}
            aria-label="뒤로 가기"
            onClick={() => (typeof back === 'string' ? navigate(back) : navigate(-1))}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M15 5l-7 7 7 7"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        ) : null}
      </div>
      <h1 className={styles.title}>{title ?? '이어온 하루'}</h1>
      <div className={`${styles.side} ${styles.right}`}>
        <Link
          to="/inbox"
          className={styles.iconButton}
          aria-label={unread ? '수신함, 새 편지 있음' : '수신함'}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
            <rect
              x="3"
              y="6"
              width="18"
              height="13"
              rx="2"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
            />
            <path d="M3.5 7l8.5 6 8.5-6" fill="none" stroke="currentColor" strokeWidth="1.8" />
          </svg>
          {unread ? <span className={styles.dot} data-testid="unread-dot" /> : null}
        </Link>
      </div>
    </header>
  );
}
