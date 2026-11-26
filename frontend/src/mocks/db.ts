/**
 * 목업 데이터(docs/02 §2.10). 시드 인물은 지연·수현·민준(FE-TECH-04), 예시 계획은 docs/02 §2.5(FE-Q15).
 *
 * 상태는 localStorage `haru.mock.db`에 둔다. 요청마다 읽고 쓰므로 같은 브라우저의 탭끼리 공유하고,
 * 2단계의 두 탭 경합을 재현할 수 있다(FE-Q10).
 * 저장 항목은 백엔드 DynamoDB 항목에 가깝게 두고(내부 속성 포함), 응답은 핸들러가 계약 형태로 만든다.
 */
import type {
  AiCard,
  AiNote,
  AiQuestion,
  AiSessionStatus,
  AiTraceStep,
  ClaimStatus,
  Flag,
  PhotoStatus,
  PlanMetrics,
  PlanStatus,
} from '../api/types';
import { MOCK_USERS } from './session';

export const DB_KEY = 'haru.mock.db';
/** 저장 형태가 바뀌면 올린다. 다른 버전의 저장값은 새 시드로 바뀐다(2: idempotency, 3: aiSessions) */
const DB_VERSION = 3;
export const DAY_MS = 24 * 60 * 60 * 1000;
export const CLAIM_DURATION_DAYS = 3;

export interface DbPlace {
  order: number;
  name: string;
  activity: string;
  whyChosen: string;
}

export interface DbPlan {
  planId: string;
  areaId: string;
  ownerId: string;
  ownerNickname: string;
  title: string;
  summary: string;
  reason: string;
  estimatedMinutes: number;
  places: DbPlace[];
  question: string;
  status: PlanStatus;
  createdAt: string;
  completedAt: string | null;
  metrics: PlanMetrics;
  /** 내부 속성. 응답에 내보내지 않는다(BE-Q33) */
  currentClaimId?: string;
  claimerId?: string;
  dueAt?: string;
}

export interface DbClaim {
  claimId: string;
  planId: string;
  claimerId: string;
  claimerNickname: string;
  status: ClaimStatus;
  claimedAt: string;
  dueAt: string;
  completedAt: string | null;
  late: boolean;
}

export interface DbRecord {
  claimId: string;
  planId: string;
  letter: string;
  photoStatus: PhotoStatus;
  updatedAt: string;
  deliveredAt: string | null;
  /** 내부 속성(응답에 없음). 5단계 사진 경로 */
  photoKey?: string;
  photoContentType?: string;
  /** PROCESSING이 끝나는 시각과 결과(업로드 때 시나리오로 정한다, FE-Q24) */
  processReadyAt?: string;
  photoOutcome?: 'READY' | 'FAILED';
}

export interface DbInboxItem {
  ownerId: string;
  itemId: string;
  planId: string;
  planTitle: string;
  claimerNickname: string;
  hasPhoto: boolean;
  read: boolean;
  createdAt: string;
  reply: { text: string; sentAt: string } | null;
}

/** `POST /plans` 멱등 키 항목. 키는 `{userId}#{Idempotency-Key}` */
export interface DbIdempotency {
  bodyHash: string;
  planId: string;
}

/** AI 정리 세션(docs/03 §3.2). 화면에 보내는 SessionView 필드 + 목업 진행용 내부 필드 */
export interface DbAiSession {
  sessionId: string;
  ownerId: string;
  story: string;
  scenario: string | null;
  status: AiSessionStatus;
  turn: number;
  trace: AiTraceStep[];
  question: AiQuestion | null;
  card: AiCard | null;
  flags: Flag[];
  notes: AiNote[];
  degraded: boolean;
  finishRequested: boolean;
  /** ai-busy: 409를 준 뒤 GET에서 반영할 결과와 남은 '처리 중' GET 수 */
  pending?: { view: Omit<DbAiSession, 'pending'>; workingGets: number };
}

