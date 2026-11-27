/**
 * 하루 남기기 입력 검증(FE-CRT-06, docs/05 §5.2.3). 규칙과 문구는 백엔드 `common/validation.py`와 같다.
 * 앞뒤 공백을 뺀 값으로 세고, 글자 수는 코드 포인트로 센다(FE-Q19, pydantic과 같음).
 * 결과 키는 요청 본문 경로(`places[0].name`)라 서버 `VALIDATION_ERROR.details`와 같은 자리에 보인다.
 */
import type { PlaceInput } from '../api/types';

export type FieldErrors = { [path: string]: string };

export const LIMITS = {
  story: 1000,
  title: 40,
  summary: 120,
  reason: 300,
  question: 80,
  placeName: 30,
  placeActivity: 60,
  placeWhy: 120,
  minMinutes: 10,
  maxMinutes: 240,
  maxPlaces: 3,
} as const;

export const MESSAGES = {
  story: '1–1000자로 입력해 주세요.',
  title: '1–40자로 입력해 주세요.',
  summary: '1–120자로 입력해 주세요.',
  reason: '1–300자로 입력해 주세요.',
  estimatedMinutes: '10–240 사이의 정수로 입력해 주세요.',
  places: '장소는 1–3곳이어야 해요.',
  name: '1–30자로 입력해 주세요.',
  activity: '1–60자로 입력해 주세요.',
  whyChosen: '0–120자로 입력해 주세요.',
  question: '1–80자로 입력해 주세요.',
} as const;

/** 코드 포인트 수(이모지 1자 = 1) */
export function charCount(s: string): number {
  return [...s].length;
}

function lengthOk(value: string, min: number, max: number): boolean {
  const n = charCount(value.trim());
  return n >= min && n <= max;
}

export function validateStory(story: string): FieldErrors {
  return lengthOk(story, 1, LIMITS.story) ? {} : { story: MESSAGES.story };
}

/** 입력칸 값(문자열)을 정수 분으로. 정수가 아니면 null */
export function parseMinutes(raw: string): number | null {
  const t = raw.trim();
  if (!/^\d+$/.test(t)) return null;
  return Number(t);
}

export function validatePlace(place: PlaceInput, prefix = ''): FieldErrors {
  const out: FieldErrors = {};
  if (!lengthOk(place.name, 1, LIMITS.placeName)) out[`${prefix}name`] = MESSAGES.name;
  if (!lengthOk(place.activity, 1, LIMITS.placeActivity)) out[`${prefix}activity`] = MESSAGES.activity;
  if (!lengthOk(place.whyChosen, 0, LIMITS.placeWhy)) out[`${prefix}whyChosen`] = MESSAGES.whyChosen;
  return out;
}

export interface PlanFormValues {
  title: string;
  summary: string;
  reason: string;
  estimatedMinutes: string;
  places: PlaceInput[];
  question: string;
}

export function validatePlanForm(form: PlanFormValues): FieldErrors {
  const out: FieldErrors = {};
  if (!lengthOk(form.title, 1, LIMITS.title)) out.title = MESSAGES.title;
  if (!lengthOk(form.summary, 1, LIMITS.summary)) out.summary = MESSAGES.summary;
  if (!lengthOk(form.reason, 1, LIMITS.reason)) out.reason = MESSAGES.reason;
  const minutes = parseMinutes(form.estimatedMinutes);
  if (minutes === null || minutes < LIMITS.minMinutes || minutes > LIMITS.maxMinutes) {
    out.estimatedMinutes = MESSAGES.estimatedMinutes;
  }
  if (form.places.length < 1 || form.places.length > LIMITS.maxPlaces) out.places = MESSAGES.places;
  form.places.forEach((p, i) => Object.assign(out, validatePlace(p, `places[${i}].`)));
  if (!lengthOk(form.question, 1, LIMITS.question)) out.question = MESSAGES.question;
  return out;
}

/** 사연 앞부분으로 summary 기본값을 만든다(FE-CRT-05, 120자 이내) */
export function summaryFromStory(story: string): string {
  return [...story.trim()].slice(0, LIMITS.summary).join('').trim();
}
