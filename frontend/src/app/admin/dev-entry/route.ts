import { NextRequest, NextResponse } from 'next/server';
import { appendForwardHeaders, buildBackendUrl, buildForwardedRequestHeaders } from '@/app/api/admin/_shared';
import {
  getAdminBootstrapAdminRef,
  getInternalAuthToken,
  getPublicBaseUrl,
  isMiniDevHost,
  isMiniDevRequestHost,
} from '@/lib/env';

function isUsableExternalMiniHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return isMiniDevHost(host) && host !== '0.0.0.0';
}

function resolveQueryOrigin(request: NextRequest): string | null {
  const requestedOrigin = request.nextUrl.searchParams.get('origin');
  if (!requestedOrigin) {
    return null;
  }

  try {
    const parsedOrigin = new URL(requestedOrigin);
    if (isUsableExternalMiniHost(parsedOrigin.hostname)) {
      return parsedOrigin.origin;
    }
  } catch {}

  return null;
}

function resolveForwardedHostOrigin(request: NextRequest): string | null {
  const forwardedProto =
    request.headers.get('x-forwarded-proto') ||
    request.nextUrl.protocol.replace(/:$/, '') ||
    'http';

  const candidateHosts = [
    request.headers.get('x-forwarded-host'),
    request.headers.get('host'),
  ];

  for (const candidate of candidateHosts) {
    const value = String(candidate || '').trim().toLowerCase();
    if (!value || !isMiniDevRequestHost(value)) {
      continue;
    }
    const firstHost = value.split(',')[0]?.trim() || '';
    const hostname = firstHost.split(':')[0]?.trim() || '';
    if (!isUsableExternalMiniHost(hostname)) {
      continue;
    }
    return `${forwardedProto}://${firstHost}`;
  }

  return null;
}

function resolveExternalOrigin(request: NextRequest): string {
  const publicBaseUrl = getPublicBaseUrl();
  const queryOrigin = resolveQueryOrigin(request);
  if (queryOrigin) {
    return queryOrigin;
  }
  const originHeader = request.headers.get('origin');
  if (originHeader) {
    try {
      const parsedOrigin = new URL(originHeader);
      if (isUsableExternalMiniHost(parsedOrigin.hostname)) {
        return parsedOrigin.origin;
      }
    } catch {}
  }
  const refererHeader = request.headers.get('referer');
  if (refererHeader) {
    try {
      const parsedReferer = new URL(refererHeader);
      if (isUsableExternalMiniHost(parsedReferer.hostname)) {
        return parsedReferer.origin;
      }
    } catch {}
  }

  const forwardedOrigin = resolveForwardedHostOrigin(request);
  if (forwardedOrigin) {
    return forwardedOrigin;
  }

  try {
    if (isUsableExternalMiniHost(request.nextUrl.hostname)) {
      return request.nextUrl.origin;
    }
  } catch {}

  try {
    const parsedPublicBaseUrl = new URL(publicBaseUrl);
    if (isUsableExternalMiniHost(parsedPublicBaseUrl.hostname)) {
      return parsedPublicBaseUrl.origin;
    }
  } catch {}

  if (publicBaseUrl) {
    return publicBaseUrl;
  }

  return publicBaseUrl;
}

function buildDeniedRedirect(request: NextRequest, errorCode: string): NextResponse {
  const resolvedOrigin = resolveExternalOrigin(request);
  const response = NextResponse.redirect(
    new URL(`/admin/login?error=${encodeURIComponent(errorCode)}`, resolvedOrigin),
    303
  );
  response.headers.set('Cache-Control', 'no-store');
  return response;
}

function isMiniDevEntryEnabledForRequest(request: NextRequest): boolean {
  const hostCandidates = [
    request.headers.get('x-forwarded-host'),
    request.headers.get('host'),
    request.nextUrl.host,
  ];

  for (const candidate of hostCandidates) {
    if (isMiniDevRequestHost(candidate)) {
      return true;
    }
  }

  try {
    return isMiniDevHost(new URL(getPublicBaseUrl()).hostname);
  } catch {
    return false;
  }
}

function resolveRedirectPath(request: NextRequest): string {
  const requestedRedirect = String(request.nextUrl.searchParams.get('redirect') || '').trim();
  if (!requestedRedirect.startsWith('/admin')) {
    return '/admin';
  }
  return requestedRedirect;
}

export async function GET(request: NextRequest) {
  if (!isMiniDevEntryEnabledForRequest(request)) {
    return buildDeniedRedirect(request, 'auth.dev_entry_disabled');
  }

  const resolvedOrigin = resolveExternalOrigin(request);
  const resolvedOriginUrl = new URL(resolvedOrigin);
  let response: Response;
  try {
    response = await fetch(buildBackendUrl('/admin/auth/bootstrap'), {
      method: 'POST',
      headers: buildForwardedRequestHeaders(request, {
        Accept: 'text/html,application/json',
        'Content-Type': 'application/json',
        Host: resolvedOriginUrl.host,
        'X-Forwarded-Host': resolvedOriginUrl.host,
        'X-Forwarded-Proto': resolvedOriginUrl.protocol.replace(/:$/, ''),
        Origin: resolvedOrigin,
        Referer: `${resolvedOrigin}/`,
      }),
      body: JSON.stringify({
        token: getInternalAuthToken(),
        admin_ref: getAdminBootstrapAdminRef(),
        redirect: resolveRedirectPath(request),
      }),
      redirect: 'manual',
      cache: 'no-store',
    });
  } catch {
    return buildDeniedRedirect(request, 'auth.dev_entry_unreachable');
  }

  const redirectUrl = new URL(resolveRedirectPath(request), resolvedOrigin);
  const nextResponse = NextResponse.redirect(redirectUrl, 303);
  appendForwardHeaders(response, nextResponse);
  nextResponse.headers.set('location', redirectUrl.toString());
  nextResponse.headers.set('Cache-Control', 'no-store');
  return nextResponse;
}
