import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { loadDb, updateDb } from '../../mocks/db';
import { claimPlan } from '../../mocks/handlers/plans';
import { loadSending } from '../../state/sendingClock';
import { renderApp } from '../../test/renderApp';

const SUHYUN = { userId: 'u-suhyun', nickname: '수현' };

function suhyunClaims(): string {
  const out = updateDb((db) => claimPlan(db, 'pln_demo', SUHYUN, Date.now()));
  if (!('claim' in out)) throw new Error('claim 없음');
  return out.claim.claimId;
}

const jpeg = (name = 'bench.jpg', type = 'image/jpeg') =>
  new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], name, { type });

function pick(file: File, label = '사진 (선택, 1장)') {
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } });
}

async function writeWithPhoto(claimId: string, file = jpeg()) {
  const app = renderApp(`/claims/${claimId}/record`, 'u-suhyun');
  fireEvent.change(await screen.findByLabelText('다녀온 이야기'), {
    target: { value: '벤치에서 물소리를 들었어요.' },
  });
  pick(file);
  await screen.findByText(file.name);
  return app;
}

describe('사진 선택(FE-REC-03)', () => {
  it('형식이 맞지 않으면 고르지 않고 안내, 맞으면 버튼이 두 개가 된다', async () => {
    const claimId = suhyunClaims();
    renderApp(`/claims/${claimId}/record`, 'u-suhyun');
    await screen.findByLabelText('다녀온 이야기');
    pick(new File(['gif'], 'a.gif', { type: 'image/gif' }));
    expect(await screen.findByText('JPEG 또는 PNG, 10MB 이하 사진을 골라 주세요.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '글로 완료하기' })).toBeInTheDocument();

    pick(jpeg());
    expect(await screen.findByRole('button', { name: '사진과 경험 기록 보내기' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '사진 없이 글로 완료' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '사진 빼기' }));
    expect(await screen.findByRole('button', { name: '글로 완료하기' })).toBeInTheDocument();
  });
});

describe('사진과 함께 보내기(FE-REC-04, 06, 10)', () => {
  it('보내기 → 보내는 중 → 사진 포함 완료 문구, 수신함에 사진', async () => {
    const claimId = suhyunClaims();
    const { router } = await writeWithPhoto(claimId);
    fireEvent.click(screen.getByRole('button', { name: '사진과 경험 기록 보내기' }));
    expect(
      await screen.findByText('사진과 경험 기록을 보냈어요', {}, { timeout: 15_000 }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/claims/${claimId}/done`);
    const db = loadDb();
    expect(db.records.find((r) => r.claimId === claimId)).toMatchObject({
      photoStatus: 'READY',
      letter: '벤치에서 물소리를 들었어요.',
    });
    expect(db.inbox.find((i) => i.itemId === claimId)?.hasPhoto).toBe(true);
    expect(loadSending(claimId)).toBeNull();
  });

  it('사진 없이 글로 완료 → 글 문구', async () => {
    const claimId = suhyunClaims();
    await writeWithPhoto(claimId);
    fireEvent.click(screen.getByRole('button', { name: '사진 없이 글로 완료' }));
    expect(await screen.findByText('경험 기록을 보냈어요')).toBeInTheDocument();
  });

  it('처리 실패(photo-fail) → 5-2 → 글로 완료', async () => {
    sessionStorage.setItem('haru.mock.scenario', 'photo-fail');
    const claimId = suhyunClaims();
    await writeWithPhoto(claimId);
    fireEvent.click(screen.getByRole('button', { name: '사진과 경험 기록 보내기' }));
    expect(await screen.findByTestId('screen-5-2', {}, { timeout: 15_000 })).toHaveTextContent(
      '사진을 보내지 못했어요',
    );
    fireEvent.click(screen.getByRole('button', { name: '글로 완료하기' }));
    expect(await screen.findByText('경험 기록을 보냈어요')).toBeInTheDocument();
    expect(loadDb().records.find((r) => r.claimId === claimId)?.photoStatus).toBe('DISCARDED');
  });

  it('업로드 실패(photo-upload-fail) → 바로 5-2, 사진 바꾸기 → 5-3 → 새 사진으로 완료', async () => {
    sessionStorage.setItem('haru.mock.scenario', 'photo-upload-fail');
    const claimId = suhyunClaims();
    const { router } = await writeWithPhoto(claimId);
    fireEvent.click(screen.getByRole('button', { name: '사진과 경험 기록 보내기' }));
    expect(await screen.findByTestId('screen-5-2', {}, { timeout: 15_000 })).toBeInTheDocument();
    expect(loadSending(claimId)?.uploadFailed).toBe(true);

    sessionStorage.setItem('haru.mock.scenario', ''); // 다음 업로드는 성공
    fireEvent.click(screen.getByRole('button', { name: '사진 바꾸기' }));
    await screen.findByTestId('screen-5-3');
    expect(router.state.location.pathname).toBe(`/claims/${claimId}/record/photo`);
    pick(jpeg('river.png', 'image/png'), '새 사진');
    await screen.findByText('river.png');
    fireEvent.click(screen.getByRole('button', { name: '이 사진으로 보내기' }));
    expect(
      await screen.findByText('사진과 경험 기록을 보냈어요', {}, { timeout: 15_000 }),
    ).toBeInTheDocument();
    expect(
      loadDb()
        .records.find((r) => r.claimId === claimId)
        ?.photoKey?.endsWith('.png'),
    ).toBe(true);
  });

  it('처리가 늦으면(photo-slow) 보내는 중에서 글로 완료할 수 있다', async () => {
    sessionStorage.setItem('haru.mock.scenario', 'photo-slow');
    const claimId = suhyunClaims();
    await writeWithPhoto(claimId);
    fireEvent.click(screen.getByRole('button', { name: '사진과 경험 기록 보내기' }));
    expect(await screen.findByText('보내는 중이에요', {}, { timeout: 15_000 })).toBeInTheDocument();
    await waitFor(() =>
      expect(loadDb().records.find((r) => r.claimId === claimId)?.photoStatus).toBe('PROCESSING'),
    );
    fireEvent.click(screen.getByRole('button', { name: '글로 완료하기' }));
    expect(await screen.findByText('경험 기록을 보냈어요')).toBeInTheDocument();
  });
});

describe('돌아온 하루의 사진(FE-INB-03)', () => {
  it('사진과 캡션을 보여 준다', async () => {
    updateDb((db) => {
      db.inbox[0].hasPhoto = true;
    });
    renderApp('/inbox/clm_bridge_suhyun', 'u-jiyeon');
    expect(await screen.findByAltText('수현님이 보낸 사진')).toBeInTheDocument();
    expect(screen.getByText('하천 다리에서')).toBeInTheDocument();
  });
});
