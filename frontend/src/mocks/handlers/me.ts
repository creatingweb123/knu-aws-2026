import { HttpResponse, http } from 'msw';

import type { Me } from '../../api/types';
import { withDb } from './claims';
import { api, currentUser, unauthorized } from './common';

export const meHandlers = [
  http.get(api('/me'), ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    // 사진 처리로 완료된 수신함 항목이 헤더 점에 바로 보이도록 처리 결과를 먼저 반영한다
    const unread = withDb((db) => db.inbox.filter((i) => i.ownerId === user.userId && !i.read).length);
    const body: Me = { userId: user.userId, nickname: user.nickname, unreadInboxCount: unread };
    return HttpResponse.json(body);
  }),
];
