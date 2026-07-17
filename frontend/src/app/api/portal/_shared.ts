import { NextRequest, NextResponse } from 'next/server';
import {
  buildBackendUrl,
  buildErrorResponse,
  buildForwardedRequestHeaders,
  forwardBackendJson,
  getExternalRequestHost,
  getExternalRequestOrigin,
  getExternalRequestProto,
} from '@/app/api/admin/_shared';

const COPIED_REQUEST_HEADERS = [
  'accept-language',
  'authorization',
  'idempotency-key',
] as const;

function buildPortalBackendPath(pathSegments: string[]): string {
  const normalized = pathSegments
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join('/');
  return normalized ? `/portal/v1/${normalized}` : '/portal/v1';
}

export async function proxyPortalBackendPath(
  request: NextRequest,
  backendPath: string,
  options: {
    method?: string;
    unreachableCode: string;
    unreachableMessage: string;
  }
): Promise<NextResponse> {
  const method = (options.method || request.method).toUpperCase();
  const accept = request.headers.get('accept');
  const contentType = request.headers.get('content-type');
  const requestOrigin = getExternalRequestOrigin(request);
  const requestHost = getExternalRequestHost(request);
  const requestProto = getExternalRequestProto(request) || request.nextUrl.protocol.replace(/:$/, '');
  const headers = buildForwardedRequestHeaders(request, {
    Accept: accept || 'application/json',
  });

  headers.Origin = request.headers.get('origin') || requestOrigin;
  headers.Referer = request.headers.get('referer') || `${requestOrigin}/`;
  headers['X-Forwarded-Host'] = requestHost;
  headers['X-Forwarded-Proto'] = requestProto;
  headers['X-Forwarded-Port'] = request.nextUrl.port || '';

  const debugPortalLink = request.headers.get('x-npcink-debug-portal-link');
  if (debugPortalLink) {
    headers['X-Npcink-Debug-Portal-Link'] = debugPortalLink;
  }

  for (const headerName of COPIED_REQUEST_HEADERS) {
    const value = request.headers.get(headerName);
    if (value) {
      headers[headerName] = value;
    }
  }

  let body: string | undefined;
  if (method !== 'GET' && method !== 'HEAD') {
    body = await request.text();
    if (!body) {
      body = undefined;
    }
    if (contentType) {
      headers['Content-Type'] = contentType;
    }
  }

  let response: Response;
  try {
    response = await fetch(buildBackendUrl(backendPath, request.nextUrl.search), {
      method,
      headers,
      body,
      cache: 'no-store',
    });
  } catch {
    return buildErrorResponse(
      502,
      options.unreachableCode,
      options.unreachableMessage
    );
  }

  return forwardBackendJson(response);
}

export async function proxyPortalPathSegments(
  request: NextRequest,
  pathSegments: string[],
  options: {
    method?: string;
    unreachableCode: string;
    unreachableMessage: string;
  }
): Promise<NextResponse> {
  return proxyPortalBackendPath(
    request,
    buildPortalBackendPath(pathSegments),
    options
  );
}
