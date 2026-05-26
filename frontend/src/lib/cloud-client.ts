import { getRuntimeApiBaseUrl } from './env';
import type { CloudEnvelope } from './envelope';

export interface CloudClientConfig {
  baseUrl?: string;
  headers?: Record<string, string>;
}

/**
 * Cloud API Client
 * Handles communication with the Cloud backend API
 */
export class CloudClient {
  private baseUrl: string;
  private defaultHeaders: Record<string, string>;

  constructor(config: CloudClientConfig = {}) {
    this.baseUrl = config.baseUrl || getRuntimeApiBaseUrl();
    this.defaultHeaders = {
      'Content-Type': 'application/json',
      ...config.headers,
    };
  }

  /**
   * Build full URL from path
   */
  private buildUrl(path: string): string {
    const basePath = this.baseUrl.replace(/\/$/, '');
    const cleanPath = path.replace(/^\//, '');
    return `${basePath}/${cleanPath}`;
  }

  /**
   * Build request headers
   */
  private buildHeaders(customHeaders?: Record<string, string>): Record<string, string> {
    return {
      ...this.defaultHeaders,
      ...(customHeaders || {}),
    };
  }

  /**
   * GET request
   */
  async get<T>(
    path: string,
    options?: {
      headers?: Record<string, string>;
      signal?: AbortSignal;
    }
  ): Promise<CloudEnvelope<T>> {
    const response = await fetch(this.buildUrl(path), {
      method: 'GET',
      headers: this.buildHeaders(options?.headers),
      signal: options?.signal,
    });

    return this.parseResponse<T>(response);
  }

  /**
   * POST request with optional Idempotency-Key
   */
  async post<T>(
    path: string,
    data?: unknown,
    options?: {
      headers?: Record<string, string>;
      idempotencyKey?: string;
      signal?: AbortSignal;
    }
  ): Promise<CloudEnvelope<T>> {
    const headers: Record<string, string> = {
      ...this.buildHeaders(options?.headers),
    };

    if (options?.idempotencyKey) {
      headers['Idempotency-Key'] = options.idempotencyKey;
    }

    const response = await fetch(this.buildUrl(path), {
      method: 'POST',
      headers,
      body: data ? JSON.stringify(data) : undefined,
      signal: options?.signal,
    });

    return this.parseResponse<T>(response);
  }

  /**
   * Parse response and ensure envelope format
   */
  private async parseResponse<T>(response: Response): Promise<CloudEnvelope<T>> {
    const contentType = response.headers.get('content-type');
    
    if (!contentType?.includes('application/json')) {
      throw new Error(
        `Expected JSON response but got: ${contentType || 'unknown'}`
      );
    }

    const envelope: CloudEnvelope<T> = await response.json();

    // Validate envelope structure
    if (
      !envelope ||
      typeof envelope !== 'object' ||
      !('status' in envelope) ||
      !('message' in envelope)
    ) {
      throw new Error('Invalid Cloud API envelope structure');
    }

    return envelope;
  }
}

/**
 * Create a new Cloud API client instance
 */
export function createCloudClient(config?: CloudClientConfig): CloudClient {
  return new CloudClient(config);
}

/**
 * Default client instance for server-side use
 */
let defaultClient: CloudClient | undefined;

export function getDefaultClient(): CloudClient {
  if (!defaultClient) {
    defaultClient = new CloudClient();
  }
  return defaultClient;
}
