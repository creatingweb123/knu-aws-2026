/**
 * Cognito 서비스(FE-AUTH-01, 02)의 단위 테스트. Amplify를 모킹하므로 네트워크를 쓰지 않는다.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthError, authErrorMessage } from './authErrors';

const amplify = vi.hoisted(() => ({
  configure: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  signUp: vi.fn(),
  fetchAuthSession: vi.fn(),
}));

vi.mock('aws-amplify', () => ({ Amplify: { configure: amplify.configure } }));
vi.mock('aws-amplify/auth', () => ({
  signIn: amplify.signIn,
  signOut: amplify.signOut,
  signUp: amplify.signUp,
  fetchAuthSession: amplify.fetchAuthSession,
}));

import { cognitoService } from './cognito';

function namedError(name: string): Error {
  const e = new Error(name);
  e.name = name;
  return e;
}

const DONE = { isSignedIn: true, nextStep: { signInStep: 'DONE' } };

beforeEach(() => {
  amplify.signIn.mockReset();
  amplify.signOut.mockReset();
  amplify.signUp.mockReset();
  amplify.fetchAuthSession.mockReset();
});

describe('cognitoService.signIn', () => {
  it('DONE이면 예외 없이 끝난다', async () => {
    amplify.signIn.mockResolvedValueOnce(DONE);
    await expect(cognitoService.signIn(' suhyun@example.com ', 'Pass-w0rd!')).resolves.toBeUndefined();
    // 이메일 앞뒤 공백은 잘라서 넘긴다
    expect(amplify.signIn).toHaveBeenCalledWith({ username: 'suhyun@example.com', password: 'Pass-w0rd!' });
  });

  it('추가 확인 단계가 남으면 AuthError로 안내한다', async () => {
    amplify.signIn.mockResolvedValueOnce({ isSignedIn: false, nextStep: { signInStep: 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED' } });
    const err = await cognitoService.signIn('a@example.com', 'Pass-w0rd!').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(AuthError);
    expect(authErrorMessage(err)).toBe('추가 확인이 필요한 계정이에요. 관리자에게 문의해 주세요.');
  });

  it('이미 다른 계정으로 로그인되어 있으면 로그아웃 후 한 번 더 로그인한다', async () => {
    amplify.signIn
      .mockRejectedValueOnce(namedError('UserAlreadyAuthenticatedException'))
      .mockResolvedValueOnce(DONE);
    amplify.signOut.mockResolvedValueOnce(undefined);

    await expect(cognitoService.signIn('suhyun@example.com', 'Pass-w0rd!')).resolves.toBeUndefined();
    expect(amplify.signOut).toHaveBeenCalledTimes(1);
    expect(amplify.signIn).toHaveBeenCalledTimes(2);
  });

  it('재로그인도 실패하면 그 오류를 그대로 던진다', async () => {
    amplify.signIn
      .mockRejectedValueOnce(namedError('UserAlreadyAuthenticatedException'))
      .mockRejectedValueOnce(namedError('NotAuthorizedException'));
    amplify.signOut.mockResolvedValueOnce(undefined);

    const err = await cognitoService.signIn('suhyun@example.com', 'wrong').catch((e: unknown) => e);
    expect(authErrorMessage(err)).toBe('이메일 또는 비밀번호가 맞지 않아요.');
  });

  it('처음 로그인에서 발생한 NotAuthorizedException은 재시도하지 않는다', async () => {
    amplify.signIn.mockRejectedValueOnce(namedError('NotAuthorizedException'));
    await expect(cognitoService.signIn('suhyun@example.com', 'wrong')).rejects.toMatchObject({
      name: 'NotAuthorizedException',
    });
    expect(amplify.signOut).not.toHaveBeenCalled();
  });
});

describe('cognitoService.getIdToken', () => {
  it('세션의 ID 토큰 문자열을 돌려준다', async () => {
    amplify.fetchAuthSession.mockResolvedValueOnce({ tokens: { idToken: { toString: () => 'id.token.value' } } });
    await expect(cognitoService.getIdToken()).resolves.toBe('id.token.value');
  });

  it('세션이 없으면 null', async () => {
    amplify.fetchAuthSession.mockResolvedValueOnce({ tokens: undefined });
    await expect(cognitoService.getIdToken()).resolves.toBeNull();
  });

  it('세션 조회가 실패하면 null (요청 쪽에서 401로 처리)', async () => {
    amplify.fetchAuthSession.mockRejectedValueOnce(new Error('network'));
    await expect(cognitoService.getIdToken()).resolves.toBeNull();
  });
});

describe('cognitoService.signUp', () => {
  it('닉네임 앞뒤 공백을 자르고 가입 후 자동 로그인한다', async () => {
    amplify.signUp.mockResolvedValueOnce({ isSignUpComplete: true, nextStep: { signUpStep: 'DONE' } });
    amplify.signIn.mockResolvedValueOnce(DONE);

    await cognitoService.signUp('suhyun@example.com', 'Pass-w0rd!', '  수현  ');

    expect(amplify.signUp).toHaveBeenCalledWith({
      username: 'suhyun@example.com',
      password: 'Pass-w0rd!',
      options: { userAttributes: { email: 'suhyun@example.com', nickname: '수현' } },
    });
    expect(amplify.signIn).toHaveBeenCalledWith({ username: 'suhyun@example.com', password: 'Pass-w0rd!' });
  });

  it('인증 코드 단계가 나오면 AuthError로 안내하고 로그인하지 않는다', async () => {
    amplify.signUp.mockResolvedValueOnce({ isSignUpComplete: false, nextStep: { signUpStep: 'CONFIRM_SIGN_UP' } });
    const err = await cognitoService.signUp('a@example.com', 'Pass-w0rd!', '지연').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(AuthError);
    expect(amplify.signIn).not.toHaveBeenCalled();
  });
});

describe('authErrorMessage (Cognito 오류 이름 매핑)', () => {
  it('InvalidPasswordException은 정책 안내 문구로 바꾼다', () => {
    expect(authErrorMessage(namedError('InvalidPasswordException'))).toBe(
      '비밀번호 규칙에 맞지 않아요. 8자 이상으로 대문자·소문자·숫자·특수문자를 섞어 주세요.',
    );
  });

  it('fetch 네트워크 오류(TypeError)는 네트워크 안내 문구로 바꾼다', () => {
    expect(authErrorMessage(new TypeError('Failed to fetch'))).toBe('네트워크 연결을 확인해 주세요.');
  });

  it('모르는 오류는 일반 문구로 바꾼다', () => {
    expect(authErrorMessage(namedError('SomethingElse'))).toBe(
      '로그인하지 못했어요. 잠시 후 다시 시도해 주세요.',
    );
  });
});
