/** 키를 정렬한 JSON(백엔드 body_hash와 같은 방식의 정규화) */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    const out: { [k: string]: unknown } = {};
    for (const k of Object.keys(value).sort()) out[k] = sortKeys((value as { [k: string]: unknown })[k]);
    return out;
  }
  return value;
}

/**
 * 동기 문자열 해시(cyrb53). 본문이 바뀌었는지 판단하는 데만 쓴다.
 * 충돌해도 서버가 409 IDEMPOTENCY_CONFLICT를 돌려주고 새 키로 다시 보내므로 안전하다.
 */
export function hashString(s: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < s.length; i++) {
    const ch = s.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16);
}
