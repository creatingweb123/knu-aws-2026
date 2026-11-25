import { useNavigate } from 'react-router-dom';

import { usePlans } from '../../api/queries/usePlans';
import { errorMessage } from '../../api/errors';
import { PageTitle } from '../../components/PageTitle';
import { PrimaryButton } from '../../components/PrimaryButton';

/**
 * 1. 둘러보기. 1단계는 `GET /plans` 연결 확인용으로 건수만 보여준다(요구사항 7.3).
 * 카드 목록·빈 상태는 2단계(FE-BRW-01–04).
 */
export function BrowsePage() {
  const navigate = useNavigate();
  const { data, error, isPending } = usePlans();

  return (
    <section data-testid="screen-1">
      <PageTitle
        title={'이어받을 수 있는\n하루를 둘러보세요'}
        description="누군가 하지 못한 동네 산책을 이어받아요."
      />
      {isPending ? <p>불러오는 중…</p> : null}
      {error ? <p role="alert">{errorMessage(error)}</p> : null}
      {data ? <p data-testid="plan-count">이어받기 가능한 하루 {data.items.length}개</p> : null}
      <PrimaryButton onClick={() => navigate('/plans/new')}>취소된 하루 남기기</PrimaryButton>
    </section>
  );
}
