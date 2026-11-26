/**
 * AI 카드 ↔ 폼 연결(FE-CRT-02, 03, 14). 카드 필드 이름은 `POST /plans` 요청과 같고,
 * `flags[].path`는 `VALIDATION_ERROR.details`와 같은 경로 표기라 폼 입력칸에 그대로 연결한다.
 */
import type { AiCard, Flag, PlaceInput } from '../../../api/types';
import type { PlanForm } from '../../../state/planDraft';
import { LIMITS } from '../../../utils/validation';

/** `null`은 빈칸, 분은 입력칸 문자열로 */
export function cardToForm(card: AiCard): PlanForm {
  return {
    title: card.title ?? '',
    summary: card.summary ?? '',
    reason: card.reason ?? '',
    estimatedMinutes: card.estimatedMinutes === null ? '' : String(card.estimatedMinutes),
    places: (card.places ?? []).map((p) => ({
      name: p.name ?? '',
      activity: p.activity ?? '',
      whyChosen: p.whyChosen ?? '',
    })),
    question: card.question ?? '',
  };
}

const FLAG_MESSAGES: { [type in Flag['type']]: string } = {
  NOT_IN_SOURCE: '원문에 없던 내용이에요, 확인해 주세요',
  MISSING: '직접 채워주세요',
  PRIVACY: '공개하기 어려운 정보일 수 있어요',
};

export function flagMessage(type: Flag['type']): string {
  return FLAG_MESSAGES[type];
}

/** 경로의 안내 문구(여러 개면 첫 번째). 장소 접두사(`places[0]`)를 주면 그 장소의 안내를 모두 돌려준다 */
export function flagFor(flags: Flag[], path: string): string | undefined {
  const f = flags.find((x) => x.path === path);
  return f ? flagMessage(f.type) : undefined;
}

export function placeFlags(flags: Flag[], index: number): string[] {
  const prefix = `places[${index}]`;
  return [
    ...new Set(
      flags
        .filter((f) => f.path === prefix || f.path.startsWith(`${prefix}.`))
        .map((f) => flagMessage(f.type)),
    ),
  ];
}

export function withoutFlag(flags: Flag[], path: string): Flag[] {
  return flags.filter((f) => f.path !== path);
}

/** i번째 장소의 flag를 지우고 뒤 장소의 경로를 하나씩 당긴다(장소 빼기) */
export function removePlaceFlags(flags: Flag[], index: number): Flag[] {
  const out: Flag[] = [];
  for (const f of flags) {
    const m = /^places\[(\d+)\](.*)$/.exec(f.path);
    if (!m) {
      out.push(f);
      continue;
    }
    const i = Number(m[1]);
    if (i === index) continue;
    out.push(i > index ? { ...f, path: `places[${i - 1}]${m[2]}` } : f);
  }
  return out;
}

/** i번째 장소의 flag만 지운다(장소 고치기) */
export function clearPlaceFlags(flags: Flag[], index: number): Flag[] {
  const prefix = `places[${index}]`;
  return flags.filter((f) => f.path !== prefix && !f.path.startsWith(`${prefix}.`));
}

/** "다시 넣기"(FE-CRT-14, FE-Q7): 장소를 끝에 넣고 이름 경로에 경고를 붙인다. 3곳이면 null */
export function restorePlace(
  places: PlaceInput[],
  flags: Flag[],
  value: PlaceInput,
  type: 'PRIVACY' | 'NOT_IN_SOURCE',
): { places: PlaceInput[]; flags: Flag[] } | null {
  if (places.length >= LIMITS.maxPlaces) return null;
  return {
    places: [...places, { ...value }],
    flags: [...flags, { path: `places[${places.length}].name`, type }],
  };
}
