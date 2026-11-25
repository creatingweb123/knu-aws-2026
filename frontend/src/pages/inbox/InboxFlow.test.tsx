import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';

import { loadDb, updateDb } from '../../mocks/db';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';

const ITEM = 'clm_bridge_suhyun';

describe('수신함(FE-INB-01)', () => {
  it('안 읽은 편지: 새 편지 배지·점, 보낸 사람 문구', async () => {
    renderApp('/inbox', 'u-jiyeon');
    const list = await screen.findByTestId('inbox-list');
    const row = within(list).getByRole('link');
    expect(row).toHaveAttribute('href', `/inbox/${ITEM}`);
    expect(row).toHaveTextContent('새 편지');
    expect(row).toHaveTextContent('해 질 녘 다리 위에서');
    expect(row).toHaveTextContent('수현님이 방문 기록을 보냈어요');
    expect(within(row).getByTestId('item-unread-dot')).toBeInTheDocument();
  });

  it('비어 있으면 안내', async () => {
    renderApp('/inbox', 'u-suhyun');
    expect(await screen.findByTestId('inbox-empty')).toHaveTextContent('아직 돌아온 하루가 없어요');
  });
});

describe('돌아온 하루·답장(FE-INB-02–05)', () => {
  it('들어오면 읽음 처리, 헤더 점이 사라진다', async () => {
    renderApp(`/inbox/${ITEM}`, 'u-jiyeon');
    expect(await screen.findByText('내가 남긴 계획')).toBeInTheDocument();
    expect(screen.getByText('수현의 방문 기록')).toBeInTheDocument();
    expect(screen.getByText(/주황색에서 보라색으로/)).toBeInTheDocument();
    await waitFor(() => expect(loadDb().inbox[0].read).toBe(true));
    await waitFor(() => expect(screen.queryByTestId('unread-dot')).not.toBeInTheDocument());
  });

  it('답장 보내기 → 보낸 답장(7-1) + 수신함으로', async () => {
    const { router } = renderApp(`/inbox/${ITEM}`, 'u-jiyeon');
    fireEvent.change(await screen.findByLabelText('한 줄 답장'), { target: { value: ' 고마워요! ' } });
    fireEvent.click(screen.getByRole('button', { name: '답장 보내기' }));
    expect(await screen.findByTestId('sent-reply')).toHaveTextContent('고마워요!');
    expect(screen.getByTestId('screen-7-1')).toBeInTheDocument();
    expect(screen.queryByLabelText('한 줄 답장')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '수신함으로' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/inbox'));
  });

  it('이미 답장한 항목은 처음부터 7-1', async () => {
    updateDb((db) => {
      db.inbox[0].reply = { text: '이미 보낸 답장', sentAt: new Date().toISOString() };
    });
    renderApp(`/inbox/${ITEM}`, 'u-jiyeon');
    expect(await screen.findByTestId('sent-reply')).toHaveTextContent('이미 보낸 답장');
  });

  it('409 REPLY_ALREADY_SENT면 다시 읽어 보낸 답장 상태로', async () => {
    server.use(
      http.post('*/inbox/:itemId/reply', () => {
        updateDb((db) => {
          db.inbox[0].reply = { text: '다른 탭에서 보낸 답장', sentAt: new Date().toISOString() };
        });
        return HttpResponse.json({ error: { code: 'REPLY_ALREADY_SENT', message: '' } }, { status: 409 });
      }),
    );
    renderApp(`/inbox/${ITEM}`, 'u-jiyeon');
    fireEvent.change(await screen.findByLabelText('한 줄 답장'), { target: { value: '답장' } });
    fireEvent.click(screen.getByRole('button', { name: '답장 보내기' }));
    expect(await screen.findByTestId('sent-reply')).toHaveTextContent('다른 탭에서 보낸 답장');
  });

  it('빈 답장은 요청 없이 오류', async () => {
    renderApp(`/inbox/${ITEM}`, 'u-jiyeon');
    await screen.findByLabelText('한 줄 답장');
    fireEvent.click(screen.getByRole('button', { name: '답장 보내기' }));
    expect(await screen.findByText('1–100자로 입력해 주세요.')).toBeInTheDocument();
  });

  it('남의 항목은 404 안내', async () => {
    renderApp(`/inbox/${ITEM}`, 'u-suhyun');
    expect(await screen.findByText('찾을 수 없어요')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '수신함으로' })).toBeInTheDocument();
  });
});
