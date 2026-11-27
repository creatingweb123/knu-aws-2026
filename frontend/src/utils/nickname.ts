/**
 * 닉네임이 없을 때(`null`, BE-Q45) 화면에 쓰는 기본 표시명. 빈 문자열이나 "null"을 보이지 않게 한다.
 * 계획자 쪽은 "계획을 남긴 사람", 실행자 쪽은 "이어받은 사람"을 쓴다.
 */
export const OWNER_FALLBACK_NAME = '계획을 남긴 사람';
export const CLAIMER_FALLBACK_NAME = '이어받은 사람';

/** 닉네임이 있으면 그대로, 없거나 공백뿐이면 기본 표시명 */
export function displayNickname(nickname: string | null | undefined, fallback: string): string {
  return nickname && nickname.trim() ? nickname : fallback;
}

/** 아바타에 넣을 첫 글자(코드 포인트 기준) */
export function initialOf(name: string): string {
  return [...name][0] ?? '';
}
