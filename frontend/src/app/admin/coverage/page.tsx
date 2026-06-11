'use client';

import React, { Suspense, useEffect, useState } from 'react';
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
import {
  translateCoverageStateLabel,
  type CoverageState as CustomerCoverageState,
} from '@/lib/customer-package-display';
import { resolveUiErrorMessage } from '@/lib/errors';
import { translateStatusLabel } from '@/lib/status-display';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';

type CoverageAccountItem = {
  account: {
    account_id: string;
    name?: string;
    status?: string;
  };
  coverage_state?: string;
  coverage_follow_up_required?: boolean;
  display_package_label?: string;
  primary_subscription_id?: string;
  site_count?: number;
};

type CoverageSubscriptionItem = {
  subscription: {
    subscription_id: string;
    account_id?: string;
    status?: string;
    current_period_end_at?: string;
  };
  coverage?: {
    coverage_state?: CustomerCoverageState;
    display_package_label?: string;
    subscription_status?: string;
  };
  account?: {
    account_id?: string;
    name?: string;
  };
  covered_sites?: Array<{
    site_id?: string;
    name?: string;
  }>;
  billing_snapshot_status?: {
    status?: string;
    summary?: string;
  };
};

type CoverageSiteItem = {
  site: {
    site_id: string;
    account_id?: string;
    name?: string;
    status?: string;
  };
  active_key_count?: number;
  coverage?: {
    covered_by_subscription_id?: string;
    subscription_status?: string;
    coverage_state?: CustomerCoverageState;
    display_package_label?: string;
  };
  recent_usage?: {
    event_count?: number;
    last_seen_at?: string;
  };
  latest_billing_snapshot?: unknown;
};

type CoverageOverview = {
  generated_at?: string;
  counts?: {
    accounts_total?: number;
    sites_total?: number;
    subscriptions_total?: number;
  };
  attention_subscriptions?: Array<{
    subscription?: { subscription_id?: string; status?: string };
    account?: { account_id?: string };
    site?: { site_id?: string };
    reason?: string;
  }>;
};

type CoverageState = {
  overview: CoverageOverview | null;
  accounts: CoverageAccountItem[];
  subscriptions: CoverageSubscriptionItem[];
  sites: CoverageSiteItem[];
};

type CustomerCoverageQueueItem = {
  accountId: string;
  name: string;
  packageLabel: string;
  reason: string;
  tone: string;
  subscriptionId: string;
  siteCount: number;
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

function daysUntil(raw?: string): number | null {
  if (!raw) return null;
  const ms = new Date(raw).getTime() - Date.now();
  if (Number.isNaN(ms)) return null;
  return Math.ceil(ms / 86400000);
}

function isSubscriptionRisk(item: CoverageSubscriptionItem): boolean {
  const status = String(item.subscription.status || '').toLowerCase();
  const billingStatus = String(item.billing_snapshot_status?.status || '').toLowerCase();
  const remaining = daysUntil(item.subscription.current_period_end_at);
  return (
    (status && !['active', 'trialing'].includes(status)) ||
    ['missing', 'stale'].includes(billingStatus) ||
    (remaining !== null && remaining >= 0 && remaining <= 14)
  );
}

function isSiteFollowUp(item: CoverageSiteItem): boolean {
  const siteStatus = String(item.site.status || '').toLowerCase();
  const coverageState = String(item.coverage?.coverage_state || '').toLowerCase();
  const subscriptionStatus = String(item.coverage?.subscription_status || '').toLowerCase();
  return (
    siteStatus !== 'active' ||
    coverageState === 'uncovered' ||
    ['missing', 'past_due', 'suspended', 'canceled', 'expired'].includes(subscriptionStatus) ||
    Number(item.active_key_count || 0) === 0
  );
}

function translateCoverageReason(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  value?: string
): string {
  const text = String(value || '').trim();
  if (!text) {
    return '';
  }
  if (text === 'Current-period billing snapshots are still missing for at least one covered site.') {
    return t(
      'admin.coverage_reason_billing_snapshot_missing',
      {},
      'At least one covered site is missing the current-period billing snapshot.'
    );
  }
  if (text === 'Current-period billing snapshots need rebuild to match the latest subscription posture.') {
    return t(
      'admin.coverage_reason_billing_snapshot_rebuild',
      {},
      'Current-period billing snapshots need rebuild to match the latest subscription posture.'
    );
  }
  return text;
}

function coverageToneClassName(tone: string): string {
  const normalized = tone.toLowerCase();
  if (['error', 'failed', 'canceled', 'expired'].includes(normalized)) {
    return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-200';
  }
  if (['active', 'ok', 'success', 'covered'].includes(normalized)) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-200';
  }
  return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200';
}

