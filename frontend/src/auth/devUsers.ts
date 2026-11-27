/**
 * dev-jwt 로그인 화면의 시드 인물(FE-Q26). 로컬 Floci 시드 사용자와 별개의 dev JWT 사용자다.
 * 로그인 화면이 정적으로 불러오므로 dev JWT 발급 코드(devJwt.ts)와 분리해 둔다(배포 번들에 발급 코드가 들어가지 않게).
 */
export const DEV_USERS = [
  { userId: 'dev-jiyeon', nickname: '지연' },
  { userId: 'dev-suhyun', nickname: '수현' },
  { userId: 'dev-minjun', nickname: '민준' },
] as const;
