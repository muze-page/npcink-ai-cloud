/**
 * Idempotency Key Generation
 * 
 * Portal write operations require Idempotency-Key headers to prevent
 * duplicate mutations on retry.
 */

/**
 * Generate a unique idempotency key
 * 
 * Format: <prefix>_<timestamp>_<random>
 * Example: portal_issue_key_1711180800000_abc123
 */
export function generateIdempotencyKey(
  prefix: string = 'cloud_operation'
): string {
  const timestamp = Date.now();
  const random = Math.random().toString(36).substring(2, 8);
  return `${prefix}_${timestamp}_${random}`;
}

/**
 * Validate idempotency key format
 */
export function isValidIdempotencyKey(key: string): boolean {
  // Basic validation: should be non-empty and contain only safe characters
  if (!key || key.length > 256) {
    return false;
  }
  
  // Should only contain alphanumeric, underscore, and hyphen
  return /^[a-zA-Z0-9_-]+$/.test(key);
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
  selectSite: (memberRef: string, siteId: string): string =>
    generateIdempotencyKey(`portal_select_site_${memberRef}_${siteId}`),
  
  /**
   * Logout operation
   */
  logout: (sessionToken: string): string =>
    generateIdempotencyKey(`portal_logout_${sessionToken}`),
};