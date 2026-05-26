'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { translateAllowedAction, translateExternalCommercialRole } from '@/lib/admin-display';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  BackofficeEmptyState,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';

type QuickViewId = 'all' | 'coverage_risks' | 'pending_cleanup' | 'dev_baseline_only';

interface MemberQueueAccountSummary {
  account_id: string;
  account_name?: string;
  site_count: number;
  covered_site_count: number;
  sites_needing_follow_up_count: number;
  highlight_site_id?: string;
}

interface MemberQueueItem {
  member_ref: string;
  email: string;
  identity_type?: string;
  allowed_actions?: string[];
  status: string;
  invite_state: string;
  account_count: number;
  accessible_site_count: number;
  sites_needing_follow_up_count: number;
  last_login_at: string;
  dev_baseline: boolean;
  has_coverage_follow_up: boolean;
  never_logged_in: boolean;
  disabled_mapped: boolean;
  primary_account_id: string;
  primary_follow_up_site_id: string;
  primary_impersonation_href: string;
  single_covered_subscription_id: string;
  accounts: MemberQueueAccountSummary[];
}

function formatExternalRoleSet(item: MemberQueueItem, t: (key: string, vars?: Record<string, string>, fallback?: string) => string) {
  return translateExternalCommercialRole(item.identity_type || 'user_admin', t);
}

function formatAllowedActions(item: MemberQueueItem, t: (key: string, vars?: Record<string, string>, fallback?: string) => string) {
  const values = (item.allowed_actions || []).filter(Boolean);
  if (values.length === 0) {
    return t('common.not_found');
  }
  return values.map((action) => translateAllowedAction(action, t)).join(', ');
}

interface MembersSummary {
  total: number;
  members_needing_coverage_follow_up: number;
  never_logged_in_members: number;
  disabled_mapped_members: number;
  members_on_dev_baseline: number;
}

interface MembersFilters {
  view: QuickViewId;
  member_ref: string;
  account_id: string;
  status: string;
  has_coverage_follow_up: string;
  never_logged_in: string;
  disabled: string;
  dev_baseline: string;
}

function normalizeQuickView(value: string | null): QuickViewId {
  if (
    value === 'coverage_risks' ||
    value === 'pending_cleanup' ||
    value === 'dev_baseline_only'
  ) {
    return value;
  }
  return 'all';
}

function buildFilters(searchParams: { get(name: string): string | null }): MembersFilters {
  return {
    view: normalizeQuickView(searchParams.get('view')),
    member_ref: searchParams.get('member_ref') || '',
    account_id: searchParams.get('account_id') || '',
    status: searchParams.get('status') || '',
    has_coverage_follow_up: searchParams.get('has_coverage_follow_up') || '',
    never_logged_in: searchParams.get('never_logged_in') || '',
    disabled: searchParams.get('disabled') || '',
    dev_baseline: searchParams.get('dev_baseline') || '',
  };
}

function buildQueryString(filters: MembersFilters): string {
  const params = new URLSearchParams();
  if (filters.view !== 'all') params.set('view', filters.view);
  if (filters.member_ref) params.set('member_ref', filters.member_ref);
  if (filters.account_id) params.set('account_id', filters.account_id);
  if (filters.status) params.set('status', filters.status);
  if (filters.has_coverage_follow_up) params.set('has_coverage_follow_up', filters.has_coverage_follow_up);
  if (filters.never_logged_in) params.set('never_logged_in', filters.never_logged_in);
  if (filters.disabled) params.set('disabled', filters.disabled);
  if (filters.dev_baseline) params.set('dev_baseline', filters.dev_baseline);
  return params.toString();
}

function applyQuickViewPreset(current: MembersFilters, view: QuickViewId): MembersFilters {
  const next: MembersFilters = {
    ...current,
    view,
    has_coverage_follow_up: '',
    never_logged_in: '',
    disabled: '',
    dev_baseline: '',
  };
  if (view === 'coverage_risks') {
    next.has_coverage_follow_up = 'true';
  } else if (view === 'dev_baseline_only') {
    next.dev_baseline = 'true';
  }
  return next;
}

