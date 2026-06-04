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
} from '../../_shared';
import { getInternalAuthToken } from '@/lib/env';

export async function GET(request: NextRequest): Promise<NextResponse> {
  const sessionResult = await requireAdminSessionData(request);
  if (sessionResult instanceof NextResponse) {
    return sessionResult;
  }

  const requestOrigin = getExternalRequestOrigin(request);
  const requestHost = getExternalRequestHost(request);
  const requestProto = getExternalRequestProto(request) || request.nextUrl.protocol.replace(/:$/, '');
  const headers = buildForwardedRequestHeaders(request, {
    Accept: 'application/json',
    'X-Magick-Internal-Token': getInternalAuthToken(),
  });

  headers.Origin = request.headers.get('origin') || requestOrigin;
  headers.Referer = request.headers.get('referer') || `${requestOrigin}/`;
  headers['X-Forwarded-Host'] = requestHost;
  headers['X-Forwarded-Proto'] = requestProto;
  headers['X-Forwarded-Port'] = request.nextUrl.port || '';

  let response: Response;
  try {
    response = await fetch(
      buildBackendUrl('/internal/service/advisor/ops-summary-preview', request.nextUrl.search),
      {
        method: 'GET',
        headers,
        cache: 'no-store',
      }
    );
  } catch (error) {
    return buildErrorResponse(
      502,
      'proxy.admin_advisor_preview_unreachable',
      error instanceof Error ? error.message : 'failed to reach advisor preview endpoint'
    );
  }

  return forwardBackendJson(response);
}
