/**
 * 로컬 백엔드 모드의 dev JWT(FE-TECH-09, FE-Q8, FE-Q26). 개발 빌드 + `VITE_AUTH_MODE=dev-jwt`에서만 불러온다.
 * 어댑터(`STAGE=local`)의 `POST /dev/token { userId, nickname }` → `{ idToken }`. 토큰은 메모리에만 둔다(FE-NFR-05).
 * 로그인 전 호출이라 토큰을 붙이는 공통 클라이언트를 거치지 않는다.
 */
import { config } from '../config';
import { AuthError } from './authErrors';
import type { AuthService } from './authService';

let token: string | null = null;

/** JWT `exp`(초)가 지났으면 true. 읽을 수 없으면 만료로 본다 */
export function isExpired(jwt: string, nowMs: number = Date.now()): boolean {
  try {
    const part = jwt.split('.')[1];
    const json = atob(
      part
        .replace(/-/g, '+')
        .replace(/_/g, '/')
        .padEnd(Math.ceil(part.length / 4) * 4, '='),
    );
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp !== 'number' || exp * 1000 <= nowMs;
  } catch {
    return true;
  }
}

export async function requestDevToken(userId: string, nickname: string): Promise<string> {
  const res = await fetch(`${config.apiBaseUrl}/dev/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ userId, nickname }),
  });
  if (!res.ok) {
    throw new AuthError(
      res.status === 404
        ? 'dev JWT를 받을 수 없어요. 백엔드를 STAGE=local로 띄웠는지 확인해 주세요.'
        : 'dev JWT를 받지 못했어요.',
    );
  }
  const body = (await res.json()) as { idToken?: unknown };
  if (typeof body.idToken !== 'string') throw new AuthError('dev JWT 응답 형식이 올바르지 않아요.');
  return body.idToken;
}

export const devJwtService: AuthService = {
  kind: 'dev-jwt',
  getIdToken: async () => {
    if (token && isExpired(token)) token = null;
    return token;
  },
  signIn: async () => {
    throw new AuthError('dev-jwt 모드에서는 시드 인물을 골라 로그인해요.');
  },
  signUp: async () => {
    throw new AuthError('회원가입은 dev 스택에서 확인해요(FE-AUTH-02).');
  },
  devSignIn: async (userId, nickname) => {
    token = await requestDevToken(userId, nickname);
  },
  signOut: async () => {
    token = null;
  },
};

/** 테스트용 */
export function resetDevToken(): void {
  token = null;
}
