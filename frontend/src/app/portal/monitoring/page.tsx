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
  type PortalDiagnosticAdvisorSummary,
  type PortalDiagnosticItem,
  type PortalMediaObservabilitySummary,
  type PortalMonitoringOverviewAction,
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

function diagnosticWorkflowLabel(status: string): string {
  if (status === 'acknowledged') return 'acknowledged';
  if (status === 'muted') return 'muted';
  if (status === 'resolved') return 'resolved';
  return 'new';
}

function diagnosticWorkflowTone(status: string): string {
  if (status === 'resolved') return 'success';
  if (status === 'muted') return 'inactive';
  if (status === 'acknowledged') return 'warning';
  return 'warning';
}

function resolveActionTarget(
  item: PortalMonitoringOverviewAction,
  siteId: string
): { tab?: MonitoringTab; href?: string; label: string } | null {
  const source = String(item.source || '').toLowerCase();
  if (source === 'plugins') return { tab: 'plugins', label: 'Open Plugins' };
  if (source === 'media') return { tab: 'media', label: 'Open Media' };
  if (source === 'vector') return { tab: 'vector', label: 'Open Vector' };
  if (source === 'quota' || source === 'runtime') {
    return { href: `/portal/usage?site=${encodeURIComponent(siteId)}`, label: 'Open Usage' };
  }
  if (source === 'keys' || source === 'activity') {
    return { href: `/portal/keys?site=${encodeURIComponent(siteId)}`, label: 'Open Keys' };
  }
  return null;
}

function diagnosticItemToAction(item: PortalDiagnosticItem): PortalMonitoringOverviewAction {
  return {
    code: item.code,
    severity: item.severity === 'error' ? 'error' : 'warning',
    source: item.source,
    title: item.title,
    detail: item.evidence_summary || item.likely_cause,
    suggested_action: item.next_step,
  };
}

