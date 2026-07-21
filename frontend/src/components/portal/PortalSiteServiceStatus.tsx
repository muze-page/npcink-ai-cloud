'use client';

import Link from 'next/link';
import {
  PortalCard,
  PortalMetricStrip,
  PortalSection,
} from '@/components/portal/PortalScaffold';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import type {
  PortalMonitoringOverviewAction,
  PortalMonitoringOverviewSummary,
} from '@/lib/portal-client';
import { formatDate, formatNumber } from '@/lib/utils';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

type PortalSiteServiceStatusProps = {
  t: TranslateFn;
  siteId: string;
  overview: PortalMonitoringOverviewSummary | null;
  isLoading: boolean;
  error: string;
  onRefresh: () => void;
};

function statusLabel(status: string, issueCount: number, hasQuotaPressure: boolean, t: TranslateFn): string {
  if (status === 'ok' && issueCount === 0 && !hasQuotaPressure) return t('portal.home.risk_level_normal', {}, 'Normal');
  if (status === 'inactive') return t('status.inactive', {}, 'Inactive');
  return t('portal.home.filter_attention_only', {}, 'Needs attention');
}

function statusTone(status: string, issueCount: number, hasQuotaPressure: boolean): string {
  if (status === 'ok' && issueCount === 0 && !hasQuotaPressure) return 'active';
  if (status === 'error') return 'error';
  return 'warning';
}

function customerIssueTitle(item: PortalMonitoringOverviewAction, t: TranslateFn): string {
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

export function PortalSiteServiceStatus({
  t,
  siteId,
  overview,
  isLoading,
  error,
  onRefresh,
}: PortalSiteServiceStatusProps) {
  const issueCount = overview?.action_required.length || 0;
  const healthStatus = overview?.health.status || 'inactive';
  const hasQuotaPressure = Boolean(overview && overview.quota.top_pressure !== 'none');
  const currentStatusLabel = statusLabel(healthStatus, issueCount, hasQuotaPressure, t);
  const latestActivityAt = overview?.activity.last_seen_at || overview?.generated_at || '';

  return (
    <PortalSection id="service-status" className="scroll-mt-24 space-y-5" data-portal-site="service-status">
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
        <div className="flex flex-wrap items-center gap-2">
          <PortalStatusBadge
            status={statusTone(healthStatus, issueCount, hasQuotaPressure)}
            label={overview ? currentStatusLabel : t('common.loading')}
          />
          <button type="button" className="btn btn-secondary btn-sm" onClick={onRefresh} disabled={isLoading}>
            {t('common.refresh', {}, 'Refresh')}
          </button>
        </div>
      </div>

      {isLoading ? (
        <PortalCard className="text-sm text-slate-600 dark:text-slate-300">{t('common.loading')}</PortalCard>
      ) : null}

      {error ? (
        <PortalCard className="border-amber-200 bg-amber-50/70 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
          {error}
        </PortalCard>
      ) : null}

      {overview ? (
        <PortalMetricStrip
          columnsClassName="md:grid-cols-3"
          items={[
            {
              label: t('portal.monitoring.last_activity', {}, 'Last activity'),
              value: latestActivityAt ? formatDate(latestActivityAt) : t('portal.home.package_pending_label', {}, 'To confirm'),
              detail: t('portal.monitoring.last_activity_detail', {}, 'Updated'),
              size: 'compact',
            },
            {
              label: t('portal.monitoring.recorded_errors', {}, 'Recorded error events'),
              value: formatNumber(Number(overview.activity.plugin_errors_total || 0)),
              detail: t('portal.monitoring.recorded_errors_detail', {}, 'Separate from the action items below.'),
              size: 'compact',
            },
            {
              label: t('portal.monitoring.quota_pressure', {}, 'Usage pressure'),
              value: overview.quota.top_pressure === 'none'
                ? t('portal.home.risk_level_normal', {}, 'Normal')
                : t('portal.home.filter_attention_only', {}, 'Needs attention'),
              detail: t('portal.monitoring.status_plain_detail', {}, 'Review the package page if usage needs attention.'),
              size: 'compact',
            },
          ]}
        />
      ) : null}

      {!isLoading && !error && overview && issueCount > 0 ? (
        <div className="divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {overview.action_required.slice(0, 3).map((item) => (
            <div key={`${item.code}-${item.source}`} className="p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">
                    {customerIssueTitle(item, t)}
                  </p>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {t('portal.monitoring.customer_issue_detail', {}, 'If this keeps showing, contact support and include the site name.')}
                  </p>
                </div>
                <PortalStatusBadge
                  status={item.severity === 'error' ? 'error' : 'warning'}
                  label={t('portal.home.filter_attention_only', {}, 'Needs attention')}
                />
              </div>
            </div>
          ))}
          <div className="p-4">
            <Link
              href={`/portal/support?new=1&topic=site&site=${encodeURIComponent(siteId)}`}
              className="btn btn-secondary btn-sm"
            >
              {t('portal.support_request_new_action', {}, 'Submit ticket')}
            </Link>
          </div>
        </div>
      ) : null}

      {!isLoading && !error && overview && issueCount === 0 && !hasQuotaPressure ? (
        <PortalCard className="text-sm text-slate-600 dark:text-slate-300">
          {t('portal.monitoring.no_diagnostic_items', {}, 'No suggestions for this site.')}
        </PortalCard>
      ) : null}
    </PortalSection>
  );
}
