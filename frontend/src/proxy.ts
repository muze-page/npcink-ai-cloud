import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { getApiBaseUrl } from '@/lib/env';
import {
  isInstallationState,
  parseSetupStateEnvelope,
  type InstallationState,
} from '@/lib/setup';

const ADMIN_SESSION_COOKIE = 'npcink_admin_session_token';
const PORTAL_SESSION_COOKIE = 'npcink_portal_session_token';
const SETUP_STATE_TIMEOUT_MS = 5000;

type InstallationGateResult =
  | { ok: true; installationState: InstallationState }
  | { ok: false };

const SETUP_API_RULES = new Set([
  'GET /api/setup/state',
  'POST /api/setup/session',
  'POST /api/setup/database/test',
  'POST /api/setup/install',
]);

// Completion is irreversible by contract. Cache only that terminal state so
// steady-state frontend requests do not add a setup-state network round trip.
let completedInstallationObserved = false;

function resolveDevelopmentInstallationStateOverride(): InstallationState | null {
  const runtimeEnvironment = String(process.env.NEXT_PUBLIC_ENV || '').trim().toLowerCase();
  if (runtimeEnvironment !== 'development' && runtimeEnvironment !== 'test') {
    return null;
  }
  const value = String(process.env.NPCINK_CLOUD_SETUP_STATE_OVERRIDE || '').trim();
  return isInstallationState(value) ? value : null;
}

async function readInstallationState(): Promise<InstallationGateResult> {
  if (completedInstallationObserved) {
    return { ok: true, installationState: 'complete' };
  }
  const override = resolveDevelopmentInstallationStateOverride();
  if (override) {
    completedInstallationObserved = override === 'complete';
    return { ok: true, installationState: override };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), SETUP_STATE_TIMEOUT_MS);
  try {
    const response = await fetch(`${getApiBaseUrl().replace(/\/$/, '')}/setup/v1/state`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!response.ok) {
      return completedInstallationObserved
        ? { ok: true, installationState: 'complete' }
        : { ok: false };
    }
    const state = parseSetupStateEnvelope(await response.json());
    if (state?.installation_state === 'complete') {
      completedInstallationObserved = true;
    }
    if (completedInstallationObserved) {
      return { ok: true, installationState: 'complete' };
    }
    return state
      ? { ok: true, installationState: state.installation_state }
      : { ok: false };
  } catch {
    return completedInstallationObserved
      ? { ok: true, installationState: 'complete' }
      : { ok: false };
  } finally {
    clearTimeout(timeout);
  }
}

function buildSetupGateJsonResponse(
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
      meta: { trace_id: '', revision: 'setup-gate-v1' },
    },
    { status }
  );
  response.headers.set('Cache-Control', 'no-store');
  return withSecurityHeaders(response);
}

function isJsonSurface(request: NextRequest): boolean {
  const { pathname } = request.nextUrl;
  const accept = request.headers.get('accept') || '';
  return (
    pathname.startsWith('/api/') ||
    pathname.startsWith('/admin/auth/') ||
    pathname === '/admin/session' ||
    pathname.startsWith('/portal/api/') ||
    request.method !== 'GET' ||
    accept.includes('application/json')
  );
}

