import { Link, useSearchParams } from 'react-router-dom';

import { PageTitle } from '../../components/PageTitle';
import { config } from '../../config';

/** 0. 로그인 / 회원가입. Cognito 연결은 7단계(FE-AUTH-01–03). 1단계는 안내만 둔다 */
export function LoginPage() {
  const [params] = useSearchParams();
  const redirect = params.get('redirect');
  const safeRedirect = redirect && redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/';

  return (
    <section data-testid="screen-0">
      <PageTitle
        title={'이어온 하루에\n오신 걸 환영해요'}
        description="로그인은 프론트 7단계에서 Cognito로 연결해요."
      />
      {config.useMock ? (
        <p>
          목업 모드에서는 위쪽 목업 바에서 사용자를 고르면 로그인된 상태로 봐요.{' '}
          <Link to={safeRedirect}>돌아가기</Link>
        </p>
      ) : (
        <p>지금은 목업 모드(VITE_USE_MOCK=true)에서만 화면을 볼 수 있어요.</p>
      )}
    </section>
  );
}
