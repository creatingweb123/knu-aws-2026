import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { getIdToken } from './tokens';

/** `/login`을 뺀 모든 경로를 감싼다(FE-AUTH-03, FE-Q13). 토큰이 없으면 `/login?redirect=현재 경로` */
export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [state, setState] = useState<'checking' | 'ok' | 'none'>('checking');

  useEffect(() => {
    let alive = true;
    getIdToken()
      .then((t) => alive && setState(t ? 'ok' : 'none'))
      .catch(() => alive && setState('none'));
    return () => {
      alive = false;
    };
  }, [location.pathname]);

  if (state === 'checking') return null;
  if (state === 'none') {
    const redirect = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?redirect=${encodeURIComponent(redirect)}`} replace />;
  }
  return <>{children}</>;
}
