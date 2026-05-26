'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveAdminPackageLabel } from '@/lib/admin-plan-copy';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  cn,
  formatCompactNumber as formatCompact,
  formatDate,
  formatNumber as formatInteger,
} from '@/lib/utils';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';

interface Site {
  site_id: string;
  account_id: string;
  site_name: string;
  status: string;
  member_count: number;
  key_count: number;
  coverage_status: string;
  covered_by_subscription_id: string;
  plan_id: string;
  package_alias: string;
  current_period_end: string;
  recent_usage?: {
    requests: number;
    tokens: number;
  };
}

interface SitesApiItem {
  site?: {
    site_id?: string;
    account_id?: string;
    name?: string;
    status?: string;
  };
  member_count?: number;
  active_key_count?: number;
  coverage?: {
    covered_by_subscription_id?: string;
    subscription_status?: string;
    plan_id?: string;
    package_alias?: string;
    current_period_end_at?: string | null;
  };
  recent_usage?: {
    event_count?: number;
    quantity_total?: number;
  };
}

function normalizeSite(item: SitesApiItem): Site | null {
  const site = item.site;
  if (!site?.site_id || !site.account_id) {
    return null;
  }

  return {
    site_id: site.site_id,
    account_id: site.account_id,
    site_name: site.name || site.site_id,
    status: site.status || 'inactive',
    member_count: item.member_count || 0,
    key_count: item.active_key_count || 0,
    coverage_status: item.coverage?.subscription_status || 'missing',
    covered_by_subscription_id: item.coverage?.covered_by_subscription_id || '',
    plan_id: item.coverage?.plan_id || '',
    package_alias: item.coverage?.package_alias || '',
    current_period_end: item.coverage?.current_period_end_at || '',
    recent_usage: {
      requests: item.recent_usage?.event_count || 0,
      tokens: Math.round(item.recent_usage?.quantity_total || 0),
    },
  };
}

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

function getSitePriority(site: Site): number {
  const remaining = daysUntil(site.current_period_end);
  if (site.coverage_status === 'past_due' || site.coverage_status === 'expired') {
    return 0;
  }
  if (remaining !== null && remaining >= 0 && remaining <= 30) {
    return 1;
  }
  if (site.status === 'suspended') {
    return 2;
  }
  if (site.key_count === 0) {
    return 3;
  }
  return 4;
}

function SitesContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const [sites, setSites] = useState<Site[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    status: searchParams.get('status') || '',
    account_id: searchParams.get('account_id') || '',
    subscription_status: searchParams.get('subscription_status') || '',
    expires_before: searchParams.get('expires_before') || '',
  });

  useEffect(() => {
    const loadSites = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        if (filters.status) params.set('status', filters.status);
        if (filters.account_id) params.set('account_id', filters.account_id);
        if (filters.subscription_status) params.set('subscription_status', filters.subscription_status);
        if (filters.expires_before) params.set('expires_before', filters.expires_before);

        const response = await fetch(`/api/admin/sites?${params.toString()}`, {
          credentials: 'include',
        });

        if (!response.ok) {
          throw new Error(t('error.failed_load'));
        }

        const data = await response.json();
        const normalized = ((data.data?.items || []) as SitesApiItem[])
          .map(normalizeSite)
          .filter((item): item is Site => Boolean(item));
        setSites(normalized);
        setTotal(typeof data.data?.total === 'number' ? data.data.total : normalized.length);
      } catch (err) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadSites();
  }, [filters, t]);

  const handleFilterChange = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const queuedSites = useMemo(() => {
    return [...sites].sort((left, right) => {
      const priorityDiff = getSitePriority(left) - getSitePriority(right);
      if (priorityDiff !== 0) {
        return priorityDiff;
      }
      const leftDays = daysUntil(left.current_period_end) ?? Number.POSITIVE_INFINITY;
      const rightDays = daysUntil(right.current_period_end) ?? Number.POSITIVE_INFINITY;
      return leftDays - rightDays;
    });
  }, [sites]);

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

  const activeSites = sites.filter((site) => site.status === 'active').length;
  const activeKeys = sites.reduce((sum, site) => sum + site.key_count, 0);
  const requestsTotal = sites.reduce((sum, site) => sum + (site.recent_usage?.requests || 0), 0);
  const expiringSoon = sites.filter((site) => {
    const remaining = daysUntil(site.current_period_end);
    return remaining !== null && remaining >= 0 && remaining <= 30;
  }).length;
  const criticalSites = sites.filter(
    (site) => site.coverage_status === 'past_due' || site.coverage_status === 'expired'
  ).length;
  const suspendedSites = sites.filter((site) => site.status === 'suspended').length;
  const noKeySites = sites.filter((site) => site.key_count === 0).length;
  const postureConclusion =
    criticalSites > 0
      ? t(
          'admin.sites.queue_status_error',
          {},
          'Some sites are already under commercial pressure. Resolve past-due or expired subscription coverage first.'
        )
      : expiringSoon > 0 || suspendedSites > 0 || noKeySites > 0
        ? t(
            'admin.sites.queue_status_warning',
            {},
            'Site posture is mixed. Expiry pressure, suspended sites, or missing key coverage need follow-up before they widen.'
          )
        : t(
            'admin.sites.queue_status_ok',
            {},
            'Site posture is stable. Use this queue to confirm lower-priority coverage and operator readiness.'
          );
  const filterPills = [
    { value: '', label: t('common.all'), count: total },
    { value: 'past_due', label: t('status.past_due'), count: sites.filter((site) => site.coverage_status === 'past_due').length },
    { value: 'expired', label: t('status.expired'), count: sites.filter((site) => site.coverage_status === 'expired').length },
    { value: 'suspended', label: t('status.suspended'), count: suspendedSites },
    { value: 'active', label: t('status.active'), count: activeSites },
  ];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_group_commercial_ops', {}, 'Commercial Ops')}
        title={t('admin.sites_title')}
        description={postureConclusion}
        aside={(
          <div className="w-full xl:w-[34rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('admin.active_sites'), value: formatInteger(activeSites), size: 'compact' },
                { label: t('admin.expiry_queue'), value: formatInteger(expiringSoon + criticalSites), size: 'compact' },
                { label: t('admin.active_site_keys'), value: formatInteger(activeKeys), size: 'compact' },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-3"
            />
          </div>
        )}
      >
        <div className="flex flex-wrap gap-2">
          {filterPills.map((pill) => (
            <button
              key={pill.value || 'all'}
              type="button"
              onClick={() =>
                pill.value === 'past_due' || pill.value === 'expired'
                  ? handleFilterChange('subscription_status', pill.value)
                  : handleFilterChange('status', pill.value === 'active' || pill.value === 'suspended' ? pill.value : '')
              }
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-medium transition',
                (pill.value === 'past_due' || pill.value === 'expired'
                  ? filters.subscription_status === pill.value
                  : filters.status === pill.value || (pill.value === '' && !filters.status && !filters.subscription_status))
                  ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200'
                  : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white'
              )}
            >
              {pill.label} · {formatInteger(pill.count)}
            </button>
          ))}
        </div>
      </BackofficePrimaryPanel>

      <BackofficeSectionPanel className="space-y-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.sites.queue_filters_label', {}, 'Queue filters')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.sites.queue_filters_title', {}, 'Filter the current site follow-up queue')}
            </h2>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              {t(
                'admin.sites.queue_filters_desc',
                {},
                'Keep filters compact. The main job here is to decide which site needs follow-up next, not to browse a register.'
              )}
            </p>
          </div>
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {formatCompact(requestsTotal)} {t('common.requests')}
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.status')}</span>
            <select
              value={filters.status}
              onChange={(event) => handleFilterChange('status', event.target.value)}
              className="input"
            >
              <option value="">{t('common.all')}</option>
              <option value="active">{t('status.active')}</option>
              <option value="inactive">{t('status.inactive')}</option>
              <option value="suspended">{t('status.suspended')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.account')}</span>
            <input
              type="text"
              value={filters.account_id}
              onChange={(event) => handleFilterChange('account_id', event.target.value)}
              placeholder={t('common.account')}
              className="input"
            />
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.subscription')}</span>
            <select
              value={filters.subscription_status}
              onChange={(event) => handleFilterChange('subscription_status', event.target.value)}
              className="input"
            >
              <option value="">{t('common.all')}</option>
              <option value="active">{t('status.active')}</option>
              <option value="trialing">{t('status.trialing')}</option>
              <option value="canceled">{t('status.canceled')}</option>
              <option value="expired">{t('status.expired')}</option>
              <option value="past_due">{t('status.past_due')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.expires_before')}</span>
            <input
              type="date"
              value={filters.expires_before}
              onChange={(event) => handleFilterChange('expires_before', event.target.value)}
              className="input"
            />
          </label>
        </div>
      </BackofficeSectionPanel>

      <BackofficeSectionPanel className="overflow-hidden p-0">
        <div className="border-b border-gray-200 px-6 py-5 dark:border-gray-800">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {t('admin.sites.queue_label', {}, 'Site follow-up queue')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
            {t('admin.sites.queue_title', {}, 'Which sites need operator follow-up next?')}
          </h2>
        </div>
        {queuedSites.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-gray-600 dark:text-gray-400">
            {t('common.sites')} {t('common.not_found')}
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-800">
            {queuedSites.map((site) => {
              const remaining = daysUntil(site.current_period_end);
              const riskTone =
                site.coverage_status === 'past_due' || site.coverage_status === 'expired'
                  ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200'
                  : remaining !== null && remaining >= 0 && remaining <= 30
                    ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200'
                    : site.status === 'suspended' || site.key_count === 0
                      ? 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
                      : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200';
              const reason =
                site.coverage_status === 'past_due'
                  ? t('admin.sites.reason_past_due', {}, 'Subscription billing is already in follow-up and may affect this site.')
                  : site.coverage_status === 'expired'
                    ? t('admin.sites.reason_expired', {}, 'Commercial coverage has ended and needs renewal or closure handling.')
                    : remaining !== null && remaining >= 0 && remaining <= 30
                      ? t('admin.sites.reason_expiring', {}, 'This site is approaching subscription expiry and should be reviewed before support load increases.')
                      : site.status === 'suspended'
                        ? t('admin.sites.reason_suspended', {}, 'This site is suspended and needs account or support review.')
                        : site.key_count === 0
                          ? t('admin.sites.reason_keys', {}, 'No active site keys are attached, so runtime access posture may be incomplete.')
                          : t('admin.sites.reason_ok', {}, 'This site is stable and remains here as lower-priority posture context.');

              return (
                <article key={site.site_id} className="px-6 py-5">
                  <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_0.85fr_auto] xl:items-center">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-gray-950 dark:text-white">
                          {site.site_name || site.site_id}
                        </h3>
                        <BackofficeStatusBadge status={site.status} label={t(`status.${site.status}`, undefined, site.status)} />
                        <BackofficeStatusBadge
                          status={site.coverage_status}
                          label={t(`status.${site.coverage_status}`, undefined, site.coverage_status)}
                        />
                        <span className={cn('rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em]', riskTone)}>
                          {site.coverage_status === 'past_due' || site.coverage_status === 'expired'
                            ? t('admin.risk', {}, 'Risk')
                            : t('admin.next_step', {}, 'Next step')}
                        </span>
                      </div>
                      <BackofficeIdentifier value={site.site_id} className="mt-2 block text-xs text-gray-500 dark:text-gray-400" />
                      <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{reason}</p>
                      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-gray-600 dark:text-gray-400">
                        <Link href={`/admin/accounts/${site.account_id}`} className="text-blue-600 hover:underline dark:text-blue-300">
                          <BackofficeIdentifier value={site.account_id} className="text-sm text-blue-600 dark:text-blue-300" />
                        </Link>
                        <span>
                          {resolveAdminPackageLabel(t, {
                            planId: site.plan_id,
                            packageAlias: site.package_alias,
                            fallback: site.package_alias || site.plan_id,
                          }) || t('common.unknown')}
                        </span>
                        <span>{formatInteger(site.member_count)} {t('common.members')}</span>
                      </div>
                    </div>

                    <div className="space-y-2 text-sm">
                      <div>
                        <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">
                          {t('admin.expiry_queue')}
                        </p>
                        <p className="mt-1 text-gray-700 dark:text-gray-300">
                          {site.current_period_end ? formatDate(site.current_period_end) : t('common.not_available', {}, 'N/A')}
                        </p>
                        {remaining !== null ? (
                          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            {remaining >= 0
                              ? t('admin.days_until_end', { days: String(remaining) })
                              : t('admin.sites.days_past_end', { days: String(Math.abs(remaining)) }, `${Math.abs(remaining)} days past end`)}
                          </p>
                        ) : null}
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">
                          {t('admin.active_site_keys')}
                        </p>
                        <p className="mt-1 font-semibold text-gray-950 dark:text-white">{formatInteger(site.key_count)}</p>
                        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                          {formatCompact(site.recent_usage?.requests || 0)} {t('common.requests')}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-start gap-3 xl:justify-end">
                      {(site.coverage_status === 'past_due' || site.coverage_status === 'expired') ? (
                        <Link href="/admin/subscriptions" className="btn btn-secondary">
                          {t('admin.review_coverage', {}, 'Review coverage')}
                        </Link>
                      ) : null}
                      <Link href={`/admin/accounts/${site.account_id}`} className="btn btn-secondary">
                        {t('common.account')}
                      </Link>
                      <Link href={`/admin/sites/${site.site_id}`} className="btn btn-primary">
                        {t('common.view')}
                      </Link>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function AdminSitesPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <SitesContent />
    </Suspense>
  );
}
