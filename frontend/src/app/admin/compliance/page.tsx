'use client';

import Link from 'next/link';
import React, { Suspense, useEffect, useMemo, useState } from 'react';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { formatPortalActionRequestTypeLabel } from '@/lib/portal-action-request-display';
import { readResponsePayload } from '@/lib/safe-response';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate } from '@/lib/utils';

type PortalActionRequest = {
  request_id: string;
  request_type: string;
  account_id?: string;
  site_id?: string;
  member_ref: string;
  title: string;
  message?: string;
  status: string;
  created_at: string;
};

const COMPLIANCE_TYPES = new Set([
  'compliance_export',
  'compliance_deletion_review',
  'compliance_report',
]);

function AdminComplianceContent() {
  const { t } = useLocale();
  const [items, setItems] = useState<PortalActionRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadRequests = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch('/api/admin/portal-action-requests?limit=100&status=open,acknowledged', {
          credentials: 'include',
        });
        const payload = await readResponsePayload<{
          data?: { items?: PortalActionRequest[] };
          message?: string;
        }>(response);
        if (!response.ok) {
          throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
        }
        setItems(
          (('data' in payload ? payload.data?.items : []) || []).filter((item) =>
            COMPLIANCE_TYPES.has(String(item.request_type || ''))
          )
        );
      } catch (err) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadRequests();
  }, [t]);

  const metrics = useMemo(() => {
    const exportCount = items.filter((item) => item.request_type === 'compliance_export').length;
    const deletionCount = items.filter((item) => item.request_type === 'compliance_deletion_review').length;
    const reportCount = items.filter((item) => item.request_type === 'compliance_report').length;
    return [
      { label: t('admin.requests_filter_all', {}, 'All requests'), value: items.length },
      { label: t('compliance.request_export', {}, 'Request Data Export'), value: exportCount },
      { label: t('compliance.request_deletion', {}, 'Request Deletion Review'), value: deletionCount },
      { label: t('compliance.request_report', {}, 'Request Compliance Report'), value: reportCount },
    ];
  }, [items, t]);

  if (isLoading) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('nav.compliance', {}, 'Compliance')}
        title={t('compliance.title', {}, 'Compliance Posture')}
        description={t(
          'compliance.desc',
          {},
          'Read-only view of data residency, security controls, and audit retention.'
        )}
        actions={
          <Link className="btn btn-primary" href="/admin/requests">
            {t('admin.requests_title', {}, 'Requests')}
          </Link>
        }
      >
        <BackofficeMetricStrip items={metrics} />
      </BackofficePrimaryPanel>

      {error ? (
        <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200">
          {error}
        </BackofficeStackCard>
      ) : null}

      <BackofficeSectionPanel>
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
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
          </div>
        </div>

        {items.length === 0 ? (
          <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
            {t('audit.empty', {}, 'No audit events found.')}
          </BackofficeStackCard>
        ) : (
          <div className="divide-y divide-slate-200/80 overflow-hidden rounded-[1.1rem] border border-slate-200/80 bg-white/75 dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-950/35">
            {items.map((item) => (
              <article key={item.request_id} className="grid gap-3 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="min-w-0 break-words text-sm font-semibold text-slate-950 dark:text-white">
                      {item.title || formatPortalActionRequestTypeLabel(t, item.request_type)}
                    </h3>
                    <BackofficeStatusBadge status={item.status} label={item.status} />
                  </div>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                    {formatPortalActionRequestTypeLabel(t, item.request_type)}
                  </p>
                  <p className="mt-2 break-words text-xs text-slate-500 dark:text-slate-400">
                    {item.site_id || item.account_id || item.member_ref}
                  </p>
                  {item.message ? (
                    <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {item.message}
                    </p>
                  ) : null}
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400">{formatDate(item.created_at)}</p>
              </article>
            ))}
          </div>
        )}
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function AdminCompliancePage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminComplianceContent />
    </Suspense>
  );
}
