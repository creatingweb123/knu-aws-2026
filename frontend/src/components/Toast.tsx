import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import styles from './Toast.module.css';
import { ToastContext } from './useToast';
import type { ShowToast } from './useToast';

const DURATION_MS = 2500;

/** 짧은 안내 메시지. 앱 어디서든 useToast()(./useToast)로 띄운다 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback<ShowToast>((next) => {
    if (timer.current) clearTimeout(timer.current);
    setMessage(next);
    timer.current = setTimeout(() => setMessage(null), DURATION_MS);
  }, []);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className={styles.region} role="status" aria-live="polite">
        {message ? <div className={styles.toast}>{message}</div> : null}
      </div>
    </ToastContext.Provider>
  );
}
