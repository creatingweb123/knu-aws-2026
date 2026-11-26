import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { isApiError } from '../../api/client';
import { errorMessage } from '../../api/errors';
import { useCompleteText } from '../../api/mutations/useCompleteText';
import { useToast } from '../../components/useToast';
import { clearLetter, loadLetter } from '../../state/letterDraft';
import { clearSending } from '../../state/sendingClock';

/**
 * 보내는 중·실패·교체 화면의 "글로 완료하기"(FE-REC-05, FE-REC-08). 서버에 저장된 글을 먼저, 없으면 임시 글을 쓴다.
 * 글이 없으면 작성 화면으로 보낸다. 완료 문구는 응답 `hasPhoto`로 정한다(FE-REC-10).
 */
export function useFinishText(claimId: string) {
  const navigate = useNavigate();
  const toast = useToast();
  const completeText = useCompleteText(claimId);
  const [ended, setEnded] = useState(false);
  const id = encodeURIComponent(claimId);

  const finish = (serverLetter: string | null | undefined) => {
    const letter = (serverLetter || loadLetter(claimId) || '').trim();
    if (!letter) {
      navigate(`/claims/${id}/record`, { replace: true });
      return;
    }
    completeText.mutate(letter, {
      onSuccess: (res) => {
        clearLetter(claimId);
        clearSending(claimId);
        navigate(`/claims/${id}/done`, { replace: true, state: { hasPhoto: res.hasPhoto } });
      },
      onError: (e) => {
        if (isApiError(e) && e.code === 'CLAIM_NOT_ACTIVE') setEnded(true);
        else toast(errorMessage(e));
      },
    });
  };

  return { finish, pending: completeText.isPending, ended };
}
