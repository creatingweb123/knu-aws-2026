import { HttpResponse, http } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import { setTokenProvider } from '../auth/tokens';
import { server } from '../test/server';
import { ApiError, request, setUnauthorizedHandler } from './client';

const withToken = () => setTokenProvider(async () => 'test-token');

describe('client', () => {
  it('ID 토큰을 Authorization: Bearer로 붙인다', async () => {
    withToken();
    let auth: string | null = null;
    server.use(
      http.get('*/echo', ({ request: req }) => {
        auth = req.headers.get('Authorization');
        return HttpResponse.json({ ok: true });
      }),
    );
    await expect(request('/echo')).resolves.toEqual({ ok: true });
    expect(auth).toBe('Bearer test-token');
  });

  it('토큰이 없으면 요청하지 않고 401로 처리하고 로그인으로 보낸다', async () => {
    setTokenProvider(async () => null);
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    const hit = vi.fn();
    server.use(http.get('*/echo', () => (hit(), HttpResponse.json({}))));
    await expect(request('/echo')).rejects.toMatchObject({ status: 401, code: 'UNAUTHORIZED' });
    expect(hit).not.toHaveBeenCalled();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('JSON 본문과 추가 헤더를 보낸다', async () => {
    withToken();
    let seen: { body: unknown; type: string | null; key: string | null } | null = null;
    server.use(
      http.post('*/echo', async ({ request: req }) => {
        seen = {
          body: await req.json(),
          type: req.headers.get('Content-Type'),
          key: req.headers.get('Idempotency-Key'),
        };
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    await request('/echo', { method: 'POST', body: { a: 1 }, headers: { 'Idempotency-Key': 'k1' } });
    expect(seen).toEqual({ body: { a: 1 }, type: 'application/json', key: 'k1' });
  });

  it('계약 형식 오류를 ApiError로 바꾼다(details 포함)', async () => {
    withToken();
    server.use(
      http.post('*/echo', () =>
        HttpResponse.json(
          { error: { code: 'VALIDATION_ERROR', message: '입력값', details: { 'places[0].name': '1–30자' } } },
          { status: 400 },
        ),
      ),
    );
    const e = await request('/echo', { method: 'POST', body: {} }).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({
      status: 400,
      code: 'VALIDATION_ERROR',
      details: { 'places[0].name': '1–30자' },
    });
  });

  it('401은 본문 형식과 무관하게 UNAUTHORIZED이고 로그인으로 보낸다(API Gateway 본문)', async () => {
    withToken();
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    server.use(http.get('*/echo', () => HttpResponse.json({ message: 'Unauthorized' }, { status: 401 })));
    await expect(request('/echo')).rejects.toMatchObject({ status: 401, code: 'UNAUTHORIZED' });
    expect(onUnauthorized).toHaveBeenCalledWith('/');
  });

  it('TRY_AGAIN은 1회 다시 보내고 성공하면 결과를 돌려준다', async () => {
    withToken();
    let calls = 0;
    server.use(
      http.post('*/echo', () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ error: { code: 'TRY_AGAIN', message: '' } }, { status: 503 })
          : HttpResponse.json({ ok: true });
      }),
    );
    await expect(request('/echo', { method: 'POST', body: {} })).resolves.toEqual({ ok: true });
    expect(calls).toBe(2);
  });

  it('TRY_AGAIN이 두 번이면 ApiError를 던진다(재시도는 1회만)', async () => {
    withToken();
    let calls = 0;
    server.use(
      http.get('*/echo', () => {
        calls += 1;
        return HttpResponse.json({ error: { code: 'TRY_AGAIN', message: '' } }, { status: 503 });
      }),
    );
    await expect(request('/echo')).rejects.toMatchObject({ code: 'TRY_AGAIN' });
    expect(calls).toBe(2);
  });

  it('계약 형식이 아닌 오류 본문은 INTERNAL_ERROR(BE-Q23)', async () => {
    withToken();
    server.use(http.get('*/echo', () => new HttpResponse('Internal Server Error', { status: 500 })));
    await expect(request('/echo')).rejects.toMatchObject({ status: 500, code: 'INTERNAL_ERROR' });
  });

  it('204는 undefined를 돌려준다', async () => {
    withToken();
    server.use(http.post('*/echo', () => new HttpResponse(null, { status: 204 })));
    await expect(request('/echo', { method: 'POST' })).resolves.toBeUndefined();
  });

  it('에러 메시지에 토큰을 넣지 않는다(FE-NFR-05)', async () => {
    setTokenProvider(async () => 'secret-token-value');
    server.use(http.get('*/echo', () => new HttpResponse('x', { status: 500 })));
    const e = (await request('/echo').catch((x: unknown) => x)) as ApiError;
    expect(JSON.stringify({ m: e.message, d: e.details })).not.toContain('secret-token-value');
  });
});
