/**
 * 공통 API 클라이언트(FE-COM-05). 모든 요청은 여기를 거친다.
 *
 * - ID 토큰을 `Authorization: Bearer`로 붙인다. 토큰이 없으면 요청하지 않고 401로 처리한다.
 * - 4xx/5xx의 `{ error: { code, message, details } }`를 ApiError로 바꾼다. 화면은 `error.code`로만 분기한다.
 * - 401은 본문과 무관하게 상태 코드로 판단한다(API Gateway authorizer 401은 본문 형식이 다르다, docs/03 §3.6).
 * - 503 `TRY_AGAIN`은 같은 요청을 1회 다시 보낸다(FE-COM-04).
 * - 토큰과 presigned URL은 로그·에러 메시지에 남기지 않는다(FE-NFR-05).
 */
import { getIdToken } from '../auth/tokens';
import { config } from '../config';
import type { ErrorBody, ErrorCode } from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  readonly details?: Record<string, string>;

  constructor(status: number, code: ErrorCode, message = '', details?: Record<string, string>) {
    super(message || code);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

export type HttpMethod = 'GET' | 'POST' | 'PUT';

export interface RequestOptions {
  method?: HttpMethod;
  body?: unknown;
  headers?: { [name: string]: string };
  /** 클라이언트 타임아웃. AI 세션은 서버 상한(30초)보다 길게 준다(FE-CRT-04) */
  timeoutMs?: number;
  signal?: AbortSignal;
}

type UnauthorizedHandler = (redirectTo: string) => void;

let onUnauthorized: UnauthorizedHandler = (redirectTo) => {
  window.location.assign(`/login?redirect=${encodeURIComponent(redirectTo)}`);
};

/** 라우터가 `navigate`로 처리하도록 바꾼다(테스트에서도 바꾼다) */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  onUnauthorized = handler;
}

function currentPath(): string {
  const { pathname, search } = window.location;
  return `${pathname}${search}`;
}

const DEFAULT_TIMEOUT_MS = 15_000;

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await send<T>(path, options);
  } catch (e) {
    if (isApiError(e) && e.code === 'TRY_AGAIN') return send<T>(path, options);
    throw e;
  }
}

async function send<T>(path: string, options: RequestOptions): Promise<T> {
  const token = await getIdToken();
  if (!token) throw unauthorized();

  const headers: { [name: string]: string } = { Authorization: `Bearer ${token}`, ...options.headers };
  let body: string | undefined;
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = options.signal ? anySignal([options.signal, timeout.signal]) : timeout.signal;

  let res: Response;
  try {
    res = await fetch(`${config.apiBaseUrl}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body,
      signal,
    });
  } finally {
    clearTimeout(timer);
  }

  if (res.status === 401) throw unauthorized();
  if (res.status === 204) return undefined as T;

  const data: unknown = await readJson(res);
  if (!res.ok) throw toApiError(res.status, data);
  return data as T;
}

function unauthorized(): ApiError {
  onUnauthorized(currentPath());
  return new ApiError(401, 'UNAUTHORIZED');
}

async function readJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function toApiError(status: number, data: unknown): ApiError {
  const err = (data as Partial<ErrorBody> | null)?.error;
  if (err && typeof err.code === 'string') {
    return new ApiError(status, err.code, err.message ?? '', err.details);
  }
  return new ApiError(status, 'INTERNAL_ERROR');
}

function anySignal(signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController();
  for (const s of signals) {
    if (s.aborted) {
      controller.abort();
      break;
    }
    s.addEventListener('abort', () => controller.abort(), { once: true });
  }
  return controller.signal;
}
