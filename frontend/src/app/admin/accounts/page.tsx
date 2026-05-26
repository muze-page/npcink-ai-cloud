'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import {
  resolveCustomerPackageDisplay,
  translateCoverageStateLabel,
  translatePackageKindLabel,
  type PackageKind,
  type CoverageState,
} from '@/lib/customer-package-display';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';

interface Account {
  account_id: string;
  name: string;
  status: string;
  member_count: number;
  site_count: number;
  subscription_count: number;
  top_plan?: string;
  display_package_label: string;
  package_kind: PackageKind;
  coverage_state: CoverageState;
  primary_subscription_id?: string;
  coverage_follow_up_required: boolean;
  nearest_expiry?: string;
}

interface AccountsApiItem {
  account?: {
    account_id?: string;
    name?: string;
    status?: string;
  };
  member_count?: number;
  site_count?: number;
  active_subscription_count?: number;
  top_plan_id?: string;
  display_package_label?: string;
  package_kind?: PackageKind;
  coverage_state?: CoverageState;
  primary_subscription_id?: string;
  coverage_follow_up_required?: boolean;
  package_alias?: string;
  plan_kind?: string;
  nearest_expiry_at?: string | null;
}

function normalizeAccount(
  item: AccountsApiItem,
  t: (key: string, params?: Record<string, string>, fallback?: string) => string
): Account | null {
  const account = item.account;

  if (!account?.account_id) {
    return null;
  }

  const packageDisplay = resolveCustomerPackageDisplay(t, {
    planId: item.top_plan_id,
    packageAlias: item.package_alias,
    planKind: item.plan_kind,
    packageKind: item.package_kind,
    coverageState: item.coverage_state,
  });

  return {
    account_id: account.account_id,
    name: account.name || account.account_id,
    status: account.status || 'inactive',
    member_count: item.member_count || 0,
    site_count: item.site_count || 0,
    subscription_count: item.active_subscription_count || 0,
    top_plan: item.top_plan_id || '',
    display_package_label: item.display_package_label || packageDisplay.display_package_label,
    package_kind: packageDisplay.package_kind,
    coverage_state: packageDisplay.coverage_state,
    primary_subscription_id: item.primary_subscription_id || '',
    coverage_follow_up_required: Boolean(item.coverage_follow_up_required),
    nearest_expiry: item.nearest_expiry_at || undefined,
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

function getAccountPriority(account: Account): number {
  const remaining = daysUntil(account.nearest_expiry);
  if (account.status === 'suspended') {
    return 0;
  }
  if (remaining !== null && remaining >= 0 && remaining <= 30) {
    return 1;
  }
  if (account.subscription_count === 0 && account.site_count > 0) {
    return 2;
  }
  if (account.member_count === 0) {
    return 3;
  }
  return 4;
}

function AccountsContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [filters, setFilters] = useState({
    status: searchParams.get('status') || '',
    member_ref: searchParams.get('member_ref') || '',
    expires_before: searchParams.get('expires_before') || '',
    coverage_state: searchParams.get('coverage_state') || '',
    package_kind: searchParams.get('package_kind') || '',
    top_plan_id: searchParams.get('top_plan_id') || '',
  });
  const [createForm, setCreateForm] = useState({
    account_id: '',
    name: '',
    bind_default_free: true,
  });

  useEffect(() => {
    const loadAccounts = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        if (filters.status) params.set('status', filters.status);
        if (filters.member_ref) params.set('member_ref', filters.member_ref);
        if (filters.expires_before) params.set('expires_before', filters.expires_before);
        if (filters.coverage_state) params.set('coverage_state', filters.coverage_state);
        if (filters.package_kind) params.set('package_kind', filters.package_kind);
        if (filters.top_plan_id) params.set('top_plan_id', filters.top_plan_id);

        const response = await fetch(`/api/admin/accounts?${params.toString()}`, {
          credentials: 'include',
        });

        if (!response.ok) {
          throw new Error(t('error.failed_load'));
        }

        const data = await response.json();
        const normalized = ((data.data?.items || []) as AccountsApiItem[])
          .map((item) => normalizeAccount(item, t))
          .filter((item): item is Account => Boolean(item));
        setAccounts(normalized);
        setTotal(typeof data.data?.total === 'number' ? data.data.total : normalized.length);
      } catch (err) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadAccounts();
  }, [filters, t]);

  const handleFilterChange = (key: string, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const handleCreateAccount = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSaving(true);
    setNotice(null);
    setError(null);

    try {
      const response = await fetch('/api/admin/accounts', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: createForm.account_id,
          name: createForm.name,
          bind_default_free: createForm.bind_default_free,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('error.failed_save', {}, 'Failed to save.'));
      }
      setNotice(
        createForm.bind_default_free
          ? t(
              'admin.accounts.onboarding_created_notice',
              {},
              'Customer account created and bound to the Free package.'
            )
          : t(
              'admin.accounts.account_created_notice',
              {},
              'Account created without automatic subscription coverage.'
            )
      );
      setCreateForm({ account_id: '', name: '', bind_default_free: true });
      const params = new URLSearchParams();
      if (filters.status) params.set('status', filters.status);
      if (filters.member_ref) params.set('member_ref', filters.member_ref);
      if (filters.expires_before) params.set('expires_before', filters.expires_before);
      if (filters.coverage_state) params.set('coverage_state', filters.coverage_state);
      if (filters.package_kind) params.set('package_kind', filters.package_kind);
      if (filters.top_plan_id) params.set('top_plan_id', filters.top_plan_id);
      const refresh = await fetch(`/api/admin/accounts?${params.toString()}`, { credentials: 'include' });
      if (refresh.ok) {
        const data = await refresh.json();
        const normalized = ((data.data?.items || []) as AccountsApiItem[])
          .map((item) => normalizeAccount(item, t))
          .filter((item): item is Account => Boolean(item));
        setAccounts(normalized);
        setTotal(typeof data.data?.total === 'number' ? data.data.total : normalized.length);
      }
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setIsSaving(false);
    }
  };

  const queuedAccounts = useMemo(() => {
    return [...accounts].sort((left, right) => {
      const priorityDiff = getAccountPriority(left) - getAccountPriority(right);
      if (priorityDiff !== 0) {
        return priorityDiff;
      }
      const leftDays = daysUntil(left.nearest_expiry) ?? Number.POSITIVE_INFINITY;
      const rightDays = daysUntil(right.nearest_expiry) ?? Number.POSITIVE_INFINITY;
      return leftDays - rightDays;
    });
  }, [accounts]);

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

  const activeAccounts = accounts.filter((account) => account.status === 'active').length;
  const suspendedAccounts = accounts.filter((account) => account.status === 'suspended').length;
  const sitesTotal = accounts.reduce((sum, account) => sum + account.site_count, 0);
  const subscriptionsTotal = accounts.reduce((sum, account) => sum + account.subscription_count, 0);
  const expiringSoon = accounts.filter((account) => {
    const remaining = daysUntil(account.nearest_expiry);
    return remaining !== null && remaining >= 0 && remaining <= 30;
  }).length;
  const noCoverageAccounts = accounts.filter((account) => account.coverage_state === 'uncovered' && account.site_count > 0).length;
  const freeAccounts = accounts.filter((account) => account.package_kind === 'formal_free').length;
  const devBaselineAccounts = accounts.filter((account) => account.package_kind === 'dev_baseline').length;
  const noMemberAccounts = accounts.filter((account) => account.member_count === 0).length;
  const postureConclusion =
    suspendedAccounts > 0
      ? t(
          'admin.accounts.queue_status_error',
          {},
          'Some customers are already suspended and need operator follow-up before the broader queue.'
        )
      : expiringSoon > 0 || noCoverageAccounts > 0 || noMemberAccounts > 0
        ? t(
            'admin.accounts.queue_status_warning',
            {},
            'Customer posture is mixed. Expiry pressure or missing coverage should be reviewed before it turns into site-level support work.'
          )
        : t(
            'admin.accounts.queue_status_ok',
            {},
            'Customer posture is stable. Use this queue to confirm lower-priority follow-up and access coverage.'
          );
  const filterPills = [
    { value: '', label: t('common.all'), count: total },
    { value: 'suspended', label: t('status.suspended'), count: suspendedAccounts },
    { value: 'active', label: t('status.active'), count: activeAccounts },
    { value: 'inactive', label: t('status.inactive'), count: accounts.filter((account) => account.status === 'inactive').length },
  ];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_group_commercial_ops', {}, 'Commercial Ops')}
        title={t('admin.accounts_title')}
        description={postureConclusion}
        aside={(
          <div className="w-full xl:w-[46rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('status.active'), value: formatInteger(activeAccounts), size: 'compact' },
                { label: t('admin.expiry_queue'), value: formatInteger(expiringSoon), size: 'compact' },
                { label: t('common.subscriptions'), value: formatInteger(subscriptionsTotal), size: 'compact' },
                {
                  label: t('admin.no_commercial_coverage', {}, 'No commercial coverage'),
                  value: formatInteger(noCoverageAccounts),
                  size: 'compact',
                },
                {
                  label: t('admin.plan_package_alias_starter', {}, 'Free'),
                  value: formatInteger(freeAccounts),
                  size: 'compact',
                },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-5"
            />
          </div>
        )}
      >
        <div className="flex flex-wrap gap-2">
          {filterPills.map((pill) => (
            <button
              key={pill.value || 'all'}
              type="button"
              onClick={() => handleFilterChange('status', pill.value)}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-medium transition',
                filters.status === pill.value || (pill.value === '' && !filters.status)
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
        <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.accounts.onboarding_label', {}, 'Customer onboarding')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.accounts.onboarding_title', {}, 'Create customer account with explicit coverage posture')}
            </h2>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              {t(
                'admin.accounts.onboarding_desc',
                {},
                'Use this form when a new customer account should start on the formal Free package. Turn it off only for ops or exceptional uncovered accounts.'
              )}
            </p>
          </div>
          <form onSubmit={handleCreateAccount} className="grid gap-3 rounded-2xl border border-slate-200/80 bg-white/80 p-4 dark:border-slate-800 dark:bg-slate-950/55">
            <label className="text-sm">
              <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                {t('admin.account_id', {}, 'Account ID')}
              </span>
              <input
                type="text"
                value={createForm.account_id}
                onChange={(event) => setCreateForm((current) => ({ ...current, account_id: event.target.value }))}
                placeholder="acct_customer_free"
                className="input"
                required
              />
            </label>
            <label className="text-sm">
              <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                {t('common.name', {}, 'Name')}
              </span>
              <input
                type="text"
                value={createForm.name}
                onChange={(event) => setCreateForm((current) => ({ ...current, name: event.target.value }))}
                placeholder={t('admin.accounts.customer_name_placeholder', {}, 'Customer Account')}
                className="input"
                required
              />
            </label>
            <label className="flex items-start gap-3 rounded-2xl border border-slate-200/80 px-4 py-3 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-200">
              <input
                type="checkbox"
                checked={createForm.bind_default_free}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, bind_default_free: event.target.checked }))
                }
                className="mt-1"
              />
              <span>
                {t('admin.accounts.bind_default_free_label', {}, 'Bind formal Free package on create')}
              </span>
            </label>
            <button type="submit" className="btn btn-primary" disabled={isSaving}>
              {isSaving
                ? t('common.saving', {}, 'Saving...')
                : t('admin.accounts.create_customer_account', {}, 'Create customer account')}
            </button>
            {notice ? <p className="text-sm text-emerald-700 dark:text-emerald-300">{notice}</p> : null}
          </form>
        </div>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.accounts.queue_filters_label', {}, 'Queue filters')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.accounts.queue_filters_title', {}, 'Filter the current account follow-up queue')}
            </h2>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              {t(
                'admin.accounts.queue_filters_desc',
                {},
                'Keep filters compact. This page should stay focused on which account needs follow-up next.'
              )}
            </p>
          </div>
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {formatInteger(sitesTotal)} {t('common.sites')}
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
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
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.member_ref')}</span>
            <input
              type="text"
              value={filters.member_ref}
              onChange={(event) => handleFilterChange('member_ref', event.target.value)}
              placeholder={t('admin.member_ref')}
              className="input"
            />
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
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.coverage_state', {}, 'Coverage state')}</span>
            <select
              value={filters.coverage_state}
              onChange={(event) => handleFilterChange('coverage_state', event.target.value)}
              className="input"
            >
              <option value="">{t('common.all')}</option>
              <option value="covered">{t('admin.coverage_state_covered', {}, 'Covered')}</option>
              <option value="uncovered">{t('admin.coverage_state_uncovered', {}, 'Uncovered')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.package_kind', {}, 'Package kind')}</span>
            <select
              value={filters.package_kind}
              onChange={(event) => handleFilterChange('package_kind', event.target.value)}
              className="input"
            >
              <option value="">{t('common.all')}</option>
              <option value="formal_free">{t('admin.plan_package_alias_starter', {}, 'Free')}</option>
              <option value="tier_package">{t('admin.tier_template_binding', {}, 'Tier-bound plan')}</option>
              <option value="dev_baseline">{t('admin.dev_baseline', {}, 'Dev baseline')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.top_plan', {}, 'Top plan')}</span>
            <input
              type="text"
              value={filters.top_plan_id}
              onChange={(event) => handleFilterChange('top_plan_id', event.target.value)}
              placeholder="plan_free"
              className="input"
            />
          </label>
        </div>
      </BackofficeSectionPanel>

      <BackofficeSectionPanel className="overflow-hidden p-0">
        <div className="border-b border-gray-200 px-6 py-5 dark:border-gray-800">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {t('admin.accounts.queue_label', {}, 'Customer follow-up queue')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
            {t('admin.accounts.queue_title', {}, 'Which customers need operator follow-up next?')}
          </h2>
        </div>
        {queuedAccounts.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-gray-600 dark:text-gray-400">
            {t('common.accounts')} {t('common.not_found')}
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-800">
            {queuedAccounts.map((account) => {
              const remaining = daysUntil(account.nearest_expiry);
              const riskTone =
                account.status === 'suspended'
                  ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200'
                  : remaining !== null && remaining >= 0 && remaining <= 30
                    ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200'
                    : account.subscription_count === 0 && account.site_count > 0
                      ? 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
                      : account.member_count === 0
                        ? 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
                        : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200';
              const reason =
                account.status === 'suspended'
                  ? t('admin.accounts.reason_suspended', {}, 'This customer is suspended and needs operator review before broader queue work.')
                  : remaining !== null && remaining >= 0 && remaining <= 30
                    ? t('admin.accounts.reason_expiring', {}, 'Nearest commercial expiry is approaching and should be reviewed before site-level issues appear.')
                    : account.subscription_count === 0 && account.site_count > 0
                      ? t('admin.accounts.reason_no_coverage', {}, 'This customer still has sites but no active subscription coverage.')
                      : account.package_kind === 'dev_baseline'
                        ? t('admin.accounts.reason_dev_baseline', {}, 'This customer currently resolves to a dev baseline and should be checked before treating it as production coverage.')
                      : account.member_count === 0
                        ? t('admin.accounts.reason_no_members', {}, 'This customer has no member footprint and may need access cleanup.')
                        : t('admin.accounts.reason_ok', {}, 'This customer is stable and remains here as lower-priority follow-up context.');

              return (
                <article key={account.account_id} className="px-6 py-5">
                  <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_0.85fr_auto] xl:items-center">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-gray-950 dark:text-white">
                          {account.name || account.account_id}
                        </h3>
                        <BackofficeStatusBadge status={account.status} label={t(`status.${account.status}`, undefined, account.status)} />
                        <span className={cn('rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em]', riskTone)}>
                          {account.status === 'suspended' ? t('admin.risk', {}, 'Risk') : t('admin.next_step', {}, 'Next step')}
                        </span>
                      </div>
                      <BackofficeIdentifier value={account.account_id} className="mt-2 block text-xs text-gray-500 dark:text-gray-400" />
                      <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{reason}</p>
                      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-gray-600 dark:text-gray-400">
                        <span>{formatInteger(account.site_count)} {t('common.sites')}</span>
                        <span>{formatInteger(account.member_count)} {t('common.members')}</span>
                        <span>{formatInteger(account.subscription_count)} {t('common.subscriptions')}</span>
                        <span>{t('common.package', {}, 'Package')}: {account.display_package_label}</span>
                      </div>
                    </div>

                    <div className="space-y-2 text-sm">
                      <div>
                        <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">
                          {t('admin.top_plan')}
                        </p>
                        <p className="mt-1 text-gray-700 dark:text-gray-300">{account.display_package_label}</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <span className="rounded-full border border-slate-200/80 bg-slate-50 px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
                            {translatePackageKindLabel(t, account.package_kind)}
                          </span>
                          <span
                            className={cn(
                              'rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em]',
                              account.coverage_state === 'covered'
                                ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200'
                                : 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200'
                            )}
                          >
                            {translateCoverageStateLabel(t, account.coverage_state)}
                          </span>
                        </div>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">
                          {t('admin.nearest_expiry')}
                        </p>
                        <p className="mt-1 text-gray-700 dark:text-gray-300">
                          {account.nearest_expiry ? formatDate(account.nearest_expiry) : t('common.not_available', {}, 'N/A')}
                        </p>
                        {remaining !== null ? (
                          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                            {remaining >= 0
                              ? t('admin.days_until_end', { days: String(remaining) })
                              : t('admin.accounts.days_past_end', { days: String(Math.abs(remaining)) }, `${Math.abs(remaining)} days past end`)}
                          </p>
                        ) : null}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-start gap-3 xl:justify-end">
                      {account.primary_subscription_id ? (
                        <Link href={`/admin/subscriptions`} className="btn btn-secondary">
                          {t('admin.open_coverage', {}, 'Open coverage')}
                        </Link>
                      ) : null}
                      {account.coverage_follow_up_required ? (
                        <Link href={`/admin/subscriptions`} className="btn btn-secondary">
                          {t('admin.review_coverage', {}, 'Review coverage')}
                        </Link>
                      ) : null}
                      <Link href={`/admin/sites?account_id=${encodeURIComponent(account.account_id)}`} className="btn btn-secondary">
                        {t('common.sites')}
                      </Link>
                      <Link href={`/admin/accounts/${account.account_id}`} className="btn btn-primary">
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

export default function AdminAccountsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AccountsContent />
    </Suspense>
  );
}
