import { CloudApiError, getErrorMessage } from './envelope';

/**
 * Frontend Error Types
 */

/**
 * Session error - user needs to log in or re-authenticate
 */
export class SessionError extends CloudApiError {
  constructor(message: string, errorCode?: string) {
    super(errorCode || 'auth.session_required', message);
    this.name = 'SessionError';
  }
}

/**
 * Site selection error - user needs to select a site
 */
export class SiteSelectionError extends CloudApiError {
  constructor(message: string) {
    super('auth.site_selection_required', message);
    this.name = 'SiteSelectionError';
  }
}

/**
 * API error with additional context
 */
export class ApiError extends CloudApiError {
  constructor(
    errorCode: string,
    message: string,
    public readonly statusCode?: number,
    public readonly responseBody?: unknown
  ) {
    super(errorCode, message);
    this.name = 'ApiError';
  }

  static fromResponse(
    response: Response,
    body: unknown
  ): ApiError {
    const errorCode =
      body && typeof body === 'object' && 'error_code' in body
        ? String((body as { error_code?: string }).error_code || 'unknown')
        : 'unknown';

    const message =
      body && typeof body === 'object' && 'message' in body
        ? String((body as { message?: string }).message)
        : getErrorMessage(errorCode);

    return new ApiError(errorCode, message, response.status, body);
  }
}

/**
 * Network error - failed to reach the API
 */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
  }
}

/**
 * Validation error - client-side validation failed
 */
export class ValidationError extends Error {
  constructor(
    message: string,
    public readonly field?: string
  ) {
    super(message);
    this.name = 'ValidationError';
  }
}

/**
 * Create error from Cloud API error code
 */
export function createErrorFromCode(errorCode: string, message?: string): CloudApiError {
  if (errorCode.startsWith('auth.')) {
    if (errorCode === 'auth.session_required') {
      return new SessionError(message || getErrorMessage(errorCode), errorCode);
    }
    if (errorCode === 'auth.site_selection_required') {
      return new SiteSelectionError(message || getErrorMessage(errorCode));
    }
  }

  return new CloudApiError(errorCode, message || getErrorMessage(errorCode));
}

/**
 * Handle error and return user-friendly message
 */
export function getErrorMessageFromError(error: unknown): string {
  if (error instanceof CloudApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'An unexpected error occurred';
}

/**
 * Check if error requires redirect to login
 */
export function requiresLogin(error: unknown): boolean {
  if (error instanceof CloudApiError) {
    return error.isAuthError;
  }
  return false;
}

/**
 * Check if error requires site selection
 */
export function requiresSiteSelection(error: unknown): boolean {
  return error instanceof SiteSelectionError;
}
// ============================================
// UI Error Message Resolution
// ============================================

const GENERIC_ENGLISH_ERROR_PATTERNS: RegExp[] = [
  /^failed to /i,
  /^error\b/i,
  /^unexpected error/i,
  /^unable to /i,
  /^request failed/i,
  /^internal server error$/i,
  /^forbidden$/i,
  /^unauthorized$/i,
  /^bad request$/i,
];

function containsCjk(value: string): boolean {
  return /[\u3400-\u9fff]/.test(value);
}

/**
 * Resolve a user-friendly error message from a raw error string.
 * If the message is a generic English error pattern, returns the fallback.
 * If the message contains CJK characters, returns it as-is.
 */
export function resolveUiErrorMessage(message: unknown, fallback: string): string {
  if (typeof message !== 'string') {
    return fallback;
  }

  const normalized = message.trim();
  if (!normalized) {
    return fallback;
  }

  if (containsCjk(normalized)) {
    return normalized;
  }

  if (GENERIC_ENGLISH_ERROR_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return fallback;
  }

  return normalized;
}
