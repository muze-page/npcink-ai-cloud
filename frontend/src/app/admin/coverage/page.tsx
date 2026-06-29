'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
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

function AdminCoverageContent() {
  const { t } = useLocale();
  const [queue, setQueue] = useState<CoverageWorkQueue | null>(null);
  const [error, setError] = useState('');
  const [view, setView] = useState<QueueView>('needs_action');

  useEffect(() => {
    let alive = true;

    const loadCoverage = async () => {
      setError('');
      try {
        const payload = await readJsonData<CoverageWorkQueue>('/api/admin/coverage-work-queue');
        if (!alive) return;
        setQueue(payload);
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

  const visibleItems = useMemo(() => {
    const rawItems = (queue?.items || []).filter(
      (item) => !isInternalCoverageRecord(item.account.account_id, item.account.name)
    );
    return rawItems.filter((item) => {
      if (view === 'all') return true;
      if (view === 'needs_action') return item.severity === 'error' || item.severity === 'warning';
      return item.severity === view;
    });
  }, [queue?.items, view]);

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

  if (!queue) {
    return <LoadingFallback />;
  }

  const summary = queue.summary || {};
  const filters: Array<{ value: QueueView; label: string; count: number }> = [
    {
      value: 'needs_action',
      label: t('admin.coverage.filter_needs_action', {}, 'Needs action'),
      count: Number(summary.needs_action || 0),
    },
    { value: 'error', label: translateStatusLabel('error', t), count: Number(summary.error || 0) },
    { value: 'warning', label: translateStatusLabel('warning', t), count: Number(summary.warning || 0) },
    { value: 'ok', label: translateStatusLabel('ok', t), count: Number(summary.ok || 0) },
    {
      value: 'all',
      label: t('common.all', {}, 'All'),
      count: Number(summary.total || queue.items?.length || 0),
    },
  ];
  const reasonEntries = Object.entries(summary.reason_counts || {})
    .sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0))
    .slice(0, 6);

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.coverage_surface_title', {}, 'Customer service status')}
        description={t(
          'admin.coverage_surface_desc',
          {},
          'Work from the highest-impact customer first. Each row shows the current blocker, evidence, and the next operator action.'
        )}
        actions={
          <Link href="/admin/plans" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
            {t('admin.coverage_open_package_catalog_action', {}, 'Open package catalog')} →
          </Link>
        }
        aside={
          <div className="w-full xl:w-[44rem]">
            <BackofficeMetricStrip
              columnsClassName="md:grid-cols-4"
              items={[
                {
                  label: t('admin.coverage.metric_needs_action', {}, 'Needs action'),
                  value: formatInteger(Number(summary.needs_action || 0)),
                  size: 'compact',
                },
                {
                  label: translateStatusLabel('error', t),
                  value: formatInteger(Number(summary.error || 0)),
                  size: 'compact',
                },
                {
                  label: translateStatusLabel('warning', t),
                  value: formatInteger(Number(summary.warning || 0)),
                  size: 'compact',
                },
                {
                  label: t('admin.coverage.metric_aligned', {}, 'Aligned'),
                  value: formatInteger(Number(summary.ok || 0)),
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
                            {item.package?.coverage_state || t('common.unknown', {}, 'Unknown')}
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
                <Link href="/admin/accounts" className="btn btn-secondary btn-sm">
                  {t('admin.coverage_open_customer_register_action', {}, 'Open customer register')}
                </Link>
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

          <BackofficeSectionPanel className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.secondary_detail', {}, 'Secondary detail')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.coverage.related_surfaces_title', {}, 'Related surfaces')}
              </h2>
            </div>
            <div className="grid gap-2">
              <Link href="/admin/accounts" className="btn btn-secondary btn-sm justify-center">
                {t('admin.coverage_open_customer_register_action', {}, 'Open customer register')}
              </Link>
              <Link href="/admin/subscriptions" className="btn btn-secondary btn-sm justify-center">
                {t('admin.coverage_open_subscription_queue_action', {}, 'Open subscription queue')}
              </Link>
            </div>
          </BackofficeSectionPanel>
        </div>
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
