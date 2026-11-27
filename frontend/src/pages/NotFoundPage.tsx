import { useNavigate } from 'react-router-dom';

import { PrimaryButton } from '../components/PrimaryButton';
import { ResultScreen } from '../components/ResultScreen';

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <ResultScreen
      icon="notice"
      title="찾을 수 없어요"
      description="주소가 바뀌었거나 더 이상 볼 수 없는 화면이에요."
      action={<PrimaryButton onClick={() => navigate('/')}>둘러보기로 가기</PrimaryButton>}
    />
  );
}
