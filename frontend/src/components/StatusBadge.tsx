import styles from './StatusBadge.module.css';

/** docs/05 §5.3 상태 배지 + 상세 분기(FE-PLN-02)의 배지 */
export type BadgeKind =
  'claimable' | 'claimed' | 'completed' | 'published' | 'newLetter' | 'read' | 'myClaim' | 'mine';

const LABELS: { [k in BadgeKind]: string } = {
  claimable: '이어받기 가능',
  claimed: '이어받음',
  completed: '완료',
  published: '공개',
  newLetter: '새 편지',
  read: '읽은 기록',
  myClaim: '내가 이어받은 하루',
  mine: '내가 남긴 하루',
};

export function StatusBadge({ kind }: { kind: BadgeKind }) {
  return <span className={`${styles.badge} ${styles[kind] ?? ''}`}>{LABELS[kind]}</span>;
}
