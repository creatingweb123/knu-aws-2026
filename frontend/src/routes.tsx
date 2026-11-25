/**
 * 경로 표(docs/05 §5.1). 화면 번호·이름·탭 여부를 한곳에 둔다.
 * 1단계는 빈 페이지(Placeholder)이고, 2–6단계에서 각 페이지로 바꾼다.
 * 상태 분기 화면(2-1, 5-2, 7-1, 8)은 별도 경로가 없다.
 */
import type { ReactNode } from 'react';
import { Outlet } from 'react-router-dom';
import type { RouteObject } from 'react-router-dom';

import { RequireAuth } from './auth/RequireAuth';
import { Layout } from './components/Layout';
import { BrowsePage } from './pages/browse/BrowsePage';
import { InboxDetailPage } from './pages/inbox/InboxDetailPage';
import { InboxPage } from './pages/inbox/InboxPage';
import { AbandonPage } from './pages/me/AbandonPage';
import { MyDayPage } from './pages/me/MyDayPage';
import { DonePage } from './pages/record/DonePage';
import { RecordPage } from './pages/record/RecordPage';
import { PlanDetailPage } from './pages/plan/PlanDetailPage';
import { PlacePage } from './pages/plan/create/PlacePage';
import { PlanFormPage } from './pages/plan/create/PlanFormPage';
import { PublishedPage } from './pages/plan/create/PublishedPage';
import { StoryPage } from './pages/plan/create/StoryPage';
import { LoginPage } from './pages/login/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { Placeholder } from './pages/Placeholder';
import { UnauthorizedRedirect } from './pages/UnauthorizedRedirect';

export interface ScreenRoute {
  path: string;
  screen: string;
  name: string;
  /** 하단 탭이 보이는 목록형 화면(FE-Q12) */
  tab?: boolean;
  /** 뒤로가기 버튼 */
  back?: boolean;
  /** 2–6단계 중 채울 단계 */
  stage: number;
  element?: ReactNode;
}

/** `/plans/new*`는 `/plans/:planId`보다 앞에 둔다(React Router는 정적 경로를 우선하지만 표 순서도 맞춘다) */
export const SCREENS: ScreenRoute[] = [
  { path: '/', screen: '1', name: '둘러보기', tab: true, stage: 2, element: <BrowsePage /> },
  { path: '/plans/new', screen: '3', name: '사연 입력', back: true, stage: 3, element: <StoryPage /> },
  { path: '/plans/new/card', screen: '3-1', name: 'AI와 함께 정리하기', back: true, stage: 6 },
  {
    path: '/plans/new/form',
    screen: '3-2',
    name: '하루 남기기',
    back: true,
    stage: 3,
    element: <PlanFormPage />,
  },
  {
    path: '/plans/new/place',
    screen: '3-3',
    name: '장소 추가',
    back: true,
    stage: 3,
    element: <PlacePage />,
  },
  {
    path: '/plans/:planId',
    screen: '2',
    name: '하루 들여다보기',
    back: true,
    stage: 2,
    element: <PlanDetailPage />,
  },
  {
    path: '/plans/:planId/published',
    screen: '3-4',
    name: '공개 완료',
    stage: 3,
    element: <PublishedPage />,
  },
  { path: '/me', screen: '4', name: '내 하루', tab: true, stage: 4, element: <MyDayPage /> },
  {
    path: '/claims/:claimId/abandon',
    screen: '4-1',
    name: '이어받기 포기 확인',
    back: true,
    stage: 4,
    element: <AbandonPage />,
  },
  {
    path: '/claims/:claimId/record',
    screen: '5',
    name: '그날의 이야기',
    back: true,
    stage: 4,
    element: <RecordPage />,
  },
  { path: '/claims/:claimId/sending', screen: '5-1', name: '보내는 중', stage: 5 },
  { path: '/claims/:claimId/record/photo', screen: '5-3', name: '사진 교체', back: true, stage: 5 },
  { path: '/claims/:claimId/done', screen: '5-4', name: '전송 완료', stage: 4, element: <DonePage /> },
  { path: '/inbox', screen: '6', name: '수신함', tab: true, stage: 4, element: <InboxPage /> },
  {
    path: '/inbox/:itemId',
    screen: '7',
    name: '돌아온 하루',
    back: true,
    stage: 4,
    element: <InboxDetailPage />,
  },
];

function screenElement(s: ScreenRoute): ReactNode {
  return (
    <RequireAuth>
      <Layout title={s.name} back={s.back} tab={s.tab}>
        {s.element ?? <Placeholder screen={s.screen} name={s.name} stage={s.stage} />}
      </Layout>
    </RequireAuth>
  );
}

export const routes: RouteObject[] = [
  {
    element: (
      <>
        <UnauthorizedRedirect />
        <Outlet />
      </>
    ),
    children: [
      {
        path: '/login',
        element: (
          <Layout bare>
            <LoginPage />
          </Layout>
        ),
      },
      ...SCREENS.map((s) => ({ path: s.path, element: screenElement(s) })),
      {
        path: '*',
        element: (
          <Layout title="이어온 하루" back="/">
            <NotFoundPage />
          </Layout>
        ),
      },
    ],
  },
];
