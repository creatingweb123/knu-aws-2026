/**
 * API 타입 (docs/03-api-contract.md와 같은 이름, FE-TECH-05).
 * 시간은 모두 ISO 8601 UTC 문자열(밀리초 3자리)이다.
 * 계약이 바뀌면 이 파일과 MSW 핸들러를 같은 PR에서 고친다(FE-NFR-07).
 */

export type IsoDateTime = string;

// ---------------------------------------------------------------- 공통

export type ErrorCode =
  | 'VALIDATION_ERROR'
  | 'RECORD_REQUIRED'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'ALREADY_CLAIMED'
  | 'CANNOT_CLAIM_OWN_PLAN'
  | 'CLAIM_NOT_ACTIVE'
  | 'REPLY_ALREADY_SENT'
  | 'IDEMPOTENCY_CONFLICT'
  | 'AI_SESSION_BUSY'
  | 'AI_SESSION_CLOSED'
  | 'AI_QUOTA_EXCEEDED'
  | 'AI_INVALID_OUTPUT'
  | 'TRY_AGAIN'
  | 'AI_UNAVAILABLE'
  /** 500 등 계약 형식이 아닌 오류. 백엔드 임시 코드(BE-Q23)와 같은 이름 */
  | 'INTERNAL_ERROR';

/** `details`의 키는 요청 본문 경로(예: `places[0].name`) */
export interface ErrorBody {
  // 이 파일의 `Record`는 방문 기록 타입이라 내장 Record<K, V> 대신 인덱스 시그니처를 쓴다
  error: { code: ErrorCode; message: string; details?: { [path: string]: string } };
}

export interface UserRef {
  userId: string;
  nickname: string;
}

// ---------------------------------------------------------------- 내 정보 §3.1

export interface Me {
  userId: string;
  nickname: string;
  unreadInboxCount: number;
}

// ---------------------------------------------------------------- 계획 §3.3

export type PlanStatus = 'OPEN' | 'CLAIMED' | 'COMPLETED';

export interface Place {
  order: number;
  name: string;
  activity: string;
  whyChosen: string;
}

/** 소유자에게만 내려온다 */
export interface PlanMetrics {
  authoringMode: AuthoringMode;
  durationMs: number;
  agentMode?: 'AGENT' | 'PIPELINE' | 'DEGRADED';
  [key: string]: unknown;
}

/** `currentClaimId`는 응답에 없다(BE-Q33) */
export interface Plan {
  planId: string;
  areaId: string;
  owner: UserRef;
  title: string;
  summary: string;
  reason: string;
  estimatedMinutes: number;
  places: Place[];
  question: string;
  status: PlanStatus;
  createdAt: IsoDateTime;
  completedAt: IsoDateTime | null;
  metrics?: PlanMetrics;
}

export interface PlanSummary {
  planId: string;
  title: string;
  summary: string;
  estimatedMinutes: number;
  placeCount: number;
  status: PlanStatus;
  ownerNickname: string;
  createdAt: IsoDateTime;
}

export interface PlanListResponse {
  items: PlanSummary[];
  nextCursor: string | null;
}

export interface PlanDetailResponse {
  plan: Plan;
  isOwner: boolean;
  myClaim: Claim | null;
  claimable: boolean;
}

export type AuthoringMode = 'MANUAL' | 'AI_EDITED';

export interface Authoring {
  mode: AuthoringMode;
  durationMs: number;
  aiSessionId?: string;
  story: string;
}

export interface PlaceInput {
  name: string;
  activity: string;
  whyChosen: string;
}

/** `POST /plans` 요청 본문. AI `card`와 필드 이름이 같다(§3.2) */
export interface PlanCardFields {
  title: string;
  summary: string;
  reason: string;
  estimatedMinutes: number;
  places: PlaceInput[];
  question: string;
}

export interface CreatePlanRequest extends PlanCardFields {
  authoring: Authoring;
}

export interface CreatePlanResponse {
  plan: Plan;
}

// ---------------------------------------------------------------- 이어받기·기록 §3.3–3.4

export type ClaimStatus = 'ACTIVE' | 'COMPLETED' | 'ABANDONED' | 'EXPIRED';

export interface Claim {
  claimId: string;
  planId: string;
  claimer: UserRef;
  status: ClaimStatus;
  claimedAt: IsoDateTime;
  dueAt: IsoDateTime;
  completedAt: IsoDateTime | null;
  late: boolean;
}

