/**
 * Cloud API Envelope Contract
 * 
 * All Cloud API responses follow this envelope structure:
 * {
 *   status: "ok" | "error",
 *   error_code?: string,
 *   message: string,
 *   data?: unknown,
 *   meta?: {
 *     trace_id?: string,
 *     revision: string
 *   }
 * }
 */

export interface CloudEnvelope<T = unknown> {
  status: 'ok' | 'error';
  error_code?: string;
  message: string;
  data?: T;
  meta?: {
    trace_id?: string;
    revision: string;
  };
}

/**
 * Unwrap Cloud API envelope and extract data
 * @param envelope - The Cloud API response envelope
 * @returns The data payload
 * @throws {Error} If envelope status is "error"
 */
export function unwrapEnvelope<T>(envelope: CloudEnvelope<T>): T {
  if (envelope.status === 'error') {
    throw new CloudApiError(
      envelope.error_code || 'unknown_error',
      envelope.message
    );
  }
  
  if (envelope.data === undefined) {
    throw new Error('Expected data in envelope but got undefined');
  }
  
  return envelope.data;
}

/**
 * Check if envelope represents an error state
 */
export function isErrorEnvelope(
  envelope: CloudEnvelope<unknown>
): envelope is CloudEnvelope<unknown> & { status: 'error' } {
  return envelope.status === 'error';
}

/**
 * Cloud API Error
 */
export class CloudApiError extends Error {
  constructor(
    public readonly errorCode: string,
    message: string
  ) {
    super(message);
    this.name = 'CloudApiError';
  }

  /**
   * Check if this is an authentication error
   */
  get isAuthError(): boolean {
    return this.errorCode.startsWith('auth.');
  }

  /**
   * Check if this is a commercial/business error
   */
  get isCommercialError(): boolean {
    return this.errorCode.startsWith('commercial.');
  }

  /**
   * Check if this is a service error
   */
  get isServiceError(): boolean {
    return this.errorCode.startsWith('service.');
  }

  /**
   * Check if this is a rate limit error
   */
  get isRateLimitError(): boolean {
    return this.errorCode === 'auth.rate_limit_exceeded';
  }
}

/**
 * Map Cloud API error codes to user-friendly messages
 */
export function getErrorMessage(errorCode: string): string {
  const messages: Record<string, string> = {
    'auth.session_required': 'Please log in to continue',
    'auth.site_selection_required': 'Please select a site to continue',
    'auth.portal_not_configured': 'Portal authentication is not configured',
    'auth.invalid_key': 'Invalid API key',
    'auth.rate_limit_exceeded': 'Too many requests. Please try again later',
    'portal.login_invalid': 'Invalid login credentials',
    'portal.site_invalid': 'Invalid site selection',
    'portal.email_delivery_failed': 'Failed to send login email',
    'commercial.subscription_inactive': 'Subscription is not active',
    'commercial.entitlement_denied': 'Access denied by subscription',
    'commercial.quota_exceeded': 'Usage quota exceeded',
    'commercial.concurrency_exceeded': 'Too many concurrent operations',
    'service.site_not_found': 'Site not found',
    'service.key_not_found': 'API key not found',
    'service.member_not_found': 'Member not found',
  };

  return messages[errorCode] || 'An unexpected error occurred';
}