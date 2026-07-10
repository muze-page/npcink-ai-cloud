'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { UsageBarChart } from '@/components/ui/UsageChart';
import { useLocale } from '@/contexts/LocaleContext';
import { useRetry } from '@/hooks/useRetry';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type Entitlements,
  type PortalCreditLedgerPayload,
  type PortalUsageSummaryPayload,
  type PortalUsageWindow,
} from '@/lib/portal-client';
import {
  DEFAULT_PORTAL_CURRENCY,
  formatPortalCurrency,
} from '@/lib/currency';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatCompactNumber, formatDate, formatNumber } from '@/lib/utils';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';

function toChartPoint(
  window: PortalUsageWindow | undefined,
  label: string,
): { date: string; requests: number; tokens: number; cost: number } | null {
  if (!window) return null;
  return {
    date: label,
    requests: Number(window.runs_total || 0),
    tokens: Number(window.tokens_in_total || 0) + Number(window.tokens_out_total || 0),
    cost: Number(window.cost_total || 0),
  };
}

function formatQuotaValue(value: unknown, unlimited = false, unlimitedLabel = 'Unlimited'): string {
  if (unlimited) return unlimitedLabel;
  return formatNumber(Math.round(Number(value || 0)));
}

function getCreditDeltaValue(entry: PortalCreditLedgerPayload['items'][number]): number {
  return Number(entry.net_credit_delta ?? entry.credit_delta ?? 0);
}

function quotaStatusTone(status: string | undefined): 'ok' | 'warning' | 'error' {
  if (status === 'limited') return 'error';
  if (status === 'near_limit') return 'warning';
  return 'ok';
}

function portalCreditBreakdownLabel(
  key: string,
  fallback: string,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  const labels: Record<string, string> = {
    runs: t('portal.usage.breakdown_runs', {}, 'Hosted runs'),
    tokens_total: t('portal.usage.breakdown_tokens', {}, 'Point usage'),
    web_search: t('portal.usage.breakdown_search', {}, 'Search'),
    image_recommendation: t('portal.usage.breakdown_image', {}, 'Image recommendation'),
    provider_calls_other: t('portal.usage.breakdown_provider_other', {}, 'Other service usage'),
    vector_documents: t('portal.usage.breakdown_vector_documents', {}, 'Knowledge articles'),
    vector_chunks: t('portal.usage.breakdown_vector_chunks', {}, 'Knowledge pieces'),
  };
  return labels[key] || fallback || key;
}

