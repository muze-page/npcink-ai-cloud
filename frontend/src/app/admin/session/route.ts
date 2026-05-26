import { NextRequest } from 'next/server';
import { buildBackendUrl, buildForwardedRequestHeaders, forwardBackendJson } from '@/app/api/admin/_shared';

export async function GET(request: NextRequest) {
  const response = await fetch(buildBackendUrl('/admin/session'), {
    headers: buildForwardedRequestHeaders(request, {
      Accept: 'application/json',
      Cookie: request.headers.get('cookie') || '',
    }),
    cache: 'no-store',
  });

  return forwardBackendJson(response);
}
