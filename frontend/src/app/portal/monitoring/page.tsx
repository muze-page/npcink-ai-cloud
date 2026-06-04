'use client';

import React, { Suspense, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { PortalErrorState, PortalLoadingState, PortalSignedOutState } from '@/components/portal/PortalPageState';
import { PortalMediaProcessingPanel } from '@/components/portal/PortalMediaProcessingPanel';
import { PortalPluginMonitoringPanel } from '@/components/portal/PortalPluginMonitoringPanel';
import { PortalSiteKnowledgePanel } from '@/components/portal/PortalSiteKnowledgePanel';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalMediaObservabilitySummary,
  type PortalMonitoringOverviewAction,
  type PortalMonitoringOverviewQuotaMetric,
  type PortalMonitoringOverviewSummary,
  type PortalPluginObservabilitySummary,
  type PortalVectorObservabilitySummary,
  type Site,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { getPortalSiteDisplayName } from '@/lib/portal-site-display';
import { formatDate, formatNumber } from '@/lib/utils';

type MonitoringTab = 'overview' | 'plugins' | 'media' | 'vector';

const MONITORING_TABS: MonitoringTab[] = ['overview', 'plugins', 'media', 'vector'];

function resolveSelectedSite(
  sites: Site[],
  requestedSiteId: string,
  sessionSiteId: string
): Site | null {
  return (
    sites.find((site) => site.site_id === requestedSiteId && site.status !== 'archived') ||
    sites.find((site) => site.site_id === sessionSiteId && site.status !== 'archived') ||
    sites.find((site) => site.status !== 'archived') ||
    null
  );
}

function normalizeMonitoringTab(value: string | null): MonitoringTab {
  return MONITORING_TABS.includes(value as MonitoringTab) ? (value as MonitoringTab) : 'overview';
}

function formatPercent(value: number): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function latestDateValue(values: Array<string | undefined>): string {
  let latest = '';
  let latestTime = 0;
  for (const value of values) {
    if (!value) continue;
    const time = new Date(value).getTime();
    if (!Number.isNaN(time) && time > latestTime) {
      latestTime = time;
      latest = value;
    }
  }
  return latest;
}

function statusTone(status: string): 'ok' | 'warning' | 'error' | 'inactive' {
  if (status === 'ok') return 'ok';
  if (status === 'warning') return 'warning';
  if (status === 'error') return 'error';
  return 'inactive';
}

function PortalMonitoringContent() {
  const { t } = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { session, isLoading, isAuthenticated, selectSite } = useSession();
  const [monitoringOverview, setMonitoringOverview] = useState<PortalMonitoringOverviewSummary | null>(null);
  const [summary, setSummary] = useState<PortalPluginObservabilitySummary | null>(null);
  const [mediaSummary, setMediaSummary] = useState<PortalMediaObservabilitySummary | null>(null);
  const [vectorSummary, setVectorSummary] = useState<PortalVectorObservabilitySummary | null>(null);
  const [isMonitoringOverviewLoading, setIsMonitoringOverviewLoading] = useState(false);
  const [isSummaryLoading, setIsSummaryLoading] = useState(false);
  const [isMediaSummaryLoading, setIsMediaSummaryLoading] = useState(false);
  const [isVectorSummaryLoading, setIsVectorSummaryLoading] = useState(false);
  const [monitoringOverviewError, setMonitoringOverviewError] = useState('');
  const [error, setError] = useState('');
  const [mediaError, setMediaError] = useState('');
  const [vectorError, setVectorError] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const lastLoadedSiteRef = useRef('');
  const requestedSiteId = searchParams.get('site') || '';
  const activeTab = normalizeMonitoringTab(searchParams.get('tab'));
  const sites = session?.sites || [];
  const selectedSite = resolveSelectedSite(sites, requestedSiteId, session?.site_id || '');
  const selectedSiteId = selectedSite?.site_id || '';

  useEffect(() => {
    if (!selectedSiteId) {
      setMonitoringOverview(null);
      setSummary(null);
      setMediaSummary(null);
      setVectorSummary(null);
      setMonitoringOverviewError('');
      setError('');
      setMediaError('');
      setVectorError('');
      return;
    }
    if (lastLoadedSiteRef.current !== selectedSiteId) {
      lastLoadedSiteRef.current = selectedSiteId;
      setMonitoringOverview(null);
      setSummary(null);
      setMediaSummary(null);
      setVectorSummary(null);
      setMonitoringOverviewError('');
      setError('');
      setMediaError('');
      setVectorError('');
    }
  }, [selectedSiteId]);

  useEffect(() => {
    if (!selectedSiteId) {
      return;
    }

    let isCancelled = false;
    const shouldLoadOverview = activeTab === 'overview';
    const shouldLoadPlugins = activeTab === 'plugins';
    const shouldLoadMedia = activeTab === 'media';
    const shouldLoadVector = activeTab === 'vector';

    if (shouldLoadOverview) {
      setIsMonitoringOverviewLoading(true);
      setMonitoringOverviewError('');
      void portalClient
        .getMonitoringOverview(selectedSiteId, { windowHours: 24 })
        .then((response) => {
          if (!isCancelled) {
            setMonitoringOverview(response.data);
          }
        })
        .catch((err) => {
          if (!isCancelled) {
            setMonitoringOverview(null);
            setMonitoringOverviewError(formatPortalErrorMessage(err, t, t('error.failed_load')));
          }
        })
        .finally(() => {
          if (!isCancelled) {
            setIsMonitoringOverviewLoading(false);
          }
        });
    }

    if (shouldLoadPlugins) {
      setIsSummaryLoading(true);
      setError('');
      void portalClient
        .getPluginObservability(selectedSiteId, { windowHours: 24 })
        .then((response) => {
          if (!isCancelled) {
            setSummary(response.data);
          }
        })
        .catch((err) => {
          if (!isCancelled) {
            setSummary(null);
            setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
          }
        })
        .finally(() => {
          if (!isCancelled) {
            setIsSummaryLoading(false);
          }
        });
    }

    if (shouldLoadMedia) {
      setIsMediaSummaryLoading(true);
      setMediaError('');
      void portalClient
        .getMediaObservability(selectedSiteId, { windowHours: 24 })
        .then((response) => {
          if (!isCancelled) {
            setMediaSummary(response.data);
          }
        })
        .catch((err) => {
          if (!isCancelled) {
            setMediaSummary(null);
            setMediaError(formatPortalErrorMessage(err, t, t('error.failed_load')));
          }
        })
        .finally(() => {
          if (!isCancelled) {
            setIsMediaSummaryLoading(false);
          }
        });
    }

    if (shouldLoadVector) {
      setIsVectorSummaryLoading(true);
      setVectorError('');
      void portalClient
        .getVectorObservability(selectedSiteId, { windowHours: 24 })
        .then((response) => {
          if (!isCancelled) {
            setVectorSummary(response.data);
          }
        })
        .catch((err) => {
          if (!isCancelled) {
            setVectorSummary(null);
            setVectorError(formatPortalErrorMessage(err, t, t('error.failed_load')));
          }
        })
        .finally(() => {
          if (!isCancelled) {
            setIsVectorSummaryLoading(false);
          }
        });
    }

    return () => {
      isCancelled = true;
    };
  }, [activeTab, refreshNonce, selectedSiteId, t]);

  if (isLoading) {
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

  if (!selectedSite) {
    return (
      <PortalErrorState
        title={t('portal.no_sites', {}, 'No sites')}
        description={t(
          'portal.monitoring.no_site_desc',
          {},
          'Connect a WordPress site before plugin monitoring can be displayed.'
        )}
        retryLabel={t('common.retry')}
        onRetry={() => window.location.reload()}
      />
    );
  }

  const pluginTotals = summary?.totals || null;
  const mediaTotals = mediaSummary?.totals || null;
  const vectorTotals = vectorSummary?.totals || null;
  const latestActivityAt = monitoringOverview?.activity.last_seen_at || latestDateValue([
    pluginTotals?.last_seen_at,
    mediaTotals?.last_finished_at,
    vectorTotals?.last_search_finished_at,
    vectorTotals?.last_index_job_finished_at,
  ]);
  const isOverviewLoading = isMonitoringOverviewLoading;
  const topPressure = monitoringOverview?.quota.top_pressure || 'none';
  const topPressureMetric = topPressure !== 'none' ? monitoringOverview?.quota[topPressure] : null;

  const changeTab = (nextTab: MonitoringTab) => {
    const params = new URLSearchParams(searchParams.toString());
    if (nextTab === 'overview') {
      params.delete('tab');
    } else {
      params.set('tab', nextTab);
    }
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname);
  };

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.monitoring.eyebrow', {}, 'Cloud monitoring')}
        title={t('portal.monitoring.page_title', {}, 'Cloud monitoring')}
        description={t(
          'portal.monitoring.page_desc',
          {},
          'Read-only Cloud runtime monitoring for the selected WordPress site. Admin-only cross-site data stays in the Cloud admin console.'
        )}
        currentPage="monitoring"
        selectedSiteId={selectedSiteId}
        selectedSiteName={getPortalSiteDisplayName(selectedSite)}
        sites={sites}
        onSiteChange={(siteId) => {
          void selectSite(siteId);
        }}
        showSiteContextSummary
        metrics={[
          {
            label: t('portal.monitoring.site_health', {}, 'Site health'),
            value: monitoringOverview ? `${monitoringOverview.health.score}` : t('common.not_found'),
            detail: monitoringOverview ? monitoringOverview.health.status : t('common.not_found'),
          },
          {
            label: t('portal.monitoring.actions_required', {}, 'Action required'),
            value: monitoringOverview ? formatNumber(monitoringOverview.action_required.length) : t('common.not_found'),
            detail: monitoringOverview ? 'open items' : t('common.not_found'),
          },
          {
            label: t('portal.monitoring.quota_pressure', {}, 'Quota pressure'),
            value: topPressure === 'none' ? t('common.not_found') : topPressure,
            detail: topPressureMetric ? `${formatPercent(Number(topPressureMetric.usage_ratio || 0))} used` : t('common.not_found'),
          },
          {
            label: t('portal.monitoring.last_activity', {}, 'Last activity'),
            value: latestActivityAt ? formatDate(latestActivityAt) : t('common.not_found'),
            detail: t('portal.monitoring.last_activity_detail', {}, 'Cloud received'),
          },
        ]}
      />

      <MonitoringTabs activeTab={activeTab} onChange={changeTab} />

      {activeTab === 'overview' ? (
        <MonitoringOverview
          monitoringOverview={monitoringOverview}
          pluginSummary={summary}
          mediaSummary={mediaSummary}
          vectorSummary={vectorSummary}
          isLoading={isOverviewLoading}
          errors={[monitoringOverviewError].filter(Boolean)}
          onRefresh={() => setRefreshNonce((current) => current + 1)}
          onSelectTab={changeTab}
        />
      ) : null}

      {activeTab === 'plugins' ? (
        <PortalPluginMonitoringPanel
          siteId={selectedSiteId}
          summary={summary}
          isLoading={isSummaryLoading}
          error={error}
          onRetry={() => setRefreshNonce((current) => current + 1)}
        />
      ) : null}

      {activeTab === 'media' ? (
        <PortalMediaProcessingPanel
          summary={mediaSummary}
          isLoading={isMediaSummaryLoading}
          error={mediaError}
          onRetry={() => setRefreshNonce((current) => current + 1)}
        />
      ) : null}

      {activeTab === 'vector' ? (
        <PortalSiteKnowledgePanel
          summary={vectorSummary}
          isLoading={isVectorSummaryLoading}
          error={vectorError}
          onRetry={() => setRefreshNonce((current) => current + 1)}
        />
      ) : null}
    </BackofficePageStack>
  );
}

