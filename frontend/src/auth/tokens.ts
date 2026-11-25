/**
 * ID 토큰 공급(FE-TECH-02). Client는 이 함수로만 토큰을 얻는다.
 *
 * - 목업 모드: 고른 목업 사용자의 목업 토큰(FE-Q10). 실제 토큰과 같은 `Authorization: Bearer`로 붙는다.
 * - 그 외: 7단계에서 Amplify `fetchAuthSession().tokens.idToken`으로 교체한다. 1단계에서는 토큰이 없다.
 *
 * 토큰은 로그에 남기지 않는다(FE-NFR-05).
 */
import { config } from '../config';
import { getMockUserId, mockTokenFor } from '../mocks/session';

export type TokenProvider = () => Promise<string | null>;

const defaultProvider: TokenProvider = async () => {
  if (config.useMock) return mockTokenFor(getMockUserId());
  return null; // 7단계: Amplify ID 토큰
};

let provider: TokenProvider = defaultProvider;

export function getIdToken(): Promise<string | null> {
  return provider();
}

/** 테스트와 7단계 Amplify 연결용 */
export function setTokenProvider(next: TokenProvider | null): void {
  provider = next ?? defaultProvider;
}
