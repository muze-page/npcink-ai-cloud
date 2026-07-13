'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { translateCoverageStateLabel, type CoverageState } from '@/lib/customer-package-display';
import {
  BackofficeEmptyState,
  BackofficeLayer,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { resolveUiErrorMessage } from '@/lib/errors';
import { translateStatusLabel } from '@/lib/status-display';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';

type QueueSeverity = 'error' | 'warning' | 'ok' | 'inactive';
type QueueView = 'needs_action' | 'all' | QueueSeverity;
type QueueSort = 'priority' | 'expiry' | 'customer';

type CoverageQueueItem = {
  account: {
    account_id: string;
    name?: string;
    status?: string;
  };
  primary_subscription?: {
    subscription_id?: string;
    status?: string;
    current_period_end_at?: string;
  } | null;
  package?: {
    display_package_label?: string;
    package_kind?: string;
    coverage_state?: string;
  };
  severity: QueueSeverity;
  priority?: number;
  reason_code: string;
  reason_label: string;
  recommended_action: string;
  action_label: string;
  action_href: string;
  evidence: {
    site_count?: number;
    active_site_count?: number;
    active_key_site_count?: number;
    missing_key_site_count?: number;
    subscription_status?: string;
    current_period_end_at?: string;
    days_until_end?: number | null;
    billing_snapshot_status?: {
      status?: string;
      summary?: string;
      fresh_site_count?: number;
      stale_site_count?: number;
      missing_site_count?: number;
    };
  };
};

type CoverageWorkQueue = {
  generated_at?: string;
  summary?: {
    total?: number;
    visible?: number;
    needs_action?: number;
    error?: number;
    warning?: number;
    ok?: number;
    inactive?: number;
    reason_counts?: Record<string, number>;
  };
  items?: CoverageQueueItem[];
};

const INTERNAL_TEST_TEXT_RE = /Fatal error|Stack trace|Command line code|Uncaught ValueError|Path must not be empty|(^|[_-])smoke([_-]|$)|codex_image_smoke|site_knowledge_smoke/i;
const QUEUE_VIEWS = new Set<QueueView>(['needs_action', 'all', 'error', 'warning', 'ok', 'inactive']);
const QUEUE_SORTS = new Set<QueueSort>(['priority', 'expiry', 'customer']);

function isInternalCoverageRecord(...values: Array<string | undefined>): boolean {
  return INTERNAL_TEST_TEXT_RE.test(values.filter(Boolean).join(' '));
}

function normalizeQueueView(value: string | null): QueueView {
  return value && QUEUE_VIEWS.has(value as QueueView) ? (value as QueueView) : 'needs_action';
}

function normalizeQueueSort(value: string | null): QueueSort {
  return value && QUEUE_SORTS.has(value as QueueSort) ? (value as QueueSort) : 'priority';
}

function queueItemKey(item: CoverageQueueItem): string {
  return `${item.account.account_id}:${item.reason_code}`;
}

async function readJsonData<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: 'include' });
  if (!response.ok) {
    throw new Error(`Failed to load ${url}`);
  }
  const payload = await response.json();
  return payload.data as T;
}

function severityToneClassName(severity: string): string {
  const normalized = severity.toLowerCase();
  if (normalized === 'error') {
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200';
  }
  if (normalized === 'warning') {
    return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200';
  }
  if (normalized === 'ok') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-200';
  }
  return 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-200';
}

function translateReasonCode(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  reasonCode: string,
  fallback: string
): string {
  return t(`admin.coverage.reason.${reasonCode}`, {}, fallback);
}

function translateActionLabel(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  action: string,
  fallback: string
): string {
  return t(`admin.coverage.action.${action}`, {}, fallback);
}

