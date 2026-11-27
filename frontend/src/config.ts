/** 환경 변수는 여기서만 읽는다(FE-TECH-03). VITE_* 값은 번들에 들어가므로 비밀값을 두지 않는다. */

const env = import.meta.env;

export type AuthMode = 'cognito' | 'dev-jwt';

export const config = {
  apiBaseUrl: (env.VITE_API_BASE_URL ?? '').replace(/\/+$/, ''),
  awsRegion: env.VITE_AWS_REGION || 'ap-northeast-2',
  cognitoUserPoolId: env.VITE_COGNITO_USER_POOL_ID ?? '',
  cognitoClientId: env.VITE_COGNITO_CLIENT_ID ?? '',
  cognitoEndpoint: env.VITE_COGNITO_ENDPOINT ?? '',
  authMode: (env.VITE_AUTH_MODE === 'dev-jwt' ? 'dev-jwt' : 'cognito') as AuthMode,
  useMock: env.VITE_USE_MOCK === 'true',
  isDev: env.DEV,
} as const;
