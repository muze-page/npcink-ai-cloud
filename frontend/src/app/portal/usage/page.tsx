'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSiteSwitchingNotice,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { UsageBarChart } from '@/components/ui/UsageChart';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useRetry } from '@/hooks/useRetry';
import { useSession } from '@/hooks/useSession';
import {
  getPortalSiteDisplayName,
  getPortalSiteSecondaryLabel,
  getPortalSiteWordPressUrl,
} from '@/lib/portal-site-display';
import {
  portalClient,
  type Entitlements,
  type PortalUsageSummaryPayload,
  type PortalUsageWindow,
} from '@/lib/portal-client';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import {
  DEFAULT_PORTAL_CURRENCY,
  formatPortalCurrency,
} from '@/lib/currency';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { cn, formatCompactNumber, formatDate, formatNumber } from '@/lib/utils';
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

function quotaStatusTone(status: string | undefined): 'ok' | 'warning' | 'error' {
  if (status === 'limited') return 'error';
  if (status === 'near_limit') return 'warning';
  return 'ok';
}

function portalQuotaResourceLabel(
  key: string,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  const labels: Record<string, string> = {
    bound_sites: t('portal.usage.resource_bound_sites', {}, 'Bound sites'),
    active_api_key_sites: t('portal.usage.resource_active_keys', {}, 'Active API keys'),
    concurrent_runs: t('portal.usage.resource_concurrent_runs', {}, 'Concurrent runs'),
    batch_items: t('portal.usage.resource_batch_items', {}, 'Batch items'),
    vector_documents: t('portal.usage.resource_vector_documents', {}, 'Vector articles'),
    vector_chunks: t('portal.usage.resource_vector_chunks', {}, 'Vector chunks'),
    vector_sync_documents_per_run: t('portal.usage.resource_sync_documents', {}, 'Sync articles/run'),
    vector_sync_chunks_per_run: t('portal.usage.resource_sync_chunks', {}, 'Sync chunks/run'),
  };
  return labels[key] || key;
}

function portalCreditBreakdownLabel(
  key: string,
  fallback: string,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  const labels: Record<string, string> = {
    runs: t('portal.usage.breakdown_runs', {}, 'Hosted runs'),
    tokens_total: t('portal.usage.breakdown_tokens', {}, 'Model tokens'),
    web_search: t('portal.usage.breakdown_search', {}, 'Search'),
    image_recommendation: t('portal.usage.breakdown_image', {}, 'Image recommendation'),
    provider_calls_other: t('portal.usage.breakdown_provider_other', {}, 'Other provider calls'),
    vector_documents: t('portal.usage.breakdown_vector_documents', {}, 'Vector articles'),
    vector_chunks: t('portal.usage.breakdown_vector_chunks', {}, 'Vector chunks'),
  };
  return labels[key] || fallback || key;
}

function PortalUsageContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { sites, selectedSiteId, selectedSite, isSwitchingSite, switchingSiteName, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });
  const [usage, setUsage] = useState<PortalUsageSummaryPayload | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);

  const loadBundle = useCallback(async () => {
    if (!selectedSiteId) return;
    const bundle = await portalClient.getUsageBundle(selectedSiteId);
    setUsage(bundle.usage);
    setEntitlements(bundle.entitlements);
  }, [selectedSiteId]);

  const { execute, isLoading: retryLoading, error: retryError, retry } = useRetry(loadBundle, {
    maxRetries: 2,
    initialDelay: 800,
    backoffMultiplier: 2,
  });

  useEffect(() => {
    if (!session || !isAuthenticated || !selectedSiteId) {
      return;
    }
    void execute();
  }, [isAuthenticated, selectedSiteId, session, execute]);

  const handleSiteChange = async (siteId: string) => {
    await setSelectedSiteId(siteId);
  };

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
  const tokenTotal = usageWindow ? usageWindow.tokens_in_total + usageWindow.tokens_out_total : 0;
  const entitlementSnapshot = (entitlements?.entitlement_snapshot || {}) as {
    entitlements?: Record<string, unknown>;
    requests_limit?: number;
    tokens_limit?: number;
    budgets?: {
      max_runs_per_period?: number;
      max_tokens_per_period?: number;
      max_cost_per_period?: number;
    };
  };
  const planVersion = (entitlements?.plan_version || {}) as {
    plan_id?: string;
    plan_version_id?: string;
    version_label?: string;
    budgets?: {
      max_runs_per_period?: number;
      max_tokens_per_period?: number;
      max_cost_per_period?: number;
    };
  };
  const featureList = Array.from(
    new Set(
      Object.values(entitlementSnapshot.entitlements || {})
        .flatMap((entry) => (Array.isArray(entry) ? entry : []))
        .map((entry) => String(entry))
        .filter(Boolean)
    )
  );
  const runsLimit = planVersion.budgets?.max_runs_per_period || 0;
  const tokensLimit = planVersion.budgets?.max_tokens_per_period || 0;
  const costLimit =
    planVersion.budgets?.max_cost_per_period ||
    entitlementSnapshot.budgets?.max_cost_per_period ||
    0;
  const budgetState = entitlements?.budget_state || {};
  const runBudgetState = budgetState.runs || {};
  const tokenBudgetState = budgetState.tokens || {};
  const costBudgetState = budgetState.cost || {};
  const overBudget = Object.values(budgetState).some((entry) => Boolean(entry?.over_limit));
  const subscription = entitlements?.subscription || null;
  const planDisplay = resolveCustomerPackageDisplay(t, {
    planId: planVersion.plan_id || subscription?.plan_id || session.current_subscription?.plan_id,
    planVersionId:
      planVersion.plan_version_id ||
      subscription?.plan_version_id ||
      session.current_subscription?.plan_version_id,
    packageAlias: session.current_subscription?.package_alias,
    formalPlanName: selectedSite?.plan_name,
    planKind: session.current_subscription?.plan_kind,
    coverageState: subscription || session.current_subscription ? 'covered' : 'uncovered',
  });
  const planLabel = planDisplay.display_package_label || t('common.plan');
  const graceState = entitlements?.subscription_grace || {};
  const quotaSummary = entitlements?.quota_summary || null;
  const quotaCredit = quotaSummary?.credit || null;
  const quotaResources = Array.isArray(quotaSummary?.resource_limits)
    ? quotaSummary.resource_limits
    : [];
  const quotaBreakdown = Array.isArray(quotaSummary?.breakdown)
    ? quotaSummary.breakdown
    : [];
  const unlimitedLabel = t('common.unlimited', {}, 'Unlimited');
  const quotaResourceByKey = new Map(
    quotaResources.map((item) => [String(item.key || ''), item])
  );
  const boundSitesResource = quotaResourceByKey.get('bound_sites');
  const vectorDocumentsResource = quotaResourceByKey.get('vector_documents');
  const remainingRequests = Math.max(0, toFinite(runBudgetState.limit || runsLimit) - toFinite(runBudgetState.current_total));
  const remainingTokens = Math.max(0, toFinite(tokenBudgetState.limit || tokensLimit) - toFinite(tokenBudgetState.current_total));
  const remainingCost = Math.max(0, toFinite(costBudgetState.limit || costLimit) - toFinite(costBudgetState.current_total));
  const formatPreferredCurrency = (value: number) => formatPortalCurrency(value, { to: DEFAULT_PORTAL_CURRENCY });
  const headroomTone =
    overBudget
      ? t('status.over_budget')
      : remainingRequests === 0 || remainingTokens === 0 || remainingCost === 0
        ? t('portal.usage.headroom_low', {}, 'At limit')
        : remainingRequests < Math.max(1, Math.floor(toFinite(runBudgetState.limit || runsLimit) * 0.2)) ||
            remainingTokens < Math.max(1, Math.floor(toFinite(tokenBudgetState.limit || tokensLimit) * 0.2)) ||
            remainingCost < toFinite(costBudgetState.limit || costLimit) * 0.2
          ? t('portal.usage.headroom_watch', {}, 'Close to limit')
          : t('status.within_budget');
  const budgetExplanations = [
    runBudgetState.over_limit
      ? t(
          'portal.usage.runs_over_limit_explainer',
          {},
          'Run usage is already above the frozen package limit for this period.'
        )
      : '',
    tokenBudgetState.over_limit
      ? t(
          'portal.usage.tokens_over_limit_explainer',
          {},
          'Token usage is already above the frozen package limit for this period.'
        )
      : '',
    costBudgetState.over_limit
      ? t(
          'portal.usage.cost_over_limit_explainer',
          {},
          'Estimated provider cost is already above the package cost budget for this period.'
        )
      : '',
    graceState.active
      ? t(
          'portal.usage.subscription_grace_explainer',
          {},
          'A subscription grace rule is active. Operator review may keep service available until the listed grace deadline.'
        )
      : '',
  ].filter(Boolean);

  const runUtilizationPct = toFinite(runBudgetState.limit || runsLimit) > 0
    ? Math.min(100, Math.round((toFinite(runBudgetState.current_total) / toFinite(runBudgetState.limit || runsLimit)) * 100))
    : 0;
  const tokenUtilizationPct = toFinite(tokenBudgetState.limit || tokensLimit) > 0
    ? Math.min(100, Math.round((toFinite(tokenBudgetState.current_total) / toFinite(tokenBudgetState.limit || tokensLimit)) * 100))
    : 0;
  const costUtilizationPct = toFinite(costBudgetState.limit || costLimit) > 0
    ? Math.min(100, Math.round((toFinite(costBudgetState.current_total) / toFinite(costBudgetState.limit || costLimit)) * 100))
    : 0;

  const headroomMetrics = [
    quotaCredit
      ? {
          label: t('portal.usage.ai_credits_label', {}, 'AI credits'),
          value: `${formatQuotaValue(quotaCredit.used)} / ${formatQuotaValue(quotaCredit.limit, Boolean(quotaCredit.unlimited), unlimitedLabel)}`,
          detail: t('portal.usage.ai_credits_metric_detail', {}, 'Estimated credits used this package period.'),
        }
      : {
          label: t('portal.usage.remaining_requests_test_label', {}, 'Requests left'),
          value: formatNumber(remainingRequests),
          detail: `${formatNumber(toFinite(runBudgetState.current_total))} / ${formatNumber(toFinite(runBudgetState.limit || runsLimit))}`,
        },
    boundSitesResource
      ? {
          label: t('portal.usage.resource_bound_sites', {}, 'Bound sites'),
          value: `${formatQuotaValue(boundSitesResource.used)} / ${formatQuotaValue(boundSitesResource.limit, Boolean(boundSitesResource.unlimited), unlimitedLabel)}`,
          detail: t('portal.usage.resource_bound_sites_detail', {}, 'Sites attached to this account.'),
        }
      : {
          label: t('portal.usage.remaining_tokens_test_label', {}, 'Tokens left'),
          value: formatCompactNumber(remainingTokens),
          detail: `${formatCompactNumber(toFinite(tokenBudgetState.current_total))} / ${formatCompactNumber(toFinite(tokenBudgetState.limit || tokensLimit))}`,
        },
    vectorDocumentsResource
      ? {
          label: t('portal.usage.resource_vector_documents', {}, 'Vector articles'),
          value: `${formatQuotaValue(vectorDocumentsResource.used)} / ${formatQuotaValue(vectorDocumentsResource.limit, Boolean(vectorDocumentsResource.unlimited), unlimitedLabel)}`,
          detail: t('portal.usage.resource_vector_documents_detail', {}, 'Indexed article capacity remains a separate resource limit.'),
        }
      : {
          label: t('portal.usage.remaining_cost_test_label', {}, 'Cost headroom'),
          value: formatPreferredCurrency(remainingCost),
          detail: `${formatPreferredCurrency(toFinite(costBudgetState.current_total))} / ${formatPreferredCurrency(toFinite(costBudgetState.limit || costLimit))}`,
        },
    {
      label: t('common.status'),
      value: quotaSummary
        ? t(`status.${quotaStatusTone(quotaSummary.status)}`, {}, quotaSummary.status || 'ok')
        : headroomTone,
      detail: quotaSummary?.period_start_at && quotaSummary?.period_end_at
        ? `${t('common.period')}: ${formatDate(quotaSummary.period_start_at)} - ${formatDate(quotaSummary.period_end_at)}`
        : usageWindow ? `${t('common.period')}: ${formatDate(usageWindow.start_at)} - ${formatDate(usageWindow.end_at)}` : undefined,
    },
  ];

  const primarySummaryItems = [
    {
      label: t('common.site'),
      value: getPortalSiteDisplayName(selectedSite) || selectedSiteId || t('common.not_found'),
      detail:
        getPortalSiteWordPressUrl(selectedSite) ||
        getPortalSiteSecondaryLabel(selectedSite) ||
        selectedSiteId,
    },
    {
      label: t('portal.usage.context_generated'),
      value: usage?.generated_at ? formatDate(usage.generated_at) : t('common.not_found'),
      detail: usage?.timezone || t('common.unknown'),
      size: 'compact',
    },
    {
      label: t('portal.usage.context_window'),
      value: usageWindow ? `${formatDate(usageWindow.start_at)} - ${formatDate(usageWindow.end_at)}` : t('common.not_found'),
      detail: t('backoffice.summary_window'),
      size: 'compact',
    },
  ];

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('usage.summary')}
        title={t('portal.usage.primary_title')}
        eyebrowInfo={t(
          'portal.usage.primary_desc',
          {},
          'Review usage for this site and see how much headroom remains under the current package.'
        )}
        currentPage="usage"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSite?.site_name}
        sites={sites}
        onSiteChange={handleSiteChange}
        metrics={headroomMetrics.length > 0 ? headroomMetrics : primarySummaryItems}
        metricsColumnsClassName={headroomMetrics.length > 0 ? 'lg:grid-cols-4' : 'lg:grid-cols-3'}
      >
        <div className="max-w-sm">
          <label htmlFor="portal-usage-site-select" className="sr-only">
            {t('common.site')}
          </label>
          <select
            id="portal-usage-site-select"
            value={selectedSiteId}
            onChange={(event) => void handleSiteChange(event.target.value)}
            className="input"
          >
            {sites.map((site) => (
              <option key={site.site_id} value={site.site_id}>
                {getPortalSiteDisplayName(site) || site.site_id}
              </option>
            ))}
          </select>
        </div>
      </PortalWorkspaceHeader>

      {isSwitchingSite ? (
        <PortalSiteSwitchingNotice
          message={t(
            'portal.site_switching_notice_with_target',
            { site: switchingSiteName || selectedSite?.site_name || selectedSiteId },
            `正在切换到 ${switchingSiteName || selectedSite?.site_name || selectedSiteId}，页面数据会自动更新。`
          )}
        />
      ) : null}

      {quotaSummary && quotaCredit ? (
        <BackofficeSectionPanel className="space-y-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('portal.usage.ai_credit_eyebrow', {}, 'Package usage')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('portal.usage.ai_credit_title', {}, 'AI credits and resource limits')}
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-400">
                {t(
                  'portal.usage.ai_credit_desc',
                  {},
                  'AI credits measure consumption. Site binding, concurrency, batch size, and vector capacity remain separate package limits.'
                )}
              </p>
            </div>
            <BackofficeStatusBadge
              status={quotaStatusTone(quotaSummary.status)}
              label={t(`status.${quotaStatusTone(quotaSummary.status)}`, {}, quotaSummary.status || 'ok')}
            />
          </div>
          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-gray-950 dark:text-white">
                    {t('portal.usage.ai_credits_label', {}, 'AI credits')}
                  </p>
                  <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                    {quotaCredit.estimated
                      ? t('portal.usage.ai_credits_estimated_desc', {}, 'Estimated until the credit ledger is enforced.')
                      : t('portal.usage.ai_credits_actual_desc', {}, 'Credits recorded for this package period.')}
                  </p>
                </div>
                <p className="text-right text-lg font-semibold text-gray-950 dark:text-white">
                  {formatQuotaValue(quotaCredit.used)} / {formatQuotaValue(quotaCredit.limit, Boolean(quotaCredit.unlimited), unlimitedLabel)}
                </p>
              </div>
              {!quotaCredit.unlimited ? (
                <div className="mt-4">
                  <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                    <div
                      className={cn(
                        'h-full rounded-full',
                        quotaCredit.status === 'limited'
                          ? 'bg-red-500'
                          : quotaCredit.status === 'near_limit'
                            ? 'bg-amber-500'
                            : 'bg-emerald-500'
                      )}
                      style={{ width: `${Math.min(100, Math.max(0, Number(quotaCredit.usage_ratio || 0) * 100))}%` }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                    {t('portal.usage.remaining_credits', {}, 'Remaining')}: {formatQuotaValue(quotaCredit.remaining)}
                  </p>
                </div>
              ) : null}
              {quotaBreakdown.length > 0 ? (
                <div className="mt-5 rounded-[1rem] border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-950/35">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                    {t('portal.usage.credit_breakdown_title', {}, 'Credit breakdown')}
                  </p>
                  <div className="mt-3 divide-y divide-slate-200 text-sm dark:divide-slate-800">
                    {quotaBreakdown.map((item) => (
                      <div key={item.key || item.label} className="flex items-start justify-between gap-4 py-2">
                        <div>
                          <p className="font-medium text-slate-900 dark:text-slate-100">
                            {portalCreditBreakdownLabel(String(item.key || ''), String(item.label || ''), t)}
                          </p>
                          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                            {formatQuotaValue(item.quantity)} {item.unit}
                          </p>
                        </div>
                        <p className="text-right font-semibold text-slate-950 dark:text-white">
                          {formatQuotaValue(item.credits)}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </BackofficeStackCard>
            <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
              <p className="text-sm font-semibold text-gray-950 dark:text-white">
                {t('portal.usage.resource_limits_title', {}, 'Resource limits')}
              </p>
              <div className="mt-4 space-y-4">
                {quotaResources.map((resource) => {
                  const status = String(resource.status || 'ok');
                  const progress = resource.unlimited
                    ? 0
                    : Math.min(100, Math.max(0, Number(resource.usage_ratio || 0) * 100));
                  return (
                    <div key={resource.key} className="border-b border-slate-200 pb-4 last:border-b-0 dark:border-slate-800">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-xs uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                            {portalQuotaResourceLabel(String(resource.key || ''), t)}
                          </p>
                          <p className="mt-1 text-sm font-semibold text-slate-950 dark:text-white">
                            {formatQuotaValue(resource.used)} / {formatQuotaValue(resource.limit, Boolean(resource.unlimited), unlimitedLabel)}
                          </p>
                        </div>
                        <p className="text-right text-xs text-slate-500 dark:text-slate-400">
                          {resource.unlimited ? unlimitedLabel : `${Math.round(progress)}%`}
                        </p>
                      </div>
                      {!resource.unlimited ? (
                        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                          <div
                            className={cn(
                              'h-full rounded-full',
                              status === 'limited'
                                ? 'bg-red-500'
                                : status === 'near_limit'
                                  ? 'bg-amber-500'
                                  : 'bg-emerald-500'
                            )}
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </BackofficeStackCard>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {chartData.length > 0 ? (
        <BackofficeSectionPanel className="space-y-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.usage.trends_label', {}, 'Usage trends')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.usage.trends_title', {}, 'Requests, tokens, and cost')}
            </h2>
          </div>
          <div className="grid gap-6 md:grid-cols-3">
            <BackofficeStackCard>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                {t('usage.requests', {}, 'Requests')}
              </p>
              <div className="mt-3">
                <UsageBarChart data={chartData} type="requests" height={160} />
              </div>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                {t('usage.tokens', {}, 'Tokens')}
              </p>
              <div className="mt-3">
                <UsageBarChart data={chartData} type="tokens" height={160} />
              </div>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                {t('usage.cost', {}, 'Cost')}
              </p>
              <div className="mt-3">
                <UsageBarChart data={chartData} type="cost" height={160} />
              </div>
            </BackofficeStackCard>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {entitlements ? (
        <BackofficeSectionPanel className="space-y-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.usage.quota_headroom_label', {}, 'Quota headroom')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.usage.quota_headroom_title', {}, 'Plan utilization')}
            </h2>
          </div>
          <div className="space-y-4">
            <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
              <div className="space-y-4">
                <div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-gray-950 dark:text-white">{t('usage.requests', {}, 'Requests')}</span>
                    <span className="text-gray-600 dark:text-gray-400">{runUtilizationPct}%</span>
                  </div>
                  <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all',
                        runUtilizationPct >= 100 ? 'bg-red-500' : runUtilizationPct >= 80 ? 'bg-amber-500' : 'bg-emerald-500'
                      )}
                      style={{ width: `${runUtilizationPct}%` }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {formatNumber(toFinite(runBudgetState.current_total))} / {formatNumber(toFinite(runBudgetState.limit || runsLimit))}
                  </p>
                </div>
                <div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-gray-950 dark:text-white">{t('usage.tokens', {}, 'Tokens')}</span>
                    <span className="text-gray-600 dark:text-gray-400">{tokenUtilizationPct}%</span>
                  </div>
                  <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all',
                        tokenUtilizationPct >= 100 ? 'bg-red-500' : tokenUtilizationPct >= 80 ? 'bg-amber-500' : 'bg-emerald-500'
                      )}
                      style={{ width: `${tokenUtilizationPct}%` }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {formatCompactNumber(toFinite(tokenBudgetState.current_total))} / {formatCompactNumber(toFinite(tokenBudgetState.limit || tokensLimit))}
                  </p>
                </div>
                <div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-medium text-gray-950 dark:text-white">{t('common.cost', {}, 'Cost')}</span>
                    <span className="text-gray-600 dark:text-gray-400">{costUtilizationPct}%</span>
                  </div>
                  <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all',
                        costUtilizationPct >= 100 ? 'bg-red-500' : costUtilizationPct >= 80 ? 'bg-amber-500' : 'bg-emerald-500'
                      )}
                      style={{ width: `${costUtilizationPct}%` }}
                    />
                  </div>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {formatPreferredCurrency(toFinite(costBudgetState.current_total))} / {formatPreferredCurrency(toFinite(costBudgetState.limit || costLimit))}
                  </p>
                </div>
              </div>
            </BackofficeStackCard>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {usageWindow ? (
        <BackofficeSectionPanel className="space-y-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.usage.cost_summary_label', {}, 'Cost summary')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.usage.cost_summary_title', {}, 'Provider cost breakdown')}
            </h2>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                {t('portal.usage.estimated_total_cost', {}, 'Estimated total cost')}
              </p>
              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
                {formatPreferredCurrency(toFinite(usageWindow.cost_total))}
              </p>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {usageWindow ? `${formatDate(usageWindow.start_at)} - ${formatDate(usageWindow.end_at)}` : t('common.not_found')}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                {t('portal.usage.input_tokens', {}, 'Input tokens')}
              </p>
              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
                {formatCompactNumber(toFinite(usageWindow.tokens_in_total))}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                {t('portal.usage.output_tokens', {}, 'Output tokens')}
              </p>
              <p className="mt-3 text-2xl font-semibold text-gray-950 dark:text-white">
                {formatCompactNumber(toFinite(usageWindow.tokens_out_total))}
              </p>
            </BackofficeStackCard>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {entitlements ? (
        <BackofficeSectionPanel className="space-y-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.usage.detail_label', {}, 'Details')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.usage.entitlement_title', {}, 'Usage detail')}
            </h2>
          </div>
          <div className="space-y-4">
            <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/45">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                    {t('portal.current_subscription_label', {}, 'Current package')}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <p className="truncate text-lg font-semibold text-gray-950 dark:text-white">
                      {planLabel}
                    </p>
                    <BackofficeStatusBadge
                      status={overBudget ? 'over_budget' : 'within_budget'}
                      label={overBudget ? t('status.over_budget') : t('status.within_budget')}
                    />
                  </div>
                  <p className="mt-1 truncate text-sm text-gray-600 dark:text-gray-400">
                    {getPortalSiteSecondaryLabel(selectedSite) || entitlements.site_id}
                  </p>
                </div>
                <div className="grid gap-2 text-sm text-slate-700 dark:text-slate-200 sm:grid-cols-3 lg:min-w-[34rem]">
                  <span className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-800">
                    {t('usage.requests_month')}: <strong>{formatNumber(runsLimit)}</strong>
                  </span>
                  <span className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-800">
                    {t('usage.tokens_month')}: <strong>{formatCompactNumber(tokensLimit)}</strong>
                  </span>
                  <span className="rounded-2xl border border-slate-200/80 px-3 py-2 dark:border-slate-800">
                    {t('common.cost')}: <strong>{formatPreferredCurrency(costLimit)}</strong>
                  </span>
                </div>
              </div>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-sm font-medium text-gray-950 dark:text-white">
                {t('portal.usage.behavior_title', {}, 'What happens when usage crosses the package limit?')}
              </p>
              <div className="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-300">
                {budgetExplanations.length > 0 ? (
                  budgetExplanations.map((line) => <p key={line}>{line}</p>)
                ) : (
                  <p>
                    {t(
                      'portal.usage.behavior_clear',
                      {},
                      'This site is still within the current package envelope. If soft-limit, grace, or downgrade rules are introduced for this plan version, they will show here as read-only explanations.'
                    )}
                  </p>
                )}
                {graceState.grace_until_at ? (
                  <p>
                    {t('portal.usage.grace_until', {}, 'Grace until')}: {formatDate(graceState.grace_until_at)}
                  </p>
                ) : null}
                <p>
                  {t(
                    'portal.usage.operator_mediated_notice',
                    {},
                    'This portal explains the current package state but does not change package coverage directly. If something looks wrong, contact your operator.'
                  )}
                </p>
              </div>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-sm font-medium text-gray-950 dark:text-white">
                {t('portal.usage.help_understanding_limits_title', {}, 'Need help understanding limits')}
              </p>
              <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
                {t(
                  'portal.usage.help_understanding_limits_desc',
                  {},
                  'Use this read-only view to compare current usage, package headroom, and grace posture before asking the operator to review coverage.'
                )}
              </p>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <p className="text-sm font-medium text-gray-950 dark:text-white">{t('usage.features')}</p>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{t('portal.usage.feature_list_desc')}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {featureList.map((feature) => (
                  <span
                    key={feature}
                    className="rounded-full bg-blue-100 px-3 py-1 text-xs text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
                  >
                    {feature}
                  </span>
                ))}
              </div>
            </BackofficeStackCard>
          </div>
        </BackofficeSectionPanel>
      ) : (
        <PortalEmptyState
          title={t('portal.usage.empty_title', {}, 'Usage details are not ready yet')}
          description={t(
            'portal.usage.empty_desc',
            {},
            'This site does not have a usage snapshot for the current period yet. Open Package to confirm coverage or return to the workspace.'
          )}
          actionLabel={t('portal.nav_package', {}, 'Open Package')}
          actionHref={selectedSiteId ? `/portal/billing?site=${selectedSiteId}` : '/portal/billing'}
        />
      )}
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