function translateReasonShortLabel(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  reasonCode: string
): string {
  const fallback = reasonCode
    .replace(/^service_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
  return t(`admin.coverage.reason_short.${reasonCode}`, {}, fallback);
}

function normalizeCoverageState(value?: string): CoverageState | null {
  if (value === 'covered' || value === 'uncovered') {
    return value;
  }
  return null;
}

function CoverageStatusBadge({
  severity,
  label,
}: {
  severity: string;
  label: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 rounded-full border px-2.5 py-1 text-xs font-semibold leading-none',
        severityToneClassName(severity)
      )}
    >
      {label}
    </span>
  );
}

function buildQueueSummary(items: CoverageQueueItem[]): Required<NonNullable<CoverageWorkQueue['summary']>> {
  const reasonCounts: Record<string, number> = {};
  const summary = {
    total: items.length,
    visible: items.length,
    needs_action: 0,
    error: 0,
    warning: 0,
    ok: 0,
    inactive: 0,
    reason_counts: reasonCounts,
  };

  for (const item of items) {
    if (item.severity === 'error') summary.error += 1;
    if (item.severity === 'warning') summary.warning += 1;
    if (item.severity === 'ok') summary.ok += 1;
    if (item.severity === 'inactive') summary.inactive += 1;
    if (item.severity === 'error' || item.severity === 'warning') summary.needs_action += 1;
    reasonCounts[item.reason_code] = (reasonCounts[item.reason_code] || 0) + 1;
  }

  return summary;
}

