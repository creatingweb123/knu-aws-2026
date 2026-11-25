/**
 * `POST /plans` 본문 검증 목업. 백엔드 `common/validation.py`(pydantic strict)와 같은 경로·문구를 돌려준다.
 * 백엔드처럼 공백을 자르지 않고 길이만 보고, 정수는 문자열·실수·불리언을 받지 않는다.
 * 같은 경로는 첫 오류만 남긴다.
 */

type Details = { [path: string]: string };

const REQUIRED = '필수 항목이에요.';
const FIELD_MESSAGES: { [name: string]: string } = {
  title: '1–40자로 입력해 주세요.',
  summary: '1–120자로 입력해 주세요.',
  reason: '1–300자로 입력해 주세요.',
  estimatedMinutes: '10–240 사이의 정수로 입력해 주세요.',
  places: '장소는 1–3곳이어야 해요.',
  name: '1–30자로 입력해 주세요.',
  activity: '1–60자로 입력해 주세요.',
  whyChosen: '0–120자로 입력해 주세요.',
  question: '1–80자로 입력해 주세요.',
  authoring: '작성 정보가 올바르지 않아요.',
  mode: 'MANUAL 또는 AI_EDITED여야 해요.',
  durationMs: '0 이상의 정수로 입력해 주세요.',
  aiSessionId: '문자열이어야 해요.',
  story: '1–1000자로 입력해 주세요.',
};
const GENERIC = '형식이 올바르지 않아요.';

type Obj = { [k: string]: unknown };
const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);
const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v);
const len = (s: string) => [...s].length;

function str(details: Details, obj: Obj, key: string, path: string, min: number, max: number) {
  if (!(key in obj)) return void (details[path] ??= REQUIRED);
  const v = obj[key];
  if (typeof v !== 'string' || len(v) < min || len(v) > max) details[path] ??= FIELD_MESSAGES[key] ?? GENERIC;
}

/** 오류가 없으면 null */
export function validateCreatePlan(body: unknown): Details | null {
  const d: Details = {};
  if (!isObj(body)) return { body: GENERIC };

  str(d, body, 'title', 'title', 1, 40);
  str(d, body, 'summary', 'summary', 1, 120);
  str(d, body, 'reason', 'reason', 1, 300);
  if (!('estimatedMinutes' in body)) d.estimatedMinutes = REQUIRED;
  else {
    const m = body.estimatedMinutes;
    if (!isInt(m) || m < 10 || m > 240) d.estimatedMinutes = FIELD_MESSAGES.estimatedMinutes;
  }

  if (!('places' in body)) d.places = REQUIRED;
  else if (!Array.isArray(body.places) || body.places.length < 1 || body.places.length > 3) {
    d.places = FIELD_MESSAGES.places;
  }
  if (Array.isArray(body.places)) {
    body.places.forEach((p, i) => {
      const prefix = `places[${i}]`;
      if (!isObj(p)) return void (d[prefix] ??= GENERIC);
      str(d, p, 'name', `${prefix}.name`, 1, 30);
      str(d, p, 'activity', `${prefix}.activity`, 1, 60);
      str(d, p, 'whyChosen', `${prefix}.whyChosen`, 0, 120);
    });
  }
  str(d, body, 'question', 'question', 1, 80);

  if (!('authoring' in body)) d.authoring = REQUIRED;
  else if (!isObj(body.authoring)) d.authoring = FIELD_MESSAGES.authoring;
  else {
    const a = body.authoring;
    if (!('mode' in a)) d['authoring.mode'] = REQUIRED;
    else if (a.mode !== 'MANUAL' && a.mode !== 'AI_EDITED') d['authoring.mode'] = FIELD_MESSAGES.mode;
    if (!('durationMs' in a)) d['authoring.durationMs'] = REQUIRED;
    else if (!isInt(a.durationMs) || a.durationMs < 0) d['authoring.durationMs'] = FIELD_MESSAGES.durationMs;
    if ('aiSessionId' in a && a.aiSessionId !== null && typeof a.aiSessionId !== 'string') {
      d['authoring.aiSessionId'] = FIELD_MESSAGES.aiSessionId;
    }
    str(d, a, 'story', 'authoring.story', 1, 1000);
  }
  return Object.keys(d).length ? d : null;
}
