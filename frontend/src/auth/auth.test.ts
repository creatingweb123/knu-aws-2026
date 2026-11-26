import { HttpResponse, http } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { server } from '../test/server';
import { AUTH_FALLBACK, AuthError, authErrorMessage, validateAuthInput } from './authErrors';
import { devJwtService, isExpired, resetDevToken } from './devJwt';

const b64url = (o: object) =>
  btoa(JSON.stringify(o)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const jwt = (exp: number) => `${b64url({ alg: 'RS256' })}.${b64url({ sub: 'dev-suhyun', exp })}.sig`;

describe('로그인 오류 문구(FE-AUTH-01, 02, FE-Q26)', () => {
  it('Cognito 오류 이름별 문구, 원문 메시지는 쓰지 않는다', () => {
    expect(
      authErrorMessage({ name: 'NotAuthorizedException', message: 'Incorrect username or password.' }),
    ).toBe('이메일 또는 비밀번호가 맞지 않아요.');
    expect(authErrorMessage({ name: 'UserNotFoundException' })).toBe('이메일 또는 비밀번호가 맞지 않아요.');
    expect(authErrorMessage({ name: 'UsernameExistsException' })).toContain('이미 가입한 이메일');
    expect(authErrorMessage({ name: 'InvalidPasswordException' })).toContain('비밀번호 규칙');
    expect(authErrorMessage(new TypeError('Failed to fetch'))).toBe('네트워크 연결을 확인해 주세요.');
    expect(authErrorMessage(new AuthError('직접 쓴 문구'))).toBe('직접 쓴 문구');
    expect(authErrorMessage({ name: 'Weird', message: 'secret@example.com' })).toBe(AUTH_FALLBACK);
  });

  it('입력 검사: 이메일 형식, 비밀번호 8자, 가입 때만 닉네임 1–20자', () => {
    const ok = { email: 'jiyeon@example.com', password: 'Passw0rd!' };
    expect(validateAuthInput(ok, 'signIn')).toEqual({});
    expect(validateAuthInput({ ...ok, email: 'jiyeon' }, 'signIn')).toHaveProperty('email');
    expect(validateAuthInput({ ...ok, password: '1234567' }, 'signIn')).toHaveProperty('password');
    expect(validateAuthInput(ok, 'signUp')).toHaveProperty('nickname');
    expect(validateAuthInput({ ...ok, nickname: '  지연  ' }, 'signUp')).toEqual({});
    expect(validateAuthInput({ ...ok, nickname: '가'.repeat(21) }, 'signUp')).toHaveProperty('nickname');
  });
});

describe('dev JWT(FE-TECH-09, FE-Q26)', () => {
  afterEach(() => resetDevToken());

  it('POST /dev/token { userId, nickname } → 메모리 토큰', async () => {
    const token = jwt(Math.floor(Date.now() / 1000) + 3600);
    let sent: unknown = null;
    server.use(
      http.post('*/dev/token', async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ idToken: token });
      }),
    );
    expect(await devJwtService.getIdToken()).toBeNull();
    await devJwtService.devSignIn!('dev-suhyun', '수현');
    expect(sent).toEqual({ userId: 'dev-suhyun', nickname: '수현' });
    expect(await devJwtService.getIdToken()).toBe(token);
    expect(localStorage.length + sessionStorage.length).toBe(0); // 저장소에 두지 않는다(FE-NFR-05)
  });

  it('만료된 토큰은 버린다', async () => {
    server.use(
      http.post('*/dev/token', () => HttpResponse.json({ idToken: jwt(Math.floor(Date.now() / 1000) - 1) })),
    );
    await devJwtService.devSignIn!('dev-suhyun', '수현');
    expect(await devJwtService.getIdToken()).toBeNull();
    expect(isExpired('not-a-jwt')).toBe(true);
  });

  it('STAGE=local이 아니면(404) 안내 문구', async () => {
    server.use(http.post('*/dev/token', () => new HttpResponse(null, { status: 404 })));
    await expect(devJwtService.devSignIn!('dev-suhyun', '수현')).rejects.toThrow(/STAGE=local/);
  });
});
