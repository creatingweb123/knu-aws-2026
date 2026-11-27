/**
 * 로그인·회원가입 오류를 화면 문구로 바꾼다(FE-AUTH-01, 02, FE-Q26).
 * Cognito(Amplify) 오류는 `name`으로 구분한다. 원문 메시지에는 입력값이 섞일 수 있어 화면에 그대로 쓰지 않는다.
 */
export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuthError';
  }
}

const BY_NAME: { [name: string]: string } = {
  NotAuthorizedException: '이메일 또는 비밀번호가 맞지 않아요.',
  UserNotFoundException: '이메일 또는 비밀번호가 맞지 않아요.',
  UsernameExistsException: '이미 가입한 이메일이에요. 로그인해 주세요.',
  InvalidPasswordException:
    '비밀번호 규칙에 맞지 않아요. 8자 이상으로 대문자·소문자·숫자·특수문자를 섞어 주세요.',
  InvalidParameterException: '입력값을 확인해 주세요.',
  // PreSignUp 트리거가 닉네임 길이 등을 거절할 때(BE-AUTH-02). 원문 메시지는 쓰지 않는다
  UserLambdaValidationException: '입력값을 확인해 주세요.',
  UserNotConfirmedException: '가입 확인이 끝나지 않은 계정이에요.',
  LimitExceededException: '요청이 많아요. 잠시 후 다시 시도해 주세요.',
  TooManyRequestsException: '요청이 많아요. 잠시 후 다시 시도해 주세요.',
  TooManyFailedAttemptsException: '실패가 많아요. 잠시 후 다시 시도해 주세요.',
  NetworkError: '네트워크 연결을 확인해 주세요.',
};

export const AUTH_FALLBACK = '로그인하지 못했어요. 잠시 후 다시 시도해 주세요.';

export function authErrorMessage(e: unknown): string {
  if (e instanceof AuthError) return e.message;
  const name = (e as { name?: unknown } | null)?.name;
  if (typeof name === 'string' && BY_NAME[name]) return BY_NAME[name];
  if (e instanceof TypeError) return BY_NAME.NetworkError; // fetch 네트워크 오류
  return AUTH_FALLBACK;
}

// ---------------------------------------------------------------- 입력 검사(FE-Q26)

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const PASSWORD_MIN = 8;
export const NICKNAME_MAX = 20;

export type AuthFieldErrors = { email?: string; password?: string; nickname?: string };

export function validateAuthInput(
  input: { email: string; password: string; nickname?: string },
  mode: 'signIn' | 'signUp',
): AuthFieldErrors {
  const out: AuthFieldErrors = {};
  if (!EMAIL.test(input.email.trim())) out.email = '이메일 주소를 확인해 주세요.';
  if (input.password.length < PASSWORD_MIN) out.password = `비밀번호는 ${PASSWORD_MIN}자 이상이에요.`;
  if (mode === 'signUp') {
    const n = [...(input.nickname ?? '').trim()].length;
    if (n < 1 || n > NICKNAME_MAX) out.nickname = `닉네임은 1–${NICKNAME_MAX}자로 입력해 주세요.`;
  }
  return out;
}
