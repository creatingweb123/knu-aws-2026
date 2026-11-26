import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest';

import { setUnauthorizedHandler } from '../api/client';
import { setTokenProvider } from '../auth/tokens';
import { setPhotoProcessMs } from '../mocks/photos';
import { server } from './server';

// jsdom은 location.assign 이동을 지원하지 않는다. 401 이동은 테스트마다 필요하면 바꿔 확인한다
const noRedirect = () => undefined;

// jsdom의 Blob(File)에 없는 메서드를 채운다. Node fetch(undici)는 업로드 본문의 stream()을 부른다
if (typeof Blob.prototype.arrayBuffer !== 'function') {
  Blob.prototype.arrayBuffer = function arrayBuffer(this: Blob) {
    return new Promise<ArrayBuffer>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(this);
    });
  };
}
if (typeof Blob.prototype.stream !== 'function') {
  Blob.prototype.stream = function stream(this: Blob) {
    const read = this.arrayBuffer.bind(this);
    return new ReadableStream<Uint8Array>({
      async start(controller) {
        controller.enqueue(new Uint8Array(await read()));
        controller.close();
      },
    });
  } as Blob['stream'];
}

// 테스트 파일을 병렬로 돌리면 첫 렌더·첫 요청이 1초(기본값)를 넘길 때가 있어 findBy/waitFor 대기를 늘린다
configure({ asyncUtilTimeout: 5000 });

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  setUnauthorizedHandler(noRedirect);
  // 사진 처리 지연(목업 기본 3초)을 없앤다. 업로드 직후 첫 조회에서 처리가 끝난다
  setPhotoProcessMs(0);
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  setTokenProvider(null);
  localStorage.clear();
  sessionStorage.clear();
});
afterAll(() => server.close());
