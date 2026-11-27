import { useState } from 'react';
import type { ReactNode } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';

import { isApiError } from '../../api/client';
import { errorMessage, fieldErrors } from '../../api/errors';
import { useCompleteText } from '../../api/mutations/useCompleteText';
import { useSendWithPhoto } from '../../api/mutations/usePhotoSend';
import { useMyClaims } from '../../api/queries/useMyClaims';
import { useRecord } from '../../api/queries/useRecord';
import { BottomActions, PrimaryButton } from '../../components/PrimaryButton';
import { ResultScreen } from '../../components/ResultScreen';
import { TextArea } from '../../components/TextArea';
import { useToast } from '../../components/useToast';
import { clearLetter, loadLetter, saveLetter } from '../../state/letterDraft';
import { clearSending } from '../../state/sendingClock';
import { charCount } from '../../utils/validation';
import { EndedNotice } from './EndedNotice';
import { PhotoPicker } from './PhotoPicker';
import styles from './Record.module.css';

const LETTER_MAX = 1000;
const LETTER_ERROR = '1–1000자로 입력해 주세요.';

/**
 * 5. 그날의 이야기(경험 기록 작성, FE-REC-01–03, 05, 11). 4단계는 글만 보낸다(사진은 5단계).
 * 글 초기값: 서버 `record.letter` → localStorage 임시 글 → 빈 칸(FE-REC-02).
 */
export function RecordPage() {
  const { claimId = '' } = useParams();
  return <RecordEditor key={claimId} claimId={claimId} />;
}

function RecordEditor({ claimId }: { claimId: string }) {
  const navigate = useNavigate();
  const toast = useToast();
  const recordQ = useRecord(claimId);
  const claimsQ = useMyClaims('ACTIVE');
  const completeText = useCompleteText(claimId);
  const sendWithPhoto = useSendWithPhoto(claimId);
  const [edited, setEdited] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const [ended, setEnded] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoError, setPhotoError] = useState<string>();

  const item = claimsQ.data?.items.find((i) => i.claim.claimId === claimId);
  const initial = recordQ.data ? recordQ.data.record?.letter || loadLetter(claimId) || '' : '';
  const letter = edited ?? initial;

  const wrap = (children: ReactNode) => <section data-testid="screen-5">{children}</section>;

  if (recordQ.isPending) return wrap(<p className={styles.status}>불러오는 중…</p>);

  if (recordQ.error) {
    const e = recordQ.error;
    const gone = isApiError(e) && (e.code === 'NOT_FOUND' || e.code === 'FORBIDDEN');
    return wrap(
      <ResultScreen
        icon="alert"
        title={gone ? '찾을 수 없어요' : '불러오지 못했어요'}
        description={errorMessage(e)}
        action={
          gone ? (
            <PrimaryButton onClick={() => navigate('/')}>둘러보기로 가기</PrimaryButton>
          ) : (
            <PrimaryButton onClick={() => void recordQ.refetch()}>다시 시도</PrimaryButton>
          )
        }
      />,
    );
  }

  const view = recordQ.data;
  if (view.delivered) {
    return <Navigate to={`/claims/${encodeURIComponent(claimId)}/done`} replace />;
  }
  if (ended || view.claimStatus === 'ABANDONED' || view.claimStatus === 'EXPIRED') {
    return wrap(<EndedNotice claimId={claimId} letter={letter} />);
  }

  const onChange = (value: string) => {
    setEdited(value);
    saveLetter(claimId, value);
    if (error) setError(undefined);
  };

  const onComplete = () => {
    const text = letter.trim();
    const n = charCount(text);
    if (n < 1 || n > LETTER_MAX) {
      setError(LETTER_ERROR);
      return;
    }
    completeText.mutate(text, {
      onSuccess: (res) => {
        clearLetter(claimId);
        clearSending(claimId);
        navigate(`/claims/${encodeURIComponent(claimId)}/done`, {
          replace: true,
          state: { hasPhoto: res.hasPhoto },
        });
      },
      onError,
    });
  };

  const onError = (e: unknown) => {
    if (isApiError(e) && e.code === 'CLAIM_NOT_ACTIVE') setEnded(true);
    else if (isApiError(e) && e.code === 'VALIDATION_ERROR') {
      const errs = fieldErrors(e);
      if (errs.photo) setPhotoError(errs.photo);
      setError(errs.letter ?? (errs.photo ? undefined : LETTER_ERROR));
    } else toast(errorMessage(e));
  };

  /** 사진과 경험 기록 보내기(FE-REC-04): 업로드 성공·실패 모두 보내는 중으로 간다(실패는 5-2) */
  const onSendWithPhoto = () => {
    const text = letter.trim();
    const n = charCount(text);
    if (n < 1 || n > LETTER_MAX) {
      setError(LETTER_ERROR);
      return;
    }
    if (!photo) return;
    sendWithPhoto.mutate(
      { letter: text, file: photo },
      {
        onSuccess: () => navigate(`/claims/${encodeURIComponent(claimId)}/sending`, { replace: true }),
        onError,
      },
    );
  };

  const busy = completeText.isPending || sendWithPhoto.isPending;

  return wrap(
    <>
      <div className={`${styles.form} ${photo ? styles.twoButtons : ''}`}>
        {item ? <p className={styles.planTitle}>{item.plan.title}</p> : null}
        <p className={styles.to}>{item ? `${item.plan.owner.nickname}에게` : '계획자에게'}</p>
        {item ? (
          <div className={styles.question}>
            <p className={styles.questionLabel}>하루 카드의 질문</p>
            <p className={styles.questionText}>{item.plan.question}</p>
          </div>
        ) : null}
        <TextArea
          label="다녀온 이야기"
          rows={10}
          value={letter}
          maxLength={LETTER_MAX}
          error={error}
          hint="직접 해 보고 본 것, 들은 것, 느낀 것을 적어 주세요."
          onChange={(e) => onChange(e.target.value)}
        />
        <PhotoPicker
          file={photo}
          serverError={photoError}
          onChange={(f) => {
            setPhoto(f);
            setPhotoError(undefined);
          }}
        />
      </div>
      {photo ? (
        <BottomActions>
          <PrimaryButton
            fixed={false}
            onClick={onSendWithPhoto}
            loading={sendWithPhoto.isPending}
            disabled={busy}
          >
            사진과 경험 기록 보내기
          </PrimaryButton>
          <PrimaryButton
            fixed={false}
            variant="secondary"
            onClick={onComplete}
            loading={completeText.isPending}
            disabled={busy}
          >
            사진 없이 글로 완료
          </PrimaryButton>
        </BottomActions>
      ) : (
        <PrimaryButton onClick={onComplete} loading={completeText.isPending}>
          글로 완료하기
        </PrimaryButton>
      )}
    </>,
  );
}
