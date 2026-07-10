'use client';

import React, { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { formatAdminCurrency } from '@/lib/currency';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { buildAdminOperatorWatchItems, operatorSeverityClasses } from '@/lib/admin-operator-signals';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  BackofficeMetricStrip,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { AdminWorkspacePage, AdminWorkspaceSplit } from '@/components/admin/AdminWorkspace';

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
  runtimeTelemetry: {
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
  const runtimeTelemetry = raw?.runtime_telemetry ?? {};
  const runtimeTelemetryAlertSummary = runtimeTelemetry?.alert_summary ?? {};
  const runtimeTelemetryDailyDigest = runtimeTelemetryAlertSummary?.daily_digest ?? {};
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
    runtimeTelemetry: {
      status: String(runtimeTelemetryAlertSummary.status ?? 'inactive'),
      summary: String(runtimeTelemetryAlertSummary.summary ?? ''),
      alertCount: Number(runtimeTelemetryAlertSummary.alert_count ?? 0),
      href: String(runtimeTelemetryAlertSummary.href ?? '/admin/troubleshooting') || '/admin/troubleshooting',
      dailyDigest: {
        runs: Number(runtimeTelemetryDailyDigest.runs ?? 0),
        providerCalls: Number(runtimeTelemetryDailyDigest.provider_calls ?? 0),
        meterEvents: Number(runtimeTelemetryDailyDigest.meter_events ?? 0),
        meteredRunCoverageRate: Number(runtimeTelemetryDailyDigest.metered_run_coverage_rate ?? 0),
        providerCallRunCoverageRate: Number(runtimeTelemetryDailyDigest.provider_call_run_coverage_rate ?? 0),
        unmeteredRunCount: Number(runtimeTelemetryDailyDigest.unmetered_run_count ?? 0),
        runsWithoutProviderCallCount: Number(runtimeTelemetryDailyDigest.runs_without_provider_call_count ?? 0),
      },
      alerts: Array.isArray(runtimeTelemetryAlertSummary.alerts)
        ? runtimeTelemetryAlertSummary.alerts.map((item: any) => ({
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

function coverageToneClass(value: number): string {
  if (value >= 0.95) {
    return 'text-emerald-700 dark:text-emerald-300';
  }
  if (value >= 0.8) {
    return 'text-amber-700 dark:text-amber-300';
  }
  return 'text-red-700 dark:text-red-300';
}

function buildAdminLookupHref(path: string, query: string): string {
  const trimmed = query.trim();
  if (!trimmed) {
    return path;
  }
  const params = new URLSearchParams({ q: trimmed });
  return `${path}?${params.toString()}`;
}

function AdminOverviewContent() {
  const { t } = useLocale();
  const router = useRouter();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [supportQuery, setSupportQuery] = useState('');

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
    runtimeTelemetry: {
      status: overview.runtimeTelemetry.status,
      alertCount: overview.runtimeTelemetry.alertCount,
      firstAlertTitle: overview.runtimeTelemetry.alerts[0]?.title || '',
      firstAlertSummary: overview.runtimeTelemetry.alerts[0]?.summary || '',
      summary: overview.runtimeTelemetry.summary,
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
      runtimeTelemetryTitle: t('admin.watch_runtime_telemetry_title', {}, 'Runtime telemetry needs review'),
      runtimeTelemetryReason: t(
        'admin.watch_runtime_telemetry_reason',
        {},
        'Runtime telemetry coverage needs review before traffic expands.'
      ),
    },
  });

  const statusTone =
    overview.runtimeSummary.callbackFailed > 0
      ? 'error'
      : overview.runtimeTelemetry.status === 'error'
        ? 'error'
      : overview.attentionSubscriptions.length > 0 ||
          overview.runtimeTelemetry.status === 'warning' ||
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
      label: t('admin.platform_credit_total_label', {}, 'AI credits used'),
      value: formatInteger(Math.round(overview.platformCreditSummary.credit.used)),
      detail: t('admin.home_metric_credit', {}, 'Current evidence-window AI credit consumption.'),
    },
    {
      label: t('admin.home_runtime_runs', {}, 'Runtime runs'),
      value: formatInteger(overview.recentUsage.runs),
      detail: t('admin.home_metric_runtime_runs', {}, 'Hosted runtime executions in the current evidence window.'),
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
      ? '/admin/troubleshooting'
      : firstOperatorWatchScope.startsWith('runtime.') || firstOperatorWatchScope.startsWith('request.')
        ? '/admin/accounts'
        : statusTone === 'error' || commercialItems.length > 0 || overview.expiringSubscriptions.in7Days > 0
          ? '/admin/coverage'
          : '/admin/accounts';
  const primaryActionLabel =
    primaryActionHref === '/admin/troubleshooting'
      ? t('admin.home_primary_action_runtime_telemetry', {}, 'Inspect runtime telemetry')
      : primaryActionHref === '/admin/coverage'
      ? t('admin.home_primary_action_coverage', {}, 'Review service status')
      : t('admin.home_primary_action_accounts', {}, 'Review customers');
  const secondaryActionHref =
    '/admin/accounts';
  const secondaryActionLabel =
    t('admin.home_secondary_action_accounts', {}, 'Inspect accounts');
  const supportLookupAccountHref = buildAdminLookupHref('/admin/accounts', supportQuery);
  const supportLookupPortalUserHref = buildAdminLookupHref('/admin/portal-users', supportQuery);
  const quickLinks = [
    {
      href: '/admin/support-requests',
      label: t('admin.home_quick_tickets', {}, 'Tickets'),
      detail: t('admin.home_quick_tickets_desc', {}, 'Portal-submitted billing, payment, site, usage, and account issues.'),
    },
    {
      href: '/admin/coverage',
      label: t('admin.home_quick_service_status', {}, 'Service status'),
      detail: t('admin.home_quick_service_status_desc', {}, 'Customer coverage, package, and subscription pressure.'),
    },
    {
      href: '/admin/accounts',
      label: t('admin.home_quick_customers', {}, 'Customers'),
      detail: t('admin.home_quick_customers_desc', {}, 'Account, site, package, and support context.'),
    },
    {
      href: '/admin/troubleshooting',
      label: t('admin.home_quick_runtime_diagnostics', {}, 'Runtime diagnostics'),
      detail: t(
        'admin.home_quick_runtime_diagnostics_desc',
        {},
        'Runtime, plugin, media, vector, and feedback evidence.'
      ),
    },
    {
      href: '/admin/ai-resources',
      label: t('admin.home_quick_providers', {}, 'Providers'),
      detail: t('admin.home_quick_providers_desc', {}, 'Cloud runtime suppliers and credential readiness.'),
    },
    {
      href: '/admin/service-settings',
      label: t('admin.home_quick_service_settings', {}, 'Service settings'),
      detail: t('admin.home_quick_service_settings_desc', {}, 'Portal login, delivery, and Cloud-owned service configuration.'),
    },
  ];
  const evidenceWindowMetrics = [
    {
      label: t('admin.home_evidence_runs', {}, 'Runs'),
      value: formatInteger(overview.recentUsage.runs),
      detail: t('admin.home_evidence_runs_desc', {}, 'Hosted executions in the current overview window.'),
    },
    {
      label: t('admin.home_evidence_provider_calls', {}, 'Provider calls'),
      value: formatInteger(overview.recentUsage.providerCalls),
      detail: t('admin.home_evidence_provider_calls_desc', {}, 'Observed provider-call records in the same window.'),
    },
    {
      label: t('admin.home_evidence_cost', {}, 'Cost'),
      value: formatAdminCurrency(overview.recentUsage.cost),
      detail: t('admin.home_evidence_cost_desc', {}, 'Internal estimated cost, not a customer wallet balance.'),
      size: 'compact' as const,
    },
    {
      label: t('admin.home_evidence_meter_coverage', {}, 'Meter coverage'),
      value: formatPercent(overview.runtimeTelemetry.dailyDigest.meteredRunCoverageRate),
      detail: t('admin.home_evidence_meter_coverage_desc', {}, 'Share of runtime runs represented in usage metering.'),
      toneClassName: coverageToneClass(overview.runtimeTelemetry.dailyDigest.meteredRunCoverageRate),
    },
  ];
  const runtimeStatusItems = [
    {
      label: t('admin.home_runtime_queued', {}, 'Queued'),
      value: formatInteger(overview.runtimeSummary.queuedRuns),
      detail: t('admin.home_runtime_queued_detail', {}, 'Runs waiting for hosted execution.'),
    },
    {
      label: t('admin.running_runs', {}, 'Running'),
      value: formatInteger(overview.runtimeSummary.runningRuns),
      detail: t('admin.home_metric_running', {}, 'Work already in flight across the hosted runtime.'),
    },
    {
      label: t('admin.home_runtime_pending', {}, 'Callback pending'),
      value: formatInteger(overview.runtimeSummary.callbackPending),
      detail: t('admin.home_runtime_pending_detail', {}, 'Terminal callbacks waiting for delivery.'),
    },
    {
      label: t('admin.guard_events', {}, 'Guard events'),
      value: formatInteger(overview.runtimeSummary.guardEvents),
      detail: t('admin.home_metric_guard', {}, 'Recent guard signals that may need follow-up.'),
    },
  ];
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
      label: t('admin.home_runtime_telemetry_runs', {}, 'Runtime runs'),
      value: formatInteger(overview.runtimeTelemetry.dailyDigest.runs),
      detail: t('admin.home_runtime_telemetry_runs_detail', {}, 'Runs observed in the runtime telemetry window.'),
    },
    {
      label: t('admin.home_runtime_telemetry_meter', {}, 'Meter coverage'),
      value: formatPercent(overview.runtimeTelemetry.dailyDigest.meteredRunCoverageRate),
      detail: t('admin.home_runtime_telemetry_meter_detail', {}, 'Share of runtime runs represented in usage metering.'),
    },
    {
      label: t('admin.home_runtime_telemetry_provider', {}, 'Provider coverage'),
      value: formatPercent(overview.runtimeTelemetry.dailyDigest.providerCallRunCoverageRate),
      detail: t('admin.home_runtime_telemetry_provider_detail', {}, 'Share of runtime runs with provider call telemetry.'),
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
    <AdminWorkspacePage>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.home_title', {}, 'Platform state comes first')}
        description={platformConclusion}
        className="rounded-[1.2rem] shadow-none"
        contentClassName="px-5 py-5 md:px-6 md:py-5"
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

      <AdminWorkspaceSplit
        primary={(
          <>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.home_quick_actions_eyebrow', {}, 'Operator console')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.home_quick_actions_title', {}, 'Handle queues first')}
                </h2>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-400">
                  {t(
                    'admin.home_quick_actions_desc',
                    {},
                    'These entries only open existing Cloud service-plane detail surfaces. They do not edit WordPress, prompts, routers, abilities, or workflows.'
                  )}
                </p>
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {quickLinks.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="group block rounded-2xl border border-slate-200/80 bg-white/80 px-4 py-3.5 text-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:bg-blue-50/70 hover:shadow-sm dark:border-slate-800 dark:bg-slate-950/45 dark:hover:border-blue-900/70 dark:hover:bg-blue-950/25"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold text-slate-950 dark:text-white">{item.label}</p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                        {item.detail}
                      </p>
                    </div>
                    <span className="shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-blue-600 dark:text-slate-500 dark:group-hover:text-blue-300">
                      →
                    </span>
                  </div>
                </Link>
              ))}
            </div>
            <BackofficeStackCard className="mt-4 bg-white/80 dark:bg-slate-950/45" data-admin-support-lookup>
              <div className="grid gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {t('admin.home_support_lookup_eyebrow', {}, 'Support lookup')}
                  </p>
                  <h3 className="mt-2 text-base font-semibold text-slate-950 dark:text-white">
                    {t('admin.home_support_lookup_title', {}, 'Find the customer record first')}
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {t(
                      'admin.home_support_lookup_desc',
                      {},
                      'Search by email, customer, site, or domain. Start from the customer or Portal user record, then open service status only when coverage needs follow-up.'
                    )}
                  </p>
                </div>
                <form
                  className="flex w-full flex-col gap-2 sm:flex-row"
                  onSubmit={(event) => {
                    event.preventDefault();
                    router.push(supportLookupAccountHref);
                  }}
                >
                  <label className="sr-only" htmlFor="admin-support-lookup-query">
                    {t('admin.home_support_lookup_label', {}, 'Support lookup query')}
                  </label>
                  <input
                    id="admin-support-lookup-query"
                    type="search"
                    value={supportQuery}
                    onChange={(event) => setSupportQuery(event.target.value)}
                    placeholder={t('admin.home_support_lookup_placeholder', {}, 'Email, customer, site, or domain')}
                    className="min-h-11 min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100 dark:border-slate-700 dark:bg-slate-950 dark:text-white dark:focus:border-blue-500 dark:focus:ring-blue-950"
                  />
                  <div className="flex shrink-0 gap-2">
                    <Link href={supportLookupAccountHref} className="btn btn-primary btn-sm whitespace-nowrap">
                      {t('admin.home_support_lookup_accounts', {}, 'Find customer')}
                    </Link>
                    <Link href={supportLookupPortalUserHref} className="btn btn-secondary btn-sm whitespace-nowrap">
                      {t('admin.home_support_lookup_portal_users', {}, 'Find user')}
                    </Link>
                  </div>
                </form>
              </div>
              <div className="mt-4 flex flex-wrap gap-2 text-xs">
                <Link
                  href="/admin/coverage"
                  className="rounded-full border border-slate-200 px-3 py-1.5 font-medium text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-800 dark:text-slate-300 dark:hover:border-blue-900 dark:hover:bg-blue-950/30 dark:hover:text-blue-300"
                >
                  {t('admin.home_support_lookup_coverage', {}, 'Open service status')}
                </Link>
                <Link
                  href="/admin/troubleshooting"
                  className="rounded-full border border-slate-200 px-3 py-1.5 font-medium text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-800 dark:text-slate-300 dark:hover:border-blue-900 dark:hover:bg-blue-950/30 dark:hover:text-blue-300"
                >
                  {t('admin.home_support_lookup_diagnostics', {}, 'Open diagnostics')}
                </Link>
              </div>
            </BackofficeStackCard>
          </>
        )}
        inspector={(
          <>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.home_evidence_window_eyebrow', {}, 'Evidence window')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.home_evidence_window_title', {}, 'Runtime and usage snapshot')}
                </h2>
                <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-400">
                  {t(
                    'admin.home_evidence_window_desc',
                    { days: String(overview.recentUsage.windowDays) },
                    `Current ${overview.recentUsage.windowDays}-day overview signals from existing runtime and metering evidence.`
                  )}
                </p>
              </div>
              <span
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.18em]',
                  statusClasses
                )}
              >
                {statusLabel}
              </span>
            </div>
            <BackofficeMetricStrip
              items={evidenceWindowMetrics}
              columnsClassName="mt-4 grid-cols-2 md:grid-cols-2 xl:grid-cols-2"
            />
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              {runtimeStatusItems.map((item) => (
                <div
                  key={item.label}
                  className="rounded-xl border border-slate-200/80 bg-slate-50/70 px-3 py-2.5 dark:border-slate-800 dark:bg-slate-950/35"
                  title={item.detail}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</span>
                    <span className="text-sm font-semibold text-slate-950 dark:text-white">{item.value}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      />

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
          <Link href="/admin/troubleshooting" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
            {t('admin.home_secondary_action_runtime', {}, 'Inspect runtime sources')} →
          </Link>
        </div>
        <BackofficeMetricStrip items={runtimeTelemetryMetrics} columnsClassName="md:grid-cols-3" />
        {overview.runtimeTelemetry.alerts.length > 0 ? (
          <div className="grid gap-3 xl:grid-cols-2">
            {overview.runtimeTelemetry.alerts.slice(0, 2).map((alert) => (
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
            {overview.runtimeTelemetry.summary ||
              t('admin.home_runtime_telemetry_empty', {}, 'No runtime telemetry alerts are active today.')}
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
    </AdminWorkspacePage>
  );
}

export default function AdminOverviewPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminOverviewContent />
    </Suspense>
  );
}