function buildInstallationUnavailableResponse(request: NextRequest): NextResponse {
  if (isJsonSurface(request)) {
    return buildSetupGateJsonResponse(
      503,
      'setup.state_unavailable',
      'installation state is unavailable'
    );
  }
  const response = new NextResponse('Cloud installation state is unavailable.', {
    status: 503,
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
  response.headers.set('Cache-Control', 'no-store');
  response.headers.set('Retry-After', '5');
  return withSecurityHeaders(response);
}

function buildInstallationRequiredResponse(request: NextRequest): NextResponse {
  if (isJsonSurface(request)) {
    return buildSetupGateJsonResponse(
      503,
      'setup.installation_required',
      'Cloud installation is required'
    );
  }
  const setupUrl = new URL('/setup', request.url);
  return withSecurityHeaders(NextResponse.redirect(setupUrl, 307));
}

function buildSetupClosedResponse(request: NextRequest): NextResponse {
  if (isJsonSurface(request)) {
    return buildSetupGateJsonResponse(404, 'setup.already_complete', 'setup is already complete');
  }
  const response = new NextResponse('Not Found', {
    status: 404,
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
  response.headers.set('Cache-Control', 'no-store');
  return withSecurityHeaders(response);
}

function buildContentSecurityPolicy(): string {
  const isDevelopment = process.env.NODE_ENV !== 'production';
  const scriptSrc = ["'self'", "'unsafe-inline'"];
  if (isDevelopment) {
    scriptSrc.push("'unsafe-eval'");
  }

  return [
    "default-src 'self'",
    `script-src ${scriptSrc.join(' ')}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    "connect-src 'self' https:",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
  ].join('; ');
}

function withSecurityHeaders(response: NextResponse): NextResponse {
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set('X-XSS-Protection', '1; mode=block');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.headers.set('Content-Security-Policy', buildContentSecurityPolicy());

  return response;
}

function withAdminIndexingDisabled(response: NextResponse): NextResponse {
  response.headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive');
  return response;
}

function buildAdminLoginRedirect(request: NextRequest): NextResponse {
  const loginUrl = new URL('/admin/login', request.url);
  const redirectTo = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  loginUrl.searchParams.set('redirect', redirectTo);
  return NextResponse.redirect(loginUrl);
}

/**
 * Middleware for Cloud Portal
 * 
 * Handles:
 * - Authentication redirects for portal routes
 * - Security headers
 * - Request logging
 */
export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const response = withSecurityHeaders(NextResponse.next());
  const setupRouteKey = `${request.method.toUpperCase()} ${pathname}`;
  const isSetupStateRoute = setupRouteKey === 'GET /api/setup/state';
  const isSetupApiRoute = pathname === '/api/setup' || pathname.startsWith('/api/setup/');
  const isSetupPage = pathname === '/setup' || pathname === '/setup/';
  const isFrontendHealthRoute =
    pathname === '/api/health' && (request.method === 'GET' || request.method === 'HEAD');
  const isHealthRoute =
    pathname === '/health/live' || pathname === '/health/ready' || isFrontendHealthRoute;

  // The state projection itself must remain reachable so the browser can show
  // an explicit backend failure instead of guessing that a deployment is new.
  if (!isSetupStateRoute && !isHealthRoute) {
    const installation = await readInstallationState();
    if (!installation.ok) {
      return buildInstallationUnavailableResponse(request);
    }

    if (installation.installationState === 'complete') {
      if (isSetupPage || isSetupApiRoute) {
        return buildSetupClosedResponse(request);
      }
    } else {
      if (isSetupPage) {
        return response;
      }
      if (isSetupApiRoute) {
        return SETUP_API_RULES.has(setupRouteKey)
          ? response
          : buildSetupGateJsonResponse(
              404,
              'proxy.setup_route_not_allowed',
              'setup route is not allowed'
            );
      }
      return buildInstallationRequiredResponse(request);
    }
  }

  const hasAdminSession = Boolean(request.cookies.get(ADMIN_SESSION_COOKIE)?.value);
  const isAdminLogin = pathname === '/admin/login';
  const isAdminDevEntry = pathname === '/admin/dev-entry';
  const isAdminAuthRoute = pathname.startsWith('/admin/auth/');
  const isAdminSessionRoute = pathname === '/admin/session';
  const isAdminLogoutRoute = pathname === '/admin/logout';
  const isAdminPublicRoute =
    isAdminLogin || isAdminDevEntry || isAdminAuthRoute || isAdminSessionRoute || isAdminLogoutRoute;
  const isAdminRoute = pathname === '/admin' || pathname.startsWith('/admin/');
  const isAdminApiRoute = pathname === '/api/admin' || pathname.startsWith('/api/admin/');

  if (isAdminApiRoute && !hasAdminSession) {
    return withAdminIndexingDisabled(withSecurityHeaders(
      NextResponse.json(
        {
          status: 'error',
          error_code: 'auth.admin_session_required',
          message: 'admin session is required',
          revision: 'm6',
        },
        { status: 401 }
      )
    ));
  }

  if (isAdminRoute && !isAdminPublicRoute && !hasAdminSession) {
    return withAdminIndexingDisabled(withSecurityHeaders(buildAdminLoginRedirect(request)));
  }

  if (isAdminRoute || isAdminApiRoute) {
    return withAdminIndexingDisabled(response);
  }

  // Skip auth check for non-portal routes
  if (!pathname.startsWith('/portal')) {
    return response;
  }

  // Skip auth check for public portal entry pages.
  if (pathname === '/portal/login' || pathname === '/portal/register' || pathname === '/portal/dev-entry') {
    return response;
  }

  // Skip auth check for API routes
  if (pathname.startsWith('/portal/api')) {
    return response;
  }

  // Portal page gating is a UX convenience only. Keep it aligned with the
  // current backend-issued session cookie.
  const hasSessionToken = Boolean(request.cookies.get(PORTAL_SESSION_COOKIE)?.value);

  // Redirect to login if no auth
  if (!hasSessionToken) {
    const loginUrl = new URL('/portal/login', request.url);
    loginUrl.searchParams.set('redirect', `${pathname}${request.nextUrl.search}`);
    return withSecurityHeaders(NextResponse.redirect(loginUrl));
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    '/((?!_next/static(?:/|$)|_next/image(?:/|$)|favicon\\.ico$).*)',
  ],
};