function MonitoringTabs({
  activeTab,
  onChange,
}: {
  activeTab: MonitoringTab;
  onChange: (tab: MonitoringTab) => void;
}) {
  const { t } = useLocale();
  const tabs: Array<{ id: MonitoringTab; label: string; description: string }> = [
    {
      id: 'overview',
      label: t('portal.monitoring.tabs_overview', {}, 'Overview'),
      description: t('portal.monitoring.tabs_overview_desc', {}, 'All monitoring'),
    },
    {
      id: 'plugins',
      label: t('portal.monitoring.tabs_plugins', {}, 'Plugins'),
      description: t('portal.monitoring.tabs_plugins_desc', {}, 'Plugin events'),
    },
    {
      id: 'media',
      label: t('portal.monitoring.tabs_media', {}, 'Media'),
      description: t('portal.monitoring.tabs_media_desc', {}, 'Processing jobs'),
    },
    {
      id: 'vector',
      label: t('portal.monitoring.tabs_vector', {}, 'Vector'),
      description: t('portal.monitoring.tabs_vector_desc', {}, 'Site knowledge'),
    },
  ];
  return (
    <BackofficeSectionPanel className="p-2 md:p-2">
      <div role="tablist" aria-label={t('portal.monitoring.tabs_label', {}, 'Monitoring sections')} className="grid gap-2 md:grid-cols-4">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onChange(tab.id)}
              className={`rounded-[1rem] px-4 py-3 text-left transition ${
                isActive
                  ? 'bg-slate-950 text-white shadow-sm dark:bg-white dark:text-slate-950'
                  : 'text-slate-600 hover:bg-white/75 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-900/70 dark:hover:text-white'
              }`}
            >
              <span className="block text-sm font-semibold">{tab.label}</span>
              <span className={`mt-1 block text-xs ${isActive ? 'text-white/70 dark:text-slate-700' : 'text-slate-500 dark:text-slate-400'}`}>
                {tab.description}
              </span>
            </button>
          );
        })}
      </div>
    </BackofficeSectionPanel>
  );
}

