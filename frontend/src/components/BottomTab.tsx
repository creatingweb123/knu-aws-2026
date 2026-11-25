import { NavLink } from 'react-router-dom';

import styles from './BottomTab.module.css';

const TABS = [
  { to: '/', label: '둘러보기', end: true },
  { to: '/me', label: '내 하루', end: false },
  { to: '/inbox', label: '수신함', end: false },
] as const;

/** 하단 탭. 목록형 화면(FE-Q12)에서만 Layout이 그린다(FE-COM-01) */
export function BottomTab() {
  return (
    <nav className={styles.tab} aria-label="주요 화면">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) => `${styles.item} ${isActive ? styles.active : ''}`}
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}
