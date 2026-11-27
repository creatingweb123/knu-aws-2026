# Requirements: frontend-stage7a-auth

## Introduction

프론트엔드 7단계(docs/07 §7.4) 중 AWS 계정 없이 할 수 있는 부분이다. 로그인·회원가입 화면(0)과 Amplify(Cognito) 연동 코드, 로컬 백엔드 dev JWT 모드를 만든다. 요구사항은 FE-AUTH-01–03, FE-TECH-02, 08, 09, FE-COM-03, FE-NFR-05다. 실제 Cognito(dev 스택)와 로컬 Floci Cognito 연결 확인(FE-Q8), `VITE_USE_MOCK=false` 전 기능 점검, 배포(FE-TECH-07), 리허설은 7단계 나머지(7b)로 남긴다. 문서에 없는 결정은 docs/08 FE-Q26을 따른다.

## Requirements

### Requirement 1: 인증 방식 선택 [FE-TECH-02, 08, 09]

1. THE 앱 SHALL 환경 변수로만 인증 방식을 고른다: `VITE_USE_MOCK=true` → 목업 사용자(FE-Q10), 개발 빌드이고 `VITE_AUTH_MODE=dev-jwt` → dev JWT, 그 외 → Amplify Cognito.
2. THE Cognito 방식 SHALL `aws-amplify`를 `Auth.Cognito { userPoolId, userPoolClientId, loginWith.email }`로 설정하고, `VITE_COGNITO_ENDPOINT`가 있으면 `userPoolEndpoint`로 넘긴다. 처음 쓸 때 한 번만 설정하고, 목업 모드에서는 불러오지 않는다.
3. THE API 요청 SHALL `fetchAuthSession().tokens.idToken`(ID 토큰, 만료 시 Amplify가 갱신)을 `Authorization: Bearer`로 붙인다. 세션이 없거나 오류면 토큰 없음으로 본다.
4. THE dev JWT 방식 SHALL 어댑터 `POST {VITE_API_BASE_URL}/dev/token { userId, nickname }` → `{ idToken }`을 메모리에만 두고, `exp`가 지났으면 버린다. 이 코드는 `import.meta.env.DEV` 분기로만 불러와 배포 빌드에 들어가지 않는다.

### Requirement 2: 로그인 [FE-AUTH-01, FE-AUTH-03, FE-COM-03]

1. THE 로그인 화면 SHALL 이메일·비밀번호 입력과 "로그인" 버튼을 둔다. 이메일 형식·비밀번호 8자 이상을 먼저 검사한다(FE-Q26).
2. WHEN 로그인이 성공하면 THE 화면 SHALL 쿼리 캐시를 비우고 `?redirect=` 경로로 replace 이동한다. `redirect`가 `/`로 시작하지 않거나 `//`·`/login`으로 시작하면 `/`로 간다.
3. IF 실패하면 THE 화면 SHALL Cognito 오류 이름으로 정한 문구를 보여 준다(원문 메시지는 쓰지 않는다).
4. 이미 다른 계정이 로그인돼 있으면(`UserAlreadyAuthenticatedException`) 내보내고 다시 로그인한다.

### Requirement 3: 회원가입 [FE-AUTH-02]

1. THE 회원가입 탭 SHALL 이메일·비밀번호·닉네임(필수, 1–20자)을 받는다. 인증 코드 화면은 없다.
2. WHEN 가입이 끝나면 THE 화면 SHALL 같은 이메일·비밀번호로 바로 로그인하고 2.2처럼 이동한다. 가입 확인이 남아 있으면(자동 확인 미설정) 안내 문구를 보여 준다.

### Requirement 4: dev JWT 로그인 [FE-TECH-09, FE-Q26]

1. WHILE dev-jwt 모드이면 THE 로그인 화면 SHALL 시드 인물 버튼(지연·수현·민준)을 보여 주고, 누르면 dev JWT를 받아 2.2처럼 이동한다. 404면 "STAGE=local" 확인 안내.

### Requirement 5: 검증

1. THE 테스트 SHALL 오류 문구·입력 검사, dev JWT 발급·만료·404, 로그인 화면(redirect 왕복, 입력 검사, 오류, 열린 리디렉션 방지, 회원가입, dev-jwt, 목업 안내)을 확인한다.
2. THE Frontend SHALL lint, test, build, format:check를 통과하고, 목업 모드 번들에 Amplify가 들어가지 않는다(동적 import).

## 정합성 갱신(2026-11-27, spec backend-frontend-alignment)

- 가입 닉네임 1–20자는 프론트 사전 검사와 백엔드 PreSignUp 검사가 같은 규칙을 쓴다(BE-Q139). PreSignUp 거절 `UserLambdaValidationException`은 "입력값을 확인해 주세요."로 안내한다.
