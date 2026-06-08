'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import {
  BackofficeEmptyState,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import {
  CloudWorkflowMetadataPanel,
  normalizeCloudWorkflowMetadata,
  type CloudWorkflowMetadata,
} from '@/components/backoffice/CloudWorkflowMetadataPanel';
import { AnalyticsBarChart, AnalyticsLineChart } from '@/components/ui/EChartsWrapper';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber } from '@/lib/utils';

type MediaObservabilityData = {
  generatedAt: string;
  workflowMetadata: CloudWorkflowMetadata;
  window: { hours: number; startAt: string; endAt: string };
  totals: {
    jobsTotal: number;
    succeededTotal: number;
    failedTotal: number;
    successRate: number;
    avgProcessingDurationMs: number;
    p95ProcessingDurationMs: number;
    avgQueueWaitMs: number;
    sourceBytesTotal: number;
    outputBytesTotal: number;
    bytesSavedTotal: number;
    compressionRatio: number;
    artifactDownloadCount: number;
    lastFinishedAt: string;
    activeSiteCount: number;
    activeAccountCount: number;
    watermarkJobCount: number;
    activeArtifactCount: number;
    activeArtifactBytes: number;
  };
  health: { status: string; score: number; summary: string };
  timeline: Array<{
    bucketStartAt: string;
    jobsTotal: number;
    failedTotal: number;
    bytesSavedTotal: number;
  }>;
  formats: Array<{
    targetFormat: string;
    jobsTotal: number;
    succeededTotal: number;
    failedTotal: number;
    successRate: number;
    sourceBytesTotal: number;
    outputBytesTotal: number;
    bytesSavedTotal: number;
    compressionRatio: number;
    avgProcessingDurationMs: number;
  }>;
  sites: Array<{
    siteId: string;
    jobsTotal: number;
    succeededTotal: number;
    failedTotal: number;
    successRate: number;
    sourceBytesTotal: number;
    outputBytesTotal: number;
    bytesSavedTotal: number;
    compressionRatio: number;
    avgProcessingDurationMs: number;
    lastFinishedAt: string;
  }>;
  errors: Array<{ errorCode: string; count: number; lastSeenAt: string }>;
  recentFailures: Array<{
    runId: string;
    siteId: string;
    targetFormat: string;
    errorCode: string;
    sourceBytes: number;
    queueWaitMs: number;
    processingDurationMs: number;
    finishedAt: string;
  }>;
};

const WINDOW_OPTIONS = [
  { label: '24h', value: 24 },
  { label: '72h', value: 72 },
  { label: '168h', value: 168 },
];

const FORMAT_OPTIONS = [
  { label: 'All formats', value: '' },
  { label: 'WebP', value: 'webp' },
  { label: 'JPEG', value: 'jpeg' },
  { label: 'PNG', value: 'png' },
  { label: 'AVIF', value: 'avif' },
  { label: 'Original', value: 'original' },
];

