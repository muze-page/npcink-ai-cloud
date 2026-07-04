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
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type Entitlements,
  type PortalBillingReconciliation,
  type PortalBillingSnapshot,
  type PortalCreditPackCatalogPayload,
  type PortalCreditPackPaymentOrder,
  type PortalPaymentOrderListPayload,
} from '@/lib/portal-client';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import { DEFAULT_PORTAL_CURRENCY, formatPortalCurrency, normalizePortalCurrency } from '@/lib/currency';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatCompactNumber, formatDate, formatNumber } from '@/lib/utils';

function coerceFiniteNumber(value: unknown): number {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatQuotaValue(value: unknown, unlimited = false, unlimitedLabel = 'Unlimited'): string {
  if (unlimited) return unlimitedLabel;
  return formatNumber(Math.round(Number(value || 0)));
}

function PortalBillingContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { sites, selectedSiteId, selectedSite, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });
  const [snapshots, setSnapshots] = useState<PortalBillingSnapshot[]>([]);
  const [reconciliation, setReconciliation] = useState<PortalBillingReconciliation | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [creditPacks, setCreditPacks] = useState<PortalCreditPackCatalogPayload | null>(null);
  const [paymentOrders, setPaymentOrders] = useState<PortalPaymentOrderListPayload | null>(null);
  const [creditPackOrder, setCreditPackOrder] = useState<PortalCreditPackPaymentOrder | null>(null);
  const [creditPackPending, setCreditPackPending] = useState<string | null>(null);
  const [creditPackError, setCreditPackError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBilling = useCallback(async (siteId: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const [billingBundle, usageBundle] = await Promise.all([
        portalClient.getBillingBundle(siteId),
        portalClient.getUsageBundle(siteId),
      ]);
      setSnapshots(billingBundle.snapshots);
      setReconciliation(billingBundle.reconciliation);
      setEntitlements(usageBundle.entitlements);
      setCreditPacks(usageBundle.creditPacks);
      setPaymentOrders(usageBundle.paymentOrders);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error.failed_load', {}, 'Failed to load.'));
      setSnapshots([]);
      setReconciliation(null);
      setEntitlements(null);
      setCreditPacks(null);
      setPaymentOrders(null);
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (!selectedSiteId) {
      setIsLoading(false);
      return;
    }
    void loadBilling(selectedSiteId);
  }, [loadBilling, selectedSiteId]);

  const handleSiteChange = async (siteId: string) => {
    await setSelectedSiteId(siteId);
    setCreditPackOrder(null);
    setCreditPackError(null);
  };

  const handleCreateCreditPackOrder = async (packId: string) => {
    if (!selectedSiteId) return;
    setCreditPackPending(packId);
    setCreditPackError(null);
    setCreditPackOrder(null);
    try {
      const response = await portalClient.createCreditPackOrder(selectedSiteId, packId);
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

  if (!sites.length || !selectedSiteId || !selectedSite) {
    return (
      <PortalEmptyState
        title={t('portal.empty_no_site_title', {}, 'No site available')}
        description={t('portal.empty_no_site_desc', {}, 'Ask an operator to provision a site before using Cloud billing detail.')}
      />
    );
  }

  if (isLoading) {
    return <PortalLoadingState message={t('portal.billing.loading', {}, 'Loading billing snapshots...')} />;
  }

  const currency = normalizePortalCurrency(snapshots[0]?.currency || DEFAULT_PORTAL_CURRENCY);
  const latestSnapshot = snapshots[0] || null;
  const syncState = reconciliation?.reconciliation?.in_sync;
  const currentSubscription = session.current_subscription || null;
  const snapshotPlanVersionId =
    latestSnapshot?.plan_version_id || currentSubscription?.plan_version_id || '';
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
  const recentPaymentOrders = paymentOrders?.items || [];
  const packageStatus =
    String(quotaSummary?.status || '') === 'limited'
      ? 'warning'
      : syncState === false
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
        sites={sites}
        selectedSiteId={selectedSiteId}
        onSiteChange={handleSiteChange}
      />

      {error ? (
        <PortalErrorState
          title={t('error.failed_load', {}, 'Failed to load')}
          description={error}
          retryLabel={t('common.retry', {}, 'Retry')}
          onRetry={() => void loadBilling(selectedSiteId)}
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
            <Link href={`/portal/account?site=${selectedSiteId}`} className="btn btn-primary">
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
                  'Add points to the current package period without changing your plan.'
                )}
              </p>
            </div>
            <BackofficeStatusBadge
              status="warning"
              label={t('portal.usage.credit_packs_period_badge', {}, 'Current period')}
            />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {availableCreditPacks.map((pack) => (
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
            ))}
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

      <BackofficeStackCard variant="portal" className="bg-white/70 dark:bg-slate-950/35">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-gray-950 dark:text-white">
              {t('portal.usage.payment_orders_title', {}, 'Recent payment orders')}
            </p>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t(
                'portal.usage.payment_orders_desc',
                {},
                'Credit pack orders wait for Alipay or WeChat Pay confirmation before credits are granted.'
              )}
            </p>
          </div>
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
            {t('portal.usage.payment_orders_provider_note', {}, 'Alipay / WeChat Pay ready')}
          </p>
        </div>
        {recentPaymentOrders.length > 0 ? (
          <div className="mt-4 divide-y divide-slate-200 rounded-[1rem] border border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-800">
            {recentPaymentOrders.map((order) => (
              <div
                key={order.order_id}
                className="grid grid-cols-1 gap-3 px-4 py-3 sm:grid-cols-[1fr_0.7fr_0.8fr]"
              >
                <div>
                  <p className="font-medium text-slate-950 dark:text-white">
                    {order.credit_pack?.label || order.subject || order.order_id}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {order.status_detail?.detail ||
                      t('portal.usage.payment_order_default_detail', {}, 'Payment status is recorded by Cloud.')}
                  </p>
                </div>
                <div>
                  <BackofficeStatusBadge
                    label={order.status_detail?.label || order.status || 'pending'}
                    status={order.status || 'pending'}
                  />
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    {order.status_detail?.label || order.status}
                  </p>
                </div>
                <div className="sm:text-right">
                  <p className="font-semibold text-slate-950 dark:text-white">
                    {formatPortalCurrency(Number(order.amount || 0), {
                      from: normalizePortalCurrency(order.currency),
                      to: DEFAULT_PORTAL_CURRENCY,
                    })}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {order.created_at ? formatDate(order.created_at) : order.order_id}
                  </p>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-4 rounded-[1rem] border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
            {t('portal.usage.payment_orders_empty', {}, 'No payment orders for this site yet.')}
          </div>
        )}
      </BackofficeStackCard>

      <BackofficeStackCard variant="portal" className="bg-white/70 dark:bg-slate-950/35">
        <p className="text-sm font-semibold text-gray-950 dark:text-white">
          {t('portal.billing.help_title', {}, 'Need help?')}
        </p>
        <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
          {t(
            'portal.billing.help_desc',
            {},
            'If the package or record status looks wrong, contact support with your account email. Technical record IDs are hidden below unless support asks for them.'
          )}
        </p>
      </BackofficeStackCard>

      <details className="overflow-hidden rounded-[1.4rem] border border-gray-200 bg-white dark:border-gray-800 dark:bg-slate-950">
        <summary className="cursor-pointer px-5 py-4 text-sm font-semibold text-gray-950 hover:bg-gray-50 dark:text-white dark:hover:bg-slate-900">
          {t('portal.billing.records_title', {}, 'Support record details')}
        </summary>
        <div className="grid gap-4 border-t border-gray-200 p-4 dark:border-gray-800 lg:grid-cols-2">
          {snapshots.map((snapshot) => (
            <BackofficeStackCard key={`record-${snapshot.snapshot_id}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
	                  <p className="text-sm font-semibold text-gray-950 dark:text-white">
	                    {t('portal.billing.record_title', {}, 'Package record')}
	                  </p>
	                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
	                    {t('portal.billing.record_support_hint', {}, 'Support can look up the technical record if needed.')}
	                  </p>
                </div>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {formatDate(snapshot.generated_at)}
                </span>
              </div>
              <BackofficeMetricStrip
                items={[
	                  {
	                    label: t('portal.usage.package_service_uses_label', {}, 'Service uses'),
	                    value: formatNumber(coerceFiniteNumber(snapshot.totals?.runs)),
	                  },
	                  {
	                    label: t('portal.usage.breakdown_tokens', {}, 'Point usage'),
	                    value: formatCompactNumber(coerceFiniteNumber(snapshot.totals?.tokens_total)),
	                  },
	                  {
	                    label: t('portal.usage.package_budget_label', {}, 'Budget'),
	                    value: formatPortalCurrency(coerceFiniteNumber(snapshot.totals?.cost), { to: currency }),
	                  },
                ]}
              />
            </BackofficeStackCard>
          ))}
          {!snapshots.length ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {t('portal.billing.records_empty', {}, 'No records')}
            </p>
          ) : null}
        </div>
      </details>

      {!snapshots.length ? (
        <PortalEmptyState
          title={t('portal.billing.empty_title', {}, 'No package records yet')}
          description={t('portal.billing.empty_desc', {}, 'Package records will appear after support finishes the first service cycle.')}
        />
      ) : null}
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
