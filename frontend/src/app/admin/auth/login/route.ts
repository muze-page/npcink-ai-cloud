import { NextRequest, NextResponse } from 'next/server';
import {
  buildBackendUrl,
  buildForwardedRequestHeaders,
  forwardBackendJson,
} from '@/app/api/admin/_shared';
import { getPublicBaseUrl } from '@/lib/env';

const ADMIN_SESSION_COOKIE = 'npcink_admin_session_token';
const INVALID_UPSTREAM_ERROR_CODE = 'proxy.admin_login_invalid_response';

function resolveTrustedAdminOrigin(): string {
  return new URL(getPublicBaseUrl()).origin;
}

function buildAdminLoginHeaders(
  request: NextRequest,
  baseHeaders: Record<string, string>
): Record<string, string> {
  const trustedOrigin = new URL(resolveTrustedAdminOrigin());
  const headers = buildForwardedRequestHeaders(request, baseHeaders);
  headers.Host = trustedOrigin.host;
  headers['X-Forwarded-Host'] = trustedOrigin.host;
  headers['X-Forwarded-Proto'] = trustedOrigin.protocol.replace(/:$/, '');
  headers['X-Forwarded-Port'] = trustedOrigin.port;
  return headers;
}

function readSetCookieHeaders(response: Response): string[] {
  const accessor = (response.headers as Headers & { getSetCookie?: () => string[] }).getSetCookie;
  if (typeof accessor === 'function') {
    return accessor.call(response.headers);
  }
  const value = response.headers.get('set-cookie');
  return value ? [value] : [];
}

function copyAdminSessionCookie(source: Response, target: NextResponse): void {
  for (const value of readSetCookieHeaders(source)) {
    const cookieName = value.split(';', 1)[0]?.split('=', 1)[0]?.trim();
    if (cookieName === ADMIN_SESSION_COOKIE) {
      target.headers.append('set-cookie', value);
    }
  }
}

function sanitizeAdminRedirect(value: string): string {
  const normalized = String(value || '/admin').trim() || '/admin';
  try {
    const parsed = new URL(normalized, 'http://local.invalid');
    if (
      parsed.origin !== 'http://local.invalid' ||
      (parsed.pathname !== '/admin' && !parsed.pathname.startsWith('/admin/'))
    ) {
      return '/admin';
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return '/admin';
  }
}

function redirectToLogin(
  request: NextRequest,
  errorCode: string,
  data: unknown,
  meta: unknown,
  redirect: string
): NextResponse {
  const url = new URL('/admin/login', resolveTrustedAdminOrigin());
  url.searchParams.set('error', errorCode);
  const payloadData = data && typeof data === 'object' ? data : {};
  const payloadMeta = meta && typeof meta === 'object' ? meta : {};
  const traceId = String(
    (payloadData as { trace_id?: unknown }).trace_id ||
      (payloadMeta as { trace_id?: unknown }).trace_id ||
      ''
  ).trim();
  if (traceId) {
    url.searchParams.set('trace_id', traceId);
  }
  url.searchParams.set('redirect', sanitizeAdminRedirect(redirect));
  const response = NextResponse.redirect(url, 303);
  response.headers.set('Cache-Control', 'no-store');
  return response;
}

function invalidUpstreamResponse(
  request: NextRequest,
  wantsJson: boolean,
  redirect: string
): NextResponse {
  if (!wantsJson) {
    return redirectToLogin(request, INVALID_UPSTREAM_ERROR_CODE, {}, {}, redirect);
  }
  const response = NextResponse.json(
    {
      status: 'error',
      error_code: INVALID_UPSTREAM_ERROR_CODE,
      message: 'admin login endpoint returned an invalid response',
      data: {},
      meta: { trace_id: '', revision: 'admin-login-bff-v1' },
    },
    { status: 502 }
  );
  response.headers.set('Cache-Control', 'no-store');
  return response;
}

export async function GET(request: NextRequest) {
  const redirect = sanitizeAdminRedirect(request.nextUrl.searchParams.get('redirect') || '/admin');
  const response = NextResponse.redirect(
    new URL(`/admin/login?redirect=${encodeURIComponent(redirect)}`, resolveTrustedAdminOrigin()),
    303
  );
  response.headers.set('Cache-Control', 'no-store');
  return response;
}

export async function POST(request: NextRequest) {
  const contentType = request.headers.get('content-type') || '';
  const wantsJson = contentType.includes('application/json');
  let adminKey = '';
  let redirect = '/admin';

  if (wantsJson) {
    const body = await request.json().catch(() => ({}));
    adminKey = String(body?.admin_key || '');
    redirect = sanitizeAdminRedirect(String(body?.redirect || '/admin'));
  } else {
    const formData = await request.formData();
    adminKey = String(formData.get('admin_key') || '');
    redirect = sanitizeAdminRedirect(String(formData.get('redirect') || '/admin'));
  }

  const payload = { admin_key: adminKey, redirect };

  let backendResponse: Response;
  try {
    backendResponse = await fetch(buildBackendUrl('/admin/auth/login'), {
      method: 'POST',
      headers: buildAdminLoginHeaders(request, {
        Accept: wantsJson ? 'application/json' : 'text/html,application/json',
        'Content-Type': 'application/json',
      }),
      body: JSON.stringify(payload),
      redirect: 'manual',
      cache: 'no-store',
    });
  } catch {
    if (!wantsJson) {
      return redirectToLogin(request, 'auth.admin_login_unreachable', {}, {}, redirect);
    }
    return NextResponse.json(
      {
        status: 'error',
        error_code: 'auth.admin_login_unreachable',
        message: 'failed to reach admin login endpoint',
        data: {},
        meta: { trace_id: '', revision: 'admin-login-bff-v1' },
      },
      { status: 502 }
    );
  }

  const location = backendResponse.headers.get('location');
  if (location && backendResponse.status >= 300 && backendResponse.status < 400) {
    let redirectLocation = redirect;
    try {
      const parsed = new URL(location, resolveTrustedAdminOrigin());
      redirectLocation = sanitizeAdminRedirect(`${parsed.pathname}${parsed.search}${parsed.hash}`);
    } catch {}
    const response = NextResponse.redirect(
      new URL(redirectLocation, resolveTrustedAdminOrigin()),
      303
    );
    copyAdminSessionCookie(backendResponse, response);
    response.headers.set('Cache-Control', 'no-store');
    return response;
  }

  const backendContentType = backendResponse.headers.get('content-type') || '';
  const backendBody = backendContentType.includes('application/json')
    ? await backendResponse
        .clone()
        .json()
        .then((value: unknown) =>
          value && typeof value === 'object' && !Array.isArray(value)
            ? (value as Record<string, unknown>)
            : null
        )
        .catch(() => null)
    : null;
  if (!backendBody) {
    return invalidUpstreamResponse(request, wantsJson, redirect);
  }

  if (!wantsJson) {
    if (backendResponse.ok) {
      const response = NextResponse.redirect(
        new URL(redirect, resolveTrustedAdminOrigin()),
        303
      );
      copyAdminSessionCookie(backendResponse, response);
      response.headers.set('Cache-Control', 'no-store');
      return response;
    }
    return redirectToLogin(
      request,
      String(backendBody.error_code || INVALID_UPSTREAM_ERROR_CODE),
      backendBody.data,
      backendBody.meta,
      redirect
    );
  }

  const response = await forwardBackendJson(backendResponse);
  response.headers.set('Cache-Control', 'no-store');
  return response;
}
