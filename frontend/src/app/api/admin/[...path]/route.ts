import { NextRequest, NextResponse } from 'next/server';
import {
  buildBackendUrl,
  buildErrorResponse,
  buildForwardedRequestHeaders,
  forwardBackendJson,
  getExternalRequestOrigin,
  getExternalRequestHost,
  getExternalRequestProto,
  requireAdminSessionData,
} from '../_shared';
import { getInternalAuthToken } from '@/lib/env';

/**
 * Admin API catch-all proxy.
 *
 * Replaces 43 individual route.ts files with a single catch-all handler.
 * Maps /api/admin/* → /internal/service/admin/* for reads.
 * Writes stay on the service router and only add the admin namespace for
 * backend routes that actually declare it.
 */

const COPIED_REQUEST_HEADERS = [
  'accept-language',
  'idempotency-key',
  'x-npcink-debug-portal-link',
] as const;

function buildAdminBackendPath(pathSegments: string[], method: string): string {
  const normalized = pathSegments
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join('/');

  const upperMethod = method.toUpperCase();

  // GET routes always go through /internal/service/admin/
  if (upperMethod === 'GET') {
    return normalized ? `/internal/service/admin/${normalized}` : '/internal/service/admin';
  }

  // Account creation is a service write, not an admin-prefixed write.
  if (upperMethod === 'POST' && normalized === 'accounts') {
    return '/internal/service/accounts';
  }

  if (/^accounts\/[^/]+\/(?:suspend|restore)$/.test(normalized)) {
    return `/internal/service/admin/${normalized}`;
  }
  if (/^accounts\/[^/]+\/subscription(?:\/(?:suspend|cancel))?$/.test(normalized)) {
    return `/internal/service/admin/${normalized}`;
  }
  if (/^subscriptions\/[^/]+\/billing-snapshots\/rebuild$/.test(normalized)) {
    return `/internal/service/admin/${normalized}`;
  }
  if (/^subscriptions\/[^/]+\/topup$/.test(normalized)) {
    return `/internal/service/${normalized}`;
  }
  if (
    upperMethod === 'POST' &&
    normalized === 'plugin-observability/attention-state'
  ) {
    return '/internal/service/admin/plugin-observability/attention-state';
  }
  if (
    upperMethod === 'POST' &&
    normalized === 'web-search-providers'
  ) {
    return '/internal/service/admin/web-search-providers';
  }
  if (
    upperMethod === 'POST' &&
    normalized === 'image-source-providers'
  ) {
    return '/internal/service/admin/image-source-providers';
  }
  if (
    upperMethod === 'POST' &&
    normalized === 'audio-providers'
  ) {
    return '/internal/service/admin/audio-providers';
  }
  if (
    upperMethod === 'POST' &&
    normalized === 'audio-providers/minimax/test'
  ) {
    return '/internal/service/admin/audio-providers/minimax/test';
  }
  if (
    upperMethod === 'POST' &&
    normalized === 'audio-jobs'
  ) {
    return '/internal/service/admin/audio-jobs';
  }
  if (
    upperMethod === 'POST' &&
    normalized === 'ai-resources/profile-preferences'
  ) {
    return '/internal/service/admin/ai-resources/profile-preferences';
  }
  if (
    upperMethod === 'POST' &&
    normalized === 'wordpress-ai-routing'
  ) {
    return '/internal/service/admin/wordpress-ai-routing';
  }

  return normalized ? `/internal/service/${normalized}` : '/internal/service';
}

async function proxyAdminRequest(
  request: NextRequest,
  pathSegments: string[],
  options: {
    method?: string;
    unreachableCode: string;
    unreachableMessage: string;
  }
): Promise<NextResponse> {
  const method = (options.method || request.method).toUpperCase();
  const backendPath = buildAdminBackendPath(pathSegments, method);
  const accept = request.headers.get('accept');
  const contentType = request.headers.get('content-type');
  const requestOrigin = getExternalRequestOrigin(request);
  const requestHost = getExternalRequestHost(request);
  const requestProto = getExternalRequestProto(request) || request.nextUrl.protocol.replace(/:$/, '');

  const sessionResult = await requireAdminSessionData(request);
  if (sessionResult instanceof NextResponse) {
    return sessionResult;
  }

  const headers = buildForwardedRequestHeaders(request, {
    Accept: accept || 'application/json',
  });

  headers.Origin = request.headers.get('origin') || requestOrigin;
  headers.Referer = request.headers.get('referer') || `${requestOrigin}/`;
  headers['X-Forwarded-Host'] = requestHost;
  headers['X-Forwarded-Proto'] = requestProto;
  headers['X-Forwarded-Port'] = request.nextUrl.port || '';

  // Copy specific request headers
  for (const headerName of COPIED_REQUEST_HEADERS) {
    const value = request.headers.get(headerName);
    if (value) {
      headers[headerName] = value;
    }
  }

  // Add internal token for all admin requests
  headers['X-Npcink-Internal-Token'] = getInternalAuthToken();

  // Add idempotency key for write requests
  if (method !== 'GET' && method !== 'HEAD') {
    headers['Idempotency-Key'] = request.headers.get('idempotency-key') || crypto.randomUUID();
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
  } catch (error) {
    return buildErrorResponse(
      502,
      options.unreachableCode,
      error instanceof Error ? error.message : options.unreachableMessage
    );
  }

  return forwardBackendJson(response);
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_get_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_post_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_put_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_patch_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyAdminRequest(request, path || [], {
    unreachableCode: 'proxy.admin_delete_unreachable',
    unreachableMessage: 'failed to reach admin endpoint',
  });
}
