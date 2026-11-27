import type { ReactNode } from 'react';

import styles from './ResultScreen.module.css';

interface Props {
  icon: 'check' | 'alert';
  title: string;
  description?: ReactNode;
  /** 요약 카드(선택) */
  summary?: ReactNode;
  /** 하단 버튼 영역. 보통 PrimaryButton */
  action?: ReactNode;
}

/** 완료/확인 화면: 원형 아이콘 + 제목 + 설명 + 요약 카드 + 하단 버튼(docs/05 §5.3) */
export function ResultScreen({ icon, title, description, summary, action }: Props) {
  return (
    <section className={styles.screen}>
      <div className={`${styles.icon} ${icon === 'alert' ? styles.alert : ''}`} aria-hidden="true">
        {icon === 'check' ? (
          <svg width="32" height="32" viewBox="0 0 24 24">
            <path
              d="M5 12.5l4.5 4.5L19 7.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
            />
          </svg>
        ) : (
          <svg width="32" height="32" viewBox="0 0 24 24">
            <path d="M12 6v8" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
            <circle cx="12" cy="18" r="1.4" fill="currentColor" />
          </svg>
        )}
      </div>
      <h2 className={styles.title}>{title}</h2>
      {description ? <p className={styles.description}>{description}</p> : null}
      {summary ? <div className={styles.summary}>{summary}</div> : null}
      {action}
    </section>
  );
}
