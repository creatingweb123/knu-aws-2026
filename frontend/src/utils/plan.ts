/** 카드·상세의 보조 줄: `약 45분 · 장소 2곳` (FE-BRW-01) */
export function planMetaText(estimatedMinutes: number, placeCount: number): string {
  return `약 ${estimatedMinutes}분 · 장소 ${placeCount}곳`;
}