function PortalMonitoringContent() {
  const { t } = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { session, isLoading, isAuthenticated, selectSite } = useSession();
  const [monitoringOverview, setMonitoringOverview] = useState<PortalMonitoringOverviewSummary | null>(null);
  const [diagnosticAdvisor, setDiagnosticAdvisor] = useState<PortalDiagnosticAdvisorSummary | null>(null);
  const [summary, setSummary] = useState<PortalPluginObservabilitySummary | null>(null);
  const [mediaSummary, setMediaSummary] = useState<PortalMediaObservabilitySummary | null>(null);
  const [vectorSummary, setVectorSummary] = useState<PortalVectorObservabilitySummary | null>(null);
  const [isMonitoringOverviewLoading, setIsMonitoringOverviewLoading] = useState(false);
  const [isDiagnosticAdvisorLoading, setIsDiagnosticAdvisorLoading] = useState(false);
  const [isSummaryLoading, setIsSummaryLoading] = useState(false);
  const [isMediaSummaryLoading, setIsMediaSummaryLoading] = useState(false);
  const [isVectorSummaryLoading, setIsVectorSummaryLoading] = useState(false);
  const [monitoringOverviewError, setMonitoringOverviewError] = useState('');
  const [diagnosticAdvisorError, setDiagnosticAdvisorError] = useState('');
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
      setDiagnosticAdvisor(null);
      setSummary(null);
      setMediaSummary(null);
      setVectorSummary(null);
      setMonitoringOverviewError('');
      setDiagnosticAdvisorError('');
      setError('');
      setMediaError('');
      setVectorError('');
      return;
    }
    if (lastLoadedSiteRef.current !== selectedSiteId) {
      lastLoadedSiteRef.current = selectedSiteId;
      setMonitoringOverview(null);
      setDiagnosticAdvisor(null);
      setSummary(null);
      setMediaSummary(null);
      setVectorSummary(null);
      setMonitoringOverviewError('');
      setDiagnosticAdvisorError('');
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

      setIsDiagnosticAdvisorLoading(true);
      setDiagnosticAdvisorError('');
      void portalClient
        .getDiagnosticAdvisor(selectedSiteId, { windowHours: 24 })
        .then((response) => {
          if (!isCancelled) {
            setDiagnosticAdvisor(response.data);
          }
        })
        .catch((err) => {
          if (!isCancelled) {
            setDiagnosticAdvisor(null);
            setDiagnosticAdvisorError(formatPortalErrorMessage(err, t, t('error.failed_load')));
          }
        })
        .finally(() => {
          if (!isCancelled) {
            setIsDiagnosticAdvisorLoading(false);
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

  const openActionTarget = (item: PortalMonitoringOverviewAction) => {
    const target = resolveActionTarget(item, selectedSiteId);
    if (!target) return;
    if (target.tab) {
      changeTab(target.tab);
      return;
    }
    if (target.href) {
      router.push(target.href);
    }
  };

  const openDiagnosticTarget = (item: PortalDiagnosticItem) => {
    openActionTarget(diagnosticItemToAction(item));
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
          diagnosticAdvisor={diagnosticAdvisor}
          isLoading={isOverviewLoading}
          isDiagnosticAdvisorLoading={isDiagnosticAdvisorLoading}
          errors={[monitoringOverviewError].filter(Boolean)}
          diagnosticAdvisorError={diagnosticAdvisorError}
          onRefresh={() => setRefreshNonce((current) => current + 1)}
          onSelectTab={changeTab}
          onSelectAction={openActionTarget}
          onSelectDiagnostic={openDiagnosticTarget}
          selectedSiteId={selectedSiteId}
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
  diagnosticAdvisor,
  isLoading,
  isDiagnosticAdvisorLoading,
  errors,
  diagnosticAdvisorError,
  onRefresh,
  onSelectTab,
  onSelectAction,
  onSelectDiagnostic,
  selectedSiteId,
}: {
  monitoringOverview: PortalMonitoringOverviewSummary | null;
  diagnosticAdvisor: PortalDiagnosticAdvisorSummary | null;
  isLoading: boolean;
  isDiagnosticAdvisorLoading: boolean;
  errors: string[];
  diagnosticAdvisorError: string;
  onRefresh: () => void;
  onSelectTab: (tab: MonitoringTab) => void;
  onSelectAction: (item: PortalMonitoringOverviewAction) => void;
  onSelectDiagnostic: (item: PortalDiagnosticItem) => void;
  selectedSiteId: string;
}) {
  const { t } = useLocale();
  const actionItems = monitoringOverview?.action_required || [];
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
              'Only the items that need attention are shown here. Use the tabs for detail.'
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

      <DiagnosticAdvisorPanel
        advisor={diagnosticAdvisor}
        isLoading={isDiagnosticAdvisorLoading}
        error={diagnosticAdvisorError}
        onSelectDiagnostic={onSelectDiagnostic}
        selectedSiteId={selectedSiteId}
      />

      <ActionRequiredPanel
        items={actionItems}
        onSelectAction={onSelectAction}
        selectedSiteId={selectedSiteId}
      />

      <div className="grid gap-4 xl:grid-cols-3">
        <MonitoringOverviewCard
          title={t('portal.monitoring.card_plugins', {}, 'Plugins')}
          status={statusTone(pluginComponent?.status || 'inactive')}
          badge={`${pluginComponent?.status || 'inactive'} · ${pluginComponent?.score ?? 0}`}
          detail={pluginComponent?.summary || t('portal.monitoring.no_plugin_summary', {}, 'No plugin summary yet.')}
          meta={`${formatNumber(Number(activity?.plugin_errors_total || 0))} errors`}
          actionLabel={t('common.inspect', {}, 'Inspect')}
          onClick={() => onSelectTab('plugins')}
        />
        <MonitoringOverviewCard
          title={t('portal.monitoring.card_media', {}, 'Media')}
          status={statusTone(mediaComponent?.status || 'inactive')}
          badge={`${mediaComponent?.status || 'inactive'} · ${mediaComponent?.score ?? 0}`}
          detail={mediaComponent?.summary || t('portal.monitoring.no_media_summary', {}, 'No media summary yet.')}
          meta={`${formatNumber(Number(activity?.media_failed_total || 0))} failed jobs`}
          actionLabel={t('common.inspect', {}, 'Inspect')}
          onClick={() => onSelectTab('media')}
        />
        <MonitoringOverviewCard
          title={t('portal.monitoring.card_vector', {}, 'Vector')}
          status={statusTone(vectorComponent?.status || 'inactive')}
          badge={`${vectorComponent?.status || 'inactive'} · ${vectorComponent?.score ?? 0}`}
          detail={vectorComponent?.summary || t('portal.monitoring.no_vector_summary', {}, 'No vector summary yet.')}
          meta={`${formatNumber(Number(activity?.vector_searches_total || 0))} searches`}
          actionLabel={t('common.inspect', {}, 'Inspect')}
          onClick={() => onSelectTab('vector')}
        />
      </div>
    </BackofficeSectionPanel>
  );
}

function DiagnosticAdvisorPanel({
  advisor,
  isLoading,
  error,
  onSelectDiagnostic,
  selectedSiteId,
}: {
  advisor: PortalDiagnosticAdvisorSummary | null;
  isLoading: boolean;
  error: string;
  onSelectDiagnostic: (item: PortalDiagnosticItem) => void;
  selectedSiteId: string;
}) {
  const { t } = useLocale();
  const items = advisor?.diagnostic_items || [];
  const visibleItems = items.slice(0, 3);
  const workflow = advisor?.diagnostic_workflow;
  const evidenceWindow = advisor?.evidence_window;
  const evidenceWindowLabel = evidenceWindow?.hours
    ? `${evidenceWindow.hours}h`
    : String(advisor?.filters?.window_hours || '');
  const hasUnsafeWritePosture =
    Boolean(advisor?.safety?.direct_wordpress_write) || Boolean(advisor?.safety?.automatic_repair_allowed);
  const status = advisor?.severity || advisor?.status || (items.length ? 'warning' : 'inactive');
  return (
    <BackofficeStackCard className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('portal.monitoring.diagnostic_advisor', {}, 'Site diagnostics')}
            </h3>
            <BackofficeStatusBadge
              status={status}
              label={advisor?.status || (isLoading ? 'loading' : items.length ? 'attention' : 'inactive')}
            />
          </div>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {advisor?.summary ||
              t(
                'portal.monitoring.diagnostic_advisor_desc',
                {},
                'Cloud summarizes monitoring signals into reviewable next steps for this site.'
              )}
          </p>
        </div>
        <BackofficeTag tone={hasUnsafeWritePosture ? 'danger' : 'info'}>
          {hasUnsafeWritePosture
            ? t('portal.monitoring.write_posture_invalid', {}, 'write posture blocked')
            : t('portal.monitoring.suggestion_only', {}, 'suggestion only')}
        </BackofficeTag>
      </div>

      {advisor ? (
        <BackofficeMetricStrip
          columnsClassName="md:grid-cols-2 xl:grid-cols-4"
          items={[
            {
              label: t('portal.monitoring.diagnostic_new', {}, 'New'),
              value: formatNumber(Number(workflow?.new || 0)),
              detail: t('portal.monitoring.diagnostic_new_detail', {}, 'Needs review'),
              size: 'compact',
            },
            {
              label: t('portal.monitoring.diagnostic_acknowledged', {}, 'Acknowledged'),
              value: formatNumber(Number(workflow?.acknowledged || 0)),
              detail: t('portal.monitoring.diagnostic_acknowledged_detail', {}, 'Operator noted'),
              size: 'compact',
            },
            {
              label: t('portal.monitoring.evidence_window', {}, 'Evidence window'),
              value: evidenceWindowLabel || t('common.not_found'),
              detail: evidenceWindow?.end_at
                ? `${t('portal.monitoring.window_end', {}, 'Ends')}: ${formatDate(evidenceWindow.end_at)}`
                : t('common.not_found'),
              size: 'compact',
            },
            {
              label: t('portal.monitoring.generated_at', {}, 'Generated'),
              value: advisor.generated_at ? formatDate(advisor.generated_at) : t('common.not_found'),
              detail: `${t('portal.monitoring.diagnostic_total', {}, 'Total')}: ${formatNumber(Number(workflow?.total || items.length))}`,
              size: 'compact',
            },
          ]}
        />
      ) : null}

      {isLoading ? (
        <div className="rounded-[0.75rem] border border-dashed border-slate-200 p-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
          {t('portal.monitoring.loading_diagnostics', {}, 'Loading diagnostic recommendations.')}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-[0.75rem] border border-amber-200 bg-amber-50/70 p-4 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
          {error}
        </div>
      ) : null}

      {!isLoading && !error && items.length ? (
        <div className="divide-y divide-slate-200 overflow-hidden rounded-[0.75rem] border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {visibleItems.map((item) => {
            const target = resolveActionTarget(diagnosticItemToAction(item), selectedSiteId);
            return (
              <button
                key={`${item.code}-${item.recommended_action_id}`}
                type="button"
                aria-label={`${item.title} ${target?.label || ''}`.trim()}
                onClick={() => {
                  onSelectDiagnostic(item);
                }}
                className="block w-full cursor-pointer p-4 text-left transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-slate-300 dark:hover:bg-slate-900/50 dark:focus:ring-slate-700"
              >
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.title}</p>
                      <BackofficeStatusBadge status={item.severity} label={item.source} />
                      <BackofficeStatusBadge
                        status={diagnosticWorkflowTone(item.workflow_status)}
                        label={diagnosticWorkflowLabel(item.workflow_status)}
                      />
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {item.evidence_summary}
                    </p>
                    <div className="mt-3 grid gap-3 text-xs leading-5 text-slate-500 dark:text-slate-400 md:grid-cols-2">
                      <p>
                        <span className="font-semibold text-slate-700 dark:text-slate-200">
                          {t('portal.monitoring.likely_cause', {}, 'Likely cause')}:
                        </span>{' '}
                        {item.likely_cause}
                      </p>
                      <p>
                        <span className="font-semibold text-slate-700 dark:text-slate-200">
                          {t('portal.monitoring.next_step', {}, 'Next step')}:
                        </span>{' '}
                        {item.next_step}
                      </p>
                    </div>
                  </div>
                  {target ? (
                    <span className="shrink-0 space-y-1 text-xs font-semibold leading-5 text-slate-700 dark:text-slate-200">
                      <span className="block">{target.label}</span>
                      {item.last_updated_at ? (
                        <span className="block font-medium text-slate-500 dark:text-slate-400">
                          {formatDate(item.last_updated_at)}
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                </div>
              </button>
            );
          })}
        </div>
      ) : null}

      {!isLoading && !error && !items.length ? (
        <div className="rounded-[0.75rem] border border-dashed border-slate-200 p-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
          {t('portal.monitoring.no_diagnostic_items', {}, 'No diagnostic recommendations for this site.')}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
        <span>{t('portal.monitoring.advisor_safety', {}, 'Operator review required')}</span>
        <span aria-hidden="true">·</span>
        <span>{t('portal.monitoring.no_wordpress_write', {}, 'No direct WordPress write')}</span>
        {advisor?.confidence ? (
          <>
            <span aria-hidden="true">·</span>
            <span>{`${t('portal.monitoring.confidence', {}, 'Confidence')}: ${advisor.confidence}`}</span>
          </>
        ) : null}
      </div>
    </BackofficeStackCard>
  );
}

function ActionRequiredPanel({
  items,
  onSelectAction,
  selectedSiteId,
}: {
  items: PortalMonitoringOverviewAction[];
  onSelectAction: (item: PortalMonitoringOverviewAction) => void;
  selectedSiteId: string;
}) {
  const { t } = useLocale();
  const visibleItems = items.slice(0, 3);
  return (
    <BackofficeStackCard className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.monitoring.action_required', {}, 'Action required')}
          </h3>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {t('portal.monitoring.action_required_desc', {}, 'Top items for the selected site.')}
          </p>
        </div>
        <BackofficeTag tone={items.some((item) => item.severity === 'error') ? 'danger' : 'info'}>
          {formatNumber(items.length)}
        </BackofficeTag>
      </div>
      {items.length ? (
        <div className="space-y-3">
          {visibleItems.map((item) => {
            const target = resolveActionTarget(item, selectedSiteId);
            return (
            <button
              key={`${item.code}-${item.source}`}
              type="button"
              onClick={() => {
                onSelectAction(item);
              }}
              className="block w-full cursor-pointer rounded-[0.75rem] border border-slate-200 p-3 text-left transition hover:border-slate-300 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-300 dark:border-slate-800 dark:hover:border-slate-700 dark:hover:bg-slate-900/50 dark:focus:ring-slate-700"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.title}</p>
                  <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{item.detail}</p>
                </div>
                <BackofficeStatusBadge status={item.severity} label={item.source} />
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                <span>{item.suggested_action}</span>
                {target ? (
                  <span className="font-semibold text-slate-700 dark:text-slate-200">
                    {target.label}
                  </span>
                ) : null}
              </div>
            </button>
          );
          })}
          {items.length > visibleItems.length ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t(
                'portal.monitoring.more_actions_in_tabs',
                {},
                `${items.length - visibleItems.length} more item(s) are available in the detail tabs.`
              )}
            </p>
          ) : null}
        </div>
      ) : (
        <div className="rounded-[0.75rem] border border-dashed border-slate-200 p-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
          {t('portal.monitoring.no_immediate_actions', {}, 'No immediate action required.')}
        </div>
      )}
    </BackofficeStackCard>
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
