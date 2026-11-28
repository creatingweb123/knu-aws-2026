import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AuthService } from '../../auth/authService';
import { setAuthService } from '../../auth/authService';
import { setTokenProvider } from '../../auth/tokens';
import { mockTokenFor } from '../../mocks/session';
import { saveLetter } from '../../state/letterDraft';
import { renderApp } from '../../test/renderApp';

/** 로그인된 가짜 인증. signOut하면 토큰이 사라진다 */
function fakeAuth(kind: AuthService['kind'], over: Partial<AuthService> = {}) {
  let token: string | null = mockTokenFor('u-suhyun');
  const service: AuthService = {
    kind,
    getIdToken: async () => token,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(async () => {
      token = null;
    }),
    ...over,
  };
  setAuthService(service);
  setTokenProvider(() => service.getIdToken());
  return service;
}

const openSheet = async () => {
  const account = await screen.findByTestId('account');
  fireEvent.click(within(account).getByRole('button', { name: '로그아웃' }));
  return screen.findByRole('dialog', { name: '로그아웃할까요?' });
};

describe('로그아웃(FE-AUTH-04, docs/05 §5.2.4)', () => {
  it('내 하루 맨 아래에 지금 로그인한 닉네임과 로그아웃 버튼이 있다', async () => {
    fakeAuth('cognito');
    renderApp('/me');
    const account = await screen.findByTestId('account');
    expect(await within(account).findByText('수현')).toBeInTheDocument();
    expect(within(account).getByText('이 이름으로 로그인했어요')).toBeInTheDocument();
  });

  it('목업 모드에서는 계정 영역을 그리지 않는다(목업 바가 사용자를 바꾼다)', async () => {
    fakeAuth('mock');
    renderApp('/me');
    await screen.findByTestId('screen-4');
    expect(screen.queryByTestId('account')).not.toBeInTheDocument();
  });

  it('확인 시트: 보내지 않은 글이 없으면 경고 없이, "계속 쓰기"·Esc로 닫힌다', async () => {
    const auth = fakeAuth('cognito');
    renderApp('/me');
    const sheet = await openSheet();
    expect(within(sheet).getByText(/이어받은 하루와 남긴 하루는 그대로 있어요/)).toBeInTheDocument();
    expect(screen.queryByTestId('logout-drafts')).not.toBeInTheDocument();
    expect(within(sheet).getByRole('button', { name: '계속 쓰기' })).toHaveFocus();

    fireEvent.click(within(sheet).getByRole('button', { name: '계속 쓰기' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    await openSheet();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(auth.signOut).not.toHaveBeenCalled();
  });

  it('보내지 않은 글이 있으면 경고하고, 로그아웃하면 지운 뒤 로그인 화면으로 간다', async () => {
    const auth = fakeAuth('cognito');
    saveLetter('clm_x', '시장 입구에 귤 상자가 있었어요.');
    sessionStorage.setItem('haru.sending.clm_x', JSON.stringify({ startedAt: 1, uploadFailed: false }));
    const { router } = renderApp('/me');
    const sheet = await openSheet();
    expect(within(sheet).getByTestId('logout-drafts')).toHaveTextContent('이 기기에 보내지 않은 글이 있어요');

    fireEvent.click(within(sheet).getByRole('button', { name: '로그아웃' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(router.state.location.search).toBe('');
    expect(auth.signOut).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('haru.letterDraft.clm_x')).toBeNull();
    expect(sessionStorage.getItem('haru.sending.clm_x')).toBeNull();
    expect(await screen.findByText('로그아웃했어요')).toBeInTheDocument();
  });

  it('로그아웃에 실패하면 안내하고 화면에 남는다(글도 지우지 않는다)', async () => {
    fakeAuth('cognito', { signOut: vi.fn(async () => Promise.reject(new Error('network'))) });
    saveLetter('clm_x', '임시 글');
    const { router } = renderApp('/me');
    const sheet = await openSheet();
    fireEvent.click(within(sheet).getByRole('button', { name: '로그아웃' }));
    expect(await screen.findByText('로그아웃하지 못했어요. 다시 시도해 주세요.')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/me');
    expect(localStorage.getItem('haru.letterDraft.clm_x')).toBe('임시 글');
  });
});
