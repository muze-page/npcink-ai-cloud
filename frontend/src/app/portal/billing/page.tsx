'use client';

import React, { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { PortalEntitlementUsage } from '@/components/portal/PortalEntitlementUsage';
import {
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type Entitlements,
  type PortalCreditPackCatalogPayload,
  type PortalPaymentOrder,
  type PortalPaymentOrderListPayload,
  type PortalPaymentOrderStatusGroup,
  type PortalPlanOffer,
  type PortalPlanOfferListPayload,
} from '@/lib/portal-client';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import { DEFAULT_PORTAL_CURRENCY, formatPortalCurrency, normalizePortalCurrency } from '@/lib/currency';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatDate, formatNumber } from '@/lib/utils';

function formatQuotaValue(value: unknown, unlimited = false, unlimitedLabel = 'Unlimited'): string {
  if (unlimited) return unlimitedLabel;
  return formatNumber(Math.round(Number(value || 0)));
}

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

const PAYMENT_ORDER_PAGE_SIZE = 10;

type PaymentLaunchState = {
  checkoutUrl: string;
  opened: boolean;
};

function preparePaymentWindow(): Window | null {
  const paymentWindow = window.open('about:blank', '_blank');
  if (paymentWindow) paymentWindow.opener = null;
  return paymentWindow;
}

function closePreparedPaymentWindow(paymentWindow: Window | null): void {
  if (paymentWindow && !paymentWindow.closed) paymentWindow.close();
}

function normalizePaymentText(value: unknown): string {
  return String(value || '').trim().toLowerCase().replace(/[\s_-]+/g, '_');
}

function resolvePaymentOrderTitle(order: PortalPaymentOrder, t: TranslateFn): string {
  const packId = String(order.credit_pack?.pack_id || '').trim();
  const rawTitle = String(order.credit_pack?.label || order.subject || '').trim();
  const normalized = normalizePaymentText(`${packId} ${rawTitle}`);
  const packKey = normalized.includes('pack_small') || normalized.includes('small_credit_pack')
    ? 'pack_small'
    : normalized.includes('pack_medium') || normalized.includes('medium_credit_pack')
      ? 'pack_medium'
      : normalized.includes('pack_large') || normalized.includes('large_credit_pack')
        ? 'pack_large'
        : '';

  if (packKey) {
    return t(`portal.usage.credit_pack_${packKey}`, {}, rawTitle || order.order_id);
  }
  if (normalizePaymentText(order.purchase_kind).includes('subscription')) {
    const tier = String(order.metadata?.target_tier_id || '').trim();
    const tierLabel = tier ? `${tier.charAt(0).toUpperCase()}${tier.slice(1)}` : '';
    return tierLabel
      ? t(
          'portal.usage.payment_order_subscription_title',
          { tier: tierLabel },
          `${tierLabel} monthly package`
        )
      : rawTitle;
  }
  return rawTitle || order.order_id;
}

function resolvePaymentOrderStatusLabel(order: PortalPaymentOrder, t: TranslateFn): string {
  const status = normalizePaymentText(order.status);
  const code = normalizePaymentText(order.status_detail?.code);
  if (code.includes('expired')) {
    return t('portal.usage.payment_order_status_expired', {}, 'Expired');
  }
  if (code.includes('awaiting_payment_confirmation') || status === 'pending') {
    return t('portal.usage.payment_order_status_waiting_confirmation', {}, 'Waiting for payment confirmation');
  }
  if (code.includes('paid') || status === 'paid') {
    return t('portal.usage.payment_order_status_paid', {}, 'Paid');
  }
  if (code.includes('refund') || status === 'refunded') {
    return t('portal.usage.payment_order_status_refunded', {}, 'Refunded');
  }
  if (status === 'failed') {
    return t('portal.usage.payment_order_status_failed', {}, 'Failed');
  }
  if (status === 'canceled' || status === 'cancelled') {
    return t('portal.usage.payment_order_status_canceled', {}, 'Canceled');
  }
  return t('portal.usage.payment_order_status_unknown', {}, 'To confirm');
}

function resolvePaymentProviderLabel(order: PortalPaymentOrder, t: TranslateFn): string {
  const provider = normalizePaymentText(order.provider);
  if (provider === 'alipay') {
    return t('portal.usage.payment_provider_alipay', {}, 'Alipay');
  }
  if (provider === 'wechat_pay' || provider === 'wechat') {
    return t('portal.usage.payment_provider_wechat', {}, 'WeChat Pay');
  }
  if (provider === 'manual') {
    return t('portal.usage.payment_provider_manual', {}, 'Manual payment');
  }
  return String(order.provider || '').trim() || t('portal.usage.payment_provider_unknown', {}, 'Payment provider');
}

function resolvePaymentOrderDetail(order: PortalPaymentOrder, t: TranslateFn): string {
  const status = normalizePaymentText(order.status);
  const code = normalizePaymentText(order.status_detail?.code);
  if (code.includes('expired')) {
    return t('portal.usage.payment_order_expired_detail', {}, 'This unpaid order has expired.');
  }
  if (code.includes('awaiting_payment_confirmation') || status === 'pending') {
    return t(
      'portal.usage.payment_order_waiting_confirmation_detail',
      { provider: resolvePaymentProviderLabel(order, t) },
      `Waiting for ${resolvePaymentProviderLabel(order, t)} confirmation. Package changes or credits are granted after provider confirmation.`
    );
  }
  if (code.includes('paid') || status === 'paid') {
    return t('portal.usage.payment_order_paid_detail', {}, 'Payment has been confirmed.');
  }
  if (code.includes('refund') || status === 'refunded') {
    return t('portal.usage.payment_order_refunded_detail', {}, 'This order has been refunded.');
  }
  if (status === 'failed') {
    return t('portal.usage.payment_order_failed_detail', {}, 'Payment was not completed.');
  }
  if (status === 'canceled' || status === 'cancelled') {
    return t('portal.usage.payment_order_canceled_detail', {}, 'This unpaid order was canceled.');
  }
  return t('portal.usage.payment_order_default_detail', {}, 'Payment status is recorded by Cloud.');
}

function isPendingPaymentOrder(order: PortalPaymentOrder): boolean {
  return normalizePaymentText(order.status) === 'pending';
}

