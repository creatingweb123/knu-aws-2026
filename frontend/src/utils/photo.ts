import type { PhotoContentType, PhotoMeta } from '../api/types';

/** 사진 1차 검사(FE-REC-03). 서버(사진 처리 Lambda)가 매직 바이트와 실제 크기를 다시 검사한다 */
export const PHOTO_MAX_BYTES = 10 * 1024 * 1024;
export const PHOTO_TYPES: readonly PhotoContentType[] = ['image/jpeg', 'image/png'];
export const PHOTO_ERROR = 'JPEG 또는 PNG, 10MB 이하 사진을 골라 주세요.';

export function validatePhoto(file: File): string | null {
  if (!PHOTO_TYPES.includes(file.type as PhotoContentType)) return PHOTO_ERROR;
  if (file.size < 1 || file.size > PHOTO_MAX_BYTES) return PHOTO_ERROR;
  return null;
}

/** `PUT /record`·`POST /record/photo`의 `photo` 값. 서명에 들어가므로 파일 그대로의 형식·크기다 */
export function photoMeta(file: File): PhotoMeta {
  return { contentType: file.type as PhotoContentType, size: file.size };
}
