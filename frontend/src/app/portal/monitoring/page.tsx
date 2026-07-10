'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { PortalErrorState, PortalLoadingState, PortalSignedOutState } from '@/components/portal/PortalPageState';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalMonitoringOverviewAction,
  type PortalMonitoringOverviewSummary,
  type Site,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { getPortalSiteDisplayName } from '@/lib/portal-site-display';
import { formatDate, formatNumber } from '@/lib/utils';

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

function statusLabel(status: string, issueCount: number, t: ReturnType<typeof useLocale>['t']): string {
  if (status === 'ok' && issueCount === 0) {
    return t('portal.home.risk_level_normal', {}, 'Normal');
  }
  if (status === 'inactive') {
    return t('status.inactive', {}, 'Inactive');
  }
  return t('portal.home.filter_attention_only', {}, 'Needs attention');
}

function statusTone(status: string, issueCount: number): string {
  if (status === 'ok' && issueCount === 0) return 'active';
  if (status === 'error') return 'error';
  return 'warning';
}

function customerIssueTitle(item: PortalMonitoringOverviewAction, t: ReturnType<typeof useLocale>['t']): string {
  const raw = `${item.title || ''} ${item.code || ''}`.toLowerCase();
  if (raw.includes('runtime') || raw.includes('success')) {
    return t('portal.monitoring.customer_issue_service_success', {}, 'Service success rate needs attention');
  }
  if (raw.includes('plugin') || raw.includes('connection')) {
    return t('portal.monitoring.customer_issue_connection_activity', {}, 'Site connection needs attention');
  }
  if (raw.includes('quota') || raw.includes('usage')) {
    return t('portal.monitoring.quota_pressure', {}, 'Usage pressure');
  }
  return t('portal.monitoring.customer_issue_general', {}, 'Service item needs attention');
}

