import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const ADMIN_SESSION_COOKIE = 'npcink_admin_session_token';
const PORTAL_SESSION_COOKIE = 'npcink_portal_session_token';

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
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const response = withSecurityHeaders(NextResponse.next());
  const hasAdminSession = Boolean(request.cookies.get(ADMIN_SESSION_COOKIE)?.value);
  const isAdminLogin = pathname === '/admin/login';
  const isAdminDevEntry = pathname === '/admin/dev-entry';
  const isAdminAuthRoute = pathname === '/admin/auth/bootstrap' || pathname.startsWith('/admin/auth/');
  const isAdminSessionRoute = pathname === '/admin/session';
  const isAdminLogoutRoute = pathname === '/admin/logout';
  const isAdminPublicRoute =
    isAdminLogin || isAdminDevEntry || isAdminAuthRoute || isAdminSessionRoute || isAdminLogoutRoute;
  const isAdminRoute = pathname === '/admin' || pathname.startsWith('/admin/');
  const isAdminApiRoute = pathname === '/api/admin' || pathname.startsWith('/api/admin/');

  if (isAdminApiRoute && !hasAdminSession) {
    return withSecurityHeaders(
      NextResponse.json(
        {
          status: 'error',
          error_code: 'auth.admin_session_required',
          message: 'admin session is required',
          revision: 'm6',
        },
        { status: 401 }
      )
    );
  }

  if (isAdminRoute && !isAdminPublicRoute && !hasAdminSession) {
    return withSecurityHeaders(buildAdminLoginRedirect(request));
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
     * - public files (public folder)
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