function MonitoringOverview({
  monitoringOverview,
  pluginSummary,
  mediaSummary,
  vectorSummary,
  isLoading,
  errors,
  onRefresh,
  onSelectTab,
}: {
  monitoringOverview: PortalMonitoringOverviewSummary | null;
  pluginSummary: PortalPluginObservabilitySummary | null;
  mediaSummary: PortalMediaObservabilitySummary | null;
  vectorSummary: PortalVectorObservabilitySummary | null;
  isLoading: boolean;
  errors: string[];
  onRefresh: () => void;
  onSelectTab: (tab: MonitoringTab) => void;
}) {
  const { t } = useLocale();
  const pluginTotals = pluginSummary?.totals || null;
  const mediaTotals = mediaSummary?.totals || null;
  const vectorTotals = vectorSummary?.totals || null;
  const health = monitoringOverview?.health;
  const actionItems = monitoringOverview?.action_required || [];
  const quota = monitoringOverview?.quota;
  const activity = monitoringOverview?.activity;
  const componentsByName = new Map((monitoringOverview?.components || []).map((item) => [item.component, item]));
  const pluginComponent = componentsByName.get('plugins');
  const mediaComponent = componentsByName.get('media');
  const vectorComponent = componentsByName.get('vector');
  return (
    <BackofficeSectionPanel className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
            {t('portal.monitoring.overview_title', {}, 'Monitoring overview')}
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t(
              'portal.monitoring.overview_desc',
              {},
              'A compact read-only operating summary for site health, quota pressure, and Cloud monitoring signals.'
            )}
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRefresh}>
          {t('common.refresh', {}, 'Refresh')}
        </button>
      </div>

      {isLoading ? (
        <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
          {t('common.loading')}
        </BackofficeStackCard>
      ) : null}

      {errors.length ? (
        <BackofficeStackCard className="border-amber-200 bg-amber-50/70 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
          {errors[0]}
        </BackofficeStackCard>
      ) : null}

      <BackofficeMetricStrip
        columnsClassName="md:grid-cols-4"
        items={[
          {
            label: t('portal.monitoring.site_health', {}, 'Site health'),
            value: health ? String(health.score) : t('common.not_found'),
            detail: health?.summary || t('common.not_found'),
            toneClassName:
              health?.status === 'error'
                ? 'text-red-700 dark:text-red-200'
                : health?.status === 'warning'
                  ? 'text-amber-700 dark:text-amber-200'
                  : '',
          },
          {
            label: t('portal.monitoring.actions_required', {}, 'Action required'),
            value: formatNumber(actionItems.length),
            detail: actionItems.length ? actionItems[0]?.title || '' : t('portal.monitoring.no_actions', {}, 'No immediate action'),
            toneClassName: actionItems.some((item) => item.severity === 'error') ? 'text-red-700 dark:text-red-200' : '',
          },
          {
            label: t('portal.monitoring.quota_pressure', {}, 'Quota pressure'),
            value: quota ? quota.top_pressure : t('common.not_found'),
            detail: quota?.summary || t('common.not_found'),
          },
          {
            label: t('portal.monitoring.last_activity', {}, 'Last activity'),
            value: activity?.last_seen_at ? formatDate(activity.last_seen_at) : t('common.not_found'),
            detail: activity ? `${formatNumber(activity.runtime_runs_total)} runtime runs` : t('common.not_found'),
          },
        ]}
      />

      <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <ActionRequiredPanel items={actionItems} />
        <QuotaPressurePanel quota={quota || null} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <MonitoringOverviewCard
          title={t('portal.monitoring.card_plugins', {}, 'Plugins')}
          status={statusTone(pluginComponent?.status || pluginSummary?.health?.status || 'inactive')}
          badge={`${pluginComponent?.status || pluginSummary?.health?.status || 'inactive'} · ${pluginComponent?.score ?? pluginSummary?.health?.score ?? 0}`}
          detail={pluginComponent?.summary || pluginSummary?.health?.summary || t('portal.monitoring.no_plugin_summary', {}, 'No plugin summary yet.')}
          meta={`${formatNumber(Number(activity?.plugin_errors_total ?? pluginTotals?.error_total ?? 0))} errors`}
          actionLabel={t('common.inspect', {}, 'Inspect')}
          onClick={() => onSelectTab('plugins')}
        />
        <MonitoringOverviewCard
          title={t('portal.monitoring.card_media', {}, 'Media')}
          status={statusTone(mediaComponent?.status || mediaSummary?.health?.status || 'inactive')}
          badge={`${mediaComponent?.status || mediaSummary?.health?.status || 'inactive'} · ${mediaComponent?.score ?? mediaSummary?.health?.score ?? 0}`}
          detail={mediaComponent?.summary || mediaSummary?.health?.summary || t('portal.monitoring.no_media_summary', {}, 'No media summary yet.')}
          meta={`${formatNumber(Number(activity?.media_failed_total ?? mediaTotals?.failed_total ?? 0))} failed jobs`}
          actionLabel={t('common.inspect', {}, 'Inspect')}
          onClick={() => onSelectTab('media')}
        />
        <MonitoringOverviewCard
          title={t('portal.monitoring.card_vector', {}, 'Vector')}
          status={statusTone(vectorComponent?.status || vectorSummary?.health?.status || 'inactive')}
          badge={`${vectorComponent?.status || vectorSummary?.health?.status || 'inactive'} · ${vectorComponent?.score ?? vectorSummary?.health?.score ?? 0}`}
          detail={vectorComponent?.summary || vectorSummary?.health?.summary || t('portal.monitoring.no_vector_summary', {}, 'No vector summary yet.')}
          meta={`${formatNumber(Number(vectorTotals?.current_chunk_count || 0))} indexed chunks`}
          actionLabel={t('common.inspect', {}, 'Inspect')}
          onClick={() => onSelectTab('vector')}
        />
      </div>
    </BackofficeSectionPanel>
  );
}

