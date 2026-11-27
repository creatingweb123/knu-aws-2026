import { NavLink } from 'react-router-dom';

import { useMe } from '../api/queries/useMe';
import { Icon } from './Icon';
import type { IconName } from './Icon';
import styles from './BottomTab.module.css';

const TABS: readonly { to: string; label: string; end: boolean; icon: IconName }[] = [
  { to: '/', label: '둘러보기', end: true, icon: 'grid' },
  { to: '/me', label: '내 하루', end: false, icon: 'calendar' },
  { to: '/inbox', label: '수신함', end: false, icon: 'inbox' },
];

/** 하단 탭. 목록형 화면(FE-Q12)에서만 Layout이 그린다(FE-COM-01). 수신함 탭에도 미확인 점을 둔다 */
export function BottomTab() {
  const { data: me } = useMe();
  const unread = (me?.unreadInboxCount ?? 0) > 0;

  return (
    <nav className={styles.tab} aria-label="주요 화면">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) => `${styles.item} ${isActive ? styles.active : ''}`}
        >
          <Icon name={t.icon} />
          <span>{t.label}</span>
          {t.to === '/inbox' && unread ? <span className={styles.dot} aria-hidden="true" /> : null}
        </NavLink>
      ))}
    </nav>
  );
}
