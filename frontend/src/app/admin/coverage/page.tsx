'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { CustomerAdminTabs } from '@/components/admin/CustomerAdminTabs';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { translateCoverageStateLabel, type CoverageState } from '@/lib/customer-package-display';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { resolveUiErrorMessage } from '@/lib/errors';
import { translateStatusLabel } from '@/lib/status-display';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';

type QueueSeverity = 'error' | 'warning' | 'ok' | 'inactive';
type QueueView = 'needs_action' | 'all' | QueueSeverity;
type CoverageTab = 'service_status' | 'packages';

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

type TierSummary = {
  tier_id: string;
  label?: string;
  package_alias?: string;
  usage_band?: string;
  monthly_included_points?: number;
  site_limit?: number;
  budgets_template?: Record<string, unknown>;
  concurrency_template?: Record<string, unknown>;
  max_batch_items?: number;
};

type PlanListItem = {
  plan?: {
    plan_id?: string;
    name?: string;
    status?: string;
    metadata?: Record<string, unknown>;
  };
  latest_version?: {
    status?: string;
    budgets?: Record<string, unknown>;
    concurrency?: Record<string, unknown>;
  } | null;
  tier_summary?: TierSummary;
  subscription_counts?: {
    active?: number;
  };
};

type PlanCatalog = {
  items?: PlanListItem[];
  tier_templates?: TierSummary[];
};

const INTERNAL_TEST_TEXT_RE = /Fatal error|Stack trace|Command line code|Uncaught ValueError|Path must not be empty|(^|[_-])smoke([_-]|$)|codex_image_smoke|site_knowledge_smoke/i;

