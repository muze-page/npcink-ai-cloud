import { NextRequest, NextResponse } from 'next/server';
import { getApiBaseUrl, getPublicBaseUrl } from '@/lib/env';

export const SETUP_SESSION_COOKIE = 'npcink_setup_session';
const SETUP_STATE_TIMEOUT_MS = 5000;

type SetupMethod = 'GET' | 'POST';

type SetupRouteRule = {
  method: SetupMethod;
  path: string;
  backendPath: string;
  requiresSession: boolean;
  forwardsIdempotencyKey: boolean;
};

const SETUP_ROUTE_RULES: readonly SetupRouteRule[] = [
  {
    method: 'GET',
    path: 'state',
    backendPath: '/setup/v1/state',
    requiresSession: false,
    forwardsIdempotencyKey: false,
  },
  {
    method: 'POST',
    path: 'session',
    backendPath: '/setup/v1/session',
    requiresSession: false,
    forwardsIdempotencyKey: false,
  },
  {
    method: 'POST',
    path: 'database/test',
    backendPath: '/setup/v1/database/test',
    requiresSession: true,
    forwardsIdempotencyKey: false,
  },
  {
    method: 'POST',
    path: 'install',
    backendPath: '/setup/v1/install',
    requiresSession: true,
    forwardsIdempotencyKey: true,
  },
] as const;

function buildSetupErrorResponse(
  status: number,
  errorCode: string,
  message: string
): NextResponse {
  const response = NextResponse.json(
    {
      status: 'error',
      error_code: errorCode,
      message,
      data: {},
      meta: {
        trace_id: '',
        revision: 'setup-bff-v1',
      },
    },
    { status }
  );
  response.headers.set('Cache-Control', 'no-store');
  return response;
}

function resolveSetupRule(method: string, pathSegments: string[]): SetupRouteRule | null {
  const path = pathSegments.map((segment) => segment.trim()).filter(Boolean).join('/');
  return (
    SETUP_ROUTE_RULES.find((rule) => rule.method === method && rule.path === path) || null
  );
}

function readSetCookieHeaders(response: Response): string[] {
  const accessor = (response.headers as Headers & { getSetCookie?: () => string[] }).getSetCookie;
  if (typeof accessor === 'function') {
    return accessor.call(response.headers);
  }
  const value = response.headers.get('set-cookie');
  return value ? [value] : [];
}

function copySetupCookie(source: Response, target: NextResponse): void {
  for (const value of readSetCookieHeaders(source)) {
    const cookieName = value.split(';', 1)[0]?.split('=', 1)[0]?.trim();
    if (cookieName === SETUP_SESSION_COOKIE) {
      target.headers.append('set-cookie', value);
    }
  }
}

async function forwardSetupResponse(response: Response): Promise<NextResponse> {
  const contentType = response.headers.get('content-type') || '';
  const body = await response.arrayBuffer();
  const nextResponse = new NextResponse(body, {
    status: response.status,
    headers: {
      'Content-Type': contentType || 'application/octet-stream',
      'Cache-Control': 'no-store',
    },
  });
  copySetupCookie(response, nextResponse);
  return nextResponse;
}

function buildSetupHeaders(request: NextRequest, rule: SetupRouteRule): Headers {
  const headers = new Headers({ Accept: 'application/json' });
  const contentType = request.headers.get('content-type');
  const trustedOrigin = new URL(getPublicBaseUrl());
  const realIp = request.headers.get('x-real-ip');
  const locale = request.headers.get('accept-language');
  const setupCookie = request.cookies.get(SETUP_SESSION_COOKIE)?.value;

  if (contentType) {
    headers.set('Content-Type', contentType);
  }
  if (locale) {
    headers.set('Accept-Language', locale);
  }
  headers.set('Host', trustedOrigin.host);
  headers.set('X-Forwarded-Host', trustedOrigin.host);
  headers.set('X-Forwarded-Proto', trustedOrigin.protocol.replace(/:$/, ''));
  if (trustedOrigin.port) {
    headers.set('X-Forwarded-Port', trustedOrigin.port);
  }
  if (realIp) {
    headers.set('X-Real-IP', realIp);
  }
  headers.set('Origin', request.headers.get('origin') || trustedOrigin.origin);
  headers.set('Referer', request.headers.get('referer') || `${trustedOrigin.origin}/setup`);

  if (rule.requiresSession && setupCookie) {
    headers.set('Cookie', `${SETUP_SESSION_COOKIE}=${setupCookie}`);
  }
  if (rule.forwardsIdempotencyKey) {
    const idempotencyKey = request.headers.get('idempotency-key');
    if (idempotencyKey) {
      headers.set('Idempotency-Key', idempotencyKey);
    }
  }

  return headers;
}

export async function proxySetupPath(
  request: NextRequest,
  pathSegments: string[]
): Promise<NextResponse> {
  const method = request.method.toUpperCase();
  const rule = resolveSetupRule(method, pathSegments);
  if (!rule) {
    return buildSetupErrorResponse(404, 'proxy.setup_route_not_allowed', 'setup route is not allowed');
  }

  if (rule.forwardsIdempotencyKey && !request.headers.get('idempotency-key')) {
    return buildSetupErrorResponse(400, 'setup.idempotency_key_required', 'Idempotency-Key is required');
  }

  let body: ArrayBuffer | undefined;
  if (method !== 'GET') {
    body = await request.arrayBuffer();
    if (body.byteLength > 512 * 1024) {
      return buildSetupErrorResponse(413, 'setup.request_too_large', 'setup request is too large');
    }
  }

  let response: Response;
  const stateController = rule.path === 'state' ? new AbortController() : null;
  const stateTimeout = stateController
    ? setTimeout(() => stateController.abort(), SETUP_STATE_TIMEOUT_MS)
    : null;
  try {
    response = await fetch(`${getApiBaseUrl().replace(/\/$/, '')}${rule.backendPath}`, {
      method,
      headers: buildSetupHeaders(request, rule),
      body: body && body.byteLength > 0 ? body : undefined,
      cache: 'no-store',
      redirect: 'manual',
      ...(stateController ? { signal: stateController.signal } : {}),
    });
  } catch {
    if (rule.path === 'state') {
      return buildSetupErrorResponse(
        503,
        'setup.state_unavailable',
        'installation state is unavailable'
      );
    }
    return buildSetupErrorResponse(502, 'proxy.setup_unreachable', 'failed to reach setup endpoint');
  } finally {
    if (stateTimeout !== null) {
      clearTimeout(stateTimeout);
    }
  }

  return forwardSetupResponse(response);
}
