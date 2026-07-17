'use client';

import React, { useState, useEffect, Suspense } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  BackofficeDiagnosticNotice,
  BackofficeDisclosure,
  BackofficeLayer,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { AdminAuditSummaryPanel } from '@/components/admin/AdminAuditSummaryPanel';
import { AdminRouteSkeleton } from '@/components/admin/AdminRouteSkeleton';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useToast } from '@/components/ui/Toast';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { resolveAdminPackageLabel } from '@/lib/admin-plan-copy';
import { localizeAdminCommercialCopy } from '@/lib/admin-commercial-copy';
import { translateStatusLabel } from '@/lib/status-display';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatAdminCurrency } from '@/lib/currency';
import {
  cn,
  formatDate,
  formatNumber as formatInteger,
} from '@/lib/utils';

interface SiteDetail {
  site_id: string;
  account_id: string;
  site_name: string;
  status: string;
  created_at: string;
  key_count: number;
  subscription?: {
    subscription_id: string;
    status: string;
    plan_id: string;
    plan_version_id?: string;
    current_period_start: string;
    current_period_end: string;
  };
  usage_summary?: {
    requests_total: number;
    tokens_total: number;
    cost_estimate: number;
  };
  billing_summary?: {
    total_snapshots: number;
    latest_snapshot?: {
      snapshot_id: string;
      status: string;
      cost: number;
    };
  };
  runtime_summary?: {
    total_runs: number;
    failed_runs: number;
    last_run_at?: string;
  };
  commercial_policy?: Record<string, unknown>;
  budget_state?: Record<
    string,
    {
      current_total?: number;
      limit?: number;
      grace_requests?: number;
      used_grace_requests?: number;
      remaining_grace_requests?: number;
      downgrade_policy?: Record<string, unknown>;
      over_limit?: boolean;
    }
  >;
  subscription_grace?: {
    active?: boolean;
    subscription_status?: string;
    grace_period_days?: number;
    grace_until_at?: string;
    runtime_policy_overrides?: Record<string, unknown>;
  };
  billing_reconciliation?: {
    in_sync?: boolean;
    delta_cost?: number;
  };
  related_surfaces?: {
    account_href?: string;
    subscription_href?: string;
    audit_href?: string;
  };
  commercial_follow_up?: {
    entitlement_summary?: string;
    budget_headroom_summary?: string;
    runtime_gating_summary?: string;
    next_operator_follow_up?: string;
  };
  runtime_operator_explanations?: Array<{
    state?: string;
    explain_text?: string;
    next_step_kind?: string;
    next_step_ref?: string;
  }>;
}

interface SiteDetailApiPayload {
  site?: Record<string, unknown>;
  account?: Record<string, unknown>;
  site_keys?: Array<{ status?: string }>;
  subscription?: Record<string, unknown> | null;
  commercial_policy?: {
    budget_state?: SiteDetail['budget_state'];
    subscription_grace?: SiteDetail['subscription_grace'];
    policy?: Record<string, unknown>;
  };
  billing_reconciliation?: {
    reconciliation?: {
      in_sync?: boolean;
      deltas?: { cost?: number };
    };
    snapshot?: Record<string, unknown> | null;
  };
  usage_meter?: {
    totals?: {
      requests?: number;
      tokens?: number;
      cost_usd?: number;
    };
  };
  billing_snapshots?: { items?: Array<Record<string, unknown>> };
  runtime_diagnostics?: {
    queue?: { queued_runs?: number; latest_run_at?: string };
    callback?: { failed?: number };
  };
  related_surfaces?: SiteDetail['related_surfaces'];
  commercial_follow_up?: SiteDetail['commercial_follow_up'];
  runtime_operator_explanations?: SiteDetail['runtime_operator_explanations'];
}

const siteDetailClient = createApiClient({ idempotencyPrefix: 'admin_site_detail' });

