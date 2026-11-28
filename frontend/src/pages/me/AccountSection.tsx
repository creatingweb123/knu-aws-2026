import { useEffect, useRef, useState } from 'react';

import { useMe } from '../../api/queries/useMe';
import { currentAuthKind } from '../../auth/authService';
import { useSignOut } from '../../auth/useSignOut';
import { Icon } from '../../components/Icon';
import { PrimaryButton } from '../../components/PrimaryButton';
import { hasLocalDrafts } from '../../state/localDrafts';
import { displayNickname, initialOf } from '../../utils/nickname';
import styles from './Me.module.css';

const NAME_FALLBACK = '닉네임 없음';

/**
 * 내 하루 맨 아래 계정 영역(docs/05 §5.2.4, FE-AUTH-04): 지금 로그인한 닉네임 + 로그아웃.
 * 목업 모드는 목업 바가 사용자를 바꾸므로 그리지 않는다.
 */
export function AccountSection() {
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);

  if (currentAuthKind() === 'mock') return null;

  const name = displayNickname(me?.nickname, NAME_FALLBACK);
  return (
    <section className={styles.account} aria-labelledby="account-title" data-testid="account">
      <h3 id="account-title" className={styles.accountTitle}>
        계정
      </h3>
      <div className={styles.accountRow}>
        <span className={styles.avatar} aria-hidden="true">
          {initialOf(name)}
        </span>
        <div className={styles.accountText}>
          <p className={styles.accountName}>{name}</p>
          <p className={styles.accountHint}>이 이름으로 로그인했어요</p>
        </div>
        <button
          ref={opener}
          type="button"
          className={styles.accountButton}
          aria-haspopup="dialog"
          onClick={() => setOpen(true)}
        >
          로그아웃
        </button>
      </div>
      {open ? (
        <LogoutSheet
          onClose={() => {
            setOpen(false);
            opener.current?.focus();
          }}
        />
      ) : null}
    </section>
  );
}

/** 로그아웃 확인 시트. 안전한 쪽("계속 쓰기")이 주 버튼이고, Esc·바깥 누르기로 닫힌다 */
function LogoutSheet({ onClose }: { onClose: () => void }) {
  const { signOut, pending } = useSignOut();
  const [drafts] = useState(hasLocalDrafts);
  const first = useRef<HTMLButtonElement>(null);
  // 키 처리기는 한 번만 붙이고 최신 값은 ref로 읽는다(다시 그릴 때 포커스가 튀지 않게)
  const latest = useRef({ onClose, pending });
  latest.current = { onClose, pending };

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !latest.current.pending) latest.current.onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className={styles.sheetLayer}>
      <div className={styles.backdrop} aria-hidden="true" onClick={pending ? undefined : onClose} />
      <div
        className={styles.sheet}
        role="dialog"
        aria-modal="true"
        aria-labelledby="logout-title"
        aria-describedby="logout-desc"
        data-testid="logout-sheet"
      >
        <span className={styles.grabber} aria-hidden="true" />
        <div className={styles.sheetHead}>
          <span className={styles.sheetIcon} aria-hidden="true">
            <Icon name="logout" size={22} strokeWidth={2} />
          </span>
          <div>
            <h2 id="logout-title" className={styles.sheetTitle}>
              로그아웃할까요?
            </h2>
            <p id="logout-desc" className={styles.sheetText}>
              이어받은 하루와 남긴 하루는 그대로 있어요. 다시 로그인하면 이어서 볼 수 있어요.
            </p>
          </div>
        </div>
        {drafts ? (
          <div className={styles.sheetWarn} role="note" data-testid="logout-drafts">
            <Icon name="info" size={18} strokeWidth={2.2} />
            <div>
              <p className={styles.sheetWarnTitle}>이 기기에 보내지 않은 글이 있어요</p>
              <p className={styles.sheetWarnText}>
                로그아웃하면 작성 중인 하루와 경험 기록 임시 글이 지워져요.
              </p>
            </div>
          </div>
        ) : null}
        <div className={styles.sheetActions}>
          <PrimaryButton ref={first} fixed={false} onClick={onClose} disabled={pending}>
            계속 쓰기
          </PrimaryButton>
          <PrimaryButton fixed={false} variant="danger" onClick={() => void signOut()} loading={pending}>
            로그아웃
          </PrimaryButton>
        </div>
      </div>
    </div>
  );
}
