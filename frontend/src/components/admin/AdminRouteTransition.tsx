'use client';

import React, { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';

interface AdminRouteTransitionProps {
  children: React.ReactNode;
}

function isPlainAdminNavigation(event: MouseEvent, anchor: HTMLAnchorElement): boolean {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return false;
  }
  if (anchor.target && anchor.target !== '_self') {
    return false;
  }
  if (anchor.hasAttribute('download')) {
    return false;
  }

  const nextUrl = new URL(anchor.href, window.location.href);
  if (nextUrl.origin !== window.location.origin || !nextUrl.pathname.startsWith('/admin')) {
    return false;
  }

  const currentUrl = new URL(window.location.href);
  return nextUrl.pathname !== currentUrl.pathname;
}

export function AdminRouteTransition({ children }: AdminRouteTransitionProps) {
  const pathname = usePathname();
  const previousPathname = useRef(pathname);
  const pendingTimer = useRef<number | null>(null);
  const settleTimer = useRef<number | null>(null);
  const [routePending, setRoutePending] = useState(false);
  const [routeSettling, setRouteSettling] = useState(false);

  useEffect(() => {
    const clearTimer = (timer: React.MutableRefObject<number | null>) => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
        timer.current = null;
      }
    };

    const startPending = () => {
      clearTimer(pendingTimer);
      clearTimer(settleTimer);
      setRouteSettling(false);
      setRoutePending(true);
      pendingTimer.current = window.setTimeout(() => {
        setRoutePending(false);
        pendingTimer.current = null;
      }, 8000);
    };

    const handleDocumentClick = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }

      const anchor = target.closest('a[href]');
      if (!(anchor instanceof HTMLAnchorElement) || !isPlainAdminNavigation(event, anchor)) {
        return;
      }

      startPending();
    };

    const handlePopState = () => startPending();

    document.addEventListener('click', handleDocumentClick, true);
    window.addEventListener('popstate', handlePopState);

    return () => {
      document.removeEventListener('click', handleDocumentClick, true);
      window.removeEventListener('popstate', handlePopState);
      clearTimer(pendingTimer);
      clearTimer(settleTimer);
    };
  }, []);

  useEffect(() => {
    if (previousPathname.current === pathname) {
      return;
    }

    previousPathname.current = pathname;
    if (pendingTimer.current !== null) {
      window.clearTimeout(pendingTimer.current);
      pendingTimer.current = null;
    }
    if (settleTimer.current !== null) {
      window.clearTimeout(settleTimer.current);
      settleTimer.current = null;
    }
    setRoutePending(false);
    setRouteSettling(true);
    settleTimer.current = window.setTimeout(() => {
      setRouteSettling(false);
      settleTimer.current = null;
    }, 180);
  }, [pathname]);

  return (
    <>
      <div
        className={cn('admin-route-pending-indicator', routePending && 'admin-route-pending-indicator-visible')}
        aria-hidden="true"
      >
        <span />
      </div>
      <div
        className={cn(
          'admin-route-transition mx-auto w-full max-w-[110rem] px-3 py-4 md:px-5 md:py-5',
          routePending && 'admin-route-transition-pending',
          routeSettling && 'admin-route-transition-settling'
        )}
        aria-busy={routePending ? 'true' : undefined}
      >
        {children}
      </div>
    </>
  );
}
