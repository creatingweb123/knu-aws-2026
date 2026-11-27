import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { setUnauthorizedHandler } from '../api/client';

/** Client의 401 처리를 라우터 이동으로 연결한다(FE-COM-03) */
export function UnauthorizedRedirect() {
  const navigate = useNavigate();
  useEffect(() => {
    setUnauthorizedHandler((redirectTo) => {
      if (redirectTo.startsWith('/login')) return;
      navigate(`/login?redirect=${encodeURIComponent(redirectTo)}`, { replace: true });
    });
  }, [navigate]);
  return null;
}
