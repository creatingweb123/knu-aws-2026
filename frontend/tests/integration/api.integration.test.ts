/**
 * API 계약 통합 테스트(docs/03 §3.1, §3.3, §3.6). 실제 백엔드에 요청한다.
 *
 * - 로컬(`STAGE=local` 백엔드): dev JWT를 `POST /dev/token`으로 받는다. 닉네임은 시드 값 `수현`을 기대한다.
 * - dev/demo 스택: dev JWT 경로가 없으므로 브라우저에서 로그인한 뒤 ID 토큰을 복사해
 *   `INTEGRATION_ID_TOKEN` 환경 변수로 넘긴다. 이때 닉네임은 검사하지 않는다.
 *
 * 쓰기 요청은 보내지 않는다. 데이터를 만들지 않으므로 여러 번 돌려도 상태가 바뀌지 않는다.
 */
import { beforeAll, describe, expect, it } from 'vitest';

import { requestDevToken } from '../../src/auth/devJwt';
import { config } from '../../src/config';

const base = config.apiBaseUrl;
const externalToken = process.env.INTEGRATION_ID_TOKEN;
let token = '';

async function call(path: string, withAuth = true) {
  const headers: Record<string, string> = {};
  if (withAuth) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${base}${path}`, { headers });
  const body = await res.json().catch(() => null);
  return { status: res.status, body };
}

beforeAll(async () => {
  if (!base) throw new Error('VITE_API_BASE_URL이 비어 있어요. frontend/.env.local을 확인해 주세요.');
  token = externalToken || (await requestDevToken('dev-suhyun', '수현'));
});

describe('인증 (docs/03 공통 규칙)', () => {
  it('토큰 없이 /me를 부르면 401', async () => {
    const { status } = await call('/me', false);
    expect(status).toBe(401);
  });
});

describe('GET /me (docs/03 §3.1)', () => {
  it('userId, nickname, unreadInboxCount를 돌려준다', async () => {
    const { status, body } = await call('/me');
    expect(status).toBe(200);
    expect(typeof body.userId).toBe('string');
    expect(typeof body.nickname).toBe('string');
    expect(body.nickname.length).toBeGreaterThan(0);
    expect(typeof body.unreadInboxCount).toBe('number');
  });

  // 외부 ID 토큰(dev/demo)은 시드 닉네임을 모르므로 건너뛴다
  it.skipIf(Boolean(externalToken))('로컬 dev JWT로 받으면 닉네임이 시드 값 수현이다', async () => {
    const { body } = await call('/me');
    expect(body.nickname).toBe('수현');
  });
});

describe('GET /plans (docs/03 §3.3)', () => {
  it('OPEN 목록은 items 배열과 nextCursor 키를 가진다', async () => {
    const { status, body } = await call('/plans?status=OPEN&limit=20');
    expect(status).toBe(200);
    expect(Array.isArray(body.items)).toBe(true);
    expect(Object.hasOwn(body, 'nextCursor')).toBe(true);
  });

  it('목록의 각 항목은 planId와 status OPEN을 가진다', async () => {
    const { body } = await call('/plans?status=OPEN&limit=20');
    for (const plan of body.items) {
      expect(typeof plan.planId).toBe('string');
      expect(plan.status).toBe('OPEN');
    }
  });
});

describe('에러 형식 (docs/03 §3.6)', () => {
  it('없는 계획을 부르면 404와 error.code NOT_FOUND', async () => {
    const { status, body } = await call('/plans/plan_does_not_exist');
    expect(status).toBe(404);
    expect(body.error.code).toBe('NOT_FOUND');
  });
});
