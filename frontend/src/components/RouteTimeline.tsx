import styles from './RouteTimeline.module.css';

export interface TimelinePlace {
  name: string;
  activity: string;
  whyChosen?: string;
}

/** 방문할 장소(활동 공통): 번호 원 + 세로 연결선, 마지막 장소 원은 채운 primary(docs/05 §5.3) */
export function RouteTimeline({ places }: { places: TimelinePlace[] }) {
  return (
    <ol className={styles.timeline}>
      {places.map((p, i) => {
        const last = i === places.length - 1;
        return (
          <li key={`${i}-${p.name}`} className={styles.item}>
            <span className={`${styles.circle} ${last ? styles.filled : ''}`} aria-hidden="true">
              {i + 1}
            </span>
            <div className={styles.body}>
              <p className={styles.name}>{p.name}</p>
              <p className={styles.activity}>{p.activity}</p>
              {p.whyChosen ? <p className={styles.why}>{p.whyChosen}</p> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
