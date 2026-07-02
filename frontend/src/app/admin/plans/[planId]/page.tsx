'use client';

import React, { Suspense, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeLayer,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import {
  AdminMutationReceipt,
  type AdminMutationReceiptPayload,
} from '@/components/admin/AdminMutationReceipt';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import {
  localizeFeatureGroup,
  localizeOperatorNote,
  localizePackageAlias,
  localizePackageFitCue,
  localizePlanName,
  localizePositioning,
  localizeTierLabel,
  localizeUsageBand,
} from '@/lib/admin-plan-copy';
import { translateStatusLabel } from '@/lib/status-display';
import { ADMIN_CURRENCY, formatAdminCurrency } from '@/lib/currency';
import { readResponsePayload } from '@/lib/safe-response';
import { formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';

type PlanRecord = {
  plan_id: string;
  name: string;
  status: string;
  description: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type PlanVersionRecord = {
  plan_version_id: string;
  version_label: string;
  status: string;
  currency: string;
  entitlements: Record<string, unknown>;
  budgets: Record<string, unknown>;
  concurrency: Record<string, unknown>;
  policy: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
};

type PlanSubscriptionRecord = {
  subscription: {
    subscription_id: string;
    site_id: string;
    account_id: string;
    status: string;
    plan_version_id: string;
    current_period_end_at?: string;
  };
  site?: {
    site_id?: string;
    name?: string;
  };
  account?: {
    account_id?: string;
    name?: string;
  };
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
  canonical_shell: {
    entitlements: Record<string, unknown>;
    budgets: Record<string, unknown>;
    concurrency: Record<string, unknown>;
    policy: Record<string, unknown>;
    metadata: Record<string, unknown>;
  };
  feature_groups: string[];
};

type PackageFitCue = {
  code: string;
  severity: string;
  title: string;
  detail: string;
};

type PlanDetailPayload = {
  plan: PlanRecord;
  versions: PlanVersionRecord[];
  latest_version?: PlanVersionRecord | null;
  tier_summary: TierSummary;
  package_fit_cues: PackageFitCue[];
  subscriptions: PlanSubscriptionRecord[];
};

type PlanVersionFormState = {
  plan_version_id: string;
  version_label: string;
  status: string;
  currency: string;
  monthly_included_points: string;
  site_limit: string;
  max_runs_per_period: string;
  max_tokens_per_period: string;
  max_cost_per_period: string;
  max_active_runs: string;
  max_batch_items: string;
  grace_period_days: string;
  entitlements_json: string;
  metadata_override_json: string;
  budgets_override_json: string;
  concurrency_override_json: string;
  policy_override_json: string;
};

function prettyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJsonObject(raw: string, label: string): Record<string, unknown> {
  const value = raw.trim();
  if (!value) {
    return {};
  }
  const parsed = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

function mergeJsonObjects(
  base: Record<string, unknown>,
  override: Record<string, unknown>
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...base };
  Object.entries(override).forEach(([key, value]) => {
    const current = result[key];
    if (
      current &&
      typeof current === 'object' &&
      !Array.isArray(current) &&
      value &&
      typeof value === 'object' &&
      !Array.isArray(value)
    ) {
      result[key] = mergeJsonObjects(
        current as Record<string, unknown>,
        value as Record<string, unknown>
      );
      return;
    }
    result[key] = value;
  });
  return result;
}

function numberField(value: unknown): string {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? String(numeric) : '0';
}

function numericValue(value: unknown): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatBudgetCurrency(value: unknown): string {
  return formatAdminCurrency(numericValue(value));
}

function buildInitialForm(detail: PlanDetailPayload | null): PlanVersionFormState {
  const latestVersion = detail?.latest_version || detail?.versions?.[0] || null;
  const tierSummary = detail?.tier_summary;
  const canonicalShell = tierSummary?.canonical_shell;
  const canonicalBudgets = (canonicalShell?.budgets || {}) as Record<string, unknown>;
  const canonicalConcurrency = (canonicalShell?.concurrency || {}) as Record<string, unknown>;
  const canonicalPolicy = (canonicalShell?.policy || {}) as Record<string, unknown>;
  const canonicalMetadata = (canonicalShell?.metadata || {}) as Record<string, unknown>;
  const budgets = (latestVersion?.budgets || canonicalBudgets) as Record<string, unknown>;
  const concurrency = (latestVersion?.concurrency || canonicalConcurrency) as Record<string, unknown>;
  const policy = (latestVersion?.policy || canonicalPolicy) as Record<string, unknown>;
  const metadata = (latestVersion?.metadata || canonicalMetadata) as Record<string, unknown>;
  const policySubscription = (policy.subscription || canonicalPolicy.subscription || {}) as Record<string, unknown>;
  const nextVersionNumber = Number(detail?.versions?.length || 0) + 1;

  return {
    plan_version_id:
      latestVersion?.plan_version_id || `${detail?.plan?.plan_id || 'plan'}_v${nextVersionNumber}`,
    version_label: latestVersion?.version_label || `v${nextVersionNumber}`,
    status: latestVersion?.status || 'published',
    currency: ADMIN_CURRENCY,
    monthly_included_points: numberField(
      metadata.monthly_included_points ?? tierSummary?.monthly_included_points ?? 0
    ),
    site_limit: numberField(metadata.site_limit ?? tierSummary?.site_limit ?? 0),
    max_runs_per_period: numberField(budgets.max_runs_per_period),
    max_tokens_per_period: numberField(budgets.max_tokens_per_period),
    max_cost_per_period: numberField(budgets.max_cost_per_period),
    max_active_runs: numberField(concurrency.max_active_runs),
    max_batch_items: numberField(metadata.max_batch_items ?? tierSummary?.max_batch_items ?? 0),
    grace_period_days: numberField(policySubscription.grace_period_days),
    entitlements_json: prettyJson(latestVersion?.entitlements || canonicalShell?.entitlements || {}),
    metadata_override_json: '{}',
    budgets_override_json: '{}',
    concurrency_override_json: '{}',
    policy_override_json: '{}',
  };
}

function buildBaselineFieldPatch(
  tierSummary: TierSummary | null | undefined
): Partial<PlanVersionFormState> {
  const budgets = (tierSummary?.canonical_shell?.budgets || {}) as Record<string, unknown>;
  const concurrency = (tierSummary?.canonical_shell?.concurrency || {}) as Record<string, unknown>;
  const policyBaseline = ((tierSummary?.canonical_shell?.policy || {}).subscription || {}) as Record<string, unknown>;
  return {
    monthly_included_points: numberField(tierSummary?.monthly_included_points ?? 0),
    site_limit: numberField(tierSummary?.site_limit ?? 0),
    max_runs_per_period: numberField(budgets.max_runs_per_period),
    max_tokens_per_period: numberField(budgets.max_tokens_per_period),
    max_cost_per_period: numberField(budgets.max_cost_per_period),
    max_active_runs: numberField(concurrency.max_active_runs),
    max_batch_items: numberField(tierSummary?.max_batch_items ?? 0),
    grace_period_days: numberField(policyBaseline.grace_period_days),
  };
}

function buildLatestFieldPatch(
  latestVersion: PlanVersionRecord | null | undefined,
  tierSummary: TierSummary | null | undefined
): Partial<PlanVersionFormState> {
  const budgets = (latestVersion?.budgets || tierSummary?.budgets_template || {}) as Record<string, unknown>;
  const concurrency = (latestVersion?.concurrency || tierSummary?.concurrency_template || {}) as Record<string, unknown>;
  const policy = (latestVersion?.policy || {}) as Record<string, unknown>;
  const metadata = (latestVersion?.metadata || {}) as Record<string, unknown>;
  const subscriptionPolicy = (policy.subscription || tierSummary?.policy_baseline || {}) as Record<string, unknown>;
  return {
    monthly_included_points: numberField(
      metadata.monthly_included_points ?? tierSummary?.monthly_included_points ?? 0
    ),
    site_limit: numberField(metadata.site_limit ?? tierSummary?.site_limit ?? 0),
    max_runs_per_period: numberField(budgets.max_runs_per_period),
    max_tokens_per_period: numberField(budgets.max_tokens_per_period),
    max_cost_per_period: numberField(budgets.max_cost_per_period),
    max_active_runs: numberField(concurrency.max_active_runs),
    max_batch_items: numberField(metadata.max_batch_items ?? tierSummary?.max_batch_items ?? 0),
    grace_period_days: numberField(subscriptionPolicy.grace_period_days),
  };
}

function fieldDiffersFromBaseline(
  current: string,
  baseline: string
): boolean {
  return String(current || '').trim() !== String(baseline || '').trim();
}

function resolveCueStatus(severity: string): string {
  switch (severity) {
    case 'ok':
      return 'active';
    case 'warning':
      return 'warning';
    default:
      return 'unknown';
  }
}

function PlanDetailContent() {
  const params = useParams();
  const { t } = useLocale();
  const { planId } = params as { planId: string };

  const [detail, setDetail] = useState<PlanDetailPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastReceipt, setLastReceipt] = useState<AdminMutationReceiptPayload | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [form, setForm] = useState<PlanVersionFormState>(() => buildInitialForm(null));

  const loadDetail = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/admin/plans/${encodeURIComponent(planId)}`, {
        credentials: 'include',
      });
      const payload = await readResponsePayload<{ data?: PlanDetailPayload; message?: string }>(response);
      if (!response.ok) {
        throw new Error(
          resolveUiErrorMessage(
            'message' in payload ? payload.message : null,
            t('error.failed_load')
          )
        );
      }
      setDetail(('data' in payload ? payload.data : null) as PlanDetailPayload);
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [planId, t]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  useEffect(() => {
    if (detail?.plan) {
      setForm(buildInitialForm(detail));
    }
  }, [detail]);

  const handlePublishVersion = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail) {
      return;
    }
    setIsSaving(true);
    setNotice(null);
    setLastReceipt(null);
    setError(null);
    try {
      const baseMetadata = mergeJsonObjects(
        mergeJsonObjects(
          {
            tier_id: detail.tier_summary?.tier_id || '',
            source:
              (latestVersion?.metadata?.source as string | undefined) ||
              'operator_plan_version_form',
          },
          latestVersion?.metadata || {}
        ),
        {
          monthly_included_points: Number(form.monthly_included_points || 0),
          site_limit: Number(form.site_limit || 0),
          max_batch_items: Number(form.max_batch_items || 0),
        }
      );
      const payload = {
        plan_version_id: form.plan_version_id,
        version_label: form.version_label,
        status: form.status,
        currency: ADMIN_CURRENCY,
        entitlements: parseJsonObject(form.entitlements_json, 'Entitlements'),
        budgets: mergeJsonObjects(
          {
            max_runs_per_period: Number(form.max_runs_per_period || 0),
            max_tokens_per_period: Number(form.max_tokens_per_period || 0),
            max_cost_per_period: Number(form.max_cost_per_period || 0),
          },
          parseJsonObject(form.budgets_override_json, 'Budgets override')
        ),
        concurrency: mergeJsonObjects(
          {
            max_active_runs: Number(form.max_active_runs || 0),
          },
          parseJsonObject(form.concurrency_override_json, 'Concurrency override')
        ),
        policy: mergeJsonObjects(
          {
            subscription: {
              grace_period_days: Number(form.grace_period_days || 0),
            },
            budgets: {},
          },
          parseJsonObject(form.policy_override_json, 'Policy override')
        ),
        metadata: mergeJsonObjects(
          baseMetadata,
          parseJsonObject(form.metadata_override_json, 'Metadata override')
        ),
      };
      const response = await fetch(`/api/admin/plans/${encodeURIComponent(planId)}/versions`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await readResponsePayload<{ data?: { receipt?: AdminMutationReceiptPayload | null }; message?: string }>(response);
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage('message' in data ? data.message : null, t('error.failed_save', {}, 'Failed to save.')));
      }
      setNotice(
        t('admin.coverage_package_release_saved_notice', {}, 'Coverage package release published. You can now bind it to customer subscriptions.')
      );
      setLastReceipt((('data' in data ? data.data?.receipt : null) ?? null) as AdminMutationReceiptPayload | null);
      await loadDetail();
    } catch (err) {
      setError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save', {}, 'Failed to save.'))
      );
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return <LoadingFallback />;
  }

  if (error && !detail) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-red-600">{t('common.error')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{error}</p>
          <button onClick={() => void loadDetail()} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  if (!detail) {
    return null;
  }

  const latestVersion = detail.latest_version || detail.versions[0] || null;
  const tierSummary = detail.tier_summary;
  const templateBudgets = (tierSummary?.budgets_template || {}) as {
    max_runs_per_period?: number;
    max_tokens_per_period?: number;
    max_cost_per_period?: number;
  };
  const templateConcurrency = (tierSummary?.concurrency_template || {}) as {
    max_active_runs?: number;
  };
  const latestBudgets = (latestVersion?.budgets || {}) as {
    max_runs_per_period?: number;
    max_tokens_per_period?: number;
    max_cost_per_period?: number;
  };
  const latestConcurrency = (latestVersion?.concurrency || {}) as { max_active_runs?: number };
  const policyBaseline = (tierSummary?.policy_baseline || {}) as {
    grace_period_days?: number;
    downgrade_policy?: string;
  };
  const localizedPlanName = localizePlanName(t, detail.plan.plan_id, detail.plan.name);
  const localizedPackageAlias = localizePackageAlias(
    t,
    tierSummary?.tier_id || detail.plan.plan_id,
    tierSummary?.package_alias || tierSummary?.label || detail.plan.name
  );
  const localizedTierLabel = localizeTierLabel(t, tierSummary?.tier_id || detail.plan.plan_id, tierSummary?.label);
  const localizedUsageBand = localizeUsageBand(t, tierSummary?.tier_id || detail.plan.plan_id, tierSummary?.usage_band);
  const localizedPositioning = localizePositioning(
    t,
    tierSummary?.tier_id || detail.plan.plan_id,
    tierSummary?.positioning || detail.plan.description
  );
  const localizedOperatorNote = localizeOperatorNote(
    t,
    tierSummary?.tier_id || detail.plan.plan_id,
    tierSummary?.package_operator_note || String(policyBaseline.downgrade_policy || '')
  );
  const planKind = String(detail.plan.metadata?.plan_kind || latestVersion?.metadata?.plan_kind || '');
  const isFormalProductionPlan = detail.plan.plan_id === 'plan_free' || planKind === 'default_free';
  const baselineFieldPatch = buildBaselineFieldPatch(tierSummary);
  const latestFieldPatch = buildLatestFieldPatch(latestVersion, tierSummary);
  const primaryPackageFitCue = detail.package_fit_cues?.[0]
    ? localizePackageFitCue(t, detail.package_fit_cues[0])
    : null;
  const linkedSubscriptionCount = detail.subscriptions.length;
  const subscriptionQueueHref = `/admin/subscriptions?plan_id=${encodeURIComponent(detail.plan.plan_id)}`;
  const baselineActionLabel = t(
    'admin.apply_tier_baseline',
    { tier: localizedPackageAlias || localizedTierLabel || 'tier' },
    `Apply ${localizedPackageAlias || localizedTierLabel || 'tier'} baseline`
  );

  const applyStructuredPatch = (patch: Partial<PlanVersionFormState>) => {
    setForm((current) => ({
      ...current,
      ...patch,
    }));
  };

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.coverage_package_catalog_title', {}, 'Coverage package catalog')}
        title={localizedPlanName}
        description={
          localizedPositioning ||
          t('admin.coverage_package_detail_desc', {}, 'This page should explain the coverage package before the operator touches raw JSON.')
        }
        aside={
          <div className="w-full xl:w-[46rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('common.package', {}, 'Package'), value: localizedPackageAlias || t('common.not_found'), size: 'compact' },
                { label: t('admin.coverage_package_id', {}, 'Coverage package ID'), value: <BackofficeIdentifier value={detail.plan.plan_id} />, size: 'compact' },
                {
                  label: t('admin.coverage_package_releases', {}, 'Package releases'),
                  value: formatInteger(detail.versions.length),
                  size: 'compact',
                },
                {
                  label: t('admin.linked_subscriptions', {}, 'Subscription impact'),
                  value: formatInteger(linkedSubscriptionCount),
                  size: 'compact',
                },
                {
                  label: t('admin.site_limit', {}, 'Site limit'),
                  value: formatInteger(Number(tierSummary?.site_limit || 0)),
                  size: 'compact',
                },
                {
                  label: t('admin.plan_posture', {}, 'Plan posture'),
                  value: isFormalProductionPlan
                    ? t('admin.formal_production_plan', {}, 'Formal production plan')
                    : t('admin.tier_template_binding', {}, 'Tier-bound plan'),
                  size: 'compact',
                },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-6"
            />
          </div>
        }
      >
        <div className="flex flex-wrap gap-2">
          <a href="#package-release-editor" className="btn btn-primary">
            {t('admin.edit_package_release_fields', {}, 'Edit package')}
          </a>
          {linkedSubscriptionCount ? (
            <Link href={subscriptionQueueHref} className="btn btn-secondary">
              {t('admin.open_linked_subscriptions', {}, 'Open subscriptions')}
            </Link>
          ) : null}
          <Link href="/admin/plans" className="btn btn-secondary">
            {t('admin.package_management_center_title', {}, 'Package management')}
          </Link>
        </div>
        {latestVersion ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <BackofficeStatusBadge
              status={latestVersion.status}
              label={translateStatusLabel(latestVersion.status, t)}
            />
            <span className="text-sm text-slate-600 dark:text-slate-300">
              {t('admin.latest_coverage_package_release', {}, 'Latest package release')}: {latestVersion.version_label}
            </span>
          </div>
        ) : null}
        {primaryPackageFitCue ? (
          <BackofficeStackCard className="mt-4 bg-white/80 dark:bg-slate-950/55">
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {primaryPackageFitCue.title}
            </p>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {primaryPackageFitCue.detail}
            </p>
          </BackofficeStackCard>
        ) : null}
      </BackofficePrimaryPanel>

      <details className="rounded-2xl border border-dashed border-slate-200 px-4 py-4 dark:border-slate-800">
        <summary className="cursor-pointer list-none text-sm font-medium text-slate-700 dark:text-slate-300">
          {t('admin.package_detail_diagnostics_toggle', {}, 'Inspect package fit, budget template, and cost evidence')}
        </summary>
      <BackofficeLayer
        className="mt-4"
        eyebrow={t('admin.package_tiers', {}, 'Package tiers')}
        title={t('admin.coverage_package_workspace_title', {}, 'Coverage package posture and fit')}
        description={t(
          'admin.coverage_package_workspace_desc',
          {},
          'Keep this page focused on coverage package quality. Package releases freeze entitlements, budgets, concurrency, and policy on the existing commercial truth plane.'
        )}
      />
      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('common.summary')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.plan_budget_template', {}, 'Budget and policy template')}
            </h2>
          </div>
          <BackofficeMetricStrip
            items={[
          {
            label: t('admin.included_points', {}, 'Included points'),
            value: formatInteger(Number(tierSummary?.monthly_included_points || 0)),
            detail: t('admin.included_points_detail', {}, 'Presentation-layer monthly included points for package explanation only.'),
          },
          {
            label: t('admin.site_limit', {}, 'Site limit'),
            value: formatInteger(Number(tierSummary?.site_limit || 0)),
            detail: t('admin.site_limit_detail', {}, 'Maximum covered sites on the current customer subscription.'),
          },
          {
            label: t('billing.runs', {}, 'Runs'),
            value: formatInteger(Number(templateBudgets.max_runs_per_period || 0)),
                detail: t('admin.plan_template_runs_detail', {}, 'Tier baseline run ceiling per period.'),
              },
              {
                label: t('common.tokens'),
                value: formatInteger(Number(templateBudgets.max_tokens_per_period || 0)),
                detail: t('admin.plan_template_tokens_detail', {}, 'Tier baseline token ceiling per period.'),
              },
              {
                label: t('common.cost'),
                value: String(Number(templateBudgets.max_cost_per_period || 0)),
                detail: t('admin.plan_template_cost_detail', {}, 'Tier baseline cost ceiling per period.'),
              },
              {
                label: t('admin.concurrency', {}, 'Concurrency'),
                value: formatInteger(Number(templateConcurrency.max_active_runs || 0)),
                detail: t('admin.plan_template_concurrency_detail', {}, 'Tier baseline active run ceiling.'),
              },
              {
                label: t('admin.batch_ceiling', {}, 'Batch ceiling'),
                value: formatInteger(Number(tierSummary?.max_batch_items || 0)),
                detail: t('admin.batch_ceiling_detail', {}, 'Operator-facing batch headroom for this package.'),
              },
            ]}
            columnsClassName="md:grid-cols-3"
          />
          <BackofficeStackCard>
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('admin.package_posture', {}, 'Package posture')}
            </p>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.package_core_surface_shared',
                {},
                'Core capability entry stays shared across packages; commercial differentiation comes from current-period headroom, site limit, concurrency, batch ceiling, and policy headroom.'
              )}
            </p>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t('admin.site_limit_label', {}, 'Site limit')}: {formatInteger(Number(tierSummary?.site_limit || 0))}
            </p>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t('admin.grace_period_label', {}, 'Grace period')}: {formatInteger(Number(policyBaseline.grace_period_days || 0))} {t('common.days', {}, 'days')}
            </p>
            <p className="mt-2 text-sm leading-7 text-slate-600 dark:text-slate-300">
              {localizedOperatorNote ||
                String(policyBaseline.downgrade_policy || t('admin.policy_baseline_missing', {}, 'No downgrade note was attached to this default template.'))}
            </p>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('admin.latest_coverage_package_release', {}, 'Latest package release')}
            </p>
            {latestVersion ? (
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <Metric label={t('common.label')} value={latestVersion.version_label} />
                <Metric
                  label={t('common.status')}
                  value={
                    <BackofficeStatusBadge
                      status={latestVersion.status}
                      label={translateStatusLabel(latestVersion.status, t)}
                    />
                  }
                />
                <Metric label={t('billing.runs', {}, 'Runs')} value={formatInteger(Number(latestBudgets.max_runs_per_period || 0))} />
                <Metric label={t('common.tokens')} value={formatInteger(Number(latestBudgets.max_tokens_per_period || 0))} />
                <Metric label={t('common.cost')} value={String(Number(latestBudgets.max_cost_per_period || 0))} />
                <Metric label={t('admin.site_limit', {}, 'Site limit')} value={formatInteger(Number((latestVersion.metadata || {}).site_limit || tierSummary?.site_limit || 0))} />
                <Metric label={t('admin.concurrency', {}, 'Concurrency')} value={formatInteger(Number(latestConcurrency.max_active_runs || 0))} />
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
                {t('admin.coverage_package_releases_empty', {}, 'No package release has been published yet.')}
              </p>
            )}
          </BackofficeStackCard>
        </BackofficeSectionPanel>

      </div>
      </details>

      <BackofficeLayer
        eyebrow={t('admin.package_tiers', {}, 'Package tiers')}
        title={t('admin.package_price_features_title', {}, 'Package settings')}
        description={t(
          'admin.package_price_features_detail_desc',
          {},
          'Adjust the visible package limits here. Advanced release IDs and raw JSON stay collapsed unless you need an exceptional override.'
        )}
      />
      <BackofficeSectionPanel className="space-y-4">
        <BackofficeMetricStrip
          items={[
            {
              label: t('admin.period_cost_budget', {}, 'Period cost budget'),
              value: formatBudgetCurrency(latestBudgets.max_cost_per_period),
              detail: t('admin.period_cost_budget_detail', {}, 'Stored budget ceiling for this package period.'),
            },
            {
              label: t('billing.runs', {}, 'Runs'),
              value: formatInteger(numericValue(latestBudgets.max_runs_per_period ?? templateBudgets.max_runs_per_period)),
              detail: t('admin.plan_template_runs_detail', {}, 'Tier baseline run ceiling per period.'),
            },
            {
              label: t('common.tokens'),
              value: formatInteger(numericValue(latestBudgets.max_tokens_per_period ?? templateBudgets.max_tokens_per_period)),
              detail: t('admin.plan_template_tokens_detail', {}, 'Tier baseline token ceiling per period.'),
            },
            {
              label: t('admin.site_limit', {}, 'Site limit'),
              value: formatInteger(numericValue((latestVersion?.metadata || {}).site_limit || tierSummary?.site_limit)),
              detail: t('admin.site_limit_detail', {}, 'Maximum covered sites on the current customer subscription.'),
            },
            {
              label: t('admin.concurrency', {}, 'Concurrency'),
              value: formatInteger(numericValue(latestConcurrency.max_active_runs ?? templateConcurrency.max_active_runs)),
              detail: t('admin.plan_template_concurrency_detail', {}, 'Tier baseline active run ceiling.'),
            },
            {
              label: t('admin.batch_ceiling', {}, 'Batch ceiling'),
              value: formatInteger(numericValue((latestVersion?.metadata || {}).max_batch_items || tierSummary?.max_batch_items)),
              detail: t('admin.batch_ceiling_detail', {}, 'Operator-facing batch headroom for this package.'),
            },
          ]}
          columnsClassName="md:grid-cols-3"
        />
        <BackofficeStackCard>
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('admin.feature_groups', {}, 'Feature groups')}
              </p>
              <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t(
                  'admin.feature_groups_desc',
                  {},
                  'These are the operator-readable feature groups attached to this package posture. The raw entitlement JSON remains available only for exceptional changes.'
                )}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {(tierSummary?.feature_groups || []).length ? (
                  (tierSummary?.feature_groups || []).map((feature) => (
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
            </div>
            <a href="#package-release-editor" className="btn btn-secondary">
              {t('admin.edit_package_release_fields', {}, 'Edit package')}
            </a>
          </div>
        </BackofficeStackCard>
      </BackofficeSectionPanel>

      <BackofficeLayer
        eyebrow={t('admin.quick_actions')}
        title={t('admin.publish_coverage_package_release_title', {}, 'Edit package limits')}
        description={t(
          'admin.publish_coverage_package_release_desc',
          {},
          'Change the common limits first. Saving creates the next internal package version, but operators do not need to manage version fields for normal updates.'
        )}
      />
      <div id="package-release-editor">
      <BackofficeSectionPanel>
        {notice ? (
          <div className="mb-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300">
            {notice}
          </div>
        ) : null}
        {lastReceipt ? (
          <div className="mb-4">
            <AdminMutationReceipt
              receipt={lastReceipt}
              title={t('admin.latest_receipt', {}, 'Latest receipt')}
            />
          </div>
        ) : null}
        {error ? (
          <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
            {error}
          </div>
        ) : null}
        <form className="space-y-5" onSubmit={handlePublishVersion}>
          <BackofficeStackCard>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-slate-950 dark:text-white">
                  {t('admin.plan_editor_flow_title', {}, 'Package values')}
                </p>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                  {t(
                    'admin.coverage_package_editor_flow_desc',
                    {},
                    'Most edits should only touch price, usage limits, sites, concurrency, batch size, or grace days.'
                  )}
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => applyStructuredPatch(latestFieldPatch)}
                >
                  {t('admin.reset_to_latest_version', {}, 'Reset to latest release')}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => applyStructuredPatch(baselineFieldPatch)}
                >
                  {baselineActionLabel}
                </button>
              </div>
            </div>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('admin.plan_package_fields_title', {}, 'Common package fields')}
            </p>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.plan_package_fields_desc',
                {},
                'These are the fields operators normally need. Currency is fixed to CNY for the platform admin.'
              )}
            </p>
            <div className="mt-4 grid gap-4 xl:grid-cols-3">
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.cost')}</span>
                <input value={form.max_cost_per_period} onChange={(e) => setForm((c) => ({ ...c, max_cost_per_period: e.target.value }))} className="input w-full" type="number" min="0" step="0.01" />
                <FieldBaselineHint
                  differs={fieldDiffersFromBaseline(form.max_cost_per_period, String(baselineFieldPatch.max_cost_per_period || '0'))}
                  baselineValue={String(baselineFieldPatch.max_cost_per_period || '0')}
                  t={t}
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.included_points', {}, 'Included points')}</span>
                <input value={form.monthly_included_points} onChange={(e) => setForm((c) => ({ ...c, monthly_included_points: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                <FieldBaselineHint
                  differs={fieldDiffersFromBaseline(form.monthly_included_points, String(baselineFieldPatch.monthly_included_points || '0'))}
                  baselineValue={String(baselineFieldPatch.monthly_included_points || '0')}
                  t={t}
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.batch_ceiling', {}, 'Batch ceiling')}</span>
                <input value={form.max_batch_items} onChange={(e) => setForm((c) => ({ ...c, max_batch_items: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                <FieldBaselineHint
                  differs={fieldDiffersFromBaseline(form.max_batch_items, String(baselineFieldPatch.max_batch_items || '0'))}
                  baselineValue={String(baselineFieldPatch.max_batch_items || '0')}
                  t={t}
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.site_limit', {}, 'Site limit')}</span>
                <input value={form.site_limit} onChange={(e) => setForm((c) => ({ ...c, site_limit: e.target.value }))} className="input w-full" type="number" min="1" step="1" />
                <FieldBaselineHint
                  differs={fieldDiffersFromBaseline(form.site_limit, String(baselineFieldPatch.site_limit || '0'))}
                  baselineValue={String(baselineFieldPatch.site_limit || '0')}
                  t={t}
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('billing.runs', {}, 'Runs')}</span>
                <input value={form.max_runs_per_period} onChange={(e) => setForm((c) => ({ ...c, max_runs_per_period: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                <FieldBaselineHint
                  differs={fieldDiffersFromBaseline(form.max_runs_per_period, String(baselineFieldPatch.max_runs_per_period || '0'))}
                  baselineValue={String(baselineFieldPatch.max_runs_per_period || '0')}
                  t={t}
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.tokens')}</span>
                <input value={form.max_tokens_per_period} onChange={(e) => setForm((c) => ({ ...c, max_tokens_per_period: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                <FieldBaselineHint
                  differs={fieldDiffersFromBaseline(form.max_tokens_per_period, String(baselineFieldPatch.max_tokens_per_period || '0'))}
                  baselineValue={String(baselineFieldPatch.max_tokens_per_period || '0')}
                  t={t}
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.concurrency', {}, 'Concurrency')}</span>
                <input value={form.max_active_runs} onChange={(e) => setForm((c) => ({ ...c, max_active_runs: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                <FieldBaselineHint
                  differs={fieldDiffersFromBaseline(form.max_active_runs, String(baselineFieldPatch.max_active_runs || '0'))}
                  baselineValue={String(baselineFieldPatch.max_active_runs || '0')}
                  t={t}
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.grace_period_label', {}, 'Grace period')}</span>
                <input value={form.grace_period_days} onChange={(e) => setForm((c) => ({ ...c, grace_period_days: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                <FieldBaselineHint
                  differs={fieldDiffersFromBaseline(form.grace_period_days, String(baselineFieldPatch.grace_period_days || '0'))}
                  baselineValue={String(baselineFieldPatch.grace_period_days || '0')}
                  t={t}
                />
              </label>
            </div>
          </BackofficeStackCard>
          <details className="rounded-3xl border border-slate-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-950/60">
            <summary className="cursor-pointer list-none text-sm font-semibold text-slate-950 dark:text-white">
              {t('admin.package_release_metadata_title', {}, 'Advanced release fields')}
            </summary>
            <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.package_release_metadata_desc',
                {},
                'Leave these defaults unchanged for normal package edits. They exist only for traceability and staged releases.'
              )}
            </p>
            <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr_0.8fr_0.8fr]">
              <label className="text-sm xl:col-span-2">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.coverage_package_release_id_label', {}, 'Package release ID')}</span>
                <input value={form.plan_version_id} onChange={(e) => setForm((c) => ({ ...c, plan_version_id: e.target.value }))} className="input w-full" required />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.label')}</span>
                <input value={form.version_label} onChange={(e) => setForm((c) => ({ ...c, version_label: e.target.value }))} className="input w-full" required />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.status')}</span>
                <select value={form.status} onChange={(e) => setForm((c) => ({ ...c, status: e.target.value }))} className="input w-full">
                  <option value="published">{t('status.published', {}, 'published')}</option>
                  <option value="draft">{t('status.draft', {}, 'draft')}</option>
                  <option value="archived">{t('status.archived', {}, 'archived')}</option>
                </select>
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.currency', {}, 'Currency')}</span>
                <input value={ADMIN_CURRENCY} className="input w-full" readOnly />
              </label>
            </div>
          </details>
          <details className="rounded-3xl border border-slate-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-950/60">
            <summary className="cursor-pointer list-none text-sm font-semibold text-slate-950 dark:text-white">
              {t('admin.plan_advanced_json_title', {}, 'Advanced JSON overrides')}
            </summary>
            <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.plan_advanced_json_desc',
                {},
                'Keep raw JSON here as an escape hatch. Structured fields still drive the default package maintenance path.'
              )}
            </p>
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {t(
                'admin.plan_advanced_json_rare',
                {},
                'Rare override only. Normal package maintenance should not require editing entitlements or raw budgets/concurrency/policy JSON.'
              )}
            </p>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <JsonField label={t('admin.entitlements', {}, 'Entitlements')} value={form.entitlements_json} onChange={(value) => setForm((c) => ({ ...c, entitlements_json: value }))} />
              <JsonField label={t('admin.metadata_override', {}, 'Metadata override')} value={form.metadata_override_json} onChange={(value) => setForm((c) => ({ ...c, metadata_override_json: value }))} minHeightClassName="min-h-28" />
              <JsonField label={t('admin.budgets_override', {}, 'Budgets override')} value={form.budgets_override_json} onChange={(value) => setForm((c) => ({ ...c, budgets_override_json: value }))} minHeightClassName="min-h-28" />
              <JsonField label={t('admin.concurrency_override', {}, 'Concurrency override')} value={form.concurrency_override_json} onChange={(value) => setForm((c) => ({ ...c, concurrency_override_json: value }))} minHeightClassName="min-h-28" />
              <div className="xl:col-span-2">
                <JsonField label={t('admin.policy_override', {}, 'Policy override')} value={form.policy_override_json} onChange={(value) => setForm((c) => ({ ...c, policy_override_json: value }))} minHeightClassName="min-h-28" />
              </div>
            </div>
          </details>
          <div className="flex justify-end">
            <button type="submit" className="btn btn-primary" disabled={isSaving}>
              {isSaving ? t('common.saving', {}, 'Saving…') : t('admin.save_package_changes', {}, 'Save package changes')}
            </button>
          </div>
        </form>
      </BackofficeSectionPanel>
      </div>

      <details className="rounded-[1.6rem] border border-slate-200/80 bg-white/90 px-5 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/70">
        <summary className="cursor-pointer list-none text-sm font-semibold text-slate-950 dark:text-white">
          {t('admin.published_coverage_package_releases', {}, 'Release history')}
        </summary>
        <div className="mt-4 space-y-4">
          {detail.versions.map((version) => (
            <BackofficeStackCard key={version.plan_version_id}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{version.version_label}</h2>
                  <div className="mt-1">
                    <BackofficeIdentifier value={version.plan_version_id} />
                  </div>
                </div>
                <BackofficeStatusBadge
                  status={version.status}
                  label={translateStatusLabel(version.status, t)}
                />
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <Metric label={t('common.created')} value={formatDate(version.created_at)} />
                <Metric label={t('common.currency', {}, 'Currency')} value={version.currency} />
                <Metric label={t('admin.entitlements', {}, 'Entitlements')} value={Object.keys(version.entitlements || {}).length} />
                <Metric label={t('admin.budgets', {}, 'Budgets')} value={Object.keys(version.budgets || {}).length} />
              </div>
            </BackofficeStackCard>
          ))}
        </div>
      </details>
    </BackofficePageStack>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200/80 px-4 py-3 dark:border-slate-800">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{value}</p>
    </div>
  );
}

function JsonField({
  label,
  value,
  onChange,
  minHeightClassName = 'min-h-40',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  minHeightClassName?: string;
}) {
  return (
    <label className="text-sm">
      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{label}</span>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`input w-full font-mono text-xs ${minHeightClassName}`}
      />
    </label>
  );
}

function FieldBaselineHint({
  differs,
  baselineValue,
  t,
}: {
  differs: boolean;
  baselineValue: string;
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string;
}) {
  return (
    <span className={`mt-2 block text-xs ${differs ? 'text-amber-600 dark:text-amber-300' : 'text-slate-500 dark:text-slate-400'}`}>
      {differs
        ? t('admin.field_differs_from_tier_baseline', { baseline: baselineValue }, `Differs from default template (${baselineValue}).`)
        : t('admin.field_matches_tier_baseline', { baseline: baselineValue }, `Matches default template (${baselineValue}).`)}
    </span>
  );
}

export default function AdminPlanDetailPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PlanDetailContent />
    </Suspense>
  );
}
