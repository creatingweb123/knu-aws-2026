import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { PrimaryButton } from '../../components/PrimaryButton';
import { ResultScreen } from '../../components/ResultScreen';
import { useToast } from '../../components/useToast';
import { clearLetter } from '../../state/letterDraft';
import styles from './Record.module.css';

/**
 * 8. 종료된 이어받기 안내(FE-REC-11). 포기·기한 만료로 이어받기가 끝났을 때 같은 경로에서 그린다.
 * 작성한 글은 복사할 수 있게 보여 주고, 임시 글은 지운다.
 */
export function EndedNotice({ claimId, letter }: { claimId: string; letter: string }) {
  const navigate = useNavigate();
  const toast = useToast();

  useEffect(() => clearLetter(claimId), [claimId]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(letter);
      toast('글을 복사했어요.');
    } catch {
      toast('복사하지 못했어요. 글을 길게 눌러 복사해 주세요.');
    }
  };

  return (
    <div data-testid="screen-8">
      <ResultScreen
        icon="alert"
        title="이 이어받기는 종료되었어요"
        description="포기했거나 기한이 지나 이어받기가 끝났어요. 작성한 글은 복사해 둘 수 있어요."
        summary={
          letter.trim() ? (
            <>
              <p>
                <strong>작성한 글</strong>
              </p>
              <p className={styles.letter}>{letter}</p>
              <button type="button" className={styles.copy} onClick={() => void copy()}>
                글 복사하기
              </button>
            </>
          ) : null
        }
        action={
          <PrimaryButton onClick={() => navigate('/', { replace: true })}>다른 하루 둘러보기</PrimaryButton>
        }
      />
    </div>
  );
}