function isInternalCoverageRecord(...values: Array<string | undefined>): boolean {
  return INTERNAL_TEST_TEXT_RE.test(values.filter(Boolean).join(' '));
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

function numericValue(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function normalizeTierId(value: string): string {
  return value === 'starter' ? 'free' : value;
}

function findPlanForTier(plans: PlanListItem[], tierId: string): PlanListItem | undefined {
  const expectedTierId = normalizeTierId(tierId);
  return plans.find((item) => {
    const planId = normalizeTierId(String(item.plan?.plan_id || ''));
    const metadataTierId = normalizeTierId(String(item.plan?.metadata?.tier_id || ''));
    const summaryTierId = normalizeTierId(String(item.tier_summary?.tier_id || ''));
    return (
      planId === expectedTierId ||
      metadataTierId === expectedTierId ||
      summaryTierId === expectedTierId ||
      (expectedTierId === 'free' && item.plan?.metadata?.plan_kind === 'default_free')
    );
  });
}

function resolvePackageName(shell: TierSummary, item?: PlanListItem): string {
  return String(item?.tier_summary?.package_alias || item?.plan?.name || shell.package_alias || shell.label || shell.tier_id);
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
  const [queue, setQueue] = useState<CoverageWorkQueue | null>(null);
  const [planCatalog, setPlanCatalog] = useState<PlanCatalog | null>(null);
  const [error, setError] = useState('');
  const [view, setView] = useState<QueueView>('needs_action');
  const [activeTab, setActiveTab] = useState<CoverageTab>('service_status');

  useEffect(() => {
    let alive = true;

    const loadCoverage = async () => {
      setError('');
      try {
        const [coveragePayload, plansPayload] = await Promise.all([
          readJsonData<CoverageWorkQueue>('/api/admin/coverage-work-queue'),
          readJsonData<PlanCatalog>('/api/admin/plans'),
        ]);
        if (!alive) return;
        setQueue(coveragePayload);
        setPlanCatalog(plansPayload);
      } catch (err) {
        if (!alive) return;
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      }
    };

    void loadCoverage();
    return () => {
      alive = false;
    };
  }, [t]);

  const visibleQueueItems = useMemo(
    () =>
      (queue?.items || []).filter(
      (item) => !isInternalCoverageRecord(item.account.account_id, item.account.name)
      ),
    [queue?.items]
  );
  const visibleSummary = useMemo(() => buildQueueSummary(visibleQueueItems), [visibleQueueItems]);
  const visibleItems = useMemo(() => {
    return visibleQueueItems.filter((item) => {
      if (view === 'all') return true;
      if (view === 'needs_action') return item.severity === 'error' || item.severity === 'warning';
      return item.severity === view;
    });
  }, [visibleQueueItems, view]);

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

  if (!queue || !planCatalog) {
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
  const packageShells = (planCatalog.tier_templates || []).filter((shell) =>
    ['starter', 'free', 'pro', 'agency'].includes(normalizeTierId(String(shell.tier_id || '')))
  );
  const packageRows = packageShells.map((shell) => {
    const item = findPlanForTier(planCatalog.items || [], shell.tier_id);
    const latestVersion = item?.latest_version || null;
    const budgets = (latestVersion?.budgets || item?.tier_summary?.budgets_template || shell.budgets_template || {}) as Record<string, unknown>;
    const concurrency = (latestVersion?.concurrency || item?.tier_summary?.concurrency_template || shell.concurrency_template || {}) as Record<string, unknown>;
    const sourceTier = item?.tier_summary || shell;
    return {
      shell,
      item,
      budgets,
      concurrency,
      sourceTier,
      planId: item?.plan?.plan_id,
      name: resolvePackageName(shell, item),
    };
  });
  const activePackageSubscriptions = packageRows.reduce(
    (total, row) => total + Number(row.item?.subscription_counts?.active || 0),
    0
  );
  const readyPackages = packageRows.filter((row) => row.item?.plan?.status === 'active').length;
  const tabs: Array<{ value: CoverageTab; label: string; detail: string }> = [
    {
      value: 'service_status',
      label: t('admin.coverage.tab_service_status', {}, 'Service status'),
      detail: t('admin.coverage.tab_service_status_desc', {}, 'Customer follow-up queue'),
    },
    {
      value: 'packages',
      label: t('admin.coverage.tab_packages', {}, 'Packages'),
      detail: t('admin.coverage.tab_packages_desc', {}, 'Free, Pro, and Agency'),
    },
  ];

  return (
    <BackofficePageStack>
      <CustomerAdminTabs />
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.coverage_surface_title', {}, 'Customer service status')}
        description={t(
          'admin.coverage_surface_desc',
          {},
          'Work from the highest-impact customer first. Each row shows the current blocker, evidence, and the next operator action.'
        )}
        aside={
          <div className="w-full xl:w-[44rem]">
            <BackofficeMetricStrip
              columnsClassName="md:grid-cols-4"
              items={[
                {
                  label: t('admin.coverage.metric_needs_action', {}, 'Needs action'),
                  value: formatInteger(visibleSummary.needs_action),
                  size: 'compact',
                },
                {
                  label: translateStatusLabel('error', t),
                  value: formatInteger(visibleSummary.error),
                  size: 'compact',
                },
                {
                  label: translateStatusLabel('warning', t),
                  value: formatInteger(visibleSummary.warning),
                  size: 'compact',
                },
                {
                  label: t('admin.coverage.metric_aligned', {}, 'Aligned'),
                  value: formatInteger(visibleSummary.ok),
                  size: 'compact',
                },
              ]}
            />
          </div>
        }
      >
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {queue.generated_at
            ? `${t('common.updated_at', {}, 'Updated')}: ${formatDate(queue.generated_at)}`
            : t('admin.coverage_surface_runtime_note', {}, 'Coverage reads are assembled from existing customer, subscription, and site detail surfaces.')}
        </p>
      </BackofficePrimaryPanel>

      <div className="inline-grid max-w-xl grid-cols-2 gap-1 rounded-full border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setActiveTab(tab.value)}
            className={cn(
              'cursor-pointer rounded-full px-4 py-2 text-center transition',
              activeTab === tab.value
                ? 'bg-blue-600 text-white shadow-sm dark:bg-blue-500'
                : 'text-slate-600 hover:bg-slate-50 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-white'
            )}
          >
            <span className="block text-sm font-semibold">{tab.label}</span>
            <span className={cn(
              'mt-0.5 block text-xs',
              activeTab === tab.value ? 'text-blue-50' : 'text-slate-500 dark:text-slate-400'
            )}>{tab.detail}</span>
          </button>
        ))}
      </div>

      {activeTab === 'service_status' ? (
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(22rem,0.85fr)]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div className="border-b border-slate-200/80 px-6 py-5 dark:border-slate-800">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.coverage.primary_queue_eyebrow', {}, 'Work queue')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.coverage_customer_queue_title', {}, 'Customers needing service follow-up')}
                </h2>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                  {t(
                    'admin.coverage_customer_queue_desc',
                    {},
                    'Resolve package, subscription, billing, site, and key blockers from this single customer queue.'
                  )}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {filters.map((filter) => (
                  <button
                    key={filter.value}
                    type="button"
                    onClick={() => setView(filter.value)}
                    className={cn(
                      'rounded-full border px-3 py-1.5 text-xs font-medium transition',
                      view === filter.value
                        ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200'
                        : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white'
                    )}
                  >
                    {filter.label} · {formatInteger(filter.count)}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {visibleItems.length ? (
            <div className="overflow-x-auto">
              <table className="min-w-[64rem] divide-y divide-slate-200/80 text-left text-sm dark:divide-slate-800 lg:w-full">
                <thead className="bg-slate-50/80 text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-950/30 dark:text-slate-400">
                  <tr>
                    <th className="w-[24%] px-6 py-3 font-semibold">{t('common.account', {}, 'Customer')}</th>
                    <th className="w-[17%] px-4 py-3 font-semibold">{t('common.package', {}, 'Package')}</th>
                    <th className="w-[28%] px-4 py-3 font-semibold">{t('admin.reason', {}, 'Reason')}</th>
                    <th className="w-[20%] px-4 py-3 font-semibold">{t('admin.coverage.evidence', {}, 'Evidence')}</th>
                    <th className="w-[11rem] px-6 py-3 text-right font-semibold">{t('common.actions', {}, 'Actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200/80 dark:divide-slate-800">
                  {visibleItems.map((item) => {
                    const billingStatus = item.evidence.billing_snapshot_status?.status || 'unknown';
                    const coverageState = normalizeCoverageState(item.package?.coverage_state);
                    return (
                      <tr key={`${item.account.account_id}-${item.reason_code}`} className="align-top hover:bg-slate-50/70 dark:hover:bg-slate-950/35">
                        <td className="px-6 py-4">
                          <p className="font-semibold text-slate-950 dark:text-white">{item.account.name || item.account.account_id}</p>
                          <BackofficeIdentifier value={item.account.account_id} className="mt-1 text-xs text-slate-500 dark:text-slate-400" />
                          {item.primary_subscription?.subscription_id ? (
                            <BackofficeIdentifier value={item.primary_subscription.subscription_id} className="mt-1 text-xs text-slate-500 dark:text-slate-400" />
                          ) : null}
                        </td>
                        <td className="px-4 py-4">
                          <p className="font-medium text-slate-900 dark:text-slate-100">
                            {item.package?.display_package_label || t('common.not_available', {}, 'N/A')}
                          </p>
                          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                            {coverageState
                              ? translateCoverageStateLabel(t, coverageState)
                              : t('common.unknown', {}, 'Unknown')}
                          </p>
                        </td>
                        <td className="px-4 py-4">
                          <div className="max-w-xl space-y-2">
                            <CoverageStatusBadge
                              severity={item.severity}
                              label={translateStatusLabel(item.severity, t)}
                            />
                            <p className="text-slate-700 dark:text-slate-200">
                              {translateReasonCode(t, item.reason_code, item.reason_label)}
                            </p>
                            <p className="text-xs text-slate-500 dark:text-slate-400">
                              {translateActionLabel(t, item.recommended_action, item.action_label)}
                            </p>
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          <dl className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
                            <div className="flex justify-between gap-3">
                              <dt>{t('common.sites', {}, 'Sites')}</dt>
                              <dd className="font-semibold tabular-nums">{formatInteger(Number(item.evidence.site_count || 0))}</dd>
                            </div>
                            <div className="flex justify-between gap-3">
                              <dt>{t('admin.account_detail.active_api_keys_label', {}, 'Active API keys')}</dt>
                              <dd className="font-semibold tabular-nums">{formatInteger(Number(item.evidence.active_key_site_count || 0))}</dd>
                            </div>
                            <div className="flex justify-between gap-3">
                              <dt>{t('admin.subscriptions.snapshot_status_metric', {}, 'Snapshot')}</dt>
                              <dd className="font-semibold">{translateStatusLabel(billingStatus, t)}</dd>
                            </div>
                            {item.evidence.days_until_end !== null && item.evidence.days_until_end !== undefined ? (
                              <div className="flex justify-between gap-3">
                                <dt>{t('admin.days_until_end_label', {}, 'Days left')}</dt>
                                <dd className="font-semibold tabular-nums">{formatInteger(Number(item.evidence.days_until_end))}</dd>
                              </div>
                            ) : null}
                          </dl>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Link href={item.action_href || `/admin/accounts/${item.account.account_id}`} className="btn btn-primary btn-sm whitespace-nowrap">
                            {translateActionLabel(t, item.recommended_action, item.action_label || t('common.open', {}, 'Open'))}
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-6 py-8">
              <BackofficeStackCard className="space-y-3 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-center justify-between gap-3">
                  <span>{t('admin.coverage_customers_empty', {}, 'No customer service follow-up is visible in this operator snapshot.')}</span>
                  <BackofficeStatusBadge status="ok" label={translateStatusLabel('ok', t)} />
                </div>
                {visibleQueueItems.length === 0 ? (
                  <Link href="/admin/accounts" className="btn btn-secondary btn-sm">
                    {t('admin.coverage_open_customer_register_action', {}, 'Open customer register')}
                  </Link>
                ) : null}
              </BackofficeStackCard>
            </div>
          )}
        </BackofficeSectionPanel>

        <div className="space-y-5">
          <BackofficeSectionPanel className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.coverage_evidence_label', {}, 'Evidence')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.coverage.reason_summary_title', {}, 'Reason summary')}
              </h2>
            </div>
            <div className="space-y-3">
              {reasonEntries.length ? reasonEntries.map(([reasonCode, count]) => (
                <BackofficeStackCard key={reasonCode} className="flex items-center justify-between gap-4">
                  <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
                    {translateReasonShortLabel(t, reasonCode)}
                  </span>
                  <span className="text-lg font-semibold tabular-nums text-slate-950 dark:text-white">
                    {formatInteger(Number(count || 0))}
                  </span>
                </BackofficeStackCard>
              )) : (
                <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
                  {t('admin.coverage.reason_summary_empty', {}, 'No reason codes are visible in this snapshot.')}
                </BackofficeStackCard>
              )}
            </div>
          </BackofficeSectionPanel>
        </div>
      </div>
      ) : (
        <div className="space-y-5">
          <BackofficeSectionPanel className="space-y-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.coverage.package_tab_eyebrow', {}, 'Package catalog')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.coverage_package_catalog_title', {}, 'Package catalog')}
                </h2>
                <p className="mt-2 max-w-3xl text-sm text-slate-600 dark:text-slate-300">
                  {t(
                    'admin.coverage.package_tab_desc',
                    {},
                    'Use this tab to compare package posture. Package maintenance stays in the dedicated package catalog page.'
                  )}
                </p>
              </div>
              <Link href="/admin/plans" className="btn btn-secondary btn-sm">
                {t('admin.coverage_open_package_catalog_action', {}, 'Open package catalog')}
              </Link>
            </div>
            <BackofficeMetricStrip
              columnsClassName="md:grid-cols-3"
              items={[
                {
                  label: t('admin.managed_packages', {}, 'Managed packages'),
                  value: formatInteger(packageRows.length),
                  size: 'compact',
                },
                {
                  label: t('admin.ready_packages', {}, 'Ready packages'),
                  value: formatInteger(readyPackages),
                  size: 'compact',
                },
                {
                  label: t('admin.active_subscriptions', {}, 'Active subscriptions'),
                  value: formatInteger(activePackageSubscriptions),
                  size: 'compact',
                },
              ]}
            />
          </BackofficeSectionPanel>

          <div className="grid gap-4 xl:grid-cols-3">
            {packageRows.map((row) => (
              <BackofficeStackCard key={row.shell.tier_id} className="flex flex-col">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {row.sourceTier.label || row.shell.label || row.shell.tier_id}
                    </p>
                    <h3 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{row.name}</h3>
                  </div>
                  <BackofficeStatusBadge
                    status={row.item?.plan?.status === 'active' ? 'published' : 'draft'}
                    label={row.item?.plan?.status === 'active' ? t('status.published', {}, 'published') : t('status.draft', {}, 'missing')}
                  />
                </div>
                <dl className="mt-5 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                  <div className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 dark:border-slate-800">
                    <dt>{t('admin.site_limit', {}, 'Site limit')}</dt>
                    <dd className="font-semibold tabular-nums text-slate-950 dark:text-white">
                      {formatInteger(numericValue(row.sourceTier.site_limit))}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 dark:border-slate-800">
                    <dt>{t('billing.runs', {}, 'Runs')}</dt>
                    <dd className="font-semibold tabular-nums text-slate-950 dark:text-white">
                      {formatInteger(numericValue(row.budgets.max_runs_per_period))}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 dark:border-slate-800">
                    <dt>{t('admin.concurrency', {}, 'Concurrency')}</dt>
                    <dd className="font-semibold tabular-nums text-slate-950 dark:text-white">
                      {formatInteger(numericValue(row.concurrency.max_active_runs))}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 dark:border-slate-800">
                    <dt>{t('admin.batch_ceiling', {}, 'Batch ceiling')}</dt>
                    <dd className="font-semibold tabular-nums text-slate-950 dark:text-white">
                      {formatInteger(numericValue(row.sourceTier.max_batch_items))}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4 pb-2">
                    <dt>{t('admin.active_subscriptions', {}, 'Active subscriptions')}</dt>
                    <dd className="font-semibold tabular-nums text-slate-950 dark:text-white">
                      {formatInteger(Number(row.item?.subscription_counts?.active || 0))}
                    </dd>
                  </div>
                </dl>
                <p className="mt-3 flex-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {row.sourceTier.usage_band || t('admin.package_usage_band_empty', {}, 'No usage band summary is attached.')}
                </p>
                <div className="mt-5">
                  {row.planId ? (
                    <Link href={`/admin/plans/${row.planId}`} className="btn btn-secondary btn-sm">
                      {t('common.manage', {}, 'Manage')}
                    </Link>
                  ) : (
                    <Link href="/admin/plans" className="btn btn-secondary btn-sm">
                      {t('admin.create_package_shell', {}, 'Create package')}
                    </Link>
                  )}
                </div>
              </BackofficeStackCard>
            ))}
          </div>
        </div>
      )}
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