function paymentOrderAllowsAction(
  order: PortalPaymentOrder,
  action: 'continue_payment' | 'cancel'
): boolean {
  return Array.isArray(order.available_actions) && order.available_actions.includes(action);
}

function formatPaymentOrderReference(orderId: string): string {
  const normalized = String(orderId || '').trim();
  if (normalized.length <= 20) return normalized;
  return `${normalized.slice(0, 14)}…${normalized.slice(-4)}`;
}

function PortalBillingContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, refresh } = useSession();
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [creditPacks, setCreditPacks] = useState<PortalCreditPackCatalogPayload | null>(null);
  const [paymentOrders, setPaymentOrders] = useState<PortalPaymentOrderListPayload | null>(null);
  const [planOffers, setPlanOffers] = useState<PortalPlanOfferListPayload | null>(null);
  const [creditPackPending, setCreditPackPending] = useState<string | null>(null);
  const [creditPackError, setCreditPackError] = useState<string | null>(null);
  const [packagePending, setPackagePending] = useState<string | null>(null);
  const [packageError, setPackageError] = useState<string | null>(null);
  const [trialTierSelection, setTrialTierSelection] = useState<'plus' | 'pro'>('pro');
  const [cancelPendingOrderId, setCancelPendingOrderId] = useState<string | null>(null);
  const [cancelConfirmOrderId, setCancelConfirmOrderId] = useState<string | null>(null);
  const [paymentOrderError, setPaymentOrderError] = useState<string | null>(null);
  const [paymentOrderStatusGroup, setPaymentOrderStatusGroup] =
    useState<PortalPaymentOrderStatusGroup>('all');
  const [paymentOrderOffset, setPaymentOrderOffset] = useState(0);
  const [paymentOrdersLoading, setPaymentOrdersLoading] = useState(false);
  const [paymentLaunch, setPaymentLaunch] = useState<PaymentLaunchState | null>(null);
  const [paymentReturnOrderState, setPaymentReturnOrderState] = useState<PortalPaymentOrder | null>(null);
  const [paymentReturnError, setPaymentReturnError] = useState<string | null>(null);
  const [paymentReturnTimedOut, setPaymentReturnTimedOut] = useState(false);
  const [paymentReturnReconciled, setPaymentReturnReconciled] = useState(false);
  const paymentOrderTabInitialized = useRef(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBilling = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const bundle = await portalClient.getAccountCommercialBundle();
      setEntitlements(bundle.entitlements);
      setCreditPacks(bundle.creditPacks);
      setPlanOffers(bundle.planOffers || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error.failed_load', {}, 'Failed to load.'));
      setEntitlements(null);
      setCreditPacks(null);
      setPlanOffers(null);
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  const loadPaymentOrders = useCallback(
    async (statusGroup: PortalPaymentOrderStatusGroup, offset: number) => {
      setPaymentOrdersLoading(true);
      setPaymentOrderError(null);
      try {
        const response = await portalClient.listAccountPaymentOrders({
          statusGroup,
          limit: PAYMENT_ORDER_PAGE_SIZE,
          offset,
        });
        setPaymentOrders(response.data);
        if (!paymentOrderTabInitialized.current) {
          paymentOrderTabInitialized.current = true;
          const initialGroup = Number(response.data.counts?.pending || 0) > 0 ? 'pending' : 'all';
          if (initialGroup !== statusGroup) {
            setPaymentOrderStatusGroup(initialGroup);
            setPaymentOrderOffset(0);
          }
        }
      } catch (err) {
        setPaymentOrderError(formatPortalErrorMessage(err, t, t('error.failed_load')));
      } finally {
        setPaymentOrdersLoading(false);
      }
    },
    [t]
  );

  const loadPaymentReturnOrder = useCallback(async (orderId: string) => {
    const normalizedOrderId = String(orderId || '').trim();
    if (!normalizedOrderId) return null;
    try {
      const response = await portalClient.getAccountPaymentOrder(normalizedOrderId);
      setPaymentReturnOrderState(response.data.order);
      setPaymentReturnError(null);
      return response.data.order;
    } catch (err) {
      setPaymentReturnError(formatPortalErrorMessage(err, t, t('error.failed_load')));
      return null;
    }
  }, [t]);

  useEffect(() => {
    if (!isAuthenticated || !session?.account_id) {
      setIsLoading(false);
      return;
    }
    void loadBilling();
  }, [isAuthenticated, loadBilling, session?.account_id]);

  useEffect(() => {
    if (!isAuthenticated || !session?.account_id) return;
    void loadPaymentOrders(paymentOrderStatusGroup, paymentOrderOffset);
  }, [
    isAuthenticated,
    loadPaymentOrders,
    paymentOrderOffset,
    paymentOrderStatusGroup,
    session?.account_id,
  ]);

  useEffect(() => {
    const allowedTiers = planOffers?.trial?.allowed_tiers || [];
    if (!allowedTiers.length || allowedTiers.includes(trialTierSelection)) return;
    setTrialTierSelection(allowedTiers.includes('pro') ? 'pro' : allowedTiers[0]);
  }, [planOffers?.trial?.allowed_tiers, trialTierSelection]);

  const paymentReturnProvider = String(searchParams.get('payment_return') || '').toLowerCase();
  const paymentReturnOrderId = String(searchParams.get('out_trade_no') || '').trim();
  const shouldPollAlipayReturn = paymentReturnProvider === 'alipay' && Boolean(paymentReturnOrderId);
  const hasAlipayReturn = shouldPollAlipayReturn || Boolean(paymentReturnOrderState);
  const activePaymentReturnOrderId = paymentReturnOrderId || paymentReturnOrderState?.order_id || '';

  useEffect(() => {
    if (!isAuthenticated || !session?.account_id || !shouldPollAlipayReturn) return;
    let canceled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    const poll = async () => {
      const order = await loadPaymentReturnOrder(paymentReturnOrderId);
      if (canceled) return;
      const status = normalizePaymentText(order?.status);
      if (status && status !== 'pending') {
        setPaymentReturnReconciled(false);
        window.history.replaceState(window.history.state, '', '/portal/billing');
        await Promise.all([
          refresh(),
          loadBilling(),
          loadPaymentOrders('all', 0),
        ]);
        if (!canceled) setPaymentReturnReconciled(true);
        return;
      }
      attempts += 1;
      if (attempts >= 20) {
        setPaymentReturnTimedOut(true);
        return;
      }
      timer = setTimeout(() => void poll(), 3000);
    };
    setPaymentReturnTimedOut(false);
    void poll();
    return () => {
      canceled = true;
      if (timer) clearTimeout(timer);
    };
  }, [
    isAuthenticated,
    loadBilling,
    loadPaymentOrders,
    loadPaymentReturnOrder,
    paymentReturnOrderId,
    refresh,
    session?.account_id,
    shouldPollAlipayReturn,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !session?.account_id) return;
    const refreshPaymentOrders = () => {
      void loadPaymentOrders(paymentOrderStatusGroup, paymentOrderOffset);
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') refreshPaymentOrders();
    };
    window.addEventListener('focus', refreshPaymentOrders);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener('focus', refreshPaymentOrders);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [
    isAuthenticated,
    loadPaymentOrders,
    paymentOrderOffset,
    paymentOrderStatusGroup,
    session?.account_id,
  ]);

  const handleStartPlanTrial = async (tierId: 'plus' | 'pro') => {
    setPackagePending(`trial:${tierId}`);
    setPackageError(null);
    try {
      await portalClient.startPlanTrial(tierId);
      await refresh();
      await loadBilling();
    } catch (err) {
      setPackageError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setPackagePending(null);
    }
  };

  const handleCreateSubscriptionOrder = async (offer: PortalPlanOffer) => {
    const paymentWindow = preparePaymentWindow();
    setPackagePending(`order:${offer.tier_id}`);
    setPackageError(null);
    setPaymentLaunch(null);
    try {
      const response = await portalClient.createSubscriptionOrder(offer.offer_id, 'alipay');
      if (response.data.order.checkout_url) {
        if (paymentWindow && !paymentWindow.closed) {
          paymentWindow.location.replace(response.data.order.checkout_url);
          setPaymentLaunch({ checkoutUrl: response.data.order.checkout_url, opened: true });
        } else {
          setPaymentLaunch({ checkoutUrl: response.data.order.checkout_url, opened: false });
        }
        setPaymentOrderStatusGroup('pending');
        setPaymentOrderOffset(0);
        await loadPaymentOrders('pending', 0);
      } else {
        closePreparedPaymentWindow(paymentWindow);
      }
    } catch (err) {
      closePreparedPaymentWindow(paymentWindow);
      setPackageError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setPackagePending(null);
    }
  };

  const handleScheduleFreeDowngrade = async () => {
    setPackagePending('downgrade:free');
    setPackageError(null);
    try {
      await portalClient.scheduleFreeDowngrade();
      await refresh();
      await loadBilling();
    } catch (err) {
      setPackageError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setPackagePending(null);
    }
  };

  const handleCancelPaymentOrder = async (order: PortalPaymentOrder) => {
    setCancelPendingOrderId(order.order_id);
    setCancelConfirmOrderId(null);
    setPaymentOrderError(null);
    try {
      await portalClient.cancelAccountPaymentOrder(order.order_id);
      await loadPaymentOrders(paymentOrderStatusGroup, paymentOrderOffset);
    } catch (err) {
      setPaymentOrderError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setCancelPendingOrderId(null);
    }
  };

  const handleCreateCreditPackOrder = async (packId: string) => {
    const paymentWindow = preparePaymentWindow();
    setCreditPackPending(packId);
    setCreditPackError(null);
    setPaymentLaunch(null);
    try {
      const response = await portalClient.createAccountCreditPackOrder(packId);
      if (response.data.order.checkout_url) {
        if (paymentWindow && !paymentWindow.closed) {
          paymentWindow.location.replace(response.data.order.checkout_url);
          setPaymentLaunch({ checkoutUrl: response.data.order.checkout_url, opened: true });
        } else {
          setPaymentLaunch({ checkoutUrl: response.data.order.checkout_url, opened: false });
        }
        setPaymentOrderStatusGroup('pending');
        setPaymentOrderOffset(0);
        await loadPaymentOrders('pending', 0);
      } else {
        closePreparedPaymentWindow(paymentWindow);
      }
    } catch (err) {
      closePreparedPaymentWindow(paymentWindow);
      setCreditPackError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setCreditPackPending(null);
    }
  };

  if (sessionLoading) {
    return <PortalLoadingState message={t('portal.loading_session', {}, 'Loading session...')} />;
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('auth.sign_in_required', {}, 'Sign in required')}
        description={t('portal.signed_out_desc', {}, 'Sign in to view Cloud service details.')}
        actionLabel={t('nav.sign_in', {}, 'Sign in')}
      />
    );
  }

  const currentSubscription = session.current_subscription || null;
  const currentPlanId = String(currentSubscription?.plan_id || '').toLowerCase();
  const currentStatus = String(currentSubscription?.status || '').toLowerCase();
  const tierRank: Record<string, number> = { free: 0, plus: 1, pro: 2, agency: 3 };
  const currentRank = tierRank[currentPlanId] ?? 0;
  const offersByTier = new Map(
    (planOffers?.items || []).map((offer) => [offer.tier_id, offer] as const)
  );
  const plusOffer = offersByTier.get('plus');
  const proOffer = offersByTier.get('pro');
  const agencyOffer = offersByTier.get('agency');
  const trial = planOffers?.trial;
  const trialState = trial?.state
    || (trial?.status === 'active' ? 'active' : trial?.available === false ? 'used' : 'eligible');
  const allowedTrialTiers = (trial?.allowed_tiers || []).filter(
    (tier): tier is 'plus' | 'pro' => tier === 'plus' || tier === 'pro'
  );
  const selectedTrialTier = allowedTrialTiers.includes(trialTierSelection)
    ? trialTierSelection
    : allowedTrialTiers.includes('pro')
      ? 'pro'
      : allowedTrialTiers[0];
  const selectedTrialOffer = selectedTrialTier ? offersByTier.get(selectedTrialTier) : null;
  const trialDays = Number(trial?.trial_days || selectedTrialOffer?.trial_days || 14);
  const activeTrialTier = String(trial?.highest_tier_id || trial?.tier_id || currentPlanId || '').toLowerCase();
  const activeTrialTierLabel = activeTrialTier === 'plus' ? 'Plus' : activeTrialTier === 'pro' ? 'Pro' : '';
  const canBuyTier = (tierId: 'plus' | 'pro' | 'agency') =>
    Boolean(offersByTier.get(tierId));
  const allPaymentOrders = paymentOrders?.items || [];
  const paymentOrderCounts = paymentOrders?.counts || {
    all: allPaymentOrders.length,
    pending: allPaymentOrders.filter(isPendingPaymentOrder).length,
    paid: allPaymentOrders.filter((order) => normalizePaymentText(order.status) === 'paid').length,
    closed: allPaymentOrders.filter((order) => !['pending', 'paid'].includes(normalizePaymentText(order.status))).length,
  };

  const handleRefreshPaymentReturn = async () => {
    setPaymentReturnTimedOut(false);
    setPaymentReturnReconciled(false);
    const order = await loadPaymentReturnOrder(activePaymentReturnOrderId);
    await Promise.all([
      refresh(),
      loadBilling(),
      loadPaymentOrders(paymentOrderStatusGroup, paymentOrderOffset),
    ]);
    if (normalizePaymentText(order?.status) !== 'pending') {
      setPaymentReturnReconciled(true);
    }
  };

  const paymentReturnStatus = normalizePaymentText(paymentReturnOrderState?.status);
  const paymentReturnPaid = paymentReturnStatus === 'paid';
  const paymentReturnClosed = ['canceled', 'cancelled', 'failed', 'refunded'].includes(paymentReturnStatus);
  const paymentReturnCredits = Number(paymentReturnOrderState?.credit_pack?.ai_credits || 0);
  const paymentReturnQuota = entitlements?.quota_summary?.credit;
  const paymentReturnTotalAvailableValue = paymentReturnQuota?.total_remaining;
  const paymentReturnTotalAvailable = paymentReturnTotalAvailableValue == null
    ? null
    : Number(paymentReturnTotalAvailableValue);
  const paymentReturnNextExpiry = String(paymentReturnQuota?.paid_next_expires_at || '');

  const paymentReturnNotice = hasAlipayReturn ? (
    <BackofficeStackCard
      variant="portal"
      data-ui="payment-return-notice"
      role="status"
      aria-live="polite"
      className={paymentReturnPaid
        ? 'border-emerald-200 bg-emerald-50/70 dark:border-emerald-900/60 dark:bg-emerald-950/20'
        : paymentReturnClosed
          ? 'border-red-200 bg-red-50/70 dark:border-red-900/60 dark:bg-red-950/20'
          : 'border-blue-200 bg-blue-50/70 dark:border-blue-900/60 dark:bg-blue-950/20'}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {paymentReturnPaid
              ? t('portal.package.alipay_return_paid_title', {}, 'Payment confirmed')
              : paymentReturnClosed
                ? t('portal.package.alipay_return_closed_title', {}, 'Payment was not completed')
                : t('portal.package.alipay_return_title', {}, 'Payment confirmation is pending')}
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {paymentReturnPaid
              ? paymentReturnCredits > 0
                ? t(
                    'portal.package.alipay_return_paid_credits_desc',
                    { count: formatNumber(paymentReturnCredits) },
                    `Payment is confirmed and ${formatNumber(paymentReturnCredits)} credits were added.`
                  )
                : t('portal.package.alipay_return_paid_desc', {}, 'Payment is confirmed and your package has been updated.')
              : paymentReturnClosed
                ? t('portal.package.alipay_return_closed_desc', {}, 'This order is closed. You can create a new order if needed.')
                : paymentReturnTimedOut
                  ? t('portal.package.alipay_return_timeout_desc', {}, 'Confirmation is taking longer than expected. Refresh again or contact support with the order number.')
                  : t(
                      'portal.package.alipay_return_desc',
                      {},
                      'You have returned from Alipay. Cloud is checking the verified asynchronous notification.'
                    )}
          </p>
          {paymentReturnPaid && paymentReturnCredits > 0 && paymentReturnReconciled ? (
            <div className="mt-4 grid gap-2 sm:grid-cols-3">
              <div data-payment-return-metric="credited" className="rounded-xl border border-emerald-200/80 bg-white/70 px-3 py-3 dark:border-emerald-900/70 dark:bg-slate-950/40">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('portal.package.alipay_return_credited_label', {}, 'Added this time')}
                </p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">
                  {formatNumber(paymentReturnCredits)}
                </p>
              </div>
              <div data-payment-return-metric="total-available" className="rounded-xl border border-emerald-200/80 bg-white/70 px-3 py-3 dark:border-emerald-900/70 dark:bg-slate-950/40">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('portal.usage.total_remaining_label', {}, 'Total available')}
                </p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">
                  {paymentReturnTotalAvailable != null && Number.isFinite(paymentReturnTotalAvailable)
                    ? formatNumber(paymentReturnTotalAvailable)
                    : t('common.not_available', {}, 'Not available')}
                </p>
              </div>
              <div data-payment-return-metric="next-expiry" className="rounded-xl border border-emerald-200/80 bg-white/70 px-3 py-3 dark:border-emerald-900/70 dark:bg-slate-950/40">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t('portal.package.alipay_return_expiry_label', {}, 'Nearest paid-credit expiry')}
                </p>
                <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-white">
                  {paymentReturnNextExpiry
                    ? formatDate(paymentReturnNextExpiry)
                    : t('common.not_available', {}, 'Not available')}
                </p>
              </div>
            </div>
          ) : null}
          {activePaymentReturnOrderId ? (
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {t('portal.package.alipay_return_order', { order: activePaymentReturnOrderId }, `Order ${activePaymentReturnOrderId}`)}
            </p>
          ) : null}
          {paymentReturnError ? <p className="mt-2 text-sm text-red-700 dark:text-red-300">{paymentReturnError}</p> : null}
        </div>
        {!paymentReturnPaid ? (
          <button
            type="button"
            className="btn btn-secondary shrink-0"
            onClick={() => void handleRefreshPaymentReturn()}
          >
            {t('common.refresh', {}, 'Refresh')}
          </button>
        ) : null}
      </div>
    </BackofficeStackCard>
  ) : null;

  const paymentLaunchNotice = paymentLaunch ? (
    <div
      role="status"
      className="rounded-[1rem] border border-blue-200 bg-blue-50/70 px-4 py-3 text-sm text-blue-900 dark:border-blue-900/60 dark:bg-blue-950/20 dark:text-blue-100"
    >
      {paymentLaunch.opened ? (
        t(
          'portal.usage.payment_page_opened',
          {},
          'Alipay opened in a new tab. Return here after payment and the order status will refresh automatically.'
        )
      ) : (
        <span className="flex flex-wrap items-center gap-3">
          <span>
            {t(
              'portal.usage.payment_page_blocked',
              {},
              'Your browser blocked the payment tab. Use the button to open Alipay.'
            )}
          </span>
          <a
            className="btn btn-primary"
            href={paymentLaunch.checkoutUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t('portal.usage.payment_page_open_action', {}, 'Open Alipay')}
          </a>
        </span>
      )}
    </div>
  ) : null;

  const packageActions = (
    <BackofficeStackCard variant="portal" className="bg-white/70 dark:bg-slate-950/35">
      <section className="mb-4 rounded-[1rem] border border-blue-200 bg-blue-50/55 p-4 dark:border-blue-900/60 dark:bg-blue-950/20" aria-labelledby="portal-trial-eligibility-title">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700 dark:text-blue-300">
              {t('portal.package.trial_eyebrow', {}, 'Trial eligibility')}
            </p>
            <h2 id="portal-trial-eligibility-title" className="mt-1 text-base font-semibold text-slate-950 dark:text-white">
              {trialState === 'eligible'
                ? t('portal.package.trial_eligible_title', { days: String(trialDays) }, `${trialDays}-day paid-package trial available`)
                : trialState === 'active'
                  ? t('portal.package.trial_active_title', { tier: activeTrialTierLabel }, `${activeTrialTierLabel} trial is active`)
                  : trialState === 'used'
                    ? t('portal.package.trial_used_title', {}, 'Trial already used')
                    : trialState === 'blocked'
                      ? t('portal.package.trial_blocked_title', {}, 'Trial unavailable with an active paid package')
                      : t('portal.package.trial_unavailable_title', {}, 'Trial is not currently offered')}
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
              {trialState === 'eligible'
                ? t('portal.package.trial_shared_desc', {}, 'Each account has one shared paid-package trial. You may move to a higher tier during the trial, but the end date will not be extended.')
                : trialState === 'active'
                  ? t(
                      'portal.package.trial_active_desc',
                      {
                        tier: activeTrialTierLabel,
                        date: trial?.trial_ends_at ? formatDate(trial.trial_ends_at) : t('common.unknown', {}, 'To confirm'),
                      },
                      `${activeTrialTierLabel} trial ends ${trial?.trial_ends_at ? formatDate(trial.trial_ends_at) : 'to be confirmed'}. Moving to a higher tier does not extend the end date.`
                    )
                  : trialState === 'used'
                    ? t('portal.package.trial_used_desc', {}, 'This account has already used its paid-package trial. You can still purchase a package below.')
                    : trialState === 'blocked'
                      ? t('portal.package.trial_blocked_desc', {}, 'This account already has an active paid package, so a trial cannot be started. Renew or change the package below.')
                      : t('portal.package.trial_unavailable_desc', {}, 'No self-service trial is available for this account. Package purchase remains available.')}
            </p>
          </div>
          {selectedTrialTier && (trialState === 'eligible' || trialState === 'active') ? (
            <div className="w-full shrink-0 space-y-3 lg:w-auto lg:min-w-[18rem]">
              {allowedTrialTiers.length > 1 ? (
                <div className="grid grid-cols-2 gap-2" aria-label={t('portal.package.trial_choose_tier', {}, 'Choose trial package')}>
                  {allowedTrialTiers.map((tier) => (
                    <button
                      key={tier}
                      type="button"
                      className={tier === selectedTrialTier ? 'btn btn-primary' : 'btn btn-secondary'}
                      aria-pressed={tier === selectedTrialTier}
                      disabled={packagePending !== null}
                      onClick={() => setTrialTierSelection(tier)}
                    >
                      {tier === 'plus' ? 'Plus' : 'Pro'}
                    </button>
                  ))}
                </div>
              ) : null}
              <button
                type="button"
                className="btn btn-primary w-full"
                disabled={packagePending !== null}
                onClick={() => void handleStartPlanTrial(selectedTrialTier)}
              >
                {packagePending === `trial:${selectedTrialTier}`
                  ? t('common.saving', {}, 'Saving...')
                  : trialState === 'active'
                    ? t('portal.package.trial_upgrade_action', { tier: selectedTrialTier === 'plus' ? 'Plus' : 'Pro' }, `Move trial to ${selectedTrialTier === 'plus' ? 'Plus' : 'Pro'}`)
                    : t('portal.package.trial_start_action', { tier: selectedTrialTier === 'plus' ? 'Plus' : 'Pro', days: String(trialDays) }, `Start ${trialDays}-day ${selectedTrialTier === 'plus' ? 'Plus' : 'Pro'} trial`)}
              </button>
            </div>
          ) : null}
        </div>
      </section>
      <div className="grid gap-3 lg:grid-cols-4">
        <div className="rounded-[1rem] border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/35">
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.package.free_title', {}, 'Free')}
          </p>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            {t('portal.package.free_desc', {}, 'Included automatically after registration. No trial or payment required.')}
          </p>
          <BackofficeStatusBadge
            status={currentPlanId === 'free' ? 'ok' : 'neutral'}
            label={currentPlanId === 'free' ? t('common.current', {}, 'Current') : t('common.available', {}, 'Available')}
          />
          {currentRank > 0 ? (
            <button
              type="button"
              className="btn btn-secondary mt-4"
              disabled={packagePending !== null}
              onClick={() => void handleScheduleFreeDowngrade()}
            >
              {packagePending === 'downgrade:free'
                ? t('common.saving', {}, 'Saving...')
                : t('portal.package.schedule_free_downgrade', {}, 'Switch to Free at period end')}
            </button>
          ) : null}
        </div>
        <div className="rounded-[1rem] border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/35">
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.package.plus_title', {}, 'Plus')}
          </p>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            {plusOffer
              ? t(
                  'portal.package.paid_offer_desc',
                  {
                    amount: formatPortalCurrency(plusOffer.amount),
                  },
                  `${formatPortalCurrency(plusOffer.amount)} for 30 days.`
                )
              : t('portal.package.offer_unavailable_desc', {}, 'This package is not currently available for purchase.')}
          </p>
          {currentPlanId === 'plus' || !plusOffer ? (
            <BackofficeStatusBadge
              status={currentPlanId === 'plus' ? 'ok' : 'warning'}
              label={currentPlanId === 'plus'
                ? currentStatus === 'trialing'
                  ? t('portal.package.pro_trial_active', {}, 'Trial active')
                  : t('common.current', {}, 'Current')
                : t('portal.package.offer_unavailable', {}, 'Unavailable')}
            />
          ) : null}
          <div className="mt-4 flex flex-col gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!plusOffer || !canBuyTier('plus') || packagePending !== null}
              onClick={() => plusOffer && void handleCreateSubscriptionOrder(plusOffer)}
            >
              {packagePending === 'order:plus'
                ? t('common.saving', {}, 'Saving...')
                : currentPlanId === 'plus'
                  ? t('portal.package.renew_monthly', {}, 'Renew 30 days')
                  : currentRank > tierRank.plus
                    ? t('portal.package.schedule_paid_downgrade', {}, 'Use next period')
                  : t('portal.package.buy_plus_monthly', {}, 'Buy Plus')}
            </button>
          </div>
        </div>
        <div className="rounded-[1rem] border border-blue-200 bg-blue-50/60 p-4 dark:border-blue-900/60 dark:bg-blue-950/20">
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.package.pro_title', {}, 'Pro')}
          </p>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            {proOffer
              ? t(
                  'portal.package.paid_offer_desc',
                  {
                    amount: formatPortalCurrency(proOffer.amount),
                  },
                  `${formatPortalCurrency(proOffer.amount)} for 30 days.`
                )
              : t('portal.package.offer_unavailable_desc', {}, 'This package is not currently available for purchase.')}
          </p>
          {currentPlanId === 'pro' || !proOffer ? (
            <BackofficeStatusBadge
              status={currentPlanId === 'pro' ? 'ok' : 'warning'}
              label={currentPlanId === 'pro'
                ? currentStatus === 'trialing'
                  ? t('portal.package.pro_trial_active', {}, 'Trial active')
                  : t('common.current', {}, 'Current')
                : t('portal.package.offer_unavailable', {}, 'Unavailable')}
            />
          ) : null}
          <div className="mt-4 flex flex-col gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!proOffer || !canBuyTier('pro') || packagePending !== null}
              onClick={() => proOffer && void handleCreateSubscriptionOrder(proOffer)}
            >
              {packagePending === 'order:pro'
                ? t('common.saving', {}, 'Saving...')
                : currentPlanId === 'pro'
                  ? t('portal.package.renew_monthly', {}, 'Renew 30 days')
                  : currentRank > tierRank.pro
                    ? t('portal.package.schedule_paid_downgrade', {}, 'Use next period')
                  : t('portal.package.buy_pro_monthly', {}, 'Buy Pro')}
            </button>
          </div>
        </div>
        <div className="rounded-[1rem] border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/35">
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.package.agency_title', {}, 'Agency')}
          </p>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
            {agencyOffer
              ? t(
                  'portal.package.agency_quote_desc',
                  { amount: formatPortalCurrency(agencyOffer.amount) },
                  `Your Agency quote is ${formatPortalCurrency(agencyOffer.amount)} for 30 days.`
                )
              : t('portal.package.agency_desc', {}, 'Custom high-volume coverage. Submit a request for a time-limited quote and approved trial.')}
          </p>
          <BackofficeStatusBadge
            status={currentPlanId === 'agency' ? 'ok' : 'neutral'}
            label={currentPlanId === 'agency' ? t('common.current', {}, 'Current') : t('portal.package.custom_only', {}, 'Custom')}
          />
          <div className="mt-4">
            {agencyOffer ? (
              <button
                type="button"
                className="btn btn-primary"
                disabled={!canBuyTier('agency') || packagePending !== null}
                onClick={() => void handleCreateSubscriptionOrder(agencyOffer)}
              >
                {packagePending === 'order:agency'
                  ? t('common.saving', {}, 'Saving...')
                  : currentPlanId === 'agency'
                    ? t('portal.package.renew_monthly', {}, 'Renew 30 days')
                    : t('portal.package.buy_agency_quote', {}, 'Pay Agency quote')}
              </button>
            ) : (
              <Link href="/portal/support?new=1&topic=billing" className="btn btn-secondary">
                {t('portal.package.request_agency_quote', {}, 'Request Agency quote')}
              </Link>
            )}
          </div>
        </div>
      </div>
      {packageError ? (
        <div className="mt-4 rounded-[1rem] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-200">
          {packageError}
        </div>
      ) : null}
    </BackofficeStackCard>
  );

  const renderPaymentOrderList = (orders: PortalPaymentOrder[]) => (
    <div className="divide-y divide-slate-200 overflow-hidden rounded-[1rem] border border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-800">
      {orders.map((order) => {
        const isConfirmingCancel = cancelConfirmOrderId === order.order_id;
        const isPending = isPendingPaymentOrder(order);
        return (
          <div
            key={order.order_id}
            data-payment-order-id={order.order_id}
            className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center"
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-semibold text-slate-950 dark:text-white">
                  {resolvePaymentOrderTitle(order, t)}
                </p>
                <BackofficeStatusBadge
                  label={resolvePaymentOrderStatusLabel(order, t)}
                  status={order.status || 'pending'}
                />
              </div>
              {isPending ? (
                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {resolvePaymentOrderDetail(order, t)}
                </p>
              ) : null}
              <p
                className={`${isPending ? 'mt-2' : 'mt-1'} text-xs font-medium text-slate-500 dark:text-slate-400`}
                title={order.order_id}
              >
                {t(
                  'portal.usage.payment_order_provider_reference',
                  {
                    provider: resolvePaymentProviderLabel(order, t),
                    order: formatPaymentOrderReference(order.order_id),
                  },
                  `${resolvePaymentProviderLabel(order, t)} · Order ${formatPaymentOrderReference(order.order_id)}`
                )}
              </p>
            </div>
            <div className="md:min-w-36 md:text-right">
              <p className="font-semibold text-slate-950 dark:text-white">
                {formatPortalCurrency(Number(order.amount || 0), {
                  from: normalizePortalCurrency(order.currency),
                  to: DEFAULT_PORTAL_CURRENCY,
                })}
              </p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {isPending && order.expires_at
                  ? t(
                      'portal.usage.payment_order_expires_at',
                      { time: formatDate(order.expires_at) },
                      `Complete payment before ${formatDate(order.expires_at)}`
                    )
                  : order.created_at ? formatDate(order.created_at) : order.order_id}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 md:min-w-48 md:justify-end">
              {paymentOrderAllowsAction(order, 'continue_payment') && order.checkout_url ? (
                <a
                  className="btn btn-primary"
                  href={order.checkout_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t('portal.usage.payment_order_continue', {}, 'Continue payment')}
                </a>
              ) : null}
              {paymentOrderAllowsAction(order, 'cancel') ? (
                isConfirmingCancel ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-danger"
                      disabled={cancelPendingOrderId !== null}
                      onClick={() => void handleCancelPaymentOrder(order)}
                    >
                      {cancelPendingOrderId === order.order_id
                        ? t('common.saving', {}, 'Saving...')
                        : t('portal.usage.payment_order_confirm_cancel', {}, 'Confirm cancel')}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={cancelPendingOrderId !== null}
                      onClick={() => setCancelConfirmOrderId(null)}
                    >
                      {t('common.back', {}, 'Back')}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn btn-outline text-red-700 dark:text-red-300"
                    disabled={cancelPendingOrderId !== null}
                    onClick={() => setCancelConfirmOrderId(order.order_id)}
                  >
                    {t('portal.usage.payment_order_cancel', {}, 'Cancel')}
                  </button>
                )
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );

  const paymentOrderTabs: Array<{
    id: PortalPaymentOrderStatusGroup;
    label: string;
  }> = [
    { id: 'all', label: t('portal.usage.payment_orders_tab_all', {}, 'All') },
    { id: 'pending', label: t('portal.usage.payment_orders_tab_pending', {}, 'Pending') },
    { id: 'paid', label: t('portal.usage.payment_orders_tab_paid', {}, 'Paid') },
    { id: 'closed', label: t('portal.usage.payment_orders_tab_closed', {}, 'Closed') },
  ];
  const paymentOrderTotal = Number(paymentOrders?.pagination?.total || 0);
  const paymentOrderPageEnd = Math.min(
    paymentOrderOffset + allPaymentOrders.length,
    paymentOrderTotal
  );
  const paymentOrdersCard = (
    <section className="overflow-hidden rounded-[1.25rem] border border-slate-200 bg-white/70 dark:border-slate-800 dark:bg-slate-950/35">
      <header className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <span>
          <span className="block text-sm font-semibold text-gray-950 dark:text-white">
            {t('portal.usage.payment_orders_title', {}, 'Payment orders')}
          </span>
          <span className="mt-1 block text-sm text-gray-600 dark:text-gray-400">
            {Number(paymentOrderCounts.all || 0) > 0
              ? t(
                  'portal.usage.payment_orders_summary',
                  {
                    pending: String(paymentOrderCounts.pending || 0),
                    paid: String(paymentOrderCounts.paid || 0),
                    closed: String(paymentOrderCounts.closed || 0),
                  },
                  `${paymentOrderCounts.pending || 0} pending · ${paymentOrderCounts.paid || 0} paid · ${paymentOrderCounts.closed || 0} closed`
                )
              : t('portal.usage.payment_orders_empty', {}, 'No payment orders yet.')}
          </span>
        </span>
      </header>
      <div className="border-t border-slate-200 px-5 pb-5 pt-4 dark:border-slate-800">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {t(
            'portal.usage.payment_orders_desc',
            {},
            'Payment results follow verified Alipay notifications. Unpaid orders close after 30 minutes; canceled orders remain visible here for 7 days.'
          )}
        </p>
        <div
          role="tablist"
          aria-label={t('portal.usage.payment_orders_filter_label', {}, 'Filter payment orders')}
          className="mt-4 inline-flex max-w-full gap-1 overflow-x-auto rounded-[0.875rem] bg-slate-100 p-1 dark:bg-slate-900"
        >
          {paymentOrderTabs.map((tab) => {
            const selected = tab.id === paymentOrderStatusGroup;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                className={`whitespace-nowrap rounded-[0.625rem] px-3 py-2 text-sm font-medium transition-colors ${
                  selected
                    ? 'bg-white text-blue-700 shadow-sm dark:bg-slate-800 dark:text-blue-300'
                    : 'text-slate-600 hover:text-slate-950 dark:text-slate-400 dark:hover:text-white'
                }`}
                onClick={() => {
                  setPaymentOrderStatusGroup(tab.id);
                  setPaymentOrderOffset(0);
                  setCancelConfirmOrderId(null);
                }}
              >
                {tab.label} <span className="tabular-nums">{paymentOrderCounts[tab.id] || 0}</span>
              </button>
            );
          })}
        </div>
        {paymentOrderError ? (
          <p className="mt-3 text-sm text-red-700 dark:text-red-300">{paymentOrderError}</p>
        ) : null}
        <div className="mt-4" role="tabpanel">
          {paymentOrdersLoading && allPaymentOrders.length === 0 ? (
            <p className="rounded-[1rem] border border-slate-200 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
              {t('portal.usage.payment_orders_loading', {}, 'Loading payment orders...')}
            </p>
          ) : allPaymentOrders.length > 0 ? (
            renderPaymentOrderList(allPaymentOrders)
          ) : (
            <p className="rounded-[1rem] border border-slate-200 px-4 py-6 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
              {t('portal.usage.payment_orders_filter_empty', {}, 'No orders in this status.')}
            </p>
          )}
        </div>
        {paymentOrderTotal > PAYMENT_ORDER_PAGE_SIZE ? (
          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t(
                'portal.usage.payment_orders_page_summary',
                {
                  start: String(paymentOrderTotal > 0 ? paymentOrderOffset + 1 : 0),
                  end: String(paymentOrderPageEnd),
                  total: String(paymentOrderTotal),
                },
                `${paymentOrderOffset + 1}-${paymentOrderPageEnd} of ${paymentOrderTotal}`
              )}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={paymentOrderOffset === 0 || paymentOrdersLoading}
                onClick={() => setPaymentOrderOffset(Math.max(0, paymentOrderOffset - PAYMENT_ORDER_PAGE_SIZE))}
              >
                {t('common.previous', {}, 'Previous')}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={!paymentOrders?.pagination?.has_more || paymentOrdersLoading}
                onClick={() => setPaymentOrderOffset(paymentOrderOffset + PAYMENT_ORDER_PAGE_SIZE)}
              >
                {t('common.next', {}, 'Next')}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
  const supportRequestHref = '/portal/support?new=1&topic=billing';

  if (isLoading) {
    return <PortalLoadingState message={t('portal.billing.loading', {}, 'Loading package details...')} />;
  }

  const snapshotPlanVersionId =
    currentSubscription?.plan_version_id || '';
  const packageDisplay = resolveCustomerPackageDisplay(t, {
    planId: currentSubscription?.plan_id,
    planVersionId: snapshotPlanVersionId,
    packageAlias: currentSubscription?.package_alias,
    planKind: currentSubscription?.plan_kind,
    coverageState: currentSubscription ? 'covered' : 'uncovered',
  });
  const packageLabel = packageDisplay.display_package_label || t('portal.home.package_pending_label', {}, 'To confirm');
  const quotaSummary = entitlements?.quota_summary || null;
  const currentPeriodStart =
    entitlements?.period_start_at ||
    currentSubscription?.current_period_start ||
    '';
  const currentPeriodEnd =
    entitlements?.period_end_at ||
    currentSubscription?.current_period_end ||
    '';
  const currentPeriodLabel =
    currentPeriodStart && currentPeriodEnd
      ? `${formatDate(currentPeriodStart)} - ${formatDate(currentPeriodEnd)}`
      : t('portal.home.package_pending_label', {}, 'To confirm');
  const availableCreditPacks = creditPacks?.items || [];
  const packageStatus =
    String(quotaSummary?.status || '') === 'limited'
      ? 'warning'
      : 'ok';
  const packageStatusLabel =
    packageStatus === 'warning'
      ? t('common.attention', {}, 'Attention')
      : t('common.ok', {}, 'OK');

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.workspace_label', {}, 'Portal')}
        title={t('portal.billing.customer_title', {}, 'Package')}
        description={t('portal.billing.subtitle', {}, 'Confirm the current package, included rights, and upgrade options.')}
        currentPage="billing"
        actions={
          <Link href={supportRequestHref} className="btn btn-secondary">
            {t('portal.support_request_new_action', {}, 'Submit ticket')}
          </Link>
        }
      />

      {paymentReturnNotice}

      {paymentLaunchNotice}

      {error ? (
        <PortalErrorState
          title={t('error.failed_load', {}, 'Failed to load')}
          description={error}
          retryLabel={t('common.retry', {}, 'Retry')}
          onRetry={() => void loadBilling()}
        />
      ) : null}

      <BackofficeMetricStrip
        items={[
          { label: t('portal.current_subscription_label', {}, 'Current package'), value: packageLabel },
          {
            label: t('common.status'),
            value: packageStatusLabel,
            detail: t('portal.billing.package_status_detail', {}, 'Use this page to handle package or point needs.'),
            size: 'compact',
          },
          {
            label: t('portal.usage.period_label', {}, 'Period'),
            value: currentPeriodLabel,
            size: 'compact',
          },
        ]}
        columnsClassName="lg:grid-cols-3"
        variant="portal"
      />

      <div id="package-options" className="scroll-mt-24">
        {packageActions}
      </div>

      <BackofficeStackCard variant="portal" className="bg-white/70 dark:bg-slate-950/35">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1">
            <PortalEntitlementUsage
              quotaSummary={quotaSummary}
              periodLabel={currentPeriodLabel}
              t={t}
            />
          </div>
          <div className="flex flex-col gap-2 sm:flex-row lg:flex-col">
            <Link href="#package-options" className="btn btn-primary">
              {t('portal.billing.upgrade_action', {}, 'Upgrade package')}
            </Link>
          </div>
        </div>
      </BackofficeStackCard>

      {availableCreditPacks.length > 0 ? (
        <BackofficeStackCard variant="portal" className="bg-white/70 dark:bg-slate-950/35">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-950 dark:text-white">
                {t('portal.usage.credit_packs_title', {}, 'Credit packs')}
              </p>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                {t(
                  'portal.usage.credit_packs_desc',
                  {},
                  'Add points without changing your plan. Purchased credits are valid for one year after payment.'
                )}
              </p>
            </div>
            <BackofficeStatusBadge
              status="warning"
              label={t('portal.usage.credit_packs_period_badge', {}, 'One-year validity')}
            />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {availableCreditPacks.map((pack) => {
              return (
                <div
                  key={pack.pack_id}
                  className="rounded-[1rem] border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/35"
                >
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">
                    {t(`portal.usage.credit_pack_${pack.pack_id}`, {}, pack.label)}
                  </p>
                  <p className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                    {formatQuotaValue(pack.ai_credits)}
                  </p>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {formatPortalCurrency(Number(pack.amount || 0), {
                      from: normalizePortalCurrency(pack.currency),
                      to: DEFAULT_PORTAL_CURRENCY,
                    })}
                  </p>
                  <button
                    type="button"
                    className="btn btn-secondary mt-4 w-full"
                    disabled={creditPackPending !== null}
                    onClick={() => void handleCreateCreditPackOrder(pack.pack_id)}
                  >
                    {creditPackPending === pack.pack_id
                      ? t('common.saving', {}, 'Saving...')
                      : t('portal.usage.credit_pack_buy_action', {}, 'Buy credits')}
                  </button>
                </div>
              );
            })}
          </div>
          {creditPackError ? (
            <div className="mt-4 rounded-[1rem] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-200">
              {creditPackError}
            </div>
          ) : null}
        </BackofficeStackCard>
      ) : null}

      {paymentOrdersCard}
    </BackofficePageStack>
  );
}

export default function PortalBillingPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalBillingContent />
    </Suspense>
  );
}
