/**
 * Idempotency Key Generation
 *
 * Portal write operations require Idempotency-Key headers to prevent
 * duplicate mutations on retry.
 */

const IDEMPOTENCY_KEY_MAX_LENGTH = 128;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;

function normalizeIdempotencyPrefix(prefix: string): string {
  const normalized = String(prefix || '')
    .trim()
    .replace(/[^A-Za-z0-9._:-]+/g, '_')
    .replace(/^[._:-]+|[._:-]+$/g, '');
  return normalized || 'cloud_operation';
}

/**
 * Generate a unique idempotency key
 *
 * Format: <prefix>_<timestamp>_<random>
 */
export function generateIdempotencyKey(
  prefix: string = 'cloud_operation'
): string {
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 14).padEnd(12, '0');
  const suffix = `${timestamp}_${random}`;
  const maxPrefixLength = IDEMPOTENCY_KEY_MAX_LENGTH - suffix.length - 1;
  const truncatedPrefix = normalizeIdempotencyPrefix(prefix)
    .slice(0, maxPrefixLength)
    .replace(/[._:-]+$/g, '');
  const safePrefix = truncatedPrefix || 'cloud_operation';
  return `${safePrefix}_${suffix}`;
}

/**
 * Validate idempotency key format
 */
export function isValidIdempotencyKey(key: string): boolean {
  return typeof key === 'string' && IDEMPOTENCY_KEY_PATTERN.test(key);
}

/**
 * Create idempotency key for specific operations
 */
export const IdempotencyKeys = {
  /**
   * Issue API key operation
   */
  issueKey: (siteId: string): string =>
    generateIdempotencyKey(`portal_issue_key_${siteId}`),

  /**
   * Rotate API key operation
   */
  rotateKey: (siteId: string, keyId: string): string =>
    generateIdempotencyKey(`portal_rotate_key_${siteId}_${keyId}`),

  /**
   * Revoke API key operation
   */
  revokeKey: (siteId: string, keyId: string): string =>
    generateIdempotencyKey(`portal_revoke_key_${siteId}_${keyId}`),

  /**
   * Select site operation
   */
  selectSite: (siteAdminRef: string, siteId: string): string =>
    generateIdempotencyKey(`portal_select_site_${siteAdminRef}_${siteId}`),

  /**
   * Logout operation
   */
  logout: (sessionToken: string): string => {
    void sessionToken;
    return generateIdempotencyKey('portal_logout');
  },
};
