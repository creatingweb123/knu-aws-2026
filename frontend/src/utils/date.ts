/** 서버 시간(UTC ISO 8601)을 한국 시간으로 표시한다(FE-COM-06). */

const TZ = 'Asia/Seoul';

const monthDay = new Intl.DateTimeFormat('ko-KR', { timeZone: TZ, month: 'long', day: 'numeric' });
const dateTime = new Intl.DateTimeFormat('ko-KR', {
  timeZone: TZ,
  month: 'long',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

function toDate(iso: string): Date {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) throw new RangeError(`잘못된 시간 값: ${iso}`);
  return d;
}

/** 예: "11월 21일" */
export function formatMonthDay(iso: string): string {
  return monthDay.format(toDate(iso));
}

/** 예: "11월 21일 오후 6:00" */
export function formatDateTime(iso: string): string {
  return dateTime.format(toDate(iso));
}

/** KST 기준 날짜 문자열 "YYYY-MM-DD" (비교·그룹용) */
export function kstDateKey(iso: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(toDate(iso));
  return parts;
}
