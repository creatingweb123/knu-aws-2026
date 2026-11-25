import { HttpResponse, http } from 'msw';

import type { Me } from '../../api/types';
import { loadDb } from '../db';
import { api, currentUser, unauthorized } from './common';

export const meHandlers = [
  http.get(api('/me'), ({ request }) => {
    const user = currentUser(request);
    if (!user) return unauthorized();
    const db = loadDb();
    const body: Me = {
      userId: user.userId,
      nickname: user.nickname,
      unreadInboxCount: db.inbox.filter((i) => i.ownerId === user.userId && !i.read).length,
    };
    return HttpResponse.json(body);
  }),
];
