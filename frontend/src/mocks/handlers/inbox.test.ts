import { describe, expect, it } from 'vitest';

import { request } from '../../api/client';
import type { InboxDetailResponse, InboxListResponse, Me } from '../../api/types';
import { setTokenProvider } from '../../auth/tokens';
import { createSeed, iso } from '../db';
import { mockTokenFor } from '../session';
import { inboxDetail, listInbox, markRead, replyInbox } from './inbox';

const NOW = Date.parse('2026-11-20T03:00:00.000Z');

describe('수신함 목업(docs/03 §3.5)', () => {
  it('목록은 요청자 것만', () => {
    const db = createSeed(NOW);
    expect(listInbox(db, 'u-jiyeon').items.map((i) => i.itemId)).toEqual(['clm_bridge_suhyun']);
    expect(listInbox(db, 'u-suhyun').items).toEqual([]);
    expect(listInbox(db, 'u-jiyeon').items[0]).not.toHaveProperty('ownerId');
  });

  it('상세는 소유자만, 사진 없으면 photoCaption null', () => {
    const db = createSeed(NOW);
    const d = inboxDetail(db, 'clm_bridge_suhyun', 'u-jiyeon', iso(NOW))!;
    expect(d.record).toMatchObject({
      letter: expect.stringContaining('노을'),
      photoUrl: null,
      photoCaption: null,
    });
    expect(d.plan.title).toBe('해 질 녘 다리 위에서');
    expect(inboxDetail(db, 'clm_bridge_suhyun', 'u-suhyun', iso(NOW))).toBeNull();
  });

  it('사진이 있으면 photoCaption = 마지막 장소 + "에서"', () => {
    const db = createSeed(NOW);
    db.inbox[0].hasPhoto = true;
    expect(inboxDetail(db, 'clm_bridge_suhyun', 'u-jiyeon', iso(NOW))?.record.photoCaption).toBe(
      '하천 다리에서',
    );
  });

  it('읽음, 답장 1회(두 번째는 REPLY_ALREADY_SENT), 길이 검증', () => {
    const db = createSeed(NOW);
    expect(markRead(db, 'clm_bridge_suhyun', 'u-suhyun')).toBe(false);
    expect(markRead(db, 'clm_bridge_suhyun', 'u-jiyeon')).toBe(true);
    expect(db.inbox[0].read).toBe(true);
    expect(replyInbox(db, 'clm_bridge_suhyun', 'u-jiyeon', { text: '' }, NOW)).toEqual({
      error: 'VALIDATION_ERROR',
    });
    expect(replyInbox(db, 'clm_bridge_suhyun', 'u-jiyeon', { text: '고마워요' }, NOW)).toEqual({
      reply: { text: '고마워요', sentAt: iso(NOW) },
    });
    expect(replyInbox(db, 'clm_bridge_suhyun', 'u-jiyeon', { text: '또' }, NOW)).toEqual({
      error: 'REPLY_ALREADY_SENT',
    });
    expect(replyInbox(db, 'clm_bridge_suhyun', 'u-suhyun', { text: '남의 것' }, NOW)).toEqual({
      error: 'NOT_FOUND',
    });
  });

  it('핸들러: 읽음 204 뒤 unreadInboxCount 0, 답장 201 → 409', async () => {
    setTokenProvider(async () => mockTokenFor('u-jiyeon'));
    const list = await request<InboxListResponse>('/inbox');
    const itemId = list.items[0].itemId;
    expect((await request<Me>('/me')).unreadInboxCount).toBe(1);
    await request(`/inbox/${itemId}/read`, { method: 'POST' });
    expect((await request<Me>('/me')).unreadInboxCount).toBe(0);
    await request(`/inbox/${itemId}/reply`, { method: 'POST', body: { text: '고마워요' } });
    await expect(
      request(`/inbox/${itemId}/reply`, { method: 'POST', body: { text: '또' } }),
    ).rejects.toMatchObject({
      status: 409,
      code: 'REPLY_ALREADY_SENT',
    });
    const d = await request<InboxDetailResponse>(`/inbox/${itemId}`);
    expect(d.item.reply?.text).toBe('고마워요');
    setTokenProvider(async () => mockTokenFor('u-suhyun'));
    await expect(request(`/inbox/${itemId}`)).rejects.toMatchObject({ status: 404 });
  });
});
