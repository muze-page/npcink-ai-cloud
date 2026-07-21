export interface ApiErrorInit {
  statusCode: number;
  errorCode: string;
  message: string;
  details?: unknown;
  traceId?: string;
  revision?: string;
  rawBody?: unknown;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly statusCode: number;
  readonly errorCode: string;
  readonly details: unknown;
  readonly traceId: string;
  readonly revision: string;
  readonly rawBody: unknown;
  override readonly cause: unknown;

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = 'ApiError';
    this.statusCode = init.statusCode;
    this.errorCode = init.errorCode;
    this.details = init.details;
    this.traceId = init.traceId || '';
    this.revision = init.revision || '';
    this.rawBody = init.rawBody;
    this.cause = init.cause;
  }

  get isAuthError(): boolean {
    return this.statusCode === 401 || this.errorCode.startsWith('auth.');
  }

  get isRateLimitError(): boolean {
    return this.statusCode === 429 || this.errorCode.includes('rate_limit');
  }
}

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

function extractMessage(value: unknown): string {
  if (value instanceof Error) {
    return String(value.message || '').trim();
  }
  if (typeof value === 'string') {
    return value.trim();
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return '';
  }

  const record = value as Record<string, unknown>;
  for (const candidate of [record.message, record.detail, record.error_code]) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate.trim();
    }
  }
  return '';
}

export function resolveUiErrorMessage(error: unknown, fallback: string): string {
  const normalized = extractMessage(error);
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
