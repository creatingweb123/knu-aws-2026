import type { ReactNode } from 'react';

import { Icon } from './Icon';
import styles from './ResultScreen.module.css';

/**
 * 아이콘은 색과 모양을 함께 바꿔 뜻을 나눈다(docs/05 §5.3).
 * check: 완료·공개(숲색 체크) / notice: 확인이 필요함(베이지 느낌표) / alert: 실패(빨강 느낌표) / ended: 끝남(회색 시계)
 */
export type ResultIcon = 'check' | 'notice' | 'alert' | 'ended';

interface Props {
  icon: ResultIcon;
  title: ReactNode;
  description?: ReactNode;
  /** 요약 카드(선택) */
  summary?: ReactNode;
  /** 하단 버튼 영역. 보통 PrimaryButton */
  action?: ReactNode;
}

const ICON = {
  check: { name: 'check', size: 34, stroke: 2.5 },
  notice: { name: 'alert', size: 32, stroke: 2.4 },
  alert: { name: 'alert', size: 32, stroke: 2.4 },
  ended: { name: 'timer', size: 30, stroke: 2 },
} as const;

/** 완료/확인 화면: 원형 아이콘 + 제목 + 설명 + 요약 카드 + 하단 버튼(docs/05 §5.3) */
export function ResultScreen({ icon, title, description, summary, action }: Props) {
  const i = ICON[icon];
  return (
    <section className={styles.screen}>
      <div className={`${styles.icon} ${styles[icon]}`}>
        <Icon name={i.name} size={i.size} strokeWidth={i.stroke} />
      </div>
      <h2 className={styles.title}>{title}</h2>
      {description ? <p className={styles.description}>{description}</p> : null}
      {summary ? <div className={styles.summary}>{summary}</div> : null}
      {action}
    </section>
  );
}
