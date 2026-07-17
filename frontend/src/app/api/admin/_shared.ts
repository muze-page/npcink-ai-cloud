import { NextRequest, NextResponse } from 'next/server';
import { getApiBaseUrl } from '@/lib/env';

export type AdminSessionPayload = {
  principal_id: string;
  identity_type?: string;
  role: string;
  capabilities?: Record<string, boolean>;
  auth_mode: string;
  issued_at?: string;
  expires_at?: string;
  transport?: string;
  revocable?: boolean;
};

export type AdminCapability =
  | 'can_manage_accounts'
  | 'can_manage_catalog'
  | 'can_manage_billing'
  | 'can_review_diagnostics';

const PLATFORM_ADMIN_IDENTITY_TYPE = 'platform_admin';
const PLATFORM_ADMIN_ROLE = 'platform_admin';

export function buildBackendUrl(pathname: string, search = ''): string {
  const baseUrl = getApiBaseUrl().replace(/\/$/, '');
  return `${baseUrl}${pathname}${search}`;
}

function firstHeaderValue(value: string | null | undefined): string {
  return String(value || '').split(',', 1)[0]?.trim() || '';
}

function firstUrlHostValue(value: string | null | undefined): string {
  const raw = String(value || '').trim();
  if (!raw) {
    return '';
  }
  try {
    return new URL(raw).host;
  } catch {
    return '';
  }
}

function firstUrlProtoValue(value: string | null | undefined): string {
  const raw = String(value || '').trim();
  if (!raw) {
    return '';
  }
  try {
    return new URL(raw).protocol.replace(/:$/, '');
  } catch {
    return '';
  }
}

export function getExternalRequestHost(request: NextRequest): string {
  return (
    firstUrlHostValue(request.headers.get('origin')) ||
    firstUrlHostValue(request.headers.get('referer')) ||
    firstHeaderValue(request.headers.get('x-forwarded-host')) ||
    firstHeaderValue(request.headers.get('host')) ||
    firstHeaderValue(request.nextUrl.host)
  );
}

export function getExternalRequestProto(request: NextRequest): string | undefined {
  return (
    firstUrlProtoValue(request.headers.get('origin')) ||
    firstUrlProtoValue(request.headers.get('referer')) ||
    firstHeaderValue(request.headers.get('x-forwarded-proto')) ||
    request.nextUrl.protocol.replace(/:$/, '') ||
    undefined
  );
}

export function getExternalRequestOrigin(request: NextRequest): string {
  const host = getExternalRequestHost(request);
  const proto = getExternalRequestProto(request) || 'http';
  if (host) {
    return `${proto}://${host}`;
  }
  return request.nextUrl.origin;
}

export function buildErrorResponse(
  status: number,
  errorCode: string,
  message: string
): NextResponse {
  return NextResponse.json(
    {
      status: 'error',
      error_code: errorCode,
      message,
      data: {},
      meta: {
        trace_id: '',
        revision: 'm6',
      },
    },
    { status }
  );
}

export function appendForwardHeaders(source: Response, target: NextResponse): void {
  const setCookieAccessor = (source.headers as Headers & {
    getSetCookie?: () => string[];
  }).getSetCookie;
  const setCookies =
    typeof setCookieAccessor === 'function'
      ? setCookieAccessor.call(source.headers)
      : [];

  if (setCookies.length > 0) {
    for (const value of setCookies) {
      target.headers.append('set-cookie', value);
    }
  } else {
    const singleSetCookie = source.headers.get('set-cookie');
    if (singleSetCookie) {
      target.headers.append('set-cookie', singleSetCookie);
    }
  }

  const location = source.headers.get('location');
  if (location) {
    target.headers.set('location', location);
  }
}

