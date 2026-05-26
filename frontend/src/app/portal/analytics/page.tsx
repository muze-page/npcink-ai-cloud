'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import {
  PortalErrorState,
  PortalLoadingState,
  PortalSiteSwitchingNotice,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalAnalyticsOverview,
  type PortalAnalyticsTrend,
  type PortalAnalyticsCostBreakdown,
  type PortalAnalyticsPerformance,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatCompactNumber, formatNumber } from '@/lib/utils';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
  BackofficeMetricStrip,
} from '@/components/backoffice/BackofficeScaffold';
import {
  AnalyticsLineChart,
  AnalyticsBarChart,
  AnalyticsPieChart,
  AnalyticsGaugeChart,
} from '@/components/ui/EChartsWrapper';
import { Button } from '@/components/ui/Button';

function PortalAnalyticsContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { sites, selectedSiteId, selectedSite, isSwitchingSite, switchingSiteName, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });

  const [overview, setOverview] = useState<PortalAnalyticsOverview | null>(null);
  const [trend, setTrend] = useState<PortalAnalyticsTrend | null>(null);
  const [costBreakdown, setCostBreakdown] = useState<PortalAnalyticsCostBreakdown | null>(null);
  const [performance, setPerformance] = useState<PortalAnalyticsPerformance | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRange, setSelectedRange] = useState('7d');
  const [groupBy, setGroupBy] = useState('provider');

  const allowedRanges = overview?.allowed_ranges || ['7d'];

  useEffect(() => {
    const loadData = async () => {
      if (!session || !isAuthenticated || !selectedSiteId) {
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const [overviewRes, trendRes, costRes, perfRes] = await Promise.all([
          portalClient.getAnalyticsOverview(selectedSiteId, selectedRange),
          portalClient.getAnalyticsTrend(selectedSiteId, selectedRange, 'daily'),
          portalClient.getAnalyticsCostBreakdown(selectedSiteId, selectedRange, groupBy),
          portalClient.getAnalyticsPerformance(selectedSiteId, selectedRange),
        ]);

        setOverview(overviewRes.data);
        setTrend(trendRes.data);
        setCostBreakdown(costRes.data);
        setPerformance(perfRes.data);
      } catch (err) {
        setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadData();
  }, [isAuthenticated, selectedSiteId, session, t, selectedRange, groupBy]);

  const handleSiteChange = async (siteId: string) => {
    await setSelectedSiteId(siteId);
    setIsLoading(true);
    setError(null);

    try {
      const [overviewRes, trendRes, costRes, perfRes] = await Promise.all([
        portalClient.getAnalyticsOverview(siteId, selectedRange),
        portalClient.getAnalyticsTrend(siteId, selectedRange, 'daily'),
        portalClient.getAnalyticsCostBreakdown(siteId, selectedRange, groupBy),
        portalClient.getAnalyticsPerformance(siteId, selectedRange),
      ]);

      setOverview(overviewRes.data);
      setTrend(trendRes.data);
      setCostBreakdown(costRes.data);
      setPerformance(perfRes.data);
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  };

  if (sessionLoading || isLoading) {
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

  if (error) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={error}
        retryLabel={t('common.retry')}
        onRetry={() => void handleSiteChange(selectedSiteId || '')}
      />
    );
  }

  const overviewData = overview?.overview;
  const trendRows = trend?.rows || [];
  const costData = costBreakdown?.breakdown || [];
  const perfData = performance?.performance;

  // Transform trend rows for line chart
  const trendChartData = trendRows.map((row) => ({
    label: row.bucket_gmt?.slice(0, 10) || '',
    value: row.request_total || 0,
    secondaryValue: row.success_total || 0,
  }));

  // Transform cost breakdown for pie/bar charts
  const costPieData = costData.map((item) => ({
    label: item.label,
    value: item.value,
  }));

  const costBarData = costData.map((item) => ({
    label: item.label,
    value: item.value,
  }));

  const metrics = [
    {
      label: t('portal.analytics.total_calls', {}, 'Total Calls'),
      value: formatNumber(overviewData?.total_calls || 0),
    },
    {
      label: t('portal.analytics.success_rate', {}, 'Success Rate'),
      value: `${((overviewData?.success_rate || 0) * 100).toFixed(1)}%`,
    },
    {
      label: t('portal.analytics.avg_latency', {}, 'Avg Latency'),
      value: `${formatNumber(overviewData?.avg_latency_ms || 0)}ms`,
    },
    {
      label: t('portal.analytics.total_cost', {}, 'Total Cost'),
      value: `$${(overviewData?.total_cost || 0).toFixed(2)}`,
    },
  ];

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.analytics.eyebrow', {}, 'Analytics')}
        title={t('portal.analytics.title', {}, '数据分析')}
        currentPage="analytics"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSite?.site_name}
        sites={sites}
        onSiteChange={handleSiteChange}
        metrics={metrics}
      />

      {isSwitchingSite ? (
        <PortalSiteSwitchingNotice
          message={t('portal.site_switching', { siteName: switchingSiteName }, 'Switching to {siteName}...')}
        />
      ) : null}

      {/* Range Selector */}
      <BackofficeSectionPanel title={t('portal.analytics.time_range', {}, 'Time Range')}>
        <BackofficeStackCard>
          <div className="flex flex-wrap gap-2">
            {['7d', '30d', '90d'].map((range) => (
              <Button
                key={range}
                variant={selectedRange === range ? 'primary' : 'outline'}
                size="sm"
                disabled={!allowedRanges.includes(range)}
                onClick={() => setSelectedRange(range)}
              >
                {range === '7d' && t('portal.analytics.range_7d', {}, '7 Days')}
                {range === '30d' && t('portal.analytics.range_30d', {}, '30 Days')}
                {range === '90d' && t('portal.analytics.range_90d', {}, '90 Days')}
              </Button>
            ))}
          </div>
          {!allowedRanges.includes(selectedRange) && (
            <p className="mt-2 text-sm text-amber-600 dark:text-amber-400">
              {t(
                'portal.analytics.range_upgrade_hint',
                {},
                'This range is not available on your current plan. Upgrade to see more data.'
              )}
            </p>
          )}
        </BackofficeStackCard>
      </BackofficeSectionPanel>

      {/* Call Trend */}
      <BackofficeSectionPanel title={t('portal.analytics.call_trend', {}, 'Call Trend')}>
        <BackofficeStackCard>
          {trendChartData.length > 0 ? (
            <AnalyticsLineChart
              data={trendChartData}
              height={320}
              primarySeriesName={t('portal.analytics.requests', {}, 'Requests')}
              secondarySeriesName={t('portal.analytics.successes', {}, 'Successes')}
              primaryColor="#3b82f6"
              secondaryColor="#10b981"
            />
          ) : (
            <div className="flex h-80 items-center justify-center text-gray-500">
              {t('portal.analytics.no_data', {}, 'No data available for the selected period')}
            </div>
          )}
        </BackofficeStackCard>
      </BackofficeSectionPanel>

      {/* Cost Analysis */}
      <BackofficeSectionPanel title={t('portal.analytics.cost_analysis', {}, 'Cost Analysis')}>
        <BackofficeStackCard>
          <div className="mb-4 flex flex-wrap gap-2">
            {['provider', 'model', 'ability_family'].map((gb) => (
              <Button
                key={gb}
                variant={groupBy === gb ? 'primary' : 'outline'}
                size="sm"
                onClick={() => setGroupBy(gb)}
              >
                {gb === 'provider' && t('portal.analytics.by_provider', {}, 'By Provider')}
                {gb === 'model' && t('portal.analytics.by_model', {}, 'By Model')}
                {gb === 'ability_family' && t('portal.analytics.by_ability', {}, 'By Ability')}
              </Button>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {costPieData.length > 0 ? (
              <AnalyticsPieChart data={costPieData} height={300} donut />
            ) : (
              <div className="flex h-72 items-center justify-center text-gray-500">
                {t('portal.analytics.no_cost_data', {}, 'No cost data available')}
              </div>
            )}

            {costBarData.length > 0 ? (
              <AnalyticsBarChart data={costBarData} height={300} horizontal />
            ) : (
              <div className="flex h-72 items-center justify-center text-gray-500">
                {t('portal.analytics.no_cost_data', {}, 'No cost data available')}
              </div>
            )}
          </div>

          <div className="mt-4 text-right text-lg font-semibold">
            {t('portal.analytics.total_cost_label', {}, 'Total:')}{' '}
            <span className="text-blue-600 dark:text-blue-400">
              ${(costBreakdown?.total_cost || 0).toFixed(2)}
            </span>
          </div>
        </BackofficeStackCard>
      </BackofficeSectionPanel>

      {/* Performance */}
      <BackofficeSectionPanel title={t('portal.analytics.performance', {}, 'Performance')}>
        <BackofficeStackCard>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
            <div className="flex flex-col items-center">
              <AnalyticsGaugeChart
                value={Math.round(perfData?.latency?.p95_ms || 0)}
                min={0}
                max={5000}
                title={t('portal.analytics.p95_latency', {}, 'P95 Latency')}
                unit="ms"
                color="#f59e0b"
              />
            </div>

            <div className="rounded-xl bg-surface-raised p-4">
              <div className="text-sm text-gray-500 dark:text-gray-400">
                {t('portal.analytics.error_rate', {}, 'Error Rate')}
              </div>
              <div className="mt-1 text-2xl font-bold text-red-500">
                {((perfData?.error_rate || 0) * 100).toFixed(1)}%
              </div>
            </div>

            <div className="rounded-xl bg-surface-raised p-4">
              <div className="text-sm text-gray-500 dark:text-gray-400">
                {t('portal.analytics.timeout_rate', {}, 'Timeout Rate')}
              </div>
              <div className="mt-1 text-2xl font-bold text-amber-500">
                {((perfData?.timeout_rate || 0) * 100).toFixed(1)}%
              </div>
            </div>

            <div className="rounded-xl bg-surface-raised p-4">
              <div className="text-sm text-gray-500 dark:text-gray-400">
                {t('portal.analytics.blocked_rate', {}, 'Blocked Rate')}
              </div>
              <div className="mt-1 text-2xl font-bold text-orange-500">
                {((perfData?.blocked_rate || 0) * 100).toFixed(1)}%
              </div>
            </div>
          </div>

          {/* Top Errors */}
          {perfData?.top_errors && perfData.top_errors.length > 0 && (
            <div className="mt-6">
              <h4 className="mb-3 text-sm font-semibold">
                {t('portal.analytics.top_errors', {}, 'Top Errors')}
              </h4>
              <div className="space-y-2">
                {perfData.top_errors.slice(0, 5).map((err, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between rounded-lg bg-surface-raised px-4 py-2"
                  >
                    <code className="text-sm text-red-600 dark:text-red-400">{err.error_code}</code>
                    <div className="text-sm text-gray-600 dark:text-gray-400">
                      {err.count} ({(err.percentage * 100).toFixed(1)}%)
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </BackofficeStackCard>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function PortalAnalyticsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalAnalyticsContent />
    </Suspense>
  );
}
