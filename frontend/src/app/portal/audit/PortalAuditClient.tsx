'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import {
  PortalEmptyState,
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
  type PortalAuditEvent,
  type PortalAuditSummary,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatDate } from '@/lib/utils';

const AUDIT_EVENT_KIND_LABELS: Record<string, string> = {
  'site_admin_access.upsert': 'audit.kind.site_admin_access.upsert',
  'portal_magic_link.requested': 'audit.kind.portal_login_code.requested',
  'portal_magic_link.consumed': 'audit.kind.portal_login_code.verified',
  'api_key.created': 'audit.kind.api_key.created',
  'api_key.rotated': 'audit.kind.api_key.rotated',
  'api_key.revoked': 'audit.kind.api_key.revoked',
  'site.connected': 'audit.kind.site.connected',
  'site.disconnected': 'audit.kind.site.disconnected',
  'subscription.activated': 'audit.kind.subscription.activated',
  'subscription.updated': 'audit.kind.subscription.updated',
  'subscription.canceled': 'audit.kind.subscription.canceled',
};

export function PortalAuditClient() {
  const searchParams = useSearchParams();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { t } = useLocale();
  const { sites, selectedSiteId, selectedSite, isSwitchingSite, switchingSiteName, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });
  const [auditEvents, setAuditEvents] = useState<PortalAuditEvent[]>([]);
  const [auditSummary, setAuditSummary] = useState<PortalAuditSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const recentEvents = useMemo(() => auditEvents.slice(0, 10), [auditEvents]);
  const attentionEventCount = useMemo(() => {
    return recentEvents.filter((event) => event.outcome !== 'success').length;
  }, [recentEvents]);

  const loadActivity = async (siteId: string) => {
    if (!siteId) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const bundle = await portalClient.getAuditBundle(siteId, { limit: 10 });
      setAuditSummary(bundle.summary);
      setAuditEvents(bundle.events);
    } catch (err) {
      setError(
        formatPortalErrorMessage(err, t, t('audit.load_error', {}, 'Failed to load audit data'))
      );
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (!session || !isAuthenticated || !selectedSiteId) {
      setIsLoading(false);
      return;
    }
    void loadActivity(selectedSiteId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, selectedSiteId, session]);

  const handleSiteChange = async (siteId: string) => {
    await setSelectedSiteId(siteId);
    await loadActivity(siteId);
  };

  const translateOutcome = (outcome: string) => {
    if (outcome === 'error') {
      return t('common.error');
    }
    return t(`status.${outcome}`, {}, outcome);
  };

  const translateEventKind = (eventKind: string) => {
    const key = AUDIT_EVENT_KIND_LABELS[eventKind];
    if (key) {
      return t(key);
    }
    return t('portal.audit.generic_activity', {}, 'Service activity');
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
        onRetry={() => void loadActivity(selectedSiteId)}
      />
    );
  }

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.selected_site')}
        title={t('portal.audit.nav_label', {}, 'Recent activity')}
        eyebrowInfo={t('portal.audit.customer_desc', {}, 'Review recent sign-in and service activity for the selected site.')}
        currentPage="audit"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSite?.site_name}
        sites={sites}
        onSiteChange={handleSiteChange}
        metrics={[
          { label: t('portal.audit.records_total', {}, 'Total records'), value: auditSummary?.totals?.events || 0 },
          { label: t('portal.audit.visible_records', {}, 'Visible records'), value: recentEvents.length },
          {
            label: t('portal.audit.attention_records', {}, 'Need review'),
            value: attentionEventCount,
            detail:
              attentionEventCount > 0
                ? t('portal.audit.attention_records_desc', {}, 'Some records may need support follow-up.')
                : t('portal.audit.no_attention_records_desc', {}, 'No issue is visible in this view.'),
          },
          {
            label: t('portal.updated_at', {}, 'Updated'),
            value: auditSummary?.generated_at ? formatDate(auditSummary.generated_at) : t('portal.home.package_pending_label', {}, 'To confirm'),
            size: 'compact',
          },
        ]}
        metricsColumnsClassName="xl:grid-cols-4"
        secondaryActions={
          <button type="button" className="btn btn-secondary" onClick={() => void loadActivity(selectedSiteId)}>
            {t('common.refresh', {}, 'Refresh')}
          </button>
        }
      />

      {isSwitchingSite ? (
        <PortalSiteSwitchingNotice
          message={t(
            'portal.site_switching_notice_with_target',
            { site: switchingSiteName || selectedSite?.site_name || selectedSiteId },
            `Switching to ${switchingSiteName || selectedSite?.site_name || selectedSiteId}. Page data will update automatically.`
          )}
        />
      ) : null}

      <BackofficeSectionPanel className="overflow-hidden p-0">
        <div className="border-b border-gray-200 px-6 py-5 dark:border-gray-800">
          <h2 className="text-xl font-semibold text-gray-950 dark:text-white">{t('portal.audit.nav_label', {}, 'Recent activity')}</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {t('portal.audit.recent_desc', {}, 'Only recent customer-readable activity is shown here.')}
          </p>
        </div>
        {recentEvents.length === 0 ? (
          <div className="p-6">
            <PortalEmptyState
              title={t('portal.audit.empty_title', {}, 'No activity in this view')}
              description={t(
                'portal.audit.empty_desc',
                {},
                'No site activity is visible yet. Return to the workspace or check again later.'
              )}
              actionLabel={t('portal.workspace_label', {}, 'Workspace')}
              actionHref="/portal"
            />
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-800">
            {recentEvents.map((event) => (
              <article key={event.event_id} className="px-6 py-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span className="font-medium">{translateEventKind(event.event_kind)}</span>
                      <BackofficeStatusBadge status={event.outcome} label={translateOutcome(event.outcome)} />
                    </div>
                    <p className="text-sm text-gray-500">{formatDate(event.created_at)}</p>
                  </div>
                  {event.outcome !== 'success' ? (
                    <BackofficeStackCard className="max-w-md border-amber-200 bg-amber-50/70 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
                      {t('portal.audit.support_hint', {}, 'Contact support with the site name and activity time.')}
                    </BackofficeStackCard>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}
