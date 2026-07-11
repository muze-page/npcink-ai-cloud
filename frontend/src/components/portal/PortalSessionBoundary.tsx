'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useRef, type ReactNode } from 'react';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useSession } from '@/hooks/useSession';

const PUBLIC_PORTAL_PATHS = new Set([
  '/portal/login',
  '/portal/register',
  '/portal/dev-entry',
]);

export function PortalSessionBoundary({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated, isLoading, logout } = useSession();
  const redirectStartedRef = useRef(false);
  const isPublicPath = PUBLIC_PORTAL_PATHS.has(pathname);

  useEffect(() => {
    if (isPublicPath) {
      redirectStartedRef.current = false;
      return;
    }
    if (isLoading || isAuthenticated || redirectStartedRef.current) {
      return;
    }

    redirectStartedRef.current = true;
    const returnTo = `${pathname}${window.location.search}`;
    const loginUrl = `/portal/login?redirect=${encodeURIComponent(returnTo)}`;
    void logout().finally(() => window.location.replace(loginUrl));
  }, [isAuthenticated, isLoading, isPublicPath, logout, pathname]);

  if (!isPublicPath && !isLoading && !isAuthenticated) {
    return <LoadingFallback />;
  }

  return children;
}
