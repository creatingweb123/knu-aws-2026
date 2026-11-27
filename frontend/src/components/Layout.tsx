import { Suspense, lazy } from 'react';
import type { ReactNode } from 'react';

import { config } from '../config';
import { BottomTab } from './BottomTab';
import { Header } from './Header';
import styles from './Layout.module.css';

// 목업 사용자 전환 바는 개발 빌드의 목업 모드에서만 불러온다(FE-Q10)
const DevMockBar = config.useMock && config.isDev ? lazy(() => import('./DevMockBar')) : null;

interface Props {
  title?: string;
  back?: boolean | string;
  /** 하단 탭(목록형 화면만, FE-Q12) */
  tab?: boolean;
  /** 헤더 없이 그린다(로그인 등) */
  bare?: boolean;
  children: ReactNode;
}

/** 모바일 레이아웃: 360–480px에서 꽉 차고, 그보다 넓으면 480px 가운데 정렬(FE-NFR-01) */
export function Layout({ title, back, tab = false, bare = false, children }: Props) {
  return (
    <div className={styles.app}>
      {DevMockBar ? (
        <Suspense fallback={null}>
          <DevMockBar />
        </Suspense>
      ) : null}
      {bare ? null : <Header title={title} back={back} />}
      <main className={`${styles.main} ${tab ? styles.withTab : styles.withButton}`}>{children}</main>
      {tab ? <BottomTab /> : null}
    </div>
  );
}
