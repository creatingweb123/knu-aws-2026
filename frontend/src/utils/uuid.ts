/** `Idempotency-Key` 등에 쓰는 UUID v4. HTTPS(CloudFront)와 localhost에서 동작한다 */
export function newUuid(): string {
  return crypto.randomUUID();
}
