import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useToast } from '../components/useToast';
import { clearLocalDrafts } from '../state/localDrafts';
import { getAuthService } from './authService';

/**
 * 로그아웃(docs/05 §5.2.4, FE-AUTH-04): 토큰 삭제 → 이 기기의 작성 중 글과 조회 캐시 삭제 → 로그인 화면.
 * 다른 사람이 이어서 로그인할 수 있으므로 redirect는 붙이지 않는다.
 */
export function useSignOut() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [pending, setPending] = useState(false);

  const signOut = async () => {
    setPending(true);
    try {
      await (await getAuthService()).signOut();
    } catch {
      setPending(false);
      toast('로그아웃하지 못했어요. 다시 시도해 주세요.');
      return;
    }
    clearLocalDrafts();
    queryClient.clear();
    navigate('/login', { replace: true });
    toast('로그아웃했어요');
  };

  return { signOut, pending };
}
