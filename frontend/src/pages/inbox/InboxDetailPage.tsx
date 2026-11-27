import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { isApiError } from '../../api/client';
import { errorMessage } from '../../api/errors';
import { useMarkRead, useReply } from '../../api/mutations/useInboxActions';
import { useInboxItem } from '../../api/queries/useInbox';
import type { InboxDetailResponse } from '../../api/types';
import { PrimaryButton } from '../../components/PrimaryButton';
import { ResultScreen } from '../../components/ResultScreen';
import { TextField } from '../../components/TextField';
import { useToast } from '../../components/useToast';
import { charCount } from '../../utils/validation';
import styles from './Inbox.module.css';

const REPLY_MAX = 100;
const REPLY_ERROR = '1–100자로 입력해 주세요.';

/**
 * 7. 돌아온 하루 / 7-1 답장 보낸 상태(FE-INB-02–05).
 * 안 읽은 편지면 들어올 때 읽음 처리를 한 번 보낸다. 답장이 있으면 처음부터 7-1로 보여 준다.
 */
export function InboxDetailPage() {
  const { itemId = '' } = useParams();
  return <InboxDetail key={itemId} itemId={itemId} />;
}

function InboxDetail({ itemId }: { itemId: string }) {
  const navigate = useNavigate();
  const { data, error, isPending, refetch } = useInboxItem(itemId);
  const markRead = useMarkRead(itemId);
  const readSent = useRef(false);
  const unread = data ? !data.item.read : false;

  useEffect(() => {
    if (unread && !readSent.current) {
      readSent.current = true;
      markRead.mutate();
    }
  }, [unread, markRead]);

  const wrap = (testId: string, children: ReactNode) => <section data-testid={testId}>{children}</section>;
  const toInbox = <PrimaryButton onClick={() => navigate('/inbox')}>수신함으로</PrimaryButton>;

  if (isPending) return wrap('screen-7', <p className={styles.status}>불러오는 중…</p>);
  if (error) {
    const gone = isApiError(error) && error.code === 'NOT_FOUND';
    return wrap(
      'screen-7',
      <ResultScreen
        icon="alert"
        title={gone ? '찾을 수 없어요' : '불러오지 못했어요'}
        description={errorMessage(error)}
        action={gone ? toInbox : <PrimaryButton onClick={() => void refetch()}>다시 시도</PrimaryButton>}
      />,
    );
  }

  const replied = !!data.item.reply;
  return wrap(
    replied ? 'screen-7-1' : 'screen-7',
    <>
      <Story data={data} onPhotoError={() => void refetch()} />
      <div className={styles.reply}>
        {data.item.reply ? (
          <>
            <div className={styles.sent} data-testid="sent-reply">
              <p className={styles.cardLabel}>보낸 답장</p>
              <p className={styles.cardText}>{data.item.reply.text}</p>
            </div>
            {toInbox}
          </>
        ) : (
          <ReplyForm itemId={itemId} onSent={() => void refetch()} />
        )}
      </div>
    </>,
  );
}

function Story({ data, onPhotoError }: { data: InboxDetailResponse; onPhotoError: () => void }) {
  const { item, plan, record } = data;
  const retried = useRef(false);
  return (
    <>
      <h2 className={styles.title}>{plan.title}</h2>
      {record.photoUrl ? (
        <figure>
          <img
            className={styles.photo}
            src={record.photoUrl}
            alt={`${item.claimerNickname}님이 보낸 사진`}
            onError={() => {
              // presigned URL이 만료됐으면 상세를 한 번 다시 읽는다(FE-INB-04)
              if (!retried.current) {
                retried.current = true;
                onPhotoError();
              }
            }}
          />
          {record.photoCaption ? (
            <figcaption className={styles.caption}>{record.photoCaption}</figcaption>
          ) : null}
        </figure>
      ) : null}
      <div className={styles.cards}>
        <div className={`${styles.card} ${styles.plan}`}>
          <p className={styles.cardLabel}>내가 남긴 계획</p>
          <p className={styles.cardText}>{plan.summary}</p>
        </div>
        <div className={`${styles.card} ${styles.record}`}>
          <p className={styles.cardLabel}>{item.claimerNickname}의 방문 기록</p>
          <p className={styles.cardText}>{record.letter}</p>
        </div>
      </div>
    </>
  );
}

function ReplyForm({ itemId, onSent }: { itemId: string; onSent: () => void }) {
  const toast = useToast();
  const reply = useReply(itemId);
  const [text, setText] = useState('');
  const [error, setError] = useState<string>();

  const send = () => {
    const value = text.trim();
    const n = charCount(value);
    if (n < 1 || n > REPLY_MAX) {
      setError(REPLY_ERROR);
      return;
    }
    reply.mutate(value, {
      onSuccess: onSent,
      onError: (e) => {
        // 이미 답장했으면 서버의 답장을 다시 읽어 7-1로 보여 준다
        if (isApiError(e) && e.code === 'REPLY_ALREADY_SENT') onSent();
        else if (isApiError(e) && e.code === 'VALIDATION_ERROR') setError(REPLY_ERROR);
        else toast(errorMessage(e));
      },
    });
  };

  return (
    <>
      <TextField
        label="한 줄 답장"
        value={text}
        maxLength={REPLY_MAX}
        error={error}
        placeholder="고마운 마음을 한 줄로 남겨 보세요."
        onChange={(e) => {
          setText(e.target.value);
          if (error) setError(undefined);
        }}
      />
      <PrimaryButton onClick={send} loading={reply.isPending}>
        답장 보내기
      </PrimaryButton>
    </>
  );
}
