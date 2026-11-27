import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';

import { loadDb, updateDb } from '../../mocks/db';
import { abandonClaim, putRecord } from '../../mocks/handlers/claims';
import { claimPlan } from '../../mocks/handlers/plans';
import { loadLetter, saveLetter } from '../../state/letterDraft';
import { renderApp } from '../../test/renderApp';
import { server } from '../../test/server';

const SUHYUN = { userId: 'u-suhyun', nickname: '수현' };

/** 수현이 pln_demo를 이어받은 상태를 만든다 */
function suhyunClaims(): string {
  const out = updateDb((db) => claimPlan(db, 'pln_demo', SUHYUN, Date.now()));
  if (!('claim' in out)) throw new Error('claim 없음');
  return out.claim.claimId;
}

const letterBox = () => screen.getByLabelText('다녀온 이야기');

describe('내 하루(FE-ME-01–03)', () => {
  it('이어받은 하루가 없으면 둘러보기 유도', async () => {
    renderApp('/me', 'u-suhyun');
    expect(await screen.findByTestId('me-empty')).toHaveTextContent('아직 이어받은 하루가 없어요');
  });

  it('제목·계획자·기한 문구·동선, 다녀온 이야기 쓰기 → 작성 화면', async () => {
    const claimId = suhyunClaims();
    const { router } = renderApp('/me', 'u-suhyun');
    const card = await screen.findByTestId(`claim-${claimId}`);
    expect(card).toHaveTextContent('이사 전, 마지막 동네 산책');
    expect(card).toHaveTextContent('지연 · 약 45분 · 장소 2곳');
    expect(card).toHaveTextContent(/\d+월 \d+일까지 다녀온 이야기를 보내주세요\./);
    expect(within(card).getByText('출근길 빵집')).toBeInTheDocument();
    fireEvent.click(within(card).getByRole('button', { name: '다녀온 이야기 쓰기' }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/claims/${claimId}/record`));
  });
});

describe('방문 기록(FE-REC-01–03, 05, 10)', () => {
  it('질문·"지연에게" 표시, 글로 완료 → 5-4, 임시 글 삭제, 지연 수신함에 도착', async () => {
    const claimId = suhyunClaims();
    const { router } = renderApp(`/claims/${claimId}/record`, 'u-suhyun');
    await screen.findByLabelText('다녀온 이야기');
    expect(screen.getByText('지연에게')).toBeInTheDocument();
    expect(screen.getByText('벤치에 앉았을 때 어떤 소리가 들렸나요?')).toBeInTheDocument();

    fireEvent.change(letterBox(), { target: { value: '  소금빵을 사서 벤치에 앉았어요.  ' } });
    expect(loadLetter(claimId)).toContain('소금빵');
    fireEvent.click(screen.getByRole('button', { name: '글로 완료하기' }));

    expect(await screen.findByText('방문 기록을 보냈어요')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/claims/${claimId}/done`);
    expect(loadLetter(claimId)).toBeNull();
    const db = loadDb();
    expect(db.records.find((r) => r.claimId === claimId)?.letter).toBe('소금빵을 사서 벤치에 앉았어요.');
    expect(db.inbox.find((i) => i.itemId === claimId)?.ownerId).toBe('u-jiyeon');
  });

  it('빈 글은 요청 없이 오류', async () => {
    const claimId = suhyunClaims();
    renderApp(`/claims/${claimId}/record`, 'u-suhyun');
    await screen.findByLabelText('다녀온 이야기');
    fireEvent.click(screen.getByRole('button', { name: '글로 완료하기' }));
    expect(await screen.findByText('1–1000자로 입력해 주세요.')).toBeInTheDocument();
  });

  it('서버 글이 있으면 서버 글, 없으면 임시 글로 채운다(FE-REC-02)', async () => {
    const claimId = suhyunClaims();
    saveLetter(claimId, '임시 글');
    renderApp(`/claims/${claimId}/record`, 'u-suhyun');
    await waitFor(() => expect(letterBox()).toHaveValue('임시 글'));
    cleanup();

    updateDb((db) => putRecord(db, claimId, 'u-suhyun', { letter: '서버 글' }, Date.now()));
    renderApp(`/claims/${claimId}/record`, 'u-suhyun');
    await waitFor(() => expect(letterBox()).toHaveValue('서버 글'));
  });

  it('complete가 RECORD_REQUIRED면 PUT 후 한 번 다시 보낸다', async () => {
    const claimId = suhyunClaims();
    let puts = 0;
    let completes = 0;
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'PUT' && request.url.endsWith('/record')) puts += 1;
    });
    server.use(
      http.post('*/claims/:claimId/complete', () => {
        completes += 1;
        if (completes === 1) {
          return HttpResponse.json({ error: { code: 'RECORD_REQUIRED', message: '' } }, { status: 400 });
        }
        return undefined;
      }),
    );
    renderApp(`/claims/${claimId}/record`, 'u-suhyun');
    fireEvent.change(await screen.findByLabelText('다녀온 이야기'), { target: { value: '글' } });
    fireEvent.click(screen.getByRole('button', { name: '글로 완료하기' }));
    expect(await screen.findByText('방문 기록을 보냈어요')).toBeInTheDocument();
    server.events.removeAllListeners();
    expect(puts).toBe(2);
    expect(completes).toBe(2);
  });

  it('완료된 기록으로 들어오면 전송 완료로, 새로고침한 5-4는 GET /record로 판단', async () => {
    const { router } = renderApp('/claims/clm_bridge_suhyun/record', 'u-suhyun');
    await waitFor(() => expect(router.state.location.pathname).toBe('/claims/clm_bridge_suhyun/done'));
    expect(await screen.findByText('방문 기록을 보냈어요')).toBeInTheDocument();
  });
});