function siteRuntimeExplanationText(
  value: string,
  t: (key: string, params?: Record<string, string>, fallback?: string) => string
): string {
  const known: Record<string, [string, string]> = {
    'Current runtime summary does not surface an immediate operator-critical blocker.': ['admin.site_detail.runtime_explanation_ok', 'Current runtime summary does not surface an immediate operator-critical blocker.'],
    'Queued or backlogged runs are accumulating.': ['admin.site_detail.runtime_explanation_queued_short', 'Queued or backlogged runs are accumulating.'],
  };
  const copy = known[value];
  if (copy) return t(copy[0], {}, copy[1]);
  if (value.startsWith('Callback delivery is already degraded.')) {
    return t('admin.site_detail.runtime_explanation_callback', {}, 'Callback delivery is degraded. Start from site runtime posture before widening provider or customer support work.');
  }
  if (value.startsWith('Queued or backlogged runs are accumulating.')) {
    return t('admin.site_detail.runtime_explanation_queued', {}, 'Queued or backlogged runs are accumulating. Confirm the affected site before widening provider or model checks.');
  }
  if (value.startsWith('Recent guard events suggest')) {
    return t('admin.site_detail.runtime_explanation_guard', {}, 'Recent guard events indicate policy or throttling pressure. Check commercial entitlement and support visibility before treating this as a pure runtime failure.');
  }
  return value;
}

