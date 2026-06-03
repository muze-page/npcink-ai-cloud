'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { BackofficePageStack } from '@/components/backoffice/BackofficeScaffold';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { PortalErrorState, PortalLoadingState, PortalSignedOutState } from '@/components/portal/PortalPageState';
import { PortalMediaProcessingPanel } from '@/components/portal/PortalMediaProcessingPanel';
import { PortalPluginMonitoringPanel } from '@/components/portal/PortalPluginMonitoringPanel';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalMediaObservabilitySummary,
  type PortalPluginObservabilitySummary,
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

function PortalMonitoringContent() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const { session, isLoading, isAuthenticated, selectSite } = useSession();
  const [summary, setSummary] = useState<PortalPluginObservabilitySummary | null>(null);
  const [mediaSummary, setMediaSummary] = useState<PortalMediaObservabilitySummary | null>(null);
  const [isSummaryLoading, setIsSummaryLoading] = useState(false);
  const [isMediaSummaryLoading, setIsMediaSummaryLoading] = useState(false);
  const [error, setError] = useState('');
  const [mediaError, setMediaError] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const requestedSiteId = searchParams.get('site') || '';
  const sites = session?.sites || [];
  const selectedSite = resolveSelectedSite(sites, requestedSiteId, session?.site_id || '');
  const selectedSiteId = selectedSite?.site_id || '';

  useEffect(() => {
    if (!selectedSiteId) {
      setSummary(null);
      setMediaSummary(null);
      setError('');
      setMediaError('');
      return;
    }

    let isCancelled = false;
    setIsSummaryLoading(true);
    setIsMediaSummaryLoading(true);
    setError('');
    setMediaError('');

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
          'Connect a WordPress site before plugin monitoring can be displayed.'
        )}
        retryLabel={t('common.retry')}
        onRetry={() => window.location.reload()}
      />
    );
  }

  const totals = summary?.totals || null;

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.monitoring.eyebrow', {}, 'Plugin monitoring')}
        title={t('portal.monitoring.page_title', {}, 'Plugin monitoring')}
        description={t(
          'portal.monitoring.page_desc',
          {},
          'Read-only monitoring for the selected WordPress site. Admin-only cross-site data stays in the Cloud admin console.'
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
            label: t('portal.monitoring.events', {}, 'Events'),
            value: totals ? formatNumber(Number(totals.events_total || 0)) : t('common.not_found'),
            detail: summary?.window?.hours ? `${summary.window.hours}h` : t('common.not_found'),
          },
          {
            label: t('portal.monitoring.errors', {}, 'Errors'),
            value: totals ? formatNumber(Number(totals.error_total || 0)) : t('common.not_found'),
            detail: t('portal.monitoring.error_detail', {}, 'Metadata-only'),
          },
          {
            label: t('portal.monitoring.plugins', {}, 'Plugins'),
            value: summary ? formatNumber(summary.plugins.length) : t('common.not_found'),
            detail: t('portal.monitoring.plugins_detail', {}, 'Reporting plugins'),
          },
          {
            label: t('portal.monitoring.last_seen', {}, 'Last seen'),
            value: totals?.last_seen_at ? formatDate(totals.last_seen_at) : t('common.not_found'),
            detail: t('portal.monitoring.last_seen_detail', {}, 'Cloud received'),
          },
        ]}
      />

      <PortalPluginMonitoringPanel
        siteId={selectedSiteId}
        summary={summary}
        isLoading={isSummaryLoading}
        error={error}
        onRetry={() => setRefreshNonce((current) => current + 1)}
      />

      <PortalMediaProcessingPanel
        summary={mediaSummary}
        isLoading={isMediaSummaryLoading}
        error={mediaError}
        onRetry={() => setRefreshNonce((current) => current + 1)}
      />
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
