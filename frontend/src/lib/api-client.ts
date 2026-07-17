import { ApiError } from './errors';
import {
  generateIdempotencyKey,
  isValidIdempotencyKey,
} from './idempotency';

export type ApiMethod = 'GET' | 'HEAD' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface ApiEnvelopeMeta {
  trace_id: string;
  revision: string;
}

export interface ApiEnvelope<T = unknown> {
  status: 'ok' | 'error';
  error_code: string;
  message: string;
  data: T;
  meta: ApiEnvelopeMeta;
}

export interface ApiClientConfig {
  baseUrl?: string;
  headers?: HeadersInit;
  credentials?: RequestCredentials;
  cache?: RequestCache;
  idempotencyPrefix?: string;
  idempotencyKeyFactory?: (prefix: string) => string;
}

export interface ApiRequestOptions {
  method?: ApiMethod;
  body?: unknown;
  headers?: HeadersInit;
  credentials?: RequestCredentials;
  cache?: RequestCache;
  signal?: AbortSignal;
  idempotencyKey?: string;
}

const SAFE_METHODS = new Set<ApiMethod>(['GET', 'HEAD']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isApiEnvelope(value: unknown): value is ApiEnvelope<unknown> {
  if (!isRecord(value)) {
    return false;
  }

  const meta = value.meta;
  return (
    (value.status === 'ok' || value.status === 'error') &&
    typeof value.error_code === 'string' &&
    (value.status === 'ok' || value.error_code.trim().length > 0) &&
    typeof value.message === 'string' &&
    Object.prototype.hasOwnProperty.call(value, 'data') &&
    value.data !== undefined &&
    isRecord(meta) &&
    typeof meta.trace_id === 'string' &&
    typeof meta.revision === 'string' &&
    meta.revision.trim().length > 0
  );
}

function joinUrl(baseUrl: string, path: string): string {
  const normalizedPath = String(path || '').trim();
  if (/^https?:\/\//i.test(normalizedPath)) {
    return normalizedPath;
  }

  const normalizedBase = String(baseUrl || '').replace(/\/$/, '');
  if (!normalizedBase) {
    return normalizedPath || '/';
  }
  if (!normalizedPath) {
    return normalizedBase;
  }
  return `${normalizedBase}/${normalizedPath.replace(/^\//, '')}`;
}

function normalizeIdempotencyPrefix(value: string): string {
  const normalized = String(value || '')
    .trim()
    .replace(/[^A-Za-z0-9._:-]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return normalized || 'api_write';
}

function assertIdempotencyKey(value: string): string {
  if (!isValidIdempotencyKey(value)) {
    throw new TypeError(
      'Idempotency-Key must contain 1-128 letters, numbers, dots, underscores, colons, or hyphens'
    );
  }
  return value;
}

function extractEnvelopeEvidence(value: unknown): {
  errorCode: string;
  message: string;
  details: unknown;
  traceId: string;
  revision: string;
} {
  if (!isRecord(value)) {
    return {
      errorCode: '',
      message: '',
      details: undefined,
      traceId: '',
      revision: '',
    };
  }

  const meta = isRecord(value.meta) ? value.meta : {};
  return {
    errorCode: typeof value.error_code === 'string' ? value.error_code : '',
    message: typeof value.message === 'string' ? value.message : '',
    details: Object.prototype.hasOwnProperty.call(value, 'details')
      ? value.details
      : value.data,
    traceId: typeof meta.trace_id === 'string' ? meta.trace_id : '',
    revision: typeof meta.revision === 'string' ? meta.revision : '',
  };
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly defaultHeaders: Headers;
  private readonly defaultCredentials: RequestCredentials;
  private readonly defaultCache: RequestCache;
  private readonly idempotencyPrefix: string;
  private readonly idempotencyKeyFactory: (prefix: string) => string;

  constructor(config: ApiClientConfig = {}) {
    this.baseUrl = String(config.baseUrl || '').trim();
    this.defaultHeaders = new Headers(config.headers);
    this.defaultCredentials = config.credentials || 'include';
    this.defaultCache = config.cache || 'no-store';
    this.idempotencyPrefix = normalizeIdempotencyPrefix(
      config.idempotencyPrefix || 'api_write'
    );
    this.idempotencyKeyFactory = config.idempotencyKeyFactory || generateIdempotencyKey;
  }

  async request<T>(path: string, options: ApiRequestOptions = {}): Promise<ApiEnvelope<T>> {
    const method = options.method || 'GET';
    const headers = new Headers(this.defaultHeaders);
    new Headers(options.headers).forEach((value, key) => headers.set(key, value));

    const isWrite = !SAFE_METHODS.has(method);
    if (isWrite) {
      const requestedKey =
        options.idempotencyKey !== undefined
          ? options.idempotencyKey
          : headers.has('Idempotency-Key')
            ? headers.get('Idempotency-Key') || ''
            : this.idempotencyKeyFactory(this.idempotencyPrefix);
      headers.set('Idempotency-Key', assertIdempotencyKey(requestedKey));
    } else if (options.idempotencyKey !== undefined || headers.has('Idempotency-Key')) {
      throw new TypeError(`Idempotency-Key is not valid for ${method} requests`);
    }

    let body: string | undefined;
    if (options.body !== undefined) {
      if (SAFE_METHODS.has(method)) {
        throw new TypeError(`${method} requests must not include a body`);
      }
      headers.set('Content-Type', headers.get('Content-Type') || 'application/json');
      const serializedBody = JSON.stringify(options.body);
      if (serializedBody === undefined) {
        throw new TypeError('API request body must be JSON serializable');
      }
      body = serializedBody;
    }

    let response: Response;
    try {
      response = await fetch(joinUrl(this.baseUrl, path), {
        method,
        headers,
        body,
        credentials: options.credentials || this.defaultCredentials,
        cache: options.cache || this.defaultCache,
        signal: options.signal,
      });
    } catch (cause) {
      throw new ApiError({
        statusCode: 0,
        errorCode: 'client.network_error',
        message: cause instanceof Error ? cause.message : 'Network request failed',
        details: cause,
        rawBody: undefined,
        cause,
      });
    }

    const contentType = response.headers.get('content-type') || '';
    const rawText = await response.text();
    if (!contentType.toLowerCase().includes('json')) {
      throw new ApiError({
        statusCode: response.status,
        errorCode: 'client.non_json_response',
        message: `Expected a JSON response but received ${contentType || 'unknown content type'}`,
        details: rawText,
        rawBody: rawText,
      });
    }

    let rawBody: unknown;
    try {
      rawBody = JSON.parse(rawText);
    } catch (cause) {
      throw new ApiError({
        statusCode: response.status,
        errorCode: 'client.invalid_json_response',
        message: 'API response body is not valid JSON',
        details: rawText,
        rawBody: rawText,
        cause,
      });
    }

    if (!isApiEnvelope(rawBody)) {
      const evidence = extractEnvelopeEvidence(rawBody);
      throw new ApiError({
        statusCode: response.status,
        errorCode: 'client.invalid_envelope',
        message: evidence.message || 'API response does not match the Cloud envelope contract',
        details: {
          response_error_code: evidence.errorCode,
          response_data: evidence.details,
        },
        traceId: evidence.traceId,
        revision: evidence.revision,
        rawBody,
      });
    }

    if (!response.ok || rawBody.status === 'error') {
      throw new ApiError({
        statusCode: response.status,
        errorCode: rawBody.error_code || `http.${response.status}`,
        message: rawBody.message || `API request failed with HTTP ${response.status}`,
        details: rawBody.data,
        traceId: rawBody.meta.trace_id,
        revision: rawBody.meta.revision,
        rawBody,
      });
    }

    return rawBody as ApiEnvelope<T>;
  }
}

export function createApiClient(config?: ApiClientConfig): ApiClient {
  return new ApiClient(config);
}

const defaultApiClient = createApiClient();

export function requestApi<T>(
  path: string,
  options?: ApiRequestOptions
): Promise<ApiEnvelope<T>> {
  return defaultApiClient.request<T>(path, options);
}
