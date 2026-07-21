import { NextRequest, NextResponse } from 'next/server';
import {
  buildBackendUrl,
  buildErrorResponse,
  buildForwardedRequestHeaders,
  forwardBackendJson,
  getExternalRequestHost,
  getExternalRequestOrigin,
  getExternalRequestProto,
  requireAdminCapability,
  requireAdminSessionData,
} from '../../_shared';
import { getInternalAuthToken } from '@/lib/env';

export async function GET(request: NextRequest): Promise<NextResponse> {
  const sessionResult = await requireAdminSessionData(request);
  if (sessionResult instanceof NextResponse) {
    return sessionResult;
  }
  const capabilityError = requireAdminCapability(
    sessionResult.session,
    'can_review_diagnostics'
  );
  if (capabilityError) {
    return capabilityError;
  }

  const requestOrigin = getExternalRequestOrigin(request);
  const requestHost = getExternalRequestHost(request);
  const requestProto = getExternalRequestProto(request) || request.nextUrl.protocol.replace(/:$/, '');
  const headers = buildForwardedRequestHeaders(request, {
    Accept: 'application/json',
    'X-Npcink-Internal-Token': getInternalAuthToken(),
  });

  headers.Origin = request.headers.get('origin') || requestOrigin;
  headers.Referer = request.headers.get('referer') || `${requestOrigin}/`;
  headers['X-Forwarded-Host'] = requestHost;
  headers['X-Forwarded-Proto'] = requestProto;
  headers['X-Forwarded-Port'] = request.nextUrl.port || '';

  let response: Response;
  try {
    response = await fetch(
      buildBackendUrl('/internal/service/advisor/ops-summary-value', request.nextUrl.search),
      {
        method: 'GET',
        headers,
        cache: 'no-store',
      }
    );
  } catch {
    return buildErrorResponse(
      502,
      'proxy.admin_advisor_value_unreachable',
      'failed to reach advisor value metrics endpoint'
    );
  }

  return forwardBackendJson(response);
}
