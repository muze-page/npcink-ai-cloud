'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ListPagination } from '@/components/ui/ListPagination';
import { useLocale } from '@/contexts/LocaleContext';
import { formatAdminCurrency } from '@/lib/currency';
import { resolveAdminPackageLabel } from '@/lib/admin-plan-copy';
import { readResponsePayload } from '@/lib/safe-response';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';

interface Subscription {
  subscription_id: string;
  account_id: string;
  account_name?: string;
  site_count: number;
  covered_sites: Array<{
    site_id: string;
    name: string;
  }>;
  status: string;
  plan_id: string;
  plan_version_id: string;
  package_alias?: string;
  current_period_start: string;
  current_period_end: string;
  grace_state?: string;
  billing_summary?: {
    total_cost: number;
    latest_snapshot_id?: string;
  };
  billing_snapshot_status?: {
    status: string;
    summary?: string;
    fresh_site_count: number;
    stale_site_count: number;
    missing_site_count: number;
  };
}

interface SubscriptionApiItem {
  subscription?: {
    subscription_id?: string;
    account_id?: string;
    status?: string;
    plan_id?: string;
    plan_version_id?: string;
    current_period_start_at?: string;
    current_period_end_at?: string;
  };
  account?: {
    account_id?: string;
    name?: string;
  };
  covered_sites?: Array<{
    site_id?: string;
    name?: string;
  }>;
  coverage?: {
    site_count?: number;
    package_alias?: string;
  };
  expiry?: {
    current_period_end_at?: string;
  };
  latest_billing_snapshots?: Array<{
    totals?: {
      cost?: number;
    };
    snapshot_id?: string;
  }>;
  billing_snapshot_status?: {
    status?: string;
    summary?: string;
    fresh_site_count?: number;
    stale_site_count?: number;
    missing_site_count?: number;
  };
}

const PAGE_SIZE = 20;

function daysUntil(raw?: string): number | null {
  if (!raw) {
    return null;
  }
  const ms = new Date(raw).getTime() - Date.now();
  if (Number.isNaN(ms)) {
    return null;
  }
  return Math.ceil(ms / 86400000);
}

function normalizeSubscription(item: SubscriptionApiItem): Subscription {
  const subscription = item.subscription || {};
  const account = item.account || {};
  const sites = Array.isArray(item.covered_sites) ? item.covered_sites : [];
  const snapshots = Array.isArray(item.latest_billing_snapshots) ? item.latest_billing_snapshots : [];

  return {
    subscription_id: subscription.subscription_id || '',
    account_id: subscription.account_id || account.account_id || '',
    account_name: account.name || '',
    site_count: Number(item.coverage?.site_count || sites.length || 0),
    covered_sites: sites.map((site) => ({
      site_id: String(site.site_id || ''),
      name: String(site.name || site.site_id || ''),
    })).filter((site) => site.site_id),
    status: subscription.status || 'unknown',
    plan_id: subscription.plan_id || '',
    plan_version_id: subscription.plan_version_id || '',
    package_alias: item.coverage?.package_alias || '',
    current_period_start: subscription.current_period_start_at || '',
    current_period_end: subscription.current_period_end_at || item.expiry?.current_period_end_at || '',
    billing_summary: {
      total_cost: snapshots.reduce((sum, snapshot) => sum + Number(snapshot.totals?.cost || 0), 0),
      latest_snapshot_id: snapshots[0]?.snapshot_id,
    },
    billing_snapshot_status: {
      status: item.billing_snapshot_status?.status || 'unknown',
      summary: item.billing_snapshot_status?.summary || '',
      fresh_site_count: Number(item.billing_snapshot_status?.fresh_site_count || 0),
      stale_site_count: Number(item.billing_snapshot_status?.stale_site_count || 0),
      missing_site_count: Number(item.billing_snapshot_status?.missing_site_count || 0),
    },
  };
}

