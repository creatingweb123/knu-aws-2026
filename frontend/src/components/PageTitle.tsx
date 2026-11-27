import type { ReactNode } from 'react';

import styles from './PageTitle.module.css';

/** 큰 제목(굵게) + 회색 보조 설명. 모든 단계 화면에 쓴다(docs/05 §5.3) */
export function PageTitle({ title, description }: { title: ReactNode; description?: ReactNode }) {
  return (
    <div className={styles.wrap}>
      <h2 className={styles.title}>{title}</h2>
      {description ? <p className={styles.description}>{description}</p> : null}
    </div>
  );
}
