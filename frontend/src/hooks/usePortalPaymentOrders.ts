'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
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
  accountId?: string;
  isAuthenticated: boolean;
  t: TranslateFn;
};

export function usePortalPaymentOrders({
  accountId,
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

  const load = useCallback(
    async (nextStatusGroup: PortalPaymentOrderStatusGroup, nextOffset: number) => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await portalClient.listAccountPaymentOrders({
          statusGroup: nextStatusGroup,
          limit: PORTAL_PAYMENT_ORDER_PAGE_SIZE,
          offset: nextOffset,
        });
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
        setError(formatPortalErrorMessage(loadError, t, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    },
    [t]
  );

  useEffect(() => {
    if (!isAuthenticated || !accountId) return;
    void load(statusGroup, offset);
  }, [accountId, isAuthenticated, load, offset, statusGroup]);

  useEffect(() => {
    if (!isAuthenticated || !accountId) return;
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
  }, [accountId, isAuthenticated, load, offset, statusGroup]);

  const cancel = useCallback(async (order: PortalPaymentOrder) => {
    setCancelPendingOrderId(order.order_id);
    setCancelConfirmOrderId(null);
    setError(null);
    try {
      await portalClient.cancelAccountPaymentOrder(order.order_id);
      await load(statusGroup, offset);
    } catch (cancelError) {
      setError(formatPortalErrorMessage(cancelError, t, t('error.failed_save')));
    } finally {
      setCancelPendingOrderId(null);
    }
  }, [load, offset, statusGroup, t]);

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
