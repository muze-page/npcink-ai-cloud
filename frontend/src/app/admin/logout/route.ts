import { NextRequest, NextResponse } from 'next/server';
import { appendForwardHeaders, buildBackendUrl } from '@/app/api/admin/_shared';

export async function GET(request: NextRequest) {
  const response = await fetch(buildBackendUrl('/admin/logout', request.nextUrl.search), {
    headers: {
      Accept: 'text/html,application/json',
      Cookie: request.headers.get('cookie') || '',
    },
    redirect: 'manual',
    cache: 'no-store',
  });

  const nextResponse = new NextResponse(null, { status: response.status });
  appendForwardHeaders(response, nextResponse);
  return nextResponse;
}
