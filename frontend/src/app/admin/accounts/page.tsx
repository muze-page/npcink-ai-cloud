'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ConfirmModal } from '@/components/ui/Modal';
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
} from '@/components/backoffice/BackofficeScaffold';

interface Account {
  account_id: string;
  name: string;
  display_name: string;
  operator_note: string;
  account_status_note: string;
  account_status_updated_at: string;
  status: string;
  member_count: number;
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
  member_count?: number;
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

type PendingConfirmation = {
  title: string;
  message: string;
  confirmLabel: string;
  showSuspendReason?: boolean;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

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
    member_count: item.member_count || 0,
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

function getAccountPriority(account: Account): number {
  const remaining = daysUntil(account.nearest_expiry);
  if (account.status === 'suspended') {
    return 0;
  }
  if (remaining !== null && remaining >= 0 && remaining <= EXPIRY_ACTION_WINDOW_DAYS) {
    return 1;
  }
  if (account.subscription_count === 0 && account.site_count > 0) {
    return 2;
  }
  return 4;
}

function accountNeedsAction(account: Account): boolean {
  const remaining = daysUntil(account.nearest_expiry);
  return (
    account.status === 'suspended' ||
    (remaining !== null && remaining >= 0 && remaining <= EXPIRY_ACTION_WINDOW_DAYS) ||
    (account.subscription_count === 0 && account.site_count > 0) ||
    account.package_kind === 'dev_baseline'
  );
}

function getAccountNextStep(
  account: Account,
  t: (key: string, params?: Record<string, string>, fallback?: string) => string
): { label: string; tone: 'error' | 'warning' | 'muted' | 'ok'; isAction: boolean } {
  const remaining = daysUntil(account.nearest_expiry);
  if (account.status === 'suspended') {
    return {
      label: t('admin.accounts.next_review_status', {}, 'Review status'),
      tone: 'error',
      isAction: true,
    };
  }
  if (remaining !== null && remaining >= 0 && remaining <= EXPIRY_ACTION_WINDOW_DAYS) {
    return {
      label: t('admin.accounts.next_review_package', {}, 'Review package'),
      tone: 'warning',
      isAction: true,
    };
  }
  if (account.subscription_count === 0 && account.site_count > 0) {
    return {
      label: t('admin.accounts.next_assign_package', {}, 'Assign package'),
      tone: 'warning',
      isAction: true,
    };
  }
  if (account.package_kind === 'dev_baseline') {
    return {
      label: t('admin.accounts.next_confirm_package', {}, 'Confirm package'),
      tone: 'muted',
      isAction: true,
    };
  }
  return {
    label: t('admin.accounts.next_ok', {}, 'OK'),
    tone: 'ok',
    isAction: false,
  };
}

function nextStepClassName(tone: 'error' | 'warning' | 'muted' | 'ok'): string {
  switch (tone) {
    case 'error':
      return 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200';
    case 'warning':
      return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200';
    case 'muted':
      return 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200';
    case 'ok':
    default:
      return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200';
  }
}

function AccountsContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [accountActionId, setAccountActionId] = useState<string | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [suspendReason, setSuspendReason] = useState('');
  const [filters, setFilters] = useState({
    q: searchParams.get('q') || '',
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
    operator_display_name: '',
    operator_note: '',
    bind_default_free: true,
  });
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [needsActionOnly, setNeedsActionOnly] = useState(false);
  const [showInternalAccounts, setShowInternalAccounts] = useState(false);

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
      member_ref: '',
      expires_before: '',
      coverage_state: '',
      package_kind: '',
      top_plan_id: '',
    });
    setNeedsActionOnly(false);
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
      }
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setIsSaving(false);
    }
  };

  const handleAccountStatusMutation = async (account: Account, action: 'suspend' | 'restore') => {
    setAccountActionId(account.account_id);
    setNotice(null);
    setActionError(null);
    try {
      const response = await fetch(`/api/admin/accounts/${encodeURIComponent(account.account_id)}/${action}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: action === 'suspend' ? suspendReason.trim() : '',
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('error.failed_save', {}, 'Failed to save.'));
      }
      const nextStatus = String(payload.data?.status || (action === 'restore' ? 'active' : 'suspended'));
      const metadata = payload.data?.metadata && typeof payload.data.metadata === 'object'
        ? payload.data.metadata
        : {};
      setAccounts((current) =>
        current.map((item) =>
          item.account_id === account.account_id
            ? {
                ...item,
                status: nextStatus,
                account_status_note: String(metadata.account_status_note || item.account_status_note || ''),
                account_status_updated_at: String(metadata.account_status_updated_at || item.account_status_updated_at || ''),
              }
            : item
        )
      );
      setNotice(
        action === 'restore'
          ? t('admin.accounts.account_restored_notice', { account: account.display_name }, `${account.display_name} has been restored.`)
          : t('admin.accounts.account_suspended_notice', { account: account.display_name }, `${account.display_name} has been suspended.`)
      );
    } catch (err) {
      setActionError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setAccountActionId(null);
      setSuspendReason('');
    }
  };

  const requestAccountStatusMutation = (account: Account) => {
    const action = account.status === 'suspended' ? 'restore' : 'suspend';
    setSuspendReason('');
    setPendingConfirmation({
      title:
        action === 'restore'
          ? t('admin.accounts.confirm_restore_title', {}, 'Confirm account restore')
          : t('admin.accounts.confirm_suspend_title', {}, 'Confirm account suspension'),
      message:
        action === 'restore'
          ? t(
              'admin.accounts.confirm_restore_desc',
              { account: account.display_name },
              `Restore ${account.display_name} to active access?`
            )
          : t(
              'admin.accounts.confirm_suspend_desc',
              { account: account.display_name },
              `Suspend ${account.display_name}? Customer portal access and site actions will be blocked by account status.`
            ),
      confirmLabel:
        action === 'restore'
          ? t('admin.accounts.restore_account_action', {}, 'Restore account')
          : t('admin.accounts.suspend_account_action', {}, 'Suspend account'),
      showSuspendReason: action === 'suspend',
      variant: action === 'suspend' ? 'danger' : 'default',
      onConfirm: () => void handleAccountStatusMutation(account, action),
    });
  };

  const hiddenAccounts = useMemo(() => accounts.filter(isHiddenByDefaultAccount), [accounts]);
  const visibleAccounts = useMemo(
    () => (showInternalAccounts ? accounts : accounts.filter((account) => !isHiddenByDefaultAccount(account))),
    [accounts, showInternalAccounts]
  );
  const searchedAccounts = useMemo(() => {
    const query = filters.q.trim().toLowerCase();
    if (!query) {
      return visibleAccounts;
    }
    return visibleAccounts.filter((account) =>
      [
        account.display_name,
        account.name,
        account.account_id,
        account.operator_note,
        account.display_package_label,
        account.top_plan || '',
      ]
        .join(' ')
        .toLowerCase()
        .includes(query)
    );
  }, [filters.q, visibleAccounts]);
  const queuedAccounts = useMemo(() => {
    const scopedAccounts = needsActionOnly ? searchedAccounts.filter(accountNeedsAction) : searchedAccounts;
    return [...scopedAccounts].sort((left, right) => {
      const priorityDiff = getAccountPriority(left) - getAccountPriority(right);
      if (priorityDiff !== 0) {
        return priorityDiff;
      }
      const leftDays = daysUntil(left.nearest_expiry) ?? Number.POSITIVE_INFINITY;
      const rightDays = daysUntil(right.nearest_expiry) ?? Number.POSITIVE_INFINITY;
      return leftDays - rightDays;
    });
  }, [searchedAccounts, needsActionOnly]);

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

  const activeAccounts = visibleAccounts.filter((account) => account.status === 'active').length;
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
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_group_commercial_ops', {}, 'Commercial Ops')}
        title={t('admin.accounts.list_title', {}, 'Users')}
        description={t(
          'admin.accounts.list_desc',
          {},
          'Review users, current packages, site count, and the next required action.'
        )}
        aside={(
          <div className="w-full xl:w-[46rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('admin.accounts.total_users', {}, 'Users'), value: formatInteger(visibleAccounts.length), size: 'compact' },
                { label: t('status.active'), value: formatInteger(activeAccounts), size: 'compact' },
                { label: t('common.sites'), value: formatInteger(sitesTotal), size: 'compact' },
                {
                  label: t('common.subscriptions'),
                  value: formatInteger(subscriptionsTotal),
                  size: 'compact',
                },
                {
                  label: t('admin.accounts.needs_action', {}, 'Needs action'),
                  value: formatInteger(needsActionCount),
                  size: 'compact',
                },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-5"
            />
          </div>
        )}
      >
        <p className="max-w-3xl text-sm text-slate-600 dark:text-slate-300">{postureConclusion}</p>
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
              {formatInteger(queuedAccounts.length)} / {formatInteger(visibleAccounts.length)}
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
            {actionError ? <p className="text-sm text-red-600 dark:text-red-300 md:col-span-3">{actionError}</p> : null}
          </form>
        ) : notice || actionError ? (
          <div className="border-b border-slate-200/80 px-6 py-3 text-sm dark:border-slate-800">
            {notice ? <p className="text-emerald-700 dark:text-emerald-300">{notice}</p> : null}
            {actionError ? <p className="text-red-600 dark:text-red-300">{actionError}</p> : null}
          </div>
        ) : null}
        <div className="space-y-3 border-b border-slate-200/80 bg-white px-6 py-4 dark:border-slate-800 dark:bg-slate-950/20">
          <div className="grid gap-3 md:grid-cols-[minmax(12rem,1.2fr)_minmax(10rem,0.8fr)_minmax(10rem,0.8fr)_minmax(10rem,0.8fr)_auto_auto] md:items-end">
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
            <button
              type="button"
              onClick={() => setNeedsActionOnly((value) => !value)}
              className={cn(
                'h-11 rounded-xl border px-4 text-sm font-semibold transition',
                needsActionOnly
                  ? 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200'
                  : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
              )}
            >
              {t('admin.accounts.needs_action_filter', { count: formatInteger(needsActionCount) }, `Needs action (${formatInteger(needsActionCount)})`)}
            </button>
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
            <summary className="inline-flex cursor-pointer items-center text-sm font-medium text-slate-600 hover:text-slate-950 dark:text-slate-300 dark:hover:text-white">
              {t('admin.accounts.more_filters', {}, 'More filters')}
            </summary>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
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
        {queuedAccounts.length === 0 ? (
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
                  <th scope="col" className="w-[15%] px-4 py-3 font-semibold">{t('admin.accounts.footprint_column', {}, 'Sites / members')}</th>
                  <th scope="col" className="w-[15%] px-4 py-3 font-semibold">{t('admin.nearest_expiry')}</th>
                  <th scope="col" className="w-[12%] px-4 py-3 font-semibold">{t('admin.next_step', {}, 'Next step')}</th>
                  <th scope="col" className="w-[8rem] px-6 py-3 text-right font-semibold">{t('common.actions', {}, 'Actions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200/80 dark:divide-slate-800">
            {queuedAccounts.map((account) => {
              const remaining = daysUntil(account.nearest_expiry);
              const nextStep = getAccountNextStep(account, t);

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
                          members: formatInteger(account.member_count),
                        },
                        `${formatInteger(account.site_count)} sites · ${formatInteger(account.member_count)} members`
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
                  <td className="px-4 py-4">
                    {nextStep.isAction ? (
                      <span className={cn('inline-flex whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-semibold', nextStepClassName(nextStep.tone))}>
                        {nextStep.label}
                      </span>
                    ) : (
                      <span className="text-sm text-slate-400 dark:text-slate-500">{nextStep.label}</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => requestAccountStatusMutation(account)}
                        className={cn(
                          'btn btn-secondary btn-sm whitespace-nowrap',
                          account.status === 'suspended' ? '' : 'border-amber-200 text-amber-700 hover:border-amber-300 dark:border-amber-900/60 dark:text-amber-200'
                        )}
                        disabled={accountActionId === account.account_id}
                      >
                        {accountActionId === account.account_id
                          ? t('common.saving', {}, 'Saving...')
                          : account.status === 'suspended'
                            ? t('admin.accounts.restore_account_action', {}, 'Restore account')
                            : t('admin.accounts.suspend_account_action', {}, 'Suspend account')}
                      </button>
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
      <ConfirmModal
        isOpen={Boolean(pendingConfirmation)}
        title={pendingConfirmation?.title}
        message={pendingConfirmation?.message || ''}
        confirmLabel={pendingConfirmation?.confirmLabel || t('common.confirm', {}, 'Confirm')}
        cancelLabel={t('common.cancel', {}, 'Cancel')}
        variant={pendingConfirmation?.variant || 'default'}
        onClose={() => setPendingConfirmation(null)}
        onConfirm={() => {
          pendingConfirmation?.onConfirm();
        }}
      >
        {pendingConfirmation?.showSuspendReason ? (
          <label className="block text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
              {t('admin.accounts.suspend_reason_label', {}, 'Suspension reason')}
            </span>
            <input
              type="text"
              value={suspendReason}
              onChange={(event) => setSuspendReason(event.target.value)}
              maxLength={200}
              placeholder={t('admin.accounts.suspend_reason_placeholder', {}, 'Optional short note for internal follow-up')}
              className="input"
            />
          </label>
        ) : null}
      </ConfirmModal>
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