function CoverageInlineStatus({
  status,
  label,
}: {
  status: string;
  label: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 rounded-full border px-2.5 py-1 text-xs font-semibold leading-none',
        coverageToneClassName(status)
      )}
    >
      {label}
    </span>
  );
}

function AdminCoverageContent() {
  const { t } = useLocale();
  const [state, setState] = useState<CoverageState | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;

    const loadCoverage = async () => {
      setError('');
      try {
        const [overview, accountsPayload, subscriptionsPayload, sitesPayload] = await Promise.all([
          readJsonData<CoverageOverview>('/api/admin/overview'),
          readJsonData<{ items?: CoverageAccountItem[] }>('/api/admin/accounts?coverage_state=uncovered'),
          readJsonData<{ items?: CoverageSubscriptionItem[] }>('/api/admin/subscriptions'),
          readJsonData<{ items?: CoverageSiteItem[] }>('/api/admin/sites'),
        ]);

        if (!alive) return;
        setState({
          overview,
          accounts: accountsPayload.items || [],
          subscriptions: subscriptionsPayload.items || [],
          sites: sitesPayload.items || [],
        });
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

  if (!state) {
    return <LoadingFallback />;
  }

  const accountItems = state.accounts
    .filter((item) => !isInternalCoverageRecord(item.account.account_id, item.account.name))
    .slice(0, 4);
  const subscriptionRisks = state.subscriptions
    .filter(isSubscriptionRisk)
    .filter(
      (item) =>
        !isInternalCoverageRecord(
          item.account?.account_id,
          item.account?.name,
          item.subscription.account_id,
          item.subscription.subscription_id
        )
    )
    .slice(0, 4);
  const siteFollowUps = state.sites
    .filter(isSiteFollowUp)
    .filter((item) => !isInternalCoverageRecord(item.site.site_id, item.site.name, item.site.account_id))
    .slice(0, 4);
  const customerQueueEntries: Array<[string, CustomerCoverageQueueItem]> = [
        ...accountItems.map((item): [string, CustomerCoverageQueueItem] => [
          item.account.account_id,
          {
            accountId: item.account.account_id,
            name: item.account.name || item.account.account_id,
            packageLabel: item.display_package_label || t('admin.coverage_state_uncovered', {}, 'Uncovered'),
            reason: t('admin.coverage_reason_missing_package', {}, 'Customer has site footprint without readable package coverage.'),
            tone: 'warning',
            subscriptionId: item.primary_subscription_id || '',
            siteCount: Number(item.site_count || 0),
          },
        ]),
        ...subscriptionRisks.map((item): [string, CustomerCoverageQueueItem] => [
          item.account?.account_id || item.subscription.account_id || item.subscription.subscription_id,
          {
            accountId: item.account?.account_id || item.subscription.account_id || '',
            name: item.account?.name || item.account?.account_id || item.subscription.account_id || item.subscription.subscription_id,
            packageLabel: item.coverage?.display_package_label || t('common.not_available', {}, 'N/A'),
            reason:
              translateCoverageReason(t, item.billing_snapshot_status?.summary) ||
              t('admin.coverage_reason_subscription_risk', {}, 'Subscription status, expiry, or billing snapshot needs review.'),
            tone: item.subscription.status && !['active', 'trialing'].includes(item.subscription.status) ? 'error' : 'warning',
            subscriptionId: item.subscription.subscription_id,
            siteCount: Number(item.covered_sites?.length || 0),
          },
        ]),
      ].filter(([key]) => Boolean(key));
  const customerQueue = Array.from(new Map(customerQueueEntries).values()).slice(0, 6);

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.coverage_surface_title', {}, 'Customer coverage')}
        description={t(
          'admin.coverage_surface_desc',
          {},
          'Keep the operator view centered on one question: which customer is currently covered by which package, and what needs follow-up next.'
        )}
        actions={
          <Link href="/admin/plans" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
            {t('admin.coverage_open_package_catalog_action', {}, 'Open package catalog')} →
          </Link>
        }
        aside={
          <div className="w-full xl:w-[40rem]">
            <BackofficeMetricStrip
              columnsClassName="md:grid-cols-3"
              items={[
                {
                  label: t('common.accounts', {}, 'Customers'),
                  value: formatInteger(Number(state.overview?.counts?.accounts_total || accountItems.length)),
                  size: 'compact',
                },
                {
                  label: t('common.subscriptions', {}, 'Subscriptions'),
                  value: formatInteger(Number(state.overview?.counts?.subscriptions_total || state.subscriptions.length)),
                  size: 'compact',
                },
                {
                  label: t('common.sites', {}, 'Sites'),
                  value: formatInteger(Number(state.overview?.counts?.sites_total || state.sites.length)),
                  size: 'compact',
                },
              ]}
            />
          </div>
        }
      >
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {state.overview?.generated_at
            ? `${t('common.updated_at', {}, 'Updated')}: ${formatDate(state.overview.generated_at)}`
            : t('admin.coverage_surface_runtime_note', {}, 'Coverage reads are assembled from existing customer, subscription, and site detail surfaces.')}
        </p>
      </BackofficePrimaryPanel>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(22rem,0.8fr)]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div>
            <div className="border-b border-slate-200/80 px-6 py-5 dark:border-slate-800">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('common.accounts', {}, 'Customers')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.coverage_customer_queue_title', {}, 'Customer coverage queue')}
              </h2>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                {t(
                  'admin.coverage_customer_queue_desc',
                  {},
                  'Start from the customer. Subscription and site records below are evidence, not separate first-step queues.'
                )}
              </p>
            </div>
          </div>
          {customerQueue.length ? (
            <div className="overflow-x-auto">
              <table className="min-w-[48rem] divide-y divide-slate-200/80 text-left text-sm dark:divide-slate-800 lg:w-full">
                <thead className="bg-slate-50/80 text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-950/30 dark:text-slate-400">
                  <tr>
                    <th className="w-[32%] px-6 py-3 font-semibold">{t('common.account', {}, 'Customer')}</th>
                    <th className="w-[18%] px-4 py-3 font-semibold">{t('common.package', {}, 'Package')}</th>
                    <th className="px-4 py-3 font-semibold">{t('admin.reason', {}, 'Reason')}</th>
                    <th className="w-[9rem] px-6 py-3 text-right font-semibold">{t('common.actions', {}, 'Actions')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200/80 dark:divide-slate-800">
                  {customerQueue.map((item) => (
                    <tr key={`${item.accountId || item.subscriptionId}-${item.reason}`} className="align-top hover:bg-slate-50/70 dark:hover:bg-slate-950/35">
                      <td className="px-6 py-4">
                        <p className="font-semibold text-slate-950 dark:text-white">{item.name}</p>
                        {item.accountId ? (
                          <BackofficeIdentifier value={item.accountId} className="mt-1 text-xs text-slate-500 dark:text-slate-400" />
                        ) : item.subscriptionId ? (
                          <BackofficeIdentifier value={item.subscriptionId} className="mt-1 text-xs text-slate-500 dark:text-slate-400" />
                        ) : null}
                      </td>
                      <td className="px-4 py-4">
                        <p className="font-medium text-slate-900 dark:text-slate-100">{item.packageLabel}</p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {t('admin.coverage_site_count_hint', { count: formatInteger(item.siteCount) }, `${formatInteger(item.siteCount)} sites`)}
                        </p>
                      </td>
                      <td className="px-4 py-4">
                        <div className="max-w-xl space-y-2">
                          <CoverageInlineStatus status={item.tone} label={translateStatusLabel(item.tone, t)} />
                          <p className="text-slate-600 dark:text-slate-300">{item.reason}</p>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-right">
                        {item.accountId ? (
                          <Link href={`/admin/accounts/${item.accountId}`} className="btn btn-primary btn-sm whitespace-nowrap">
                            {t('admin.coverage_open_customer_action', {}, 'Open customer')}
                          </Link>
                        ) : item.subscriptionId ? (
                          <Link href={`/admin/subscriptions/${item.subscriptionId}`} className="btn btn-secondary btn-sm whitespace-nowrap">
                            {t('admin.coverage_open_subscription_detail_action', {}, 'Inspect detail')}
                          </Link>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            ) : (
              <div className="px-6 py-8">
              <BackofficeStackCard className="space-y-3 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-center justify-between gap-3">
                  <span>{t('admin.coverage_customers_empty', {}, 'No uncovered customers are visible in this operator snapshot.')}</span>
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
                {t('admin.coverage_subscription_risks_title', {}, 'Subscription risks')}
              </h2>
            </div>
            <div className="space-y-3">
              {subscriptionRisks.length ? subscriptionRisks.map((item) => (
                <BackofficeStackCard key={item.subscription.subscription_id}>
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <BackofficeIdentifier value={item.subscription.subscription_id} className="text-sm font-semibold text-slate-950 dark:text-white" />
                      <CoverageInlineStatus
                      status={item.subscription.status || item.billing_snapshot_status?.status || 'warning'}
                      label={translateStatusLabel(item.subscription.status || item.billing_snapshot_status?.status || 'warning', t)}
                    />
                    </div>
                    <p className="text-sm text-slate-600 dark:text-slate-300">
                      {translateCoverageReason(t, item.billing_snapshot_status?.summary) ||
                        item.account?.name ||
                        item.subscription.account_id ||
                        t('common.not_found')}
                    </p>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Link href={`/admin/subscriptions/${item.subscription.subscription_id}`} className="btn btn-secondary btn-sm">
                      {t('admin.coverage_open_subscription_detail_action', {}, 'Inspect detail')}
                    </Link>
                  </div>
                </BackofficeStackCard>
              )) : (
              <BackofficeStackCard className="space-y-3 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-center justify-between gap-3">
                  <span>{t('admin.coverage_subscriptions_empty', {}, 'No subscription risk is visible in this operator snapshot.')}</span>
                  <BackofficeStatusBadge status="ok" label={translateStatusLabel('ok', t)} />
                </div>
                <Link href="/admin/subscriptions" className="btn btn-secondary btn-sm">
                  {t('admin.coverage_open_subscription_queue_action', {}, 'Open subscription queue')}
                </Link>
              </BackofficeStackCard>
            )}
            </div>
          </BackofficeSectionPanel>

          <BackofficeSectionPanel className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.coverage_evidence_label', {}, 'Evidence')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.coverage_sites_followup_title', {}, 'Sites needing follow-up')}
              </h2>
            </div>
            <div className="space-y-3">
              {siteFollowUps.length ? siteFollowUps.map((item) => (
                <BackofficeStackCard key={item.site.site_id}>
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold text-slate-950 dark:text-white">{item.site.name || item.site.site_id}</p>
                      <CoverageInlineStatus
                      status={item.coverage?.coverage_state === 'uncovered' ? 'warning' : item.site.status || 'warning'}
                      label={
                        item.coverage?.coverage_state === 'uncovered'
                          ? translateCoverageStateLabel(t, 'uncovered')
                          : translateStatusLabel(item.site.status || 'warning', t)
                      }
                    />
                    </div>
                    <BackofficeIdentifier value={item.site.site_id} className="text-xs text-slate-500 dark:text-slate-400" />
                    <p className="text-sm text-slate-600 dark:text-slate-300">
                      {item.coverage?.covered_by_subscription_id || item.site.account_id || t('common.not_found')}
                    </p>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Link href={`/admin/sites/${item.site.site_id}`} className="btn btn-secondary btn-sm">
                      {t('admin.coverage_open_site_detail_action', {}, 'Inspect detail')}
                    </Link>
                  </div>
                </BackofficeStackCard>
              )) : (
              <BackofficeStackCard className="space-y-3 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-center justify-between gap-3">
                  <span>{t('admin.coverage_sites_empty', {}, 'No site-level coverage follow-up is visible in this operator snapshot.')}</span>
                  <BackofficeStatusBadge status="ok" label={translateStatusLabel('ok', t)} />
                </div>
                <Link href="/admin/accounts" className="btn btn-secondary btn-sm">
                  {t('admin.coverage_open_customer_register_action', {}, 'Open customer register')}
                </Link>
              </BackofficeStackCard>
            )}
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
