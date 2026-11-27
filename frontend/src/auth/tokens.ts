/**
 * ID 토큰 공급(FE-TECH-02). Client는 이 함수로만 토큰을 얻는다.
 *
 * - 목업 모드: 고른 목업 사용자의 목업 토큰(FE-Q10). 실제 토큰과 같은 `Authorization: Bearer`로 붙는다.
 * - 그 외: 인증 방식(authService)의 ID 토큰. Cognito면 Amplify `fetchAuthSession().tokens.idToken`(만료 시 자동 갱신),
 *   dev-jwt면 메모리의 dev JWT. 닉네임 클레임 때문에 액세스 토큰이 아니라 ID 토큰이다.
 *
 * 토큰은 로그에 남기지 않는다(FE-NFR-05).
 */
import { getAuthService } from './authService';

export type TokenProvider = () => Promise<string | null>;

const defaultProvider: TokenProvider = async () => (await getAuthService()).getIdToken();

let provider: TokenProvider = defaultProvider;

export function getIdToken(): Promise<string | null> {
  return provider();
}

/** 테스트용 */
export function setTokenProvider(next: TokenProvider | null): void {
  provider = next ?? defaultProvider;
}
