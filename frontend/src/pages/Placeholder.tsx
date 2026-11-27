import { useParams } from 'react-router-dom';

import { PageTitle } from '../components/PageTitle';
import styles from './Placeholder.module.css';

/** 1단계 빈 페이지. 화면 번호와 이름, 경로 값을 보여준다 */
export function Placeholder({ screen, name, stage }: { screen: string; name: string; stage: number }) {
  const params = useParams();
  const entries = Object.entries(params).filter(([k]) => k !== '*');
  return (
    <section data-testid={`screen-${screen}`}>
      <PageTitle title={`${screen}. ${name}`} description={`프론트 ${stage}단계에서 채울 화면이에요.`} />
      {entries.length > 0 ? (
        <dl className={styles.params}>
          {entries.map(([k, v]) => (
            <div key={k} className={styles.row}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}
