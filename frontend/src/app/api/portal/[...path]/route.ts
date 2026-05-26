import { NextRequest } from 'next/server';
import { proxyPortalPathSegments } from '@/app/api/portal/_shared';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyPortalPathSegments(request, path || [], {
    unreachableCode: 'proxy.portal_get_unreachable',
    unreachableMessage: 'failed to reach portal endpoint',
  });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyPortalPathSegments(request, path || [], {
    unreachableCode: 'proxy.portal_post_unreachable',
    unreachableMessage: 'failed to reach portal endpoint',
  });
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyPortalPathSegments(request, path || [], {
    unreachableCode: 'proxy.portal_put_unreachable',
    unreachableMessage: 'failed to reach portal endpoint',
  });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyPortalPathSegments(request, path || [], {
    unreachableCode: 'proxy.portal_delete_unreachable',
    unreachableMessage: 'failed to reach portal endpoint',
  });
}
