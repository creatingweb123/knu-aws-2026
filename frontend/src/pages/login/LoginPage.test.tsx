import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AuthService } from '../../auth/authService';
import { setAuthService } from '../../auth/authService';
import { setTokenProvider } from '../../auth/tokens';
import { renderApp } from '../../test/renderApp';
import { safeRedirect } from '../../auth/redirect';

/** 가짜 인증: 로그인하면 목업 토큰을 돌려준다(이후 화면은 MSW로 그린다) */
function fakeAuth(kind: AuthService['kind'], over: Partial<AuthService> = {}) {
  let token: string | null = null;
  const service: AuthService = {
    kind,
    getIdToken: async () => token,
    signIn: vi.fn(async () => {
      token = 'mock.u-jiyeon';
    }),
    signUp: vi.fn(async () => {
      token = 'mock.u-jiyeon';
    }),
    devSignIn: vi.fn(async () => {
      token = 'mock.u-suhyun';
    }),
    ...over,
  };
  setAuthService(service);
  setTokenProvider(() => service.getIdToken());
  return service;
}

const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe('로그인(FE-AUTH-01, 03)', () => {
  it('보호된 경로 → /login?redirect → 로그인 → 그 경로로 돌아간다', async () => {
    const auth = fakeAuth('cognito');
    const { router } = renderApp('/inbox');
    await screen.findByTestId('screen-0');
    expect(router.state.location.search).toBe(`?redirect=${encodeURIComponent('/inbox')}`);
    type('이메일', 'jiyeon@example.com');
    type('비밀번호', 'Passw0rd!');
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/inbox'));
    expect(auth.signIn).toHaveBeenCalledWith('jiyeon@example.com', 'Passw0rd!');
    expect(await screen.findByTestId('screen-6')).toBeInTheDocument();
  });

  it('입력 검사에 걸리면 요청하지 않는다', async () => {
    const auth = fakeAuth('cognito');
    renderApp('/login');
    await screen.findByTestId('screen-0');
    type('이메일', 'jiyeon');
    type('비밀번호', 'short');
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    expect(await screen.findByText('이메일 주소를 확인해 주세요.')).toBeInTheDocument();
    expect(screen.getByText('비밀번호는 8자 이상이에요.')).toBeInTheDocument();
    expect(auth.signIn).not.toHaveBeenCalled();
  });

  it('Cognito 오류는 문구로 보여 준다', async () => {
    fakeAuth('cognito', {
      signIn: vi.fn(async () => {
        throw Object.assign(new Error('Incorrect username or password.'), { name: 'NotAuthorizedException' });
      }),
    });
    renderApp('/login');
    await screen.findByTestId('screen-0');
    type('이메일', 'jiyeon@example.com');
    type('비밀번호', 'Passw0rd!');
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('이메일 또는 비밀번호가 맞지 않아요.');
  });

  it('safeRedirect: 앱 안 경로만, 역슬래시·제어 문자·//·/login은 /', () => {
    expect(safeRedirect('/inbox/clm_1?x=1')).toBe('/inbox/clm_1?x=1');
    for (const bad of [
      null,
      '',
      'https://evil.example',
      '//evil.example',
      '/\\evil.example',
      '/\tevil',
      '/login?redirect=/',
    ]) {
      expect(safeRedirect(bad)).toBe('/');
    }
  });

  it('바깥 주소로의 redirect는 둘러보기로 바꾼다', async () => {
    fakeAuth('cognito');
    const { router } = renderApp(`/login?redirect=${encodeURIComponent('//evil.example')}`);
    await screen.findByTestId('screen-0');
    type('이메일', 'jiyeon@example.com');
    type('비밀번호', 'Passw0rd!');
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
  });
});

describe('회원가입(FE-AUTH-02)', () => {
  it('이메일·비밀번호·닉네임(필수) → 가입 후 바로 로그인 상태로 돌아간다', async () => {
    const auth = fakeAuth('cognito');
    const { router } = renderApp('/login?redirect=%2Fme');
    await screen.findByTestId('screen-0');
    fireEvent.click(screen.getByRole('tab', { name: '회원가입' }));
    type('이메일', 'new@example.com');
    type('비밀번호', 'Passw0rd!');
    fireEvent.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    expect(await screen.findByText('닉네임은 1–20자로 입력해 주세요.')).toBeInTheDocument();
    type('닉네임', '새 이웃');
    fireEvent.click(screen.getByRole('button', { name: '가입하고 시작하기' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/me'));
    expect(auth.signUp).toHaveBeenCalledWith('new@example.com', 'Passw0rd!', '새 이웃');
  });
});

describe('dev-jwt 모드(FE-TECH-09)', () => {
  it('시드 인물 버튼으로 로그인', async () => {
    const auth = fakeAuth('dev-jwt');
    const { router } = renderApp('/login?redirect=%2Fme');
    fireEvent.click(await screen.findByRole('button', { name: '수현(으)로 로그인' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/me'));
    expect(auth.devSignIn).toHaveBeenCalledWith('dev-suhyun', '수현');
  });
});

describe('목업 모드', () => {
  it('목업 바 안내만 보여 준다', async () => {
    // 테스트 환경에는 VITE_USE_MOCK이 없어 목업 방식을 직접 넣는다
    fakeAuth('mock');
    setTokenProvider(async () => null);
    renderApp('/login');
    expect(await screen.findByText(/목업 바에서 사용자를 고르면/)).toBeInTheDocument();
    expect(screen.queryByLabelText('이메일')).not.toBeInTheDocument();
  });
});
