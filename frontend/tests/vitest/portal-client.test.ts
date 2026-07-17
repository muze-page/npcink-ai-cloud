import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/errors';
import { PortalClient } from '@/lib/portal-client';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('PortalClient shared transport', () => {
  it('uses the canonical ApiClient transport for cookie session reads and writes', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          status: 'ok',
          error_code: '',
          message: 'loaded',
          data: { site_id: 'site_1', sites: [] },
          meta: { trace_id: 'trace-session', revision: 'm6' },
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: 'ok',
          error_code: '',
          message: 'logged out',
          data: {},
          meta: { trace_id: 'trace-logout', revision: 'm6' },
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: 'ok',
          error_code: '',
          message: 'selected',
          data: { site_id: 'site_1', sites: [] },
          meta: { trace_id: 'trace-select', revision: 'm6' },
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: 'ok',
          error_code: '',
          message: 'cancelled',
          data: {},
          meta: { trace_id: 'trace-cancel', revision: 'm6' },
        })
      );
    vi.stubGlobal('fetch', fetchMock);

    const client = new PortalClient('/api/portal');
    const session = await client.getSession();
    await client.logout();
    await client.selectSite('site_1');
    await client.cancelSubscriptionOrder('order_1');

    expect(session.meta.trace_id).toBe('trace-session');
    const [sessionUrl, sessionInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(sessionUrl).toBe('/api/portal/session');
    expect(sessionInit.credentials).toBe('include');
    expect(new Headers(sessionInit.headers).has('idempotency-key')).toBe(false);

    const [logoutUrl, logoutInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(logoutUrl).toBe('/api/portal/logout');
    expect(new Headers(logoutInit.headers).get('idempotency-key')).toMatch(
      /^[A-Za-z0-9._:-]{1,128}$/
    );

    const [selectUrl, selectInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(selectUrl).toBe('/api/portal/session/site');
    expect(selectInit.method).toBe('POST');
    expect(new Headers(selectInit.headers).get('idempotency-key')).toMatch(
      /^[A-Za-z0-9._:-]{1,128}$/
    );

    const [cancelUrl, cancelInit] = fetchMock.mock.calls[3] as [string, RequestInit];
    expect(cancelUrl).toBe('/api/portal/account/subscription-orders/order_1');
    expect(cancelInit.method).toBe('DELETE');
    expect(new Headers(cancelInit.headers).get('idempotency-key')).toMatch(
      /^[A-Za-z0-9._:-]{1,128}$/
    );
  });

  it('throws ApiError when HTTP 200 carries a canonical error envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: 'error',
          error_code: 'auth.portal_session_required',
          message: 'session required',
          data: {},
          meta: { trace_id: 'trace-auth', revision: 'm6' },
        })
      )
    );

    const error = await new PortalClient('/api/portal').getSession().catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      statusCode: 200,
      errorCode: 'auth.portal_session_required',
      traceId: 'trace-auth',
    });
  });
});
