'use client';

import React, { Suspense, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeInfoHint,
  BackofficeLayer,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import {
  localizeFeatureGroup,
  localizeOperatorNote,
  localizePackageAlias,
  localizePositioning,
  localizeTierLabel,
  localizeUsageBand,
} from '@/lib/admin-plan-copy';
import { ADMIN_CURRENCY } from '@/lib/currency';
import { readResponsePayload } from '@/lib/safe-response';
import { formatCurrency, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';

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

const PLAN_CATALOG_LOAD_TIMEOUT_MS = 10_000;

function numericValue(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatBudgetCurrency(value: unknown): string {
  return formatCurrency(numericValue(value), ADMIN_CURRENCY);
}

function latestMetadataValue(
  latestVersion: PlanVersionRecord | null | undefined,
  fallback: unknown,
  key: string
): number {
  const metadata = latestVersion?.metadata || {};
  return numericValue(metadata[key] ?? fallback);
}

async function fetchPlanCatalog(): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), PLAN_CATALOG_LOAD_TIMEOUT_MS);
  try {
    return await fetch('/api/admin/plans', {
      credentials: 'include',
      signal: controller.signal,
    });
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
  const [plans, setPlans] = useState<PlanListItem[]>([]);
  const [tierTemplates, setTierTemplates] = useState<TierSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(false);
  const [form, setForm] = useState({
    plan_id: '',
    name: '',
    status: 'active',
    description: '',
  });

  const loadPlans = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetchPlanCatalog();
      const payload = await readResponsePayload<{ data?: { items?: PlanListItem[]; tier_templates?: TierSummary[] }; message?: string }>(response);
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
      }
      setPlans((('data' in payload ? payload.data?.items : []) || []) as PlanListItem[]);
      setTierTemplates((('data' in payload ? payload.data?.tier_templates : []) || []) as TierSummary[]);
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      setError(
        isAbort
          ? t('admin.plans.load_timeout', {}, 'Package catalog did not finish loading. Retry, then check the admin plans endpoint if it repeats.')
          : resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load'))
      );
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);

  const handleCreatePlan = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch('/api/admin/plans', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const payload = await readResponsePayload<{ message?: string }>(response);
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_save', {}, 'Failed to save.')));
      }
      setNotice(
        t('admin.plan_saved_notice', {}, 'Plan saved. Publish a plan version next to make it selectable for subscriptions.')
      );
      setForm({ plan_id: '', name: '', status: 'active', description: '' });
      await loadPlans();
    } catch (err) {
      setError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save', {}, 'Failed to save.'))
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleBootstrapShell = useCallback(async (shell: TierSummary) => {
    setIsBootstrapping(true);
    setError(null);
    setNotice(null);
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

      const planResponse = await fetch('/api/admin/plans', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_id: shell.tier_id,
          name: localizedAlias,
          status: 'active',
          description: localizedPositioning,
          metadata,
        }),
      });
      const planPayload = await readResponsePayload<{ message?: string }>(planResponse);
      if (!planResponse.ok) {
        throw new Error(
          resolveUiErrorMessage('message' in planPayload ? planPayload.message : null, t('error.failed_save', {}, 'Failed to save.'))
        );
      }

      const versionResponse = await fetch(`/api/admin/plans/${encodeURIComponent(shell.tier_id)}/versions`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
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
        }),
      });
      const versionPayload = await readResponsePayload<{ message?: string }>(versionResponse);
      if (!versionResponse.ok) {
        throw new Error(
          resolveUiErrorMessage('message' in versionPayload ? versionPayload.message : null, t('error.failed_save', {}, 'Failed to save.'))
        );
      }

      setNotice(
        t(
          'admin.package_shell_bootstrap_notice',
          {},
          `${localizedAlias} package is now available for customer assignment.`
        )
      );
      await loadPlans();
    } catch (err) {
      setError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save', {}, 'Failed to save.'))
      );
    } finally {
      setIsBootstrapping(false);
    }
  }, [loadPlans, t]);

  const handleBootstrapMissingShells = useCallback(async () => {
    const missingShells = tierTemplates.filter((shell) => {
      const existing = findCanonicalShellPlan(plans, shell.tier_id);
      return !existing || Number(existing.published_version_count || 0) === 0;
    });
    if (missingShells.length === 0) {
      setNotice(t('admin.package_shells_present', {}, 'All standard packages are already available.'));
      return;
    }
    for (const shell of missingShells) {
      // Sequential bootstrap keeps notices and server-side upserts predictable.
      await handleBootstrapShell(shell);
    }
  }, [handleBootstrapShell, plans, t, tierTemplates]);

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
  const totalPublishedVersions = canonicalTierCoverage.reduce(
    (sum, entry) => sum + Number(entry.item?.published_version_count || 0),
    0
  );
  const activeSubscriptions = canonicalTierCoverage.reduce(
    (sum, entry) => sum + Number(entry.item?.subscription_counts?.active || 0),
    0
  );
  const missingShellCount = canonicalTierCoverage.filter((entry) => !entry.isPresent).length;

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_plan_catalog', {}, 'Package Catalog')}
        title={t('admin.coverage_package_catalog_title', {}, 'Coverage package catalog')}
        description={t(
          'admin.package_management_center_desc',
          {},
          'Read the active Free, Pro, and Agency package posture first. Open detail only when price, limits, or release state needs maintenance.'
        )}
        descriptionDisplay="hint"
        aside={
          <div className="w-full xl:w-[44rem]">
            <BackofficeMetricStrip
              items={[
                {
                  label: t('admin.managed_packages', {}, 'Managed packages'),
                  value: formatInteger(tierTemplates.length),
                  detail: t('admin.managed_packages_detail', {}, 'Free / Pro / Agency are the main packages exposed to account coverage.'),
                  detailDisplay: 'hint',
                  size: 'compact',
                },
                {
                  label: t('admin.ready_packages', {}, 'Ready packages'),
                  value: formatInteger(visibleCanonicalPlans),
                  detail: missingShellCount > 0
                    ? t('admin.plans.missing_packages_detail', {}, 'Some packages need advanced setup.')
                    : t('admin.plans.ready_packages_detail', {}, 'All public packages have a published record.'),
                  detailDisplay: 'hint',
                  size: 'compact',
                },
                { label: t('admin.active_subscriptions'), value: formatInteger(activeSubscriptions), size: 'compact' },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-3"
            />
          </div>
        }
      >
        {null}
      </BackofficePrimaryPanel>

      <BackofficeLayer
        eyebrow={t('admin.package_tiers', {}, 'Package tiers')}
        title={t('admin.package_price_features_title', {}, 'Packages')}
        description={t(
          'admin.package_price_features_desc',
          {},
          'Compare the public package limits. Maintenance and migration controls stay under Advanced maintenance.'
        )}
        descriptionDisplay="hint"
      />
      <BackofficeSectionPanel className="space-y-4">
        {error ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
            {error}
          </div>
        ) : null}
        <div className="grid gap-4 xl:grid-cols-3">
          {canonicalTierCoverage.map(({ shell, item, isPresent }) => {
            const latestVersion = item?.latest_version || item?.versions?.[0] || null;
            const budgets = (latestVersion?.budgets || shell.budgets_template || {}) as Record<string, unknown>;
            const concurrency = (latestVersion?.concurrency || shell.concurrency_template || {}) as Record<string, unknown>;
            const sourceTier = item?.tier_summary || shell;
            const monthlyIncludedPoints = latestMetadataValue(
              latestVersion,
              sourceTier.monthly_included_points,
              'monthly_included_points'
            );
            const siteLimit = latestMetadataValue(latestVersion, sourceTier.site_limit, 'site_limit');
            const batchCeiling = latestMetadataValue(latestVersion, sourceTier.max_batch_items, 'max_batch_items');
            const features = sourceTier.feature_groups || [];
            const activeSubscriptionCount = Number(item?.subscription_counts?.active || 0);
            const packageAlias = localizePackageAlias(t, shell.tier_id, sourceTier.package_alias);
            return (
              <BackofficeStackCard
                key={`price-features-${shell.tier_id}`}
                className="flex flex-col"
                role="group"
                aria-label={t(
                  'admin.package_card_label',
                  { package: packageAlias },
                  `${packageAlias} package`
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {localizeTierLabel(t, shell.tier_id, sourceTier.label)}
                    </p>
                    <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                      {packageAlias}
                    </h2>
                  </div>
                  <BackofficeStatusBadge
                    status={isPresent ? 'published' : 'draft'}
                    label={isPresent ? t('status.published', {}, 'published') : t('status.draft', {}, 'missing')}
                  />
                </div>
                <PackageStatRows
                  className="mt-5"
                  items={[
                    {
                      label: t('admin.included_points', {}, 'Included points'),
                      value: formatInteger(monthlyIncludedPoints),
                    },
                    {
                      label: t('admin.period_cost_budget', {}, 'Package fee'),
                      value: formatBudgetCurrency(budgets.max_cost_per_period),
                    },
                    {
                      label: t('admin.site_limit', {}, 'Site limit'),
                      value: formatInteger(siteLimit),
                    },
                    {
                      label: t('admin.concurrency', {}, 'Concurrency'),
                      value: formatInteger(numericValue(concurrency.max_active_runs)),
                    },
                    {
                      label: t('admin.batch_ceiling', {}, 'Batch ceiling'),
                      value: formatInteger(batchCeiling),
                    },
                    {
                      label: t('admin.active_subscriptions'),
                      value: formatInteger(activeSubscriptionCount),
                    },
                  ]}
                />
                <div className="mt-4 flex flex-wrap gap-2">
                  {features.length ? (
                    features.map((feature) => (
                      <span
                        key={feature}
                        className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                      >
                        {localizeFeatureGroup(t, feature)}
                      </span>
                    ))
                  ) : (
                    <span className="text-sm text-slate-500 dark:text-slate-400">
                      {t('admin.feature_groups_empty', {}, 'No feature groups attached.')}
                    </span>
                  )}
                </div>
                <div className="mt-5 flex flex-1 items-end justify-between gap-3">
                  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {isPresent
                      ? t(
                          'admin.package_release_summary',
                          {
                            versions: String(item?.published_version_count || 0),
                            subscriptions: String(item?.subscription_counts?.active || 0),
                          },
                          `${item?.subscription_counts?.active || 0} active subscriptions`
                        )
                      : t(
                          'admin.package_missing_release_summary',
                          {},
                          'Create this package before customer assignment.'
                        )}
                  </p>
                  {item?.plan?.plan_id ? (
                    <Link href={`/admin/plans/${item.plan.plan_id}`} className="btn btn-secondary">
                      {t('common.manage', {}, 'Manage')}
                    </Link>
                  ) : (
                    <a href="#package-maintenance" className="btn btn-secondary">
                      {t('admin.plans.open_advanced_setup', {}, 'Advanced setup')}
                    </a>
                  )}
                </div>
              </BackofficeStackCard>
            );
          })}
        </div>
      </BackofficeSectionPanel>

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
        {notice ? (
          <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300">
            {notice}
          </div>
        ) : null}
        {error ? (
          <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
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
            'Use these shortcuts to create any missing Free / Pro / Agency package entries before assigning them to customers.'
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
        <div className="grid gap-4 xl:grid-cols-3">
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

function PackageStatRows({
  items,
  className,
}: {
  items: Array<{ label: string; value: string }>;
  className?: string;
}) {
  return (
    <div className={className}>
      <dl className="grid gap-x-5 gap-y-3 md:grid-cols-2">
        {items.map((item) => (
          <div
            key={item.label}
            className="flex items-baseline justify-between gap-4 border-b border-slate-200/70 pb-2 last:border-b-0 dark:border-slate-800"
            aria-label={`${item.label}: ${item.value}`}
          >
            <dt className="min-w-0 text-sm text-slate-500 dark:text-slate-400">{item.label}</dt>
            <dd className="shrink-0 text-lg font-semibold tabular-nums text-slate-950 dark:text-white">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
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
