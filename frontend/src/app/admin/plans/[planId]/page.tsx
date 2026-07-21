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
} from '@/lib/admin-plan-copy';
import { createApiClient } from '@/lib/api-client';
import { translateStatusLabel } from '@/lib/status-display';
import { ADMIN_CURRENCY } from '@/lib/currency';
import { formatCurrency, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';
import { useDialogKeyboard } from '@/hooks/useDialogKeyboard';

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
  max_vector_documents: number;
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
  sales_offer?: {
    offer_id: string;
    amount: number;
    currency: string;
    status: string;
    plan_version_id: string;
  } | null;
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
  max_vector_documents: string;
  max_cost_per_period: string;
  sales_price_cny: string;
  max_active_runs: string;
  max_batch_items: string;
  grace_period_days: string;
  entitlements_json: string;
  metadata_override_json: string;
  budgets_override_json: string;
  concurrency_override_json: string;
  policy_override_json: string;
};

const planDetailClient = createApiClient({ idempotencyPrefix: 'admin_plan_detail' });

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
  return formatCurrency(numericValue(value), 'USD');
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
      budgets.max_ai_credits_per_period ?? metadata.monthly_included_points ?? tierSummary?.monthly_included_points ?? 0
    ),
    site_limit: numberField(metadata.site_limit ?? tierSummary?.site_limit ?? 0),
    max_vector_documents: numberField(metadata.max_vector_documents ?? tierSummary?.max_vector_documents ?? 0),
    max_cost_per_period: numberField(budgets.max_cost_per_period),
    sales_price_cny: numberField(detail?.sales_offer?.amount),
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
    max_vector_documents: numberField(tierSummary?.max_vector_documents ?? 0),
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
      budgets.max_ai_credits_per_period ?? metadata.monthly_included_points ?? tierSummary?.monthly_included_points ?? 0
    ),
    site_limit: numberField(metadata.site_limit ?? tierSummary?.site_limit ?? 0),
    max_vector_documents: numberField(metadata.max_vector_documents ?? tierSummary?.max_vector_documents ?? 0),
    max_cost_per_period: numberField(budgets.max_cost_per_period),
    max_active_runs: numberField(concurrency.max_active_runs),
    max_batch_items: numberField(metadata.max_batch_items ?? tierSummary?.max_batch_items ?? 0),
    grace_period_days: numberField(subscriptionPolicy.grace_period_days),
  };
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
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [advancedInfoTab, setAdvancedInfoTab] = useState<'diagnostics' | 'history'>('diagnostics');
  const [form, setForm] = useState<PlanVersionFormState>(() => buildInitialForm(null));
  const editorDialogRef = useDialogKeyboard<HTMLElement>({
    open: isEditorOpen,
    onClose: () => {
      if (!isSaving) setIsEditorOpen(false);
    },
    closeDisabled: isSaving,
  });

  const loadDetail = useCallback(async (options: { showLoading?: boolean } = {}) => {
    const showLoading = options.showLoading ?? true;
    if (showLoading) {
      setIsLoading(true);
    }
    setError(null);
    try {
      const payload = (await planDetailClient.request<PlanDetailPayload>(
        `/api/admin/plans/${encodeURIComponent(planId)}`
      )).data;
      setDetail(payload);
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
    } finally {
      if (showLoading) {
        setIsLoading(false);
      }
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
          max_vector_documents: Number(form.max_vector_documents || 0),
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
            max_ai_credits_per_period: Number(form.monthly_included_points || 0),
            max_runs_per_period: 0,
            max_tokens_per_period: 0,
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
        sales_price_cny: Number(form.sales_price_cny || 0),
      };
      const data = (await planDetailClient.request<{ receipt?: AdminMutationReceiptPayload | null }>(
        `/api/admin/plans/${encodeURIComponent(planId)}/versions`, {
        method: 'POST',
        body: payload,
      })).data;
      setNotice(
        t(
          'admin.coverage_package_release_saved_notice',
          {},
          'Package changes saved and published. Existing subscriptions on this package use the latest values.'
        )
      );
      setLastReceipt(data.receipt ?? null);
      await loadDetail({ showLoading: false });
      setIsEditorOpen(false);
    } catch (err) {
      setError(
        resolveUiErrorMessage(err, t('error.failed_save', {}, 'Failed to save.'))
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
    max_ai_credits_per_period?: number;
    max_cost_per_period?: number;
  };
  const templateConcurrency = (tierSummary?.concurrency_template || {}) as {
    max_active_runs?: number;
  };
  const latestBudgets = (latestVersion?.budgets || {}) as {
    max_ai_credits_per_period?: number;
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
  const baselineFieldPatch = buildBaselineFieldPatch(tierSummary);
  const latestFieldPatch = buildLatestFieldPatch(latestVersion, tierSummary);
  const primaryPackageFitCue = detail.package_fit_cues?.[0]
    ? localizePackageFitCue(t, detail.package_fit_cues[0])
    : null;
  const linkedSubscriptionCount = detail.subscriptions.length;
  const subscriptionQueueHref = `/admin/subscriptions?plan_id=${encodeURIComponent(detail.plan.plan_id)}`;
  const latestMetadata = (latestVersion?.metadata || {}) as Record<string, unknown>;
  const effectiveSiteLimit = numericValue(latestMetadata.site_limit ?? tierSummary?.site_limit);
  const effectiveVectorDocuments = numericValue(
    latestMetadata.max_vector_documents ?? tierSummary?.max_vector_documents
  );
  const effectivePackagePoints = numericValue(
    latestBudgets.max_ai_credits_per_period ??
      latestMetadata.monthly_included_points ??
      tierSummary?.monthly_included_points
  );
  const templateActionLabel = t(
    'admin.apply_tier_baseline',
    { tier: localizedPackageAlias || localizedTierLabel || 'tier' },
    `Restore ${localizedPackageAlias || localizedTierLabel || 'tier'} suggested values`
  );

  const applyStructuredPatch = (patch: Partial<PlanVersionFormState>) => {
    setForm((current) => ({
      ...current,
      ...patch,
    }));
  };

  const openEditor = () => {
    setForm(buildInitialForm(detail));
    setError(null);
    setIsEditorOpen(true);
  };

  const closeEditor = () => {
    if (!isSaving) {
      setIsEditorOpen(false);
    }
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
                {
                  label: t('admin.linked_subscriptions', {}, 'Subscription impact'),
                  value: formatInteger(linkedSubscriptionCount),
                  size: 'compact',
                },
                {
                  label: t('admin.site_limit', {}, 'Site limit'),
                  value: formatInteger(effectiveSiteLimit),
                  size: 'compact',
                },
                {
                  label: t('common.status'),
                  value: latestVersion ? (
                    <BackofficeStatusBadge
                      status={latestVersion.status}
                      label={translateStatusLabel(latestVersion.status, t)}
                    />
                  ) : (
                    t('common.not_found')
                  ),
                  size: 'compact',
                },
              ]}
              columnsClassName="md:grid-cols-3"
            />
          </div>
        }
      >
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={openEditor} className="btn btn-primary">
            {t('admin.edit_package_release_fields', {}, 'Edit package')}
          </button>
          {linkedSubscriptionCount ? (
            <Link href={subscriptionQueueHref} className="btn btn-secondary">
              {t('admin.open_linked_subscriptions', {}, 'Open subscriptions')}
            </Link>
          ) : null}
          <Link href="/admin/plans" className="btn btn-secondary">
            {t('admin.package_management_center_title', {}, 'Package management')}
          </Link>
        </div>
      </BackofficePrimaryPanel>

      {notice || lastReceipt ? (
        <BackofficeSectionPanel className="space-y-4">
          {notice ? (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300">
              {notice}
            </div>
          ) : null}
          {lastReceipt ? (
            <AdminMutationReceipt
              receipt={lastReceipt}
              title={t('admin.latest_receipt', {}, 'Latest receipt')}
            />
          ) : null}
        </BackofficeSectionPanel>
      ) : null}

      <BackofficeLayer
        eyebrow={t('admin.package_tiers', {}, 'Package tiers')}
        title={t('admin.package_price_features_title', {}, 'Package settings')}
        description={t(
          'admin.package_price_features_detail_desc',
          {},
          'These are the values current subscriptions read from this package.'
        )}
      />
      <BackofficeSectionPanel className="space-y-4">
        <BackofficeMetricStrip
          items={[
            {
              label: t('admin.included_points', {}, 'Package points'),
              value: formatInteger(effectivePackagePoints),
              detail: t('admin.included_points_detail', {}, 'Current-period package points shared by all sites on this account.'),
            },
            {
              label: t('admin.site_limit', {}, 'Site limit'),
              value: formatInteger(numericValue((latestVersion?.metadata || {}).site_limit || tierSummary?.site_limit)),
              detail: t('admin.site_limit_detail', {}, 'Maximum covered sites on the current customer subscription.'),
            },
            {
              label: t('admin.vector_documents_limit', {}, 'Knowledge articles'),
              value: formatInteger(effectiveVectorDocuments),
              detail: t('admin.vector_documents_limit_detail', {}, 'Account-level article capacity for Site Knowledge indexing.'),
            },
            {
              label: t('admin.sales_price_cny', {}, 'Sales price'),
              value: formatCurrency(numericValue(detail.sales_offer?.amount), ADMIN_CURRENCY),
              detail: t('admin.sales_price_cny_detail', {}, 'Customer-facing 30-day price used for new Alipay orders.'),
            },
            {
              label: t('admin.period_cost_budget', {}, 'Package fee'),
              value: formatBudgetCurrency(latestBudgets.max_cost_per_period),
              detail: t('admin.period_cost_budget_detail', {}, 'Saved package fee for this billing period.'),
            },
            {
              label: t('admin.concurrency', {}, 'Concurrency'),
              value: formatInteger(numericValue(latestConcurrency.max_active_runs ?? templateConcurrency.max_active_runs)),
              detail: t('admin.plan_template_concurrency_detail', {}, 'Active run ceiling stored for this package.'),
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
          </div>
        </BackofficeStackCard>
      </BackofficeSectionPanel>

      <details className="rounded-2xl border border-dashed border-slate-200 px-4 py-4 dark:border-slate-800">
        <summary className="cursor-pointer list-none text-sm font-medium text-slate-700 dark:text-slate-300">
          {t('admin.package_advanced_info', {}, 'Advanced information')}
        </summary>
        <div className="mt-4 space-y-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.package_advanced_info_desc',
                {},
                'Use this only for diagnostics, audit, or release history review.'
              )}
            </p>
            <div className="inline-flex w-full rounded-xl border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-950 md:w-auto">
              <button
                type="button"
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition md:flex-none ${
                  advancedInfoTab === 'diagnostics'
                    ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-950'
                    : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900'
                }`}
                aria-pressed={advancedInfoTab === 'diagnostics'}
                onClick={() => setAdvancedInfoTab('diagnostics')}
              >
                {t('admin.package_advanced_info_diagnostics', {}, 'Diagnostics')}
              </button>
              <button
                type="button"
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition md:flex-none ${
                  advancedInfoTab === 'history'
                    ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-950'
                    : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900'
                }`}
                aria-pressed={advancedInfoTab === 'history'}
                onClick={() => setAdvancedInfoTab('history')}
              >
                {t('admin.package_advanced_info_history', {}, 'Release history')}
              </button>
            </div>
          </div>

          {advancedInfoTab === 'diagnostics' ? (
            <BackofficeSectionPanel className="space-y-4">
              {primaryPackageFitCue ? (
                <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">
                    {primaryPackageFitCue.title}
                  </p>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {primaryPackageFitCue.detail}
                  </p>
                </BackofficeStackCard>
              ) : null}
              <BackofficeMetricStrip
                items={[
                  {
                    label: t('admin.included_points', {}, 'Package points'),
                    value: formatInteger(Number(tierSummary?.monthly_included_points || 0)),
                    detail: t('admin.included_points_detail', {}, 'Current-period package points shared by all sites on this account.'),
                  },
                  {
                    label: t('admin.site_limit', {}, 'Site limit'),
                    value: formatInteger(Number(tierSummary?.site_limit || 0)),
                    detail: t('admin.site_limit_detail', {}, 'Maximum covered sites on the current customer subscription.'),
                  },
                  {
                    label: t('admin.vector_documents_limit', {}, 'Knowledge articles'),
                    value: formatInteger(Number(tierSummary?.max_vector_documents || 0)),
                    detail: t('admin.vector_documents_limit_detail', {}, 'Account-level article capacity for Site Knowledge indexing.'),
                  },
                  {
                    label: t('common.cost'),
                    value: formatBudgetCurrency(templateBudgets.max_cost_per_period),
                    detail: t('admin.plan_template_cost_detail', {}, 'Cost ceiling stored for this package period.'),
                  },
                  {
                    label: t('admin.concurrency', {}, 'Concurrency'),
                    value: formatInteger(Number(templateConcurrency.max_active_runs || 0)),
                    detail: t('admin.plan_template_concurrency_detail', {}, 'Active run ceiling stored for this package.'),
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
                    String(policyBaseline.downgrade_policy || t('admin.policy_baseline_missing', {}, 'No downgrade note was attached to this package.'))}
                </p>
              </BackofficeStackCard>
            </BackofficeSectionPanel>
          ) : (
            <BackofficeSectionPanel className="space-y-4">
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
            </BackofficeSectionPanel>
          )}
        </div>
      </details>

      {isEditorOpen ? (
        <div className="fixed inset-0 z-50">
          <button
            type="button"
            className="absolute inset-0 bg-slate-950/45 backdrop-blur-sm"
            onClick={closeEditor}
            aria-label={t('common.close')}
          />
          <aside
            ref={editorDialogRef}
            className="absolute right-0 top-0 flex h-full w-full max-w-3xl flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950"
            role="dialog"
            aria-modal="true"
            aria-labelledby="package-editor-title"
            tabIndex={-1}
          >
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-4 py-4 dark:border-slate-800 sm:px-6">
              <div className="min-w-0">
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  {t('admin.quick_actions')}
                </p>
                <h2 id="package-editor-title" className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                  {t('admin.publish_coverage_package_release_title', {}, 'Edit current package values')}
                </h2>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t(
                    'admin.publish_coverage_package_release_desc',
                    {},
                    'Change the common limits here. Existing subscriptions on this package read the latest saved values.'
                  )}
                </p>
              </div>
              <button
                type="button"
                onClick={closeEditor}
                disabled={isSaving}
                className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-slate-900 dark:hover:text-slate-200"
                aria-label={t('common.close')}
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <form className="flex min-h-0 flex-1 flex-col" onSubmit={handlePublishVersion}>
              <div className="flex-1 space-y-5 overflow-y-auto px-4 py-5 sm:px-6">
                {error ? (
                  <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
                    {error}
                  </div>
                ) : null}
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
                          'Edit the current package values here. Saving publishes the latest values for subscriptions already using this package.'
                        )}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-3">
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => applyStructuredPatch(latestFieldPatch)}
                      >
                        {t('admin.reset_to_latest_version', {}, 'Restore saved values')}
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => applyStructuredPatch(baselineFieldPatch)}
                      >
                        {templateActionLabel}
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
                      'Customer sales price uses CNY; the internal provider-cost budget uses USD.'
                    )}
                  </p>
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <label className="text-sm">
                      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.sales_price_cny', {}, 'Sales price (CNY)')}</span>
                      <input value={form.sales_price_cny} onChange={(e) => setForm((c) => ({ ...c, sales_price_cny: e.target.value }))} className="input w-full" type="number" min="0" step="0.01" />
                      <span className="mt-2 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                        {t('admin.sales_price_cny_detail', {}, 'Customer-facing 30-day price used for new Alipay orders.')}
                      </span>
                    </label>
                    <label className="text-sm">
                      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.model_cost_budget_usd', {}, 'Model cost budget (USD / period)')}</span>
                      <input value={form.max_cost_per_period} onChange={(e) => setForm((c) => ({ ...c, max_cost_per_period: e.target.value }))} className="input w-full" type="number" min="0" step="0.01" />
                      <span className="mt-2 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                        {t('admin.model_cost_budget_usd_detail', {}, 'Internal provider-cost monitoring threshold. It does not change the customer payment amount.')}
                      </span>
                    </label>
                    <label className="text-sm">
                      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.included_points', {}, 'Package points')}</span>
                      <input value={form.monthly_included_points} onChange={(e) => setForm((c) => ({ ...c, monthly_included_points: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                    </label>
                    <label className="text-sm">
                      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.site_limit', {}, 'Site limit')}</span>
                      <input value={form.site_limit} onChange={(e) => setForm((c) => ({ ...c, site_limit: e.target.value }))} className="input w-full" type="number" min="1" step="1" />
                    </label>
                    <label className="text-sm">
                      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.vector_documents_limit', {}, 'Knowledge articles')}</span>
                      <input value={form.max_vector_documents} onChange={(e) => setForm((c) => ({ ...c, max_vector_documents: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                    </label>
                    <label className="text-sm">
                      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.batch_ceiling', {}, 'Batch ceiling')}</span>
                      <input value={form.max_batch_items} onChange={(e) => setForm((c) => ({ ...c, max_batch_items: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                    </label>
                    <label className="text-sm">
                      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.concurrency', {}, 'Concurrency')}</span>
                      <input value={form.max_active_runs} onChange={(e) => setForm((c) => ({ ...c, max_active_runs: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                    </label>
                    <label className="text-sm">
                      <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('admin.grace_period_label', {}, 'Grace period')}</span>
                      <input value={form.grace_period_days} onChange={(e) => setForm((c) => ({ ...c, grace_period_days: e.target.value }))} className="input w-full" type="number" min="0" step="1" />
                    </label>
                  </div>
                </BackofficeStackCard>

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
                  <div className="mt-4 grid gap-4">
                    <JsonField label={t('admin.entitlements', {}, 'Entitlements')} value={form.entitlements_json} onChange={(value) => setForm((c) => ({ ...c, entitlements_json: value }))} minHeightClassName="min-h-32" />
                    <JsonField label={t('admin.metadata_override', {}, 'Metadata override')} value={form.metadata_override_json} onChange={(value) => setForm((c) => ({ ...c, metadata_override_json: value }))} minHeightClassName="min-h-28" />
                    <JsonField label={t('admin.budgets_override', {}, 'Budgets override')} value={form.budgets_override_json} onChange={(value) => setForm((c) => ({ ...c, budgets_override_json: value }))} minHeightClassName="min-h-28" />
                    <JsonField label={t('admin.concurrency_override', {}, 'Concurrency override')} value={form.concurrency_override_json} onChange={(value) => setForm((c) => ({ ...c, concurrency_override_json: value }))} minHeightClassName="min-h-28" />
                    <JsonField label={t('admin.policy_override', {}, 'Policy override')} value={form.policy_override_json} onChange={(value) => setForm((c) => ({ ...c, policy_override_json: value }))} minHeightClassName="min-h-28" />
                  </div>
                </details>
              </div>

              <div className="flex flex-col-reverse gap-2 border-t border-slate-200 px-4 py-4 dark:border-slate-800 sm:flex-row sm:justify-end sm:px-6">
                <button type="button" className="btn btn-secondary" onClick={closeEditor} disabled={isSaving}>
                  {t('common.cancel', {}, 'Cancel')}
                </button>
                <button type="submit" className="btn btn-primary" disabled={isSaving}>
                  {isSaving ? t('common.saving', {}, 'Saving...') : t('admin.save_package_changes', {}, 'Save package changes')}
                </button>
              </div>
            </form>
          </aside>
        </div>
      ) : null}
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

export default function AdminPlanDetailPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PlanDetailContent />
    </Suspense>
  );
}
