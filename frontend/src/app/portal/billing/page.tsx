'use client';

import React, { Suspense, useCallback, useEffect, useState } from 'react';
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
  type PortalCreditPackPaymentOrder,
  type PortalPaymentOrder,
  type PortalPaymentOrderListPayload,
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
    return tier ? `${tier.charAt(0).toUpperCase()}${tier.slice(1)} monthly package` : rawTitle;
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
  const [creditPackOrder, setCreditPackOrder] = useState<PortalCreditPackPaymentOrder | null>(null);
  const [creditPackPending, setCreditPackPending] = useState<string | null>(null);
  const [creditPackError, setCreditPackError] = useState<string | null>(null);
  const [packageOrder, setPackageOrder] = useState<PortalPaymentOrder | null>(null);
  const [packagePending, setPackagePending] = useState<string | null>(null);
  const [packageError, setPackageError] = useState<string | null>(null);
  const [cancelPendingOrderId, setCancelPendingOrderId] = useState<string | null>(null);
  const [cancelConfirmOrderId, setCancelConfirmOrderId] = useState<string | null>(null);
  const [paymentOrderError, setPaymentOrderError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBilling = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const bundle = await portalClient.getAccountCommercialBundle();
      setEntitlements(bundle.entitlements);
      setCreditPacks(bundle.creditPacks);
      setPaymentOrders(bundle.paymentOrders);
      setPlanOffers(bundle.planOffers || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error.failed_load', {}, 'Failed to load.'));
      setEntitlements(null);
      setCreditPacks(null);
      setPaymentOrders(null);
      setPlanOffers(null);
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (!isAuthenticated || !session?.account_id) {
      setIsLoading(false);
      return;
    }
    void loadBilling();
  }, [isAuthenticated, loadBilling, session?.account_id]);

  const handleStartPlanTrial = async (tierId: 'plus' | 'pro') => {
    setPackagePending(`trial:${tierId}`);
    setPackageError(null);
    setPackageOrder(null);
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
    setPackagePending(`order:${offer.tier_id}`);
    setPackageError(null);
    setPackageOrder(null);
    try {
      const response = await portalClient.createSubscriptionOrder(offer.offer_id, 'alipay');
      setPackageOrder(response.data.order);
      setPaymentOrders((current) => ({
        ...(current || { items: [] }),
        items: [
          response.data.order,
          ...(current?.items || []).filter((item) => item.order_id !== response.data.order.order_id),
        ].slice(0, 8),
      }));
      if (response.data.order.checkout_url) {
        window.location.assign(response.data.order.checkout_url);
      }
    } catch (err) {
      setPackageError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setPackagePending(null);
    }
  };

  const handleScheduleFreeDowngrade = async () => {
    setPackagePending('downgrade:free');
    setPackageError(null);
    setPackageOrder(null);
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
      await loadBilling();
    } catch (err) {
      setPaymentOrderError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setCancelPendingOrderId(null);
    }
  };

  const handleCreateCreditPackOrder = async (packId: string) => {
    setCreditPackPending(packId);
    setCreditPackError(null);
    setCreditPackOrder(null);
    try {
      const response = await portalClient.createAccountCreditPackOrder(packId);
      setCreditPackOrder(response.data.order);
      setPaymentOrders((current) => ({
        ...(current || { items: [] }),
        items: [
          response.data.order,
          ...(current?.items || []).filter((item) => item.order_id !== response.data.order.order_id),
        ].slice(0, 8),
      }));
      if (response.data.order.checkout_url) {
        window.location.assign(response.data.order.checkout_url);
      }
    } catch (err) {
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
  const canTrialTier = (tierId: 'plus' | 'pro') => {
    const offer = offersByTier.get(tierId);
    return Boolean(
      offer?.trial_enabled
      && (planOffers?.trial?.available !== false || planOffers?.trial?.status === 'active')
      && currentStatus !== 'active'
      && tierRank[tierId] > currentRank
    );
  };
  const canBuyTier = (tierId: 'plus' | 'pro' | 'agency') =>
    Boolean(offersByTier.get(tierId));
  const paymentReturnProvider = String(searchParams.get('payment_return') || '').toLowerCase();
  const paymentReturnOrder = String(searchParams.get('out_trade_no') || '').trim();
  const paymentReturnStatus = String(searchParams.get('trade_status') || '').trim();
  const hasAlipayReturn = paymentReturnProvider === 'alipay';
  const allPaymentOrders = paymentOrders?.items || [];
  const pendingPaymentOrders = allPaymentOrders.filter(isPendingPaymentOrder);
  const recentPaymentOrders = allPaymentOrders.filter((order) => !isPendingPaymentOrder(order));

  const handleRefreshPaymentReturn = async () => {
    await refresh();
    await loadBilling();
  };

  const paymentReturnNotice = hasAlipayReturn ? (
    <BackofficeStackCard variant="portal" className="border-blue-200 bg-blue-50/70 dark:border-blue-900/60 dark:bg-blue-950/20">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.package.alipay_return_title', {}, 'Payment confirmation is pending')}
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t(
              'portal.package.alipay_return_desc',
              {},
              'You have returned from Alipay. The final package status is updated after the verified Alipay notification reaches Cloud.'
            )}
          </p>
          {paymentReturnOrder || paymentReturnStatus ? (
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {[
                paymentReturnOrder
                  ? t('portal.package.alipay_return_order', { order: paymentReturnOrder }, `Order ${paymentReturnOrder}`)
                  : '',
                paymentReturnStatus
                  ? t('portal.package.alipay_return_status', { status: paymentReturnStatus }, `Alipay status ${paymentReturnStatus}`)
                  : '',
              ].filter(Boolean).join(' · ')}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          className="btn btn-secondary shrink-0"
          onClick={() => void handleRefreshPaymentReturn()}
        >
          {t('common.refresh', {}, 'Refresh')}
        </button>
      </div>
    </BackofficeStackCard>
  ) : null;

  const packageActions = (
    <BackofficeStackCard variant="portal" className="bg-white/70 dark:bg-slate-950/35">
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
            {t('portal.package.plus_desc', {}, 'CNY 15 for 30 days, with one shared 14-day paid-package trial.')}
          </p>
          <BackofficeStatusBadge
            status={currentPlanId === 'plus' ? 'ok' : 'neutral'}
            label={currentPlanId === 'plus' ? t('common.current', {}, 'Current') : t('common.available', {}, 'Available')}
          />
          <div className="mt-4 flex flex-col gap-2">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!canTrialTier('plus') || packagePending !== null}
              onClick={() => void handleStartPlanTrial('plus')}
            >
              {packagePending === 'trial:plus'
                ? t('common.saving', {}, 'Saving...')
                : t('portal.package.start_plus_trial', {}, 'Start 14-day trial')}
            </button>
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
            {t('portal.package.pro_desc', {}, 'Start with a 14-day trial, then continue for CNY 29 per month through Alipay.')}
          </p>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!canTrialTier('pro') || packagePending !== null}
              onClick={() => void handleStartPlanTrial('pro')}
            >
              {packagePending === 'trial:pro'
                ? t('common.saving', {}, 'Saving...')
                : t('portal.package.start_pro_trial', {}, 'Start 14-day trial')}
            </button>
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
      {packageOrder ? (
        <div className="mt-4 rounded-[1rem] border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200">
          {t(
            'portal.package.pro_order_created',
            { order: packageOrder.order_id },
            `Package payment order ${packageOrder.order_id} has been created.`
          )}
        </div>
      ) : null}
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
        return (
          <div
            key={order.order_id}
            data-payment-order-id={order.order_id}
            className="grid gap-4 px-4 py-4 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center"
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
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {resolvePaymentOrderDetail(order, t)}
              </p>
              <p
                className="mt-2 text-xs font-medium text-slate-500 dark:text-slate-400"
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
                {isPendingPaymentOrder(order) && order.expires_at
                  ? t(
                      'portal.usage.payment_order_expires_at',
                      { time: formatDate(order.expires_at) },
                      `Expires ${formatDate(order.expires_at)}`
                    )
                  : order.created_at ? formatDate(order.created_at) : order.order_id}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 md:min-w-48 md:justify-end">
              {paymentOrderAllowsAction(order, 'continue_payment') && order.checkout_url ? (
                <a className="btn btn-primary" href={order.checkout_url}>
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

  const paymentOrdersCard = (
    <section className="overflow-hidden rounded-[1.25rem] border border-slate-200 bg-white/70 dark:border-slate-800 dark:bg-slate-950/35">
      <header className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <span>
          <span className="block text-sm font-semibold text-gray-950 dark:text-white">
            {t('portal.usage.payment_orders_title', {}, 'Payment orders')}
          </span>
          <span className="mt-1 block text-sm text-gray-600 dark:text-gray-400">
            {allPaymentOrders.length > 0
              ? t(
                  'portal.usage.payment_orders_summary',
                  {
                    pending: String(pendingPaymentOrders.length),
                    recent: String(recentPaymentOrders.length),
                  },
                  `${pendingPaymentOrders.length} pending · ${recentPaymentOrders.length} recent`
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
            'Payment results follow verified Alipay notifications. Unpaid orders close automatically after 30 minutes.'
          )}
        </p>
        {paymentOrderError ? (
          <p className="mt-3 text-sm text-red-700 dark:text-red-300">{paymentOrderError}</p>
        ) : null}
        {pendingPaymentOrders.length > 0 ? (
          <div className="mt-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
              {t(
                'portal.usage.payment_orders_pending_title',
                { count: String(pendingPaymentOrders.length) },
                `Pending payment (${pendingPaymentOrders.length})`
              )}
            </h3>
            {renderPaymentOrderList(pendingPaymentOrders)}
          </div>
        ) : null}
        {recentPaymentOrders.length > 0 ? (
          <div className="mt-5">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
              {t(
                'portal.usage.payment_orders_recent_title',
                { count: String(recentPaymentOrders.length) },
                `Recent records (${recentPaymentOrders.length})`
              )}
            </h3>
            {renderPaymentOrderList(recentPaymentOrders)}
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

      {packageActions}

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
            <Link href="/portal/account" className="btn btn-primary">
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
          {creditPackOrder ? (
            <div className="mt-4 rounded-[1rem] border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200">
              {t(
                'portal.usage.credit_pack_order_created',
                { order: creditPackOrder.order_id },
                `Payment order ${creditPackOrder.order_id} has been created.`
              )}
            </div>
          ) : null}
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
