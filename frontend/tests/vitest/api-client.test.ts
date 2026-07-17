import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/errors';

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set('content-type', 'application/json; charset=utf-8');
  return new Response(JSON.stringify(body), { ...init, headers });
}

function successEnvelope<T>(data: T) {
  return {
    status: 'ok' as const,
    error_code: '',
    message: 'loaded',
    data,
    meta: {
      trace_id: 'trace-success',
      revision: 'm6',
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('ApiClient', () => {
  it('returns a validated success envelope and forwards cookie, headers, and signal', async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(successEnvelope({ account_id: 'acct_1' }))
    );
    vi.stubGlobal('fetch', fetchMock);

    const client = new ApiClient({
      baseUrl: '/api/portal',
      headers: { 'X-Client': 'portal' },
    });
    const response = await client.request<{ account_id: string }>('/session', {
      headers: { 'X-Request': 'session' },
      signal,
    });

    expect(response.data.account_id).toBe('acct_1');
    expect(response.meta.trace_id).toBe('trace-success');
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe('/api/portal/session');
    expect(init.credentials).toBe('include');
    expect(init.cache).toBe('no-store');
    expect(init.signal).toBe(signal);
    expect(headers.get('x-client')).toBe('portal');
    expect(headers.get('x-request')).toBe('session');
  });

  it('throws one evidence-rich ApiError for an HTTP error envelope', async () => {
    const body = {
      status: 'error',
      error_code: 'service.principal_access_required',
      message: 'principal access is required',
      data: { account_id: 'acct_denied' },
      meta: { trace_id: 'trace-denied', revision: 'm6' },
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(body, { status: 403 })));

    const client = new ApiClient();
    await expect(client.request('/api/portal/sites')).rejects.toMatchObject({
      name: 'ApiError',
      statusCode: 403,
      errorCode: 'service.principal_access_required',
      message: 'principal access is required',
      details: { account_id: 'acct_denied' },
      traceId: 'trace-denied',
      revision: 'm6',
      rawBody: body,
    });
  });

  it('fails closed when HTTP 200 carries status:error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: 'error',
          error_code: 'commercial.quota_exceeded',
          message: 'quota exceeded',
          data: { limit: 10 },
          meta: { trace_id: 'trace-quota', revision: 'm6' },
        })
      )
    );

    await expect(new ApiClient().request('/api/portal/usage')).rejects.toMatchObject({
      statusCode: 200,
      errorCode: 'commercial.quota_exceeded',
      traceId: 'trace-quota',
    });
  });

  it('fails closed for non-JSON responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('<html>bad gateway</html>', {
          status: 502,
          headers: { 'content-type': 'text/html' },
        })
      )
    );

    await expect(new ApiClient().request('/api/admin/overview')).rejects.toMatchObject({
      statusCode: 502,
      errorCode: 'client.non_json_response',
      rawBody: '<html>bad gateway</html>',
    });
  });

  it('fails closed for an invalid Cloud envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: 'ok',
          message: 'missing required evidence',
          data: {},
        })
      )
    );

    await expect(new ApiClient().request('/api/admin/overview')).rejects.toMatchObject({
      statusCode: 200,
      errorCode: 'client.invalid_envelope',
      message: 'missing required evidence',
    });
  });

  it('always sends a valid idempotency key for writes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(successEnvelope({ saved: true })));
    vi.stubGlobal('fetch', fetchMock);
    const client = new ApiClient({
      idempotencyPrefix: 'admin_write',
      idempotencyKeyFactory: (prefix) => `${prefix}_fixed`,
    });

    await client.request('/api/admin/accounts', {
      method: 'POST',
      body: { name: 'Example' },
    });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get('idempotency-key')).toBe('admin_write_fixed');
    expect(headers.get('content-type')).toBe('application/json');
    expect(init.body).toBe(JSON.stringify({ name: 'Example' }));

    await expect(
      client.request('/api/admin/accounts', {
        method: 'PATCH',
        idempotencyKey: 'contains spaces',
      })
    ).rejects.toBeInstanceOf(TypeError);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('wraps network failures in the same ApiError model', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')));

    const error = await new ApiClient().request('/api/portal/session').catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      statusCode: 0,
      errorCode: 'client.network_error',
      message: 'connection refused',
    });
  });
});
