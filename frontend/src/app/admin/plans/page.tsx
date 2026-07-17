'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeInfoHint,
  BackofficeEmptyState,
  BackofficeLayer,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useToast } from '@/components/ui/Toast';
import { useLocale } from '@/contexts/LocaleContext';
import {
  localizeFeatureGroup,
  localizeOperatorNote,
  localizePackageAlias,
  localizePositioning,
  localizeTierLabel,
  localizeUsageBand,
} from '@/lib/admin-plan-copy';
import { createApiClient } from '@/lib/api-client';
import { ADMIN_CURRENCY } from '@/lib/currency';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { ApiError, resolveUiErrorMessage } from '@/lib/errors';

type PlanVersionRecord = {
  plan_version_id: string;
  version_label: string;
  status: string;
  currency: string;
  budgets: Record<string, unknown>;
  concurrency: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  created_at: string;
};

type PlanRecord = {
  plan_id: string;
  name: string;
  status: string;
  description: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type TierSummary = {
  tier_id: string;
  label: string;
  package_alias: string;
  usage_band: string;
  positioning: string;
  monthly_included_points: number;
  site_limit: number;
  budgets_template: Record<string, unknown>;
  concurrency_template: Record<string, unknown>;
  max_batch_items: number;
  automation_enabled: boolean;
  api_enabled: boolean;
  openclaw_enabled: boolean;
  package_operator_note: string;
  policy_baseline: Record<string, unknown>;
  feature_groups: string[];
};

type PlanListItem = {
  plan: PlanRecord;
  versions: PlanVersionRecord[];
  tier_summary: TierSummary;
  latest_version?: PlanVersionRecord | null;
  published_version_count: number;
  subscription_counts: {
    total: number;
    active: number;
  };
};

type CanonicalTierCoverageItem = {
  shell: TierSummary;
  item: PlanListItem | null;
  isPresent: boolean;
};

type PlanCatalogPayload = {
  items?: PlanListItem[];
  tier_templates?: TierSummary[];
};

const PLAN_CATALOG_LOAD_TIMEOUT_MS = 10_000;
type PlanCatalogState = 'missing' | 'unpublished' | 'ready';
type PlanCatalogSort = 'attention' | 'tier' | 'subscriptions';
const PLAN_SORTS = new Set<PlanCatalogSort>(['attention', 'tier', 'subscriptions']);
const TIER_ORDER = new Map([['free', 0], ['plus', 1], ['pro', 2], ['agency', 3]]);
const plansClient = createApiClient({ idempotencyPrefix: 'admin_plans' });

function normalizePlanSort(value: string | null): PlanCatalogSort {
  return value && PLAN_SORTS.has(value as PlanCatalogSort) ? (value as PlanCatalogSort) : 'attention';
}

function catalogState(entry: CanonicalTierCoverageItem): PlanCatalogState {
  if (!entry.item) return 'missing';
  if (!entry.isPresent) return 'unpublished';
  return 'ready';
}

function catalogStateRank(entry: CanonicalTierCoverageItem): number {
  return { missing: 0, unpublished: 1, ready: 2 }[catalogState(entry)];
}

function sortCatalog(entries: CanonicalTierCoverageItem[], sort: PlanCatalogSort): CanonicalTierCoverageItem[] {
  return [...entries].sort((left, right) => {
    if (sort === 'subscriptions') {
      return Number(right.item?.subscription_counts?.active || 0) - Number(left.item?.subscription_counts?.active || 0);
    }
    const tierDifference = (TIER_ORDER.get(left.shell.tier_id) ?? 99) - (TIER_ORDER.get(right.shell.tier_id) ?? 99);
    if (sort === 'tier') return tierDifference;
    return catalogStateRank(left) - catalogStateRank(right) || tierDifference;
  });
}

function catalogStateToneClassName(state: PlanCatalogState): string {
  if (state === 'missing') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200';
  if (state === 'unpublished') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200';
  return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200';
}

function numericValue(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function latestMetadataValue(
  latestVersion: PlanVersionRecord | null | undefined,
  fallback: unknown,
  key: string
): number {
  const metadata = latestVersion?.metadata || {};
  return numericValue(metadata[key] ?? fallback);
}

async function fetchPlanCatalog(): Promise<PlanCatalogPayload> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), PLAN_CATALOG_LOAD_TIMEOUT_MS);
  try {
    return (await plansClient.request<PlanCatalogPayload>('/api/admin/plans', {
      signal: controller.signal,
    })).data;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function findCanonicalShellPlan(plans: PlanListItem[], tierId: string): PlanListItem | undefined {
  const expectedTierId = tierId;
  return plans.find((item) => {
    const planId = item.plan.plan_id;
    const metadataTierId = String(item.plan.metadata?.tier_id || '');
    const summaryTierId = String(item.tier_summary?.tier_id || '');
    if (planId === tierId || planId === expectedTierId) {
      return true;
    }
    return (
      item.plan.metadata?.source === 'canonical_package_shell_v1' &&
      (metadataTierId === expectedTierId || summaryTierId === expectedTierId)
    );
  });
}

function PlansContent() {
  const { t } = useLocale();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const appliedQuery = searchParams.get('q') || '';
  const appliedState = searchParams.get('state') || '';
  const sort = normalizePlanSort(searchParams.get('sort'));
  const focusedTierId = searchParams.get('focus') || '';
  const [plans, setPlans] = useState<PlanListItem[]>([]);
  const [tierTemplates, setTierTemplates] = useState<TierSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queryDraft, setQueryDraft] = useState(appliedQuery);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(false);
  const activeRequestRef = useRef(false);
  const requestSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);
  const [form, setForm] = useState({
    plan_id: '',
    name: '',
    status: 'active',
    description: '',
  });

  const updateCatalogUrl = useCallback((changes: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParamsKey);
    Object.entries(changes).forEach(([key, value]) => {
      if (!value || (key === 'sort' && value === 'attention')) params.delete(key);
      else params.set(key, value);
    });
    const next = params.toString();
    router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
  }, [pathname, router, searchParamsKey]);

  const loadPlans = useCallback(async (force = false) => {
    if (!force && activeRequestRef.current) return;
    activeRequestRef.current = true;
    const sequence = ++requestSequenceRef.current;
    if (hasLoadedRef.current) setIsRefreshing(true);
    else setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchPlanCatalog();
      if (sequence !== requestSequenceRef.current) return;
      setPlans(payload.items || []);
      setTierTemplates(payload.tier_templates || []);
      setLoadedAt(new Date());
      hasLoadedRef.current = true;
    } catch (err) {
      if (sequence !== requestSequenceRef.current) return;
      const isAbort =
        err instanceof ApiError &&
        err.cause instanceof DOMException &&
        err.cause.name === 'AbortError';
      setError(
        isAbort
          ? t('admin.plans.load_timeout', {}, 'Package catalog did not finish loading. Retry, then check the admin plans endpoint if it repeats.')
          : resolveUiErrorMessage(err, t('error.failed_load'))
      );
    } finally {
      if (sequence === requestSequenceRef.current) {
        activeRequestRef.current = false;
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, [t]);

  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);

  useEffect(() => {
    setQueryDraft(appliedQuery);
  }, [appliedQuery]);

  const handleCreatePlan = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    try {
      await plansClient.request<Record<string, unknown>>('/api/admin/plans', {
        method: 'POST',
        body: form,
      });
      toast.success(
        t('admin.plan_saved_notice', {}, 'Plan saved. Publish a plan version next to make it selectable for subscriptions.'),
        t('admin.plans.plan_saved_title', {}, 'Package record saved')
      );
      setForm({ plan_id: '', name: '', status: 'active', description: '' });
      await loadPlans(true);
    } catch (err) {
      setError(
        resolveUiErrorMessage(err, t('error.failed_save', {}, 'Failed to save.'))
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleBootstrapShell = useCallback(async (shell: TierSummary) => {
    setIsBootstrapping(true);
    setError(null);
    try {
      const localizedAlias = localizePackageAlias(t, shell.tier_id, shell.package_alias);
      const localizedPositioning = localizePositioning(t, shell.tier_id, shell.positioning);
      const localizedOperatorNote = localizeOperatorNote(t, shell.tier_id, shell.package_operator_note);
      const metadata = {
        tier_id: shell.tier_id,
        package_alias: localizedAlias,
        monthly_included_points: shell.monthly_included_points,
        site_limit: shell.site_limit,
        max_batch_items: shell.max_batch_items,
        source: 'canonical_package_shell_v1',
      };

      await plansClient.request<Record<string, unknown>>('/api/admin/plans', {
        method: 'POST',
        body: {
          plan_id: shell.tier_id,
          name: localizedAlias,
          status: 'active',
          description: localizedPositioning,
          metadata,
        },
      });

      await plansClient.request<Record<string, unknown>>(`/api/admin/plans/${encodeURIComponent(shell.tier_id)}/versions`, {
        method: 'POST',
        body: {
          plan_version_id: `${shell.tier_id}_v1`,
          version_label: 'v1',
          status: 'published',
          currency: ADMIN_CURRENCY,
          entitlements: {
            ability_families: ['*'],
            channels: ['*'],
            execution_kinds: ['*'],
            execution_tiers: ['cloud'],
            data_classifications: ['*'],
          },
          budgets: shell.budgets_template,
          concurrency: shell.concurrency_template,
          policy: {
            subscription: { grace_period_days: Number(shell.policy_baseline?.grace_period_days || 0) },
            budgets: {},
          },
          metadata: {
            ...metadata,
            package_operator_note: localizedOperatorNote,
            baseline_version: 'v1',
          },
        },
      });

      toast.success(
        t(
          'admin.package_shell_bootstrap_notice',
          {},
          `${localizedAlias} package is now available for customer assignment.`
        ),
        t('admin.plans.package_initialized_title', {}, 'Package initialized')
      );
      await loadPlans(true);
    } catch (err) {
      setError(
        resolveUiErrorMessage(err, t('error.failed_save', {}, 'Failed to save.'))
      );
    } finally {
      setIsBootstrapping(false);
    }
  }, [loadPlans, t, toast]);

  const handleBootstrapMissingShells = useCallback(async () => {
    const missingShells = tierTemplates.filter((shell) => {
      const existing = findCanonicalShellPlan(plans, shell.tier_id);
      return !existing || Number(existing.published_version_count || 0) === 0;
    });
    if (missingShells.length === 0) {
      toast.success(
        t('admin.package_shells_present', {}, 'All standard packages are already available.'),
        t('admin.plans.catalog_ready_title', {}, 'Catalog ready')
      );
      return;
    }
    for (const shell of missingShells) {
      // Sequential bootstrap keeps notices and server-side upserts predictable.
      await handleBootstrapShell(shell);
    }
  }, [handleBootstrapShell, plans, t, tierTemplates, toast]);

  if (isLoading) {
    return <LoadingFallback />;
  }

  if (error && plans.length === 0) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-red-600">{t('common.error')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{error}</p>
          <button onClick={() => void loadPlans()} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  const canonicalTierCoverage: CanonicalTierCoverageItem[] = tierTemplates.map((shell) => {
    const item = findCanonicalShellPlan(plans, shell.tier_id) || null;
    return {
      shell,
      item,
      isPresent: Boolean(item && Number(item.published_version_count || 0) > 0),
    };
  });
  const visibleCanonicalPlans = canonicalTierCoverage.filter((entry) => entry.item).length;
  const activeSubscriptions = canonicalTierCoverage.reduce(
    (sum, entry) => sum + Number(entry.item?.subscription_counts?.active || 0),
    0
  );
  const missingShellCount = canonicalTierCoverage.filter((entry) => !entry.isPresent).length;
  const filteredCatalog = sortCatalog(
    canonicalTierCoverage.filter((entry) => {
      const state = catalogState(entry);
      const queryBlob = [
        entry.shell.tier_id,
        entry.shell.label,
        entry.shell.package_alias,
        entry.item?.plan?.plan_id,
        entry.item?.plan?.name,
        entry.item?.plan?.description,
      ].join(' ').toLowerCase();
      return (!appliedState || state === appliedState) && (!appliedQuery || queryBlob.includes(appliedQuery.toLowerCase()));
    }),
    sort
  );
  const selectedEntry = filteredCatalog.find((entry) => entry.shell.tier_id === focusedTierId) || filteredCatalog[0] || null;
  const hasFilters = Boolean(appliedQuery || appliedState || sort !== 'attention');

  return (
    <BackofficePageStack className="space-y-5">
      <BackofficeLayer
        eyebrow={t('admin.nav_plan_catalog', {}, 'Package Catalog')}
        title={t('admin.coverage_package_catalog_title', {}, 'Coverage package catalog')}
        description={t(
          'admin.package_management_center_desc',
          {},
          'Read the active Free, Plus, Pro, and Agency package posture first. Open detail only when price, limits, or release state needs maintenance.'
        )}
        actions={(
          <>
            <button type="button" className="btn btn-secondary" disabled={isRefreshing} onClick={() => void loadPlans(true)}>{isRefreshing ? t('common.loading', {}, 'Loading...') : t('admin.plans.refresh_action', {}, 'Refresh catalog')}</button>
            <Link href="/admin/credit-packs" className="btn btn-secondary">{t('admin.plans.open_credit_packs', {}, 'Open credit packs')}</Link>
          </>
        )}
      />

      {error ? <div role="alert" className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200 sm:flex-row sm:items-center sm:justify-between"><span>{error}{plans.length > 0 ? <span className="mt-1 block text-xs">{t('admin.plans.retained_notice', {}, 'Showing the last successfully loaded catalog.')}</span> : null}</span><button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadPlans(true)}>{t('common.retry')}</button></div> : null}

      <BackofficeSummaryStrip items={[
        { label: t('admin.managed_packages', {}, 'Managed packages'), value: formatInteger(tierTemplates.length) },
        { label: t('admin.ready_packages', {}, 'Ready packages'), value: formatInteger(visibleCanonicalPlans), toneClassName: visibleCanonicalPlans === tierTemplates.length ? 'text-emerald-600 dark:text-emerald-300' : undefined },
        { label: t('admin.plans.needs_attention_metric', {}, 'Needs attention'), value: formatInteger(missingShellCount), toneClassName: missingShellCount ? 'text-rose-600 dark:text-rose-300' : undefined },
        { label: t('admin.active_subscriptions'), value: formatInteger(activeSubscriptions) },
        { label: t('common.updated_at', {}, 'Updated'), value: loadedAt ? formatDate(loadedAt.toISOString()) : t('common.unknown', {}, 'Unknown') },
      ]} />

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(20rem,0.72fr)]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div className="space-y-4 border-b border-slate-200/80 px-5 py-5 dark:border-slate-800 md:px-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between"><div><h2 className="text-xl font-semibold text-slate-950 dark:text-white">{t('admin.plans.directory_title', {}, 'Standard package catalog')}</h2><p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('admin.plans.directory_desc', {}, 'Compare current publication and subscription posture, then inspect one package before opening maintenance detail.')}</p></div><p className="text-sm font-medium text-slate-500 dark:text-slate-400" role="status">{t('admin.plans.result_count', { visible: formatInteger(filteredCatalog.length), total: formatInteger(canonicalTierCoverage.length) }, `${formatInteger(filteredCatalog.length)} visible · ${formatInteger(canonicalTierCoverage.length)} standard packages`)}</p></div>
            <div className="flex flex-wrap gap-2" aria-label={t('admin.plans.state_filter_label', {}, 'Package readiness')}>{['', 'ready', 'unpublished', 'missing'].map((state) => <button key={state || 'all'} type="button" aria-pressed={appliedState === state} onClick={() => updateCatalogUrl({ state: state || null, focus: null })} className={cn('cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium transition', appliedState === state ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200' : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600')}>{state ? t(`admin.plans.state_${state}`, {}, state) : t('common.all', {}, 'All')}</button>)}</div>
            <form className="grid gap-3 md:grid-cols-[minmax(13rem,1fr)_minmax(10rem,0.65fr)_auto]" onSubmit={(event) => { event.preventDefault(); updateCatalogUrl({ q: queryDraft.trim() || null, focus: null }); }}>
              <label className="text-sm text-slate-700 dark:text-slate-200"><span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.plans.search_label', {}, 'Search packages')}</span><input type="search" className="input w-full" value={queryDraft} onChange={(event) => setQueryDraft(event.target.value)} placeholder={t('admin.plans.search_placeholder', {}, 'Package name or ID')} /></label>
              <label className="text-sm text-slate-700 dark:text-slate-200"><span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.plans.sort_label', {}, 'Sort')}</span><select className="input w-full" value={sort} onChange={(event) => updateCatalogUrl({ sort: normalizePlanSort(event.target.value), focus: null })}><option value="attention">{t('admin.plans.sort_attention', {}, 'Needs attention')}</option><option value="tier">{t('admin.plans.sort_tier', {}, 'Tier order')}</option><option value="subscriptions">{t('admin.plans.sort_subscriptions', {}, 'Active subscriptions')}</option></select></label>
              <div className="flex items-end gap-2 md:flex-col md:justify-end lg:flex-row"><button type="submit" className="btn btn-primary flex-1 md:flex-none">{t('common.apply', {}, 'Apply')}</button><button type="button" className="btn btn-secondary flex-1 md:flex-none" disabled={!hasFilters && !queryDraft} onClick={() => { setQueryDraft(''); updateCatalogUrl({ q: null, state: null, sort: null, focus: null }); }}>{t('common.clear_filters', {}, 'Clear filters')}</button></div>
            </form>
          </div>

          {filteredCatalog.length ? <div role="list" aria-label={t('admin.plans.list_label', {}, 'Package list')}>{filteredCatalog.map((entry) => {
            const { shell, item } = entry;
            const state = catalogState(entry);
            const latestVersion = item?.latest_version || item?.versions?.[0] || null;
            const budgets = (latestVersion?.budgets || shell.budgets_template || {}) as Record<string, unknown>;
            const concurrency = (latestVersion?.concurrency || shell.concurrency_template || {}) as Record<string, unknown>;
            const sourceTier = item?.tier_summary || shell;
            const packageAlias = localizePackageAlias(t, shell.tier_id, sourceTier.package_alias);
            const selected = selectedEntry?.shell.tier_id === shell.tier_id;
            const reason = state === 'missing' ? t('admin.plans.reason_missing', {}, 'The standard package record does not exist and cannot be assigned.') : state === 'unpublished' ? t('admin.plans.reason_unpublished', {}, 'The package exists but has no published version for subscription assignment.') : t('admin.plans.reason_ready', {}, 'The package has a published version and can carry customer subscriptions.');
            return <article key={shell.tier_id} role="listitem" data-ui="plan-catalog-item" className={cn('grid gap-4 border-b border-slate-200/80 px-5 py-5 transition last:border-b-0 dark:border-slate-800 md:grid-cols-[minmax(11rem,0.9fr)_minmax(13rem,1.1fr)] md:items-center md:px-6 2xl:grid-cols-[minmax(12rem,1fr)_minmax(14rem,1.2fr)_minmax(9rem,0.75fr)_auto]', selected ? 'bg-blue-50/65 dark:bg-blue-950/15' : 'hover:bg-slate-50/70 dark:hover:bg-slate-950/35')}>
              <div><p className="text-xs font-medium uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{localizeTierLabel(t, shell.tier_id, sourceTier.label)}</p><h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{packageAlias}</h3><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item?.plan?.plan_id || shell.tier_id}</p></div>
              <div><div className="flex flex-wrap items-center gap-2"><span className={cn('inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', catalogStateToneClassName(state))}>{t(`admin.plans.state_${state}`, {}, state)}</span><span className="text-xs text-slate-500 dark:text-slate-400">{formatInteger(item?.published_version_count || 0)} {t('admin.plans.published_versions_short', {}, 'published')}</span></div><p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{reason}</p></div>
              <dl className="grid gap-2 text-xs text-slate-600 dark:text-slate-300"><div className="flex justify-between gap-3"><dt>{t('admin.active_subscriptions')}</dt><dd className="font-semibold text-slate-950 dark:text-white">{formatInteger(item?.subscription_counts?.active || 0)}</dd></div><div className="flex justify-between gap-3"><dt>{t('admin.site_limit', {}, 'Site limit')}</dt><dd className="font-semibold text-slate-950 dark:text-white">{formatInteger(latestMetadataValue(latestVersion, sourceTier.site_limit, 'site_limit'))}</dd></div><div className="flex justify-between gap-3"><dt>{t('admin.concurrency', {}, 'Concurrency')}</dt><dd className="font-semibold text-slate-950 dark:text-white">{formatInteger(numericValue(concurrency.max_active_runs))}</dd></div><div className="flex justify-between gap-3"><dt>{t('admin.run_ceiling', {}, 'Run ceiling')}</dt><dd className="font-semibold text-slate-950 dark:text-white">{formatInteger(numericValue(budgets.max_runs_per_period))}</dd></div></dl>
              <div className="flex flex-wrap gap-2 md:justify-end"><button type="button" className="btn btn-secondary btn-sm" aria-pressed={selected} aria-controls="plan-catalog-inspector" onClick={() => updateCatalogUrl({ focus: shell.tier_id })}>{t('admin.plans.inspect_action', {}, 'Inspect')}</button>{item?.plan?.plan_id ? <Link href={`/admin/plans/${item.plan.plan_id}`} className="btn btn-primary btn-sm">{t('common.details', {}, 'Details')}</Link> : null}</div>
            </article>;
          })}</div> : <BackofficeEmptyState className="m-5 md:m-6" title={t('admin.plans.empty_title', {}, 'No packages match these filters')} description={t('admin.plans.empty_desc', {}, 'Clear the package name, readiness, or sort filters. No package record has been changed.')} action={hasFilters ? <button type="button" className="btn btn-secondary btn-sm" onClick={() => { setQueryDraft(''); updateCatalogUrl({ q: null, state: null, sort: null, focus: null }); }}>{t('common.clear_filters', {}, 'Clear filters')}</button> : null} />}
        </BackofficeSectionPanel>

        <aside id="plan-catalog-inspector" className="xl:sticky xl:top-24" aria-live="polite"><BackofficeSectionPanel className="space-y-5"><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{t('admin.plans.inspector_eyebrow', {}, 'Inspector')}</p><h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{t('admin.plans.inspector_title', {}, 'Current package')}</h2></div>{selectedEntry ? <span className={cn('inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', catalogStateToneClassName(catalogState(selectedEntry)))}>{t(`admin.plans.state_${catalogState(selectedEntry)}`, {}, catalogState(selectedEntry))}</span> : null}</div>
          {selectedEntry ? (() => { const shell = selectedEntry.shell; const item = selectedEntry.item; const latestVersion = item?.latest_version || item?.versions?.[0] || null; const sourceTier = item?.tier_summary || shell; const alias = localizePackageAlias(t, shell.tier_id, sourceTier.package_alias); return <div className="space-y-5"><div><p className="text-base font-semibold text-slate-950 dark:text-white">{alias}</p><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item?.plan?.plan_id || shell.tier_id}</p></div><dl className="grid gap-2 text-sm text-slate-600 dark:text-slate-300">{[[t('common.status'), item?.plan?.status || t('common.not_available', {}, 'N/A')],[t('admin.plans.latest_version_label', {}, 'Latest version'), latestVersion?.version_label || t('common.not_available', {}, 'N/A')],[t('admin.plans.published_versions_label', {}, 'Published versions'), formatInteger(item?.published_version_count || 0)],[t('admin.active_subscriptions'), formatInteger(item?.subscription_counts?.active || 0)],[t('admin.site_limit', {}, 'Site limit'), formatInteger(latestMetadataValue(latestVersion, sourceTier.site_limit, 'site_limit'))],[t('admin.included_points', {}, 'Included points'), formatInteger(latestMetadataValue(latestVersion, sourceTier.monthly_included_points, 'monthly_included_points'))],[t('common.currency', {}, 'Currency'), latestVersion?.currency || ADMIN_CURRENCY]].map(([label, value]) => <div key={label} className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 last:border-b-0 dark:border-slate-800"><dt>{label}</dt><dd className="text-right font-semibold text-slate-950 dark:text-white">{value}</dd></div>)}</dl><div className="flex flex-wrap gap-2">{item?.plan?.plan_id ? <Link href={`/admin/plans/${item.plan.plan_id}`} className="btn btn-primary btn-sm">{t('common.details', {}, 'Details')}</Link> : <a href="#package-maintenance" className="btn btn-primary btn-sm">{t('admin.plans.open_advanced_setup', {}, 'Advanced setup')}</a>}<Link href={`/admin/subscriptions?plan_id=${encodeURIComponent(item?.plan?.plan_id || shell.tier_id)}`} className="btn btn-secondary btn-sm">{t('admin.plans.open_subscriptions_action', {}, 'Open subscriptions')}</Link></div><details className="border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800"><summary className="cursor-pointer font-semibold text-slate-800 dark:text-slate-100">{t('admin.plans.package_context_title', {}, 'Package context')}</summary><div className="mt-3 space-y-2 text-slate-600 dark:text-slate-300"><p>{localizePositioning(t, shell.tier_id, sourceTier.positioning)}</p><p>{localizeUsageBand(t, shell.tier_id, sourceTier.usage_band)}</p><p>{sourceTier.feature_groups.map((group) => localizeFeatureGroup(t, group)).join(' · ') || t('common.not_available', {}, 'N/A')}</p></div></details><p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{t('admin.plans.inspector_boundary', {}, 'This catalog reads plans and published plan versions as Cloud commercial truth. Price, limits, release state, and exceptional creation remain in package detail or advanced maintenance; no WordPress control is created.')}</p></div>; })() : <p className="text-sm text-slate-600 dark:text-slate-300">{t('admin.plans.inspector_empty', {}, 'No package is visible in this catalog view.')}</p>}
        </BackofficeSectionPanel></aside>
      </div>

      {missingShellCount > 0 ? (
      <details id="package-maintenance" className="rounded-2xl border border-dashed border-slate-200 bg-white/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/40">
        <summary className="cursor-pointer list-none">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="flex items-center gap-2 text-sm font-semibold text-slate-950 dark:text-white">
                <span>{t('admin.package_shell_maintenance_toggle_label', {}, 'Package initialization')}</span>
                <BackofficeInfoHint
                  detail={t(
                    'admin.plans.advanced_maintenance_desc',
                    {},
                    'Initialize missing standard packages or create an exceptional package record.'
                  )}
                />
              </p>
            </div>
            <span className="inline-flex w-fit items-center rounded-full border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600 dark:border-slate-800 dark:text-slate-300">
              {missingShellCount > 0
                ? t('admin.package_shell_bootstrap_missing', {}, 'Some standard packages are still missing or unpublished.')
                : t('admin.package_shells_present', {}, 'All standard packages are already available.')}
            </span>
          </div>
        </summary>
        {error ? (
          <div role="alert" className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
            {error}
          </div>
        ) : null}

      <div className="mt-4 rounded-2xl border border-dashed border-slate-200 px-4 py-4 dark:border-slate-800">
        <BackofficeLayer
          eyebrow={t('admin.quick_actions')}
          title={t('admin.package_shell_bootstrap_title', {}, 'Create missing standard packages')}
          description={t(
            'admin.package_shell_bootstrap_desc',
            {},
            'Use these shortcuts to create any missing Free / Plus / Pro / Agency package entries before assigning them to customers.'
          )}
          descriptionDisplay="hint"
        />
        <BackofficeSectionPanel className="mt-4 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {missingShellCount > 0
              ? t(
                  'admin.package_shell_bootstrap_missing',
                  {},
                  `${missingShellCount} standard package${missingShellCount > 1 ? 's are' : ' is'} still missing or unpublished.`
                )
              : t('admin.package_shells_present', {}, 'All standard packages are already available.')}
          </p>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void handleBootstrapMissingShells()}
            disabled={isBootstrapping || missingShellCount === 0}
          >
            {t('admin.bootstrap_missing_shells', {}, 'Create missing packages')}
          </button>
        </div>
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-4">
          {canonicalTierCoverage.map(({ shell, item, isPresent }) => {
            return (
              <BackofficeStackCard key={shell.tier_id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-950 dark:text-white">
                      {localizePackageAlias(t, shell.tier_id, shell.package_alias)}
                    </p>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {localizeTierLabel(t, shell.tier_id)} · {localizeUsageBand(t, shell.tier_id, shell.usage_band)}
                    </p>
                  </div>
                  <BackofficeStatusBadge
                    status={isPresent ? 'published' : 'draft'}
                    label={isPresent ? t('status.published', {}, 'published') : t('status.draft', {}, 'missing')}
                  />
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-4">
                  <MetricInline
                    label={t('admin.included_points', {}, 'Included points')}
                    value={formatInteger(shell.monthly_included_points)}
                  />
                  <MetricInline
                    label={t('admin.site_limit', {}, 'Site limit')}
                    value={formatInteger(shell.site_limit)}
                  />
                  <MetricInline
                    label={t('admin.concurrency', {}, 'Concurrency')}
                    value={formatInteger(Number(shell.concurrency_template?.max_active_runs || 0))}
                  />
                  <MetricInline
                    label={t('admin.batch_ceiling', {}, 'Batch ceiling')}
                    value={formatInteger(shell.max_batch_items)}
                  />
                </div>
                <button
                  type="button"
                  className="btn btn-secondary mt-4 w-full"
                  disabled={isBootstrapping || isPresent}
                  onClick={() => void handleBootstrapShell(shell)}
                >
                  {isPresent
                    ? t('admin.package_shell_present', {}, 'Already present')
                    : t('admin.create_package_shell', {}, `Create ${localizePackageAlias(t, shell.tier_id, shell.package_alias)} package`)}
                </button>
                {item?.plan?.plan_id ? (
                  <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                    {t(
                      'admin.package_shell_binding',
                      { planId: item.plan.plan_id },
                      `This standard package uses ID ${item.plan.plan_id}.`
                    )}
                  </p>
                ) : null}
              </BackofficeStackCard>
            );
          })}
        </div>
        </BackofficeSectionPanel>
      </div>

      <div className="mt-4 rounded-2xl border border-dashed border-slate-200 px-4 py-4 dark:border-slate-800">
        <BackofficeLayer
          eyebrow={t('admin.quick_actions')}
          title={t('admin.create_plan_title', {}, 'Create package record')}
          description={t(
            'admin.create_plan_form_desc_v2',
            {},
            'Create package objects here only when the customer coverage queue genuinely needs a new package. This is a deep inspection workflow, not a default operator path.'
          )}
          descriptionDisplay="hint"
        />
        <BackofficeSectionPanel className="mt-4">
        <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-[0.9fr_1fr_0.7fr]" onSubmit={handleCreatePlan}>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.plan_id', {}, 'Package ID')}</span>
            <input
              value={form.plan_id}
              onChange={(event) => setForm((current) => ({ ...current, plan_id: event.target.value }))}
              className="input w-full"
              placeholder="free"
              required
            />
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.label')}</span>
            <input
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              className="input w-full"
              placeholder="Free"
              required
            />
          </label>
          <label className="text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.status')}</span>
            <select
              value={form.status}
              onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}
              className="input w-full"
            >
              <option value="active">{t('status.active', {}, 'active')}</option>
              <option value="draft">{t('status.draft', {}, 'draft')}</option>
              <option value="archived">{t('status.archived', {}, 'archived')}</option>
            </select>
          </label>
          <label className="text-sm md:col-span-2 xl:col-span-2">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.description')}</span>
            <textarea
              value={form.description}
              onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              className="input min-h-28 w-full"
              placeholder={t(
                'admin.plan_description_placeholder',
                {},
                'Describe the intended package posture, operating band, and any operator-only notes.'
              )}
            />
          </label>
          <div className="flex items-end justify-end">
            <button type="submit" className="btn btn-secondary w-full xl:w-auto" disabled={isSaving}>
              {isSaving ? t('common.saving', {}, 'Saving…') : t('common.create')}
            </button>
          </div>
        </form>
        </BackofficeSectionPanel>
      </div>
      </details>
      ) : null}
    </BackofficePageStack>
  );
}

function MetricInline({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-800">
      <p className="text-[0.65rem] uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-white">{value}</p>
    </div>
  );
}

export default function AdminPlansPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PlansContent />
    </Suspense>
  );
}
