# Implementation Plan: frontend-stage7a-auth

- [x] 1. docs/08 FE-Q26, `aws-amplify` 설치(6.22.2)
- [x] 2. `auth/authService.ts`, `cognito.ts`, `devJwt.ts`, `devUsers.ts`, `authErrors.ts`, `redirect.ts`, `tokens.ts` 교체
  - _Requirements: 1, 2.3, 2.4_
- [x] 3. 로그인·회원가입 화면
  - _Requirements: 2, 3, 4_
- [x] 4. 테스트와 검증
  - _Requirements: 5_
- [x] 5. push `feat/fe-7-auth`

남은 7단계(7b, AWS 계정·dev 스택 필요): 실제 Cognito 로그인·가입 확인, FE-Q8 로컬 Floci 확인, `VITE_USE_MOCK=false` 전 기능 점검(FE-NFR-07), 배포 스크립트(FE-TECH-07), 기기·접근성 점검, 리허설.

## 구현 중 바뀐 것

- `npm audit`(운영 의존성)에서 react-router 6의 역슬래시 열린 리디렉션(GHSA-wrjc-x8rr-h8h6)이 나와, `?redirect=` 검사(`auth/redirect.ts`)가 역슬래시·제어 문자도 거부하게 했다. react-router 7 업그레이드는 큰 변경이라 하지 않았다.
- dev JWT 시드 인물 목록을 `devUsers.ts`로 떼어 로그인 화면이 발급 코드(`devJwt.ts`)를 정적으로 불러오지 않게 했다. 배포 빌드 산출물에 `dev/token` 문자열이 없는 것을 확인했다.
- 테스트 환경에는 `VITE_USE_MOCK`이 없어, 로그인 화면 테스트는 `setAuthService`로 방식을 넣는다. 테스트마다 `setAuthService(null)`로 되돌린다.
