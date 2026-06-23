import { NextRequest, NextResponse } from 'next/server';
import {
  buildBackendUrl,
  buildErrorResponse,
  buildForwardedRequestHeaders,
  forwardBackendJson,
  getExternalRequestHost,
  getExternalRequestOrigin,
  getExternalRequestProto,
  requireAdminSessionData,
} from '../../_shared';
import { getInternalAuthToken } from '@/lib/env';

export async function POST(request: NextRequest): Promise<NextResponse> {
  const sessionResult = await requireAdminSessionData(request);
  if (sessionResult instanceof NextResponse) {
    return sessionResult;
  }

  const requestOrigin = getExternalRequestOrigin(request);
  const requestHost = getExternalRequestHost(request);
  const requestProto = getExternalRequestProto(request) || request.nextUrl.protocol.replace(/:$/, '');
  const body = await request.json().catch(() => ({}));
  const headers = buildForwardedRequestHeaders(request, {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    'X-Npcink-Internal-Token': getInternalAuthToken(),
  });

  headers.Origin = request.headers.get('origin') || requestOrigin;
  headers.Referer = request.headers.get('referer') || `${requestOrigin}/`;
  headers['X-Forwarded-Host'] = requestHost;
  headers['X-Forwarded-Proto'] = requestProto;
  headers['X-Forwarded-Port'] = request.nextUrl.port || '';
  headers['Idempotency-Key'] = request.headers.get('idempotency-key') || crypto.randomUUID();

  let response: Response;
  try {
    response = await fetch(buildBackendUrl('/internal/service/advisor/ops-summary-review'), {
      method: 'POST',
      headers,
      body: JSON.stringify({
        ...body,
        actor_ref: sessionResult.session.platform_admin_ref,
      }),
      cache: 'no-store',
    });
  } catch (error) {
    return buildErrorResponse(
      502,
      'proxy.admin_advisor_review_unreachable',
      error instanceof Error ? error.message : 'failed to reach advisor review endpoint'
    );
  }

  return forwardBackendJson(response);
}
