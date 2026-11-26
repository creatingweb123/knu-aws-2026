import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { authErrorMessage, NICKNAME_MAX, validateAuthInput } from '../../auth/authErrors';
import type { AuthFieldErrors } from '../../auth/authErrors';
import { currentAuthKind, getAuthService } from '../../auth/authService';
import { safeRedirect } from '../../auth/redirect';
import { DEV_USERS } from '../../auth/devUsers';
import { PageTitle } from '../../components/PageTitle';
import { PrimaryButton } from '../../components/PrimaryButton';
import { TextField } from '../../components/TextField';
import styles from './LoginPage.module.css';

/**
 * 0. 로그인 / 회원가입(FE-AUTH-01–03). 시안 없음: 큰 제목 + 보조 문구 + 하단 주 버튼.
 * 로그인하면 `?redirect=` 경로로 돌아간다(FE-COM-03). 인증 방식은 authService가 정한다.
 */
export function LoginPage() {
  const [params] = useSearchParams();
  const redirect = safeRedirect(params.get('redirect'));
  const kind = currentAuthKind();

  return (
    <section data-testid="screen-0">
      <PageTitle
        title={'이어온 하루에\n오신 걸 환영해요'}
        description="취소된 동네 산책을 이어받고, 그날의 이야기를 돌려줘요."
      />
      {kind === 'mock' ? (
        <p className={styles.note}>
          목업 모드에서는 위쪽 목업 바에서 사용자를 고르면 로그인된 상태로 봐요.{' '}
          <Link to={redirect}>돌아가기</Link>
        </p>
      ) : kind === 'dev-jwt' ? (
        <DevJwtLogin redirect={redirect} />
      ) : (
        <CognitoLogin redirect={redirect} />
      )}
    </section>
  );
}

function useFinish(redirect: string) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // 이전 사용자(또는 401)로 받은 캐시를 버리고 돌아간다
  return () => {
    queryClient.clear();
    navigate(redirect, { replace: true });
  };
}

function CognitoLogin({ redirect }: { redirect: string }) {
  const finish = useFinish(redirect);
  const [mode, setMode] = useState<'signIn' | 'signUp'>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [nickname, setNickname] = useState('');
  const [errors, setErrors] = useState<AuthFieldErrors>({});
  const [formError, setFormError] = useState<string>();
  const [pending, setPending] = useState(false);

  const submit = async () => {
    const errs = validateAuthInput({ email, password, nickname }, mode);
    setErrors(errs);
    setFormError(undefined);
    if (Object.keys(errs).length > 0) return;
    setPending(true);
    try {
      const auth = await getAuthService();
      if (mode === 'signIn') await auth.signIn(email, password);
      else await auth.signUp(email, password, nickname);
      finish();
    } catch (e) {
      setFormError(authErrorMessage(e));
    } finally {
      setPending(false);
    }
  };

  const switchTo = (next: 'signIn' | 'signUp') => {
    setMode(next);
    setErrors({});
    setFormError(undefined);
  };

  return (
    <>
      <div className={styles.tabs} role="tablist" aria-label="로그인 또는 회원가입">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'signIn'}
          className={`${styles.tab} ${mode === 'signIn' ? styles.active : ''}`}
          onClick={() => switchTo('signIn')}
        >
          로그인
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'signUp'}
          className={`${styles.tab} ${mode === 'signUp' ? styles.active : ''}`}
          onClick={() => switchTo('signUp')}
        >
          회원가입
        </button>
      </div>
      <form
        className={styles.form}
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <TextField
          label="이메일"
          type="email"
          autoComplete="email"
          value={email}
          error={errors.email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <TextField
          label="비밀번호"
          type="password"
          autoComplete={mode === 'signIn' ? 'current-password' : 'new-password'}
          value={password}
          error={errors.password}
          hint={mode === 'signUp' ? '8자 이상, 대문자·소문자·숫자·특수문자를 섞어 주세요.' : undefined}
          onChange={(e) => setPassword(e.target.value)}
        />
        {mode === 'signUp' ? (
          <TextField
            label="닉네임"
            autoComplete="nickname"
            value={nickname}
            maxLength={NICKNAME_MAX}
            error={errors.nickname}
            hint="이어받은 사람과 계획자에게 보이는 이름이에요."
            onChange={(e) => setNickname(e.target.value)}
          />
        ) : null}
        {formError ? (
          <p className={styles.formError} role="alert">
            {formError}
          </p>
        ) : null}
        {/* 하단 고정 버튼은 폼 밖에 그려지므로 Enter 제출용 숨은 버튼을 둔다 */}
        <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
      </form>
      <PrimaryButton onClick={() => void submit()} loading={pending}>
        {mode === 'signIn' ? '로그인' : '가입하고 시작하기'}
      </PrimaryButton>
    </>
  );
}

function DevJwtLogin({ redirect }: { redirect: string }) {
  const finish = useFinish(redirect);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string>();

  const login = async (userId: string, nickname: string) => {
    setPending(userId);
    setError(undefined);
    try {
      const auth = await getAuthService();
      await auth.devSignIn?.(userId, nickname);
      finish();
    } catch (e) {
      setError(authErrorMessage(e));
    } finally {
      setPending(null);
    }
  };

  return (
    <div className={styles.form}>
      <p className={styles.note}>
        로컬 백엔드 dev JWT 모드예요(개발 빌드 전용). 시드 인물을 골라 로그인해요.
      </p>
      <div className={styles.devUsers}>
        {DEV_USERS.map((u) => (
          <PrimaryButton
            key={u.userId}
            fixed={false}
            variant="secondary"
            loading={pending === u.userId}
            disabled={pending !== null}
            onClick={() => void login(u.userId, u.nickname)}
          >
            {u.nickname}(으)로 로그인
          </PrimaryButton>
        ))}
      </div>
      {error ? (
        <p className={styles.formError} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
