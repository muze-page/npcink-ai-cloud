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
    memberships: number;
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

  return {
    generatedAt: String(raw?.generated_at ?? ''),
    totals: {
      accounts: Number(counts.accounts_total ?? 0),
      memberships: Number(counts.memberships_active ?? 0),
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
  };
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
    },
  });

  const statusTone =
    overview.runtimeSummary.callbackFailed > 0
      ? 'error'
      : overview.attentionSubscriptions.length > 0 ||
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
    item.scope.startsWith('runtime.') || item.scope.startsWith('queue.') || item.scope.startsWith('guard.')
  );
  const attentionNotes = operatorWatchItems.slice(0, 2);
  const primaryActionHref =
    statusTone === 'error' || commercialItems.length > 0 || overview.expiringSubscriptions.in7Days > 0
      ? '/admin/subscriptions'
      : '/admin/sites';
  const primaryActionLabel =
    primaryActionHref === '/admin/subscriptions'
      ? t('admin.home_primary_action_coverage', {}, 'Review coverage')
      : t('admin.home_primary_action_sites', {}, 'Review sites');
  const secondaryActionHref =
    statusTone === 'error' || runtimeRiskItems.length > 0 ? '/admin/sites' : '/admin/accounts';
  const secondaryActionLabel =
    secondaryActionHref === '/admin/sites'
      ? t('admin.home_secondary_action_sites', {}, 'Inspect sites')
      : t('admin.home_secondary_action_accounts', {}, 'Inspect accounts');
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
            <Link href="/admin/sites" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
              {t('common.sites')} →
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
                    'Runtime watch items are already active. Keep the next inspection on affected sites and coverage continuity first.'
                  )
                  : t(
                      'admin.home_section_platform_sites_focus',
                      {},
                      'Service posture is mainly tied to site and subscription continuity. Keep site inspection as the next detailed read.'
                    )}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t('admin.home_secondary_sites', {}, 'Sites needing inspection')}
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
                {t('admin.home_section_commercial_title', {}, 'Which customers need coverage follow-up next?')}
              </h2>
            </div>
            <Link href="/admin/subscriptions" className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
              {t('admin.nav_coverage', {}, 'Coverage')} →
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
                        {t('admin.home_open_customer_coverage_action', {}, 'Open customer coverage')} →
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
              {t('admin.home_secondary_details', {}, 'Secondary detail')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.home_secondary_title', {}, 'Context that supports the main operator read')}
            </h2>
          </div>
        </div>
        <div>
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
      </BackofficeSectionPanel>
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