export interface ClaimResponse {
  claim: Claim;
}

export type PhotoStatus = 'NONE' | 'UPLOAD_PENDING' | 'PROCESSING' | 'READY' | 'FAILED' | 'DISCARDED';

export interface Record {
  claimId: string;
  planId: string;
  letter: string;
  photoStatus: PhotoStatus;
  updatedAt: IsoDateTime;
  deliveredAt: IsoDateTime | null;
}

export interface MyClaimItem {
  claim: Claim;
  plan: Plan;
  record: Record | null;
}

export interface MyClaimsResponse {
  items: MyClaimItem[];
}

export type PhotoContentType = 'image/jpeg' | 'image/png';

export interface PhotoMeta {
  contentType: PhotoContentType;
  size: number;
}

export interface PutRecordRequest {
  letter: string;
  photo?: PhotoMeta;
}

export interface UploadInstruction {
  url: string;
  method: 'PUT';
  headers: { [name: string]: string };
  expiresAt: IsoDateTime;
}

export interface PutRecordResponse {
  record: Record;
  upload: UploadInstruction | null;
}

export interface ReplacePhotoResponse {
  upload: UploadInstruction;
}

export interface GetRecordResponse {
  record: Record | null;
  claimStatus: ClaimStatus;
  delivered: boolean;
  photoStatus: PhotoStatus;
}

export interface CompleteRequest {
  mode: 'TEXT_ONLY';
}

export interface CompleteResponse {
  claim: Claim;
  delivered: boolean;
  hasPhoto: boolean;
}

// ---------------------------------------------------------------- 수신함 §3.5

export interface Reply {
  text: string;
  sentAt: IsoDateTime;
}

export interface InboxItem {
  itemId: string;
  planId: string;
  planTitle: string;
  claimerNickname: string;
  hasPhoto: boolean;
  read: boolean;
  createdAt: IsoDateTime;
  reply: Reply | null;
}

export interface InboxListResponse {
  items: InboxItem[];
}

export interface InboxDetailResponse {
  item: InboxItem;
  plan: Plan;
  record: {
    letter: string;
    deliveredAt: IsoDateTime;
    photoUrl: string | null;
    photoCaption: string | null;
  };
}

export interface ReplyResponse {
  reply: Reply;
}

// ---------------------------------------------------------------- AI 정리 세션 §3.2

export type AiSessionStatus = 'WORKING' | 'ASKING' | 'READY' | 'FAILED';

export interface AiTraceStep {
  step: number;
  tool: string;
  summary: string;
}

export interface AiQuestion {
  questionId: string;
  path: string;
  text: string;
  reason: string;
  options: string[];
  allowFreeText: boolean;
}

/** AI 카드. `POST /plans` 요청과 같은 필드이고 값이 없으면 `null` */
export interface AiCard {
  title: string | null;
  summary: string | null;
  reason: string | null;
  estimatedMinutes: number | null;
  places: { name: string | null; activity: string | null; whyChosen: string | null }[] | null;
  question: string | null;
}

export interface Flag {
  path: string;
  type: 'NOT_IN_SOURCE' | 'MISSING' | 'PRIVACY';
}

export interface AiNote {
  path: string;
  action: 'REWRITTEN' | 'REMOVED' | 'ASKED' | 'KEPT_FLAGGED';
  reason: string;
  source: 'STORY' | 'ANSWER';
  /**
   * 계약에 없는 임시 필드(FE-Q7·BE-Q13). "다시 넣기"로 되살릴 원래 값과 경고 유형.
   * MSW만 보낸다. 실제 API에는 없으므로 이 필드가 없으면 "다시 넣기"를 보여 주지 않는다.
   */
  restore?: { value: PlaceInput; type: 'PRIVACY' | 'NOT_IN_SOURCE' };
}

export interface SessionView {
  sessionId: string;
  status: AiSessionStatus;
  turn: number;
  trace: AiTraceStep[];
  question: AiQuestion | null;
  card: AiCard | null;
  flags: Flag[];
  notes: AiNote[];
  degraded: boolean;
}

export interface CreateSessionRequest {
  story: string;
}

export type AiAnswer =
  | { questionId: string; choice: string }
  | { questionId: string; text: string }
  | { questionId: string; skipped: true };

export interface TurnRequest {
  expectedTurn: number;
  answer?: AiAnswer;
  finish?: boolean;
}
