'use client';

import React, { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { localizeAdminCommercialCopy } from '@/lib/admin-commercial-copy';
import { resolveUiErrorMessage } from '@/lib/errors';
import { normalizeStatusToken, translateStatusLabel } from '@/lib/status-display';
import { readResponsePayload } from '@/lib/safe-response';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { AdminAuditSummaryPanel } from '@/components/admin/AdminAuditSummaryPanel';
import { formatAdminCurrency } from '@/lib/currency';
import { formatDate, formatNumber as formatInteger } from '@/lib/utils';

type SubscriptionDetailPayload = {
  subscription?: {
    subscription_id?: string;
    account_id?: string;
    status?: string;
    plan_id?: string;
    plan_version_id?: string;
    current_period_start_at?: string;
    current_period_end_at?: string;
    metadata?: Record<string, unknown>;
  };
  account?: {
    account_id?: string;
    name?: string;
    status?: string;
  };
  covered_sites?: Array<{
    site_id?: string;
    name?: string;
    status?: string;
  }>;
  plan?: {
    plan_id?: string;
    display_name?: string;
  };
  plan_version?: {
    plan_version_id?: string;
  };
  commercial_policy?: {
    subscription?: {
      grace_period_days?: number;
    };
  };
  budget_headroom?: {
    base_budget?: {
      runs?: number;
      tokens?: number;
      cost?: number;
    };
    current_period_topup_delta?: {
      runs?: number;
      tokens?: number;
      cost?: number;
    };
    effective_budget?: {
      runs?: number;
      tokens?: number;
      cost?: number;
    };
  };
  budget_state?: Record<
    string,
    {
      current_total?: number;
      limit?: number;
      over_limit?: boolean;
    }
  >;
  subscription_grace?: {
    subscription_status?: string;
    active?: boolean;
    grace_until_at?: string;
  };
  usage_totals?: {
    runs?: number;
    tokens?: number;
    cost?: number;
  };
  related_surfaces?: {
    site_href?: string;
    account_href?: string;
    audit_href?: string;
  };
  billing_snapshot_status?: {
    status?: string;
    summary?: string;
    site_count?: number;
    fresh_site_count?: number;
    stale_site_count?: number;
    missing_site_count?: number;
    next_action?: {
      action?: string;
      label?: string;
      detail?: string;
    } | null;
  };
  commercial_follow_up?: {
    lifecycle_posture?: string;
    snapshot_reconciliation_summary?: string;
    next_operator_follow_up?: string;
  };
};

function SubscriptionDetailContent() {
  const params = useParams();
  const { t } = useLocale();
  const { subscriptionId } = params as { subscriptionId: string };
  const [detail, setDetail] = useState<SubscriptionDetailPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mutationNotice, setMutationNotice] = useState<string | null>(null);
  const [isSnapshotRefreshSaving, setIsSnapshotRefreshSaving] = useState(false);

  useEffect(() => {
    const loadDetail = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await fetch(`/api/admin/subscriptions/${encodeURIComponent(subscriptionId)}`, {
          credentials: 'include',
        });

        if (!response.ok) {
          throw new Error(t('error.failed_load'));
        }

        const payload = await response.json();
        setDetail((payload?.data ?? null) as SubscriptionDetailPayload | null);
      } catch (err) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadDetail();
  }, [subscriptionId, t]);

  const reloadDetail = async () => {
    const response = await fetch(`/api/admin/subscriptions/${encodeURIComponent(subscriptionId)}`, {
      credentials: 'include',
    });
    if (!response.ok) {
      throw new Error(t('error.failed_load'));
    }
    const payload = await response.json();
    setDetail((payload?.data ?? null) as SubscriptionDetailPayload | null);
  };

  const normalized = useMemo(() => {
    const subscription = detail?.subscription ?? {};
    const account = detail?.account ?? {};
    const relatedSites = Array.isArray(detail?.covered_sites)
      ? detail?.covered_sites ?? []
      : [];
    const plan = detail?.plan ?? {};
    const planVersion = detail?.plan_version ?? {};
    const budget = detail?.budget_state ?? {};
    const usage = detail?.usage_totals ?? {};
    const grace = detail?.subscription_grace ?? {};
    const graceDays = Number(detail?.commercial_policy?.subscription?.grace_period_days ?? 0);
    const budgetHeadroom = detail?.budget_headroom ?? {};
    const billingSnapshotStatus = detail?.billing_snapshot_status ?? {};

    return {
      subscriptionId: String(subscription.subscription_id || subscriptionId),
      status: normalizeStatusToken(String(subscription.status || grace.subscription_status || 'unknown')),
      accountId: String(account.account_id || subscription.account_id || ''),
      accountName: String(account.name || account.account_id || ''),
      planId: String(plan.plan_id || subscription.plan_id || ''),
      planName: String(plan.display_name || plan.plan_id || subscription.plan_id || ''),
      planVersionId: String(planVersion.plan_version_id || subscription.plan_version_id || ''),
      currentPeriodStart: String(subscription.current_period_start_at || ''),
      currentPeriodEnd: String(subscription.current_period_end_at || ''),
      graceDays,
      graceActive: Boolean(grace.active),
      graceUntilAt: String(grace.grace_until_at || ''),
      runsCurrent: Number(budget.runs?.current_total ?? usage.runs ?? 0),
      runsLimit: Number(budget.runs?.limit ?? 0),
      tokensCurrent: Number(budget.tokens?.current_total ?? usage.tokens ?? 0),
      tokensLimit: Number(budget.tokens?.limit ?? 0),
      costCurrent: Number(budget.cost?.current_total ?? usage.cost ?? 0),
      costLimit: Number(budget.cost?.limit ?? 0),
      baseRunsLimit: Number(budgetHeadroom.base_budget?.runs ?? 0),
      baseTokensLimit: Number(budgetHeadroom.base_budget?.tokens ?? 0),
      baseCostLimit: Number(budgetHeadroom.base_budget?.cost ?? 0),
      topupRunsDelta: Number(budgetHeadroom.current_period_topup_delta?.runs ?? 0),
      topupTokensDelta: Number(budgetHeadroom.current_period_topup_delta?.tokens ?? 0),
      topupCostDelta: Number(budgetHeadroom.current_period_topup_delta?.cost ?? 0),
      effectiveRunsLimit: Number(budgetHeadroom.effective_budget?.runs ?? budget.runs?.limit ?? 0),
      effectiveTokensLimit: Number(budgetHeadroom.effective_budget?.tokens ?? budget.tokens?.limit ?? 0),
      effectiveCostLimit: Number(budgetHeadroom.effective_budget?.cost ?? budget.cost?.limit ?? 0),
      billingSnapshotStatus: String(billingSnapshotStatus.status || 'unknown'),
      billingSnapshotSummary: String(billingSnapshotStatus.summary || ''),
      billingSnapshotFreshCount: Number(billingSnapshotStatus.fresh_site_count ?? 0),
      billingSnapshotStaleCount: Number(billingSnapshotStatus.stale_site_count ?? 0),
      billingSnapshotMissingCount: Number(billingSnapshotStatus.missing_site_count ?? 0),
      billingSnapshotNextAction: {
        action: String(billingSnapshotStatus.next_action?.action || ''),
        label: String(billingSnapshotStatus.next_action?.label || ''),
        detail: String(billingSnapshotStatus.next_action?.detail || ''),
      },
      hasBudgetPressure: Boolean(budget.runs?.over_limit || budget.tokens?.over_limit || budget.cost?.over_limit),
      relatedSites: relatedSites.map((site) => ({
        siteId: String(site.site_id || ''),
        siteName: String(site.name || site.site_id || ''),
        status: String(site.status || 'unknown'),
      })),
    };
  }, [detail, subscriptionId]);

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

  const nextStepCopy = normalized.hasBudgetPressure
    ? t(
        'admin.subscription_detail.next_step_budget',
        {},
        'Budget pressure is already visible. Read customer subscription posture first, then move to a covered site only if runtime follow-up becomes operational.'
      )
    : normalized.status === 'past_due' || normalized.status === 'expired'
      ? t(
          'admin.subscription_detail.next_step_status',
          {},
          'Commercial follow-up is the first concern. Open the customer account first, then move to a site only when you need service continuity context.'
        )
      : t(
          'admin.subscription_detail.next_step_default',
          {},
          'This inspector is stable. Use customer detail for access and coverage context, then open a covered site only when runtime continuity needs inspection.'
        );
  const statusValue = translateStatusLabel(normalized.status, t);
  const lifecyclePosture = localizeAdminCommercialCopy(detail?.commercial_follow_up?.lifecycle_posture, t);
  const snapshotReconciliation = localizeAdminCommercialCopy(
    detail?.commercial_follow_up?.snapshot_reconciliation_summary,
    t
  );
  const nextOperatorFollowUp = localizeAdminCommercialCopy(
    detail?.commercial_follow_up?.next_operator_follow_up,
    t
  );
  const billingSnapshotStatusLabel =
    normalized.billingSnapshotStatus === 'fresh'
      ? t('admin.subscription_detail.snapshot_status_fresh', {}, 'Fresh')
      : normalized.billingSnapshotStatus === 'stale'
      ? t('admin.subscription_detail.snapshot_status_stale', {}, 'Stale')
      : normalized.billingSnapshotStatus === 'missing'
      ? t('admin.subscription_detail.snapshot_status_missing', {}, 'Missing')
      : t('common.unknown', {}, 'Unknown');
  const billingSnapshotStatusTone =
    normalized.billingSnapshotStatus === 'fresh'
      ? 'active'
      : normalized.billingSnapshotStatus === 'stale'
      ? 'warning'
      : normalized.billingSnapshotStatus === 'missing'
      ? 'error'
      : 'unknown';
  const localizedBillingSnapshotSummary = localizeAdminCommercialCopy(normalized.billingSnapshotSummary, t);
  const localizedSnapshotActionLabel = localizeAdminCommercialCopy(normalized.billingSnapshotNextAction.label, t);
  const localizedSnapshotActionDetail = localizeAdminCommercialCopy(normalized.billingSnapshotNextAction.detail, t);
  const hasSnapshotFollowUp = ['missing', 'stale'].includes(normalized.billingSnapshotStatus);
  const relatedSiteCountLabel =
    normalized.relatedSites.length > 0
      ? t(
          'admin.subscription_detail.covered_sites_count',
          { count: String(normalized.relatedSites.length) },
          `${normalized.relatedSites.length} covered sites`
        )
      : t('common.not_found', {}, 'Not found');

  const handleBillingSnapshotRefresh = async () => {
    setMutationNotice(null);
    setError(null);
    setIsSnapshotRefreshSaving(true);
    try {
      const response = await fetch(
        `/api/admin/subscriptions/${encodeURIComponent(normalized.subscriptionId)}/billing-snapshots/rebuild`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        }
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload?.message ?? null, t('error.failed_save', {}, 'Failed to save.')));
      }
      setMutationNotice(
        t(
          'admin.subscription_detail.snapshot_refresh_notice',
          {},
          'Current-period billing snapshots were rebuilt for this subscription.'
        )
      );
      await reloadDetail();
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save', {}, 'Failed to save.')));
    } finally {
      setIsSnapshotRefreshSaving(false);
    }
  };

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_group_commercial_ops', {}, 'Commercial Ops')}
        title={t(
          'admin.subscription_detail.title',
          { subscription: normalized.subscriptionId },
          `Subscription service status: ${normalized.subscriptionId}`
        )}
        description={t(
          'admin.subscription_detail.primary_desc',
          {},
          'Check the subscription conclusion first, then handle the billing, package, or customer follow-up shown below.'
        )}
        actions={(
          <>
            <Link href="/admin/subscriptions" className="btn btn-secondary">
              {t('admin.back_to_subscriptions', {}, 'Back to subscriptions')}
            </Link>
            {detail?.related_surfaces?.account_href ? (
              <Link href={detail.related_surfaces.account_href} className="btn btn-primary">
                {t('admin.subscription_detail.open_customer_action', {}, 'Open customer')}
              </Link>
            ) : null}
            {detail?.related_surfaces?.account_href || normalized.accountId ? (
              <Link
                href={`${detail?.related_surfaces?.account_href || `/admin/accounts/${encodeURIComponent(normalized.accountId)}`}#coverage-actions`}
                className="btn btn-secondary"
              >
                {t('admin.account_detail.change_package_action', {}, 'Change package')}
              </Link>
            ) : null}
          </>
        )}
        summary={(
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-4"
            items={[
              {
                label: t('status.active', {}, 'Status'),
                value: statusValue,
                detail: t('admin.subscription_detail.status_metric', {}, 'Current operator-visible subscription state.'),
              },
              {
                label: t('admin.current_package', {}, 'Current package'),
                value: normalized.planId || t('common.unknown', {}, 'Unknown'),
                detail: normalized.planVersionId || t('common.not_available', {}, 'N/A'),
              },
              {
                label: t('admin.subscription_detail.snapshot_freshness', {}, 'Snapshot freshness'),
                value: billingSnapshotStatusLabel,
                detail: localizedBillingSnapshotSummary || t('admin.subscription_detail.snapshot_freshness_desc', {}, 'Current-period billing evidence.'),
              },
              {
                label: t('admin.subscription_detail.covered_sites_label', {}, 'Covered sites'),
                value: formatInteger(normalized.relatedSites.length),
                detail: t('admin.subscription_detail.related_sites_metric_detail', {}, 'Related evidence only.'),
              },
            ]}
          />
        )}
      >
        <BackofficeStackCard className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <BackofficeStatusBadge status={normalized.status} label={translateStatusLabel(normalized.status, t)} />
              <BackofficeStatusBadge status={billingSnapshotStatusTone} label={billingSnapshotStatusLabel} />
              {normalized.graceActive ? (
                <BackofficeStatusBadge status="warning" label={t('admin.subscription_detail.grace_active', {}, 'Grace active')} />
              ) : null}
            </div>
            <BackofficeIdentifier
              value={normalized.subscriptionId}
              className="mt-3 block text-sm font-semibold text-slate-950 dark:text-white"
              full
            />
            <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-600 dark:text-slate-300">
              {hasSnapshotFollowUp
                ? t('admin.subscription_detail.current_conclusion_snapshot', {}, 'Current-period billing evidence needs follow-up before treating this subscription as reconciled.')
                : nextStepCopy}
            </p>
          </div>
          {hasSnapshotFollowUp && normalized.billingSnapshotNextAction.action ? (
            <button
              type="button"
              className="btn btn-primary shrink-0"
              onClick={() => void handleBillingSnapshotRefresh()}
              disabled={isSnapshotRefreshSaving}
            >
              {isSnapshotRefreshSaving
                ? t('admin.subscription_detail.snapshot_refresh_saving', {}, 'Rebuilding snapshots...')
                : localizedSnapshotActionLabel ||
                  t('admin.subscription_detail.snapshot_refresh_action', {}, 'Rebuild current-period billing snapshots')}
            </button>
          ) : null}
        </BackofficeStackCard>
      </BackofficePrimaryPanel>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(24rem,0.85fr)]">
        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.subscription_detail.commercial_status_eyebrow', {}, 'Commercial status')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.subscription_detail.commercial_status_title', {}, 'Package and billing state')}
            </h2>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <BackofficeStackCard>
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{t('common.account', {}, 'Customer')}</p>
              <p className="mt-2 text-base font-semibold text-slate-950 dark:text-white">
                {normalized.accountName || normalized.accountId || t('common.unknown', {}, 'Unknown')}
              </p>
              {normalized.accountId ? (
                <Link href={`/admin/accounts/${normalized.accountId}`} className="mt-3 inline-flex text-sm font-medium text-blue-600 hover:underline dark:text-blue-300">
                  <BackofficeIdentifier value={normalized.accountId} />
                </Link>
              ) : null}
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{t('admin.current_package', {}, 'Current package')}</p>
              <p className="mt-2 text-base font-semibold text-slate-950 dark:text-white">
                {normalized.planId || t('common.unknown', {}, 'Unknown')}
              </p>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                {normalized.planVersionId || t('common.not_available', {}, 'N/A')}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{t('admin.billing_period', {}, 'Billing period')}</p>
              <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">
                {normalized.currentPeriodStart ? formatDate(normalized.currentPeriodStart) : t('common.not_available', {}, 'N/A')}
                {' - '}
                {normalized.currentPeriodEnd ? formatDate(normalized.currentPeriodEnd) : t('common.not_available', {}, 'N/A')}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{t('admin.subscription_detail.grace_policy', {}, 'Grace policy')}</p>
              <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">
                {t('admin.subscription_detail.grace_days', { days: String(normalized.graceDays) }, `${normalized.graceDays} day grace policy`)}
              </p>
              {normalized.graceUntilAt ? (
                <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  {t('admin.subscription_detail.grace_until', { date: formatDate(normalized.graceUntilAt) }, `Grace until ${formatDate(normalized.graceUntilAt)}`)}
                </p>
              ) : null}
            </BackofficeStackCard>
          </div>
          <BackofficeStackCard>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                  {t('admin.subscription_detail.usage_title', {}, 'Budget and usage')}
                </p>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {t('admin.subscription_detail.usage_boundary', {}, 'Base budget plus current-period top-up becomes the effective budget.')}
                </p>
              </div>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="min-w-[36rem] text-left text-sm">
                <thead className="text-xs text-slate-500 dark:text-slate-400">
                  <tr>
                    <th className="py-2 font-semibold">{t('admin.subscription_detail.metric_label', {}, 'Metric')}</th>
                    <th className="py-2 font-semibold">{t('admin.subscription_detail.base_budget', {}, 'Base budget')}</th>
                    <th className="py-2 font-semibold">{t('admin.subscription_detail.current_topup', {}, 'Top-up')}</th>
                    <th className="py-2 font-semibold">{t('admin.subscription_detail.effective_budget', {}, 'Effective budget')}</th>
                    <th className="py-2 font-semibold">{t('admin.subscription_detail.used', {}, 'Used')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200/70 dark:divide-slate-800">
                  <tr>
                    <td className="py-2 text-slate-600 dark:text-slate-300">{t('common.requests', {}, 'Runs')}</td>
                    <td className="py-2 font-medium tabular-nums">{formatInteger(normalized.baseRunsLimit)}</td>
                    <td className="py-2 font-medium tabular-nums">{formatInteger(normalized.topupRunsDelta)}</td>
                    <td className="py-2 font-semibold tabular-nums text-slate-950 dark:text-white">{formatInteger(normalized.effectiveRunsLimit)}</td>
                    <td className="py-2 font-medium tabular-nums">{formatInteger(normalized.runsCurrent)}</td>
                  </tr>
                  <tr>
                    <td className="py-2 text-slate-600 dark:text-slate-300">{t('common.tokens', {}, 'Tokens')}</td>
                    <td className="py-2 font-medium tabular-nums">{formatInteger(normalized.baseTokensLimit)}</td>
                    <td className="py-2 font-medium tabular-nums">{formatInteger(normalized.topupTokensDelta)}</td>
                    <td className="py-2 font-semibold tabular-nums text-slate-950 dark:text-white">{formatInteger(normalized.effectiveTokensLimit)}</td>
                    <td className="py-2 font-medium tabular-nums">{formatInteger(normalized.tokensCurrent)}</td>
                  </tr>
                  <tr>
                    <td className="py-2 text-slate-600 dark:text-slate-300">{t('common.cost', {}, 'Cost')}</td>
                    <td className="py-2 font-medium tabular-nums">{formatAdminCurrency(normalized.baseCostLimit)}</td>
                    <td className="py-2 font-medium tabular-nums">{formatAdminCurrency(normalized.topupCostDelta)}</td>
                    <td className="py-2 font-semibold tabular-nums text-slate-950 dark:text-white">{formatAdminCurrency(normalized.effectiveCostLimit)}</td>
                    <td className="py-2 font-medium tabular-nums">{formatAdminCurrency(normalized.costCurrent)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </BackofficeStackCard>
        </BackofficeSectionPanel>

        <div className="space-y-6">
          <BackofficeSectionPanel className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.subscription_detail.follow_up_eyebrow', {}, 'Follow-up')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.subscription_detail.follow_up_title', {}, 'What needs action')}
              </h2>
            </div>
            <BackofficeStackCard className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">
                    {t('admin.subscription_detail.snapshot_freshness', {}, 'Snapshot freshness')}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {t(
                      'admin.subscription_detail.snapshot_freshness_counts',
                      {
                        fresh: String(normalized.billingSnapshotFreshCount),
                        stale: String(normalized.billingSnapshotStaleCount),
                        missing: String(normalized.billingSnapshotMissingCount),
                      },
                      `Fresh ${normalized.billingSnapshotFreshCount} · Stale ${normalized.billingSnapshotStaleCount} · Missing ${normalized.billingSnapshotMissingCount}`
                    )}
                  </p>
                </div>
                <BackofficeStatusBadge status={billingSnapshotStatusTone} label={billingSnapshotStatusLabel} />
              </div>
              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {localizedBillingSnapshotSummary ||
                  t(
                    'admin.subscription_detail.snapshot_freshness_desc',
                    {},
                    'Billing snapshot freshness stays tied to the current subscription period.'
                  )}
              </p>
              {normalized.billingSnapshotNextAction.action ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/50">
                  <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {localizedSnapshotActionDetail ||
                      t('admin.subscription_detail.snapshot_refresh_detail', {}, 'Refresh current-period billing snapshots for every covered site before treating billing posture as reconciled.')}
                  </p>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm mt-3"
                    onClick={() => void handleBillingSnapshotRefresh()}
                    disabled={isSnapshotRefreshSaving}
                  >
                    {isSnapshotRefreshSaving
                      ? t('admin.subscription_detail.snapshot_refresh_saving', {}, 'Rebuilding snapshots...')
                      : localizedSnapshotActionLabel ||
                        t('admin.subscription_detail.snapshot_refresh_action', {}, 'Rebuild current-period billing snapshots')}
                  </button>
                </div>
              ) : null}
              {mutationNotice ? (
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-300">
                  {mutationNotice}
                </div>
              ) : null}
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('admin.subscription_detail.route_hint', {}, 'Route discipline')}
              </p>
              <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t(
                  'admin.subscription_detail.route_hint_desc',
                  {},
                  'This page stays a commercial inspector. It does not become the customer access authority, site access authority, or runtime control surface.'
                )}
              </p>
              <div className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                {lifecyclePosture ? <p>{lifecyclePosture}</p> : null}
                {snapshotReconciliation ? <p>{snapshotReconciliation}</p> : null}
                {nextOperatorFollowUp ? <p>{nextOperatorFollowUp}</p> : null}
              </div>
            </BackofficeStackCard>
          </BackofficeSectionPanel>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,0.8fr)]">
        <BackofficeSectionPanel className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.subscription_detail.related_evidence_eyebrow', {}, 'Related evidence')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.subscription_detail.covered_sites_label', {}, 'Covered sites')}
              </h2>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                {t(
                  'admin.subscription_detail.related_sites_scope_desc',
                  {},
                  'Sites remain related operating surfaces. They are not the commercial authority for this subscription.'
                )}
              </p>
            </div>
            <BackofficeStatusBadge status="inactive" label={relatedSiteCountLabel} />
          </div>
          {normalized.relatedSites.length > 0 ? (
            <div className="divide-y divide-slate-200/80 overflow-hidden rounded-2xl border border-slate-200/80 dark:divide-slate-800 dark:border-slate-800">
              {normalized.relatedSites.map((site) => (
                <div key={site.siteId} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                  <div>
                    <p className="font-medium text-slate-950 dark:text-white">{site.siteName || site.siteId}</p>
                    <Link href={`/admin/sites/${site.siteId}`} className="mt-1 inline-flex text-sm font-medium text-blue-600 hover:underline dark:text-blue-300">
                      <BackofficeIdentifier value={site.siteId} className="text-sm text-blue-600 dark:text-blue-300" />
                    </Link>
                  </div>
                  <BackofficeStatusBadge status={site.status} label={translateStatusLabel(site.status, t)} />
                </div>
              ))}
            </div>
          ) : (
            <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
              {t('admin.subscription_detail.no_covered_sites', {}, 'No covered sites are attached to this subscription.')}
            </BackofficeStackCard>
          )}
        </BackofficeSectionPanel>
        <AdminAuditSummaryPanel
          title={t('admin.audit_summary.subscription_title', {}, 'Recent audit summary for this subscription')}
          siteId={normalized.relatedSites[0]?.siteId || ''}
          accountId={normalized.accountId}
          trailHref={detail?.related_surfaces?.audit_href}
        />
      </div>
    </BackofficePageStack>
  );
}

export default function AdminSubscriptionDetailPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <SubscriptionDetailContent />
    </Suspense>
  );
}
