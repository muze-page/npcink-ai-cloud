'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { BackofficePageStack, BackofficeSectionPanel, BackofficeStackCard } from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { PortalErrorState, PortalLoadingState, PortalSignedOutState } from '@/components/portal/PortalPageState';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import { portalClient, type PortalSiteSummaryRecord, type Site } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import {
  getPortalSiteDisplayName,
  getPortalSiteWordPressUrl,
} from '@/lib/portal-site-display';
import { formatDate } from '@/lib/utils';

function PortalSiteRecordContent() {
  const params = useParams<{ siteId?: string }>();
  const siteId = String(params?.siteId || '');
  const { t } = useLocale();
  const { session, isLoading, isAuthenticated } = useSession();
  const [summary, setSummary] = useState<PortalSiteSummaryRecord | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isAuthenticated || !siteId) return;
    let alive = true;
    setError('');
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
    ...(summary.site || {}),
    ...(sessionSite || {}),
    site_id: siteId,
    site_name: summary.site?.site_name || sessionSite?.site_name || siteId,
    account_id: summary.site?.account_id || sessionSite?.account_id || summary.account_id || session.account_id || '',
    status: (summary.site?.status || sessionSite?.status || 'inactive') as Site['status'],
    created_at: summary.site?.created_at || sessionSite?.created_at || '',
  };
  const siteUrl = getPortalSiteWordPressUrl(site);
  const siteNeedsAttention = site.status !== 'active' || !siteUrl;
  const siteStatusLabel = siteNeedsAttention
    ? t('portal.home.filter_attention_only', {}, 'Needs attention')
    : t('portal.home.risk_level_normal', {}, 'Normal');
  const contactStatusLabel = t('portal.site_record_contact_available', {}, 'Available in Contact');

  return (
    <BackofficePageStack>
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
            detail: siteUrl || t('portal.site_url_missing_short', {}, 'Site URL not configured'),
          },
          {
            label: t('portal.site_address_label', {}, 'Site address'),
            value: siteUrl ? t('portal.site_address_configured', {}, 'Configured') : t('portal.site_url_missing_short', {}, 'Site URL not configured'),
            detail: siteUrl || t('portal.site_record_address_missing_detail', {}, 'Add a site address so support can identify this site faster.'),
          },
          {
            label: t('common.created_at', {}, 'Created'),
            value: site.created_at ? formatDate(site.created_at) : t('portal.home.package_pending_label', {}, 'To confirm'),
          },
        ]}
      />

      <BackofficeSectionPanel className="space-y-4" variant="portal">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">
            {t('portal.site_record_current_label', {}, 'Current site')}
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
        <div className="grid gap-3 lg:grid-cols-3">
          <BackofficeStackCard variant="portal">
            <div className="space-y-1">
              <p className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('portal.site_address_label', {}, 'Site address')}
              </p>
              <p className="break-words text-sm leading-6 text-slate-600 dark:text-slate-300">
                {siteUrl || t('portal.site_url_missing', {}, 'WordPress URL not configured')}
              </p>
            </div>
          </BackofficeStackCard>
          <BackofficeStackCard variant="portal">
            <div className="flex h-full items-start justify-between gap-3">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-slate-950 dark:text-white">
                  {t('portal.nav_account', {}, 'Contact')}
                </p>
                <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t(
                    'portal.site_record_contact_desc',
                    {},
                    'Use the Contact page to confirm the email and service contact details for this account.'
                  )}
                </p>
              </div>
              <BackofficeStatusBadge status="active" label={contactStatusLabel} />
            </div>
          </BackofficeStackCard>
          <BackofficeStackCard variant="portal">
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
              </div>
              <BackofficeStatusBadge
                status={siteNeedsAttention ? 'warning' : 'active'}
                label={siteStatusLabel}
              />
            </div>
          </BackofficeStackCard>
        </div>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function PortalSiteRecordPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalSiteRecordContent />
    </Suspense>
  );
}