function ActionRequiredPanel({ items }: { items: PortalMonitoringOverviewAction[] }) {
  const { t } = useLocale();
  return (
    <BackofficeStackCard className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.monitoring.action_required', {}, 'Action required')}
          </h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {t('portal.monitoring.action_required_desc', {}, 'Prioritized items for the selected site.')}
          </p>
        </div>
        <BackofficeTag tone={items.some((item) => item.severity === 'error') ? 'danger' : 'info'}>
          {formatNumber(items.length)}
        </BackofficeTag>
      </div>
      {items.length ? (
        <div className="space-y-3">
          {items.slice(0, 5).map((item) => (
            <div key={`${item.code}-${item.source}`} className="rounded-[0.75rem] border border-slate-200 p-3 dark:border-slate-800">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.title}</p>
                  <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{item.detail}</p>
                </div>
                <BackofficeStatusBadge status={item.severity} label={item.source} />
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{item.suggested_action}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-[0.75rem] border border-dashed border-slate-200 p-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
          {t('portal.monitoring.no_immediate_actions', {}, 'No immediate action required.')}
        </div>
      )}
    </BackofficeStackCard>
  );
}

function QuotaPressurePanel({ quota }: { quota: PortalMonitoringOverviewSummary['quota'] | null }) {
  const { t } = useLocale();
  const rows: Array<{ key: 'runs' | 'tokens' | 'cost'; label: string; metric: PortalMonitoringOverviewQuotaMetric }> = quota
    ? [
        { key: 'runs', label: t('portal.monitoring.quota_runs', {}, 'Runs'), metric: quota.runs },
        { key: 'tokens', label: t('portal.monitoring.quota_tokens', {}, 'Tokens'), metric: quota.tokens },
        { key: 'cost', label: t('portal.monitoring.quota_cost', {}, 'Cost'), metric: quota.cost },
      ]
    : [];
  return (
    <BackofficeStackCard className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
          {t('portal.monitoring.quota_cost', {}, 'Quota & cost')}
        </h3>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
          {quota?.summary || t('portal.monitoring.no_quota_summary', {}, 'No quota summary yet.')}
        </p>
      </div>
      <div className="space-y-3">
        {rows.map((row) => (
          <QuotaPressureRow key={row.key} label={row.label} metric={row.metric} />
        ))}
      </div>
      {quota?.period_end_at ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {t('portal.monitoring.period_ends', {}, 'Period ends')} {formatDate(quota.period_end_at)}
        </p>
      ) : null}
    </BackofficeStackCard>
  );
}

function QuotaPressureRow({ label, metric }: { label: string; metric: PortalMonitoringOverviewQuotaMetric }) {
  const percent = Math.min(100, Math.max(0, Number(metric.usage_ratio || 0) * 100));
  const hasLimit = Number(metric.limit || 0) > 0;
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium text-slate-700 dark:text-slate-200">{label}</span>
        <span className="text-slate-500 dark:text-slate-400">
          {hasLimit ? `${formatNumber(metric.used)} / ${formatNumber(metric.limit)}` : 'unlimited'}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-900">
        <div
          className={`h-full rounded-full ${metric.over_limit || percent >= 90 ? 'bg-red-500' : percent >= 75 ? 'bg-amber-500' : 'bg-emerald-500'}`}
          style={{ width: hasLimit ? `${percent}%` : '0%' }}
        />
      </div>
    </div>
  );
}

function MonitoringOverviewCard({
  title,
  status,
  badge,
  detail,
  meta,
  actionLabel,
  onClick,
}: {
  title: string;
  status: string;
  badge: string;
  detail: string;
  meta: string;
  actionLabel: string;
  onClick: () => void;
}) {
  return (
    <BackofficeStackCard className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-950 dark:text-white">{title}</h3>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{detail}</p>
        </div>
        <BackofficeStatusBadge status={status} label={badge} />
      </div>
      <div className="flex items-center justify-between gap-3">
        <BackofficeTag tone={status === 'error' ? 'danger' : status === 'warning' ? 'warning' : 'info'}>
          {meta}
        </BackofficeTag>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onClick}>
          {actionLabel}
        </button>
      </div>
    </BackofficeStackCard>
  );
}

export default function PortalMonitoringPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalMonitoringContent />
    </Suspense>
  );
}
