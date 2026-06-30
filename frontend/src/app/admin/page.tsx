'use client';

import React, { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { formatAdminCurrency } from '@/lib/currency';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { buildAdminOperatorWatchItems, operatorSeverityClasses } from '@/lib/admin-operator-signals';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';

interface AdminOverview {
  generatedAt: string;
  totals: {
    accounts: number;
    siteAdmins: number;
    sites: number;
    sitesActive: number;
    subscriptions: number;
    subscriptionsActive: number;
    siteKeysActive: number;
  };
  expiringSubscriptions: {
    in7Days: number;
    in30Days: number;
    items: Array<{
      subscriptionId: string;
      accountId: string;
      siteId: string;
      status: string;
      currentPeriodEnd: string;
      daysUntilEnd: number;
    }>;
  };
  attentionSubscriptions: Array<{
    subscriptionId: string;
    accountId: string;
    siteId: string;
    status: string;
    reason: string;
  }>;
  runtimeSummary: {
    queuedRuns: number;
    runningRuns: number;
    callbackFailed: number;
    callbackPending: number;
    guardEvents: number;
  };
  recentUsage: {
    windowDays: number;
    runs: number;
    providerCalls: number;
    tokensTotal: number;
    cost: number;
  };
  platformCreditSummary: {
    windowDays: number;
    periodStartAt: string;
    periodEndAt: string;
    previousPeriodStartAt: string;
    previousPeriodEndAt: string;
    credit: {
      used: number;
      estimated: boolean;
      rateVersion: string;
      source: string;
    };
    breakdown: Array<{
      key: string;
      label: string;
      quantity: number;
      unit: string;
      credits: number;
    }>;
    topAccounts: Array<{
      accountId: string;
      credits: number;
      runs: number;
      providerCalls: number;
      tokensTotal: number;
    }>;
    trend: {
      currentUsed: number;
      previousUsed: number;
      delta: number;
      deltaPercent: number | null;
      status: string;
      previousPeriodStartAt: string;
      previousPeriodEndAt: string;
    };
    watchItems: Array<{
      code: string;
      severity: string;
      title: string;
      detail: string;
      metric: string;
      value: number;
      delta: number;
      accountId: string;
      href: string;
    }>;
  };
  planDistribution: Array<{
    planId: string;
    count: number;
  }>;
  recentAuditSummary: Array<{
    eventKind: string;
    outcome: string;
    count: number;
    lastSeenAt: string;
  }>;
  runtimeOperatorExplanations: Array<{
    state: string;
    explainText: string;
    nextStepKind: string;
    nextStepRef: string;
  }>;
  hostedModelGovernance: {
    status: string;
    summary: string;
    alertCount: number;
    href: string;
    dailyDigest: {
      runs: number;
      providerCalls: number;
      meterEvents: number;
      meteredRunCoverageRate: number;
      providerCallRunCoverageRate: number;
      unmeteredRunCount: number;
      runsWithoutProviderCallCount: number;
    };
    alerts: Array<{
      code: string;
      severity: string;
      title: string;
      summary: string;
      count: number;
      capabilities: string[];
    }>;
  };
}

function normalizeOverview(raw: any): AdminOverview {
  const counts = raw?.counts ?? {};
  const expiring = raw?.expiring_subscriptions ?? {};
  const runtimeDiagnostics = raw?.runtime_diagnostics ?? {};
  const queue = runtimeDiagnostics?.queue ?? {};
  const callback = runtimeDiagnostics?.callback ?? {};
  const guard = runtimeDiagnostics?.guard ?? {};
  const recentUsage = raw?.recent_usage ?? {};
  const totals = recentUsage?.totals ?? {};
  const hostedGovernance = raw?.hosted_model_governance ?? {};
  const hostedAlertSummary = hostedGovernance?.alert_summary ?? {};
  const hostedDailyDigest = hostedAlertSummary?.daily_digest ?? {};
  const platformCredit = raw?.platform_credit_summary ?? {};
  const platformCreditMetric = platformCredit?.credit ?? {};

  return {
    generatedAt: String(raw?.generated_at ?? ''),
    totals: {
      accounts: Number(counts.accounts_total ?? 0),
      siteAdmins: Number(counts.site_admins_active ?? 0),
      sites: Number(counts.sites_total ?? 0),
      sitesActive: Number(counts.sites_active ?? 0),
      subscriptions: Number(counts.subscriptions_total ?? 0),
      subscriptionsActive: Number(counts.subscriptions_active ?? 0),
      siteKeysActive: Number(counts.site_keys_active ?? 0),
    },
    expiringSubscriptions: {
      in7Days: Number(expiring.within_7_days ?? 0),
      in30Days: Number(expiring.within_30_days ?? 0),
      items: Array.isArray(expiring.items)
        ? expiring.items.map((item: any) => ({
            subscriptionId: String(item?.subscription?.subscription_id ?? ''),
            accountId: String(item?.account?.account_id ?? ''),
            siteId: String(item?.site?.site_id ?? ''),
            status: String(item?.subscription?.status ?? ''),
            currentPeriodEnd: String(
              item?.expiry?.current_period_end_at ?? item?.subscription?.current_period_end_at ?? ''
            ),
            daysUntilEnd: Number(item?.expiry?.days_until_end ?? 0),
          }))
        : [],
    },
    attentionSubscriptions: Array.isArray(raw?.attention_subscriptions)
      ? raw.attention_subscriptions.map((item: any) => ({
          subscriptionId: String(item?.subscription?.subscription_id ?? item?.subscription_id ?? ''),
          accountId: String(item?.account?.account_id ?? item?.account_id ?? ''),
          siteId: String(item?.site?.site_id ?? item?.site_id ?? ''),
          status: String(item?.subscription?.status ?? item?.status ?? ''),
          reason: String(item?.reason ?? item?.message ?? ''),
        }))
      : [],
    runtimeSummary: {
      queuedRuns: Number(queue.queued_runs ?? 0),
      runningRuns: Number(queue.running_runs ?? 0),
      callbackFailed: Number(callback.failed ?? 0),
      callbackPending: Number(callback.pending ?? 0),
      guardEvents: Number(guard.recent_events ?? 0),
    },
    recentUsage: {
      windowDays: Number(recentUsage.window_days ?? 7),
      runs: Number(totals.runs ?? 0),
      providerCalls: Number(totals.provider_calls ?? 0),
      tokensTotal: Number(totals.tokens_total ?? 0),
      cost: Number(totals.cost ?? 0),
    },
    platformCreditSummary: {
      windowDays: Number(platformCredit.window_days ?? recentUsage.window_days ?? 7),
      periodStartAt: String(platformCredit.period_start_at ?? ''),
      periodEndAt: String(platformCredit.period_end_at ?? ''),
      previousPeriodStartAt: String(platformCredit.previous_period_start_at ?? ''),
      previousPeriodEndAt: String(platformCredit.previous_period_end_at ?? ''),
      credit: {
        used: Number(platformCreditMetric.used ?? 0),
        estimated: Boolean(platformCreditMetric.estimated),
        rateVersion: String(platformCreditMetric.rate_version ?? ''),
        source: String(platformCreditMetric.source ?? ''),
      },
      breakdown: Array.isArray(platformCredit.breakdown)
        ? platformCredit.breakdown.map((item: any) => ({
            key: String(item?.key ?? ''),
            label: String(item?.label ?? item?.key ?? ''),
            quantity: Number(item?.quantity ?? 0),
            unit: String(item?.unit ?? ''),
            credits: Number(item?.credits ?? 0),
          }))
        : [],
      topAccounts: Array.isArray(platformCredit.top_accounts)
        ? platformCredit.top_accounts.map((item: any) => ({
            accountId: String(item?.account_id ?? ''),
            credits: Number(item?.credits ?? 0),
            runs: Number(item?.runs ?? 0),
            providerCalls: Number(item?.provider_calls ?? 0),
            tokensTotal: Number(item?.tokens_total ?? 0),
          }))
        : [],
      trend: {
        currentUsed: Number(platformCredit.trend?.current_used ?? platformCreditMetric.used ?? 0),
        previousUsed: Number(platformCredit.trend?.previous_used ?? 0),
        delta: Number(platformCredit.trend?.delta ?? 0),
        deltaPercent:
          platformCredit.trend?.delta_percent === null || platformCredit.trend?.delta_percent === undefined
            ? null
            : Number(platformCredit.trend.delta_percent),
        status: String(platformCredit.trend?.status ?? 'flat'),
        previousPeriodStartAt: String(platformCredit.trend?.previous_period_start_at ?? platformCredit.previous_period_start_at ?? ''),
        previousPeriodEndAt: String(platformCredit.trend?.previous_period_end_at ?? platformCredit.previous_period_end_at ?? ''),
      },
      watchItems: Array.isArray(platformCredit.watch_items)
        ? platformCredit.watch_items.map((item: any) => ({
            code: String(item?.code ?? ''),
            severity: String(item?.severity ?? 'info'),
            title: String(item?.title ?? ''),
            detail: String(item?.detail ?? ''),
            metric: String(item?.metric ?? ''),
            value: Number(item?.value ?? 0),
            delta: Number(item?.delta ?? 0),
            accountId: String(item?.account_id ?? ''),
            href: String(item?.href ?? '/admin/accounts'),
          }))
        : [],
    },
    planDistribution: Array.isArray(raw?.plan_distribution)
      ? raw.plan_distribution.map((item: any) => ({
          planId: String(item?.plan_id ?? ''),
          count: Number(item?.count ?? 0),
        }))
      : [],
    recentAuditSummary: Array.isArray(raw?.recent_audit_summary?.items)
      ? raw.recent_audit_summary.items.map((item: any) => ({
          eventKind: String(item?.event_kind ?? ''),
          outcome: String(item?.outcome ?? ''),
          count: Number(item?.count ?? 0),
          lastSeenAt: String(item?.last_seen_at ?? ''),
        }))
      : [],
    runtimeOperatorExplanations: Array.isArray(raw?.runtime_operator_explanations)
      ? raw.runtime_operator_explanations.map((item: any) => ({
          state: String(item?.state ?? ''),
          explainText: String(item?.explain_text ?? ''),
          nextStepKind: String(item?.next_step_kind ?? ''),
          nextStepRef: String(item?.next_step_ref ?? ''),
        }))
      : [],
    hostedModelGovernance: {
      status: String(hostedAlertSummary.status ?? 'inactive'),
      summary: String(hostedAlertSummary.summary ?? ''),
      alertCount: Number(hostedAlertSummary.alert_count ?? 0),
      href: String(hostedAlertSummary.href ?? '').startsWith('/admin/hosted-models')
        ? '/admin/ai-resources?view=diagnostics'
        : String(hostedAlertSummary.href ?? '/admin/ai-resources?view=diagnostics'),
      dailyDigest: {
        runs: Number(hostedDailyDigest.runs ?? 0),
        providerCalls: Number(hostedDailyDigest.provider_calls ?? 0),
        meterEvents: Number(hostedDailyDigest.meter_events ?? 0),
        meteredRunCoverageRate: Number(hostedDailyDigest.metered_run_coverage_rate ?? 0),
        providerCallRunCoverageRate: Number(hostedDailyDigest.provider_call_run_coverage_rate ?? 0),
        unmeteredRunCount: Number(hostedDailyDigest.unmetered_run_count ?? 0),
        runsWithoutProviderCallCount: Number(hostedDailyDigest.runs_without_provider_call_count ?? 0),
      },
      alerts: Array.isArray(hostedAlertSummary.alerts)
        ? hostedAlertSummary.alerts.map((item: any) => ({
            code: String(item?.code ?? ''),
            severity: String(item?.severity ?? ''),
            title: String(item?.title ?? ''),
            summary: String(item?.summary ?? ''),
            count: Number(item?.count ?? 0),
            capabilities: Array.isArray(item?.capabilities) ? item.capabilities.map(String) : [],
          }))
        : [],
    },
  };
}

function formatPercent(value: number): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function platformCreditBreakdownLabel(
  key: string,
  fallback: string,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  const labels: Record<string, string> = {
    runs: t('admin.platform_credit_breakdown_runs', {}, 'Hosted runs'),
    tokens_total: t('admin.platform_credit_breakdown_tokens', {}, 'Model tokens'),
    web_search: t('admin.platform_credit_breakdown_search', {}, 'Search'),
    image_recommendation: t('admin.platform_credit_breakdown_image', {}, 'Image recommendation'),
    provider_calls_other: t('admin.platform_credit_breakdown_provider_other', {}, 'Other provider calls'),
    vector_documents: t('admin.platform_credit_breakdown_vector_documents', {}, 'Vector articles'),
    vector_chunks: t('admin.platform_credit_breakdown_vector_chunks', {}, 'Vector chunks'),
  };
  return labels[key] || fallback || key;
}

function platformCreditTrendLabel(
  status: string,
  deltaPercent: number | null,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  if (status === 'new_activity') {
    return t('admin.platform_credit_trend_new', {}, 'New activity');
  }
  if (status === 'flat') {
    return t('admin.platform_credit_trend_flat', {}, 'Flat');
  }
  const direction =
    status === 'down'
      ? t('admin.platform_credit_trend_down', {}, 'Down')
      : t('admin.platform_credit_trend_up', {}, 'Up');
  if (deltaPercent === null) {
    return direction;
  }
  return `${direction} ${Math.abs(deltaPercent).toFixed(1)}%`;
}

function platformCreditWatchTitle(
  code: string,
  fallback: string,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  const titles: Record<string, string> = {
    credit_new_activity: t('admin.platform_credit_watch_new_title', {}, 'New platform credit activity'),
    credit_usage_spike: t('admin.platform_credit_watch_spike_title', {}, 'AI credit usage rose sharply'),
    credit_account_concentration: t('admin.platform_credit_watch_account_title', {}, 'Consumption is concentrated in one account'),
    credit_component_concentration: t('admin.platform_credit_watch_component_title', {}, 'One meter family dominates usage'),
    credit_source_changed_to_estimate: t('admin.platform_credit_watch_source_title', {}, 'Current window is using fallback metering'),
  };
  return titles[code] || fallback || code;
}

function platformCreditWatchDetail(
  code: string,
  fallback: string,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  const details: Record<string, string> = {
    credit_new_activity: t('admin.platform_credit_watch_new_detail', {}, 'The previous comparison window had no AI credit consumption.'),
    credit_usage_spike: t('admin.platform_credit_watch_spike_detail', {}, 'Current usage is at least 50% above the previous comparison window.'),
    credit_account_concentration: t('admin.platform_credit_watch_account_detail', {}, 'The top account accounts for at least 60% of this window’s AI credits.'),
    credit_component_concentration: t('admin.platform_credit_watch_component_detail', {}, 'One credit component accounts for at least 65% of this window’s consumption.'),
    credit_source_changed_to_estimate: t('admin.platform_credit_watch_source_detail', {}, 'The comparison window had ledger entries, but the current window is falling back to meter estimates.'),
  };
  return details[code] || fallback || code;
}

function platformCreditWatchSeverity(severity: string): 'watch' | 'warn' | 'action-needed' {
  if (severity === 'error' || severity === 'action-needed') {
    return 'action-needed';
  }
  if (severity === 'warning' || severity === 'warn') {
    return 'warn';
  }
  return 'watch';
}

function AdminOverviewContent() {
  const { t } = useLocale();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadOverview = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const overviewResponse = await fetch('/api/admin/overview', { credentials: 'include' });

        if (!overviewResponse.ok) {
          throw new Error(t('error.failed_load'));
        }

        const overviewPayload = await overviewResponse.json();
        setOverview(normalizeOverview(overviewPayload.data));
      } catch (err) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadOverview();
  }, [t]);

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

  if (!overview) {
    return null;
  }

  const operatorWatchItems = buildAdminOperatorWatchItems({
    runtimeSummary: overview.runtimeSummary,
    expiringSubscriptionsIn7Days: overview.expiringSubscriptions.in7Days,
    attentionSubscriptionsCount: overview.attentionSubscriptions.length,
    firstAttentionReason: overview.attentionSubscriptions[0]?.reason || '',
    hostedModelGovernance: {
      status: overview.hostedModelGovernance.status,
      alertCount: overview.hostedModelGovernance.alertCount,
      firstAlertTitle: overview.hostedModelGovernance.alerts[0]?.title || '',
      firstAlertSummary: overview.hostedModelGovernance.alerts[0]?.summary || '',
      summary: overview.hostedModelGovernance.summary,
    },
    formatValue: formatInteger,
    copy: {
      callbackTitle: t('admin.watch_callback_title'),
      callbackReason: t('admin.watch_callback_reason'),
      guardTitle: t('admin.watch_guard_title'),
      guardReason: t('admin.watch_guard_reason'),
      expiryTitle: t('admin.watch_expiry_title'),
      expiryReason: t('admin.watch_expiry_reason'),
      attentionTitle: t('admin.watch_attention_title'),
      attentionFallbackReason: t('admin.watch_attention_reason'),
      hostedTitle: t('admin.watch_hosted_governance_title', {}, 'Runtime telemetry needs review'),
      hostedReason: t(
        'admin.watch_hosted_governance_reason',
        {},
        'Runtime telemetry coverage needs review before traffic expands.'
      ),
    },
  });

  const statusTone =
    overview.runtimeSummary.callbackFailed > 0
      ? 'error'
      : overview.hostedModelGovernance.status === 'error'
        ? 'error'
      : overview.attentionSubscriptions.length > 0 ||
          overview.hostedModelGovernance.status === 'warning' ||
          overview.expiringSubscriptions.in7Days > 0 ||
          overview.runtimeSummary.guardEvents > 0 ||
          overview.runtimeSummary.callbackPending > 0
        ? 'warning'
        : overview.totals.sitesActive === 0
          ? 'inactive'
          : 'ok';
  const statusLabel = t(`status.${statusTone}`, {}, statusTone);
  const statusClasses =
    statusTone === 'error'
      ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200'
      : statusTone === 'warning'
        ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200'
        : statusTone === 'inactive'
          ? 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
          : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200';
  const platformConclusion =
    statusTone === 'error'
      ? t(
          'admin.home_status_error',
          {},
          'Platform callbacks are failing and need operator intervention now.'
        )
      : statusTone === 'warning'
        ? t(
            'admin.home_status_warning',
            {},
            'Platform is serving traffic, but subscriptions or runtime signals need review before they widen.'
          )
        : statusTone === 'inactive'
          ? t(
              'admin.home_status_inactive',
              {},
              'No active sites are currently provisioned. Confirm whether this is intentional before further operator work.'
            )
          : t(
              'admin.home_status_ok',
              {},
              'Platform is nominal. Use this surface to review posture and clear the next operational queue.'
            );
  const primaryMetrics = [
    {
      label: t('admin.active_sites'),
      value: formatInteger(overview.totals.sitesActive),
      detail: t('admin.home_metric_sites', {}, 'Sites currently provisioned for service.'),
    },
    {
      label: t('admin.active_subscriptions'),
      value: formatInteger(overview.totals.subscriptionsActive),
      detail: t('admin.home_metric_subscriptions', {}, 'Subscriptions currently contributing to access.'),
    },
    {
      label: t('admin.running_runs'),
      value: formatInteger(overview.runtimeSummary.runningRuns),
      detail: t('admin.home_metric_running', {}, 'Work already in flight across the hosted runtime.'),
    },
    {
      label: t('admin.guard_events'),
      value: formatInteger(overview.runtimeSummary.guardEvents),
      detail: t('admin.home_metric_guard', {}, 'Recent guard signals that may need follow-up.'),
    },
  ];
  const commercialItems = overview.attentionSubscriptions.slice(0, 2);
  const abnormalSiteItems = Array.from(
    new Map(
      overview.attentionSubscriptions
        .filter((item) => item.siteId)
        .map((item) => [
          item.siteId,
          {
            siteId: item.siteId,
            subscriptionId: item.subscriptionId,
            status: item.status,
            reason: item.reason,
          },
        ])
    ).values()
  ).slice(0, 4);
  const commercialItemsWithHref = commercialItems.map((item) => ({
    ...item,
    href: item.accountId
      ? `/admin/accounts/${item.accountId}`
      : item.siteId
        ? `/admin/sites/${item.siteId}`
        : '/admin/subscriptions',
  }));
  const runtimeRiskItems = operatorWatchItems.filter((item) =>
    item.scope.startsWith('runtime.') || item.scope.startsWith('queue.') || item.scope.startsWith('request.')
  );
  const firstOperatorWatchItem = operatorWatchItems[0];
  const firstOperatorWatchScope = firstOperatorWatchItem?.scope || '';
  const attentionNotes = operatorWatchItems.slice(0, 2);
  const primaryActionHref =
    firstOperatorWatchScope.startsWith('runtime.telemetry')
      ? '/admin/ai-resources?view=diagnostics'
      : firstOperatorWatchScope.startsWith('runtime.') || firstOperatorWatchScope.startsWith('request.')
        ? '/admin/accounts'
        : statusTone === 'error' || commercialItems.length > 0 || overview.expiringSubscriptions.in7Days > 0
          ? '/admin/coverage'
          : '/admin/accounts';
  const primaryActionLabel =
    primaryActionHref === '/admin/ai-resources?view=diagnostics'
      ? t('admin.home_primary_action_runtime_telemetry', {}, 'Inspect runtime telemetry')
      : primaryActionHref === '/admin/coverage'
      ? t('admin.home_primary_action_coverage', {}, 'Review service status')
      : t('admin.home_primary_action_accounts', {}, 'Review customers');
  const secondaryActionHref =
    '/admin/accounts';
  const secondaryActionLabel =
    t('admin.home_secondary_action_accounts', {}, 'Inspect accounts');
  const commercialPanelMetrics = [
    {
      label: t('admin.home_commercial_attention', {}, 'Attention now'),
      value: formatInteger(overview.attentionSubscriptions.length),
      detail: t('admin.home_commercial_attention_detail', {}, 'Subscriptions already calling for operator review.'),
    },
    {
      label: t('admin.home_commercial_expiring', {}, 'Expiring in 7 days'),
      value: formatInteger(overview.expiringSubscriptions.in7Days),
      detail: t(
        'admin.home_commercial_expiring_detail',
        {},
        'Upcoming renewals or lapses that could affect service continuity.'
      ),
    },
    {
      label: t('admin.home_commercial_revenue', {}, 'Usage window cost'),
      value: formatAdminCurrency(overview.recentUsage.cost),
      detail: t('admin.home_commercial_revenue_detail', {}, 'Current usage window cost estimate.'),
    },
  ];
  const recentAuditItems = overview.recentAuditSummary.slice(0, 4);
  const runtimeTelemetryMetrics = [
    {
      label: t('admin.home_hosted_runs', {}, 'Runtime runs'),
      value: formatInteger(overview.hostedModelGovernance.dailyDigest.runs),
      detail: t('admin.home_hosted_runs_detail', {}, 'Runs observed in the runtime telemetry window.'),
    },
    {
      label: t('admin.home_hosted_meter', {}, 'Meter coverage'),
      value: formatPercent(overview.hostedModelGovernance.dailyDigest.meteredRunCoverageRate),
      detail: t('admin.home_hosted_meter_detail', {}, 'Share of runtime runs represented in usage metering.'),
    },
    {
      label: t('admin.home_hosted_provider', {}, 'Provider coverage'),
      value: formatPercent(overview.hostedModelGovernance.dailyDigest.providerCallRunCoverageRate),
      detail: t('admin.home_hosted_provider_detail', {}, 'Share of runtime runs with provider call telemetry.'),
    },
  ];
  const platformCredit = overview.platformCreditSummary;
  const platformCreditMetrics = [
    {
      label: t('admin.platform_credit_total_label', {}, 'AI credits used'),
      value: formatInteger(Math.round(platformCredit.credit.used)),
      detail: platformCredit.credit.estimated
        ? t(
            'admin.platform_credit_total_detail',
            { days: String(platformCredit.windowDays) },
            `Estimated consumption across all accounts in the last ${platformCredit.windowDays} days.`
          )
        : t(
            'admin.platform_credit_total_recorded_detail',
            { days: String(platformCredit.windowDays) },
            `Ledger-recorded consumption across all accounts in the last ${platformCredit.windowDays} days.`
          ),
    },
    {
      label: t('admin.platform_credit_runs_label', {}, 'Runs'),
      value: formatInteger(overview.recentUsage.runs),
      detail: t('admin.platform_credit_runs_detail', {}, 'Hosted run meter events in the same window.'),
    },
    {
      label: t('admin.platform_credit_provider_calls_label', {}, 'Provider calls'),
      value: formatInteger(overview.recentUsage.providerCalls),
      detail: t('admin.platform_credit_provider_calls_detail', {}, 'Provider call meter events in the same window.'),
    },
    {
      label: t('admin.platform_credit_tokens_label', {}, 'Tokens'),
      value: formatInteger(Math.round(overview.recentUsage.tokensTotal)),
      detail: t('admin.platform_credit_tokens_detail', {}, 'Token usage remains an internal guardrail.'),
    },
  ];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.home_title', {}, 'Platform state comes first')}
        description={platformConclusion}
        actions={(
          <>
            <Link href={primaryActionHref} className="btn btn-primary">
              {primaryActionLabel}
            </Link>
            <Link href={secondaryActionHref} className="btn btn-secondary">
              {secondaryActionLabel}
            </Link>
          </>
        )}
        aside={(
          <div className="w-full xl:w-[44rem]">
            <BackofficeMetricStrip
              items={primaryMetrics.map((item) => ({ ...item, detail: undefined, size: 'compact' }))}
              columnsClassName="md:grid-cols-2 xl:grid-cols-4"
            />
          </div>
        )}
      >
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.18em]',
                statusClasses
              )}
            >
              {statusLabel}
            </span>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {overview.generatedAt ? formatDate(overview.generatedAt) : t('common.unknown')}
            </span>
          </div>
          {attentionNotes.length > 0 ? (
            attentionNotes.map((item) => (
              <BackofficeStackCard key={`${item.scope}-${item.title}`}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{item.title}</p>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.reason}</p>
                  </div>
                  <span
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.18em]',
                      operatorSeverityClasses(item.severity)
                    )}
                  >
                    {item.value}
                  </span>
                </div>
              </BackofficeStackCard>
            ))
          ) : (
            <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
              {t('admin.home_attention_clear', {}, 'No immediate watch items are rising from the current overview payload.')}
            </BackofficeStackCard>
          )}
        </div>
      </BackofficePrimaryPanel>

      <BackofficeSectionPanel className="space-y-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.platform_credit_eyebrow', {}, 'Platform consumption')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.platform_credit_title', {}, 'AI credit usage across all accounts')}
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-400">
              {t(
                'admin.platform_credit_desc',
                {},
                'This is the operator-wide consumption view. It uses the same estimated AI credit formula as account detail and keeps token/cost as internal guardrails.'
              )}
            </p>
          </div>
          <span className="rounded-full border border-slate-200 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-600 dark:border-slate-800 dark:text-slate-300">
            {platformCredit.credit.estimated
              ? t('admin.platform_credit_estimated', {}, 'Estimated')
              : t('admin.current_period_only', {}, 'Current period only')}
          </span>
        </div>
        <BackofficeMetricStrip items={platformCreditMetrics} columnsClassName="md:grid-cols-2 xl:grid-cols-4" />
        <div className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-gray-950 dark:text-white">
                  {t('admin.platform_credit_trend_title', {}, 'Credit trend')}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {t(
                    'admin.platform_credit_trend_detail',
                    { days: String(platformCredit.windowDays) },
                    `Compared with the previous ${platformCredit.windowDays}-day window.`
                  )}
                </p>
              </div>
              <span className="rounded-full border border-slate-200 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-600 dark:border-slate-800 dark:text-slate-300">
                {platformCreditTrendLabel(platformCredit.trend.status, platformCredit.trend.deltaPercent, t)}
              </span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('admin.platform_credit_trend_current', {}, 'Current')}
                </p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">
                  {formatInteger(Math.round(platformCredit.trend.currentUsed))}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('admin.platform_credit_trend_previous', {}, 'Previous')}
                </p>
                <p className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">
                  {formatInteger(Math.round(platformCredit.trend.previousUsed))}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t('admin.platform_credit_trend_delta', {}, 'Delta')}
                </p>
                <p className={cn(
                  'mt-1 text-lg font-semibold',
                  platformCredit.trend.delta > 0
                    ? 'text-amber-700 dark:text-amber-300'
                    : platformCredit.trend.delta < 0
                      ? 'text-emerald-700 dark:text-emerald-300'
                      : 'text-slate-950 dark:text-white'
                )}>
                  {platformCredit.trend.delta > 0 ? '+' : ''}
                  {formatInteger(Math.round(platformCredit.trend.delta))}
                </p>
              </div>
            </div>
          </BackofficeStackCard>
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
            <p className="text-sm font-semibold text-gray-950 dark:text-white">
              {t('admin.platform_credit_watch_title', {}, 'Read-only watch items')}
            </p>
            <div className="mt-3 space-y-3">
              {platformCredit.watchItems.length > 0 ? (
                platformCredit.watchItems.map((item) => (
                  <Link
                    key={`${item.code}-${item.metric}-${item.accountId || item.value}`}
                    href={item.href || '/admin/accounts'}
                    className="block rounded-xl border border-slate-200/80 px-3 py-3 text-sm transition hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900/70"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="font-medium text-slate-900 dark:text-slate-100">
                          {platformCreditWatchTitle(item.code, item.title, t)}
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                          {platformCreditWatchDetail(item.code, item.detail, t)}
                        </p>
                      </div>
                      <span className={cn(
                        'shrink-0 rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em]',
                        operatorSeverityClasses(platformCreditWatchSeverity(item.severity))
                      )}>
                        {item.severity}
                      </span>
                    </div>
                  </Link>
                ))
              ) : (
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  {t('admin.platform_credit_watch_empty', {}, 'No credit concentration or comparison-window spike is visible right now.')}
                </p>
              )}
            </div>
          </BackofficeStackCard>
        </div>
        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
            <p className="text-sm font-semibold text-gray-950 dark:text-white">
              {t('admin.platform_credit_breakdown_title', {}, 'Credit breakdown')}
            </p>
            <div className="mt-3 divide-y divide-slate-200 text-sm dark:divide-slate-800">
              {platformCredit.breakdown.length > 0 ? (
                platformCredit.breakdown.map((item) => (
                  <div key={item.key} className="flex items-start justify-between gap-4 py-3">
                    <div>
                      <p className="font-medium text-slate-900 dark:text-slate-100">
                        {platformCreditBreakdownLabel(item.key, item.label, t)}
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {formatInteger(Math.round(item.quantity))} {item.unit}
                      </p>
                    </div>
                    <p className="text-right text-sm font-semibold text-slate-950 dark:text-white">
                      {formatInteger(Math.round(item.credits))}
                    </p>
                  </div>
                ))
              ) : (
                <p className="py-3 text-slate-600 dark:text-slate-300">
                  {t('admin.platform_credit_breakdown_empty', {}, 'No metered credit consumption in the current window.')}
                </p>
              )}
            </div>
          </BackofficeStackCard>
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
            <p className="text-sm font-semibold text-gray-950 dark:text-white">
              {t('admin.platform_credit_top_accounts_title', {}, 'Top accounts')}
            </p>
            <div className="mt-3 space-y-3">
              {platformCredit.topAccounts.length > 0 ? (
                platformCredit.topAccounts.map((item) => (
                  <Link
                    key={item.accountId}
                    href={`/admin/accounts/${encodeURIComponent(item.accountId)}`}
                    className="block rounded-xl border border-slate-200/80 px-3 py-3 text-sm transition hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900/70"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-900 dark:text-slate-100">
                          {item.accountId}
                        </p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {formatInteger(item.runs)} runs · {formatInteger(item.providerCalls)} calls
                        </p>
                      </div>
                      <p className="shrink-0 text-right font-semibold text-slate-950 dark:text-white">
                        {formatInteger(Math.round(item.credits))}
                      </p>
                    </div>
                  </Link>
                ))
              ) : (
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  {t('admin.platform_credit_top_accounts_empty', {}, 'No account-level credit consumption in the current window.')}
                </p>
              )}
            </div>
          </BackofficeStackCard>
        </div>
      </BackofficeSectionPanel>

      <div className="grid gap-5 xl:grid-cols-2">
        <BackofficeSectionPanel className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.home_section_platform', {}, 'Platform health')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.home_section_platform_title', {}, 'Is the platform healthy enough to keep operating?')}
              </h2>
            </div>
            <Link href="/admin/accounts" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
              {t('common.accounts')} →
            </Link>
          </div>
          <div className="space-y-3">
            <BackofficeStackCard>
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t('admin.home_section_platform_followup', {}, 'Follow-up focus')}
              </p>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                {runtimeRiskItems.length > 0
                  ? t(
                    'admin.home_section_platform_runtime_focus',
                    {},
                    'Runtime watch items are active. Start from affected customers, then drill into their sites only when evidence requires it.'
                  )
                  : t(
                      'admin.home_section_platform_sites_focus',
                      {},
                      'Service posture is mainly tied to customer package and subscription continuity. Keep user review as the next detailed read.'
                    )}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t('admin.home_secondary_sites', {}, 'Customer site evidence')}
              </p>
              {abnormalSiteItems.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {abnormalSiteItems.slice(0, 3).map((item) => (
                    <div
                      key={`${item.siteId}-${item.subscriptionId || 'subscription'}`}
                      className="rounded-xl border border-slate-200/70 px-3 py-2 text-sm dark:border-slate-800"
                    >
                      <p className="font-medium text-slate-900 dark:text-slate-100">{item.siteId}</p>
                      <p className="mt-1 text-slate-600 dark:text-slate-300">{item.reason}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  {t('admin.home_secondary_sites_empty', {}, 'No site-level anomalies in the current overview payload.')}
                </p>
              )}
            </BackofficeStackCard>
          </div>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.home_section_commercial', {}, 'Commercial attention')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.home_section_commercial_title', {}, 'Which customers need service follow-up next?')}
              </h2>
            </div>
            <Link href="/admin/coverage" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
              {t('admin.nav_coverage', {}, 'Service status')} →
            </Link>
          </div>
          <BackofficeMetricStrip items={commercialPanelMetrics} columnsClassName="xl:grid-cols-1" />
          {commercialItemsWithHref.length > 0 ? (
            <div className="space-y-3">
              {commercialItemsWithHref.map((item) => (
                <BackofficeStackCard key={item.subscriptionId || `${item.accountId}-${item.siteId}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {item.accountId || item.siteId || item.subscriptionId}
                      </p>
                      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{item.reason}</p>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200">
                        {item.status || t('status.warning')}
                      </span>
                      <Link
                        href={item.href}
                        className="text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200"
                      >
                        {t('admin.home_open_customer_coverage_action', {}, 'Open customer service status')} →
                      </Link>
                    </div>
                  </div>
                </BackofficeStackCard>
              ))}
              {overview.attentionSubscriptions.length > commercialItemsWithHref.length ? (
                <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
                  {t(
                    'admin.home_commercial_attention_more',
                    { count: String(overview.attentionSubscriptions.length - commercialItemsWithHref.length) },
                    `${overview.attentionSubscriptions.length - commercialItemsWithHref.length} more customer coverage items remain in Coverage.`
                  )}
                </BackofficeStackCard>
              ) : null}
            </div>
          ) : (
            <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
              {t('admin.home_section_commercial_empty', {}, 'No subscriptions currently require operator follow-up.')}
            </BackofficeStackCard>
          )}
        </BackofficeSectionPanel>

      </div>

      <BackofficeSectionPanel className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.home_section_runtime', {}, 'Runtime attention')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.home_section_runtime_title', {}, 'Which runtime signals need follow-up?')}
            </h2>
          </div>
          <Link href="/admin/ai-resources?view=diagnostics" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
            {t('admin.home_secondary_action_runtime', {}, 'Inspect runtime sources')} →
          </Link>
        </div>
        <BackofficeMetricStrip items={runtimeTelemetryMetrics} columnsClassName="md:grid-cols-3" />
        {overview.hostedModelGovernance.alerts.length > 0 ? (
          <div className="grid gap-3 xl:grid-cols-2">
            {overview.hostedModelGovernance.alerts.slice(0, 2).map((alert) => (
              <BackofficeStackCard key={alert.code}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {alert.title}
                    </p>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                      {alert.summary}
                    </p>
                    {alert.capabilities.length > 0 ? (
                      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        {alert.capabilities.slice(0, 3).join(', ')}
                      </p>
                    ) : null}
                  </div>
                  <span
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.18em]',
                      alert.severity === 'error'
                        ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200'
                        : 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200'
                    )}
                  >
                    {formatInteger(alert.count)}
                  </span>
                </div>
              </BackofficeStackCard>
            ))}
          </div>
        ) : (
          <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
            {overview.hostedModelGovernance.summary ||
              t('admin.home_hosted_empty', {}, 'No runtime telemetry alerts are active today.')}
          </BackofficeStackCard>
        )}
      </BackofficeSectionPanel>

      <details className="rounded-2xl border border-dashed border-slate-200 px-5 py-4 dark:border-slate-800">
        <summary className="cursor-pointer list-none text-sm font-semibold text-slate-700 hover:text-slate-950 dark:text-slate-300 dark:hover:text-white">
          {t('admin.home_secondary_title', {}, 'Supporting evidence')}
          <span className="ml-3 font-normal text-slate-500 dark:text-slate-400">
            {t('admin.home_secondary_details', {}, 'Audit and low-frequency context')}
          </span>
        </summary>
        <div className="mt-4">
          <BackofficeStackCard className="space-y-3">
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {t('admin.home_secondary_audit', {}, 'Recent audit summary')}
            </p>
            {recentAuditItems.length > 0 ? (
              recentAuditItems.map((item) => (
                <div
                  key={`${item.eventKind}-${item.outcome}-${item.lastSeenAt}`}
                  className="rounded-xl border border-slate-200/70 px-3 py-2 text-sm dark:border-slate-800"
                >
                  <p className="font-medium text-slate-900 dark:text-slate-100">
                    {item.eventKind || t('common.unknown')} / {item.outcome || t('common.unknown')}
                  </p>
                  <p className="mt-1 text-slate-600 dark:text-slate-300">
                    {`${formatInteger(item.count)} ${t('admin.home_secondary_audit_events', {}, 'recent events')}`} ·{' '}
                    {item.lastSeenAt ? formatDate(item.lastSeenAt) : t('common.unknown')}
                  </p>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {t('admin.home_secondary_audit_empty', {}, 'No recent audit summary items are currently available.')}
              </p>
            )}
          </BackofficeStackCard>
        </div>
      </details>
    </BackofficePageStack>
  );
}

export default function AdminOverviewPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminOverviewContent />
    </Suspense>
  );
}
