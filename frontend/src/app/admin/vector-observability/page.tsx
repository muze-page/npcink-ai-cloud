'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import {
  BackofficeEmptyState,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { AnalyticsBarChart, AnalyticsLineChart } from '@/components/ui/EChartsWrapper';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber } from '@/lib/utils';

type VectorObservabilityData = {
  generatedAt: string;
  window: { hours: number; startAt: string; endAt: string };
  totals: {
    indexJobsTotal: number;
    indexSucceededTotal: number;
    indexFailedTotal: number;
    indexSuccessRate: number;
    indexedDocumentsTotal: number;
    indexedChunksTotal: number;
    failedDocumentsTotal: number;
    avgIndexDurationMs: number;
    p95IndexDurationMs: number;
    searchQueriesTotal: number;
    searchSucceededTotal: number;
    searchFailedTotal: number;
    searchSuccessRate: number;
    noHitTotal: number;
    noHitRate: number;
    avgSearchLatencyMs: number;
    p95SearchLatencyMs: number;
    avgTop1Score: number;
    indexedSiteCount: number;
    currentDocumentCount: number;
    currentChunkCount: number;
  };
  health: { status: string; score: number; summary: string };
  timeline: Array<{
    bucketStartAt: string;
    indexJobsTotal: number;
    indexedChunksTotal: number;
    searchQueriesTotal: number;
    noHitTotal: number;
    failedTotal: number;
  }>;
  intents: Array<{
    intent: string;
    queriesTotal: number;
    noHitTotal: number;
    noHitRate: number;
    avgTop1Score: number;
    avgLatencyMs: number;
  }>;
  sites: Array<{
    siteId: string;
    queriesTotal: number;
    noHitTotal: number;
    noHitRate: number;
    avgTop1Score: number;
    avgLatencyMs: number;
    lastSearchFinishedAt: string;
    documentCount: number;
    chunkCount: number;
    lastIndexedAt: string;
  }>;
  indexSnapshots: Array<{
    siteId: string;
    documentCount: number;
    chunkCount: number;
    postTypeCounts: Record<string, number>;
    sourceTypeCounts: Record<string, number>;
    lastIndexedAt: string;
    embeddingProvider: string;
    embeddingModel: string;
    embeddingDimensions: number;
    vectorBackend: string;
    capturedAt: string;
  }>;
  errors: Array<{ errorCode: string; count: number; lastSeenAt: string }>;
};

const WINDOW_OPTIONS = [
  { label: '24h', value: 24 },
  { label: '72h', value: 72 },
  { label: '168h', value: 168 },
];

