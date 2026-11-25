import { describe, expect, it } from 'vitest';

import { ApiError } from './client';
import { errorMessage, fieldErrors } from './errors';

describe('errorMessage', () => {
  it('코드별 공통 문구를 돌려준다(FE-COM-04)', () => {
    expect(errorMessage(new ApiError(404, 'NOT_FOUND'))).toBe('찾을 수 없어요.');
    expect(errorMessage(new ApiError(503, 'TRY_AGAIN'))).toBe('잠시 후 다시 시도해 주세요.');
  });

  it('모르는 오류는 기본 문구', () => {
    expect(errorMessage(new Error('boom'))).toContain('문제가 생겼어요');
  });
});

describe('fieldErrors', () => {
  const e = new ApiError(400, 'VALIDATION_ERROR', '', {
    title: '1–40자로 입력해 주세요.',
    'places[0].name': '1–30자로 입력해 주세요.',
    'places[1].activity': '1–60자로 입력해 주세요.',
  });

  it('details를 경로 그대로 돌려준다', () => {
    expect(fieldErrors(e)['places[0].name']).toBe('1–30자로 입력해 주세요.');
    expect(fieldErrors(e).title).toBe('1–40자로 입력해 주세요.');
  });

  it('prefix 아래 경로만 상대 경로로 돌려준다', () => {
    expect(fieldErrors(e, 'places[0]')).toEqual({ name: '1–30자로 입력해 주세요.' });
  });

  it('VALIDATION_ERROR가 아니면 빈 객체', () => {
    expect(fieldErrors(new ApiError(409, 'ALREADY_CLAIMED'))).toEqual({});
  });
});