function MembersContent() {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useLocale();
  const [items, setItems] = useState<MemberQueueItem[]>([]);
  const [summary, setSummary] = useState<MembersSummary>({
    total: 0,
    members_needing_coverage_follow_up: 0,
    never_logged_in_members: 0,
    disabled_mapped_members: 0,
    members_on_dev_baseline: 0,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<MembersFilters>(() => buildFilters(searchParams));

  useEffect(() => {
    setFilters(buildFilters(searchParams));
  }, [searchParams]);

  useEffect(() => {
    const queryString = buildQueryString(filters);
    const nextUrl = queryString ? `${pathname}?${queryString}` : pathname;
    router.replace(nextUrl, { scroll: false });
  }, [filters, pathname, router]);

  useEffect(() => {
    const loadMembers = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (filters.member_ref) params.set('member_ref', filters.member_ref);
        if (filters.account_id) params.set('account_id', filters.account_id);
        if (filters.status) params.set('status', filters.status);
        if (filters.has_coverage_follow_up) params.set('has_coverage_follow_up', filters.has_coverage_follow_up);
        if (filters.never_logged_in) params.set('never_logged_in', filters.never_logged_in);
        if (filters.disabled) params.set('disabled', filters.disabled);
        if (filters.dev_baseline) params.set('dev_baseline', filters.dev_baseline);

        const response = await fetch(`/api/admin/members?${params.toString()}`, {
          credentials: 'include',
        });
        if (!response.ok) {
          throw new Error(t('error.failed_load'));
        }
        const payload = await response.json();
        setItems(Array.isArray(payload.data?.items) ? payload.data.items : []);
        setSummary({
          total: Number(payload.data?.summary?.total || 0),
          members_needing_coverage_follow_up: Number(payload.data?.summary?.members_needing_coverage_follow_up || 0),
          never_logged_in_members: Number(payload.data?.summary?.never_logged_in_members || 0),
          disabled_mapped_members: Number(payload.data?.summary?.disabled_mapped_members || 0),
          members_on_dev_baseline: Number(payload.data?.summary?.members_on_dev_baseline || 0),
        });
      } catch (err) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadMembers();
  }, [filters, t]);

  const displayedItems = useMemo(() => {
    const baseItems =
      filters.view === 'pending_cleanup'
        ? items.filter((item) => item.never_logged_in || item.disabled_mapped)
        : items;
    return [...baseItems].sort((left, right) => {
      const leftRank = [
        left.has_coverage_follow_up ? 0 : 1,
        left.disabled_mapped ? 0 : 1,
        left.never_logged_in ? 0 : 1,
        left.dev_baseline ? 0 : 1,
        left.member_ref,
      ];
      const rightRank = [
        right.has_coverage_follow_up ? 0 : 1,
        right.disabled_mapped ? 0 : 1,
        right.never_logged_in ? 0 : 1,
        right.dev_baseline ? 0 : 1,
        right.member_ref,
      ];
      return leftRank.join(':').localeCompare(rightRank.join(':'));
    });
  }, [filters.view, items]);

  const handleFilterChange = (key: keyof MembersFilters, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  };

  const handleQuickViewChange = (view: QuickViewId) => {
    setFilters((prev) => applyQuickViewPreset(prev, view));
  };

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

  const queueConclusion =
    summary.members_needing_coverage_follow_up > 0
      ? t(
          'admin.members.queue_warning',
          {},
          'Some portal members still reach sites that need subscription follow-up. Start with those members before lower-risk access review.'
        )
      : summary.disabled_mapped_members > 0
        ? t(
            'admin.members.queue_disabled_warning',
            {},
            'Some disabled memberships still map to live site access. Review those members before invite or baseline cleanup.'
          )
        : summary.never_logged_in_members > 0
          ? t(
              'admin.members.queue_never_logged_in',
              {},
              'Coverage looks stable, but some members have never logged in. Review whether those memberships still need to exist.'
            )
          : t(
                'admin.members.queue_ok',
                {},
                'Member coverage posture is readable. Use this queue to decide whether the next operator step belongs on a customer, site, or impersonation path.'
              );

  const quickViews: Array<{ id: QuickViewId; label: string }> = [
    { id: 'all', label: t('admin.members.quick_view_all', {}, 'All members') },
    { id: 'coverage_risks', label: t('admin.members.quick_view_coverage', {}, 'Coverage risks') },
    { id: 'pending_cleanup', label: t('admin.members.quick_view_cleanup', {}, 'Pending access cleanup') },
    { id: 'dev_baseline_only', label: t('admin.members.quick_view_dev', {}, 'Dev baseline only') },
  ];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_group_support_access', {}, 'Support / Access')}
        title={t('admin.members_title', {}, 'Support access queue')}
        description={queueConclusion}
        aside={
          <div className="w-full xl:w-[46rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('common.members'), value: formatInteger(summary.total), size: 'compact' },
                {
                  label: t('admin.coverage_follow_up_required', {}, 'Coverage follow-up required'),
                  value: formatInteger(summary.members_needing_coverage_follow_up),
                  size: 'compact',
                },
                { label: t('admin.never_logged_in', {}, 'Never logged in'), value: formatInteger(summary.never_logged_in_members), size: 'compact' },
                { label: t('admin.disabled_mapping', {}, 'Disabled mapping'), value: formatInteger(summary.disabled_mapped_members), size: 'compact' },
                { label: t('admin.dev_baseline_members', {}, 'Dev baseline'), value: formatInteger(summary.members_on_dev_baseline), size: 'compact' },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-5"
            />
          </div>
        }
      />

      <BackofficeSectionPanel className="space-y-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.members.filters_label', {}, 'Queue filters')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.members.filters_title', {}, 'Filter support access coverage')}
            </h2>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {quickViews.map((view) => (
            <button
              key={view.id}
              type="button"
              onClick={() => handleQuickViewChange(view.id)}
              className={cn('btn', filters.view === view.id ? 'btn-primary' : 'btn-secondary')}
            >
              {view.label}
            </button>
          ))}
        </div>

        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-7">
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.member')}</span>
            <input className="input" value={filters.member_ref} onChange={(event) => handleFilterChange('member_ref', event.target.value)} placeholder="user:admin@example.com" />
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.account')}</span>
            <input className="input" value={filters.account_id} onChange={(event) => handleFilterChange('account_id', event.target.value)} placeholder="acct_demo" />
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.status')}</span>
            <select className="input" value={filters.status} onChange={(event) => handleFilterChange('status', event.target.value)}>
              <option value="">{t('common.all')}</option>
              <option value="active">{t('status.active')}</option>
              <option value="pending_invite">{t('status.pending')}</option>
              <option value="disabled">{t('status.disabled')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.coverage_follow_up_required', {}, 'Coverage follow-up required')}</span>
            <select className="input" value={filters.has_coverage_follow_up} onChange={(event) => handleFilterChange('has_coverage_follow_up', event.target.value)}>
              <option value="">{t('common.all')}</option>
              <option value="true">{t('common.yes')}</option>
              <option value="false">{t('common.no')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.never_logged_in', {}, 'Never logged in')}</span>
            <select className="input" value={filters.never_logged_in} onChange={(event) => handleFilterChange('never_logged_in', event.target.value)}>
              <option value="">{t('common.all')}</option>
              <option value="true">{t('common.yes')}</option>
              <option value="false">{t('common.no')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.disabled_mapping', {}, 'Disabled mapping')}</span>
            <select className="input" value={filters.disabled} onChange={(event) => handleFilterChange('disabled', event.target.value)}>
              <option value="">{t('common.all')}</option>
              <option value="true">{t('common.yes')}</option>
              <option value="false">{t('common.no')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.dev_baseline_label', {}, 'Dev baseline')}</span>
            <select className="input" value={filters.dev_baseline} onChange={(event) => handleFilterChange('dev_baseline', event.target.value)}>
              <option value="">{t('common.all')}</option>
              <option value="true">{t('common.yes')}</option>
              <option value="false">{t('common.no')}</option>
            </select>
          </label>
        </div>
      </BackofficeSectionPanel>

      <BackofficeSectionPanel className="space-y-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {t('admin.members.queue_results_label', {}, 'Support access queue')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
            {t('admin.members.queue_results_title', {}, 'Inspect support access before billing or site follow-up')}
          </h2>
        </div>
        {displayedItems.length === 0 ? (
          <BackofficeEmptyState
            title={t('admin.members.empty_title', {}, 'No matching members')}
            description={t('admin.members.empty_desc', {}, 'No member matches the current filters. Clear the queue filter or refresh the directory.')}
            action={
              <Link href="/admin/members" className="btn btn-secondary">
                {t('common.clear_filters', {}, 'Clear filters')}
              </Link>
            }
          />
        ) : (
          <div className="space-y-3">
            {displayedItems.map((item) => (
              <BackofficeStackCard key={item.member_ref} className="space-y-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <BackofficeIdentifier value={item.member_ref} className="text-sm font-semibold text-gray-950 dark:text-white" />
                    <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{item.email || t('common.not_found')}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <BackofficeStatusBadge status={item.status || 'unknown'} label={item.status ? t(`status.${item.status}`, undefined, item.status) : t('common.unknown')} />
                    {item.has_coverage_follow_up ? (
                      <BackofficeStatusBadge status="error" label={t('admin.coverage_follow_up_required', {}, 'Coverage follow-up required')} />
                    ) : null}
                    {item.never_logged_in ? (
                      <BackofficeStatusBadge status="warning" label={t('admin.never_logged_in', {}, 'Never logged in')} />
                    ) : null}
                    {item.disabled_mapped ? (
                      <BackofficeStatusBadge status="error" label={t('admin.disabled_mapping', {}, 'Disabled mapping')} />
                    ) : null}
                    {item.dev_baseline ? (
                      <BackofficeStatusBadge status="warning" label={t('admin.dev_baseline_label', {}, 'Dev baseline')} />
                    ) : null}
                    {!item.has_coverage_follow_up && !item.never_logged_in && !item.disabled_mapped && !item.dev_baseline ? (
                      <BackofficeStatusBadge status="ok" label={t('status.active')} />
                    ) : null}
                  </div>
                </div>

                <BackofficeMetricStrip
                  columnsClassName="md:grid-cols-4 xl:grid-cols-5"
                  items={[
                    { label: t('common.accounts'), value: formatInteger(item.account_count) },
                    { label: t('common.sites'), value: formatInteger(item.accessible_site_count) },
                    { label: t('admin.sites_needing_follow_up', {}, 'Sites needing follow-up'), value: formatInteger(item.sites_needing_follow_up_count), toneClassName: item.has_coverage_follow_up ? 'text-red-600 dark:text-red-400' : undefined },
                    { label: t('admin.invite_state', {}, 'Invite state'), value: item.invite_state || t('common.unknown') },
                    { label: t('admin.last_login', {}, 'Last login'), value: item.last_login_at ? formatDate(item.last_login_at) : t('common.never') },
                  ]}
                />

                <div className="flex flex-wrap gap-2 text-xs text-gray-600 dark:text-gray-400">
                  <span>
                    {t('admin.product_role', {}, 'Product role')}: {formatExternalRoleSet(item, t) || t('common.not_found')}
                  </span>
                  <span>
                    {t('common.actions', {}, 'Actions')}: {formatAllowedActions(item, t)}
                  </span>
                  <span>{t('admin.sites_needing_follow_up', {}, 'Sites needing follow-up')}: {formatInteger(item.sites_needing_follow_up_count)}</span>
                </div>

                <div className="flex flex-wrap gap-2">
                  {item.primary_account_id ? (
                    <Link href={`/admin/accounts/${item.primary_account_id}`} className="btn btn-secondary">
                      {t('admin.members.open_account', {}, 'Open customer')}
                    </Link>
                  ) : null}
                  {item.primary_follow_up_site_id ? (
                    <Link href={`/admin/sites/${item.primary_follow_up_site_id}`} className="btn btn-secondary">
                      {t('admin.members.open_follow_up_site', {}, 'Open follow-up site')}
                    </Link>
                  ) : null}
                  {item.single_covered_subscription_id ? (
                    <Link
                      href={`/admin/subscriptions/${item.single_covered_subscription_id}`}
                      className="text-xs font-medium text-gray-500 underline decoration-dotted underline-offset-4 transition hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
                    >
                      {t('admin.coverage_open_subscription_detail_action', {}, 'Inspect detail')} →
                    </Link>
                  ) : null}
                  <Link href={item.primary_impersonation_href || '/admin/impersonations'} className="btn btn-secondary">
                    {t('admin.members.open_impersonation_inventory', {}, 'Open impersonation inventory')}
                  </Link>
                </div>

                <BackofficeStackCard className="space-y-2 border border-dashed border-gray-200 bg-gray-50/60 dark:border-gray-800 dark:bg-gray-950/40">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                      {t('admin.members.account_breakdown_label', {}, 'Customer breakdown')}
                    </p>
                  </div>
                  <div className="space-y-2">
                    {item.accounts.map((account) => (
                      <div key={`${item.member_ref}:${account.account_id}`} className="rounded-2xl border border-gray-200 px-4 py-3 dark:border-gray-800">
                        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                          <div>
                            <Link href={`/admin/accounts/${account.account_id}`} className="font-semibold text-blue-600 hover:underline dark:text-blue-300">
                              {account.account_name || account.account_id}
                            </Link>
                            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                              {formatInteger(account.covered_site_count)} {t('admin.covered_sites', {}, 'covered')} · {formatInteger(account.sites_needing_follow_up_count)} {t('admin.sites_needing_follow_up', {}, 'follow-up')}
                            </p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </BackofficeStackCard>
              </BackofficeStackCard>
            ))}
          </div>
        )}
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function MembersPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <MembersContent />
    </Suspense>
  );
}
