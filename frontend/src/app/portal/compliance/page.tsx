'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSiteSwitchingNotice,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { Button } from '@/components/ui/Button';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalCompliancePosture,
  type PortalComplianceRequestPayload,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatNumber } from '@/lib/utils';

type ComplianceRequestType = PortalComplianceRequestPayload['request_type'];

const COMPLIANCE_REQUEST_OPTIONS: Array<{
  type: ComplianceRequestType;
  labelKey: string;
  fallback: string;
}> = [
  {
    type: 'compliance_export',
    labelKey: 'compliance.request_export',
    fallback: 'Request Data Export',
  },
  {
    type: 'compliance_deletion_review',
    labelKey: 'compliance.request_deletion',
    fallback: 'Request Deletion Review',
  },
  {
    type: 'compliance_report',
    labelKey: 'compliance.request_report',
    fallback: 'Request Compliance Report',
  },
];

export function PortalComplianceContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { sites, selectedSiteId, selectedSite, isSwitchingSite, switchingSiteName, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });
  const [posture, setPosture] = useState<PortalCompliancePosture | null>(null);
  const [requestType, setRequestType] = useState<ComplianceRequestType>('compliance_export');
  const [requestReason, setRequestReason] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadPosture = useCallback(
    async (siteId: string) => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await portalClient.getCompliancePosture(siteId);
        setPosture(response.data);
      } catch (err) {
        setError(
          formatPortalErrorMessage(
            err,
            t,
            t('compliance.load_error', {}, 'Failed to load compliance posture')
          )
        );
      } finally {
        setIsLoading(false);
      }
    },
    [t]
  );

  useEffect(() => {
    if (!session || !isAuthenticated || !selectedSiteId) {
      setIsLoading(false);
      return;
    }
    void loadPosture(selectedSiteId);
  }, [isAuthenticated, loadPosture, selectedSiteId, session]);

  const handleSiteChange = async (siteId: string) => {
    await setSelectedSiteId(siteId);
    setMessage(null);
    await loadPosture(siteId);
  };

  const metrics = useMemo(
    () => [
      {
        label: t('compliance.storage_region', {}, 'Storage Region'),
        value: posture?.data_residency.storage_region || '--',
        size: 'compact' as const,
      },
      {
        label: t('compliance.inference_region', {}, 'Inference Region'),
        value: posture?.data_residency.inference_region || '--',
        size: 'compact' as const,
      },
      {
        label: t('compliance.retention_days', {}, 'Retention Days'),
        value: posture ? formatNumber(posture.audit.retention_days) : '--',
      },
      {
        label: t('compliance.events_in_retention', {}, 'Events in Retention'),
        value: posture ? formatNumber(posture.audit.events_in_retention) : '--',
      },
    ],
    [posture, t]
  );

  const handleSubmit = async () => {
    if (!selectedSiteId) return;
    setIsSubmitting(true);
    setMessage(null);
    setError(null);
    try {
      await portalClient.createComplianceRequest(selectedSiteId, {
        request_type: requestType,
        reason: requestReason,
      });
      setRequestReason('');
      setMessage(t('compliance.request_submitted', {}, 'Request submitted for operator review.'));
    } catch (err) {
      setError(
        formatPortalErrorMessage(
          err,
          t,
          t('compliance.request_error', {}, 'Failed to submit compliance request')
        )
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  if (sessionLoading || isLoading) {
    return <PortalLoadingState message={t('common.loading')} />;
  }

  if (!isAuthenticated) {
    return (
      <PortalSignedOutState
        title={t('auth.sign_in_required', {}, 'Sign in required')}
        description={t('portal.sign_in_desc', {}, 'Sign in to view this portal workspace.')}
        actionLabel={t('auth.sign_in', {}, 'Sign in')}
      />
    );
  }

  if (!selectedSiteId) {
    return (
      <PortalEmptyState
        title={t('portal.no_site_title', {}, 'No site selected')}
        description={t('portal.no_site_desc', {}, 'Create or select a site before opening this workspace.')}
        actionLabel={t('portal.nav_sites', {}, 'Sites')}
        actionHref="/portal/sites"
      />
    );
  }

  if (error && !posture) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={error}
        retryLabel={t('common.retry', {}, 'Retry')}
        onRetry={() => void loadPosture(selectedSiteId)}
      />
    );
  }

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('nav.compliance', {}, 'Compliance')}
        title={t('compliance.title', {}, 'Compliance Posture')}
        description={t(
          'compliance.desc',
          {},
          'Read-only view of data residency, security controls, and audit retention.'
        )}
        currentPage="compliance"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSite?.site_name}
        showSiteContextSummary
        sites={sites}
        onSiteChange={handleSiteChange}
        metrics={metrics}
      />

      {isSwitchingSite ? (
        <PortalSiteSwitchingNotice
          message={t('portal.switching_site', { site: switchingSiteName || selectedSiteId }, 'Switching site...')}
        />
      ) : null}

      {error ? (
        <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200">
          {error}
        </BackofficeStackCard>
      ) : null}

      {message ? (
        <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200">
          {message}
        </BackofficeStackCard>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,0.8fr)]">
        <BackofficeSectionPanel>
          <div className="flex flex-col gap-5">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
                {t('compliance.data_residency', {}, 'Data Residency')}
              </h2>
              <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {posture?.data_residency.byom_enabled
                  ? t('compliance.byom_notice', {}, 'This site uses BYOM. Your model provider terms and residency apply.')
                  : t('compliance.data_localization_notice', {}, 'Data is stored outside mainland China.')}
              </p>
            </div>
            <BackofficeMetricStrip items={metrics.slice(0, 3)} columnsClassName="md:grid-cols-3" />
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
                {t('compliance.security_controls', {}, 'Security Controls')}
              </h2>
              <div className="mt-4 divide-y divide-slate-200/80 rounded-[1.1rem] border border-slate-200/80 bg-white/70 dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-950/35">
                {(posture?.security_controls || []).map((control) => (
                  <div key={control.control} className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,0.8fr)_auto_minmax(0,1.2fr)] md:items-center">
                    <p className="min-w-0 break-words text-sm font-semibold text-slate-950 dark:text-white">
                      {control.control.replace(/_/g, ' ')}
                    </p>
                    <BackofficeStatusBadge status={control.status} label={control.status} />
                    <p className="min-w-0 break-words text-sm text-slate-600 dark:text-slate-300">
                      {control.detail}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel>
          <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
            {t('compliance.compliance_requests', {}, 'Compliance Requests')}
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t(
              'compliance.gdpr_notice',
              {},
              'We process data for service delivery and security. For data-subject requests, submit a ticket.'
            )}
          </p>

          <div className="mt-5 space-y-4">
            <div className="grid gap-2">
              {COMPLIANCE_REQUEST_OPTIONS.map((option) => (
                <button
                  key={option.type}
                  type="button"
                  onClick={() => setRequestType(option.type)}
                  className={`rounded-[0.8rem] border px-3 py-2 text-left text-sm font-medium transition ${
                    requestType === option.type
                      ? 'border-blue-500 bg-blue-50 text-blue-900 dark:border-blue-400 dark:bg-blue-950/30 dark:text-blue-100'
                      : 'border-slate-200 bg-white/70 text-slate-700 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-200 dark:hover:bg-slate-900'
                  }`}
                >
                  {t(option.labelKey, {}, option.fallback)}
                </button>
              ))}
            </div>

            <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('compliance.request_reason', {}, 'Reason (optional)')}
              <textarea
                value={requestReason}
                onChange={(event) => setRequestReason(event.target.value)}
                rows={4}
                className="mt-2 w-full rounded-[0.8rem] border border-slate-200 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 dark:border-slate-800 dark:bg-slate-950 dark:text-white"
              />
            </label>

            <Button onClick={handleSubmit} loading={isSubmitting} fullWidth>
              {t('compliance.request_submit', {}, 'Submit Request')}
            </Button>
          </div>
        </BackofficeSectionPanel>
      </div>
    </BackofficePageStack>
  );
}

export default function PortalCompliancePage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalComplianceContent />
    </Suspense>
  );
}
