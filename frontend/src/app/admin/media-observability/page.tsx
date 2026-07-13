'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import {
  BackofficeEmptyState,
  BackofficeDiagnosticNotice,
  BackofficeDisclosure,
  BackofficeLayer,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
  BackofficeSummaryStrip,
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
  { labelKey: 'admin.media_obs.format_all', label: 'All formats', value: '' },
  { labelKey: 'admin.media_obs.format_webp', label: 'WebP', value: 'webp' },
  { labelKey: 'admin.media_obs.format_jpeg', label: 'JPEG', value: 'jpeg' },
  { labelKey: 'admin.media_obs.format_png', label: 'PNG', value: 'png' },
  { labelKey: 'admin.media_obs.format_avif', label: 'AVIF', value: 'avif' },
  { labelKey: 'admin.media_obs.format_original', label: 'Original', value: 'original' },
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

function mediaStatusLabel(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  status: string
): string {
  return t(`status.${status || 'unknown'}`, {}, status || 'unknown');
}

function mediaHealthSummary(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  data: MediaObservabilityData
): string {
  if (data.health.status === 'inactive') {
    return t('admin.media_obs.health_summary_inactive', {}, 'No media processing jobs in this window.');
  }
  return t(
    'admin.media_obs.health_summary_active',
    {
      jobs: formatNumber(data.totals.jobsTotal),
      failures: formatNumber(data.totals.failedTotal),
      p95: formatNumber(data.totals.p95ProcessingDurationMs),
    },
    '{{jobs}} jobs · {{failures}} failed · P95 {{p95}}ms'
  );
}

function normalizeMediaWindow(value: string | null): number {
  const parsed = Number(value);
  return parsed === 72 || parsed === 168 ? parsed : 24;
}

function normalizeTargetFormat(value: string | null): string {
  const normalized = value || '';
  return FORMAT_OPTIONS.some((option) => option.value === normalized) ? normalized : '';
}

