import { NextRequest, NextResponse } from 'next/server';
import {
  buildBackendUrl,
  buildForwardedRequestHeaders,
  forwardBackendJson,
  getExternalRequestOrigin,
} from '@/app/api/admin/_shared';
import { getAdminBootstrapAdminRef } from '@/lib/env';

const ADMIN_SESSION_COOKIE = 'npcink_admin_session_token';
const ADMIN_SESSION_COOKIE_LEGACY = 'magick_admin_session_token';
const FORWARDED_ADMIN_COOKIE_NAMES = new Set([
  ADMIN_SESSION_COOKIE,
  ADMIN_SESSION_COOKIE_LEGACY,
]);

type ParsedSetCookie = {
  name: string;
  value: string;
  path?: string;
  maxAge?: number;
  expires?: Date;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: 'lax' | 'strict' | 'none';
};

function readSetCookieHeaders(response: Response): string[] {
  const setCookieAccessor = (response.headers as Headers & {
    getSetCookie?: () => string[];
  }).getSetCookie;
  if (typeof setCookieAccessor === 'function') {
    return setCookieAccessor.call(response.headers);
  }

  const singleSetCookie = response.headers.get('set-cookie');
  return singleSetCookie ? [singleSetCookie] : [];
}

function parseSetCookie(header: string): ParsedSetCookie | null {
  const parts = header.split(';').map((part) => part.trim()).filter(Boolean);
  if (parts.length === 0) {
    return null;
  }

  const [nameValue, ...attributes] = parts;
  const separatorIndex = nameValue.indexOf('=');
  if (separatorIndex <= 0) {
    return null;
  }

  const parsed: ParsedSetCookie = {
    name: nameValue.slice(0, separatorIndex).trim(),
    value: nameValue.slice(separatorIndex + 1).trim(),
  };

  for (const attribute of attributes) {
    const [rawKey, ...rawValueParts] = attribute.split('=');
    const key = rawKey.trim().toLowerCase();
    const value = rawValueParts.join('=').trim();

    if (key === 'path') {
      parsed.path = value || '/';
      continue;
    }
    if (key === 'max-age') {
      const maxAge = Number.parseInt(value, 10);
      if (Number.isFinite(maxAge)) {
        parsed.maxAge = maxAge;
      }
      continue;
    }
    if (key === 'expires') {
      const expires = new Date(value);
      if (!Number.isNaN(expires.getTime())) {
        parsed.expires = expires;
      }
      continue;
    }
    if (key === 'httponly') {
      parsed.httpOnly = true;
      continue;
    }
    if (key === 'secure') {
      parsed.secure = true;
      continue;
    }
    if (key === 'samesite') {
      const normalized = value.toLowerCase();
      if (normalized === 'lax' || normalized === 'strict' || normalized === 'none') {
        parsed.sameSite = normalized;
      }
    }
  }

  return parsed;
}

function applyCookieForwarding(response: Response, nextResponse: NextResponse): void {
  for (const header of readSetCookieHeaders(response)) {
    const parsed = parseSetCookie(header);
    if (!parsed || !FORWARDED_ADMIN_COOKIE_NAMES.has(parsed.name)) {
      continue;
    }

    nextResponse.cookies.set({
      name: parsed.name,
      value: parsed.value === '""' ? '' : parsed.value,
      path: parsed.path || '/',
      maxAge: parsed.maxAge,
      expires: parsed.expires,
      httpOnly: parsed.httpOnly,
      secure: parsed.secure,
      sameSite: parsed.sameSite,
    });
  }
}

async function forwardAdminBootstrap(
  request: NextRequest,
  bootstrap: {
    token: string;
    admin_ref: string;
    redirect: string;
  },
  options: {
    wantsLoginRedirect: boolean;
  }
) {
  const payload = {
    token: String(bootstrap.token || ''),
    admin_ref: String(bootstrap.admin_ref || ''),
    redirect: String(bootstrap.redirect || '/admin'),
  };

  const response = await fetch(buildBackendUrl('/admin/auth/bootstrap'), {
    method: 'POST',
    headers: buildForwardedRequestHeaders(request, {
      Accept: 'text/html,application/json',
      'Content-Type': 'application/json',
    }),
    body: JSON.stringify(payload),
    redirect: 'manual',
    cache: 'no-store',
  });

  const location = response.headers.get('location');
  if (!location) {
    if (options.wantsLoginRedirect) {
      const payload = await response.json().catch(() => ({}));
      const errorCode = String(payload?.error_code || 'auth.admin_bootstrap_failed');
      return redirectToLogin(request, errorCode, payload?.message, payload?.data, payload?.meta, bootstrap.redirect);
    }
    return forwardBackendJson(response);
  }

  const nextResponse = new NextResponse(null, { status: response.status });
  nextResponse.headers.set('location', location);
  applyCookieForwarding(response, nextResponse);
  return nextResponse;
}

function sanitizeAdminRedirect(value: string): string {
  const normalized = String(value || '/admin').trim() || '/admin';
  try {
    const parsed = new URL(normalized, 'http://local.invalid');
    if (parsed.origin !== 'http://local.invalid' || !parsed.pathname.startsWith('/admin')) {
      return '/admin';
    }
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return '/admin';
  }
}

function redirectToLogin(
  request: NextRequest,
  errorCode: string,
  message: unknown,
  data: unknown,
  meta: unknown,
  redirect: string
): NextResponse {
  const url = new URL('/admin/login', getExternalRequestOrigin(request));
  url.searchParams.set('error', errorCode);
  const detail = String(message || '').trim();
  if (detail) {
    url.searchParams.set('detail', detail);
  }
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

export async function GET(request: NextRequest) {
  const redirect = String(request.nextUrl.searchParams.get('redirect') || '/admin').trim() || '/admin';
  return NextResponse.redirect(
    new URL(
      `/admin/login?redirect=${encodeURIComponent(redirect)}`,
      getExternalRequestOrigin(request)
    ),
    303
  );
}

export async function POST(request: NextRequest) {
  const contentType = request.headers.get('content-type') || '';
  let token = '';
  let adminRef = '';
  let redirect = '/admin';

  if (contentType.includes('application/json')) {
    const body = await request.json().catch(() => ({}));
    token = String(body?.token || '');
    adminRef = String(body?.admin_ref || '');
    redirect = String(body?.redirect || '/admin');
  } else {
    const formData = await request.formData();
    token = String(formData.get('token') || '');
    adminRef = String(formData.get('admin_ref') || '');
    redirect = String(formData.get('redirect') || '/admin');
  }

  return forwardAdminBootstrap(request, {
    token,
    admin_ref: adminRef,
    redirect,
  }, {
    wantsLoginRedirect: !contentType.includes('application/json'),
  });
}
