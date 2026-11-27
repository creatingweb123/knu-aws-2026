/**
 * 공개 요청 본문과 `Idempotency-Key`를 정한다(FE-CRT-09, FE-CRT-10, FE-Q18).
 * 키 재사용은 `authoring.durationMs`를 뺀 본문의 해시로 판단한다. 같으면 저장한 키와 처음 계산한
 * durationMs로 같은 본문을 다시 보내, 재전송이 서버에서 같은 Plan으로 재생되게 한다.
 */
import type { CreatePlanRequest } from '../../../api/types';
import type { PlanDraft } from '../../../state/planDraft';
import { canonicalJson, hashString } from '../../../utils/hash';
import { newUuid } from '../../../utils/uuid';
import { parseMinutes } from '../../../utils/validation';

/** durationMs를 뺀 공개 본문. 값은 앞뒤 공백을 뺀다(FE-Q19). 폼 검증을 통과한 뒤 부른다 */
export function buildPlanContent(draft: PlanDraft): Omit<CreatePlanRequest, 'authoring'> & {
  authoring: Omit<CreatePlanRequest['authoring'], 'durationMs'>;
} {
  const f = draft.form;
  const aiSessionId = draft.mode === 'AI_EDITED' && draft.sessionId ? draft.sessionId : undefined;
  return {
    title: f.title.trim(),
    summary: f.summary.trim(),
    reason: f.reason.trim(),
    estimatedMinutes: parseMinutes(f.estimatedMinutes) ?? 0,
    places: f.places.map((p) => ({
      name: p.name.trim(),
      activity: p.activity.trim(),
      whyChosen: p.whyChosen.trim(),
    })),
    question: f.question.trim(),
    authoring: {
      mode: draft.mode,
      story: draft.story.trim(),
      ...(aiSessionId ? { aiSessionId } : {}),
    },
  };
}

export interface PreparedPublish {
  body: CreatePlanRequest;
  key: string;
  /** 초안에 저장할 키 정보 */
  keyBodyHash: string;
  keyDurationMs: number;
}

export function preparePublish(draft: PlanDraft, now: number): PreparedPublish {
  const content = buildPlanContent(draft);
  const keyBodyHash = hashString(canonicalJson(content));
  const reuse =
    draft.idempotencyKey !== null && draft.keyBodyHash === keyBodyHash && draft.keyDurationMs !== null;
  const key = reuse ? draft.idempotencyKey! : newUuid();
  const keyDurationMs = reuse ? draft.keyDurationMs! : Math.max(0, Math.round(now - draft.startedAt));
  return {
    body: { ...content, authoring: { ...content.authoring, durationMs: keyDurationMs } },
    key,
    keyBodyHash,
    keyDurationMs,
  };
}