function AdminMediaObservabilityContent() {
  const { t } = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const windowHours = normalizeMediaWindow(searchParams.get('window'));
  const targetFormat = normalizeTargetFormat(searchParams.get('format'));
  const siteIdFilter = searchParams.get('site') || '';
  const focusedRunId = searchParams.get('focus') || '';
  const [data, setData] = useState<MediaObservabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [siteIdInput, setSiteIdInput] = useState(siteIdFilter);
  const requestControllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);

  const updateUrl = useCallback((updates: { window?: number | null; format?: string | null; site?: string | null; focus?: string | null }) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value && !(key === 'window' && value === 24)) params.set(key, String(value));
      else params.delete(key);
    });
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  const loadData = useCallback(async (refresh = false) => {
    requestControllerRef.current?.abort();
    const sequence = ++requestSequenceRef.current;
    if (!hasLoadedRef.current || !refresh) setLoading(true);
    setError('');
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const timeout = globalThis.setTimeout(() => controller.abort(), 8000);
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
        cache: 'no-store',
        signal: controller.signal,
      });
      const payload = await response.json();
      if (!response.ok || payload?.status === 'error') {
        throw payload;
      }
      if (sequence !== requestSequenceRef.current) return;
      setData(normalizeMediaObservability(payload?.data ?? {}));
      hasLoadedRef.current = true;
    } catch (err) {
      if (sequence !== requestSequenceRef.current) return;
      setError(resolveUiErrorMessage(err, t('admin.media_obs.load_error', {}, 'Failed to load media processing diagnostics.')));
    } finally {
      globalThis.clearTimeout(timeout);
      if (sequence === requestSequenceRef.current) {
        requestControllerRef.current = null;
        setLoading(false);
      }
    }
  }, [siteIdFilter, t, targetFormat, windowHours]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    setSiteIdInput(siteIdFilter);
  }, [siteIdFilter]);

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
        label: item.targetFormat || t('common.unknown', {}, 'Unknown'),
        value: item.jobsTotal,
        color: item.failedTotal > 0 ? '#f59e0b' : '#2563eb',
      })),
    [data, t]
  );
  const savingsData = useMemo(
    () =>
      (data?.formats || []).map((item) => ({
        label: item.targetFormat || t('common.unknown', {}, 'Unknown'),
        value: Math.abs(item.bytesSavedTotal),
        color: item.bytesSavedTotal < 0 ? '#f59e0b' : '#10b981',
      })),
    [data, t]
  );
  const selectedFailure = data?.recentFailures.find((item) => item.runId === focusedRunId)
    || data?.recentFailures[0]
    || null;
  const isEmpty = data !== null && data.totals.jobsTotal === 0;

  if (loading && !data) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficeLayer
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.media_obs.title', {}, 'Media Processing Observability')}
        description={t(
          'admin.media_obs.desc',
          {},
          'Cross-site runtime metrics for Cloud image derivative jobs. This view tracks processing health, temporary artifact pressure, and compression value without exposing image payloads.'
        )}
        aside={data ? <BackofficeStatusBadge status={data.health.status} label={`${mediaStatusLabel(t, data.health.status)} · ${data.health.score}`} /> : undefined}
        actions={<button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadData(true)} disabled={loading}>{t('common.refresh', {}, 'Refresh')}</button>}
      />

      <BackofficeSectionPanel className="p-4 md:p-5">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
          {WINDOW_OPTIONS.map((opt) => (
            <BackofficeFilterPill
              key={opt.value}
              active={windowHours === opt.value}
              tone="info"
              onClick={() => updateUrl({ window: opt.value, focus: null })}
            >
              {opt.label}
            </BackofficeFilterPill>
          ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
          {FORMAT_OPTIONS.map((opt) => (
            <BackofficeFilterPill
              key={opt.value || 'all'}
              active={targetFormat === opt.value}
              tone="accent"
              onClick={() => updateUrl({ format: opt.value || null, focus: null })}
            >
              {t(opt.labelKey, {}, opt.label)}
            </BackofficeFilterPill>
          ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input type="text" value={siteIdInput} aria-label={t('admin.media_obs.site_filter_label', {}, 'Filter by site ID')} onChange={(event) => setSiteIdInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') updateUrl({ site: siteIdInput.trim() || null, focus: null }); }} placeholder={t('admin.media_obs.site_filter', {}, 'Site ID')} className="input h-9 min-w-0 flex-1 sm:max-w-xs" />
            <button type="button" onClick={() => updateUrl({ site: siteIdInput.trim() || null, focus: null })} className="btn btn-secondary btn-sm justify-center">{t('common.apply', {}, 'Apply')}</button>
            {siteIdFilter ? <button type="button" className="btn btn-ghost btn-sm justify-center" onClick={() => { setSiteIdInput(''); updateUrl({ site: null, focus: null }); }}>{t('common.clear_filters', {}, 'Clear filters')}</button> : null}
            {data?.generatedAt ? <p className="text-xs text-slate-500 sm:ml-auto dark:text-slate-400">{t('common.updated_at', {}, 'Updated')}: {formatDate(data.generatedAt)}</p> : null}
          </div>
        </div>
      </BackofficeSectionPanel>

      {data ? <BackofficeSummaryStrip items={[
        { label: t('admin.media_obs.jobs', {}, 'Jobs'), value: formatNumber(data.totals.jobsTotal) },
        { label: t('admin.media_obs.success_rate', {}, 'Success rate'), value: formatPercent(data.totals.successRate), toneClassName: statusForSuccess(data.totals.successRate, data.totals.failedTotal) === 'error' ? 'text-rose-600 dark:text-rose-400' : statusForSuccess(data.totals.successRate, data.totals.failedTotal) === 'warning' ? 'text-amber-600 dark:text-amber-400' : undefined },
        { label: t('admin.media_obs.p95_processing', {}, 'P95 processing'), value: `${formatNumber(data.totals.p95ProcessingDurationMs)}ms` },
        { label: t('admin.media_obs.saved', {}, 'Size change'), value: formatBytes(data.totals.bytesSavedTotal), toneClassName: data.totals.bytesSavedTotal < 0 ? 'text-amber-600 dark:text-amber-400' : undefined },
        { label: t('admin.media_obs.failures', {}, 'Failures'), value: formatNumber(data.totals.failedTotal), toneClassName: data.totals.failedTotal > 0 ? 'text-rose-600 dark:text-rose-400' : undefined },
      ]} /> : null}

      {error ? <BackofficeDiagnosticNotice message={error} staleDescription={data ? t('admin.media_obs.stale_notice', {}, 'The last successfully loaded media snapshot remains visible.') : undefined} retryLabel={t('common.retry')} onRetry={() => void loadData(true)} /> : null}

      {!data ? null : isEmpty ? (
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
            <BackofficeSectionPanel className="min-w-0 space-y-4 overflow-hidden xl:col-span-2">
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

            <BackofficeSectionPanel className="min-w-0 space-y-4 overflow-hidden">
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
                    detail: t(
                      'admin.media_obs.watermark_jobs_detail',
                      { count: formatNumber(data?.totals.watermarkJobCount || 0) },
                      '{{count}} watermark jobs'
                    ),
                  },
                ]}
              />
            </BackofficeSectionPanel>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeSectionPanel className="min-w-0 space-y-4 overflow-hidden">
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

            <BackofficeSectionPanel className="min-w-0 space-y-4 overflow-hidden">
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
                    <th className="px-5 py-3 text-left font-semibold">{t('common.site', {}, 'Site')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.media_obs.jobs', {}, 'Jobs')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.media_obs.success', {}, 'Success')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.media_obs.saved', {}, 'Size change')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.media_obs.avg_ms', {}, 'Avg ms')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.media_obs.last', {}, 'Last')}</th>
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

          <BackofficeSectionPanel className="overflow-hidden p-0 md:p-0">
            <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800 md:px-6"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('admin.media_obs.recent_label', {}, 'Recent')}</p><h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">{t('admin.media_obs.failure_queue_title', {}, 'Recent failure queue')}</h2><p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('admin.media_obs.failure_queue_desc', {}, 'Select a failed media job to inspect its site, format, size, queue wait, and processing evidence.')}</p></div>
            <div className={data.recentFailures.length ? 'grid xl:grid-cols-[minmax(0,1fr)_22rem]' : ''}>
              <div className="max-h-[36rem] divide-y divide-slate-200 overflow-y-auto dark:divide-slate-800">
                {data.recentFailures.map((item) => { const selected = selectedFailure?.runId === item.runId; return <button key={item.runId} type="button" data-ui="media-failure-item" aria-pressed={selected} aria-controls="media-failure-inspector" className={`grid w-full cursor-pointer gap-3 px-5 py-4 text-left transition hover:bg-slate-50 dark:hover:bg-slate-900/45 md:grid-cols-[minmax(0,1fr)_8rem] md:items-center md:px-6 ${selected ? 'bg-blue-50/65 dark:bg-blue-950/20' : ''}`} onClick={() => updateUrl({ focus: item.runId })}><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-slate-950 dark:text-white">{item.errorCode}</span><BackofficeTag tone="warning">{item.targetFormat}</BackofficeTag></div><p className="mt-1 truncate text-sm text-slate-600 dark:text-slate-300">{item.siteId} · {formatBytes(item.sourceBytes)} · {item.finishedAt ? formatDate(item.finishedAt) : t('common.not_found')}</p></div><div className="text-sm font-medium text-slate-500 md:text-right dark:text-slate-400">{formatNumber(item.processingDurationMs)}ms</div></button>; })}
                {data.recentFailures.length ? null : <BackofficeEmptyState className="m-5 md:m-6" title={t('admin.media_obs.no_recent_failures', {}, 'No recent failures.')} description={t('admin.media_obs.no_recent_failures_desc', {}, 'The selected scope has no failed media jobs that require evidence review.')} />}
              </div>
              {data.recentFailures.length ? <div id="media-failure-inspector" className="border-t border-slate-200 p-5 dark:border-slate-800 xl:border-l xl:border-t-0 xl:p-6">
                {selectedFailure ? <div className="space-y-5"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('admin.media_obs.selected_failure', {}, 'Selected failure')}</p><h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{selectedFailure.errorCode}</h3><p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{selectedFailure.finishedAt ? formatDate(selectedFailure.finishedAt) : t('common.not_found')}</p></div><dl className="grid gap-3 text-sm"><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.media_obs.run_id', {}, 'Run ID')}</dt><dd className="mt-1"><BackofficeIdentifier value={selectedFailure.runId} /></dd></div><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('common.site', {}, 'Site')}</dt><dd className="mt-1"><BackofficeIdentifier value={selectedFailure.siteId} /></dd></div><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.media_obs.failure_format_size', {}, 'Format and source size')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{selectedFailure.targetFormat} · {formatBytes(selectedFailure.sourceBytes)}</dd></div><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.media_obs.failure_timing', {}, 'Queue and processing time')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{formatNumber(selectedFailure.queueWaitMs)}ms · {formatNumber(selectedFailure.processingDurationMs)}ms</dd></div></dl><p className="rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-500 dark:bg-slate-900/45 dark:text-slate-400">{t('admin.media_obs.failure_boundary', {}, 'Failure evidence is metadata-only. Image payloads and temporary artifact contents are not exposed here.')}</p></div> : null}
              </div> : null}
            </div>
          </BackofficeSectionPanel>
        </>
      )}

      {data ? <BackofficeDisclosure summary={t('admin.media_obs.advanced_evidence', {}, 'Advanced workflow and error evidence')} contentClassName="space-y-5"><CloudWorkflowMetadataPanel metadata={data.workflowMetadata} /><div><h3 className="text-base font-semibold text-slate-950 dark:text-white">{t('admin.media_obs.errors_title', {}, 'Error codes')}</h3><div className="mt-3 grid gap-2 md:grid-cols-2">{data.errors.length ? data.errors.map((item) => <div key={`${item.errorCode}-${item.lastSeenAt}`} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 px-3 py-2 dark:border-slate-800"><div className="min-w-0"><p className="truncate font-mono text-sm font-semibold text-slate-950 dark:text-white">{item.errorCode}</p><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item.lastSeenAt ? formatDate(item.lastSeenAt) : t('common.not_found')}</p></div><BackofficeTag tone="warning">{formatNumber(item.count)}</BackofficeTag></div>) : <p className="text-sm text-slate-600 dark:text-slate-300">{t('admin.media_obs.no_errors', {}, 'No media processing failures in this window.')}</p>}</div></div></BackofficeDisclosure> : null}
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