function SiteDetailContent() {
  const params = useParams();
  const { t } = useLocale();
  const toast = useToast();
  const { siteId } = params as { siteId: string };
  
  const [site, setSite] = useState<SiteDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [siteActionError, setSiteActionError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [isActivatingSite, setIsActivatingSite] = useState(false);

  const handleActivateSite = async () => {
    if (!site) {
      return;
    }

    setIsActivatingSite(true);
    setSiteActionError(null);

    try {
      await siteDetailClient.request<Record<string, unknown>>(`/api/admin/sites/${encodeURIComponent(site.site_id)}/activate`, {
        method: 'POST',
        body: {},
      });
      setSite((current) => (current ? { ...current, status: 'active' } : current));
      toast.success(
        t(
          'admin.site_detail.activate_success',
          undefined,
          'Site is now active. Signed addon probes and hosted runtime requests can proceed.'
        ),
        t('admin.site_detail.activate_success_title', undefined, 'Site activated')
      );
    } catch (err) {
      setSiteActionError(resolveUiErrorMessage(
        err,
        t('admin.site_detail.activate_failed', undefined, 'Failed to activate the site.')
      ));
    } finally {
      setIsActivatingSite(false);
    }
  };

  useEffect(() => {
    const loadSite = async () => {
      setIsLoading(true);
      setError(null);
      
      try {
        const payload = (await siteDetailClient.request<SiteDetailApiPayload>(
          `/api/admin/sites/${siteId}`
        )).data;
        const rawSite = payload.site || {};
        const rawAccount = payload.account || {};
        const siteKeys = Array.isArray(payload.site_keys) ? payload.site_keys : [];
        const rawSubscription = payload.subscription || null;
        const commercialPolicy = payload.commercial_policy || {};
        const policyBudgetState = commercialPolicy.budget_state || {};
        const subscriptionGrace = commercialPolicy.subscription_grace || {};
        const billingReconciliation = payload.billing_reconciliation || {};
        const usageTotals = payload.usage_meter?.totals || {};
        const billingItems = Array.isArray(payload.billing_snapshots?.items)
          ? payload.billing_snapshots.items
          : [];
        const latestSnapshot = billingItems[0] || payload.billing_reconciliation?.snapshot || null;
        const normalizedSite: SiteDetail = {
          site_id: String(rawSite.site_id || siteId),
          account_id: String(rawSite.account_id || rawAccount.account_id || ''),
          site_name: String(rawSite.name || rawSite.site_id || siteId),
          status: String(rawSite.status || 'unknown'),
          created_at: String(rawSite.created_at || ''),
          key_count: siteKeys.length,
          subscription: rawSubscription
            ? {
                subscription_id: String(rawSubscription.subscription_id || ''),
                status: String(rawSubscription.status || 'unknown'),
                plan_id: String(rawSubscription.plan_id || ''),
                plan_version_id: String(rawSubscription.plan_version_id || ''),
                current_period_start: String(rawSubscription.current_period_start_at || ''),
                current_period_end: String(rawSubscription.current_period_end_at || ''),
              }
            : undefined,
          usage_summary: {
            requests_total: Number(usageTotals.requests || 0),
            tokens_total: Number(usageTotals.tokens || 0),
            cost_estimate: Number(usageTotals.cost_usd || 0),
          },
          billing_summary: {
            total_snapshots: billingItems.length,
            latest_snapshot: latestSnapshot
              ? {
                  snapshot_id: String(latestSnapshot.snapshot_id || ''),
                  status: String(latestSnapshot.status || 'unknown'),
                  cost: Number(latestSnapshot.total_cost_usd || latestSnapshot.cost_usd || 0),
                }
              : undefined,
          },
          runtime_summary: {
            total_runs: Number(payload.runtime_diagnostics?.queue?.queued_runs || 0),
            failed_runs: Number(payload.runtime_diagnostics?.callback?.failed || 0),
            last_run_at: String(payload.runtime_diagnostics?.queue?.latest_run_at || ''),
          },
          commercial_policy:
            commercialPolicy && typeof commercialPolicy === 'object'
              ? commercialPolicy.policy || {}
              : {},
          budget_state:
            policyBudgetState && typeof policyBudgetState === 'object' ? policyBudgetState : {},
          subscription_grace:
            subscriptionGrace && typeof subscriptionGrace === 'object' ? subscriptionGrace : {},
          billing_reconciliation: {
            in_sync: Boolean(billingReconciliation?.reconciliation?.in_sync),
            delta_cost: Number(billingReconciliation?.reconciliation?.deltas?.cost || 0),
          },
          related_surfaces:
            payload.related_surfaces && typeof payload.related_surfaces === 'object'
              ? payload.related_surfaces
              : {},
          commercial_follow_up:
            payload.commercial_follow_up && typeof payload.commercial_follow_up === 'object'
              ? payload.commercial_follow_up
              : {},
          runtime_operator_explanations: Array.isArray(payload.runtime_operator_explanations)
            ? payload.runtime_operator_explanations
            : [],
        };
        setSite(normalizedSite);
        await Promise.resolve();
      } catch (err) {
        setError(resolveUiErrorMessage(err, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    loadSite();
  }, [reloadKey, siteId, t]);

  if (isLoading) {
    return <AdminRouteSkeleton />;
  }

  if (error) {
    return (
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow={t('admin.site_health')}
          title={t('admin.site_detail.load_error_title', undefined, 'Site detail is temporarily unavailable')}
          description={t('admin.site_detail.load_error_desc', undefined, 'Retry this bounded site read without leaving the current operator route.')}
        >
          <BackofficeDiagnosticNotice
            message={error}
            retryLabel={t('common.retry')}
            onRetry={() => setReloadKey((value) => value + 1)}
          />
        </BackofficePrimaryPanel>
      </BackofficePageStack>
    );
  }

  if (!site) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <h2 className="text-2xl font-bold mb-4">{t('admin.site_not_found')}</h2>
          <Link href="/admin/accounts" className="text-blue-600 hover:underline">
            ← {t('common.accounts', {}, 'Accounts')}
          </Link>
        </div>
      </div>
    );
  }

  const subscriptionStatus = site.subscription?.status || 'inactive';
  const graceActive = Boolean(site.subscription_grace?.active);
  const runBudget = site.budget_state?.runs || {};
  const tokenBudget = site.budget_state?.tokens || {};
  const costBudget = site.budget_state?.cost || {};
  const overBudget = [runBudget, tokenBudget, costBudget].some((item) => Boolean(item.over_limit));
  const billingMismatch = Math.abs(Number(site.billing_reconciliation?.delta_cost || 0)) > 0;
  const failedRuns = site.runtime_summary?.failed_runs || 0;
  const totalRuns = site.runtime_summary?.total_runs || 0;
  const hasRuntimeRisk = failedRuns > 0;
  const hasKeyCoverageGap = site.key_count === 0;
  const hasCommercialRisk = Boolean(
    !site.subscription ||
      !['active', 'trialing'].includes(site.subscription.status) ||
      overBudget ||
      graceActive ||
      billingMismatch
  );
  const isProvisioning = site.status === 'provisioning';
  const postureTone =
    site.status === 'suspended' || hasCommercialRisk || hasRuntimeRisk
      ? 'error'
      : isProvisioning || hasKeyCoverageGap
        ? 'warning'
        : 'ok';
  const postureTitle =
    site.status === 'suspended'
      ? t('admin.site_detail.suspended_title', undefined, 'Site access is suspended')
      : hasCommercialRisk
        ? t('admin.site_detail.commercial_risk_title', undefined, 'Commercial coverage needs follow-up')
        : hasRuntimeRisk
          ? t('admin.site_detail.runtime_risk_title', undefined, 'Runtime failures need follow-up')
          : isProvisioning
            ? t('admin.site_detail.provisioning_title', undefined, 'Site is provisioned but not yet active')
            : hasKeyCoverageGap
              ? t('admin.site_detail.key_gap_title', undefined, 'Site is missing active key coverage')
              : t('admin.site_detail.healthy_title', undefined, 'Site posture is stable');
  const postureDescription =
    site.status === 'suspended'
      ? t('admin.site_detail.suspended_desc', undefined, 'Commercial or support review should happen before traffic resumes for this site.')
      : hasCommercialRisk
        ? t('admin.site_detail.commercial_risk_desc', undefined, 'Commercial coverage is now the leading blocker. Confirm subscription state, budget pressure, grace, and reconciliation before treating runtime noise as primary.')
        : hasRuntimeRisk
          ? t('admin.site_detail.runtime_risk_desc', undefined, 'The site is receiving runtime traffic, but recent failures mean operator attention should start with execution diagnostics.')
          : isProvisioning
            ? t('admin.site_detail.provisioning_desc', undefined, 'The site record exists, but hosted runtime remains blocked until activation completes.')
            : hasKeyCoverageGap
              ? t('admin.site_detail.key_gap_desc', undefined, 'Traffic can only proceed after at least one active site key is issued or restored.')
              : t('admin.site_detail.healthy_desc', undefined, 'Commercial coverage, runtime signal, and key inventory are all readable from this surface.');
  const nextStep = site.status === 'suspended'
    ? {
        href: `/admin/accounts/${site.account_id}`,
        label: t('admin.site_detail.open_account_action', undefined, 'Open account follow-up'),
        description: t('admin.site_detail.open_account_desc', undefined, 'Inspect the parent account before changing traffic or support posture for this site.'),
      }
      : hasCommercialRisk && site.subscription?.subscription_id
        ? {
          href: `/admin/subscriptions`,
          label: t('admin.open_coverage_action', undefined, 'Open coverage'),
          description: t('admin.site_detail.open_coverage_desc', undefined, 'Commercial status is the current blocker; keep the next step on the customer coverage surface before opening deeper subscription detail.'),
        }
      : hasRuntimeRisk
        ? {
            href: `/admin/sites/${site.site_id}`,
            label: t('admin.site_detail.inspect_site_runtime_action', undefined, 'Inspect site runtime'),
            description: t('admin.site_detail.inspect_site_runtime_desc', undefined, 'Keep the next step on the site surface first so runtime signals stay tied to the affected asset.'),
          }
        : hasKeyCoverageGap
          ? {
              href: `/admin/accounts/${site.account_id}`,
              label: t('admin.site_detail.review_account_access_action', undefined, 'Review account access'),
              description: t('admin.site_detail.review_account_access_desc', undefined, 'Use the account surface to confirm support posture and site access before rotating keys.'),
            }
          : {
              href: `/admin/accounts/${site.account_id}`,
              label: t('admin.site_detail.review_parent_account_action', undefined, 'Review parent account'),
              description: t('admin.site_detail.review_parent_account_desc', undefined, 'The site is stable; move up one level only if you need broader account coverage or support context.'),
            };
  const watchItems = [
    {
      label: t('admin.subscription_posture'),
      value: site.subscription
        ? translateStatusLabel(subscriptionStatus, t)
        : t('common.not_found'),
      detail: site.subscription
        ? resolveAdminPackageLabel(t, {
            planId: site.subscription.plan_id,
            fallback: site.subscription.plan_id || t('common.plan'),
          })
        : t('admin.site_detail.subscription_missing_desc', undefined, 'No active customer subscription is covering this site yet.'),
      toneClassName: hasCommercialRisk ? 'text-red-600 dark:text-red-400' : undefined,
    },
    {
      label: t('admin.site_detail.coverage_state_label', undefined, 'Coverage state'),
      value: hasCommercialRisk
        ? t('admin.site_detail.coverage_state_commercial', undefined, 'Commercial blocker')
        : hasRuntimeRisk
          ? t('admin.site_detail.coverage_state_runtime', undefined, 'Runtime blocker')
          : hasKeyCoverageGap
            ? t('admin.site_detail.coverage_state_keys', undefined, 'Key coverage blocker')
            : t('admin.site_detail.coverage_state_ok', undefined, 'Coverage aligned'),
      detail: hasCommercialRisk
        ? t('admin.site_detail.coverage_state_commercial_desc', undefined, 'Subscription, budget, grace, or billing reconciliation is already leading the next action.')
        : hasRuntimeRisk
          ? t('admin.site_detail.coverage_state_runtime_desc', undefined, 'Commercial coverage is readable; runtime diagnostics should lead the next action.')
          : hasKeyCoverageGap
            ? t('admin.site_detail.coverage_state_keys_desc', undefined, 'Commercial and runtime coverage are readable, but no active key is available.')
            : t('admin.site_detail.coverage_state_ok_desc', undefined, 'Commercial, runtime, and key coverage are all readable from this site surface.'),
      toneClassName: hasCommercialRisk
        ? 'text-red-600 dark:text-red-400'
        : hasRuntimeRisk || hasKeyCoverageGap
          ? 'text-amber-700 dark:text-amber-300'
          : undefined,
    },
    {
      label: t('common.cost'),
      value: formatAdminCurrency(Number(costBudget.current_total || site.usage_summary?.cost_estimate || 0)),
      detail: billingMismatch
        ? t('admin.site_detail.billing_delta_desc', undefined, 'Billing reconciliation is not fully aligned yet, so treat commercial evidence as active follow-up.')
        : t('admin.site_detail.billing_aligned_desc', undefined, 'Billing evidence is aligned closely enough for normal operator follow-up.'),
      toneClassName: billingMismatch ? 'text-amber-700 dark:text-amber-300' : undefined,
    },
  ];
  const entitlementSummary = localizeAdminCommercialCopy(site.commercial_follow_up?.entitlement_summary, t);
  const budgetHeadroomSummary = localizeAdminCommercialCopy(site.commercial_follow_up?.budget_headroom_summary, t);
  const runtimeGatingSummary = localizeAdminCommercialCopy(site.commercial_follow_up?.runtime_gating_summary, t);
  const siteNextOperatorFollowUp = localizeAdminCommercialCopy(
    site.commercial_follow_up?.next_operator_follow_up,
    t
  );
  const formatUsageAgainstLimit = (
    current: number,
    limit: number,
    formatter: (value: number) => string
  ) => limit > 0
    ? `${formatter(current)} / ${formatter(limit)}`
    : t(
        'admin.site_detail.usage_without_limit',
        { used: formatter(current) },
        `Used ${formatter(current)} · limit not configured`
      );

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.site_health')}
        title={site.site_name || site.site_id}
        description={postureDescription}
        actions={site.status === 'provisioning' ? (
              <button
                type="button"
                onClick={handleActivateSite}
                className={cn('btn btn-primary', isActivatingSite && 'pointer-events-none opacity-50')}
                disabled={isActivatingSite}
              >
                {isActivatingSite
                  ? t('common.saving')
                  : t('admin.site_detail.activate_action', undefined, 'Activate site')}
              </button>
            ) : undefined}
        summary={(
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.05fr)_1.45fr]">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.site_detail.summary_title', undefined, 'Site operator summary')}
              </p>
              <BackofficeIdentifier value={site.site_id} className="mt-2 block text-xs text-gray-500 dark:text-gray-400" />
              <div className="mt-3 flex flex-wrap gap-2">
                <BackofficeStatusBadge status={postureTone} label={translateStatusLabel(postureTone, t)} />
                <BackofficeStatusBadge status={site.status} label={translateStatusLabel(site.status, t)} />
                {site.subscription ? (
                  <BackofficeStatusBadge
                    status={site.subscription.status}
                    label={translateStatusLabel(site.subscription.status, t)}
                  />
                ) : null}
              </div>
              {site.status === 'provisioning' ? (
                <p className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
                  {t(
                    'admin.site_detail.provisioning_warning',
                    undefined,
                    'This site record exists, but hosted runtime is still blocked until the site is activated.'
                  )}
                </p>
              ) : null}
              {siteActionError ? (
                <p className="mt-3 rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
                  {siteActionError}
                </p>
              ) : null}
            </div>
            <BackofficeMetricStrip
              items={[
                {
                  label: t('admin.account_detail.site_admin_workspace_metric', undefined, 'Site admin workspace'),
                  value: t('common.enabled', undefined, 'Enabled'),
                },
                { label: t('common.keys'), value: formatInteger(site.key_count) },
                {
                  label: t('admin.failed_runs'),
                  value: formatInteger(failedRuns),
                  toneClassName: hasRuntimeRisk ? 'text-red-600 dark:text-red-400' : undefined,
                },
                {
                  label: t('admin.period_end'),
                  value: site.subscription?.current_period_end
                    ? formatDate(site.subscription.current_period_end)
                    : t('common.not_found'),
                },
              ]}
            />
          </div>
        )}
      >
        <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.site_detail.primary_title', undefined, 'Current follow-up')}
            </p>
            <h3 className="mt-3 text-lg font-semibold text-gray-950 dark:text-white">{postureTitle}</h3>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{nextStep.description}</p>
            <div className="mt-4 flex flex-wrap gap-3">
              <Link href={nextStep.href} className="btn btn-primary">
                {nextStep.label}
              </Link>
            </div>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.site_detail.followup_focus_title', undefined, 'Follow-up focus')}
            </p>
            <div className="mt-4 space-y-4">
              {watchItems.map((item) => (
                <div key={item.label} className="flex items-start justify-between gap-4 border-b border-gray-200 pb-4 last:border-b-0 last:pb-0 dark:border-gray-800">
                  <div className="min-w-0">
                    <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">{item.label}</p>
                    <p className={cn('mt-1 text-sm font-semibold text-gray-950 dark:text-white', item.toneClassName)}>
                      {item.value}
                    </p>
                  </div>
                  <p className="max-w-sm text-right text-sm text-gray-600 dark:text-gray-400">{item.detail}</p>
                </div>
              ))}
            </div>
          </BackofficeStackCard>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.related_surfaces', {}, 'Related surfaces')}
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              {site.related_surfaces?.account_href ? (
                <Link href={site.related_surfaces.account_href} className="btn btn-secondary">
                  {t('common.account', {}, 'Customer')}
                </Link>
              ) : null}
              {site.related_surfaces?.subscription_href ? (
                <Link href={site.related_surfaces.subscription_href} className="text-sm font-medium text-slate-600 underline decoration-dotted underline-offset-4 transition hover:text-slate-950 dark:text-slate-300 dark:hover:text-white">
                  {t('admin.inspect_subscription_detail', {}, 'Inspect subscription detail')}
                </Link>
              ) : null}
            </div>
            <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
              {siteNextOperatorFollowUp ||
                t(
                  'admin.site_detail.related_surfaces_desc',
                  undefined,
                  'Use related surfaces to move between customer, coverage, and audit follow-up without restarting from overview.'
                )}
            </p>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.runtime_explainability', {}, 'Runtime explainability')}
            </p>
            <div className="mt-3 space-y-3">
              {(site.runtime_operator_explanations || []).slice(0, 3).map((item, index) => (
                <div key={`${item.state || 'runtime'}-${index}`} className="rounded-xl border border-slate-200/70 px-3 py-3 dark:border-slate-800">
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">
                    {translateStatusLabel(item.state || 'ok', t)}
                  </p>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.explain_text ? siteRuntimeExplanationText(item.explain_text, t) : t('common.not_available', {}, 'N/A')}</p>
                </div>
              ))}
            </div>
          </BackofficeStackCard>
        </div>

        <details className="rounded-2xl border border-dashed border-slate-200 px-4 py-4 dark:border-slate-800">
          <summary className="cursor-pointer list-none text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('admin.site_detail.audit_reveal', {}, 'Inspect audit follow-up')}
          </summary>
          <div className="mt-4">
            <AdminAuditSummaryPanel
              title={t('admin.audit_summary.site_title', {}, 'Recent audit summary for this site')}
              siteId={site.site_id}
              accountId={site.account_id}
              trailHref={site.related_surfaces?.audit_href}
            />
          </div>
        </details>
      </BackofficePrimaryPanel>

      <BackofficeDisclosure
        summary={t('admin.site_detail.advanced_operational_evidence', undefined, 'Advanced site operational evidence')}
        contentClassName="space-y-6"
      >
      <BackofficeLayer
        eyebrow={t('admin.site_detail.operational_detail_eyebrow', undefined, 'Operational detail')}
        title={t('admin.site_detail.operational_detail_title', undefined, 'Inspect linked records before deeper support actions')}
        description={t('admin.site_detail.operational_detail_desc', undefined, 'Keep account subscription coverage, runtime signal, usage, and billing in separate operator sections so the next action stays explicit.')}
      />
      <div className="grid gap-6 xl:grid-cols-2">
        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.site_detail.commercial_boundary_title', undefined, 'Coverage state')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.site_detail.coverage_panel_title', undefined, 'Commercial coverage')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t(
                'admin.site_detail.commercial_boundary_desc',
                undefined,
                'Use the linked account subscription truth to decide whether this site is blocked by coverage, budget pressure, grace, or billing reconciliation before taking runtime action.'
              )}
            </p>
          </div>
          {site.subscription ? (
            <>
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-3 xl:grid-cols-3"
                items={[
                  {
                    label: t('common.status'),
                    value: translateStatusLabel(site.subscription.status, t),
                    toneClassName: site.subscription.status === 'active' ? 'text-emerald-600 dark:text-emerald-300' : undefined,
                  },
                  {
                    label: t('common.plan'),
                    value: resolveAdminPackageLabel(t, {
                      planId: site.subscription.plan_id,
                      fallback: site.subscription.plan_id,
                    }),
                  },
                  {
                    label: t('admin.site_detail.coverage_reconciliation', undefined, 'Reconciliation'),
                    value: site.billing_reconciliation?.in_sync
                      ? translateStatusLabel('ok', t)
                      : translateStatusLabel('warning', t),
                    detail: site.billing_reconciliation?.delta_cost
                      ? formatAdminCurrency(Math.abs(Number(site.billing_reconciliation.delta_cost || 0)))
                      : undefined,
                  },
                ]}
              />
              <BackofficeStackCard>
                <div className="grid gap-3 md:grid-cols-3">
                  <CoverageMetric
                    label={t('billing.runs', {}, 'Runs')}
                    value={formatUsageAgainstLimit(
                      Number(runBudget.current_total || 0),
                      Number(runBudget.limit || 0),
                      formatInteger
                    )}
                  />
                  <CoverageMetric
                    label={t('common.tokens')}
                    value={formatUsageAgainstLimit(
                      Number(tokenBudget.current_total || 0),
                      Number(tokenBudget.limit || 0),
                      formatInteger
                    )}
                  />
                  <CoverageMetric
                    label={t('common.cost')}
                    value={formatUsageAgainstLimit(
                      Number(costBudget.current_total || 0),
                      Number(costBudget.limit || 0),
                      formatAdminCurrency
                    )}
                  />
                </div>
                <div className="mt-4 space-y-2 text-sm text-gray-600 dark:text-gray-300">
                  <p>
                    {graceActive
                      ? t('admin.site_detail.grace_active_desc', undefined, 'Grace is active for the current account subscription and should be treated as part of current site coverage.')
                      : t('admin.site_detail.grace_inactive_desc', undefined, 'Grace is not active for the current account subscription right now.')}
                  </p>
                  {site.subscription_grace?.grace_until_at ? (
                    <p>
                      {t('portal.usage.grace_until', {}, 'Grace until')}: {formatDate(site.subscription_grace.grace_until_at)}
                    </p>
                  ) : null}
                </div>
              </BackofficeStackCard>
              <BackofficeStackCard>
                <p className="text-sm font-medium text-gray-950 dark:text-white">
                  {t(
                    'admin.site_detail.subscription_shortcut_title',
                    undefined,
                    'Commercial follow-up stays on the current account subscription record.'
                  )}
                </p>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  {t(
                    'admin.site_detail.subscription_shortcut_desc',
                    undefined,
                    'Use the current follow-up action above when this site is commercially blocked. Keep this section focused on explaining why the account subscription boundary owns the next move.'
                  )}
                </p>
                <div className="mt-4 space-y-2 text-sm text-gray-600 dark:text-gray-300">
                  <p>{entitlementSummary}</p>
                  <p>{budgetHeadroomSummary}</p>
                  <p>{runtimeGatingSummary}</p>
                </div>
              </BackofficeStackCard>
            </>
          ) : (
            <BackofficeStackCard>{t('site_details.no_subscription')}</BackofficeStackCard>
          )}
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.runtime_signal')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.site_detail.runtime_inspector_title', undefined, 'Runtime inspector')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t('admin.site_detail.runtime_inspector_desc', undefined, 'Keep callback failures, queued traffic, and last activity visible before moving into provider-level debugging.')
              }
            </p>
          </div>
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-3 xl:grid-cols-3"
            items={[
              { label: t('admin.total_runs'), value: formatInteger(site.runtime_summary?.total_runs || 0) },
              {
                label: t('admin.failed_runs'),
                value: formatInteger(site.runtime_summary?.failed_runs || 0),
                toneClassName: (site.runtime_summary?.failed_runs || 0) > 0 ? 'text-red-600 dark:text-red-400' : undefined,
              },
              {
                label: t('admin.last_run'),
                value: site.runtime_summary?.last_run_at ? formatDate(site.runtime_summary.last_run_at) : t('common.never'),
              },
            ]}
          />
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.recent_usage')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.site_detail.usage_window_title', undefined, 'Usage window')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t('admin.site_detail.usage_window_desc', undefined, 'Check current request volume and estimated cost before deciding whether a runtime issue is isolated or systemic.')
              }
            </p>
          </div>
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-3 xl:grid-cols-3"
            items={[
              { label: t('common.requests'), value: formatInteger(site.usage_summary?.requests_total || 0) },
              { label: t('common.tokens'), value: formatInteger(site.usage_summary?.tokens_total || 0) },
              { label: t('admin.est_cost'), value: formatAdminCurrency(site.usage_summary?.cost_estimate || 0) },
            ]}
          />
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.billing_summary')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.site_detail.billing_window_title', undefined, 'Billing window')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t('admin.site_detail.billing_window_desc', undefined, 'Billing snapshots stay secondary here; inspect them only when a commercial or reconciliation question is already explicit.')
              }
            </p>
          </div>
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-2 xl:grid-cols-2"
            items={[
              { label: t('billing.total_snapshots'), value: formatInteger(site.billing_summary?.total_snapshots || 0) },
              {
                label: t('billing.latest_snapshot'),
                value: site.billing_summary?.latest_snapshot
                  ? formatAdminCurrency(site.billing_summary.latest_snapshot.cost)
                  : t('common.not_found'),
                detail: site.billing_summary?.latest_snapshot
                  ? translateStatusLabel(site.billing_summary.latest_snapshot.status, t)
                  : undefined,
              },
            ]}
          />
        </BackofficeSectionPanel>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <BackofficeSectionPanel>
          <div className="border-b border-gray-200 px-6 py-5 dark:border-gray-800">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.site_admin_workspace_eyebrow', undefined, 'Site admin workspace')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.site_admin_workspace_title', undefined, 'Workspace access')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t(
                'admin.site_admin_workspace_desc',
                undefined,
                'Site administrators use the Cloud site workspace for this site. Access is bound per site and audited through the service API.'
              )}
            </p>
          </div>
          <div className="px-6 py-5">
            <BackofficeMetricStrip
              columnsClassName="md:grid-cols-2"
              items={[
                {
                  label: t('admin.site_admin_access_scope', undefined, 'Access scope'),
                  value: t('admin.site_admin_access_scope_site', undefined, 'This site'),
                },
                {
                  label: t('common.status'),
                  value: t('common.enabled', undefined, 'Enabled'),
                },
              ]}
            />
          </div>
        </BackofficeSectionPanel>
      </div>
      </BackofficeDisclosure>
    </BackofficePageStack>
  );
}

function CoverageMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200/80 px-4 py-3 dark:border-slate-800">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-sm font-semibold text-slate-950 dark:text-white">{value}</p>
    </div>
  );
}

export default function AdminSiteDetailPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <SiteDetailContent />
    </Suspense>
  );
}
