import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

vi.mock('@/lib/env', () => ({
  getApiBaseUrl: () => 'http://api:8000',
  getPublicBaseUrl: () => 'https://cloud.example.com',
}));

import { proxySetupPath, SETUP_SESSION_COOKIE } from '@/app/api/setup/_shared';

function envelope(data: Record<string, unknown> = {}) {
  return JSON.stringify({
    status: 'ok',
    error_code: '',
    message: 'ok',
    data,
    meta: { trace_id: '', revision: 'first-install-v1' },
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('setup BFF', () => {
  it('returns a stable 503 when the setup-state backend request hangs', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          'abort',
          () => reject(new DOMException('setup state timed out', 'AbortError')),
          { once: true }
        );
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const responsePromise = proxySetupPath(
      new NextRequest('https://cloud.example.com/api/setup/state'),
      ['state']
    );
    await vi.advanceTimersByTimeAsync(5000);
    const response = await responsePromise;

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      error_code: 'setup.state_unavailable',
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('forwards only the setup cookie and trusted client IP evidence', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      expect(headers.get('cookie')).toBe(`${SETUP_SESSION_COOKIE}=session-value`);
      expect(headers.get('x-real-ip')).toBe('203.0.113.10');
      expect(headers.has('x-forwarded-for')).toBe(false);
      expect(headers.has('x-npcink-internal-token')).toBe(false);
      expect(headers.get('host')).toBe('cloud.example.com');
      expect(headers.get('x-forwarded-host')).toBe('cloud.example.com');
      expect(headers.get('x-forwarded-proto')).toBe('https');
      expect(headers.get('origin')).toBe('https://attacker.example');
      expect(headers.get('referer')).toBe('https://attacker.example/setup-form');
      return new Response(envelope({ postgres_major_version: 18 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const request = new NextRequest('https://cloud.example.com/api/setup/database/test', {
      method: 'POST',
      headers: {
        cookie: `${SETUP_SESSION_COOKIE}=session-value; unrelated_cookie=must-not-forward`,
        'content-type': 'application/json',
        'x-real-ip': '203.0.113.10',
        'x-forwarded-for': '198.51.100.9',
        host: 'attacker.example',
        origin: 'https://attacker.example',
        referer: 'https://attacker.example/setup-form',
      },
      body: JSON.stringify({}),
    });

    const response = await proxySetupPath(request, ['database', 'test']);
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('lets the backend decide whether a missing session is pending or complete', async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({
        status: 'error',
        error_code: 'setup.already_complete',
        message: 'setup is already complete',
        data: {},
        meta: { trace_id: '', revision: 'first-install-v1' },
      }),
      { status: 404, headers: { 'content-type': 'application/json' } }
    ));
    vi.stubGlobal('fetch', fetchMock);

    const request = new NextRequest('https://cloud.example.com/api/setup/database/test', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    });

    const response = await proxySetupPath(request, ['database', 'test']);
    expect(response.status).toBe(404);
    expect(fetchMock).toHaveBeenCalledOnce();
    await expect(response.json()).resolves.toMatchObject({
      error_code: 'setup.already_complete',
    });
  });

  it('copies only the backend setup-session cookie', async () => {
    const fetchMock = vi.fn(async () => {
      const headers = new Headers({ 'content-type': 'application/json' });
      headers.append(
        'set-cookie',
        `${SETUP_SESSION_COOKIE}=issued-session; Path=/; HttpOnly; Secure; SameSite=Strict`
      );
      headers.append('set-cookie', 'backend_private_cookie=must-not-forward; Path=/; HttpOnly');
      return new Response(envelope({ expires_in_seconds: 900 }), { status: 200, headers });
    });
    vi.stubGlobal('fetch', fetchMock);

    const request = new NextRequest('https://cloud.example.com/api/setup/session', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ setup_code: 'nca_setup_test-only' }),
    });

    const response = await proxySetupPath(request, ['session']);
    const setCookies = response.headers.getSetCookie();
    expect(setCookies).toHaveLength(1);
    expect(setCookies[0]).toContain(`${SETUP_SESSION_COOKIE}=issued-session`);
    expect(setCookies[0]).not.toContain('backend_private_cookie');
  });
});
