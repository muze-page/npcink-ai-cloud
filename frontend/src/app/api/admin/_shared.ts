import { NextRequest, NextResponse } from 'next/server';
import { getApiBaseUrl, getInternalAuthToken } from '@/lib/env';

export type AdminSessionPayload = {
  principal_id: string;
  platform_admin_ref: string;
  identity_type?: string;
  role: string;
  capabilities?: Record<string, boolean>;
  auth_mode: string;
  issued_at?: string;
  expires_at?: string;
  transport?: string;
  revocable?: boolean;
};

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
      revision: 'm6',
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

export async function requireAdminSession(request: NextRequest): Promise<NextResponse | null> {
  const sessionResult = await requireAdminSessionData(request);
  return sessionResult instanceof NextResponse ? sessionResult : null;
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

  const principalId = String(data?.principal_id || data?.platform_admin_ref || '').trim();
  const platformAdminRef = String(data?.platform_admin_ref || principalId).trim();
  const role = String(data?.role || '').trim();
  const authMode = String(data?.auth_mode || '').trim();
  if (!principalId || !platformAdminRef || !role || !authMode) {
    return null;
  }

  return {
    principal_id: principalId,
    platform_admin_ref: platformAdminRef,
    identity_type: String(data?.identity_type || ''),
    role,
    capabilities:
      data?.capabilities && typeof data.capabilities === 'object'
        ? Object.fromEntries(
            Object.entries(data.capabilities as Record<string, unknown>).map(([key, value]) => [
              key,
              Boolean(value),
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
  } catch (error) {
    return buildErrorResponse(502, 'proxy.admin_session_unreachable', error instanceof Error ? error.message : 'failed to verify admin session');
  }

  if (!response.ok) {
    return forwardBackendJson(response);
  }

  const payload = await response.json().catch(() => ({}));
  const session = parseAdminSessionPayload(payload);
  if (!session) {
    return buildErrorResponse(502, 'proxy.admin_session_invalid', 'invalid admin session payload');
  }

  return { session, response };
}

export async function proxyAdminServiceGet(
  request: NextRequest,
  servicePath: string
): Promise<NextResponse> {
  const sessionResult = await requireAdminSessionData(request);
  if (sessionResult instanceof NextResponse) {
    return sessionResult;
  }
  const { response: sessionResponse } = sessionResult;

  let response: Response;

  try {
    response = await fetch(buildBackendUrl(servicePath, request.nextUrl.search), {
      headers: {
        Accept: 'application/json',
        'X-Npcink-Internal-Token': getInternalAuthToken(),
      },
      cache: 'no-store',
    });
  } catch (error) {
    return buildErrorResponse(502, 'proxy.admin_service_unreachable', error instanceof Error ? error.message : 'failed to reach admin service');
  }

  const nextResponse = await forwardBackendJson(response);
  appendForwardHeaders(sessionResponse, nextResponse);
  return nextResponse;
}

export async function proxyAdminServiceJsonPost(
  request: NextRequest,
  servicePath: string
): Promise<NextResponse> {
  const sessionResult = await requireAdminSessionData(request);
  if (sessionResult instanceof NextResponse) {
    return sessionResult;
  }
  const { response: sessionResponse } = sessionResult;

  let payload: unknown = {};
  try {
    payload = await request.json();
  } catch {
    payload = {};
  }

  let response: Response;
  try {
    response = await fetch(buildBackendUrl(servicePath), {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-Npcink-Internal-Token': getInternalAuthToken(),
        'Idempotency-Key': request.headers.get('idempotency-key') || crypto.randomUUID(),
      },
      body: JSON.stringify(payload),
      cache: 'no-store',
    });
  } catch (error) {
    return buildErrorResponse(502, 'proxy.admin_service_write_unreachable', error instanceof Error ? error.message : 'failed to reach admin service');
  }

  const nextResponse = await forwardBackendJson(response);
  appendForwardHeaders(sessionResponse, nextResponse);
  return nextResponse;
}

export async function proxyAdminJsonPost(
  request: NextRequest,
  adminPath: string
): Promise<NextResponse> {
  let payload: unknown = {};

  try {
    payload = await request.json();
  } catch {
    payload = {};
  }

  let response: Response;

  try {
    response = await fetch(buildBackendUrl(adminPath), {
      method: 'POST',
      headers: buildForwardedRequestHeaders(request, {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify(payload),
      cache: 'no-store',
    });
  } catch (error) {
    return buildErrorResponse(502, 'proxy.admin_write_unreachable', error instanceof Error ? error.message : 'failed to reach admin write endpoint');
  }

  return forwardBackendJson(response);
}
