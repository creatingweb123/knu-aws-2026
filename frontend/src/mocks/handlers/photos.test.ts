import { describe, expect, it } from 'vitest';

import type { PutRecordResponse } from '../../api/types';
import { createSeed, iso } from '../db';
import { MOCK_PHOTO_URL, UPLOAD_ORIGIN, advancePhotos, setPhotoProcessMs } from '../photos';
import { completeClaim, getRecord, putRecord, receiveUpload, replacePhoto } from './claims';
import { inboxDetail } from './inbox';
import { claimPlan } from './plans';

const NOW = Date.parse('2026-11-20T03:00:00.000Z');
const ME = 'u-suhyun';
const JPEG = { contentType: 'image/jpeg', size: 2_480_000 };

function withPhoto() {
  const db = createSeed(NOW);
  const out = claimPlan(db, 'pln_demo', { userId: ME, nickname: '수현' }, NOW);
  if (!('claim' in out)) throw new Error('claim 없음');
  const claimId = out.claim.claimId;
  const put = putRecord(db, claimId, ME, { letter: '소금빵', photo: JPEG }, NOW) as PutRecordResponse;
  const key = new URL(put.upload!.url).pathname.slice(1);
  return { db, claimId, put, key };
}

describe('사진 목업(FE-Q24, docs/03 §3.4)', () => {
  it('PUT /record { photo } → UPLOAD_PENDING과 업로드 지시(10분, Content-Type)', () => {
    const { put, claimId, key } = withPhoto();
    expect(put.record.photoStatus).toBe('UPLOAD_PENDING');
    expect(put.upload).toMatchObject({
      method: 'PUT',
      headers: { 'Content-Type': 'image/jpeg' },
      expiresAt: iso(NOW + 600_000),
    });
    expect(put.upload!.url.startsWith(UPLOAD_ORIGIN)).toBe(true);
    expect(key).toMatch(new RegExp(`^photos/original/${claimId}/[0-9a-f-]+\\.jpg$`));
  });

  it('형식·크기 검증은 400 photo', () => {
    const db = createSeed(NOW);
    const out = claimPlan(db, 'pln_demo', { userId: ME, nickname: '수현' }, NOW);
    if (!('claim' in out)) throw new Error('claim 없음');
    for (const photo of [
      { contentType: 'image/gif', size: 10 },
      { contentType: 'image/jpeg', size: 10 * 1024 * 1024 + 1 },
      { contentType: 'image/png', size: 0 },
    ]) {
      expect(putRecord(db, out.claim.claimId, ME, { letter: '글', photo }, NOW)).toMatchObject({
        error: 'VALIDATION_ERROR',
        details: { photo: expect.any(String) },
      });
    }
  });

  it('업로드 → PROCESSING → 처리 끝: READY·전달·수신함 hasPhoto·사진 URL', () => {
    setPhotoProcessMs(3000);
    const { db, claimId, key } = withPhoto();
    expect(receiveUpload(db, key, 'image/jpeg', null, NOW)).toBe('ok');
    expect(getRecord(db, claimId, ME)).toMatchObject({ photoStatus: 'PROCESSING', delivered: false });
    expect(advancePhotos(db, NOW + 2999)).toBe(false);
    expect(advancePhotos(db, NOW + 3000)).toBe(true);
    expect(getRecord(db, claimId, ME)).toMatchObject({
      photoStatus: 'READY',
      delivered: true,
      claimStatus: 'COMPLETED',
    });
    const item = db.inbox.find((i) => i.itemId === claimId)!;
    expect(item.hasPhoto).toBe(true);
    const detail = inboxDetail(db, claimId, 'u-jiyeon', iso(NOW))!;
    expect(detail.record.photoUrl).toBe(MOCK_PHOTO_URL);
    expect(detail.record.photoCaption).toBe('하천 산책로 벤치에서');
    // 이미 사진과 함께 완료된 뒤의 TEXT_ONLY는 멱등 hasPhoto true
    expect(completeClaim(db, claimId, ME, { mode: 'TEXT_ONLY' }, NOW + 5000)).toMatchObject({
      hasPhoto: true,
    });
  });

  it('photo-fail → FAILED, 수신함 없음', () => {
    const { db, claimId, key } = withPhoto();
    receiveUpload(db, key, 'image/jpeg', 'photo-fail', NOW);
    advancePhotos(db, NOW);
    expect(getRecord(db, claimId, ME)).toMatchObject({ photoStatus: 'FAILED', delivered: false });
    expect(db.inbox.find((i) => i.itemId === claimId)).toBeUndefined();
  });

  it('Content-Type이 서명과 다르면 403, 모르는 키는 무시', () => {
    const { db, key } = withPhoto();
    expect(receiveUpload(db, key, 'image/png', null, NOW)).toBe('forbidden');
    expect(receiveUpload(db, 'photos/original/x/y.jpg', 'image/jpeg', null, NOW)).toBe('ignored');
  });

  it('교체: 새 키로 UPLOAD_PENDING, 이전 키 업로드는 무시', () => {
    const { db, claimId, key } = withPhoto();
    receiveUpload(db, key, 'image/jpeg', 'photo-fail', NOW);
    advancePhotos(db, NOW);
    const replaced = replacePhoto(db, claimId, ME, { contentType: 'image/png', size: 1000 }, NOW);
    if (!('upload' in replaced)) throw new Error('upload 없음');
    const newKey = new URL(replaced.upload.url).pathname.slice(1);
    expect(newKey).not.toBe(key);
    expect(newKey.endsWith('.png')).toBe(true);
    expect(receiveUpload(db, key, 'image/jpeg', null, NOW)).toBe('ignored');
    expect(getRecord(db, claimId, ME)).toMatchObject({ photoStatus: 'UPLOAD_PENDING' });
    expect(receiveUpload(db, newKey, 'image/png', null, NOW)).toBe('ok');
    advancePhotos(db, NOW);
    expect(getRecord(db, claimId, ME)).toMatchObject({ photoStatus: 'READY', delivered: true });
  });

  it('교체는 기록이 없으면 RECORD_REQUIRED', () => {
    const db = createSeed(NOW);
    const out = claimPlan(db, 'pln_demo', { userId: ME, nickname: '수현' }, NOW);
    if (!('claim' in out)) throw new Error('claim 없음');
    expect(replacePhoto(db, out.claim.claimId, ME, JPEG, NOW)).toEqual({ error: 'RECORD_REQUIRED' });
  });

  it('처리 중 글로 완료(TEXT_ONLY) → DISCARDED, 처리 결과는 무시', () => {
    setPhotoProcessMs(3000);
    const { db, claimId, key } = withPhoto();
    receiveUpload(db, key, 'image/jpeg', null, NOW);
    expect(completeClaim(db, claimId, ME, { mode: 'TEXT_ONLY' }, NOW + 1000)).toMatchObject({
      hasPhoto: false,
    });
    advancePhotos(db, NOW + 10_000);
    expect(getRecord(db, claimId, ME)).toMatchObject({ photoStatus: 'DISCARDED', delivered: true });
    expect(db.inbox.filter((i) => i.itemId === claimId)).toHaveLength(1);
    expect(db.inbox.find((i) => i.itemId === claimId)?.hasPhoto).toBe(false);
  });

  it('사진 없이 PUT /record하면 진행 중이던 사진은 그대로', () => {
    const { db, claimId, key } = withPhoto();
    receiveUpload(db, key, 'image/jpeg', null, NOW);
    putRecord(db, claimId, ME, { letter: '고친 글' }, NOW);
    expect(getRecord(db, claimId, ME)).toMatchObject({ photoStatus: 'PROCESSING' });
  });
});
