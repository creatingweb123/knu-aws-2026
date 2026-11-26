import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { isApiError } from '../../api/client';
import { errorMessage, fieldErrors } from '../../api/errors';
import { useReplacePhoto } from '../../api/mutations/usePhotoSend';
import { useRecord } from '../../api/queries/useRecord';
import { PageTitle } from '../../components/PageTitle';
import { BottomActions, PrimaryButton } from '../../components/PrimaryButton';
import { useToast } from '../../components/useToast';
import { loadLetter } from '../../state/letterDraft';
import { EndedNotice } from './EndedNotice';
import { PhotoPicker } from './PhotoPicker';
import styles from './Record.module.css';
import { useFinishText } from './useFinishText';

/**
 * 5-3 사진 교체(FE-REC-09): `POST /record/photo` → 새 URL로 업로드 → 보내는 중.
 * 작성한 글은 서버에 저장되어 있으므로 "글로 완료하기"도 둔다.
 */
export function PhotoReplacePage() {
  const { claimId = '' } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const recordQ = useRecord(claimId);
  const replace = useReplacePhoto(claimId);
  const finish = useFinishText(claimId);
  const [file, setFile] = useState<File | null>(null);
  const [serverError, setServerError] = useState<string>();
  const [ended, setEnded] = useState(false);
  const serverLetter = recordQ.data?.record?.letter;

  if (ended || finish.ended) {
    return (
      <section data-testid="screen-5-3">
        <EndedNotice claimId={claimId} letter={serverLetter ?? loadLetter(claimId) ?? ''} />
      </section>
    );
  }

  const onSend = () => {
    if (!file) return;
    replace.mutate(file, {
      onSuccess: () => navigate(`/claims/${encodeURIComponent(claimId)}/sending`, { replace: true }),
      onError: (e) => {
        if (isApiError(e) && e.code === 'CLAIM_NOT_ACTIVE') setEnded(true);
        else if (isApiError(e) && e.code === 'VALIDATION_ERROR')
          setServerError(fieldErrors(e).photo ?? errorMessage(e));
        else toast(errorMessage(e));
      },
    });
  };

  const busy = replace.isPending || finish.pending;
  return (
    <section data-testid="screen-5-3" className={styles.twoButtons}>
      <PageTitle
        title={'다른 사진으로\n바꿔 볼까요?'}
        description="작성한 글은 저장되어 있어요. 새 사진을 골라 주세요."
      />
      <PhotoPicker
        file={file}
        label="새 사진"
        serverError={serverError}
        onChange={(f) => {
          setFile(f);
          setServerError(undefined);
        }}
      />
      <BottomActions>
        <PrimaryButton fixed={false} onClick={onSend} disabled={!file || busy} loading={replace.isPending}>
          이 사진으로 보내기
        </PrimaryButton>
        <PrimaryButton
          fixed={false}
          variant="secondary"
          onClick={() => finish.finish(serverLetter)}
          disabled={busy}
          loading={finish.pending}
        >
          글로 완료하기
        </PrimaryButton>
      </BottomActions>
    </section>
  );
}
