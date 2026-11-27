import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { usePlan } from '../../../api/queries/usePlans';
import type { Plan } from '../../../api/types';
import { PrimaryButton } from '../../../components/PrimaryButton';
import { ResultScreen } from '../../../components/ResultScreen';
import { planMetaText } from '../../../utils/plan';

/**
 * 3-4. 공개 완료(FE-CRT-11). 공개 응답의 plan을 라우터 state로 받고,
 * 새로고침으로 state가 없으면 `GET /plans/{planId}`로 다시 읽는다(FE-Q2).
 */
export function PublishedPage() {
  const { planId = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const fromState = (location.state as { plan?: Plan } | null)?.plan;
  const { data } = usePlan(planId, { enabled: !fromState });
  const plan = fromState ?? data?.plan;

  return (
    <section data-testid="screen-3-4">
      <ResultScreen
        icon="check"
        title="하루를 공개했어요"
        description="누군가 이 하루를 이어받아 다녀오면, 그날의 이야기가 수신함으로 돌아와요."
        summary={
          plan ? (
            <>
              <p>
                <strong>{plan.title}</strong>
              </p>
              <p>{planMetaText(plan.estimatedMinutes, plan.places.length)}</p>
            </>
          ) : null
        }
        action={<PrimaryButton onClick={() => navigate('/')}>둘러보기로 가기</PrimaryButton>}
      />
    </section>
  );
}
