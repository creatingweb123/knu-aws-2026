import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { useRecord } from '../../api/queries/useRecord';
import { BottomActions, PrimaryButton } from '../../components/PrimaryButton';
import { ResultScreen } from '../../components/ResultScreen';
import { clearLetter, loadLetter } from '../../state/letterDraft';
import { clearSending, loadSending } from '../../state/sendingClock';
import { EndedNotice } from './EndedNotice';
import styles from './Record.module.css';
import { decideSendingState } from './sendingState';
import { useFinishText } from './useFinishText';

const POLL_MS = 2000;

/**
 * 5-1 보내는 중 / 5-2 사진 처리 실패(같은 경로, FE-REC-06–08).
 * `GET /record`를 2초 간격으로 폴링하고 `decideSendingState`로 분기한다.
 * 기준 시각은 업로드 시작 때 저장한 `haru.sending.{claimId}`, 없으면 `record.updatedAt`(FE-Q23).
 */
export function SendingPage() {
  const { claimId = '' } = useParams();
  return <Sending key={claimId} claimId={claimId} />;
}

function Sending({ claimId }: { claimId: string }) {
  const navigate = useNavigate();
  const recordQ = useRecord(claimId, { refetchInterval: POLL_MS });
  const finish = useFinishText(claimId);
  const [clock] = useState(() => loadSending(claimId));
  const now = useNow(1000);

  const base = clock?.startedAt ?? (recordQ.data?.record ? Date.parse(recordQ.data.record.updatedAt) : now);
  const state = decideSendingState(
    { data: recordQ.data, error: recordQ.error },
    now - base,
    clock?.uploadFailed,
  );
  const serverLetter = recordQ.data?.record?.letter;
  const id = encodeURIComponent(claimId);

  const doneWithPhoto = state.kind === 'done' ? state.hasPhoto : null;
  useEffect(() => {
    if (doneWithPhoto === null) return;
    clearLetter(claimId);
    clearSending(claimId);
    navigate(`/claims/${id}/done`, { replace: true, state: { hasPhoto: doneWithPhoto } });
  }, [doneWithPhoto, claimId, id, navigate]);

  const wrap = (children: ReactNode) => <section data-testid="screen-5-1">{children}</section>;

  if (state.kind === 'ended' || finish.ended) {
    return wrap(<EndedNotice claimId={claimId} letter={serverLetter ?? loadLetter(claimId) ?? ''} />);
  }

  if (state.kind === 'failed') {
    return wrap(
      <div data-testid="screen-5-2">
        <ResultScreen
          icon="alert"
          title="사진을 보내지 못했어요"
          description="작성한 글은 저장되어 있어요. 사진을 바꾸거나 글로 먼저 완료할 수 있어요."
          action={
            <BottomActions>
              <PrimaryButton
                fixed={false}
                onClick={() => navigate(`/claims/${id}/record/photo`)}
                disabled={finish.pending}
              >
                사진 바꾸기
              </PrimaryButton>
              <PrimaryButton
                fixed={false}
                variant="secondary"
                onClick={() => finish.finish(serverLetter)}
                loading={finish.pending}
              >
                글로 완료하기
              </PrimaryButton>
            </BottomActions>
          }
        />
      </div>,
    );
  }

  const emphasize = state.kind === 'waiting' && state.emphasize;
  return wrap(
    <>
      <div className={styles.sending} role="status" aria-live="polite">
        <span className={styles.spinner} aria-hidden="true" />
        <p className={styles.sendingTitle}>보내는 중이에요</p>
        <p className={styles.sendingText}>사진을 정리해서 방문 기록과 함께 보내고 있어요.</p>
        {emphasize ? (
          <p className={styles.slow} data-testid="sending-slow">
            사진 처리가 늦어지고 있어요. 글로 먼저 완료할 수 있어요.
          </p>
        ) : null}
      </div>
      <PrimaryButton
        variant={emphasize ? 'primary' : 'secondary'}
        onClick={() => finish.finish(serverLetter)}
        loading={finish.pending}
      >
        글로 완료하기
      </PrimaryButton>
    </>,
  );
}

/** 경과 시간을 다시 그리기 위한 시계(폴링 응답이 같으면 다시 그리지 않으므로 따로 둔다) */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}
