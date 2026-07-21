'use client';

import React, { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { formatAdminCurrency } from '@/lib/currency';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { buildAdminOperatorWatchItems, operatorSeverityClasses } from '@/lib/admin-operator-signals';
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  BackofficeMetricStrip,
  BackofficeDiagnosticNotice,
  BackofficeLayer,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { AdminWorkspacePage } from '@/components/admin/AdminWorkspace';

const adminOverviewClient = createApiClient({ idempotencyPrefix: 'admin_overview' });

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

function overviewRuntimeAlertTitle(
  alert: AdminOverview['runtimeTelemetry']['alerts'][number] | undefined,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  if (!alert) return '';
  const known: Record<string, [string, string]> = {
    'hosted_model.provider_errors': ['admin.troubleshooting.issue_provider_errors', 'Provider call errors'],
    'hosted_model.failed_runs': ['admin.troubleshooting.issue_runtime_failed', 'Runtime runs failed'],
    'hosted_model.provider_call_gap': ['admin.troubleshooting.issue_provider_gap', 'Provider call coverage gap'],
  };
  const copy = known[alert.code];
  return copy ? t(copy[0], {}, copy[1]) : alert.title || alert.code;
}

function overviewRuntimeAlertSummary(
  alert: AdminOverview['runtimeTelemetry']['alerts'][number] | undefined,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  if (!alert) return '';
  const known: Record<string, [string, string]> = {
    'hosted_model.provider_errors': ['admin.troubleshooting.issue_provider_errors_desc', 'Provider calls are returning errors in the current telemetry window.'],
    'hosted_model.failed_runs': ['admin.troubleshooting.issue_runtime_failed_desc', 'Runtime runs are failing before or during provider execution.'],
    'hosted_model.provider_call_gap': ['admin.troubleshooting.issue_provider_gap_desc', 'Some runtime runs do not have matching provider-call telemetry.'],
  };
  const copy = known[alert.code];
  return copy ? t(copy[0], {}, copy[1]) : alert.summary;
}

function AdminOverviewContent() {
  const { t } = useLocale();
  const router = useRouter();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [supportQuery, setSupportQuery] = useState('');
  const requestControllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);

  const loadOverview = useCallback(async () => {
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const sequence = ++requestSequenceRef.current;
    setIsLoading(true);
    setError(null);
    const timeout = globalThis.setTimeout(() => controller.abort(), 12000);

    try {
      const overviewResponse = await adminOverviewClient.request<unknown>('/api/admin/overview', {
        signal: controller.signal,
      });
      if (sequence === requestSequenceRef.current) {
        setOverview(normalizeOverview(overviewResponse.data));
      }
    } catch (err) {
      if (sequence === requestSequenceRef.current) {
        setError(resolveUiErrorMessage(err, t('error.failed_load')));
      }
    } finally {
      globalThis.clearTimeout(timeout);
      if (sequence === requestSequenceRef.current) {
        requestControllerRef.current = null;
        setIsLoading(false);
      }
    }
  }, [t]);

  useEffect(() => {
    void loadOverview();
    return () => requestControllerRef.current?.abort();
  }, [loadOverview]);

  if (isLoading && !overview) {
    return (
      <AdminWorkspacePage>
        <BackofficeLayer
          eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
          title={t('admin.home_title', {}, 'Platform state comes first')}
          description={t('admin.home_loading_desc', {}, 'Loading the current platform conclusion and operator queues.')}
        />
        <LoadingFallback />
      </AdminWorkspacePage>
    );
  }

  if (error && !overview) {
    return (
      <AdminWorkspacePage>
        <BackofficeLayer
          eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
          title={t('admin.home_title', {}, 'Platform state comes first')}
          description={t('admin.home_error_desc', {}, 'The platform overview could not be loaded. No operator action has been performed.')}
        />
        <BackofficeDiagnosticNotice message={error} retryLabel={t('common.retry')} onRetry={() => void loadOverview()} />
      </AdminWorkspacePage>
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
      firstAlertTitle: overviewRuntimeAlertTitle(overview.runtimeTelemetry.alerts[0], t),
      firstAlertSummary: overviewRuntimeAlertSummary(overview.runtimeTelemetry.alerts[0], t),
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
      label: t('admin.home_evidence_provider_calls', {}, 'Provider calls'),
      value: formatInteger(overview.recentUsage.providerCalls),
      detail: t('admin.home_evidence_provider_calls_desc', {}, 'Observed provider-call records in the same window.'),
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
  return (
    <AdminWorkspacePage>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.home_title', {}, 'Platform state comes first')}
        description={platformConclusion}
        className="rounded-[1.2rem] shadow-none"
        contentClassName="px-5 py-5 md:px-6 md:py-5"
        actions={(
          <Link href={primaryActionHref} className="btn btn-primary">
            {primaryActionLabel}
          </Link>
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

      <BackofficeSectionPanel className="space-y-4" data-ui="admin-overview-destinations">
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
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {quickLinks.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  data-ui="admin-overview-destination"
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
      </BackofficeSectionPanel>

      <details className="rounded-2xl border border-slate-200/80 bg-white/60 dark:border-slate-800 dark:bg-slate-950/30">
        <summary className="cursor-pointer px-5 py-4 text-sm font-semibold text-slate-800 hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-900/60">
          {t('admin.home_extended_evidence_title', {}, 'Platform usage and extended evidence')}
          <span className="ml-2 text-xs font-normal text-slate-500 dark:text-slate-400">
            {t('admin.home_extended_evidence_desc', {}, 'Open when the first-screen conclusion is not enough.')}
          </span>
        </summary>
        <div className="space-y-5 border-t border-slate-200/80 p-4 dark:border-slate-800">
      <BackofficeSectionPanel className="space-y-4">
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
          <span className={cn('rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.18em]', statusClasses)}>
            {statusLabel}
          </span>
        </div>
        <BackofficeMetricStrip items={evidenceWindowMetrics} columnsClassName="grid-cols-2 md:grid-cols-4" />
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {runtimeStatusItems.map((item) => (
            <div key={item.label} className="rounded-xl border border-slate-200/80 bg-slate-50/70 px-3 py-2.5 dark:border-slate-800 dark:bg-slate-950/35" title={item.detail}>
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{item.label}</span>
                <span className="text-sm font-semibold text-slate-950 dark:text-white">{item.value}</span>
              </div>
            </div>
          ))}
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
                      {overviewRuntimeAlertTitle(alert, t)}
                    </p>
                    <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                      {overviewRuntimeAlertSummary(alert, t)}
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

        </div>
      </details>

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
