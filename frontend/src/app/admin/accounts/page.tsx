'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { CustomerAdminTabs } from '@/components/admin/CustomerAdminTabs';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import {
  resolveCustomerPackageDisplay,
  translateCoverageStateLabel,
  translatePackageKindLabel,
  type PackageKind,
  type CoverageState,
} from '@/lib/customer-package-display';
import { formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
} from '@/components/backoffice/BackofficeScaffold';

interface Account {
  account_id: string;
  name: string;
  display_name: string;
  operator_note: string;
  account_status_note: string;
  account_status_updated_at: string;
  status: string;
  site_count: number;
  subscription_count: number;
  top_plan?: string;
  display_package_label: string;
  package_kind: PackageKind;
  coverage_state: CoverageState;
  coverage_follow_up_required: boolean;
  nearest_expiry?: string;
}

interface AccountsApiItem {
  account?: {
    account_id?: string;
    name?: string;
    status?: string;
    metadata?: Record<string, unknown>;
  };
  site_count?: number;
  active_subscription_count?: number;
  top_plan_id?: string;
  display_package_label?: string;
  package_kind?: PackageKind;
  coverage_state?: CoverageState;
  coverage_follow_up_required?: boolean;
  package_alias?: string;
  plan_kind?: string;
  nearest_expiry_at?: string | null;
}

const MALFORMED_ACCOUNT_TEXT_RE = /Fatal error|Stack trace|Command line code|Uncaught ValueError|Path must not be empty/i;
const INTERNAL_TEST_ACCOUNT_RE = /(^|[_-])(smoke)([_-]|$)|codex_image_smoke|site_knowledge_smoke/i;

function isMalformedAccountText(value?: string): boolean {
  return MALFORMED_ACCOUNT_TEXT_RE.test(String(value || ''));
}

