import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';

import { useRecord } from '../../api/queries/useRecord';
import { PrimaryButton } from '../../components/PrimaryButton';
import { ResultScreen } from '../../components/ResultScreen';

/**
 * 5-4. 전송 완료(FE-REC-10). 문구는 누른 버튼이 아니라 서버 결과로 정한다:
 * 라우터 state의 `hasPhoto`(complete 응답), 없으면(새로고침) `GET /record`의 `photoStatus === 'READY'`.
 */
export function DonePage() {
  const { claimId = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const fromState = (location.state as { hasPhoto?: boolean } | null)?.hasPhoto;
  const recordQ = useRecord(claimId, { enabled: fromState === undefined });

  if (fromState === undefined && recordQ.data && !recordQ.data.delivered) {
    return <Navigate to={`/claims/${encodeURIComponent(claimId)}/record`} replace />;
  }

  const hasPhoto = fromState ?? (recordQ.data?.delivered && recordQ.data.photoStatus === 'READY');
  const known = fromState !== undefined || !!recordQ.data?.delivered;

  return (
    <section data-testid="screen-5-4">
      <ResultScreen
        icon="check"
        title={
          !known
            ? '전송 결과를 확인하고 있어요'
            : hasPhoto
              ? '사진과 방문 기록을 보냈어요'
              : '방문 기록을 보냈어요'
        }
        description={known ? '계획자의 수신함에 그날의 이야기가 도착했어요.' : undefined}
        action={
          <PrimaryButton onClick={() => navigate('/', { replace: true })}>둘러보기로 돌아가기</PrimaryButton>
        }
      />
    </section>
  );
}
