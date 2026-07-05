'use client';

import {
  BackofficeEmptyState,
  BackofficeMetricStrip,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { AnalyticsBarChart, AnalyticsLineChart } from '@/components/ui/EChartsWrapper';
import { useLocale } from '@/contexts/LocaleContext';
import type { PortalMediaObservabilitySummary } from '@/lib/portal-client';
import { formatDate, formatNumber } from '@/lib/utils';

type PortalMediaProcessingPanelProps = {
  summary: PortalMediaObservabilitySummary | null;
  isLoading?: boolean;
  error?: string;
  onRetry?: () => void;
};

function formatBytes(value: number): string {
  const bytes = Number(value || 0);
  if (Math.abs(bytes) >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (Math.abs(bytes) >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} B`;
}

function formatPercent(value: number): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function timelineLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${String(date.getHours()).padStart(2, '0')}:00`;
}

export function PortalMediaProcessingPanel({
  summary,
  isLoading = false,
  error = '',
  onRetry,
}: PortalMediaProcessingPanelProps) {
  const { t } = useLocale();
  const totals = summary?.totals || null;
  const hasJobs = Number(totals?.jobs_total || 0) > 0;
  const timelineData = (summary?.timeline || []).map((point) => ({
    label: timelineLabel(point.bucket_start_at),
    value: Number(point.jobs_total || 0),
    secondaryValue: Number(point.failed_total || 0),
  }));
  const formatData = (summary?.formats || []).map((item) => ({
    label: item.target_format || 'unknown',
    value: Number(item.jobs_total || 0),
    color: Number(item.failed_total || 0) > 0 ? '#f59e0b' : '#2563eb',
  }));

  return (
    <BackofficeSectionPanel className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
	          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
	            {t('portal.media_obs.eyebrow', {}, 'Images')}
	          </p>
	          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
	            {t('portal.media_obs.title', {}, 'Image processing')}
	          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-300">
            {t(
              'portal.media_obs.desc',
              {},
	              'Read-only image processing status for this site.'
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {summary?.health ? (
            <BackofficeStatusBadge
	              status={summary.health.status}
	              label={t(`status.${summary.health.status}`, {}, summary.health.status)}
            />
          ) : null}
          {onRetry ? (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
              {t('common.refresh', {}, 'Refresh')}
            </button>
          ) : null}
        </div>
      </div>

      {isLoading ? (
        <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
          {t('common.loading')}
        </BackofficeStackCard>
      ) : error ? (
        <BackofficeStackCard className="border-red-200 bg-red-50/70 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200">
          {error}
        </BackofficeStackCard>
      ) : !hasJobs ? (
        <BackofficeEmptyState
	          title={t('portal.media_obs.empty_title', {}, 'No image activity yet')}
          description={t(
            'portal.media_obs.empty_desc',
            {},
	            'Image activity will appear after the site sends image work to Cloud.'
          )}
        />
      ) : (
        <>
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-4"
            items={[
              {
	                label: t('portal.media_obs.jobs', {}, 'Images'),
                value: formatNumber(Number(totals?.jobs_total || 0)),
                detail: `${summary?.window?.hours || 24}h`,
              },
              {
	                label: t('portal.media_obs.success_rate', {}, 'OK rate'),
	                value: formatPercent(Number(totals?.success_rate || 0)),
	                detail: t('portal.media_obs.failed_count', { count: formatNumber(Number(totals?.failed_total || 0)) }, '{{count}} issue(s)'),
	              },
	              {
	                label: t('portal.media_obs.saved', {}, 'Size saved'),
                value: formatBytes(Number(totals?.bytes_saved_total || 0)),
                detail: formatPercent(Number(totals?.compression_ratio || 0)),
                toneClassName: Number(totals?.bytes_saved_total || 0) < 0 ? 'text-amber-700 dark:text-amber-200' : '',
              },
              {
	                label: t('portal.media_obs.p95', {}, 'Processing time'),
	                value: `${formatNumber(Number(totals?.p95_processing_duration_ms || 0))}ms`,
	                detail: t('portal.media_obs.active_storage', { value: formatBytes(Number(totals?.active_artifact_bytes || 0)) }, '{{value}} in use'),
                size: 'compact',
              },
            ]}
          />

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
	                {t('portal.media_obs.trend', {}, 'Images and issues')}
              </h3>
              <AnalyticsLineChart
                data={timelineData}
                height={240}
	                primarySeriesName={t('portal.media_obs.jobs', {}, 'Images')}
	                secondarySeriesName={t('portal.media_obs.failures', {}, 'Issues')}
                primaryColor="#2563eb"
                secondaryColor="#f59e0b"
              />
            </BackofficeStackCard>
            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('portal.media_obs.formats', {}, 'Format mix')}
              </h3>
              <AnalyticsBarChart data={formatData} height={240} barColor="#2563eb" />
            </BackofficeStackCard>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeStackCard className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                  {t('portal.media_obs.formats_table', {}, 'Formats')}
                </h3>
                <BackofficeTag tone="info">
                  {formatNumber(Number(totals?.artifact_download_count || 0))} downloads
                </BackofficeTag>
              </div>
              <div className="space-y-2">
                {(summary?.formats || []).slice(0, 5).map((item) => (
                  <div
                    key={item.target_format}
                    className="flex items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900/40"
                  >
                    <div>
                      <p className="font-semibold text-slate-950 dark:text-white">{item.target_format}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {formatBytes(item.bytes_saved_total)} · {formatPercent(item.compression_ratio)}
                      </p>
                    </div>
                    <BackofficeTag tone={item.failed_total > 0 ? 'warning' : 'info'}>
                      {formatNumber(item.jobs_total)}
                    </BackofficeTag>
                  </div>
                ))}
              </div>
            </BackofficeStackCard>

            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
	                  {t('portal.media_obs.failures', {}, 'Issues')}
              </h3>
              {(summary?.errors || []).length ? (
                <div className="space-y-2">
                  {(summary?.errors || []).slice(0, 5).map((item) => (
                    <div
                      key={`${item.error_code}-${item.last_seen_at}`}
                      className="flex items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900/40"
                    >
                      <div className="min-w-0">
	                        <p className="truncate font-semibold text-slate-950 dark:text-white">
	                          {t('portal.media_obs.issue_item', {}, 'Image issue')}
	                        </p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {item.last_seen_at ? formatDate(item.last_seen_at) : t('common.not_found')}
                        </p>
                      </div>
                      <BackofficeTag tone="warning">{formatNumber(item.count)}</BackofficeTag>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-600 dark:text-slate-300">
	                  {t('portal.media_obs.no_failures', {}, 'No issues in this period.')}
                </p>
              )}
            </BackofficeStackCard>
          </div>
        </>
      )}
    </BackofficeSectionPanel>
  );
}
