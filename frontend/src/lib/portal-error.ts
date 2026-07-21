import { ApiError } from './errors';

type PortalTranslator = (
  key: string,
  params?: Record<string, string>,
  fallback?: string
) => string;

function appendErrorCode(message: string, errorCode: string): string {
  const normalizedMessage = String(message || '').trim();
  const normalizedCode = String(errorCode || '').trim();
  if (!normalizedCode) {
    return normalizedMessage;
  }
  return normalizedMessage ? `${normalizedMessage} [${normalizedCode}]` : `[${normalizedCode}]`;
}

export function formatPortalErrorMessage(
  error: unknown,
  t: PortalTranslator,
  fallbackMessage: string
): string {
  if (error instanceof ApiError) {
    switch (error.errorCode) {
      case 'portal.login_code_rate_limited':
        return appendErrorCode(
          t(
            'error.portal_rate_limited',
            { minutes: '15' },
            'Too many portal requests were sent in a short window. Wait a few minutes and try again.'
          ),
          error.errorCode
        );
      case 'auth.portal_login_code_invalid':
      case 'auth.portal_login_code_required':
      case 'auth.portal_email_change_code_invalid':
      case 'auth.portal_email_change_code_required':
        return appendErrorCode(
          t(
            'error.portal_login_code_invalid',
            undefined,
            'The verification code is invalid or expired. Request a new code and try again.'
          ),
          error.errorCode
        );
      case 'service.portal_email_change_same_email':
        return appendErrorCode(
          t(
            'portal.account.email_change_same_email',
            undefined,
            'This email is already your current login email.'
          ),
          error.errorCode
        );
      case 'service.portal_email_change_email_in_use':
        return appendErrorCode(
          t(
            'portal.account.email_change_email_in_use',
            undefined,
            'This email is already used by another Portal user.'
          ),
          error.errorCode
        );
      case 'auth.portal_session_required':
      case 'auth.portal_token_required':
        return appendErrorCode(
          t(
            'error.portal_sign_in_again',
            undefined,
            'Your portal session is missing or expired. Sign in again and reload this page.'
          ),
          error.errorCode
        );
      case 'auth.origin_required':
      case 'auth.origin_forbidden':
        return appendErrorCode(
          t(
            'error.portal_same_origin_required',
            undefined,
            'This browser request was rejected by same-origin protection. Reload the local portal page and try again.'
          ),
          error.errorCode
        );
      default:
        return appendErrorCode(error.message || fallbackMessage, error.errorCode);
    }
  }

  if (error instanceof Error) {
    const message = String(error.message || '').trim();
    return message || fallbackMessage;
  }

  return fallbackMessage;
}