describe('종료된 이어받기(FE-REC-11)', () => {
  it('작성 중 포기된 이어받기면 저장할 때 화면 8, 글 복사 가능', async () => {
    const claimId = suhyunClaims();
    renderApp(`/claims/${claimId}/record`, 'u-suhyun');
    fireEvent.change(await screen.findByLabelText('다녀온 이야기'), { target: { value: '쓰던 글' } });
    // 다른 탭에서 포기했다
    updateDb((db) => abandonClaim(db, claimId, 'u-suhyun'));
    fireEvent.click(screen.getByRole('button', { name: '글로 완료하기' }));
    expect(await screen.findByText('이 이어받기는 종료되었어요')).toBeInTheDocument();
    expect(screen.getByText('쓰던 글')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '글 복사하기' })).toBeInTheDocument();
    expect(loadLetter(claimId)).toBeNull();
  });

  it('포기된 이어받기로 들어오면 바로 화면 8', async () => {
    const claimId = suhyunClaims();
    updateDb((db) => abandonClaim(db, claimId, 'u-suhyun'));
    renderApp(`/claims/${claimId}/record`, 'u-suhyun');
    expect(await screen.findByTestId('screen-8')).toBeInTheDocument();
  });
});

describe('이어받기 포기(FE-ME-04)', () => {
  it('포기 → 둘러보기, 하루가 다시 목록에', async () => {
    const claimId = suhyunClaims();
    const { router } = renderApp(`/claims/${claimId}/abandon`, 'u-suhyun');
    expect(await screen.findByText('이사 전, 마지막 동네 산책')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '이어받기 포기' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
    const list = await screen.findByTestId('plan-list');
    expect(within(list).getByText('이사 전, 마지막 동네 산책')).toBeInTheDocument();
    expect(loadDb().claims.find((c) => c.claimId === claimId)?.status).toBe('ABANDONED');
  });

  it('이미 끝난 이어받기면 안내 후 내 하루', async () => {
    const claimId = suhyunClaims();
    updateDb((db) => abandonClaim(db, claimId, 'u-suhyun'));
    const { router } = renderApp(`/claims/${claimId}/abandon`, 'u-suhyun');
    fireEvent.click(await screen.findByRole('button', { name: '이어받기 포기' }));
    expect(await screen.findByText('이미 종료된 이어받기예요.')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/me');
  });

  it('계속 이어가기 → 내 하루', async () => {
    const claimId = suhyunClaims();
    const { router } = renderApp(`/claims/${claimId}/abandon`, 'u-suhyun');
    fireEvent.click(await screen.findByRole('button', { name: '계속 이어가기' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/me'));
  });
});
