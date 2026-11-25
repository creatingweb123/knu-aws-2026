/**
 * 개발용 목업 사용자 전환 바(FE-Q10). 개발 빌드의 목업 모드에서만 Layout이 불러온다.
 * 사용자 선택은 탭별(sessionStorage)이라 탭 A는 수현, 탭 B는 민준으로 두고 같은 목업 데이터에서
 * 두 탭 경합을 재현할 수 있다. 목업 데이터는 localStorage라 탭끼리 공유된다.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { resetDb } from '../mocks/db';
import { MOCK_USERS, getMockScenario, getMockUserId, setMockUserId } from '../mocks/session';
import type { MockUserId } from '../mocks/session';
import styles from './DevMockBar.module.css';

export default function DevMockBar() {
  const queryClient = useQueryClient();
  const [userId, setUserId] = useState<MockUserId>(getMockUserId());
  const scenario = getMockScenario();

  const change = (next: MockUserId) => {
    setMockUserId(next);
    setUserId(next);
    queryClient.clear();
  };

  return (
    <div className={styles.bar} role="region" aria-label="개발용 목업 설정">
      <span className={styles.tag}>목업</span>
      <div className={styles.users} role="radiogroup" aria-label="목업 사용자">
        {MOCK_USERS.map((u) => (
          <button
            key={u.userId}
            type="button"
            role="radio"
            aria-checked={userId === u.userId}
            className={`${styles.user} ${userId === u.userId ? styles.active : ''}`}
            onClick={() => change(u.userId)}
          >
            {u.nickname}
          </button>
        ))}
      </div>
      {scenario ? <span className={styles.scenario}>?mock={scenario}</span> : null}
      <button
        type="button"
        className={styles.reset}
        onClick={() => {
          resetDb();
          queryClient.clear();
        }}
      >
        초기화
      </button>
    </div>
  );
}