function normalizeMediaObservability(raw: any): MediaObservabilityData {
  const totals = raw?.totals ?? {};
  const window = raw?.window ?? {};
  const health = raw?.health ?? {};
  return {
    generatedAt: String(raw?.generated_at ?? ''),
    workflowMetadata: normalizeCloudWorkflowMetadata(raw?.workflow_metadata ?? {}),
    window: {
      hours: Number(window.hours ?? 24),
      startAt: String(window.start_at ?? ''),
      endAt: String(window.end_at ?? ''),
    },
    totals: {
      jobsTotal: Number(totals.jobs_total ?? 0),
      succeededTotal: Number(totals.succeeded_total ?? 0),
      failedTotal: Number(totals.failed_total ?? 0),
      successRate: Number(totals.success_rate ?? 0),
      avgProcessingDurationMs: Number(totals.avg_processing_duration_ms ?? 0),
      p95ProcessingDurationMs: Number(totals.p95_processing_duration_ms ?? 0),
      avgQueueWaitMs: Number(totals.avg_queue_wait_ms ?? 0),
      sourceBytesTotal: Number(totals.source_bytes_total ?? 0),
      outputBytesTotal: Number(totals.output_bytes_total ?? 0),
      bytesSavedTotal: Number(totals.bytes_saved_total ?? 0),
      compressionRatio: Number(totals.compression_ratio ?? 0),
      artifactDownloadCount: Number(totals.artifact_download_count ?? 0),
      lastFinishedAt: String(totals.last_finished_at ?? ''),
      activeSiteCount: Number(totals.active_site_count ?? 0),
      activeAccountCount: Number(totals.active_account_count ?? 0),
      watermarkJobCount: Number(totals.watermark_job_count ?? 0),
      activeArtifactCount: Number(totals.active_artifact_count ?? 0),
      activeArtifactBytes: Number(totals.active_artifact_bytes ?? 0),
    },
    health: {
      status: String(health.status ?? 'inactive'),
      score: Number(health.score ?? 0),
      summary: String(health.summary ?? ''),
    },
    timeline: Array.isArray(raw?.timeline)
      ? raw.timeline.map((item: any) => ({
          bucketStartAt: String(item.bucket_start_at ?? ''),
          jobsTotal: Number(item.jobs_total ?? 0),
          failedTotal: Number(item.failed_total ?? 0),
          bytesSavedTotal: Number(item.bytes_saved_total ?? 0),
        }))
      : [],
    formats: Array.isArray(raw?.formats)
      ? raw.formats.map((item: any) => ({
          targetFormat: String(item.target_format ?? ''),
          jobsTotal: Number(item.jobs_total ?? 0),
          succeededTotal: Number(item.succeeded_total ?? 0),
          failedTotal: Number(item.failed_total ?? 0),
          successRate: Number(item.success_rate ?? 0),
          sourceBytesTotal: Number(item.source_bytes_total ?? 0),
          outputBytesTotal: Number(item.output_bytes_total ?? 0),
          bytesSavedTotal: Number(item.bytes_saved_total ?? 0),
          compressionRatio: Number(item.compression_ratio ?? 0),
          avgProcessingDurationMs: Number(item.avg_processing_duration_ms ?? 0),
        }))
      : [],
    sites: Array.isArray(raw?.sites)
      ? raw.sites.map((item: any) => ({
          siteId: String(item.site_id ?? ''),
          jobsTotal: Number(item.jobs_total ?? 0),
          succeededTotal: Number(item.succeeded_total ?? 0),
          failedTotal: Number(item.failed_total ?? 0),
          successRate: Number(item.success_rate ?? 0),
          sourceBytesTotal: Number(item.source_bytes_total ?? 0),
          outputBytesTotal: Number(item.output_bytes_total ?? 0),
          bytesSavedTotal: Number(item.bytes_saved_total ?? 0),
          compressionRatio: Number(item.compression_ratio ?? 0),
          avgProcessingDurationMs: Number(item.avg_processing_duration_ms ?? 0),
          lastFinishedAt: String(item.last_finished_at ?? ''),
        }))
      : [],
    errors: Array.isArray(raw?.errors)
      ? raw.errors.map((item: any) => ({
          errorCode: String(item.error_code ?? ''),
          count: Number(item.count ?? 0),
          lastSeenAt: String(item.last_seen_at ?? ''),
        }))
      : [],
    recentFailures: Array.isArray(raw?.recent_failures)
      ? raw.recent_failures.map((item: any) => ({
          runId: String(item.run_id ?? ''),
          siteId: String(item.site_id ?? ''),
          targetFormat: String(item.target_format ?? ''),
          errorCode: String(item.error_code ?? ''),
          sourceBytes: Number(item.source_bytes ?? 0),
          queueWaitMs: Number(item.queue_wait_ms ?? 0),
          processingDurationMs: Number(item.processing_duration_ms ?? 0),
          finishedAt: String(item.finished_at ?? ''),
        }))
      : [],
  };
}

