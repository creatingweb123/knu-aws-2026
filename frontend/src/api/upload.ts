/**
 * presigned PUT 업로드(FE-REC-04). 우리 API가 아니라 S3 주소라 공통 클라이언트를 거치지 않고,
 * `Authorization`을 붙이지 않는다(FE-COM-05의 예외). URL·헤더는 받은 그대로 쓰고 파일을 변환하지 않는다
 * (Content-Type·Content-Length가 서명에 들어 있다). URL은 로그·오류 문구에 남기지 않는다(FE-NFR-05).
 */
import type { UploadInstruction } from './types';

export class UploadError extends Error {
  constructor(readonly status: number | null) {
    super(status === null ? '사진을 올리지 못했어요(네트워크).' : `사진을 올리지 못했어요(${status}).`);
    this.name = 'UploadError';
  }
}

const UPLOAD_TIMEOUT_MS = 60_000;

export async function uploadPhoto(upload: UploadInstruction, file: File): Promise<void> {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), UPLOAD_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(upload.url, {
      method: upload.method,
      headers: upload.headers,
      body: file,
      signal: timeout.signal,
    });
  } catch {
    throw new UploadError(null);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new UploadError(res.status);
}
