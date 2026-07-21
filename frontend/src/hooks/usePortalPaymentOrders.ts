'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { PORTAL_PAYMENT_ORDER_PAGE_SIZE } from '@/components/portal/PortalPaymentOrderHistory';
import {
  portalClient,
  type PortalPaymentOrder,
  type PortalPaymentOrderListPayload,
  type PortalPaymentOrderStatusGroup,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

type UsePortalPaymentOrdersOptions = {
  contextSiteId?: string;
  isAuthenticated: boolean;
  t: TranslateFn;
};

export function usePortalPaymentOrders({
  contextSiteId,
  isAuthenticated,
  t,
}: UsePortalPaymentOrdersOptions) {
  const [payload, setPayload] = useState<PortalPaymentOrderListPayload | null>(null);
  const [statusGroup, setStatusGroup] = useState<PortalPaymentOrderStatusGroup>('all');
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelPendingOrderId, setCancelPendingOrderId] = useState<string | null>(null);
  const [cancelConfirmOrderId, setCancelConfirmOrderId] = useState<string | null>(null);
  const tabInitialized = useRef(false);
  const normalizedContextSiteId = String(contextSiteId || '').trim();
  const contextSiteIdRef = useRef(normalizedContextSiteId);
  const loadRequestVersionRef = useRef(0);
  const cancelRequestVersionRef = useRef(0);

  const load = useCallback(
    async (nextStatusGroup: PortalPaymentOrderStatusGroup, nextOffset: number) => {
      const requestContextSiteId = contextSiteIdRef.current;
      if (!isAuthenticated || !requestContextSiteId) {
        loadRequestVersionRef.current += 1;
        setIsLoading(false);
        return;
      }
      const requestVersion = ++loadRequestVersionRef.current;
      setIsLoading(true);
      setError(null);
      try {
        const response = await portalClient.listAccountPaymentOrders({
          statusGroup: nextStatusGroup,
          limit: PORTAL_PAYMENT_ORDER_PAGE_SIZE,
          offset: nextOffset,
        });
        if (
          requestVersion !== loadRequestVersionRef.current
          || requestContextSiteId !== contextSiteIdRef.current
        ) return;
        setPayload(response.data);
        if (!tabInitialized.current) {
          tabInitialized.current = true;
          const initialGroup = Number(response.data.counts?.pending || 0) > 0 ? 'pending' : 'all';
          if (initialGroup !== nextStatusGroup) {
            setStatusGroup(initialGroup);
            setOffset(0);
          }
        }
      } catch (loadError) {
        if (
          requestVersion !== loadRequestVersionRef.current
          || requestContextSiteId !== contextSiteIdRef.current
        ) return;
        setError(formatPortalErrorMessage(loadError, t, t('error.failed_load')));
      } finally {
        if (
          requestVersion === loadRequestVersionRef.current
          && requestContextSiteId === contextSiteIdRef.current
        ) setIsLoading(false);
      }
    },
    [isAuthenticated, t]
  );

  useLayoutEffect(() => {
    contextSiteIdRef.current = normalizedContextSiteId;
    loadRequestVersionRef.current += 1;
    cancelRequestVersionRef.current += 1;
    tabInitialized.current = false;
    setPayload(null);
    setStatusGroup('all');
    setOffset(0);
    setIsLoading(Boolean(isAuthenticated && normalizedContextSiteId));
    setError(null);
    setCancelPendingOrderId(null);
    setCancelConfirmOrderId(null);
  }, [isAuthenticated, normalizedContextSiteId]);

  useEffect(() => {
    if (!isAuthenticated || !normalizedContextSiteId) return;
    void load(statusGroup, offset);
  }, [isAuthenticated, load, normalizedContextSiteId, offset, statusGroup]);

  useEffect(() => {
    if (!isAuthenticated || !normalizedContextSiteId) return;
    const refresh = () => void load(statusGroup, offset);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isAuthenticated, load, normalizedContextSiteId, offset, statusGroup]);

  const cancel = useCallback(async (order: PortalPaymentOrder) => {
    const requestContextSiteId = contextSiteIdRef.current;
    if (!isAuthenticated || !requestContextSiteId) return;
    const requestVersion = ++cancelRequestVersionRef.current;
    setCancelPendingOrderId(order.order_id);
    setCancelConfirmOrderId(null);
    setError(null);
    try {
      await portalClient.cancelAccountPaymentOrder(order.order_id);
      if (
        requestVersion !== cancelRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
      ) return;
      await load(statusGroup, offset);
    } catch (cancelError) {
      if (
        requestVersion !== cancelRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
      ) return;
      setError(formatPortalErrorMessage(cancelError, t, t('error.failed_save')));
    } finally {
      if (
        requestVersion === cancelRequestVersionRef.current
        && requestContextSiteId === contextSiteIdRef.current
      ) setCancelPendingOrderId(null);
    }
  }, [isAuthenticated, load, offset, statusGroup, t]);

  return {
    payload,
    statusGroup,
    offset,
    isLoading,
    error,
    cancelPendingOrderId,
    cancelConfirmOrderId,
    load,
    cancel,
    setStatusGroup,
    setOffset,
    setCancelConfirmOrderId,
  };
}