function prettifyAccountId(accountId: string): string {
  if (isMalformedAccountText(accountId)) {
    return '';
  }
  const stripped = accountId
    .replace(/^acct[_-]?/i, '')
    .replace(/^site[_-]?/i, '')
    .replace(/[_-]+/g, ' ')
    .trim();
  if (!stripped) {
    return accountId;
  }
  return stripped
    .split(/\s+/)
    .map((word) => {
      const lower = word.toLowerCase();
      if (lower === 'ai') return 'AI';
      if (lower === 'api') return 'API';
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(' ');
}

function isRawAccountName(value: string, accountId: string): boolean {
  const trimmed = value.trim();
  return !trimmed || trimmed === accountId || /^acct[_-]/i.test(trimmed) || isMalformedAccountText(trimmed);
}

function isHiddenByDefaultAccount(account: Account): boolean {
  const searchable = [account.account_id, account.name, account.display_name].join(' ');
  return isMalformedAccountText(searchable) || INTERNAL_TEST_ACCOUNT_RE.test(searchable);
}

function normalizeAccount(
  item: AccountsApiItem,
  t: (key: string, params?: Record<string, string>, fallback?: string) => string
): Account | null {
  const account = item.account;

  if (!account?.account_id) {
    return null;
  }
  const metadata = account.metadata || {};
  const operatorDisplayName = String(metadata.operator_display_name || '').trim();
  const operatorNote = String(metadata.operator_note || '').trim();
  const accountStatusNote = String(metadata.account_status_note || '').trim();
  const accountStatusUpdatedAt = String(metadata.account_status_updated_at || '').trim();
  const rawName = String(account.name || '').trim();
  const safeName = rawName && !isRawAccountName(rawName, account.account_id) ? rawName : '';
  const fallbackDisplayName = isMalformedAccountText(`${account.account_id} ${rawName}`)
    ? t('admin.accounts.malformed_account_label', {}, 'Malformed account record')
    : prettifyAccountId(account.account_id);

  const packageDisplay = resolveCustomerPackageDisplay(t, {
    planId: item.top_plan_id,
    packageAlias: item.package_alias,
    planKind: item.plan_kind,
    packageKind: item.package_kind,
    coverageState: item.coverage_state,
  });

  return {
    account_id: account.account_id,
    name: safeName || rawName || account.account_id,
    display_name: operatorDisplayName || safeName || fallbackDisplayName || account.account_id,
    operator_note: operatorNote,
    account_status_note: accountStatusNote,
    account_status_updated_at: accountStatusUpdatedAt,
    status: account.status || 'inactive',
    site_count: item.site_count || 0,
    subscription_count: item.active_subscription_count || 0,
    top_plan: item.top_plan_id || '',
    display_package_label: item.display_package_label || packageDisplay.display_package_label,
    package_kind: packageDisplay.package_kind,
    coverage_state: packageDisplay.coverage_state,
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

const EXPIRY_ACTION_WINDOW_DAYS = 14;

function accountNeedsAction(account: Account): boolean {
  const remaining = daysUntil(account.nearest_expiry);
  return (
    account.status === 'suspended' ||
    (remaining !== null && remaining >= 0 && remaining <= EXPIRY_ACTION_WINDOW_DAYS) ||
    (account.subscription_count === 0 && account.site_count > 0) ||
    account.package_kind === 'dev_baseline'
  );
}

function AccountsContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [filters, setFilters] = useState({
    q: searchParams.get('q') || '',
    status: searchParams.get('status') || '',
    expires_before: searchParams.get('expires_before') || '',
    coverage_state: searchParams.get('coverage_state') || '',
    package_kind: searchParams.get('package_kind') || '',
    top_plan_id: searchParams.get('top_plan_id') || '',
  });
  const [createForm, setCreateForm] = useState({
    account_id: '',
    name: '',
    operator_display_name: '',
    operator_note: '',
    bind_default_free: true,
  });
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [showInternalAccounts, setShowInternalAccounts] = useState(false);

  useEffect(() => {
    const loadAccounts = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const params = new URLSearchParams();
        if (filters.q.trim()) params.set('q', filters.q.trim());
        if (filters.status) params.set('status', filters.status);
        if (filters.expires_before) params.set('expires_before', filters.expires_before);
        if (filters.coverage_state) params.set('coverage_state', filters.coverage_state);
        if (filters.package_kind) params.set('package_kind', filters.package_kind);
        if (filters.top_plan_id) params.set('top_plan_id', filters.top_plan_id);
        params.set('sort', 'display_name');

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

  const clearFilters = () => {
    setFilters({
      status: '',
      q: '',
      expires_before: '',
      coverage_state: '',
      package_kind: '',
      top_plan_id: '',
    });
  };

  const handleCreateAccount = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSaving(true);
    setNotice(null);
    setError(null);

    try {
      const metadata = {
        ...(createForm.operator_display_name.trim()
          ? { operator_display_name: createForm.operator_display_name.trim() }
          : {}),
        ...(createForm.operator_note.trim() ? { operator_note: createForm.operator_note.trim() } : {}),
      };
      const response = await fetch('/api/admin/accounts', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: createForm.account_id,
          name: createForm.name,
          metadata,
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
      setCreateForm({
        account_id: '',
        name: '',
        operator_display_name: '',
        operator_note: '',
        bind_default_free: true,
      });
      setIsCreateOpen(false);
      const params = new URLSearchParams();
      if (filters.q.trim()) params.set('q', filters.q.trim());
      if (filters.status) params.set('status', filters.status);
      if (filters.expires_before) params.set('expires_before', filters.expires_before);
      if (filters.coverage_state) params.set('coverage_state', filters.coverage_state);
      if (filters.package_kind) params.set('package_kind', filters.package_kind);
      if (filters.top_plan_id) params.set('top_plan_id', filters.top_plan_id);
      params.set('sort', 'display_name');
      const refresh = await fetch(`/api/admin/accounts?${params.toString()}`, { credentials: 'include' });
      if (refresh.ok) {
        const data = await refresh.json();
        const normalized = ((data.data?.items || []) as AccountsApiItem[])
          .map((item) => normalizeAccount(item, t))
          .filter((item): item is Account => Boolean(item));
        setAccounts(normalized);
      }
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setIsSaving(false);
    }
  };

  const hiddenAccounts = useMemo(() => accounts.filter(isHiddenByDefaultAccount), [accounts]);
  const visibleAccounts = useMemo(
    () => (showInternalAccounts ? accounts : accounts.filter((account) => !isHiddenByDefaultAccount(account))),
    [accounts, showInternalAccounts]
  );
  const listedAccounts = useMemo(
    () => [...visibleAccounts].sort((left, right) => left.display_name.localeCompare(right.display_name)),
    [visibleAccounts]
  );

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

  const suspendedAccounts = visibleAccounts.filter((account) => account.status === 'suspended').length;
  const sitesTotal = visibleAccounts.reduce((sum, account) => sum + account.site_count, 0);
  const subscriptionsTotal = visibleAccounts.reduce((sum, account) => sum + account.subscription_count, 0);
  const expiringSoon = visibleAccounts.filter((account) => {
    const remaining = daysUntil(account.nearest_expiry);
    return remaining !== null && remaining >= 0 && remaining <= EXPIRY_ACTION_WINDOW_DAYS;
  }).length;
  const noCoverageAccounts = visibleAccounts.filter((account) => account.coverage_state === 'uncovered' && account.site_count > 0).length;
  const needsActionCount = visibleAccounts.filter(accountNeedsAction).length;
  const postureConclusion =
    suspendedAccounts > 0
      ? t(
          'admin.accounts.queue_status_error',
          {},
          'Some customers are already suspended and need operator follow-up before the broader queue.'
        )
      : expiringSoon > 0 || noCoverageAccounts > 0
        ? t(
            'admin.accounts.queue_status_warning',
            {},
            'Customer posture is mixed. Expiry pressure or missing coverage should be reviewed before it turns into site-level support work.'
          )
        : t(
            'admin.accounts.queue_status_ok',
            {},
            'Customer posture is stable.'
          );
  return (
    <BackofficePageStack>
      <CustomerAdminTabs />
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_group_commercial_ops', {}, 'Commercial Ops')}
        title={t('admin.accounts.list_title', {}, 'Users')}
        description={t(
          'admin.accounts.list_desc',
          {},
          'Review customers, current packages, and site footprint before opening details.'
        )}
        aside={(
          <div className="w-full xl:w-[46rem]">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {[
                { label: t('admin.accounts.total_users', {}, 'Users'), value: formatInteger(visibleAccounts.length) },
                { label: t('common.sites'), value: formatInteger(sitesTotal) },
                { label: t('common.subscriptions'), value: formatInteger(subscriptionsTotal) },
              ].map((item) => (
                <div
                  key={item.label}
                  className="rounded-[1.1rem] border border-slate-200/80 bg-white/80 px-4 py-3.5 dark:border-slate-800 dark:bg-slate-950/45"
                >
                  <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {item.label}
                  </p>
                  <p className="mt-2 text-base font-semibold leading-6 text-gray-950 dark:text-white">{item.value}</p>
                </div>
              ))}
              <Link
                href="/admin/coverage"
                prefetch={false}
                className="rounded-[1.1rem] border border-blue-200 bg-blue-50/80 px-4 py-3.5 text-blue-800 transition hover:border-blue-300 hover:bg-blue-100/80 dark:border-blue-900/60 dark:bg-blue-950/35 dark:text-blue-100 dark:hover:border-blue-700 dark:hover:bg-blue-950/55"
              >
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em]">
                  {t('admin.accounts.metric_service_followup', {}, 'Service follow-up')}
                </p>
                <p className="mt-2 text-base font-semibold leading-6">{formatInteger(needsActionCount)}</p>
                <p className="mt-1 text-xs leading-5 text-blue-700 dark:text-blue-200">
                  {t('admin.accounts.metric_service_followup_detail', {}, 'Open queue')}
                </p>
              </Link>
            </div>
          </div>
        )}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <p className="max-w-3xl text-sm text-slate-600 dark:text-slate-300">{postureConclusion}</p>
        </div>
      </BackofficePrimaryPanel>

      <BackofficeSectionPanel className="overflow-hidden p-0">
        <div className="flex flex-col gap-4 border-b border-gray-200 px-6 py-5 dark:border-gray-800 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.accounts.table_label', {}, 'User list')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.accounts.table_title', {}, 'Users and current packages')}
            </h2>
            <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              {formatInteger(listedAccounts.length)} / {formatInteger(visibleAccounts.length)}
            </p>
          </div>
          <button type="button" onClick={() => setIsCreateOpen((value) => !value)} className="btn btn-primary self-start">
            {isCreateOpen ? t('common.close', {}, 'Close') : t('admin.accounts.add_user', {}, 'Add user')}
          </button>
        </div>
        {isCreateOpen ? (
          <form onSubmit={handleCreateAccount} className="grid gap-3 border-b border-slate-200/80 bg-slate-50/70 px-6 py-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end dark:border-slate-800 dark:bg-slate-950/35">
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
            <label className="text-sm md:col-span-2">
              <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                {t('admin.accounts.operator_display_name_label', {}, 'Operator name')}
              </span>
              <input
                type="text"
                value={createForm.operator_display_name}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, operator_display_name: event.target.value }))
                }
                placeholder={t(
                  'admin.accounts.operator_display_name_placeholder',
                  {},
                  'Short name shown in admin lists'
                )}
                className="input"
              />
            </label>
            <label className="text-sm">
              <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                {t('admin.accounts.operator_note_label', {}, 'Operator note')}
              </span>
              <input
                type="text"
                value={createForm.operator_note}
                onChange={(event) => setCreateForm((current) => ({ ...current, operator_note: event.target.value }))}
                placeholder={t('admin.accounts.operator_note_placeholder', {}, 'Internal follow-up note')}
                className="input"
              />
            </label>
            <button type="submit" className="btn btn-primary md:col-start-3 md:row-start-1" disabled={isSaving}>
              {isSaving
                ? t('common.saving', {}, 'Saving...')
                : t('admin.accounts.create_customer_account', {}, 'Create customer account')}
            </button>
            <label className="flex items-center gap-3 text-sm text-slate-700 dark:text-slate-200 md:col-span-3">
              <input
                type="checkbox"
                checked={createForm.bind_default_free}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, bind_default_free: event.target.checked }))
                }
              />
              <span>{t('admin.accounts.bind_default_free_label', {}, 'Bind formal Free package on create')}</span>
            </label>
            {notice ? <p className="text-sm text-emerald-700 dark:text-emerald-300 md:col-span-3">{notice}</p> : null}
          </form>
        ) : notice ? (
          <div className="border-b border-slate-200/80 px-6 py-3 text-sm dark:border-slate-800">
            <p className="text-emerald-700 dark:text-emerald-300">{notice}</p>
          </div>
        ) : null}
        <div className="space-y-3 border-b border-slate-200/80 bg-white px-6 py-4 dark:border-slate-800 dark:bg-slate-950/20">
          <div className="grid gap-3 md:grid-cols-[minmax(12rem,1.2fr)_minmax(10rem,0.8fr)_minmax(10rem,0.8fr)_minmax(10rem,0.8fr)_auto] md:items-end">
            <label className="text-sm">
              <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                {t('admin.accounts.search_label', {}, 'Search')}
              </span>
              <input
                type="search"
                value={filters.q}
                onChange={(event) => handleFilterChange('q', event.target.value)}
                placeholder={t(
                  'admin.accounts.search_placeholder',
                  {},
                  'Name, account ID, package, or note'
                )}
                className="input"
              />
            </label>
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
                <option value="formal_free">{t('admin.plan_package_alias_free', {}, 'Free')}</option>
                <option value="tier_package">{t('admin.tier_template_binding', {}, 'Tier-bound plan')}</option>
                <option value="dev_baseline">{t('admin.dev_baseline', {}, 'Dev baseline')}</option>
              </select>
            </label>
            <button type="button" onClick={clearFilters} className="btn btn-secondary h-11">
              {t('common.clear_filters', {}, 'Clear filters')}
            </button>
          </div>
          {hiddenAccounts.length > 0 ? (
            <div className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between">
              <span>
                {t(
                  'admin.accounts.hidden_internal_records_note',
                  { count: formatInteger(hiddenAccounts.length) },
                  `${formatInteger(hiddenAccounts.length)} smoke or malformed records are hidden by default.`
                )}
              </span>
              <button
                type="button"
                className="btn btn-secondary btn-sm self-start sm:self-auto"
                onClick={() => setShowInternalAccounts((value) => !value)}
              >
                {showInternalAccounts
                  ? t('admin.accounts.hide_internal_records', {}, 'Hide test records')
                  : t(
                      'admin.accounts.show_internal_records',
                      { count: formatInteger(hiddenAccounts.length) },
                      `Show test records (${formatInteger(hiddenAccounts.length)})`
                    )}
              </button>
            </div>
          ) : null}
          <details className="group">
            <summary className="inline-flex cursor-pointer items-center rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm font-medium text-slate-600 hover:border-slate-300 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:text-white">
              {t('admin.accounts.more_filters', {}, 'More filters')}
            </summary>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
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
          </details>
        </div>
        {listedAccounts.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-gray-600 dark:text-gray-400">
            {t('common.accounts')} {t('common.not_found')}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-[58rem] divide-y divide-slate-200/80 text-left text-sm dark:divide-slate-800 lg:w-full">
              <thead className="bg-slate-50/80 text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-950/30 dark:text-slate-400">
                <tr>
                  <th scope="col" className="w-[30%] px-6 py-3 font-semibold">{t('admin.accounts.user_column', {}, 'User')}</th>
                  <th scope="col" className="w-[20%] px-4 py-3 font-semibold">{t('common.package', {}, 'Package')}</th>
                  <th scope="col" className="w-[15%] px-4 py-3 font-semibold">{t('admin.accounts.footprint_column', {}, 'Sites')}</th>
                  <th scope="col" className="w-[15%] px-4 py-3 font-semibold">{t('admin.nearest_expiry')}</th>
                  <th scope="col" className="w-[8rem] px-6 py-3 text-right font-semibold">{t('common.actions', {}, 'Actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200/80 dark:divide-slate-800">
            {listedAccounts.map((account) => {
              const remaining = daysUntil(account.nearest_expiry);

              return (
                <tr key={account.account_id} className="align-top hover:bg-slate-50/70 dark:hover:bg-slate-950/35">
                  <td className="px-6 py-4">
                    <div className="min-w-0">
                      <Link href={`/admin/accounts/${account.account_id}`} className="line-clamp-1 font-semibold text-blue-700 hover:text-blue-900 dark:text-blue-300 dark:hover:text-blue-200">
                          {account.display_name}
                      </Link>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <BackofficeIdentifier value={account.account_id} className="text-xs text-gray-500 dark:text-gray-400" />
                        {account.status !== 'active' ? (
                          <BackofficeStatusBadge status={account.status} label={t(`status.${account.status}`, undefined, account.status)} />
                        ) : null}
                      </div>
                      {account.operator_note ? (
                        <p className="mt-2 line-clamp-1 text-xs text-slate-500 dark:text-slate-400">
                          {t('admin.accounts.internal_note_prefix', {}, 'Internal note')}: {account.operator_note}
                        </p>
                      ) : null}
                      {account.account_status_note ? (
                        <p className="mt-1 line-clamp-1 text-xs text-amber-700 dark:text-amber-300">
                          {t('admin.accounts.suspend_reason_label', {}, 'Suspension reason')}: {account.account_status_note}
                        </p>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900 dark:text-slate-100">{account.display_package_label}</p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {translatePackageKindLabel(t, account.package_kind)}
                        {' · '}
                        {translateCoverageStateLabel(t, account.coverage_state)}
                      </p>
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <p className="font-medium tabular-nums text-slate-900 dark:text-slate-100">
                      {t(
                        'admin.accounts.footprint_value',
                        {
                          sites: formatInteger(account.site_count),
                        },
                        `${formatInteger(account.site_count)} sites`
                      )}
                    </p>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {account.subscription_count
                        ? t(
                            'admin.accounts.subscription_count_value',
                            { count: formatInteger(account.subscription_count) },
                            `${formatInteger(account.subscription_count)} subscriptions`
                          )
                        : t('admin.accounts.no_subscription_count', {}, 'No subscription')}
                    </p>
                  </td>
                  <td className="px-4 py-4">
                    <div className="min-w-0 text-slate-700 dark:text-slate-300">
                      <p>{account.nearest_expiry ? formatDate(account.nearest_expiry) : t('common.not_available', {}, 'N/A')}</p>
                      {remaining !== null ? (
                        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                          {remaining >= 0
                            ? t('admin.days_until_end', { days: String(remaining) })
                            : t('admin.accounts.days_past_end', { days: String(Math.abs(remaining)) }, `${Math.abs(remaining)} days past end`)}
                        </p>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex flex-wrap justify-end gap-2">
                      <Link href={`/admin/accounts/${account.account_id}`} className="btn btn-primary btn-sm whitespace-nowrap">
                        {t('common.details', {}, 'Details')}
                      </Link>
                    </div>
                  </td>
                </tr>
              );
            })}
              </tbody>
            </table>
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
