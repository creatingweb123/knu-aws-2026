/**
 * 로그인 뒤 돌아갈 `?redirect=` 경로(FE-COM-03). 앱 안 경로만 받는다(열린 리디렉션 방지).
 * 브라우저는 `\`를 `/`로 읽으므로 `/\evil.example`도 바깥 주소가 된다(react-router GHSA-wrjc-x8rr-h8h6와 같은 경로).
 * 역슬래시·제어 문자, `//`, `/login`으로 시작하는 값은 `/`로 바꾼다.
 */
export function safeRedirect(raw: string | null): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/login')) return '/';
  // eslint-disable-next-line no-control-regex
  if (/[\\\u0000-\u001f]/.test(raw)) return '/';
  return raw;
}
