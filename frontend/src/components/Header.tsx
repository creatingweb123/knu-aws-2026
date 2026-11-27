import { Link, useNavigate } from 'react-router-dom';

import { useMe } from '../api/queries/useMe';
import { Icon } from './Icon';
import styles from './Header.module.css';

interface Props {
  title?: string;
  /** 뒤로가기 버튼. `true`면 브라우저 뒤로, 문자열이면 그 경로로 간다 */
  back?: boolean | string;
  /** 목록형 화면(하단 탭이 있는 화면): 가운데 제목 대신 왼쪽에 서비스 이름을 둔다(docs/05 §5.3) */
  brand?: boolean;
}

/** 상단 헤더: 뒤로가기 + 가운데 제목 + 편지 아이콘(미확인 점, FE-COM-02) */
export function Header({ title, back, brand = false }: Props) {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const unread = (me?.unreadInboxCount ?? 0) > 0;

  return (
    <header className={`${styles.header} ${brand ? styles.brandHeader : ''}`}>
      {brand ? (
        <div className={styles.brand}>
          <Icon name="ticket" size={22} strokeWidth={2} />
          <span aria-hidden="true">이어온 하루</span>
          {/* 화면 이름은 보조 기술에만 읽힌다(가운데 제목을 서비스 이름으로 대신하므로) */}
          <h1 className={styles.srOnly}>{title ?? '이어온 하루'}</h1>
        </div>
      ) : (
        <>
          <div className={styles.side}>
            {back ? (
              <button
                type="button"
                className={styles.iconButton}
                aria-label="뒤로 가기"
                onClick={() => (typeof back === 'string' ? navigate(back) : navigate(-1))}
              >
                <Icon name="back" size={22} strokeWidth={2} />
              </button>
            ) : null}
          </div>
          <h1 className={styles.title}>{title ?? '이어온 하루'}</h1>
        </>
      )}
      <div className={`${styles.side} ${styles.right}`}>
        <Link
          to="/inbox"
          className={styles.iconButton}
          aria-label={unread ? '수신함, 새 편지 있음' : '수신함'}
        >
          <Icon name="mail" />
          {unread ? <span className={styles.dot} data-testid="unread-dot" /> : null}
        </Link>
      </div>
    </header>
  );
}