export interface MockDb {
  version: number;
  plans: DbPlan[];
  claims: DbClaim[];
  records: DbRecord[];
  inbox: DbInboxItem[];
  idempotency: { [userAndKey: string]: DbIdempotency };
  aiSessions: DbAiSession[];
}

/** 계약과 같은 밀리초 3자리 UTC 문자열 */
export function iso(ms: number): string {
  return new Date(ms).toISOString();
}

function nick(id: string): string {
  return MOCK_USERS.find((u) => u.userId === id)?.nickname ?? id;
}

const JIYEON = 'u-jiyeon';
const SUHYUN = 'u-suhyun';
const MINJUN = 'u-minjun';
const HOUR_MS = 60 * 60 * 1000;

/**
 * 시드: 지연의 데모 계획(OPEN), 민준의 계획(OPEN), 지연의 계획을 민준이 이어받은 것(CLAIMED),
 * 지연의 계획을 수현이 완료해 지연 수신함에 안 읽은 편지 1건(COMPLETED).
 * 시각은 `now` 기준 상대값이라 언제 초기화해도 기한이 미래에 있다.
 */
export function createSeed(now: number = Date.now()): MockDb {
  const plans: DbPlan[] = [
    {
      planId: 'pln_demo',
      areaId: 'default',
      ownerId: JIYEON,
      ownerNickname: nick(JIYEON),
      title: '이사 전, 마지막 동네 산책',
      summary: '출근길 빵집에 들르고, 저녁마다 걷던 하천 벤치에 앉아 쉬고 싶었어요.',
      reason: '이삿짐 정리가 길어져 5년간 살던 동네에서 마지막 산책을 하지 못했어요.',
      estimatedMinutes: 45,
      places: [
        {
          order: 1,
          name: '출근길 빵집',
          activity: '들러서 빵 사기',
          whyChosen: '출근길에 지나치던 곳이에요.',
        },
        {
          order: 2,
          name: '하천 산책로 벤치',
          activity: '벤치에 앉아 쉬기',
          whyChosen: '저녁마다 걷던 길이에요.',
        },
      ],
      question: '벤치에 앉았을 때 어떤 소리가 들렸나요?',
      status: 'OPEN',
      createdAt: iso(now - 2 * HOUR_MS),
      completedAt: null,
      metrics: { authoringMode: 'AI_EDITED', durationMs: 183000, agentMode: 'AGENT' },
    },
    {
      planId: 'pln_library',
      areaId: 'default',
      ownerId: MINJUN,
      ownerNickname: nick(MINJUN),
      title: '비 오는 날 도서관 가는 길',
      summary: '구립 도서관 창가 자리에서 책을 읽고, 앞 공원 정자에서 쉬고 싶었어요.',
      reason: '갑자기 야근이 잡혀 주말 계획을 미뤘어요.',
      estimatedMinutes: 60,
      places: [
        {
          order: 1,
          name: '구립 도서관',
          activity: '창가 자리에서 책 읽기',
          whyChosen: '비 오는 날 창가가 좋아요.',
        },
        { order: 2, name: '공원 정자', activity: '정자에 앉아 쉬기', whyChosen: '' },
      ],
      question: '도서관 창가에서 무엇이 보였나요?',
      status: 'OPEN',
      createdAt: iso(now - 26 * HOUR_MS),
      completedAt: null,
      metrics: { authoringMode: 'MANUAL', durationMs: 240000 },
    },
    {
      planId: 'pln_market',
      areaId: 'default',
      ownerId: JIYEON,
      ownerNickname: nick(JIYEON),
      title: '시장 골목 아침 장보기',
      summary: '아침 시장에서 제철 과일을 사고 국숫집에서 아침을 먹고 싶었어요.',
      reason: '주말 아침에 일이 생겨 가지 못했어요.',
      estimatedMinutes: 40,
      places: [
        { order: 1, name: '아침 시장', activity: '제철 과일 사기', whyChosen: '주말 아침에만 열려요.' },
        { order: 2, name: '시장 국숫집', activity: '국수로 아침 먹기', whyChosen: '' },
      ],
      question: '시장에서 가장 먼저 눈에 띈 것은 무엇이었나요?',
      status: 'CLAIMED',
      createdAt: iso(now - 3 * DAY_MS),
      completedAt: null,
      metrics: { authoringMode: 'MANUAL', durationMs: 150000 },
      currentClaimId: 'clm_market_minjun',
      claimerId: MINJUN,
      dueAt: iso(now + 2 * DAY_MS),
    },
    {
      planId: 'pln_bridge',
      areaId: 'default',
      ownerId: JIYEON,
      ownerNickname: nick(JIYEON),
      title: '해 질 녘 다리 위에서',
      summary: '해 질 녘에 다리 위에서 노을을 보고 싶었어요.',
      reason: '친구와 약속이 겹쳤어요.',
      estimatedMinutes: 30,
      places: [{ order: 1, name: '하천 다리', activity: '노을 보기', whyChosen: '노을이 잘 보여요.' }],
      question: '노을은 어떤 색이었나요?',
      status: 'COMPLETED',
      createdAt: iso(now - 6 * DAY_MS),
      completedAt: iso(now - DAY_MS),
      metrics: { authoringMode: 'MANUAL', durationMs: 120000 },
      currentClaimId: 'clm_bridge_suhyun',
      claimerId: SUHYUN,
      dueAt: iso(now - 2 * DAY_MS),
    },
  ];

  const claims: DbClaim[] = [
    {
      claimId: 'clm_market_minjun',
      planId: 'pln_market',
      claimerId: MINJUN,
      claimerNickname: nick(MINJUN),
      status: 'ACTIVE',
      claimedAt: iso(now - DAY_MS),
      dueAt: iso(now + 2 * DAY_MS),
      completedAt: null,
      late: false,
    },
    {
      claimId: 'clm_bridge_suhyun',
      planId: 'pln_bridge',
      claimerId: SUHYUN,
      claimerNickname: nick(SUHYUN),
      status: 'COMPLETED',
      claimedAt: iso(now - 5 * DAY_MS),
      dueAt: iso(now - 2 * DAY_MS),
      completedAt: iso(now - DAY_MS),
      late: false,
    },
  ];

  const records: DbRecord[] = [
    {
      claimId: 'clm_bridge_suhyun',
      planId: 'pln_bridge',
      letter: '다리 위에서 본 노을은 주황색에서 보라색으로 천천히 바뀌었어요.',
      photoStatus: 'NONE',
      updatedAt: iso(now - DAY_MS),
      deliveredAt: iso(now - DAY_MS),
    },
  ];

  const inbox: DbInboxItem[] = [
    {
      ownerId: JIYEON,
      itemId: 'clm_bridge_suhyun',
      planId: 'pln_bridge',
      planTitle: '해 질 녘 다리 위에서',
      claimerNickname: nick(SUHYUN),
      hasPhoto: false,
      read: false,
      createdAt: iso(now - DAY_MS),
      reply: null,
    },
  ];

  return { version: DB_VERSION, plans, claims, records, inbox, idempotency: {}, aiSessions: [] };
}

export function loadDb(): MockDb {
  try {
    const raw = localStorage.getItem(DB_KEY);
    if (raw) {
      const db = JSON.parse(raw) as MockDb;
      if (db.version === DB_VERSION) return db;
    }
  } catch {
    // 손상된 값이면 새 시드로 바꾼다
  }
  return resetDb();
}

export function saveDb(db: MockDb): void {
  localStorage.setItem(DB_KEY, JSON.stringify(db));
}

/** 읽고 바꾸고 저장한다. 핸들러의 쓰기는 모두 이 함수를 거친다 */
export function updateDb<T>(fn: (db: MockDb) => T): T {
  const db = loadDb();
  const result = fn(db);
  saveDb(db);
  return result;
}

export function resetDb(now?: number): MockDb {
  const seed = createSeed(now);
  saveDb(seed);
  return seed;
}
