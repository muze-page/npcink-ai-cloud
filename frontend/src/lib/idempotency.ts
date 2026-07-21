/**
 * Idempotency Key Generation
 *
 * Portal write operations require Idempotency-Key headers to prevent
 * duplicate mutations on retry.
 */

const IDEMPOTENCY_KEY_MAX_LENGTH = 128;

function isAsciiLetterOrDigit(character: string): boolean {
  const code = character.charCodeAt(0);
  return (
    (code >= 48 && code <= 57) ||
    (code >= 65 && code <= 90) ||
    (code >= 97 && code <= 122)
  );
}

function isIdempotencyKeyCharacter(character: string): boolean {
  return (
    isAsciiLetterOrDigit(character) ||
    character === '.' ||
    character === '_' ||
    character === ':' ||
    character === '-'
  );
}

function isIdempotencyKeyPunctuation(character: string): boolean {
  return character === '.' || character === '_' || character === ':' || character === '-';
}

function normalizeIdempotencyPrefix(prefix: string): string {
  const source = String(prefix || '').trim();
  const normalized: string[] = [];
  let previousCharacterWasInvalid = false;

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (isIdempotencyKeyCharacter(character)) {
      normalized.push(character);
      previousCharacterWasInvalid = false;
    } else if (!previousCharacterWasInvalid) {
      normalized.push('_');
      previousCharacterWasInvalid = true;
    }
  }

  let start = 0;
  while (start < normalized.length && isIdempotencyKeyPunctuation(normalized[start])) {
    start += 1;
  }

  let end = normalized.length;
  while (end > start && isIdempotencyKeyPunctuation(normalized[end - 1])) {
    end -= 1;
  }

  return normalized.slice(start, end).join('') || 'cloud_operation';
}

function trimTrailingIdempotencyKeyPunctuation(value: string): string {
  let end = value.length;
  while (end > 0 && isIdempotencyKeyPunctuation(value[end - 1])) {
    end -= 1;
  }
  return value.slice(0, end);
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
  const truncatedPrefix = trimTrailingIdempotencyKeyPunctuation(
    normalizeIdempotencyPrefix(prefix).slice(0, maxPrefixLength)
  );
  const safePrefix = truncatedPrefix || 'cloud_operation';
  return `${safePrefix}_${suffix}`;
}

/**
 * Validate idempotency key format
 */
export function isValidIdempotencyKey(key: string): boolean {
  if (
    typeof key !== 'string' ||
    key.length === 0 ||
    key.length > IDEMPOTENCY_KEY_MAX_LENGTH
  ) {
    return false;
  }

  for (let index = 0; index < key.length; index += 1) {
    if (!isIdempotencyKeyCharacter(key[index])) {
      return false;
    }
  }
  return true;
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
