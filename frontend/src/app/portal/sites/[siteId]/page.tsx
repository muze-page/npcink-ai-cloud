'use client';

import React, { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { PortalPageStack, PortalSection, PortalCard } from '@/components/portal/PortalScaffold';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import { PortalSiteKnowledgePanel } from '@/components/portal/PortalSiteKnowledgePanel';
import { PortalSiteServiceStatus } from '@/components/portal/PortalSiteServiceStatus';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { PortalErrorState, PortalLoadingState, PortalSignedOutState } from '@/components/portal/PortalPageState';
import { Modal } from '@/components/ui/Modal';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteMonitoring } from '@/hooks/usePortalSiteMonitoring';
import { usePortalSiteKnowledge } from '@/hooks/usePortalSiteKnowledge';
import { useSession } from '@/hooks/useSession';
import { portalClient, type PortalSiteSummaryRecord, type Site } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import {
  getPortalSiteDisplayName,
  getPortalSiteUrl,
} from '@/lib/portal-site-display';

function PortalSiteRecordContent() {
  const params = useParams<{ siteId?: string }>();
  const router = useRouter();
  const siteId = String(params?.siteId || '');
  const { t } = useLocale();
  const { session, isLoading, isAuthenticated, refresh } = useSession();
  const [summary, setSummary] = useState<PortalSiteSummaryRecord | null>(null);
  const [error, setError] = useState('');
  const [showRemoveModal, setShowRemoveModal] = useState(false);
  const [removeError, setRemoveError] = useState('');
  const [isRemovingSite, setIsRemovingSite] = useState(false);
  const siteMonitoring = usePortalSiteMonitoring(siteId, t);
  const siteKnowledge = usePortalSiteKnowledge(siteId, t);

  useEffect(() => {
    setSummary(null);
    setError('');
    if (!isAuthenticated || !siteId) return;
    let alive = true;
    portalClient
      .getSiteSummary(siteId)
      .then((response) => {
        if (alive) {
          setSummary(response.data);
        }
      })
      .catch((err) => {
        if (alive) {
          setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
        }
      });

    return () => {
      alive = false;
    };
  }, [isAuthenticated, siteId, t]);

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

  if (error) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={error}
        retryLabel={t('common.retry')}
        onRetry={() => window.location.reload()}
      />
    );
  }

  if (!summary) {
    return <PortalLoadingState message={t('common.loading')} />;
  }

  const sessionSite = session.sites.find((item) => item.site_id === siteId) || null;
  const site: Site = {
    site_id: siteId,
    name: summary.site?.name || sessionSite?.name || siteId,
    site_url: summary.site?.site_url || sessionSite?.site_url || '',
    platform_kind: summary.site?.platform_kind || sessionSite?.platform_kind || 'wordpress',
    status: summary.site?.status || sessionSite?.status || 'inactive',
  };
  const siteUrl = getPortalSiteUrl(site);
  const monitoringNeedsAttention = siteMonitoring.overview
    ? siteMonitoring.overview.health.status !== 'ok'
      || siteMonitoring.overview.action_required.length > 0
      || siteMonitoring.overview.quota.top_pressure !== 'none'
    : false;
  const siteNeedsAttention = site.status !== 'active'
    || !siteUrl
    || Boolean(summary.customer_status?.needs_attention)
    || monitoringNeedsAttention;
  const siteStatusLabel = siteNeedsAttention
    ? t('portal.home.filter_attention_only', {}, 'Needs attention')
    : t('portal.home.risk_level_normal', {}, 'Normal');
  const canRemoveThisSite = Boolean(
    session.selected_context?.site.site_id === siteId
    && session.selected_context.allowed_actions.includes('remove_sites')
    && site.status !== 'archived'
    && site.status !== 'suspended'
  );

  const closeRemoveModal = () => {
    if (isRemovingSite) return;
    setShowRemoveModal(false);
    setRemoveError('');
  };

  const handleRemoveSite = async () => {
    if (!canRemoveThisSite) return;
    setIsRemovingSite(true);
    setRemoveError('');
    try {
      await portalClient.removeSite(site.site_id);
      await refresh();
      router.push('/portal#sites');
    } catch (err) {
      setRemoveError(
        formatPortalErrorMessage(
          err,
          t,
          t('portal.site_remove_failed', {}, 'Failed to remove this site.')
        )
      );
    } finally {
      setIsRemovingSite(false);
    }
  };

  return (
    <PortalPageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.site_record_label', {}, 'Site summary')}
        title={getPortalSiteDisplayName(site)}
        currentPage="record"
        selectedSiteId={siteId}
        selectedSiteName={getPortalSiteDisplayName(site)}
        sites={session.sites}
        showSiteContextSummary
        metrics={[
          {
            label: t('common.status', {}, 'Status'),
            value: siteStatusLabel,
            detail: siteNeedsAttention
              ? t('portal.site_record_attention_action', {}, 'The site status or address needs confirmation.')
              : t('portal.site_record_ready_action', {}, 'No action is needed for this site right now.'),
          },
          {
            label: t('portal.site_address_label', {}, 'Site address'),
            value: siteUrl ? t('portal.site_address_configured', {}, 'Configured') : t('portal.site_url_missing_short', {}, 'Site URL not configured'),
            detail: siteUrl || t('portal.site_record_address_missing_detail', {}, 'Add a site address so support can identify this site faster.'),
          },
        ]}
      />

      <PortalSection className="space-y-4" variant="portal">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">
            {t('portal.site_record_current_label', {}, 'Site record')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
            {t('portal.site_record_current_title', {}, 'What needs attention?')}
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {siteNeedsAttention
              ? t(
                'portal.site_record_attention_desc',
                {},
                'This site still has information to confirm. Contact support if it looks wrong.'
              )
              : t(
                'portal.site_record_ready_desc',
                {},
                'This site address and service status look normal.'
              )}
          </p>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <PortalCard variant="portal">
            <div className="flex h-full flex-col items-start justify-between gap-4">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-slate-950 dark:text-white">
                  {t('portal.nav_account', {}, 'Contact')}
                </p>
                <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t(
                    'portal.site_record_contact_desc',
                    {},
                    'Use the Account page to confirm the email and service contact details for this account.'
                  )}
                </p>
              </div>
              <Link href="/portal/account" className="btn btn-secondary btn-sm">
                {t('portal.site_record_contact_action', {}, 'Open account')}
              </Link>
            </div>
          </PortalCard>
          <PortalCard variant="portal">
            <div className="flex h-full items-start justify-between gap-3">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-slate-950 dark:text-white">
                  {t('portal.site_record_attention_title', {}, 'Need to handle?')}
                </p>
                <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {siteNeedsAttention
                    ? t(
                      'portal.site_record_attention_action',
                      {},
                      'The site status or address needs confirmation.'
                    )
                    : t(
                      'portal.site_record_ready_action',
                      {},
                      'No action is needed for this site right now.'
                    )}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link href={`/portal/sites/${encodeURIComponent(siteId)}#service-status`} className="btn btn-secondary btn-sm">
                    {t('portal.site_record_service_status_action', {}, 'View service status')}
                  </Link>
                  {siteNeedsAttention ? (
                    <Link href={`/portal/support?new=1&topic=site&site=${encodeURIComponent(siteId)}`} className="btn btn-secondary btn-sm">
                      {t('portal.support_request_new_action', {}, 'Submit ticket')}
                    </Link>
                  ) : null}
                </div>
                {canRemoveThisSite ? (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm mt-3 text-red-700 hover:border-red-300 hover:bg-red-50 dark:text-red-300 dark:hover:border-red-900 dark:hover:bg-red-950/30"
                    onClick={() => setShowRemoveModal(true)}
                  >
                    {t('portal.remove_site_action', {}, 'Remove site')}
                  </button>
                ) : null}
              </div>
              <PortalStatusBadge
                status={siteNeedsAttention ? 'warning' : 'active'}
                label={siteStatusLabel}
              />
            </div>
          </PortalCard>
        </div>
      </PortalSection>

      <PortalSiteServiceStatus
        t={t}
        siteId={siteId}
        overview={siteMonitoring.overview}
        isLoading={siteMonitoring.isLoading}
        error={siteMonitoring.error}
        onRefresh={siteMonitoring.refresh}
      />

      <PortalSiteKnowledgePanel
        summary={siteKnowledge.summary}
        isLoading={siteKnowledge.isLoading}
        error={siteKnowledge.error}
        onRetry={siteKnowledge.refresh}
      />

      <Modal
        isOpen={showRemoveModal}
        onClose={closeRemoveModal}
        closeLabel={t('common.close', {}, 'Close')}
        closeOnOverlay={!isRemovingSite}
        title={t('portal.remove_site_action', {}, 'Remove site')}
        description={t(
          'portal.remove_site_confirm',
          {},
          'Remove this site? Cloud service will stop, active keys will be revoked, and usage history will be kept.'
        )}
        footer={
          <>
            <button type="button" className="btn btn-secondary" onClick={closeRemoveModal} disabled={isRemovingSite}>
              {t('common.cancel')}
            </button>
            <button type="button" className="btn btn-danger" onClick={() => void handleRemoveSite()} disabled={isRemovingSite}>
              {isRemovingSite ? t('common.saving') : t('portal.remove_site_action', {}, 'Remove site')}
            </button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-slate-600 dark:text-slate-300">
          <p className="font-semibold text-slate-950 dark:text-white">{getPortalSiteDisplayName(site)}</p>
          <p className="break-words">
            {siteUrl || t('portal.site_url_missing_short', {}, 'Site URL not configured')}
          </p>
          {removeError ? (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
              {removeError}
            </p>
          ) : null}
        </div>
      </Modal>
    </PortalPageStack>
  );
}

export default function PortalSiteRecordPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalSiteRecordContent />
    </Suspense>
  );
}