function PortalMonitoringContent() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const { session, isLoading, isAuthenticated, selectSite } = useSession();
  const [overview, setOverview] = useState<PortalMonitoringOverviewSummary | null>(null);
  const [isOverviewLoading, setIsOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const requestedSiteId = searchParams.get('site') || '';
  const sites = session?.sites || [];
  const selectedSite = resolveSelectedSite(sites, requestedSiteId, session?.site_id || '');
  const selectedSiteId = selectedSite?.site_id || '';

  useEffect(() => {
    if (!selectedSiteId) {
      setOverview(null);
      setOverviewError('');
      return;
    }

    let isCancelled = false;
    setIsOverviewLoading(true);
    setOverviewError('');
    void portalClient
      .getMonitoringOverview(selectedSiteId, { windowHours: 24 })
      .then((response) => {
        if (!isCancelled) {
          setOverview(response.data);
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          setOverview(null);
          setOverviewError(formatPortalErrorMessage(err, t, t('portal.monitoring.load_failed', {}, 'Service status could not be loaded for the current site.')));
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setIsOverviewLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [refreshNonce, selectedSiteId, t]);

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
          'Connect a WordPress site before service status can be displayed.'
        )}
        retryLabel={t('common.retry')}
        onRetry={() => window.location.reload()}
      />
    );
  }

  const issueCount = overview?.action_required.length || 0;
  const healthStatus = overview?.health.status || 'inactive';
  const currentStatusLabel = statusLabel(healthStatus, issueCount, t);
  const latestActivityAt = overview?.activity.last_seen_at || overview?.generated_at || '';

  return (
    <BackofficePageStack data-portal-support-deeplink="monitoring">
      <PortalWorkspaceHeader
        eyebrow={t('portal.monitoring.eyebrow', {}, 'Service status')}
        title={t('portal.monitoring.page_title', {}, 'Service status')}
        description={t(
          'portal.monitoring.page_desc',
          {},
          'Check whether the selected site needs attention. This page is read only.'
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
            label: t('portal.monitoring.site_health', {}, 'Site status'),
            value: overview ? currentStatusLabel : t('portal.home.package_pending_label', {}, 'To confirm'),
            detail: t('portal.monitoring.service_check_detail', {}, 'Only customer-readable items are shown here.'),
          },
          {
            label: t('portal.monitoring.actions_required', {}, 'Action required'),
            value: overview ? formatNumber(issueCount) : t('portal.home.package_pending_label', {}, 'To confirm'),
            detail: t('portal.monitoring.diagnostic_total_detail', {}, 'Visible items'),
          },
          {
            label: t('portal.monitoring.last_activity', {}, 'Last activity'),
            value: latestActivityAt ? formatDate(latestActivityAt) : t('portal.home.package_pending_label', {}, 'To confirm'),
            detail: t('portal.monitoring.last_activity_detail', {}, 'Updated'),
          },
        ]}
        metricsColumnsClassName="lg:grid-cols-3"
        secondaryActions={
          <button type="button" className="btn btn-secondary" onClick={() => setRefreshNonce((current) => current + 1)}>
            {t('common.refresh', {}, 'Refresh')}
          </button>
        }
      />

      <BackofficeSectionPanel className="space-y-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
              {t('portal.monitoring.overview_title', {}, 'Service overview')}
            </h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t(
                'portal.monitoring.overview_desc',
                {},
                'Only the items that need attention are shown here. Contact support if an item stays visible.'
              )}
            </p>
          </div>
          <BackofficeStatusBadge
            status={statusTone(healthStatus, issueCount)}
            label={overview ? currentStatusLabel : t('common.loading')}
          />
        </div>

        {isOverviewLoading ? (
          <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
            {t('common.loading')}
          </BackofficeStackCard>
        ) : null}

        {overviewError ? (
          <BackofficeStackCard className="border-amber-200 bg-amber-50/70 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
            {overviewError}
          </BackofficeStackCard>
        ) : null}

        {overview ? (
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-3"
            items={[
              {
                label: t('portal.monitoring.events', {}, 'Activity'),
                value: formatNumber(Number(overview.activity.plugin_events_total || 0)),
                detail: t('portal.monitoring.last_seen_detail', {}, 'Updated'),
                size: 'compact',
              },
              {
                label: t('portal.monitoring.errors', {}, 'Issues'),
                value: formatNumber(Number(overview.activity.plugin_errors_total || 0)),
                detail: t('portal.monitoring.error_detail', {}, 'No private content shown'),
                size: 'compact',
              },
              {
                label: t('portal.monitoring.quota_pressure', {}, 'Usage pressure'),
                value: overview.quota.top_pressure === 'none'
                  ? t('portal.home.risk_level_normal', {}, 'Normal')
                  : t('portal.home.filter_attention_only', {}, 'Needs attention'),
                detail: t('portal.monitoring.status_plain_detail', {}, 'Review the plan page if usage needs attention.'),
                size: 'compact',
              },
            ]}
          />
        ) : null}

        {!isOverviewLoading && !overviewError && overview && issueCount > 0 ? (
          <div className="divide-y divide-slate-200 overflow-hidden rounded-[0.75rem] border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {overview.action_required.slice(0, 3).map((item) => (
              <div key={`${item.code}-${item.source}`} className="p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-slate-950 dark:text-white">
                        {customerIssueTitle(item, t)}
                      </p>
                      <BackofficeStatusBadge
                        status={item.severity === 'error' ? 'error' : 'warning'}
                        label={t('portal.home.filter_attention_only', {}, 'Needs attention')}
                      />
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {t('portal.monitoring.customer_issue_detail', {}, 'If this keeps showing, contact support and include the site name.')}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}

        {!isOverviewLoading && !overviewError && overview && issueCount === 0 ? (
          <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
            {t('portal.monitoring.no_diagnostic_items', {}, 'No suggestions for this site.')}
          </BackofficeStackCard>
        ) : null}
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function PortalMonitoringPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalMonitoringContent />
    </Suspense>
  );
}