function getSubscriptionPriority(item: Subscription): number {
  const remaining = daysUntil(item.current_period_end);
  if (item.status === 'past_due') {
    return 0;
  }
  if (item.status === 'expired') {
    return 1;
  }
  if (remaining !== null && remaining >= 0 && remaining <= 14) {
    return 2;
  }
  if (item.status === 'trialing') {
    return 3;
  }
  if (item.status === 'active') {
    return 4;
  }
  return 5;
}

function SubscriptionsContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    status: searchParams.get('status') || '',
    account_id: searchParams.get('account_id') || '',
    plan_id: searchParams.get('plan_id') || '',
    expires_before: searchParams.get('expires_before') || '',
  });

  useEffect(() => {
    const loadSubscriptions = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        if (filters.status) params.set('status', filters.status);
        if (filters.account_id) params.set('account_id', filters.account_id);
        if (filters.plan_id) params.set('plan_id', filters.plan_id);
        if (filters.expires_before) params.set('expires_before', filters.expires_before);
        params.set('limit', String(PAGE_SIZE));
        if (offset > 0) params.set('offset', String(offset));

        const response = await fetch(`/api/admin/subscriptions?${params.toString()}`, {
          credentials: 'include',
        });
        const data = await readResponsePayload<{ data?: { items?: SubscriptionApiItem[]; total?: number }; message?: string }>(response);
        if (!response.ok) {
          throw new Error(resolveUiErrorMessage('message' in data ? data.message : null, t('error.failed_load')));
        }
        const nextItems = ((('data' in data ? data.data?.items : []) || []) as SubscriptionApiItem[]).map(normalizeSubscription);
        setSubscriptions(nextItems);
        setTotal(('data' in data ? data.data?.total : 0) || nextItems.length);
      } catch (err) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadSubscriptions();
  }, [filters, offset, t]);

  const handleFilterChange = (key: string, value: string) => {
    setOffset(0);
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const queuedSubscriptions = useMemo(() => {
    return [...subscriptions].sort((left, right) => {
      const priorityDiff = getSubscriptionPriority(left) - getSubscriptionPriority(right);
      if (priorityDiff !== 0) {
        return priorityDiff;
      }
      const leftDays = daysUntil(left.current_period_end) ?? Number.POSITIVE_INFINITY;
      const rightDays = daysUntil(right.current_period_end) ?? Number.POSITIVE_INFINITY;
      return leftDays - rightDays;
    });
  }, [subscriptions]);

  if (isLoading) {
    return <LoadingFallback />;
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-red-600">{t('common.error')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{error}</p>
          <button onClick={() => window.location.reload()} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  const activeSubscriptions = subscriptions.filter((item) => item.status === 'active').length;
  const trialingSubscriptions = subscriptions.filter((item) => item.status === 'trialing').length;
  const pastDueSubscriptions = subscriptions.filter((item) => item.status === 'past_due').length;
  const expiredSubscriptions = subscriptions.filter((item) => item.status === 'expired').length;
  const expiringSoon = subscriptions.filter((item) => {
    const remaining = daysUntil(item.current_period_end);
    return remaining !== null && remaining >= 0 && remaining <= 14;
  }).length;
  const subscriptionsNeedingSnapshotFollowUp = subscriptions.filter((item) => {
    const status = item.billing_snapshot_status?.status || 'unknown';
    return status === 'stale' || status === 'missing';
  }).length;
  const serviceRiskCount = subscriptions.filter((item) => {
    const remaining = daysUntil(item.current_period_end);
    const snapshotStatus = item.billing_snapshot_status?.status || 'unknown';
    return (
      item.status === 'past_due' ||
      item.status === 'expired' ||
      snapshotStatus === 'stale' ||
      snapshotStatus === 'missing' ||
      (remaining !== null && remaining >= 0 && remaining <= 14)
    );
  }).length;
  const stableSubscriptions = subscriptions.filter((item) => {
    const remaining = daysUntil(item.current_period_end);
    return (
      item.status === 'active' &&
      item.billing_snapshot_status?.status === 'fresh' &&
      !(remaining !== null && remaining >= 0 && remaining <= 14)
    );
  }).length;
  const riskConclusion =
    pastDueSubscriptions > 0 || expiredSubscriptions > 0
      ? t(
          'admin.subscriptions.queue_status_error',
          { count: String(pastDueSubscriptions + expiredSubscriptions) },
          `${pastDueSubscriptions + expiredSubscriptions} customers may lose Cloud service. Handle past-due and expired coverage first.`
        )
      : expiringSoon > 0
        ? t(
            'admin.subscriptions.queue_status_warning',
            { count: String(expiringSoon) },
            `${expiringSoon} customers are approaching renewal. Review them before service continuity becomes support work.`
          )
        : t(
            'admin.subscriptions.queue_status_ok',
            { count: String(stableSubscriptions) },
            `${stableSubscriptions} customers look stable in this queue. Keep this page for service coverage checks and lower-priority follow-up.`
          );
  const filterPills = [
    { value: '', label: t('common.all'), count: total },
    { value: 'past_due', label: t('status.past_due') },
    { value: 'expired', label: t('status.expired') },
    { value: 'trialing', label: t('status.trialing') },
    { value: 'active', label: t('status.active') },
  ];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_coverage', {}, 'Service status')}
        title={t('admin.coverage_workspace_subscriptions_title', {}, 'Service risk queue')}
        description={riskConclusion}
        aside={(
          <div className="w-full xl:w-[44rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('admin.subscriptions.page_needs_action_metric', {}, 'Page needs action'), value: formatInteger(serviceRiskCount), size: 'compact' },
                { label: t('admin.subscriptions.page_expiring_metric', {}, 'Page expiring soon'), value: formatInteger(expiringSoon), size: 'compact' },
                {
                  label: t('admin.subscriptions.page_snapshot_status_metric', {}, 'Page billing stats to refresh'),
                  value: formatInteger(subscriptionsNeedingSnapshotFollowUp),
                  size: 'compact',
                },
                { label: t('admin.subscriptions.page_stable_metric', {}, 'Page service normal'), value: formatInteger(stableSubscriptions), size: 'compact' },
              ]}
              columnsClassName="md:grid-cols-2 xl:grid-cols-4"
            />
          </div>
        )}
      >
        <div className="flex flex-wrap gap-2">
          <Link href="/admin/coverage" className="btn btn-secondary btn-sm">
            {t('admin.back_to_coverage', {}, 'Back to coverage')}
          </Link>
          {filterPills.map((pill) => (
            <button
              key={pill.value || 'all'}
              type="button"
              onClick={() => handleFilterChange('status', pill.value)}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-medium transition',
                filters.status === pill.value
                  ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200'
                  : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white'
              )}
            >
              {pill.label}{typeof pill.count === 'number' ? ` · ${formatInteger(pill.count)}` : ''}
            </button>
          ))}
        </div>
      </BackofficePrimaryPanel>

      <BackofficeSectionPanel className="space-y-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.subscriptions.queue_label', {}, 'Queue filters')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.subscriptions.queue_title', {}, 'Filter the current service risk queue')}
            </h2>
          </div>
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {formatInteger(total)} {t('common.subscriptions')}
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.account')}</span>
            <input
              type="text"
              value={filters.account_id}
              onChange={(event) => handleFilterChange('account_id', event.target.value)}
              placeholder={t('common.account')}
              className="input w-full"
            />
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.plan')}</span>
            <input
              type="text"
              value={filters.plan_id}
              onChange={(event) => handleFilterChange('plan_id', event.target.value)}
              placeholder={t('common.plan')}
              className="input w-full"
            />
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.expires_before')}</span>
            <input
              type="date"
              value={filters.expires_before}
              onChange={(event) => handleFilterChange('expires_before', event.target.value)}
              className="input w-full"
            />
          </label>
        </div>
      </BackofficeSectionPanel>

      <BackofficeSectionPanel className="overflow-hidden p-0">
        <div className="border-b border-gray-200 px-5 py-5 dark:border-gray-800 md:px-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {t('admin.subscription_register_title')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
            {t('admin.subscriptions.queue_list_title', {}, 'Customers needing service follow-up')}
          </h2>
        </div>
        {queuedSubscriptions.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-gray-600 dark:text-gray-400">
            {t('common.subscriptions')} {t('common.not_found')}
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-800">
            {queuedSubscriptions.map((subscription) => {
              const remaining = daysUntil(subscription.current_period_end);
              const snapshotStatus = subscription.billing_snapshot_status?.status || 'unknown';
              const riskTone =
                subscription.status === 'past_due' || subscription.status === 'expired'
                  ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200'
                  : remaining !== null && remaining >= 0 && remaining <= 14
                    ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200'
                    : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/50 dark:bg-blue-950/20 dark:text-blue-200';
              const riskReason =
                subscription.status === 'past_due'
                  ? t('admin.subscriptions.reason_past_due', {}, 'Billing follow-up is already active and may affect service continuity.')
                  : subscription.status === 'expired'
                    ? t('admin.subscriptions.reason_expired', {}, 'The subscription has ended and needs a renewal or closure decision.')
                    : remaining !== null && remaining >= 0 && remaining <= 14
                      ? t('admin.subscriptions.reason_expiring', {}, 'Current period ends soon, so renewal or follow-up should happen before support load increases.')
                    : subscription.status === 'trialing'
                        ? t('admin.subscriptions.reason_trialing', {}, 'Trial coverage is still active and should be checked before converting or ending.')
                        : snapshotStatus === 'stale'
                          ? t('admin.subscriptions.reason_snapshot_stale', {}, 'This period billing statistics need refresh before the account is treated as reconciled.')
                          : snapshotStatus === 'missing'
                            ? t('admin.subscriptions.reason_snapshot_missing', {}, 'This period billing statistics are missing for at least one covered site.')
                            : t('admin.subscriptions.reason_active', {}, 'Service coverage is currently stable and remains here as lower-priority review context.');
              const suggestedAction =
                subscription.status === 'past_due'
                  ? t('admin.subscriptions.action_past_due', {}, 'Open customer and handle billing follow-up.')
                  : subscription.status === 'expired'
                    ? t('admin.subscriptions.action_expired', {}, 'Open customer and decide renewal or service closure.')
                    : remaining !== null && remaining >= 0 && remaining <= 14
                      ? t('admin.subscriptions.action_expiring', {}, 'Review renewal before service continuity becomes support work.')
                      : snapshotStatus === 'stale' || snapshotStatus === 'missing'
                        ? t('admin.subscriptions.action_snapshot', {}, 'Open service detail and refresh this period billing statistics.')
                        : subscription.status === 'trialing'
                          ? t('admin.subscriptions.action_trialing', {}, 'Review trial conversion or end date.')
                          : t('admin.subscriptions.action_active', {}, 'No immediate action. Keep as service coverage context.');
              const packageLabel = resolveAdminPackageLabel(t, {
                planId: subscription.plan_id,
                packageAlias: subscription.package_alias,
                fallback: subscription.package_alias || subscription.plan_id,
              }) || t('common.unknown');

              return (
                <article key={subscription.subscription_id} className="px-5 py-5 md:px-6">
                  <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_0.9fr_auto] xl:items-center">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-semibold text-gray-950 dark:text-white">
                          {subscription.account_name || packageLabel}
                        </h3>
                        <BackofficeStatusBadge
                          status={subscription.status}
                          label={t(`status.${subscription.status}`, undefined, subscription.status)}
                        />
                        <span className={cn('rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em]', riskTone)}>
                          {remaining !== null && remaining >= 0 && remaining <= 14
                            ? t('admin.expiring_soon')
                            : t('admin.subscriptions.queue_priority', {}, 'Review')}
                        </span>
                      </div>
                      <p className="mt-3 text-sm font-semibold text-gray-950 dark:text-white">
                        {packageLabel}
                      </p>
                      <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">{riskReason}</p>
                      <p className="mt-2 text-sm text-gray-700 dark:text-gray-200">
                        <span className="font-semibold">{t('admin.suggested_action', {}, 'Suggested action')}:</span>{' '}
                        {suggestedAction}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-gray-600 dark:text-gray-400">
                        <Link href={`/admin/accounts/${subscription.account_id}`} className="text-blue-600 hover:underline dark:text-blue-300">
                          {t('common.account', {}, 'Customer')}
                        </Link>
                        <span>
                          {t('common.sites', {}, 'Sites')}: {formatInteger(subscription.site_count)}
                        </span>
                      </div>
                      <details className="mt-3 text-xs text-gray-500 dark:text-gray-400">
                        <summary className="cursor-pointer font-medium hover:text-gray-800 dark:hover:text-gray-200">
                          {t('portal.support_information', {}, 'Support information')}
                        </summary>
                        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                          <BackofficeIdentifier value={subscription.subscription_id} />
                          <BackofficeIdentifier value={subscription.account_id} />
                        </div>
                      </details>
                      <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <span
                          className={cn(
                            'rounded-full border px-2.5 py-1 font-semibold uppercase tracking-[0.16em]',
                            subscription.billing_snapshot_status?.status === 'fresh'
                              ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200'
                              : subscription.billing_snapshot_status?.status === 'stale'
                                ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200'
                                : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200'
                          )}
                        >
                          {subscription.billing_snapshot_status?.status === 'fresh'
                            ? t('admin.subscriptions.snapshot_fresh_label', {}, 'Billing statistics current')
                            : subscription.billing_snapshot_status?.status === 'stale'
                              ? t('admin.subscriptions.snapshot_stale_label', {}, 'Billing statistics need refresh')
                              : t('admin.subscriptions.snapshot_missing_label', {}, 'Billing statistics missing')}
                        </span>
                        {subscription.billing_snapshot_status?.status !== 'fresh' ? (
                          <span className="text-gray-500 dark:text-gray-400">
                            {subscription.billing_snapshot_status?.summary ||
                              t(
                                'admin.subscriptions.snapshot_follow_up_required',
                                {},
                                'This period billing statistics need operator follow-up.'
                              )}
                          </span>
                        ) : null}
                      </div>
                    </div>

                    <div className="space-y-2 text-sm">
                      <div>
                        <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">
                          {t('admin.billing_period')}
                        </p>
                        <p className="mt-1 text-gray-700 dark:text-gray-300">{formatDate(subscription.current_period_end)}</p>
                        {remaining !== null ? (
                          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            {remaining >= 0
                              ? t('admin.days_until_end', { days: String(remaining) })
                              : t('admin.subscriptions.days_past_end', { days: String(Math.abs(remaining)) }, `${Math.abs(remaining)} days past end`)}
                          </p>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">
                          {t('admin.usage_cost')}
                        </p>
                        <p className="mt-1 font-semibold text-gray-950 dark:text-white">
                          {formatAdminCurrency(subscription.billing_summary?.total_cost || 0)}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-start gap-3 xl:justify-end">
                      <Link href={`/admin/accounts/${subscription.account_id}`} className="btn btn-secondary">
                        {t('common.account', {}, 'Customer')}
                      </Link>
                      {subscription.covered_sites[0]?.site_id ? (
                        <Link href={`/admin/sites/${subscription.covered_sites[0].site_id}`} className="btn btn-secondary">
                          {subscription.site_count > 1
                            ? t('admin.open_covered_sites', {}, 'Open covered sites')
                            : t('admin.open_site')}
                        </Link>
                      ) : null}
                      <Link
                        href={`/admin/subscriptions/${subscription.subscription_id}`}
                        className="text-xs font-medium text-gray-500 underline decoration-dotted underline-offset-4 transition hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
                      >
                        {t('admin.coverage_open_subscription_detail_action', {}, 'Inspect detail')} →
                      </Link>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
        <ListPagination
          offset={offset}
          limit={PAGE_SIZE}
          total={total}
          isLoading={isLoading}
          onOffsetChange={setOffset}
        />
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function AdminSubscriptionsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <SubscriptionsContent />
    </Suspense>
  );
}