function formatBytes(value: number): string {
  const bytes = Number(value || 0);
  if (Math.abs(bytes) >= 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }
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

function statusForSuccess(successRate: number, failures: number): string {
  if (failures > 0 && successRate < 0.95) return 'error';
  if (failures > 0 || successRate < 0.99) return 'warning';
  return 'ok';
}

function AdminMediaObservabilityContent() {
  const { t } = useLocale();
  const [data, setData] = useState<MediaObservabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [windowHours, setWindowHours] = useState(24);
  const [targetFormat, setTargetFormat] = useState('');
  const [siteIdInput, setSiteIdInput] = useState('');
  const [siteIdFilter, setSiteIdFilter] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      params.set('window_hours', String(windowHours));
      if (siteIdFilter.trim()) {
        params.set('site_id', siteIdFilter.trim());
      }
      if (targetFormat) {
        params.set('target_format', targetFormat);
      }
      const response = await fetch(`/api/admin/media-observability?${params.toString()}`, {
        credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok || payload?.status === 'error') {
        throw payload;
      }
      setData(normalizeMediaObservability(payload?.data ?? {}));
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [siteIdFilter, t, targetFormat, windowHours]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const timelineData = useMemo(
    () =>
      (data?.timeline || []).map((point) => ({
        label: timelineLabel(point.bucketStartAt),
        value: point.jobsTotal,
        secondaryValue: point.failedTotal,
      })),
    [data]
  );
  const formatData = useMemo(
    () =>
      (data?.formats || []).map((item) => ({
        label: item.targetFormat || 'unknown',
        value: item.jobsTotal,
        color: item.failedTotal > 0 ? '#f59e0b' : '#2563eb',
      })),
    [data]
  );
  const savingsData = useMemo(
    () =>
      (data?.formats || []).map((item) => ({
        label: item.targetFormat || 'unknown',
        value: Math.abs(item.bytesSavedTotal),
        color: item.bytesSavedTotal < 0 ? '#f59e0b' : '#10b981',
      })),
    [data]
  );
  const isEmpty = data !== null && data.totals.jobsTotal === 0;

  if (loading && !data) {
    return <LoadingFallback />;
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-red-600">{t('common.error')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{error}</p>
          <button onClick={() => void loadData()} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.media_obs.title', {}, 'Media Processing Observability')}
        description={t(
          'admin.media_obs.desc',
          {},
          'Cross-site runtime metrics for Cloud image derivative jobs. This view tracks processing health, temporary artifact pressure, and compression value without exposing image payloads.'
        )}
        aside={
          data ? (
            <div className="w-full xl:w-[48rem]">
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-2 xl:grid-cols-5"
                items={[
                  {
                    label: t('admin.media_obs.health', {}, 'Health'),
                    value: `${data.health.status} · ${data.health.score}`,
                    detail: data.health.summary,
                    toneClassName: data.health.status === 'error' ? 'text-rose-600 dark:text-rose-400' : data.health.status === 'warning' ? 'text-amber-600 dark:text-amber-400' : undefined,
                    size: 'compact',
                  },
                  {
                    label: t('admin.media_obs.jobs', {}, 'Jobs'),
                    value: formatNumber(data.totals.jobsTotal),
                    detail: `${formatNumber(data.totals.succeededTotal)} ok / ${formatNumber(data.totals.failedTotal)} failed`,
                  },
                  {
                    label: t('admin.media_obs.success_rate', {}, 'Success rate'),
                    value: formatPercent(data.totals.successRate),
                    toneClassName: statusForSuccess(data.totals.successRate, data.totals.failedTotal) === 'error' ? 'text-rose-600 dark:text-rose-400' : statusForSuccess(data.totals.successRate, data.totals.failedTotal) === 'warning' ? 'text-amber-600 dark:text-amber-400' : undefined,
                  },
                  {
                    label: t('admin.media_obs.saved', {}, 'Size change'),
                    value: formatBytes(data.totals.bytesSavedTotal),
                    detail: formatPercent(data.totals.compressionRatio),
                    toneClassName: data.totals.bytesSavedTotal < 0 ? 'text-amber-600 dark:text-amber-400' : '',
                    size: 'compact',
                  },
                  {
                    label: t('admin.media_obs.storage', {}, 'Active storage'),
                    value: formatBytes(data.totals.activeArtifactBytes),
                    detail: `${formatNumber(data.totals.activeArtifactCount)} artifacts`,
                    size: 'compact',
                  },
                ]}
              />
            </div>
          ) : undefined
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          {WINDOW_OPTIONS.map((opt) => (
            <BackofficeFilterPill
              key={opt.value}
              active={windowHours === opt.value}
              tone="info"
              onClick={() => setWindowHours(opt.value)}
            >
              {opt.label}
            </BackofficeFilterPill>
          ))}
          <span className="mx-1 h-5 w-px bg-slate-200 dark:bg-slate-700" />
          {FORMAT_OPTIONS.map((opt) => (
            <BackofficeFilterPill
              key={opt.value || 'all'}
              active={targetFormat === opt.value}
              tone="accent"
              onClick={() => setTargetFormat(opt.value)}
            >
              {opt.label}
            </BackofficeFilterPill>
          ))}
          <span className="mx-1 h-5 w-px bg-slate-200 dark:bg-slate-700" />
          <input
            type="text"
            value={siteIdInput}
            onChange={(event) => setSiteIdInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                setSiteIdFilter(siteIdInput.trim());
              }
            }}
            placeholder="site_id"
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:placeholder:text-slate-500"
          />
          <button
            type="button"
            onClick={() => setSiteIdFilter(siteIdInput.trim())}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white"
          >
            Filter
          </button>
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={loading}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white"
          >
            {t('common.refresh', {}, 'Refresh')}
          </button>
        </div>
        {data?.generatedAt ? (
          <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">
            {t('common.updated_at', {}, 'Updated')}: {formatDate(data.generatedAt)}
          </p>
        ) : null}
      </BackofficePrimaryPanel>

      {data ? <CloudWorkflowMetadataPanel metadata={data.workflowMetadata} /> : null}

      {isEmpty ? (
        <BackofficeEmptyState
          title={t('admin.media_obs.empty_title', {}, 'No media jobs yet')}
          description={t(
            'admin.media_obs.empty_desc',
            {},
            'Media processing metrics will appear after sites send image derivative jobs to Cloud.'
          )}
        />
      ) : (
        <>
          <div className="grid gap-5 xl:grid-cols-3">
            <BackofficeSectionPanel className="space-y-4 xl:col-span-2">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {t('admin.media_obs.trend_label', {}, 'Trend')}
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                    {t('admin.media_obs.trend_title', {}, 'Jobs and failures')}
                  </h2>
                </div>
                {data ? (
                  <BackofficeStatusBadge
                    status={data.health.status}
                    label={`${data.health.status} · ${data.health.score}`}
                  />
                ) : null}
              </div>
              <AnalyticsLineChart
                data={timelineData}
                height={300}
                primarySeriesName={t('admin.media_obs.jobs', {}, 'Jobs')}
                secondarySeriesName={t('admin.media_obs.failures', {}, 'Failures')}
                primaryColor="#2563eb"
                secondaryColor="#f59e0b"
              />
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.media_obs.latency_label', {}, 'Latency')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.media_obs.latency_title', {}, 'Processing speed')}
                </h2>
              </div>
              <BackofficeMetricStrip
                columnsClassName="xl:grid-cols-1"
                items={[
                  {
                    label: t('admin.media_obs.avg_processing', {}, 'Avg processing'),
                    value: `${formatNumber(data?.totals.avgProcessingDurationMs || 0)}ms`,
                    size: 'compact',
                  },
                  {
                    label: t('admin.media_obs.p95_processing', {}, 'P95 processing'),
                    value: `${formatNumber(data?.totals.p95ProcessingDurationMs || 0)}ms`,
                    size: 'compact',
                  },
                  {
                    label: t('admin.media_obs.queue_wait', {}, 'Avg queue wait'),
                    value: `${formatNumber(data?.totals.avgQueueWaitMs || 0)}ms`,
                    size: 'compact',
                  },
                  {
                    label: t('admin.media_obs.downloads', {}, 'Downloads'),
                    value: formatNumber(data?.totals.artifactDownloadCount || 0),
                    detail: `${formatNumber(data?.totals.watermarkJobCount || 0)} watermark jobs`,
                  },
                ]}
              />
            </BackofficeSectionPanel>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.media_obs.formats_label', {}, 'Formats')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.media_obs.format_mix', {}, 'Format mix')}
                </h2>
              </div>
              <AnalyticsBarChart data={formatData} height={280} barColor="#2563eb" />
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.media_obs.savings_label', {}, 'Value')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.media_obs.savings_title', {}, 'Size change by format')}
                </h2>
              </div>
              <AnalyticsBarChart data={savingsData} height={280} barColor="#10b981" />
            </BackofficeSectionPanel>
          </div>

          <BackofficeSectionPanel className="overflow-hidden p-0">
            <div className="border-b border-slate-200/80 px-5 py-4 dark:border-slate-800 md:px-6">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.media_obs.sites_label', {}, 'Sites')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.media_obs.sites_title', {}, 'Site breakdown')}
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200/80 text-sm dark:divide-slate-800">
                <thead className="bg-slate-50/80 text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-950/30 dark:text-slate-400">
                  <tr>
                    <th className="px-5 py-3 text-left font-semibold">Site</th>
                    <th className="px-5 py-3 text-right font-semibold">Jobs</th>
                    <th className="px-5 py-3 text-right font-semibold">Success</th>
                    <th className="px-5 py-3 text-right font-semibold">Size change</th>
                    <th className="px-5 py-3 text-right font-semibold">Avg ms</th>
                    <th className="px-5 py-3 text-right font-semibold">Last</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200/80 dark:divide-slate-800">
                  {(data?.sites || []).map((site) => (
                    <tr key={site.siteId} className="bg-white/55 dark:bg-slate-950/20">
                      <td className="px-5 py-3">
                        <BackofficeIdentifier value={site.siteId} />
                      </td>
                      <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                        {formatNumber(site.jobsTotal)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <BackofficeTag tone={site.failedTotal > 0 ? 'warning' : 'info'}>
                          {formatPercent(site.successRate)}
                        </BackofficeTag>
                      </td>
                      <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                        {formatBytes(site.bytesSavedTotal)}
                      </td>
                      <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                        {formatNumber(site.avgProcessingDurationMs)}
                      </td>
                      <td className="px-5 py-3 text-right text-slate-500 dark:text-slate-400">
                        {site.lastFinishedAt ? formatDate(site.lastFinishedAt) : t('common.not_found')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </BackofficeSectionPanel>

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.media_obs.errors_label', {}, 'Errors')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.media_obs.errors_title', {}, 'Error codes')}
                </h2>
              </div>
              {(data?.errors || []).length ? (
                <div className="space-y-2">
                  {(data?.errors || []).map((item) => (
                    <BackofficeStackCard key={`${item.errorCode}-${item.lastSeenAt}`}>
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate font-semibold text-slate-950 dark:text-white">{item.errorCode}</p>
                          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                            {item.lastSeenAt ? formatDate(item.lastSeenAt) : t('common.not_found')}
                          </p>
                        </div>
                        <BackofficeTag tone="warning">{formatNumber(item.count)}</BackofficeTag>
                      </div>
                    </BackofficeStackCard>
                  ))}
                </div>
              ) : (
                <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
                  {t('admin.media_obs.no_errors', {}, 'No media processing failures in this window.')}
                </BackofficeStackCard>
              )}
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.media_obs.recent_label', {}, 'Recent')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.media_obs.recent_title', {}, 'Recent failures')}
                </h2>
              </div>
              {(data?.recentFailures || []).length ? (
                <div className="space-y-2">
                  {(data?.recentFailures || []).map((item) => (
                    <BackofficeStackCard key={item.runId}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <BackofficeIdentifier value={item.runId} />
                          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                            {item.errorCode} · {item.targetFormat} · {formatBytes(item.sourceBytes)}
                          </p>
                          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                            {item.siteId} · {item.finishedAt ? formatDate(item.finishedAt) : t('common.not_found')}
                          </p>
                        </div>
                        <BackofficeTag tone="warning">{formatNumber(item.processingDurationMs)}ms</BackofficeTag>
                      </div>
                    </BackofficeStackCard>
                  ))}
                </div>
              ) : (
                <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
                  {t('admin.media_obs.no_recent_failures', {}, 'No recent failures.')}
                </BackofficeStackCard>
              )}
            </BackofficeSectionPanel>
          </div>
        </>
      )}
    </BackofficePageStack>
  );
}

export default function AdminMediaObservabilityPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminMediaObservabilityContent />
    </Suspense>
  );
}