function AdminCoverageContent() {
  const { t } = useLocale();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const [queue, setQueue] = useState<CoverageWorkQueue | null>(null);
  const [error, setError] = useState('');
  const [view, setView] = useState<QueueView>(() => normalizeQueueView(searchParams.get('status')));
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('q') || '');
  const [reasonFilter, setReasonFilter] = useState(() => searchParams.get('reason') || '');
  const [sort, setSort] = useState<QueueSort>(() => normalizeQueueSort(searchParams.get('sort')));
  const [selectedKey, setSelectedKey] = useState(() => searchParams.get('focus') || '');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const mountedRef = useRef(false);
  const queueParamsRef = useRef(new URLSearchParams(searchParamsKey));
  const coverageRequestActiveRef = useRef(false);
  const coverageRequestSequenceRef = useRef(0);

  const updateQueueUrl = useCallback((patch: Record<string, string | null>) => {
    const nextParams = new URLSearchParams(queueParamsRef.current.toString());
    Object.entries(patch).forEach(([key, value]) => {
      const isDefault =
        (key === 'status' && value === 'needs_action') ||
        (key === 'sort' && value === 'priority');
      if (!value || isDefault) {
        nextParams.delete(key);
      } else {
        nextParams.set(key, value);
      }
    });
    const nextQuery = nextParams.toString();
    queueParamsRef.current = nextParams;
    const nextUrl = nextQuery ? `${pathname}?${nextQuery}` : pathname;
    window.history.replaceState(window.history.state, '', nextUrl);
  }, [pathname]);

  const loadCoverage = useCallback(async (force = false) => {
    if (!force && coverageRequestActiveRef.current) {
      return;
    }
    const requestSequence = coverageRequestSequenceRef.current + 1;
    coverageRequestSequenceRef.current = requestSequence;
    coverageRequestActiveRef.current = true;
    if (force) {
      setIsRefreshing(true);
    }
    setError('');
    try {
      const coveragePayload = await readJsonData<CoverageWorkQueue>('/api/admin/coverage-work-queue');
      if (mountedRef.current && coverageRequestSequenceRef.current === requestSequence) {
        setQueue(coveragePayload);
      }
    } catch (err) {
      if (mountedRef.current && coverageRequestSequenceRef.current === requestSequence) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      }
    } finally {
      if (coverageRequestSequenceRef.current === requestSequence) {
        coverageRequestActiveRef.current = false;
        if (mountedRef.current) {
          setIsRefreshing(false);
        }
      }
    }
  }, [setError, setIsRefreshing, setQueue, t]);

  useEffect(() => {
    mountedRef.current = true;
    void loadCoverage();
    return () => {
      mountedRef.current = false;
    };
  }, [loadCoverage]);

  useEffect(() => {
    const params = new URLSearchParams(searchParamsKey);
    queueParamsRef.current = params;
    setView(normalizeQueueView(params.get('status')));
    setSearchQuery(params.get('q') || '');
    setReasonFilter(params.get('reason') || '');
    setSort(normalizeQueueSort(params.get('sort')));
    setSelectedKey(params.get('focus') || '');
  }, [searchParamsKey]);

  const visibleQueueItems = useMemo(
    () =>
      (queue?.items || []).filter(
      (item) => !isInternalCoverageRecord(item.account.account_id, item.account.name)
      ),
    [queue?.items]
  );
  const visibleSummary = useMemo(() => buildQueueSummary(visibleQueueItems), [visibleQueueItems]);
  const visibleItems = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    const filtered = visibleQueueItems.filter((item) => {
      const matchesView =
        view === 'all' ||
        (view === 'needs_action'
          ? item.severity === 'error' || item.severity === 'warning'
          : item.severity === view);
      if (!matchesView || (reasonFilter && item.reason_code !== reasonFilter)) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      return [
        item.account.account_id,
        item.account.name,
        item.primary_subscription?.subscription_id,
        item.package?.display_package_label,
        item.reason_label,
        item.reason_code,
      ].filter(Boolean).join(' ').toLowerCase().includes(normalizedQuery);
    });
    const severityRank: Record<QueueSeverity, number> = { error: 0, warning: 1, inactive: 2, ok: 3 };
    return [...filtered].sort((left, right) => {
      if (sort === 'customer') {
        return String(left.account.name || left.account.account_id).localeCompare(
          String(right.account.name || right.account.account_id)
        );
      }
      if (sort === 'expiry') {
        const leftDays = left.evidence.days_until_end ?? Number.MAX_SAFE_INTEGER;
        const rightDays = right.evidence.days_until_end ?? Number.MAX_SAFE_INTEGER;
        return leftDays - rightDays || severityRank[left.severity] - severityRank[right.severity];
      }
      return Number(left.priority ?? severityRank[left.severity] * 100) -
        Number(right.priority ?? severityRank[right.severity] * 100) ||
        String(left.account.name || left.account.account_id).localeCompare(
          String(right.account.name || right.account.account_id)
        );
    });
  }, [reasonFilter, searchQuery, sort, view, visibleQueueItems]);
  const selectedQueueItem =
    visibleItems.find((item) => queueItemKey(item) === selectedKey) || visibleItems[0] || null;

  if (error && !queue) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-red-600">{t('common.error')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{error}</p>
          <button onClick={() => void loadCoverage(true)} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  if (!queue) {
    return <LoadingFallback />;
  }

  const filters: Array<{ value: QueueView; label: string; count: number }> = [
    {
      value: 'needs_action',
      label: t('admin.coverage.filter_needs_action', {}, 'Needs action'),
      count: visibleSummary.needs_action,
    },
    { value: 'error', label: translateStatusLabel('error', t), count: visibleSummary.error },
    { value: 'warning', label: translateStatusLabel('warning', t), count: visibleSummary.warning },
    { value: 'ok', label: translateStatusLabel('ok', t), count: visibleSummary.ok },
    {
      value: 'all',
      label: t('common.all', {}, 'All'),
      count: visibleSummary.total,
    },
  ];
  const reasonEntries = Object.entries(visibleSummary.reason_counts || {})
    .sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0))
    .slice(0, 6);
  return (
    <BackofficePageStack className="space-y-5">
      <BackofficeLayer
        eyebrow={t('admin.coverage.primary_queue_eyebrow', {}, 'Work queue')}
        title={t('admin.coverage_surface_title', {}, 'Service risk queue')}
        description={t(
          'admin.coverage_surface_desc',
          {},
          'Prioritize customers by service impact, then open the bounded account, subscription, or site action that resolves the blocker.'
        )}
        actions={(
          <>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void loadCoverage(true)}
              disabled={isRefreshing}
            >
              {isRefreshing
                ? t('common.loading', {}, 'Loading...')
                : t('admin.coverage.refresh_action', {}, 'Refresh queue')}
            </button>
            <Link href="/admin/subscriptions" className="btn btn-secondary">
              {t('admin.coverage_open_subscription_queue_action', {}, 'Open subscription risk')}
            </Link>
          </>
        )}
      />

      {error ? (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200 sm:flex-row sm:items-center sm:justify-between"
        >
          <span>{error}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadCoverage(true)}>
            {t('common.retry')}
          </button>
        </div>
      ) : null}

      <BackofficeSummaryStrip
        items={[
          {
            label: t('admin.coverage.metric_needs_action', {}, 'Needs action'),
            value: formatInteger(visibleSummary.needs_action),
            toneClassName: visibleSummary.needs_action > 0 ? 'text-amber-600 dark:text-amber-300' : undefined,
          },
          {
            label: translateStatusLabel('error', t),
            value: formatInteger(visibleSummary.error),
            toneClassName: visibleSummary.error > 0 ? 'text-rose-600 dark:text-rose-300' : undefined,
          },
          { label: translateStatusLabel('warning', t), value: formatInteger(visibleSummary.warning) },
          { label: t('admin.coverage.metric_aligned', {}, 'Aligned'), value: formatInteger(visibleSummary.ok) },
          {
            label: t('common.updated_at', {}, 'Updated'),
            value: queue.generated_at ? formatDate(queue.generated_at) : t('common.unknown', {}, 'Unknown'),
          },
        ]}
      />

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(20rem,0.72fr)]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div className="space-y-4 border-b border-slate-200/80 px-5 py-5 dark:border-slate-800 md:px-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.coverage_customer_queue_title', {}, 'Customers needing service follow-up')}
                </h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  {t(
                    'admin.coverage_customer_queue_desc',
                    {},
                    'Resolve package, subscription, billing, site, and key blockers from one prioritized queue.'
                  )}
                </p>
              </div>
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400" role="status">
                {t(
                  'admin.coverage.queue_count',
                  { visible: formatInteger(visibleItems.length), total: formatInteger(visibleQueueItems.length) },
                  `${formatInteger(visibleItems.length)} of ${formatInteger(visibleQueueItems.length)} customers`
                )}
              </p>
            </div>

            <div className="flex flex-wrap gap-2" aria-label={t('admin.coverage.status_filter_label', {}, 'Queue status')}>
              {filters.map((filter) => (
                <button
                  key={filter.value}
                  type="button"
                  aria-pressed={view === filter.value}
                  onClick={() => {
                    setView(filter.value);
                    setSelectedKey('');
                    updateQueueUrl({
                      status: filter.value,
                      q: searchQuery.trim() || null,
                      reason: reasonFilter || null,
                      sort,
                      focus: null,
                    });
                  }}
                  className={cn(
                    'cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium transition',
                    view === filter.value
                      ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200'
                      : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white'
                  )}
                >
                  {filter.label} · {formatInteger(filter.count)}
                </button>
              ))}
            </div>

            <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-[minmax(13rem,1fr)_minmax(10rem,0.55fr)_minmax(10rem,0.5fr)_auto]">
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('common.search', {}, 'Search')}
                </span>
                <input
                  type="search"
                  className="input w-full"
                  value={searchQuery}
                  placeholder={t('admin.coverage.search_placeholder', {}, 'Customer, account, subscription, or package')}
                  onChange={(event) => {
                    const nextValue = event.target.value;
                    setSearchQuery(nextValue);
                    setSelectedKey('');
                    updateQueueUrl({
                      status: view,
                      q: nextValue.trim() || null,
                      reason: reasonFilter || null,
                      sort,
                      focus: null,
                    });
                  }}
                />
              </label>
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('admin.coverage.reason_filter_label', {}, 'Reason')}
                </span>
                <select
                  className="input w-full"
                  value={reasonFilter}
                  onChange={(event) => {
                    const nextValue = event.target.value;
                    setReasonFilter(nextValue);
                    setSelectedKey('');
                    updateQueueUrl({
                      status: view,
                      q: searchQuery.trim() || null,
                      reason: nextValue || null,
                      sort,
                      focus: null,
                    });
                  }}
                >
                  <option value="">{t('admin.coverage.reason_all', {}, 'All reasons')}</option>
                  {reasonEntries.map(([reasonCode, count]) => (
                    <option key={reasonCode} value={reasonCode}>
                      {translateReasonShortLabel(t, reasonCode)} · {formatInteger(Number(count || 0))}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('admin.coverage.sort_label', {}, 'Sort')}
                </span>
                <select
                  className="input w-full"
                  value={sort}
                  onChange={(event) => {
                    const nextValue = normalizeQueueSort(event.target.value);
                    setSort(nextValue);
                    updateQueueUrl({
                      status: view,
                      q: searchQuery.trim() || null,
                      reason: reasonFilter || null,
                      sort: nextValue,
                      focus: selectedKey || null,
                    });
                  }}
                >
                  <option value="priority">{t('admin.coverage.sort_priority', {}, 'Highest impact')}</option>
                  <option value="expiry">{t('admin.coverage.sort_expiry', {}, 'Ending soon')}</option>
                  <option value="customer">{t('admin.coverage.sort_customer', {}, 'Customer name')}</option>
                </select>
              </label>
              <div className="flex items-end">
                <button
                  type="button"
                  className="btn btn-secondary w-full md:w-auto"
                  disabled={!searchQuery && !reasonFilter && view === 'needs_action' && sort === 'priority'}
                  onClick={() => {
                    setSearchQuery('');
                    setReasonFilter('');
                    setView('needs_action');
                    setSort('priority');
                    setSelectedKey('');
                    updateQueueUrl({ q: null, reason: null, status: null, sort: null, focus: null });
                  }}
                >
                  {t('common.clear_filters', {}, 'Clear filters')}
                </button>
              </div>
            </div>
          </div>

          {visibleItems.length ? (
            <div role="list" aria-label={t('admin.coverage.table_region_label', {}, 'Customer service queue')}>
              {visibleItems.map((item) => {
                const itemKey = queueItemKey(item);
                const isSelected = selectedQueueItem ? queueItemKey(selectedQueueItem) === itemKey : false;
                const coverageState = normalizeCoverageState(item.package?.coverage_state);
                const billingStatus = item.evidence.billing_snapshot_status?.status || 'unknown';
                return (
                  <article
                    key={itemKey}
                    role="listitem"
                    data-ui="coverage-queue-item"
                    className={cn(
                      'grid gap-4 border-b border-slate-200/80 px-5 py-5 transition last:border-b-0 dark:border-slate-800 md:grid-cols-[minmax(10rem,0.85fr)_minmax(13rem,1.15fr)] md:px-6 md:items-center 2xl:grid-cols-[minmax(11rem,1fr)_minmax(13rem,1.35fr)_minmax(9rem,0.8fr)_auto]',
                      isSelected
                        ? 'bg-blue-50/65 dark:bg-blue-950/15'
                        : 'hover:bg-slate-50/70 dark:hover:bg-slate-950/35'
                    )}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate font-semibold text-slate-950 dark:text-white">
                          {item.account.name || t('admin.subscription_detail.current_customer_label', {}, 'Current customer')}
                        </p>
                        <CoverageStatusBadge severity={item.severity} label={translateStatusLabel(item.severity, t)} />
                      </div>
                      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        <BackofficeIdentifier value={item.account.account_id} />
                      </div>
                    </div>

                    <div className="min-w-0">
                      <p className="text-sm font-medium leading-6 text-slate-800 dark:text-slate-100">
                        {translateReasonCode(t, item.reason_code, item.reason_label)}
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {translateActionLabel(t, item.recommended_action, item.action_label)}
                      </p>
                    </div>

                    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-600 dark:text-slate-300 lg:grid-cols-1">
                      <div className="flex justify-between gap-3">
                        <dt>{t('common.package', {}, 'Package')}</dt>
                        <dd className="font-semibold text-slate-950 dark:text-white">
                          {item.package?.display_package_label || t('common.not_available', {}, 'N/A')}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt>{t('common.sites', {}, 'Sites')}</dt>
                        <dd className="font-semibold tabular-nums text-slate-950 dark:text-white">
                          {formatInteger(Number(item.evidence.site_count || 0))}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt>{t('admin.subscriptions.snapshot_status_metric', {}, 'Snapshot')}</dt>
                        <dd className="font-semibold text-slate-950 dark:text-white">
                          {translateStatusLabel(billingStatus, t)}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt>{t('admin.coverage_state', {}, 'Coverage')}</dt>
                        <dd className="font-semibold text-slate-950 dark:text-white">
                          {coverageState
                            ? translateCoverageStateLabel(t, coverageState)
                            : t('common.unknown', {}, 'Unknown')}
                        </dd>
                      </div>
                    </dl>

                    <div className="flex flex-wrap gap-2 md:justify-end 2xl:justify-end">
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        aria-pressed={isSelected}
                        aria-controls="coverage-inspector"
                        onClick={() => {
                          setSelectedKey(itemKey);
                          updateQueueUrl({
                            status: view,
                            q: searchQuery.trim() || null,
                            reason: reasonFilter || null,
                            sort,
                            focus: itemKey,
                          });
                        }}
                      >
                        {t('admin.coverage.select_inspector_action', {}, 'Inspect')}
                      </button>
                      <Link
                        href={item.action_href || `/admin/accounts/${item.account.account_id}`}
                        className="btn btn-primary btn-sm whitespace-nowrap"
                      >
                        {translateActionLabel(t, item.recommended_action, item.action_label || t('common.open', {}, 'Open'))}
                      </Link>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <BackofficeEmptyState
              className="m-5 md:m-6"
              title={t('admin.coverage.no_match_title', {}, 'No customers match these filters')}
              description={t(
                'admin.coverage.no_match_desc',
                {},
                'Clear or adjust the current status, reason, and search filters. The source queue has not been changed.'
              )}
              action={visibleQueueItems.length === 0 ? (
                <Link href="/admin/accounts" className="btn btn-secondary btn-sm">
                  {t('admin.coverage_open_customer_register_action', {}, 'Open customer register')}
                </Link>
              ) : (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => {
                    setSearchQuery('');
                    setReasonFilter('');
                    setView('all');
                    setSort('priority');
                    updateQueueUrl({ q: null, reason: null, status: 'all', sort: null, focus: null });
                  }}
                >
                  {t('common.clear_filters', {}, 'Clear filters')}
                </button>
              )}
            />
          )}
        </BackofficeSectionPanel>

        <aside id="coverage-inspector" className="xl:sticky xl:top-24" aria-live="polite">
          <BackofficeSectionPanel className="space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.coverage.inspector_eyebrow', {}, 'Inspector')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.coverage.inspector_title', {}, 'Current customer focus')}
                </h2>
              </div>
              {selectedQueueItem ? (
                <CoverageStatusBadge
                  severity={selectedQueueItem.severity}
                  label={translateStatusLabel(selectedQueueItem.severity, t)}
                />
              ) : null}
            </div>

            {selectedQueueItem ? (
              <div className="space-y-5">
                <div>
                  <p className="text-base font-semibold text-slate-950 dark:text-white">
                    {selectedQueueItem.account.name || t('admin.subscription_detail.current_customer_label', {}, 'Current customer')}
                  </p>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    <BackofficeIdentifier value={selectedQueueItem.account.account_id} full />
                  </div>
                  <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {translateReasonCode(t, selectedQueueItem.reason_code, selectedQueueItem.reason_label)}
                  </p>
                </div>

                <dl className="grid gap-2 text-sm text-slate-600 dark:text-slate-300">
                  {[
                    [t('common.package', {}, 'Package'), selectedQueueItem.package?.display_package_label || t('common.not_available', {}, 'N/A')],
                    [t('common.sites', {}, 'Sites'), formatInteger(Number(selectedQueueItem.evidence.site_count || 0))],
                    [t('admin.account_detail.active_api_keys_label', {}, 'Active API keys'), formatInteger(Number(selectedQueueItem.evidence.active_key_site_count || 0))],
                    [t('admin.subscriptions.snapshot_status_metric', {}, 'Snapshot'), translateStatusLabel(selectedQueueItem.evidence.billing_snapshot_status?.status || 'unknown', t)],
                    [t('common.subscription', {}, 'Subscription'), translateStatusLabel(selectedQueueItem.evidence.subscription_status || 'unknown', t)],
                  ].map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 last:border-b-0 dark:border-slate-800">
                      <dt>{label}</dt>
                      <dd className="text-right font-semibold text-slate-950 dark:text-white">{value}</dd>
                    </div>
                  ))}
                </dl>

                <div className="flex flex-wrap gap-2">
                  <Link
                    href={selectedQueueItem.action_href || `/admin/accounts/${selectedQueueItem.account.account_id}`}
                    className="btn btn-primary btn-sm"
                  >
                    {translateActionLabel(t, selectedQueueItem.recommended_action, selectedQueueItem.action_label || t('common.open', {}, 'Open'))}
                  </Link>
                  <Link href={`/admin/accounts/${selectedQueueItem.account.account_id}`} className="btn btn-secondary btn-sm">
                    {t('admin.coverage_open_customer_action', {}, 'Open customer')}
                  </Link>
                </div>

                <details className="border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800">
                  <summary className="cursor-pointer font-semibold text-slate-800 dark:text-slate-100">
                    {t('admin.coverage.reason_summary_title', {}, 'Reason summary')}
                  </summary>
                  <div className="mt-3 space-y-2">
                    {reasonEntries.length ? reasonEntries.map(([reasonCode, count]) => (
                      <div key={reasonCode} className="flex items-center justify-between gap-4 text-slate-600 dark:text-slate-300">
                        <span>{translateReasonShortLabel(t, reasonCode)}</span>
                        <span className="font-semibold tabular-nums text-slate-950 dark:text-white">
                          {formatInteger(Number(count || 0))}
                        </span>
                      </div>
                    )) : (
                      <p className="text-slate-500 dark:text-slate-400">
                        {t('admin.coverage.reason_summary_empty', {}, 'No reason codes are visible in this snapshot.')}
                      </p>
                    )}
                  </div>
                </details>

                <details className="border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800">
                  <summary className="cursor-pointer font-semibold text-slate-800 dark:text-slate-100">
                    {t('admin.coverage.related_surfaces_title', {}, 'Related surfaces')}
                  </summary>
                  <div className="mt-3 flex flex-col items-start gap-2">
                    <Link href="/admin/subscriptions" className="text-blue-700 hover:underline dark:text-blue-300">
                      {t('admin.coverage_open_subscription_queue_action', {}, 'Open subscription risk')}
                    </Link>
                    <Link href="/admin/plans" className="text-blue-700 hover:underline dark:text-blue-300">
                      {t('admin.coverage_open_package_catalog_action', {}, 'Open package catalog')}
                    </Link>
                    <Link href="/admin/accounts" className="text-blue-700 hover:underline dark:text-blue-300">
                      {t('admin.coverage_open_customer_register_action', {}, 'Open customer register')}
                    </Link>
                  </div>
                </details>

                <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {t(
                    'admin.coverage.inspector_boundary',
                    {},
                    'This inspector only opens existing customer, subscription, site, and package surfaces. It does not create customer-facing checkout, payment, or WordPress write controls.'
                  )}
                </p>
              </div>
            ) : (
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {t('admin.coverage.inspector_empty', {}, 'No customer needs inspection in this snapshot.')}
              </p>
            )}
          </BackofficeSectionPanel>
        </aside>
      </div>
    </BackofficePageStack>
  );
}

export default function AdminCoveragePage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminCoverageContent />
    </Suspense>
  );
}
