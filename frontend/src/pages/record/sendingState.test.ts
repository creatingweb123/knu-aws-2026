import { describe, expect, it } from 'vitest';

import { ApiError } from '../../api/client';
import type { GetRecordResponse, PhotoStatus } from '../../api/types';
import { validatePhoto } from '../../utils/photo';
import { decideSendingState } from './sendingState';

const view = (photoStatus: PhotoStatus, over: Partial<GetRecordResponse> = {}): GetRecordResponse => ({
  record: {
    claimId: 'c',
    planId: 'p',
    letter: '글',
    photoStatus,
    updatedAt: '2026-11-20T03:00:00.000Z',
    deliveredAt: null,
  },
  claimStatus: 'ACTIVE',
  delivered: false,
  photoStatus,
  ...over,
});

describe('decideSendingState(FE-REC-06, 07, FE-Q23)', () => {
  it('1. delivered → 완료, 사진 문구는 READY일 때만', () => {
    expect(decideSendingState({ data: view('READY', { delivered: true }) }, 0)).toEqual({
      kind: 'done',
      hasPhoto: true,
    });
    expect(decideSendingState({ data: view('DISCARDED', { delivered: true }) }, 0)).toEqual({
      kind: 'done',
      hasPhoto: false,
    });
  });

  it('delivered가 종료·실패보다 먼저', () => {
    expect(decideSendingState({ data: view('READY', { delivered: true }) }, 99_000, true).kind).toBe('done');
  });

  it('2. ABANDONED·EXPIRED, 403·404·409 → 종료', () => {
    expect(decideSendingState({ data: view('DISCARDED', { claimStatus: 'ABANDONED' }) }, 0).kind).toBe(
      'ended',
    );
    expect(decideSendingState({ data: view('PROCESSING', { claimStatus: 'EXPIRED' }) }, 0).kind).toBe(
      'ended',
    );
    for (const [status, code] of [
      [403, 'FORBIDDEN'],
      [404, 'NOT_FOUND'],
      [409, 'CLAIM_NOT_ACTIVE'],
    ] as const) {
      expect(decideSendingState({ error: new ApiError(status, code) }, 0).kind).toBe('ended');
    }
  });

  it('3. FAILED·업로드 실패·보낼 사진 없음 → 실패', () => {
    expect(decideSendingState({ data: view('FAILED') }, 0).kind).toBe('failed');
    expect(decideSendingState({ data: view('UPLOAD_PENDING') }, 0, true).kind).toBe('failed');
    expect(decideSendingState({}, 0, true).kind).toBe('failed');
    expect(decideSendingState({ data: view('NONE') }, 0).kind).toBe('failed');
    expect(decideSendingState({ data: view('DISCARDED') }, 0).kind).toBe('failed');
  });

  it('UPLOAD_PENDING은 30초까지 대기, 넘으면 실패', () => {
    expect(decideSendingState({ data: view('UPLOAD_PENDING') }, 30_000).kind).toBe('waiting');
    expect(decideSendingState({ data: view('UPLOAD_PENDING') }, 30_001).kind).toBe('failed');
    // PROCESSING은 30초 기준을 쓰지 않는다
    expect(decideSendingState({ data: view('PROCESSING') }, 45_000)).toEqual({
      kind: 'waiting',
      emphasize: false,
    });
  });

  it('4. 60초부터 글로 완료하기 강조', () => {
    expect(decideSendingState({ data: view('PROCESSING') }, 59_999)).toEqual({
      kind: 'waiting',
      emphasize: false,
    });
    expect(decideSendingState({ data: view('PROCESSING') }, 60_000)).toEqual({
      kind: 'waiting',
      emphasize: true,
    });
  });

  it('데이터 없이 네트워크 오류·5xx면 대기를 유지한다', () => {
    expect(decideSendingState({ error: new TypeError('network') }, 0).kind).toBe('waiting');
    expect(decideSendingState({ error: new ApiError(503, 'TRY_AGAIN') }, 0).kind).toBe('waiting');
  });
});

describe('사진 1차 검사(FE-REC-03)', () => {
  const file = (type: string, size: number) => {
    const f = new File(['x'], 'p', { type });
    Object.defineProperty(f, 'size', { value: size });
    return f;
  };

  it('JPEG·PNG 10MB 이하만', () => {
    expect(validatePhoto(file('image/jpeg', 10 * 1024 * 1024))).toBeNull();
    expect(validatePhoto(file('image/png', 1))).toBeNull();
    expect(validatePhoto(file('image/jpeg', 10 * 1024 * 1024 + 1))).not.toBeNull();
    expect(validatePhoto(file('image/gif', 10))).not.toBeNull();
    expect(validatePhoto(file('image/heic', 10))).not.toBeNull();
    expect(validatePhoto(file('image/jpeg', 0))).not.toBeNull();
  });
});