function normalizeVectorObservability(raw: any): VectorObservabilityData {
  const totals = raw?.totals ?? {};
  const window = raw?.window ?? {};
  const health = raw?.health ?? {};
  return {
    generatedAt: String(raw?.generated_at ?? ''),
    window: {
      hours: Number(window.hours ?? 24),
      startAt: String(window.start_at ?? ''),
      endAt: String(window.end_at ?? ''),
    },
    totals: {
      indexJobsTotal: Number(totals.index_jobs_total ?? 0),
      indexSucceededTotal: Number(totals.index_succeeded_total ?? 0),
      indexFailedTotal: Number(totals.index_failed_total ?? 0),
      indexSuccessRate: Number(totals.index_success_rate ?? 0),
      indexedDocumentsTotal: Number(totals.indexed_documents_total ?? 0),
      indexedChunksTotal: Number(totals.indexed_chunks_total ?? 0),
      failedDocumentsTotal: Number(totals.failed_documents_total ?? 0),
      avgIndexDurationMs: Number(totals.avg_index_duration_ms ?? 0),
      p95IndexDurationMs: Number(totals.p95_index_duration_ms ?? 0),
      searchQueriesTotal: Number(totals.search_queries_total ?? 0),
      searchSucceededTotal: Number(totals.search_succeeded_total ?? 0),
      searchFailedTotal: Number(totals.search_failed_total ?? 0),
      searchSuccessRate: Number(totals.search_success_rate ?? 0),
      noHitTotal: Number(totals.no_hit_total ?? 0),
      noHitRate: Number(totals.no_hit_rate ?? 0),
      avgSearchLatencyMs: Number(totals.avg_search_latency_ms ?? 0),
      p95SearchLatencyMs: Number(totals.p95_search_latency_ms ?? 0),
      avgTop1Score: Number(totals.avg_top1_score ?? 0),
      indexedSiteCount: Number(totals.indexed_site_count ?? 0),
      currentDocumentCount: Number(totals.current_document_count ?? 0),
      currentChunkCount: Number(totals.current_chunk_count ?? 0),
    },
    health: {
      status: String(health.status ?? 'inactive'),
      score: Number(health.score ?? 0),
      summary: String(health.summary ?? ''),
    },
    timeline: Array.isArray(raw?.timeline)
      ? raw.timeline.map((item: any) => ({
          bucketStartAt: String(item.bucket_start_at ?? ''),
          indexJobsTotal: Number(item.index_jobs_total ?? 0),
          indexedChunksTotal: Number(item.indexed_chunks_total ?? 0),
          searchQueriesTotal: Number(item.search_queries_total ?? 0),
          noHitTotal: Number(item.no_hit_total ?? 0),
          failedTotal: Number(item.failed_total ?? 0),
        }))
      : [],
    intents: Array.isArray(raw?.intents)
      ? raw.intents.map((item: any) => ({
          intent: String(item.intent ?? ''),
          queriesTotal: Number(item.queries_total ?? 0),
          noHitTotal: Number(item.no_hit_total ?? 0),
          noHitRate: Number(item.no_hit_rate ?? 0),
          avgTop1Score: Number(item.avg_top1_score ?? 0),
          avgLatencyMs: Number(item.avg_latency_ms ?? 0),
        }))
      : [],
    sites: Array.isArray(raw?.sites)
      ? raw.sites.map((item: any) => ({
          siteId: String(item.site_id ?? ''),
          queriesTotal: Number(item.queries_total ?? 0),
          noHitTotal: Number(item.no_hit_total ?? 0),
          noHitRate: Number(item.no_hit_rate ?? 0),
          avgTop1Score: Number(item.avg_top1_score ?? 0),
          avgLatencyMs: Number(item.avg_latency_ms ?? 0),
          lastSearchFinishedAt: String(item.last_search_finished_at ?? ''),
          documentCount: Number(item.document_count ?? 0),
          chunkCount: Number(item.chunk_count ?? 0),
          lastIndexedAt: String(item.last_indexed_at ?? ''),
        }))
      : [],
    indexSnapshots: Array.isArray(raw?.index_snapshots)
      ? raw.index_snapshots.map((item: any) => ({
          siteId: String(item.site_id ?? ''),
          documentCount: Number(item.document_count ?? 0),
          chunkCount: Number(item.chunk_count ?? 0),
          postTypeCounts: item.post_type_counts ?? {},
          sourceTypeCounts: item.source_type_counts ?? {},
          lastIndexedAt: String(item.last_indexed_at ?? ''),
          embeddingProvider: String(item.embedding_provider ?? ''),
          embeddingModel: String(item.embedding_model ?? ''),
          embeddingDimensions: Number(item.embedding_dimensions ?? 0),
          vectorBackend: String(item.vector_backend ?? ''),
          capturedAt: String(item.captured_at ?? ''),
        }))
      : [],
    errors: Array.isArray(raw?.errors)
      ? raw.errors.map((item: any) => ({
          errorCode: String(item.error_code ?? ''),
          count: Number(item.count ?? 0),
          lastSeenAt: String(item.last_seen_at ?? ''),
        }))
      : [],
  };
}

function formatPercent(value: number): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function formatScore(value: number): string {
  return Number(value || 0).toFixed(3);
}

function timelineLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${String(date.getHours()).padStart(2, '0')}:00`;
}

function AdminVectorObservabilityContent() {
  const { t } = useLocale();
  const [data, setData] = useState<VectorObservabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [windowHours, setWindowHours] = useState(24);
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
      const response = await fetch(`/api/admin/vector-observability?${params.toString()}`, {
        credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok || payload?.status === 'error') {
        throw payload;
      }
      setData(normalizeVectorObservability(payload?.data ?? {}));
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [siteIdFilter, t, windowHours]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const searchTimelineData = useMemo(
    () =>
      (data?.timeline || []).map((point) => ({
        label: timelineLabel(point.bucketStartAt),
        value: point.searchQueriesTotal,
        secondaryValue: point.noHitTotal,
      })),
    [data]
  );
  const indexTimelineData = useMemo(
    () =>
      (data?.timeline || []).map((point) => ({
        label: timelineLabel(point.bucketStartAt),
        value: point.indexedChunksTotal,
        secondaryValue: point.failedTotal,
      })),
    [data]
  );
  const intentData = useMemo(
    () =>
      (data?.intents || []).map((item) => ({
        label: item.intent || 'unknown',
        value: item.queriesTotal,
        color: item.noHitRate >= 0.25 ? '#f59e0b' : '#2563eb',
      })),
    [data]
  );
  const isEmpty =
    data !== null &&
    data.totals.indexJobsTotal === 0 &&
    data.totals.searchQueriesTotal === 0 &&
    data.totals.currentChunkCount === 0;

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
        title={t('admin.vector_obs.title', {}, 'Vector Observability')}
        description={t(
          'admin.vector_obs.desc',
          {},
          'Cross-site runtime metrics for Cloud site knowledge indexing and semantic search. This view exposes coverage, hit quality, latency, and errors without showing chunk text, embeddings, or query text.'
        )}
        aside={
          data ? (
            <div className="w-full xl:w-[48rem]">
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-2 xl:grid-cols-5"
                items={[
                  {
                    label: t('admin.vector_obs.health', {}, 'Health'),
                    value: `${data.health.status} · ${data.health.score}`,
                    detail: data.health.summary,
                    toneClassName:
                      data.health.status === 'error'
                        ? 'text-rose-600 dark:text-rose-400'
                        : data.health.status === 'warning'
                          ? 'text-amber-600 dark:text-amber-400'
                          : undefined,
                    size: 'compact',
                  },
                  {
                    label: t('admin.vector_obs.indexed', {}, 'Indexed'),
                    value: formatNumber(data.totals.currentDocumentCount),
                    detail: `${formatNumber(data.totals.currentChunkCount)} chunks`,
                  },
                  {
                    label: t('admin.vector_obs.searches', {}, 'Searches'),
                    value: formatNumber(data.totals.searchQueriesTotal),
                    detail: `${formatNumber(data.totals.noHitTotal)} no-hit`,
                  },
                  {
                    label: t('admin.vector_obs.no_hit_rate', {}, 'No-hit rate'),
                    value: formatPercent(data.totals.noHitRate),
                    toneClassName:
                      data.totals.noHitRate >= 0.25
                        ? 'text-amber-600 dark:text-amber-400'
                        : undefined,
                  },
                  {
                    label: t('admin.vector_obs.p95', {}, 'P95 search'),
                    value: `${formatNumber(data.totals.p95SearchLatencyMs)}ms`,
                    detail: `top1 ${formatScore(data.totals.avgTop1Score)}`,
                    size: 'compact',
                  },
                ]}
              />
            </div>
          ) : null
        }
      />

      <BackofficeSectionPanel>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
              {t('admin.vector_obs.filters', {}, 'Filters')}
            </h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              {t('admin.vector_obs.filters_desc', {}, 'Inspect one site or compare all sites in the selected window.')}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-950">
              {WINDOW_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setWindowHours(option.value)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                    windowHours === option.value
                      ? 'bg-slate-950 text-white dark:bg-white dark:text-slate-950'
                      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <input
              type="text"
              value={siteIdInput}
              onChange={(event) => setSiteIdInput(event.target.value)}
              placeholder={t('admin.vector_obs.site_filter', {}, 'Site ID')}
              className="input input-bordered input-sm w-56"
            />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setSiteIdFilter(siteIdInput.trim())}
            >
              {t('common.apply', {}, 'Apply')}
            </button>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadData()}>
              {t('common.refresh', {}, 'Refresh')}
            </button>
          </div>
        </div>
      </BackofficeSectionPanel>

      {isEmpty ? (
        <BackofficeEmptyState
          title={t('admin.vector_obs.empty_title', {}, 'No vector activity yet')}
          description={t(
            'admin.vector_obs.empty_desc',
            {},
            'Vector observability will populate after sites run knowledge sync or semantic search through Cloud.'
          )}
        />
      ) : (
        <>
          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('admin.vector_obs.search_trend', {}, 'Searches and no-hit')}
              </h3>
              <AnalyticsLineChart
                data={searchTimelineData}
                height={260}
                primarySeriesName={t('admin.vector_obs.searches', {}, 'Searches')}
                secondarySeriesName={t('admin.vector_obs.no_hit', {}, 'No-hit')}
                primaryColor="#2563eb"
                secondaryColor="#f59e0b"
              />
            </BackofficeStackCard>
            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('admin.vector_obs.index_trend', {}, 'Indexed chunks and failures')}
              </h3>
              <AnalyticsLineChart
                data={indexTimelineData}
                height={260}
                primarySeriesName={t('admin.vector_obs.chunks', {}, 'Chunks')}
                secondarySeriesName={t('admin.vector_obs.failures', {}, 'Failures')}
                primaryColor="#10b981"
                secondaryColor="#ef4444"
              />
            </BackofficeStackCard>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <BackofficeStackCard className="space-y-3 xl:col-span-2">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('admin.vector_obs.sites', {}, 'Sites')}
              </h3>
              <div className="overflow-x-auto">
                <table className="min-w-full text-left text-sm">
                  <thead className="text-xs uppercase text-slate-500 dark:text-slate-400">
                    <tr>
                      <th className="px-3 py-2">{t('common.site', {}, 'Site')}</th>
                      <th className="px-3 py-2">{t('admin.vector_obs.coverage', {}, 'Coverage')}</th>
                      <th className="px-3 py-2">{t('admin.vector_obs.searches', {}, 'Searches')}</th>
                      <th className="px-3 py-2">{t('admin.vector_obs.no_hit', {}, 'No-hit')}</th>
                      <th className="px-3 py-2">{t('admin.vector_obs.latency', {}, 'Latency')}</th>
                      <th className="px-3 py-2">{t('admin.vector_obs.last_seen', {}, 'Last seen')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                    {(data?.sites || []).map((site) => (
                      <tr key={site.siteId}>
                        <td className="px-3 py-3">
                          <BackofficeIdentifier value={site.siteId} />
                        </td>
                        <td className="px-3 py-3">
                          {formatNumber(site.documentCount)} docs · {formatNumber(site.chunkCount)} chunks
                        </td>
                        <td className="px-3 py-3">{formatNumber(site.queriesTotal)}</td>
                        <td className="px-3 py-3">{formatPercent(site.noHitRate)}</td>
                        <td className="px-3 py-3">{formatNumber(site.avgLatencyMs)}ms</td>
                        <td className="px-3 py-3">
                          {site.lastSearchFinishedAt ? formatDate(site.lastSearchFinishedAt) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </BackofficeStackCard>

            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('admin.vector_obs.intents', {}, 'Search intents')}
              </h3>
              <AnalyticsBarChart data={intentData} height={220} barColor="#2563eb" />
              <div className="space-y-2">
                {(data?.intents || []).slice(0, 5).map((intent) => (
                  <div key={intent.intent} className="flex items-center justify-between gap-3 text-sm">
                    <span className="font-medium text-slate-700 dark:text-slate-200">{intent.intent}</span>
                    <BackofficeTag tone={intent.noHitRate >= 0.25 ? 'warning' : 'info'}>
                      {formatNumber(intent.queriesTotal)}
                    </BackofficeTag>
                  </div>
                ))}
              </div>
            </BackofficeStackCard>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('admin.vector_obs.snapshots', {}, 'Latest index snapshots')}
              </h3>
              <div className="space-y-2">
                {(data?.indexSnapshots || []).slice(0, 8).map((snapshot) => (
                  <div
                    key={`${snapshot.siteId}-${snapshot.capturedAt}`}
                    className="rounded-lg border border-slate-200/80 bg-white/70 p-3 text-sm dark:border-slate-800 dark:bg-slate-900/40"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <BackofficeIdentifier value={snapshot.siteId} />
                      <BackofficeTag tone="info">{snapshot.vectorBackend || 'local'}</BackofficeTag>
                    </div>
                    <div className="mt-2 text-slate-600 dark:text-slate-300">
                      {formatNumber(snapshot.documentCount)} docs · {formatNumber(snapshot.chunkCount)} chunks ·{' '}
                      {snapshot.embeddingProvider || 'deterministic'} {snapshot.embeddingDimensions}d
                    </div>
                  </div>
                ))}
              </div>
            </BackofficeStackCard>

            <BackofficeStackCard className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                  {t('admin.vector_obs.errors', {}, 'Errors')}
                </h3>
                <BackofficeStatusBadge
                  status={(data?.errors || []).length ? 'warning' : 'ok'}
                  label={(data?.errors || []).length ? 'needs attention' : 'ok'}
                />
              </div>
              {(data?.errors || []).length ? (
                <div className="space-y-2">
                  {(data?.errors || []).map((item) => (
                    <div
                      key={`${item.errorCode}-${item.lastSeenAt}`}
                      className="flex items-center justify-between gap-3 rounded-lg border border-slate-200/80 bg-white/70 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900/40"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-slate-950 dark:text-white">{item.errorCode}</p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {item.lastSeenAt ? formatDate(item.lastSeenAt) : '-'}
                        </p>
                      </div>
                      <BackofficeTag tone="warning">{formatNumber(item.count)}</BackofficeTag>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  {t('admin.vector_obs.no_errors', {}, 'No search failures in this window.')}
                </p>
              )}
            </BackofficeStackCard>
          </div>
        </>
      )}
    </BackofficePageStack>
  );
}

export default function AdminVectorObservabilityPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminVectorObservabilityContent />
    </Suspense>
  );
}
