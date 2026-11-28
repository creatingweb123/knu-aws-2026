/**
 * Cognito User Pool 연결(FE-TECH-02, FE-AUTH-01, 02). `aws-amplify/auth`(Auth 모듈만)를 쓴다.
 * `VITE_COGNITO_ENDPOINT`가 있으면 그 주소(로컬 Floci Cognito)로 붙는다. 동작 여부는 FE-Q8에서 확인한다.
 * 토큰 저장은 Amplify 기본 저장소에 맡긴다(FE-NFR-05). 처음 쓸 때 한 번만 설정한다.
 */
import { config } from '../config';
import { AuthError } from './authErrors';
import type { AuthService } from './authService';

type AuthModule = typeof import('aws-amplify/auth');

let ready: Promise<AuthModule> | null = null;

function amplifyAuth(): Promise<AuthModule> {
  if (!ready) {
    ready = (async () => {
      const { Amplify } = await import('aws-amplify');
      Amplify.configure({
        Auth: {
          Cognito: {
            userPoolId: config.cognitoUserPoolId,
            userPoolClientId: config.cognitoClientId,
            ...(config.cognitoEndpoint ? { userPoolEndpoint: config.cognitoEndpoint } : {}),
            loginWith: { email: true },
          },
        },
      });
      return import('aws-amplify/auth');
    })();
  }
  return ready;
}

async function signInOnce(auth: AuthModule, email: string, password: string): Promise<void> {
  const res = await auth.signIn({ username: email, password });
  if (res.nextStep.signInStep !== 'DONE') {
    // 새 비밀번호 요구 등은 MVP 화면에 없다(시드·가입 사용자는 영구 비밀번호)
    throw new AuthError('추가 확인이 필요한 계정이에요. 관리자에게 문의해 주세요.');
  }
}

export const cognitoService: AuthService = {
  kind: 'cognito',

  getIdToken: async () => {
    try {
      const auth = await amplifyAuth();
      const session = await auth.fetchAuthSession();
      return session.tokens?.idToken?.toString() ?? null;
    } catch {
      return null;
    }
  },

  signIn: async (email, password) => {
    const auth = await amplifyAuth();
    try {
      await signInOnce(auth, email.trim(), password);
    } catch (e) {
      // 다른 계정이 로그인된 채면 내보내고 한 번 더
      if ((e as { name?: string }).name !== 'UserAlreadyAuthenticatedException') throw e;
      await auth.signOut();
      await signInOnce(auth, email.trim(), password);
    }
  },

  signUp: async (email, password, nickname) => {
    const auth = await amplifyAuth();
    const username = email.trim();
    const res = await auth.signUp({
      username,
      password,
      options: { userAttributes: { email: username, nickname: nickname.trim() } },
    });
    // PreSignUp 트리거가 자동 확인하므로 인증 코드 단계가 없다(FE-AUTH-02)
    if (!res.isSignUpComplete && res.nextStep.signUpStep === 'CONFIRM_SIGN_UP') {
      throw new AuthError('가입 확인이 필요한 상태예요. 자동 확인 설정을 확인해 주세요.');
    }
    await cognitoService.signIn(username, password);
  },

  // 이 기기의 토큰만 지운다(global: false). 다른 기기의 로그인은 그대로 둔다
  signOut: async () => {
    const auth = await amplifyAuth();
    await auth.signOut();
  },
};