function PortalUsageContent() {
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated } = useSession();
  const [usage, setUsage] = useState<PortalUsageSummaryPayload | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [creditLedger, setCreditLedger] = useState<PortalCreditLedgerPayload | null>(null);

  const loadBundle = useCallback(async () => {
    const bundle = await portalClient.getUsageBundle();
    setUsage(bundle.usage);
    setEntitlements(bundle.entitlements);
    setCreditLedger(bundle.creditLedger);
  }, []);

  const { execute, isLoading: retryLoading, error: retryError, retry } = useRetry(loadBundle, {
    maxRetries: 2,
    initialDelay: 800,
    backoffMultiplier: 2,
  });

  useEffect(() => {
    if (!session || !isAuthenticated) {
      return;
    }
    void execute();
  }, [isAuthenticated, session, execute]);

  const toFinite = (value: unknown): number => {
    const numeric = Number(value || 0);
    return Number.isFinite(numeric) ? numeric : 0;
  };

  const errorMessage = retryError
    ? formatPortalErrorMessage(retryError, t, t('error.failed_load'))
    : null;

  const chartData = useMemo(() => {
    const points = [
      toChartPoint(usage?.windows?.today, t('portal.usage.window_today', {}, 'Today')),
      toChartPoint(usage?.windows?.rolling_24h, t('portal.usage.window_rolling_24h', {}, '24h')),
    ].filter(Boolean) as { date: string; requests: number; tokens: number; cost: number }[];
    return points;
  }, [usage, t]);

  if (sessionLoading || retryLoading) {
    return <PortalLoadingState message={t('common.loading')} />;
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('auth.not_signed_in')}
        description={t('auth.please_sign_in')}
        actionLabel={t('nav.sign_in')}
      />
    );
  }

  if (errorMessage) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={errorMessage}
        retryLabel={t('common.retry')}
        onRetry={() => void retry()}
      />
    );
  }

  const usageWindow = usage?.windows?.rolling_24h || usage?.windows?.today || null;
  const budgetState = entitlements?.budget_state || {};
  const overBudget = Object.values(budgetState).some((entry) => Boolean(entry?.over_limit));
  const subscription = entitlements?.subscription || null;
  const quotaSummary = entitlements?.quota_summary || null;
  const creditLedgerItems = creditLedger?.items || [];
  const creditLedgerTotal = Number(
    creditLedger?.summary?.net_used_credits ?? creditLedger?.summary?.total_credits ?? 0
  );
  const creditLedgerCount = Number(creditLedger?.pagination?.total ?? creditLedger?.summary?.entry_count ?? 0);
  const formatPreferredCurrency = (value: number) => formatPortalCurrency(value, { to: DEFAULT_PORTAL_CURRENCY });
  const chartTotals = chartData.reduce(
    (totals, item) => ({
      requests: totals.requests + toFinite(item.requests),
      tokens: totals.tokens + toFinite(item.tokens),
      cost: totals.cost + toFinite(item.cost),
    }),
    { requests: 0, tokens: 0, cost: 0 }
  );
  const currentPeriodStart =
    entitlements?.period_start_at ||
    subscription?.current_period_start_at ||
    subscription?.current_period_start ||
    session.current_subscription?.current_period_start ||
    '';
  const currentPeriodEnd =
    entitlements?.period_end_at ||
    subscription?.current_period_end_at ||
    subscription?.current_period_end ||
    session.current_subscription?.current_period_end ||
    '';
  const currentPeriodRange =
    currentPeriodStart && currentPeriodEnd
      ? `${formatDate(currentPeriodStart)} - ${formatDate(currentPeriodEnd)}`
      : '';
  const formatCreditPoints = (value: number) =>
    t('portal.usage.credit_points_value', { count: formatNumber(Math.abs(Math.round(value))) }, '{{count}} points');
  const isCustomerServiceLedgerEntry = (entry: PortalCreditLedgerPayload['items'][number]) =>
    ['runs', 'tokens_total', 'tokens'].includes(String(entry.source_type || '')) ||
    String(entry.category_label || '').toLowerCase() === 'ai usage';
  const formatLedgerFeatureText = (
    entry: PortalCreditLedgerPayload['items'][number],
    field: 'title' | 'detail'
  ) => {
    const featureKey = String(entry.feature_key || '').trim();
    const fallback =
      field === 'title'
        ? String(entry.feature_label || '').trim()
        : String(entry.feature_detail || '').trim();
    if (!featureKey) {
      return fallback;
    }
    return t(`portal.usage.credit_ledger_feature_${featureKey}_${field}`, {}, fallback);
  };
  const formatLedgerTitle = (entry: PortalCreditLedgerPayload['items'][number]) => {
    const featureTitle = formatLedgerFeatureText(entry, 'title');
    if (featureTitle) {
      return featureTitle;
    }
    if (isCustomerServiceLedgerEntry(entry)) {
      return t('portal.usage.credit_ledger_ai_service_title', {}, 'AI service usage');
    }
    const creditDelta = getCreditDeltaValue(entry);
    if (creditDelta > 0) {
      return t('portal.usage.credit_ledger_credit_added_title', {}, 'Points added');
    }
    return entry.category_label || portalCreditBreakdownLabel(entry.source_type, '', t);
  };
  const formatLedgerDescription = (entry: PortalCreditLedgerPayload['items'][number]) => {
    const creditDelta = getCreditDeltaValue(entry);
    if (creditDelta < 0) {
      const featureDetail = formatLedgerFeatureText(entry, 'detail');
      if (featureDetail) {
        return `${featureDetail} ${t(
          'portal.usage.credit_ledger_service_used_suffix',
          { credits: formatCreditPoints(creditDelta) },
          'This time used {{credits}}.'
        )}`;
      }
      return t(
        'portal.usage.credit_ledger_service_used_desc',
        { credits: formatCreditPoints(creditDelta) },
        'This service used {{credits}}.'
      );
    }
    if (creditDelta > 0) {
      return t(
        'portal.usage.credit_ledger_credit_added_desc',
        { credits: formatCreditPoints(creditDelta) },
        '{{credits}} were added to this package.'
      );
    }
    return t('portal.usage.credit_ledger_default_event', {}, 'Usage event');
  };
  const formatLedgerCreditDelta = (entry: PortalCreditLedgerPayload['items'][number]) => {
    const creditDelta = getCreditDeltaValue(entry);
    if (creditDelta < 0) {
      return t(
        'portal.usage.credit_ledger_credit_deducted',
        { credits: formatCreditPoints(creditDelta) },
        'Deducted {{credits}}'
      );
    }
    if (creditDelta > 0) {
      return t(
        'portal.usage.credit_ledger_credit_added',
        { credits: formatCreditPoints(creditDelta) },
        'Added {{credits}}'
      );
    }
    return formatCreditPoints(0);
  };

  const usageStatusLabel = quotaStatusTone(quotaSummary?.status) === 'error' || overBudget
    ? t('portal.home.service_status_attention', {}, 'Needs attention')
    : quotaStatusTone(quotaSummary?.status) === 'warning'
      ? t('portal.usage.headroom_watch', {}, 'Close to limit')
      : t('portal.home.risk_level_normal', {}, 'Normal');
  const usageHeaderMetrics = [
    {
      label: t('common.status'),
      value: usageStatusLabel,
      detail: t('portal.usage.status_plain_detail', {}, 'Use the numbers below to decide whether you need more points.'),
    },
    {
      label: t('portal.usage.period_label', {}, 'Period'),
      value: currentPeriodRange || t('common.not_found'),
      detail: t('portal.usage.header_period_detail', {}, 'Current package period.'),
      size: 'compact' as const,
    },
    {
      label: t('portal.usage.context_generated'),
      value: usage?.generated_at ? formatDate(usage.generated_at) : t('common.not_found'),
      detail: t('portal.usage.header_updated_detail', {}, 'Latest available data.'),
      size: 'compact' as const,
    },
  ];

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.usage.summary_label', {}, 'Usage')}
        title={t('portal.nav_usage', {}, 'Usage')}
        eyebrowInfo={t(
          'portal.usage.summary_desc',
          {},
          "Review this period's account point use, records, and trends."
        )}
        currentPage="usage"
        metrics={usageHeaderMetrics}
        metricsColumnsClassName="lg:grid-cols-3"
      />

      {entitlements ? (
        <BackofficeSectionPanel className="space-y-5" variant="portal" data-portal-usage="usage-records">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('portal.usage.summary_label', {}, 'Usage')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('portal.usage.credit_ledger_title', {}, 'Point record details')}
              </h2>
              <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-400">
                {t(
                  'portal.usage.credit_ledger_desc',
                  {},
                  'Current-period package point records for this account.'
                )}
              </p>
            </div>
            <div className="text-left sm:text-right">
              <p className="text-lg font-semibold text-gray-950 dark:text-white">
                {formatQuotaValue(creditLedgerTotal)}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {t(
                  'portal.usage.credit_ledger_record_count',
                  { count: formatQuotaValue(creditLedgerCount) },
                  `${formatQuotaValue(creditLedgerCount)} records`
                )}
              </p>
            </div>
          </div>
          {creditLedgerItems.length > 0 ? (
            <div className="overflow-hidden rounded-[1rem] border border-slate-200 dark:border-slate-800">
              <div className="hidden grid-cols-[1.4fr_0.6fr_0.9fr] gap-3 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:bg-slate-950/45 dark:text-slate-400 sm:grid">
                <span>{t('portal.usage.credit_ledger_source', {}, 'Source')}</span>
                <span className="text-right">{t('portal.usage.credit_ledger_credits', {}, 'Credits')}</span>
                <span className="text-right">{t('portal.usage.credit_ledger_time', {}, 'Time')}</span>
              </div>
              <div className="divide-y divide-slate-200 text-sm dark:divide-slate-800">
                {creditLedgerItems.map((entry) => (
                  <div
                    key={entry.ledger_entry_id || `${entry.source_type}-${entry.created_at}`}
                    className="grid grid-cols-1 gap-2 px-4 py-3 sm:grid-cols-[1.4fr_0.6fr_0.9fr] sm:gap-3"
                  >
                    <div>
                      <p className="font-medium text-slate-950 dark:text-white">
                        {formatLedgerTitle(entry)}
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {formatLedgerDescription(entry)}
                      </p>
                    </div>
                    <p className="font-semibold text-slate-950 dark:text-white sm:text-right">
                      {formatLedgerCreditDelta(entry)}
                    </p>
                    <p className="text-slate-500 dark:text-slate-400 sm:text-right">
                      {entry.created_at ? formatDate(entry.created_at) : '-'}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-[1rem] border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
              {t(
                'portal.usage.credit_ledger_empty',
                {},
                'No package point records are available for the current period.'
              )}
            </div>
          )}
        </BackofficeSectionPanel>
      ) : null}

      <details
        className="overflow-hidden rounded-[1.35rem] border border-slate-200/80 bg-white/80 dark:border-slate-800 dark:bg-slate-950/45"
        data-portal-usage="usage-detail"
      >
        <summary className="cursor-pointer px-5 py-4 text-sm font-semibold text-gray-950 hover:bg-slate-50 dark:text-white dark:hover:bg-slate-900/60">
          {t('portal.usage.detail_toggle', {}, 'Usage details')}
        </summary>
        <div className="space-y-5 border-t border-slate-200 p-4 dark:border-slate-800">
          {chartData.length > 0 ? (
            <BackofficeSectionPanel className="space-y-5" variant="portal">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.usage.trends_label', {}, 'Usage trends')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
	              {t('portal.usage.trends_title', {}, 'Service uses, points, and budget')}
            </h2>
          </div>
          <div className="grid gap-6 md:grid-cols-3">
            <BackofficeStackCard variant="portal">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
	                {t('portal.usage.package_service_uses_label', {}, 'Service uses')}
	              </p>
	              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
	                {formatNumber(chartTotals.requests)}
	              </p>
	              <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-300">
	                {t('portal.usage.trend_service_detail', {}, 'Service uses recorded in this view.')}
	              </p>
	              <div className="mt-3">
	                {chartTotals.requests > 0 ? (
	                  <UsageBarChart data={chartData} type="requests" height={120} />
	                ) : (
	                  <div className="flex h-[120px] items-center justify-center rounded-xl border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
	                    {t('portal.usage.trend_empty', {}, 'No data yet')}
	                  </div>
	                )}
	              </div>
	            </BackofficeStackCard>
	            <BackofficeStackCard variant="portal">
	              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
		                {t('portal.usage.breakdown_tokens', {}, 'Point usage')}
	              </p>
	              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
	                {formatCompactNumber(chartTotals.tokens)}
	              </p>
	              <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-300">
	                {t('portal.usage.trend_points_detail', {}, 'Points used by service requests in this view.')}
	              </p>
	              <div className="mt-3">
	                {chartTotals.tokens > 0 ? (
	                  <UsageBarChart data={chartData} type="tokens" height={120} />
	                ) : (
	                  <div className="flex h-[120px] items-center justify-center rounded-xl border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
	                    {t('portal.usage.trend_empty', {}, 'No data yet')}
	                  </div>
	                )}
	              </div>
	            </BackofficeStackCard>
	            <BackofficeStackCard variant="portal">
	              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
		                {t('portal.usage.package_budget_label', {}, 'Budget')}
	              </p>
	              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
	                {formatPreferredCurrency(chartTotals.cost)}
	              </p>
	              <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-300">
	                {t('portal.usage.trend_budget_detail', {}, 'Estimated service budget used in this view.')}
	              </p>
	              <div className="mt-3">
	                {chartTotals.cost > 0 ? (
	                  <UsageBarChart data={chartData} type="cost" height={120} />
	                ) : (
	                  <div className="flex h-[120px] items-center justify-center rounded-xl border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
	                    {t('portal.usage.trend_empty', {}, 'No data yet')}
	                  </div>
	                )}
	              </div>
	            </BackofficeStackCard>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {usageWindow ? (
        <BackofficeSectionPanel className="space-y-5" variant="portal">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
	              {t('portal.usage.cost_summary_label', {}, 'Budget summary')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
	              {t('portal.usage.cost_summary_title', {}, 'Service usage details')}
            </h2>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <BackofficeStackCard className="bg-white/70 dark:bg-slate-950/35" variant="portal">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
	                {t('portal.usage.estimated_total_cost', {}, 'Estimated service budget')}
              </p>
              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
                {formatPreferredCurrency(toFinite(usageWindow.cost_total))}
              </p>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {usageWindow ? `${formatDate(usageWindow.start_at)} - ${formatDate(usageWindow.end_at)}` : t('common.not_found')}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard className="bg-white/70 dark:bg-slate-950/35" variant="portal">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
	                {t('portal.usage.input_tokens', {}, 'Input points')}
              </p>
              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
                {formatCompactNumber(toFinite(usageWindow.tokens_in_total))}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard className="bg-white/70 dark:bg-slate-950/35" variant="portal">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
	                {t('portal.usage.output_tokens', {}, 'Output points')}
              </p>
              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
                {formatCompactNumber(toFinite(usageWindow.tokens_out_total))}
              </p>
            </BackofficeStackCard>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {!entitlements ? (
        <PortalEmptyState
          title={t('portal.usage.empty_title', {}, 'Usage details are not ready yet')}
          description={t(
            'portal.usage.empty_desc',
            {},
            'This account does not have a usage snapshot for the current period yet. Open Package to confirm coverage, or return to the workspace.'
          )}
          actionLabel={t('portal.nav_package', {}, 'Package')}
          actionHref="/portal/billing"
          />
        ) : null}
        </div>
      </details>
    </BackofficePageStack>
  );
}

export default function PortalUsagePage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalUsageContent />
    </Suspense>
  );
}