export function buildForwardedRequestHeaders(
  request: NextRequest,
  baseHeaders: Record<string, string> = {}
): Record<string, string> {
  const headers: Record<string, string> = { ...baseHeaders };
  const resolvedOrigin = getExternalRequestOrigin(request);
  let host = getExternalRequestHost(request);
  let forwardedProto = getExternalRequestProto(request);
  let forwardedPort = firstHeaderValue(request.headers.get('x-forwarded-port')) || request.nextUrl.port;
  try {
    const parsedOrigin = new URL(resolvedOrigin);
    host = parsedOrigin.host || host;
    forwardedProto = parsedOrigin.protocol.replace(/:$/, '') || forwardedProto;
    forwardedPort = parsedOrigin.port || forwardedPort;
  } catch {}
  const forwardedHost = host;
  const realIp = request.headers.get('x-real-ip');
  const forwardedFor = request.headers.get('x-forwarded-for');
  const cookie = request.headers.get('cookie');
  const origin = request.headers.get('origin');
  const referer = request.headers.get('referer');

  if (host) {
    headers.Host = host;
  }
  if (forwardedHost) {
    headers['X-Forwarded-Host'] = forwardedHost;
  } else if (host) {
    headers['X-Forwarded-Host'] = host;
  }
  if (forwardedProto) {
    headers['X-Forwarded-Proto'] = forwardedProto;
  }
  if (forwardedPort) {
    headers['X-Forwarded-Port'] = forwardedPort;
  }
  if (realIp) {
    headers['X-Real-IP'] = realIp;
  }
  if (forwardedFor) {
    headers['X-Forwarded-For'] = forwardedFor;
  }
  if (cookie) {
    headers.Cookie = cookie;
  }
  if (origin) {
    headers.Origin = origin;
  }
  if (referer) {
    headers.Referer = referer;
  }

  return headers;
}

export async function forwardBackendJson(response: Response): Promise<NextResponse> {
  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    const payload = await response.json();
    const nextResponse = NextResponse.json(payload, { status: response.status });
    appendForwardHeaders(response, nextResponse);
    return nextResponse;
  }

  const text = await response.text();
  const nextResponse = new NextResponse(text, {
    status: response.status,
    headers: {
      'content-type': contentType || 'text/plain; charset=utf-8',
    },
  });
  appendForwardHeaders(response, nextResponse);
  return nextResponse;
}

function parseAdminSessionPayload(payload: unknown): AdminSessionPayload | null {
  const data =
    payload &&
    typeof payload === 'object' &&
    'data' in payload &&
    payload.data &&
    typeof payload.data === 'object'
      ? (payload.data as Record<string, unknown>)
      : null;

  const principalId = String(data?.principal_id || '').trim();
  const role = String(data?.role || '').trim();
  const authMode = String(data?.auth_mode || '').trim();
  if (!principalId || !role || !authMode) {
    return null;
  }

  return {
    principal_id: principalId,
    identity_type: String(data?.identity_type || ''),
    role,
    capabilities:
      data?.capabilities && typeof data.capabilities === 'object'
        ? Object.fromEntries(
            Object.entries(data.capabilities as Record<string, unknown>).map(([key, value]) => [
              key,
              value === true,
            ])
          )
        : {},
    auth_mode: authMode,
    issued_at: String(data?.issued_at || ''),
    expires_at: String(data?.expires_at || ''),
    transport: String(data?.transport || ''),
    revocable: Boolean(data?.revocable),
  };
}

export async function requireAdminSessionData(
  request: NextRequest
): Promise<NextResponse | { session: AdminSessionPayload; response: Response }> {
  const cookieHeader = request.headers.get('cookie') || '';
  let response: Response;

  try {
    response = await fetch(buildBackendUrl('/admin/session'), {
      headers: buildForwardedRequestHeaders(request, {
        Accept: 'application/json',
        ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      }),
      cache: 'no-store',
    });
  } catch {
    return buildErrorResponse(
      502,
      'proxy.admin_session_unreachable',
      'failed to verify admin session'
    );
  }

  if (!response.ok) {
    return forwardBackendJson(response);
  }

  const payload = await response.json().catch(() => ({}));
  const session = parseAdminSessionPayload(payload);
  if (!session) {
    return buildErrorResponse(502, 'proxy.admin_session_invalid', 'invalid admin session payload');
  }
  if (
    session.identity_type !== PLATFORM_ADMIN_IDENTITY_TYPE ||
    session.role !== PLATFORM_ADMIN_ROLE
  ) {
    return buildErrorResponse(
      403,
      'proxy.admin_session_forbidden',
      'platform administrator session required'
    );
  }

  return { session, response };
}

export function requireAdminCapability(
  session: AdminSessionPayload,
  capability: AdminCapability
): NextResponse | null {
  if (session.capabilities?.[capability] === true) {
    return null;
  }
  return buildErrorResponse(
    403,
    'proxy.admin_capability_required',
    `admin capability required: ${capability}`
  );
}
