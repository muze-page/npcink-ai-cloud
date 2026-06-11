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
import { formatDate, formatNumber as formatInteger } from '@/lib/utils';

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

  const accountItems = state.accounts.slice(0, 4);
  const subscriptionRisks = state.subscriptions
    .filter(isSubscriptionRisk)
    .slice(0, 4);
  const siteFollowUps = state.sites.filter(isSiteFollowUp).slice(0, 4);

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

      <div className="grid gap-5 xl:grid-cols-3">
        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('common.accounts', {}, 'Customers')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.coverage_customers_followup_title', {}, 'Customers needing coverage follow-up')}
            </h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.coverage_customers_followup_desc',
                {},
                'Only customers with site footprint and missing package coverage appear here.'
              )}
            </p>
          </div>
          <div className="space-y-3">
            {accountItems.length ? (
              accountItems.map((item) => (
                <BackofficeStackCard key={item.account.account_id}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold text-slate-950 dark:text-white">{item.account.name || item.account.account_id}</p>
                      <BackofficeIdentifier value={item.account.account_id} className="mt-1 text-xs text-slate-500 dark:text-slate-400" />
                      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                        {item.display_package_label || t('admin.coverage_state_uncovered', {}, 'Uncovered')}
                      </p>
                    </div>
                    <BackofficeStatusBadge
                      status={item.coverage_state || 'warning'}
                      label={translateCoverageStateLabel(t, (item.coverage_state as CustomerCoverageState) || 'uncovered')}
                    />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Link href={`/admin/accounts/${item.account.account_id}`} className="btn btn-secondary btn-sm">
                      {t('admin.coverage_open_customer_action', {}, 'Open customer')}
                    </Link>
                  </div>
                </BackofficeStackCard>
              ))
            ) : (
              <BackofficeStackCard className="space-y-3 text-sm text-slate-600 dark:text-slate-300">
                <div className="flex items-center justify-between gap-3">
                  <span>{t('admin.coverage_customers_empty', {}, 'No uncovered customers are visible in this operator snapshot.')}</span>
                  <BackofficeStatusBadge status="ok" label={translateStatusLabel('ok', t)} />
                </div>
                <Link href="/admin/accounts" className="btn btn-secondary btn-sm">
                  {t('admin.coverage_open_customer_register_action', {}, 'Open customer register')}
                </Link>
              </BackofficeStackCard>
            )}
          </div>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('common.subscriptions', {}, 'Subscriptions')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.coverage_subscription_risks_title', {}, 'Subscription risks')}
            </h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.coverage_subscription_risks_desc',
                {},
                'Shows non-active subscriptions, near-term expiry, or billing snapshot gaps.'
              )}
            </p>
          </div>
          <div className="space-y-3">
            {subscriptionRisks.length ? (
              subscriptionRisks.map((item) => (
                <BackofficeStackCard key={item.subscription.subscription_id}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <BackofficeIdentifier value={item.subscription.subscription_id} className="text-sm font-semibold text-slate-950 dark:text-white" />
                      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                        {item.billing_snapshot_status?.summary ||
                          item.account?.name ||
                          item.subscription.account_id ||
                          t('common.not_found')}
                      </p>
                    </div>
                    <BackofficeStatusBadge
                      status={item.subscription.status || item.billing_snapshot_status?.status || 'warning'}
                      label={translateStatusLabel(item.subscription.status || item.billing_snapshot_status?.status || 'warning', t)}
                    />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Link href={`/admin/subscriptions/${item.subscription.subscription_id}`} className="btn btn-secondary btn-sm">
                      {t('admin.coverage_open_subscription_detail_action', {}, 'Inspect detail')}
                    </Link>
                  </div>
                </BackofficeStackCard>
              ))
            ) : (
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
              {t('common.sites', {}, 'Sites')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.coverage_sites_followup_title', {}, 'Sites needing follow-up')}
            </h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.coverage_sites_followup_desc',
                {},
                'Shows sites with inactive status, missing coverage, blocked subscription state, or no active site key.'
              )}
            </p>
          </div>
          <div className="space-y-3">
            {siteFollowUps.length ? (
              siteFollowUps.map((item) => (
                <BackofficeStackCard key={item.site.site_id}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold text-slate-950 dark:text-white">{item.site.name || item.site.site_id}</p>
                      <BackofficeIdentifier value={item.site.site_id} className="mt-1 text-xs text-slate-500 dark:text-slate-400" />
                      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                        {item.coverage?.covered_by_subscription_id || item.site.account_id || t('common.not_found')}
                      </p>
                    </div>
                    <BackofficeStatusBadge
                      status={item.coverage?.coverage_state === 'uncovered' ? 'warning' : item.site.status || 'warning'}
                      label={
                        item.coverage?.coverage_state === 'uncovered'
                          ? translateCoverageStateLabel(t, 'uncovered')
                          : translateStatusLabel(item.site.status || 'warning', t)
                      }
                    />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Link href={`/admin/sites/${item.site.site_id}`} className="btn btn-secondary btn-sm">
                      {t('admin.coverage_open_site_detail_action', {}, 'Inspect detail')}
                    </Link>
                  </div>
                </BackofficeStackCard>
              ))
            ) : (
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
