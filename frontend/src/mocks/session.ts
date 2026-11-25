/**
 * 목업 모드의 사용자와 시나리오 선택(FE-Q10, FE-Q11).
 * MSW 코드와 분리해 두어 앱 번들이 MSW를 불러오지 않게 한다.
 */

export const MOCK_USERS = [
  { userId: 'u-jiyeon', nickname: '지연' },
  { userId: 'u-suhyun', nickname: '수현' },
  { userId: 'u-minjun', nickname: '민준' },
] as const;

export type MockUserId = (typeof MOCK_USERS)[number]['userId'];

const USER_KEY = 'haru.mock.user';
const SCENARIO_KEY = 'haru.mock.scenario';
const TOKEN_PREFIX = 'mock.';
const DEFAULT_USER: MockUserId = 'u-suhyun';

function isMockUserId(v: string | null): v is MockUserId {
  return MOCK_USERS.some((u) => u.userId === v);
}

/**
 * 탭마다 다른 사용자를 쓸 수 있게 선택은 sessionStorage(탭별)에 두고,
 * localStorage에는 새 탭의 기본값만 둔다. 목업 데이터(db)는 localStorage라 탭끼리 공유된다.
 */
export function getMockUserId(): MockUserId {
  const tab = safeGet(sessionStorage, USER_KEY);
  if (isMockUserId(tab)) return tab;
  const saved = safeGet(localStorage, USER_KEY);
  return isMockUserId(saved) ? saved : DEFAULT_USER;
}

export function setMockUserId(id: MockUserId): void {
  sessionStorage.setItem(USER_KEY, id);
  localStorage.setItem(USER_KEY, id);
}

export function mockTokenFor(id: string): string {
  return `${TOKEN_PREFIX}${id}`;
}

/** `Authorization` 헤더 값에서 목업 사용자를 찾는다. 없거나 모르는 토큰이면 null */
export function mockUserFromAuthHeader(header: string | null): (typeof MOCK_USERS)[number] | null {
  const m = /^Bearer (.+)$/.exec(header ?? '');
  if (!m || !m[1].startsWith(TOKEN_PREFIX)) return null;
  const id = m[1].slice(TOKEN_PREFIX.length);
  return MOCK_USERS.find((u) => u.userId === id) ?? null;
}

/** 진입 URL의 `?mock=` 값을 탭이 닫힐 때까지 유지한다. `?mock=`(빈 값)이면 지운다 */
export function captureScenarioFromUrl(search: string = window.location.search): void {
  const params = new URLSearchParams(search);
  if (!params.has('mock')) return;
  const value = params.get('mock') ?? '';
  if (value) sessionStorage.setItem(SCENARIO_KEY, value);
  else sessionStorage.removeItem(SCENARIO_KEY);
}

export function getMockScenario(): string | null {
  return safeGet(sessionStorage, SCENARIO_KEY);
}

function safeGet(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}
