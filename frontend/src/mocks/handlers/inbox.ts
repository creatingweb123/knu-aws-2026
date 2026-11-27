/**
 * 수신함 목업(docs/03 §3.5). 요청자(`ownerId`) 것만 보이고, 아니면 404.
 * 답장은 1회: 이미 있으면 409 REPLY_ALREADY_SENT. `photoCaption`은 저장하지 않고 응답 때 만든다.
 * `photoUrl`은 사진 경로가 생기는 5단계 전까지 null이다.
 */
import { HttpResponse, http } from 'msw';

import type { InboxDetailResponse, InboxItem, InboxListResponse, ReplyResponse } from '../../api/types';
import type { DbInboxItem, MockDb } from '../db';
import { iso } from '../db';
import { MOCK_PHOTO_URL } from '../photos';
import { withDb } from './claims';
import { api, apiError, currentUser, unauthorized } from './common';
import { toPlan } from './plans';

export function toInboxItem(i: DbInboxItem): InboxItem {
  return {
    itemId: i.itemId,
    planId: i.planId,
    planTitle: i.planTitle,
    claimerNickname: i.claimerNickname,
    hasPhoto: i.hasPhoto,
    read: i.read,
    createdAt: i.createdAt,
    reply: i.reply ? { ...i.reply } : null,
  };
}

const find = (db: MockDb, itemId: string, userId: string) =>
  db.inbox.find((i) => i.itemId === itemId && i.ownerId === userId);

export function listInbox(db: MockDb, userId: string): InboxListResponse {
  return {
    items: db.inbox
      .filter((i) => i.ownerId === userId)
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1))
      .map(toInboxItem),
  };
}

export function inboxDetail(
  db: MockDb,
  itemId: string,
  userId: string,
  nowIso: string,
): InboxDetailResponse | null {
  const item = find(db, itemId, userId);
  if (!item) return null;
  const plan = db.plans.find((p) => p.planId === item.planId);
  const record = db.records.find((r) => r.claimId === item.itemId);
  if (!plan || !record || !record.deliveredAt) return null;
  const last = plan.places[plan.places.length - 1];
  return {
    item: toInboxItem(item),
    plan: toPlan(plan, userId, nowIso),
    record: {
      letter: record.letter,
      deliveredAt: record.deliveredAt,
      photoUrl: item.hasPhoto ? MOCK_PHOTO_URL : null,
      photoCaption: item.hasPhoto && last ? `${last.name}에서` : null,
    },
  };
}

export function markRead(db: MockDb, itemId: string, userId: string): boolean {
  const item = find(db, itemId, userId);
  if (!item) return false;
  item.read = true;
  return true;
}

export type ReplyOutcome = ReplyResponse | { error: 'NOT_FOUND' | 'REPLY_ALREADY_SENT' | 'VALIDATION_ERROR' };

export function replyInbox(
  db: MockDb,
  itemId: string,
  userId: string,
  body: unknown,
  nowMs: number,
): ReplyOutcome {
  const item = find(db, itemId, userId);
  if (!item) return { error: 'NOT_FOUND' };
  const text = (body as { text?: unknown } | null)?.text;
  if (typeof text !== 'string' || [...text].length < 1 || [...text].length > 100)
    return { error: 'VALIDATION_ERROR' };
  if (item.reply) return { error: 'REPLY_ALREADY_SENT' };
  item.reply = { text, sentAt: iso(nowMs) };
  return { reply: { ...item.reply } };
}

export const inboxHandlers = [
  http.get(api('/inbox'), ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    return HttpResponse.json(withDb((db) => listInbox(db, user.userId)));
  }),

  http.get(api('/inbox/:itemId'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const detail = withDb((db, now) => inboxDetail(db, String(params.itemId), user.userId, iso(now)));
    return detail ? HttpResponse.json(detail) : apiError('NOT_FOUND', '찾을 수 없어요.');
  }),

  http.post(api('/inbox/:itemId/read'), ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const ok = withDb((db) => markRead(db, String(params.itemId), user.userId));
    return ok ? new HttpResponse(null, { status: 204 }) : apiError('NOT_FOUND', '찾을 수 없어요.');
  }),

  http.post(api('/inbox/:itemId/reply'), async ({ request, params }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    let body: unknown = null;
    try {
      body = await request.json();
    } catch {
      body = null;
    }
    const out = withDb((db) => replyInbox(db, String(params.itemId), user.userId, body, Date.now()));
    if ('reply' in out) return HttpResponse.json(out, { status: 201 });
    if (out.error === 'VALIDATION_ERROR') {
      return apiError('VALIDATION_ERROR', '입력값을 확인해 주세요.', 400, {
        text: '1–100자로 입력해 주세요.',
      });
    }
    if (out.error === 'NOT_FOUND') return apiError('NOT_FOUND', '찾을 수 없어요.');
    return apiError('REPLY_ALREADY_SENT', '이미 답장을 보냈어요.');
  }),
];
