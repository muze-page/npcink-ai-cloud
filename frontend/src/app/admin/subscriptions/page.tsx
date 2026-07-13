'use client';

import React, { FormEvent, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeEmptyState,
  BackofficeLayer,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ListPagination } from '@/components/ui/ListPagination';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveAdminPackageLabel } from '@/lib/admin-plan-copy';
import { formatAdminCurrency } from '@/lib/currency';
import { resolveUiErrorMessage } from '@/lib/errors';
import { readResponsePayload } from '@/lib/safe-response';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';

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

type QueueSort = 'priority' | 'expiry' | 'customer';
type RiskLevel = 'critical' | 'warning' | 'monitor' | 'stable';

const PAGE_SIZE = 20;
const ALLOWED_STATUSES = new Set(['', 'past_due', 'expired', 'trialing', 'active', 'suspended', 'canceled']);
const ALLOWED_SORTS = new Set<QueueSort>(['priority', 'expiry', 'customer']);

function daysUntil(raw?: string): number | null {
  if (!raw) return null;
  const ms = new Date(raw).getTime() - Date.now();
  if (Number.isNaN(ms)) return null;
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
    covered_sites: sites
      .map((site) => ({
        site_id: String(site.site_id || ''),
        name: String(site.name || site.site_id || ''),
      }))
      .filter((site) => site.site_id),
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

function normalizeStatus(value: string | null): string {
  return value && ALLOWED_STATUSES.has(value) ? value : '';
}

function normalizeSort(value: string | null): QueueSort {
  return value && ALLOWED_SORTS.has(value as QueueSort) ? (value as QueueSort) : 'priority';
}

function normalizeOffset(value: string | null): number {
  const parsed = Number(value || 0);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

function subscriptionRiskLevel(item: Subscription): RiskLevel {
  const remaining = daysUntil(item.current_period_end);
  const snapshotStatus = item.billing_snapshot_status?.status || 'unknown';
  if (item.status === 'past_due' || item.status === 'expired' || item.status === 'suspended') {
    return 'critical';
  }
  if (
    snapshotStatus === 'stale' ||
    snapshotStatus === 'missing' ||
    (remaining !== null && remaining >= 0 && remaining <= 14)
  ) {
    return 'warning';
  }
  if (item.status === 'trialing' || item.status === 'canceled' || snapshotStatus === 'unknown') {
    return 'monitor';
  }
  return 'stable';
}

function subscriptionPriority(item: Subscription): number {
  const riskRank: Record<RiskLevel, number> = { critical: 0, warning: 1, monitor: 2, stable: 3 };
  const remaining = daysUntil(item.current_period_end) ?? Number.MAX_SAFE_INTEGER;
  return riskRank[subscriptionRiskLevel(item)] * 100000 + remaining;
}

function riskToneClassName(level: RiskLevel): string {
  if (level === 'critical') {
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200';
  }
  if (level === 'warning') {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200';
  }
  if (level === 'stable') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200';
  }
  return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/25 dark:text-blue-200';
}

function SubscriptionsContent() {
  const { t } = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const appliedStatus = normalizeStatus(searchParams.get('status'));
  const appliedAccountId = searchParams.get('account_id') || '';
  const appliedPlanId = searchParams.get('plan_id') || '';
  const appliedExpiresBefore = searchParams.get('expires_before') || '';
  const sort = normalizeSort(searchParams.get('sort'));
  const offset = normalizeOffset(searchParams.get('offset'));
  const focusedSubscriptionId = searchParams.get('focus') || '';

  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const [loadedRequestKey, setLoadedRequestKey] = useState('');
  const [draftFilters, setDraftFilters] = useState({
    account_id: appliedAccountId,
    plan_id: appliedPlanId,
    expires_before: appliedExpiresBefore,
  });
  const mountedRef = useRef(false);
  const hasLoadedRef = useRef(false);
  const [hasLoaded, setHasLoaded] = useState(false);
  const activeRequestKeyRef = useRef('');
  const requestSequenceRef = useRef(0);

  const requestKey = useMemo(() => {
    const params = new URLSearchParams();
    if (appliedStatus) params.set('status', appliedStatus);
    if (appliedAccountId) params.set('account_id', appliedAccountId);
    if (appliedPlanId) params.set('plan_id', appliedPlanId);
    if (appliedExpiresBefore) params.set('expires_before', appliedExpiresBefore);
    params.set('limit', String(PAGE_SIZE));
    if (offset > 0) params.set('offset', String(offset));
    return params.toString();
  }, [appliedAccountId, appliedExpiresBefore, appliedPlanId, appliedStatus, offset]);

  const updateQueueUrl = useCallback((patch: Record<string, string | null>) => {
    const nextParams = new URLSearchParams(searchParamsKey);
    Object.entries(patch).forEach(([key, value]) => {
      const isDefault = (key === 'sort' && value === 'priority') || (key === 'offset' && value === '0');
      if (!value || isDefault) nextParams.delete(key);
      else nextParams.set(key, value);
    });
    const nextQuery = nextParams.toString();
    router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname, { scroll: false });
  }, [pathname, router, searchParamsKey]);

  const loadSubscriptions = useCallback(async (force = false) => {
    if (!force && activeRequestKeyRef.current === requestKey) return;

    const sequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = sequence;
    activeRequestKeyRef.current = requestKey;
    setError('');
    if (force || hasLoadedRef.current) setIsRefreshing(true);
    else setIsLoading(true);

    try {
      const response = await fetch(`/api/admin/subscriptions?${requestKey}`, { credentials: 'include' });
      const payload = await readResponsePayload<{
        data?: { items?: SubscriptionApiItem[]; total?: number };
        items?: SubscriptionApiItem[];
        total?: number;
        message?: string;
      }>(response);
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
      }
      const data = 'data' in payload && payload.data ? payload.data : payload;
      const nextItems = ('items' in data && Array.isArray(data.items) ? data.items : []).map(normalizeSubscription);
      const nextTotal = 'total' in data ? Number(data.total ?? nextItems.length) : nextItems.length;
      if (mountedRef.current && requestSequenceRef.current === sequence) {
        setSubscriptions(nextItems);
        setTotal(nextTotal);
        setLoadedAt(new Date());
        setLoadedRequestKey(requestKey);
        hasLoadedRef.current = true;
        setHasLoaded(true);
      }
    } catch (err) {
      if (mountedRef.current && requestSequenceRef.current === sequence) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      }
    } finally {
      if (requestSequenceRef.current === sequence) {
        activeRequestKeyRef.current = '';
        if (mountedRef.current) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    }
  }, [requestKey, t]);

  useEffect(() => {
    mountedRef.current = true;
    void loadSubscriptions();
    return () => {
      mountedRef.current = false;
    };
  }, [loadSubscriptions]);

  useEffect(() => {
    setDraftFilters({
      account_id: appliedAccountId,
      plan_id: appliedPlanId,
      expires_before: appliedExpiresBefore,
    });
  }, [appliedAccountId, appliedExpiresBefore, appliedPlanId]);

  const queuedSubscriptions = useMemo(() => {
    return [...subscriptions].sort((left, right) => {
      if (sort === 'customer') {
        return String(left.account_name || left.account_id).localeCompare(String(right.account_name || right.account_id));
      }
      if (sort === 'expiry') {
        return (daysUntil(left.current_period_end) ?? Number.MAX_SAFE_INTEGER) -
          (daysUntil(right.current_period_end) ?? Number.MAX_SAFE_INTEGER);
      }
      return subscriptionPriority(left) - subscriptionPriority(right) ||
        String(left.account_name || left.account_id).localeCompare(String(right.account_name || right.account_id));
    });
  }, [sort, subscriptions]);

  const selectedSubscription =
    queuedSubscriptions.find((item) => item.subscription_id === focusedSubscriptionId) ||
    queuedSubscriptions[0] ||
    null;

  const pageSummary = useMemo(() => {
    const summary = { critical: 0, warning: 0, monitor: 0, stable: 0 };
    subscriptions.forEach((item) => {
      summary[subscriptionRiskLevel(item)] += 1;
    });
    return summary;
  }, [subscriptions]);

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateQueueUrl({
      account_id: draftFilters.account_id.trim() || null,
      plan_id: draftFilters.plan_id.trim() || null,
      expires_before: draftFilters.expires_before || null,
      offset: null,
      focus: null,
    });
  };

  const clearFilters = () => {
    setDraftFilters({ account_id: '', plan_id: '', expires_before: '' });
    updateQueueUrl({
      status: null,
      account_id: null,
      plan_id: null,
      expires_before: null,
      sort: null,
      offset: null,
      focus: null,
    });
  };

  if (error && !hasLoaded) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center" role="alert">
          <h2 className="mb-4 text-2xl font-bold text-rose-600">{t('common.error')}</h2>
          <p className="mb-6 text-slate-600 dark:text-slate-400">{error}</p>
          <button type="button" onClick={() => void loadSubscriptions(true)} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  if (isLoading && !hasLoaded) return <LoadingFallback />;

  const statusFilters = ['', 'past_due', 'expired', 'trialing', 'active'];
  const hasFilters = Boolean(appliedStatus || appliedAccountId || appliedPlanId || appliedExpiresBefore || sort !== 'priority');
  const isShowingRetainedResults = Boolean(error && loadedRequestKey && loadedRequestKey !== requestKey);

  return (
    <BackofficePageStack className="space-y-5">
      <BackofficeLayer
        eyebrow={t('admin.subscriptions.workspace_eyebrow', {}, 'Subscription operations')}
        title={t('admin.coverage_workspace_subscriptions_title', {}, 'Service risk queue')}
        description={t(
          'admin.subscriptions.workspace_desc',
          {},
          'Review the current filtered subscription register by service risk, then open one bounded detail surface for evidence and follow-up.'
        )}
        actions={(
          <>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void loadSubscriptions(true)}
              disabled={isRefreshing}
            >
              {isRefreshing
                ? t('common.loading', {}, 'Loading...')
                : t('admin.subscriptions.refresh_action', {}, 'Refresh subscriptions')}
            </button>
            <Link href="/admin/coverage" className="btn btn-secondary">
              {t('admin.back_to_coverage', {}, 'Back to coverage')}
            </Link>
          </>
        )}
      />

      {error ? (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200 sm:flex-row sm:items-center sm:justify-between"
        >
          <span>
            {error}
            {isShowingRetainedResults ? (
              <span className="mt-1 block text-xs">
                {t(
                  'admin.subscriptions.retained_results_notice',
                  {},
                  'Showing the last successfully loaded page; it may not match the current filters.'
                )}
              </span>
            ) : null}
          </span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadSubscriptions(true)}>
            {t('common.retry')}
          </button>
        </div>
      ) : null}

      <BackofficeSummaryStrip
        items={[
          {
            label: t('admin.subscriptions.page_critical_metric', {}, 'Page critical'),
            value: formatInteger(pageSummary.critical),
            toneClassName: pageSummary.critical > 0 ? 'text-rose-600 dark:text-rose-300' : undefined,
          },
          {
            label: t('admin.subscriptions.page_warning_metric', {}, 'Page warning'),
            value: formatInteger(pageSummary.warning),
            toneClassName: pageSummary.warning > 0 ? 'text-amber-600 dark:text-amber-300' : undefined,
          },
          { label: t('admin.subscriptions.page_monitor_metric', {}, 'Page monitor'), value: formatInteger(pageSummary.monitor) },
          { label: t('admin.subscriptions.page_stable_metric', {}, 'Page service normal'), value: formatInteger(pageSummary.stable) },
          {
            label: t('common.updated_at', {}, 'Updated'),
            value: loadedAt ? formatDate(loadedAt.toISOString()) : t('common.unknown', {}, 'Unknown'),
          },
        ]}
      />

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(20rem,0.72fr)]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div className="space-y-4 border-b border-slate-200/80 px-5 py-5 dark:border-slate-800 md:px-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-slate-950 dark:text-white">
                  {t('admin.subscriptions.queue_list_title', {}, 'Customers needing service follow-up')}
                </h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  {t(
                    'admin.subscriptions.queue_list_desc_v2',
                    {},
                    'Status filters are applied by the service API. Risk and expiry sorting apply to the current page of records.'
                  )}
                </p>
              </div>
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400" role="status">
                {t(
                  'admin.subscriptions.result_count',
                  { visible: formatInteger(queuedSubscriptions.length), total: formatInteger(total) },
                  `${formatInteger(queuedSubscriptions.length)} on this page · ${formatInteger(total)} total`
                )}
              </p>
            </div>

            <div
              className="flex flex-wrap gap-2"
              aria-label={t('admin.subscriptions.status_filter_label', {}, 'Subscription status')}
            >
              {statusFilters.map((status) => (
                <button
                  key={status || 'all'}
                  type="button"
                  aria-pressed={appliedStatus === status}
                  onClick={() => updateQueueUrl({ status: status || null, offset: null, focus: null })}
                  className={cn(
                    'cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium transition',
                    appliedStatus === status
                      ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200'
                      : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white'
                  )}
                >
                  {status ? t(`status.${status}`, undefined, status) : t('common.all', {}, 'All')}
                </button>
              ))}
            </div>

            <form onSubmit={applyFilters} className="grid gap-3 md:grid-cols-2 2xl:grid-cols-[minmax(11rem,1fr)_minmax(10rem,0.8fr)_minmax(10rem,0.7fr)_minmax(9rem,0.55fr)_auto]">
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('common.account', {}, 'Customer')}
                </span>
                <input
                  type="search"
                  className="input w-full"
                  value={draftFilters.account_id}
                  placeholder={t('admin.subscriptions.account_filter_placeholder', {}, 'Account ID')}
                  onChange={(event) => setDraftFilters((current) => ({ ...current, account_id: event.target.value }))}
                />
              </label>
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('common.plan', {}, 'Package')}
                </span>
                <input
                  type="search"
                  className="input w-full"
                  value={draftFilters.plan_id}
                  placeholder={t('admin.subscriptions.plan_filter_placeholder', {}, 'Plan ID')}
                  onChange={(event) => setDraftFilters((current) => ({ ...current, plan_id: event.target.value }))}
                />
              </label>
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('admin.expires_before')}
                </span>
                <input
                  type="date"
                  className="input w-full"
                  value={draftFilters.expires_before}
                  onChange={(event) => setDraftFilters((current) => ({ ...current, expires_before: event.target.value }))}
                />
              </label>
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('admin.subscriptions.sort_label', {}, 'Sort page')}
                </span>
                <select
                  className="input w-full"
                  value={sort}
                  onChange={(event) => updateQueueUrl({ sort: normalizeSort(event.target.value), focus: null })}
                >
                  <option value="priority">{t('admin.subscriptions.sort_priority', {}, 'Highest risk')}</option>
                  <option value="expiry">{t('admin.subscriptions.sort_expiry', {}, 'Ending soon')}</option>
                  <option value="customer">{t('admin.subscriptions.sort_customer', {}, 'Customer name')}</option>
                </select>
              </label>
              <div className="flex items-end gap-2 md:col-span-2 2xl:col-span-1">
                <button type="submit" className="btn btn-primary flex-1 2xl:flex-none">
                  {t('admin.subscriptions.apply_filters', {}, 'Apply')}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary flex-1 2xl:flex-none"
                  disabled={!hasFilters && !draftFilters.account_id && !draftFilters.plan_id && !draftFilters.expires_before}
                  onClick={clearFilters}
                >
                  {t('common.clear_filters', {}, 'Clear filters')}
                </button>
              </div>
            </form>
          </div>

          {queuedSubscriptions.length ? (
            <div role="list" aria-label={t('admin.subscriptions.queue_region_label', {}, 'Subscription risk queue')}>
              {queuedSubscriptions.map((subscription) => {
                const riskLevel = subscriptionRiskLevel(subscription);
                const remaining = daysUntil(subscription.current_period_end);
                const snapshotStatus = subscription.billing_snapshot_status?.status || 'unknown';
                const isSelected = selectedSubscription?.subscription_id === subscription.subscription_id;
                const packageLabel = resolveAdminPackageLabel(t, {
                  planId: subscription.plan_id,
                  packageAlias: subscription.package_alias,
                  fallback: subscription.package_alias || subscription.plan_id,
                }) || t('common.unknown');
                const riskReason =
                  subscription.status === 'past_due'
                    ? t('admin.subscriptions.reason_past_due', {}, 'Billing follow-up is already active and may affect service continuity.')
                    : subscription.status === 'expired'
                      ? t('admin.subscriptions.reason_expired', {}, 'The subscription has ended and needs a renewal or closure decision.')
                      : subscription.status === 'suspended'
                        ? t('admin.subscriptions.reason_suspended', {}, 'Service is suspended and requires an explicit operator decision.')
                        : snapshotStatus === 'stale'
                          ? t('admin.subscriptions.reason_snapshot_stale', {}, 'This period billing statistics need refresh before the account is treated as reconciled.')
                          : snapshotStatus === 'missing'
                            ? t('admin.subscriptions.reason_snapshot_missing', {}, 'This period billing statistics are missing for at least one covered site.')
                            : remaining !== null && remaining >= 0 && remaining <= 14
                              ? t('admin.subscriptions.reason_expiring', {}, 'Current period ends soon, so renewal or follow-up should happen before support load increases.')
                              : subscription.status === 'trialing'
                                ? t('admin.subscriptions.reason_trialing', {}, 'Trial coverage is still active and should be checked before converting or ending.')
                                : t('admin.subscriptions.reason_active', {}, 'Service coverage is currently stable and remains here as lower-priority review context.');

                return (
                  <article
                    key={subscription.subscription_id}
                    role="listitem"
                    data-ui="subscription-queue-item"
                    className={cn(
                      'grid gap-4 border-b border-slate-200/80 px-5 py-5 transition last:border-b-0 dark:border-slate-800 md:grid-cols-[minmax(10rem,0.85fr)_minmax(13rem,1.15fr)] md:items-center md:px-6 2xl:grid-cols-[minmax(11rem,1fr)_minmax(13rem,1.35fr)_minmax(9rem,0.8fr)_auto]',
                      isSelected ? 'bg-blue-50/65 dark:bg-blue-950/15' : 'hover:bg-slate-50/70 dark:hover:bg-slate-950/35'
                    )}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate font-semibold text-slate-950 dark:text-white">
                          {subscription.account_name || subscription.account_id}
                        </h3>
                        <BackofficeStatusBadge
                          status={subscription.status}
                          label={t(`status.${subscription.status}`, undefined, subscription.status)}
                        />
                      </div>
                      <p className="mt-2 text-sm font-medium text-slate-700 dark:text-slate-200">{packageLabel}</p>
                      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        <BackofficeIdentifier value={subscription.account_id} />
                      </div>
                    </div>

                    <div className="min-w-0">
                      <span className={cn('inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', riskToneClassName(riskLevel))}>
                        {t(`admin.subscriptions.risk_${riskLevel}`, undefined, riskLevel)}
                      </span>
                      <p className="mt-2 text-sm leading-6 text-slate-700 dark:text-slate-200">{riskReason}</p>
                    </div>

                    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-600 dark:text-slate-300 lg:grid-cols-1">
                      <div className="flex justify-between gap-3">
                        <dt>{t('common.sites', {}, 'Sites')}</dt>
                        <dd className="font-semibold tabular-nums text-slate-950 dark:text-white">{formatInteger(subscription.site_count)}</dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt>{t('admin.subscriptions.snapshot_status_metric', {}, 'Snapshot')}</dt>
                        <dd className="font-semibold text-slate-950 dark:text-white">
                          {t(`status.${snapshotStatus}`, undefined, snapshotStatus)}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt>{t('admin.billing_period')}</dt>
                        <dd className="font-semibold text-slate-950 dark:text-white">
                          {remaining === null
                            ? t('common.unknown', {}, 'Unknown')
                            : remaining >= 0
                              ? t('admin.days_until_end', { days: String(remaining) })
                              : t('admin.subscriptions.days_past_end', { days: String(Math.abs(remaining)) }, `${Math.abs(remaining)} days past end`)}
                        </dd>
                      </div>
                    </dl>

                    <div className="flex flex-wrap gap-2 md:justify-end">
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        aria-pressed={isSelected}
                        aria-controls="subscription-inspector"
                        onClick={() => updateQueueUrl({ focus: subscription.subscription_id })}
                      >
                        {t('admin.subscriptions.inspect_action', {}, 'Inspect')}
                      </button>
                      <Link href={`/admin/subscriptions/${subscription.subscription_id}`} className="btn btn-primary btn-sm whitespace-nowrap">
                        {t('admin.coverage_open_subscription_detail_action', {}, 'Inspect detail')}
                      </Link>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <BackofficeEmptyState
              className="m-5 md:m-6"
              title={t('admin.subscriptions.no_match_title', {}, 'No subscriptions match these filters')}
              description={t(
                'admin.subscriptions.no_match_desc',
                {},
                'Clear or adjust the current status, customer, package, and expiry filters. No subscription record has been changed.'
              )}
              action={hasFilters ? (
                <button type="button" className="btn btn-secondary btn-sm" onClick={clearFilters}>
                  {t('common.clear_filters', {}, 'Clear filters')}
                </button>
              ) : (
                <Link href="/admin/coverage" className="btn btn-secondary btn-sm">
                  {t('admin.back_to_coverage', {}, 'Back to coverage')}
                </Link>
              )}
            />
          )}

          <ListPagination
            offset={offset}
            limit={PAGE_SIZE}
            total={total}
            isLoading={isRefreshing}
            onOffsetChange={(nextOffset) => updateQueueUrl({ offset: String(nextOffset), focus: null })}
          />
        </BackofficeSectionPanel>

        <aside id="subscription-inspector" className="xl:sticky xl:top-24" aria-live="polite">
          <BackofficeSectionPanel className="space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  {t('admin.subscriptions.inspector_eyebrow', {}, 'Inspector')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                  {t('admin.subscriptions.inspector_title', {}, 'Current subscription focus')}
                </h2>
              </div>
              {selectedSubscription ? (
                <span className={cn('inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', riskToneClassName(subscriptionRiskLevel(selectedSubscription)))}>
                  {t(`admin.subscriptions.risk_${subscriptionRiskLevel(selectedSubscription)}`, undefined, subscriptionRiskLevel(selectedSubscription))}
                </span>
              ) : null}
            </div>

            {selectedSubscription ? (
              <div className="space-y-5">
                <div>
                  <p className="text-base font-semibold text-slate-950 dark:text-white">
                    {selectedSubscription.account_name || selectedSubscription.account_id}
                  </p>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                    {resolveAdminPackageLabel(t, {
                      planId: selectedSubscription.plan_id,
                      packageAlias: selectedSubscription.package_alias,
                      fallback: selectedSubscription.package_alias || selectedSubscription.plan_id,
                    }) || t('common.unknown')}
                  </p>
                </div>

                <dl className="grid gap-2 text-sm text-slate-600 dark:text-slate-300">
                  {[
                    [t('common.subscription', {}, 'Subscription'), t(`status.${selectedSubscription.status}`, undefined, selectedSubscription.status)],
                    [t('common.sites', {}, 'Sites'), formatInteger(selectedSubscription.site_count)],
                    [t('admin.subscriptions.snapshot_status_metric', {}, 'Snapshot'), t(`status.${selectedSubscription.billing_snapshot_status?.status || 'unknown'}`, undefined, selectedSubscription.billing_snapshot_status?.status || 'unknown')],
                    [t('admin.period_start'), formatDate(selectedSubscription.current_period_start)],
                    [t('admin.period_end'), formatDate(selectedSubscription.current_period_end)],
                    [t('admin.usage_cost'), formatAdminCurrency(selectedSubscription.billing_summary?.total_cost || 0)],
                  ].map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 last:border-b-0 dark:border-slate-800">
                      <dt>{label}</dt>
                      <dd className="text-right font-semibold text-slate-950 dark:text-white">{value}</dd>
                    </div>
                  ))}
                </dl>

                <div className="flex flex-wrap gap-2">
                  <Link href={`/admin/subscriptions/${selectedSubscription.subscription_id}`} className="btn btn-primary btn-sm">
                    {t('admin.coverage_open_subscription_detail_action', {}, 'Inspect detail')}
                  </Link>
                  <Link href={`/admin/accounts/${selectedSubscription.account_id}`} className="btn btn-secondary btn-sm">
                    {t('admin.coverage_open_customer_action', {}, 'Open customer')}
                  </Link>
                </div>

                <details className="border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800">
                  <summary className="cursor-pointer font-semibold text-slate-800 dark:text-slate-100">
                    {t('portal.support_information', {}, 'Support information')}
                  </summary>
                  <div className="mt-3 space-y-2 text-xs text-slate-500 dark:text-slate-400">
                    <BackofficeIdentifier value={selectedSubscription.subscription_id} full />
                    <BackofficeIdentifier value={selectedSubscription.account_id} full />
                    {selectedSubscription.plan_version_id ? <BackofficeIdentifier value={selectedSubscription.plan_version_id} full /> : null}
                    {selectedSubscription.billing_snapshot_status?.summary ? (
                      <p className="pt-1 leading-5">{selectedSubscription.billing_snapshot_status.summary}</p>
                    ) : null}
                  </div>
                </details>

                {selectedSubscription.covered_sites.length ? (
                  <details className="border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800">
                    <summary className="cursor-pointer font-semibold text-slate-800 dark:text-slate-100">
                      {t('admin.subscriptions.covered_sites_title', {}, 'Covered sites')}
                    </summary>
                    <div className="mt-3 flex flex-col items-start gap-2">
                      {selectedSubscription.covered_sites.map((site) => (
                        <Link key={site.site_id} href={`/admin/sites/${site.site_id}`} className="text-blue-700 hover:underline dark:text-blue-300">
                          {site.name || site.site_id}
                        </Link>
                      ))}
                    </div>
                  </details>
                ) : null}

                <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {t(
                    'admin.subscriptions.inspector_boundary',
                    {},
                    'This inspector opens existing subscription, customer, and site evidence only. It does not create checkout, payment, entitlement, or WordPress write controls.'
                  )}
                </p>
              </div>
            ) : (
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {t('admin.subscriptions.inspector_empty', {}, 'No subscription is visible on this page.')}
              </p>
            )}
          </BackofficeSectionPanel>
        </aside>
      </div>
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
