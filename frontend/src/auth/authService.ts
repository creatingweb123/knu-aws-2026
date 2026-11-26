/**
 * 인증 방식 선택(FE-TECH-02, 08, 09). 환경 변수로만 바꾼다.
 * - 목업(VITE_USE_MOCK=true): 목업 바의 사용자(FE-Q10). 로그인 화면은 안내만
 * - dev-jwt(개발 빌드 + VITE_AUTH_MODE=dev-jwt): 로컬 어댑터 `POST /dev/token`(FE-Q26). 배포 빌드에는 들어가지 않는다
 * - 그 외: Amplify(`aws-amplify/auth`)로 Cognito User Pool
 * Amplify와 dev JWT 모듈은 필요할 때만 불러온다(목업 번들·배포 번들 크기).
 */
import { config } from '../config';
import { getMockUserId, mockTokenFor } from '../mocks/session';
import { AuthError } from './authErrors';

export type AuthKind = 'mock' | 'dev-jwt' | 'cognito';

export interface AuthService {
  kind: AuthKind;
  getIdToken(): Promise<string | null>;
  signIn(email: string, password: string): Promise<void>;
  /** 가입 후 바로 로그인한다(PreSignUp 자동 확인, FE-AUTH-02) */
  signUp(email: string, password: string, nickname: string): Promise<void>;
  /** dev-jwt 전용 */
  devSignIn?(userId: string, nickname: string): Promise<void>;
}

const mockService: AuthService = {
  kind: 'mock',
  getIdToken: async () => mockTokenFor(getMockUserId()),
  signIn: async () => {
    throw new AuthError('목업 모드에서는 위쪽 목업 바에서 사용자를 골라 주세요.');
  },
  signUp: async () => {
    throw new AuthError('목업 모드에서는 위쪽 목업 바에서 사용자를 골라 주세요.');
  },
};

let override: AuthService | null = null;

/** 테스트용 */
export function setAuthService(next: AuthService | null): void {
  override = next;
}

/** 로그인 화면이 어떤 폼을 그릴지(동기) */
export function currentAuthKind(): AuthKind {
  if (override) return override.kind;
  if (config.useMock) return 'mock';
  if (import.meta.env.DEV && config.authMode === 'dev-jwt') return 'dev-jwt';
  return 'cognito';
}

export async function getAuthService(): Promise<AuthService> {
  if (override) return override;
  if (config.useMock) return mockService;
  // import.meta.env.DEV는 배포 빌드에서 false로 바뀌어 이 분기와 dev JWT 모듈이 빠진다(FE-TECH-09)
  if (import.meta.env.DEV && config.authMode === 'dev-jwt') return (await import('./devJwt')).devJwtService;
  return (await import('./cognito')).cognitoService;
}
