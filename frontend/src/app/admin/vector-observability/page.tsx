'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  BackofficeEmptyState,
  BackofficeDiagnosticNotice,
  BackofficeDisclosure,
  BackofficeLayer,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { AnalyticsBarChart, AnalyticsLineChart } from '@/components/ui/EChartsWrapper';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber } from '@/lib/utils';

const vectorObservabilityClient = createApiClient({ idempotencyPrefix: 'vector_observability' });

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

function vectorStatusLabel(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  status: string
): string {
  return t(`status.${status || 'unknown'}`, {}, status || 'unknown');
}

function timelineLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${String(date.getHours()).padStart(2, '0')}:00`;
}

function normalizeVectorWindow(value: string | null): number {
  const parsed = Number(value);
  return parsed === 72 || parsed === 168 ? parsed : 24;
}

function AdminVectorObservabilityContent() {
  const { t } = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const windowHours = normalizeVectorWindow(searchParams.get('window'));
  const siteIdFilter = searchParams.get('site') || '';
  const focusedErrorCode = searchParams.get('focus') || '';
  const [data, setData] = useState<VectorObservabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [siteIdInput, setSiteIdInput] = useState(siteIdFilter);
  const requestControllerRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);

  const updateUrl = useCallback((updates: { window?: number | null; site?: string | null; focus?: string | null }) => {
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
      const response = await vectorObservabilityClient.request<unknown>(`/api/admin/vector-observability?${params.toString()}`, {
        signal: controller.signal,
      });
      if (sequence === requestSequenceRef.current) {
        setData(normalizeVectorObservability(response.data));
        hasLoadedRef.current = true;
      }
    } catch (err) {
      if (sequence === requestSequenceRef.current) {
        setError(resolveUiErrorMessage(err, t('admin.vector_obs.load_error', {}, 'Failed to load vector diagnostics.')));
      }
    } finally {
      globalThis.clearTimeout(timeout);
      if (sequence === requestSequenceRef.current) {
        requestControllerRef.current = null;
        setLoading(false);
      }
    }
  }, [siteIdFilter, t, windowHours]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    setSiteIdInput(siteIdFilter);
  }, [siteIdFilter]);

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
        label: item.intent || t('admin.vector_obs.unknown_intent', {}, 'Unknown'),
        value: item.queriesTotal,
        color: item.noHitRate >= 0.25 ? '#f59e0b' : '#2563eb',
      })),
    [data, t]
  );
  const selectedError = data?.errors.find((item) => item.errorCode === focusedErrorCode)
    || data?.errors[0]
    || null;
  const isEmpty =
    data !== null &&
    data.totals.indexJobsTotal === 0 &&
    data.totals.searchQueriesTotal === 0 &&
    data.totals.currentChunkCount === 0;
  const emptyChecks = [
    t(
      'admin.vector_obs.empty_check_sync',
      {},
      'Confirm the site has run Site Knowledge sync through Cloud.'
    ),
    t(
      'admin.vector_obs.empty_check_embedding',
      {},
      'Check the embedding provider and model binding before retrying sync.'
    ),
    t(
      'admin.vector_obs.empty_check_vector_store',
      {},
      'Check vector store connectivity if sync jobs exist but no chunks appear.'
    ),
    t(
      'admin.vector_obs.empty_check_search',
      {},
      'Confirm semantic search traffic exists for the selected site and window.'
    ),
  ];

  if (loading && !data) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficeLayer
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.vector_obs.title', {}, 'Vector Observability')}
        description={t(
          'admin.vector_obs.desc',
          {},
          'Cross-site runtime metrics for Cloud site knowledge indexing and semantic search. This view exposes coverage, hit quality, latency, and errors without showing chunk text, embeddings, or query text.'
        )}
        aside={data ? <BackofficeStatusBadge status={data.health.status} label={`${vectorStatusLabel(t, data.health.status)} · ${data.health.score}`} /> : undefined}
        actions={<button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadData(true)} disabled={loading}>{t('common.refresh', {}, 'Refresh')}</button>}
      />

      <BackofficeSectionPanel className="p-4 md:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
              {t('admin.vector_obs.filters', {}, 'Filters')}
            </h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              {t('admin.vector_obs.filters_desc', {}, 'Inspect one site or compare all sites in the selected window.')}
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
            <div className="flex flex-wrap items-center gap-2">
              {WINDOW_OPTIONS.map((option) => (
                <BackofficeFilterPill
                  key={option.value}
                  active={windowHours === option.value}
                  tone="info"
                  onClick={() => updateUrl({ window: option.value, focus: null })}
                >
                  {option.label}
                </BackofficeFilterPill>
              ))}
            </div>
            <input
              type="text"
              value={siteIdInput}
              aria-label={t('admin.vector_obs.site_filter_label', {}, 'Filter by site ID')}
              onChange={(event) => setSiteIdInput(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') updateUrl({ site: siteIdInput.trim() || null, focus: null }); }}
              placeholder={t('admin.vector_obs.site_filter', {}, 'Site ID')}
              className="input h-9 min-w-0 sm:w-56"
            />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => updateUrl({ site: siteIdInput.trim() || null, focus: null })}
            >
              {t('common.apply', {}, 'Apply')}
            </button>
            {siteIdFilter ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setSiteIdInput(''); updateUrl({ site: null, focus: null }); }}>{t('common.clear_filters', {}, 'Clear filters')}</button> : null}
          </div>
        </div>
      </BackofficeSectionPanel>

      {data ? <BackofficeSummaryStrip items={[
        { label: t('admin.vector_obs.indexed', {}, 'Indexed'), value: formatNumber(data.totals.currentDocumentCount), detail: t('admin.vector_obs.detail_chunks', { count: formatNumber(data.totals.currentChunkCount) }, '{{count}} chunks') },
        { label: t('admin.vector_obs.searches', {}, 'Searches'), value: formatNumber(data.totals.searchQueriesTotal), detail: t('admin.vector_obs.detail_no_hit', { count: formatNumber(data.totals.noHitTotal) }, '{{count}} no-hit') },
        { label: t('admin.vector_obs.no_hit_rate', {}, 'No-hit rate'), value: formatPercent(data.totals.noHitRate), toneClassName: data.totals.noHitRate >= 0.25 ? 'text-amber-600 dark:text-amber-400' : undefined },
        { label: t('admin.vector_obs.p95', {}, 'P95 search'), value: `${formatNumber(data.totals.p95SearchLatencyMs)}ms`, detail: t('admin.vector_obs.detail_top1', { score: formatScore(data.totals.avgTop1Score) }, 'top1 {{score}}') },
        { label: t('admin.vector_obs.errors', {}, 'Errors'), value: formatNumber(data.errors.reduce((total, item) => total + item.count, 0)), toneClassName: data.errors.length ? 'text-rose-600 dark:text-rose-400' : undefined },
      ]} /> : null}

      {error ? <BackofficeDiagnosticNotice message={error} staleDescription={data ? t('admin.vector_obs.stale_notice', {}, 'The last successfully loaded vector snapshot remains visible.') : undefined} retryLabel={t('common.retry')} onRetry={() => void loadData(true)} /> : null}

      {!data ? null : isEmpty ? (
        <>
          <BackofficeEmptyState
            title={t('admin.vector_obs.empty_title', {}, 'No vector activity yet')}
            description={t(
              'admin.vector_obs.empty_desc',
              {},
              'Vector observability will populate after sites run knowledge sync or semantic search through Cloud.'
            )}
          />
          <BackofficeSectionPanel>
            <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('admin.vector_obs.empty_checks_title', {}, 'Read-only checks')}
            </h3>
            <ul className="mt-3 space-y-2 text-sm text-slate-600 dark:text-slate-300">
              {emptyChecks.map((item) => (
                <li key={item} className="flex gap-2">
                  <span aria-hidden="true" className="mt-2 h-1.5 w-1.5 rounded-full bg-slate-400" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </BackofficeSectionPanel>
        </>
      ) : (
        <>
          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeStackCard className="min-w-0 space-y-3 overflow-hidden">
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
            <BackofficeStackCard className="min-w-0 space-y-3 overflow-hidden">
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
            <BackofficeStackCard className="min-w-0 space-y-3 overflow-hidden xl:col-span-2">
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
                          {t(
                            'admin.vector_obs.coverage_value',
                            {
                              docs: formatNumber(site.documentCount),
                              chunks: formatNumber(site.chunkCount),
                            },
                            '{{docs}} docs · {{chunks}} chunks'
                          )}
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

            <BackofficeStackCard className="min-w-0 space-y-3 overflow-hidden">
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

          <BackofficeSectionPanel className="overflow-hidden p-0 md:p-0">
            <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800 md:px-6"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('admin.vector_obs.attention_label', {}, 'Attention')}</p><h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">{t('admin.vector_obs.error_queue_title', {}, 'Vector error queue')}</h2><p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('admin.vector_obs.error_queue_desc', {}, 'Select an error code to inspect its count, last-seen time, current scope, and read-only boundary.')}</p></div>
            <div className={data.errors.length ? 'grid xl:grid-cols-[minmax(0,1fr)_22rem]' : ''}>
              <div className="max-h-[32rem] divide-y divide-slate-200 overflow-y-auto dark:divide-slate-800">
                {data.errors.map((item) => { const selected = selectedError?.errorCode === item.errorCode; return <button key={`${item.errorCode}-${item.lastSeenAt}`} type="button" data-ui="vector-error-item" aria-pressed={selected} aria-controls="vector-error-inspector" className={`grid w-full cursor-pointer gap-3 px-5 py-4 text-left transition hover:bg-slate-50 dark:hover:bg-slate-900/45 md:grid-cols-[minmax(0,1fr)_8rem] md:items-center md:px-6 ${selected ? 'bg-blue-50/65 dark:bg-blue-950/20' : ''}`} onClick={() => updateUrl({ focus: item.errorCode })}><div className="min-w-0"><p className="truncate font-semibold text-slate-950 dark:text-white">{item.errorCode}</p><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{item.lastSeenAt ? formatDate(item.lastSeenAt) : t('common.not_found')}</p></div><div className="md:text-right"><BackofficeTag tone="warning">{formatNumber(item.count)}</BackofficeTag></div></button>; })}
                {data.errors.length ? null : <BackofficeEmptyState className="m-5 md:m-6" title={t('admin.vector_obs.no_errors', {}, 'No search failures in this window.')} description={t('admin.vector_obs.no_errors_desc', {}, 'The selected scope has no vector errors that require evidence review.')} />}
              </div>
              {data.errors.length ? <div id="vector-error-inspector" className="border-t border-slate-200 p-5 dark:border-slate-800 xl:border-l xl:border-t-0 xl:p-6">
                {selectedError ? <div className="space-y-5"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('admin.vector_obs.selected_error', {}, 'Selected error')}</p><h3 className="mt-2 break-words text-lg font-semibold text-slate-950 dark:text-white">{selectedError.errorCode}</h3></div><dl className="grid gap-3 text-sm"><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.vector_obs.occurrences', {}, 'Occurrences')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{formatNumber(selectedError.count)}</dd></div><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.vector_obs.last_seen', {}, 'Last seen')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{selectedError.lastSeenAt ? formatDate(selectedError.lastSeenAt) : t('common.not_found')}</dd></div><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.vector_obs.scope', {}, 'Current scope')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{siteIdFilter || t('admin.vector_obs.all_sites', {}, 'All sites')} · {windowHours}h</dd></div></dl><p className="rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-500 dark:bg-slate-900/45 dark:text-slate-400">{t('admin.vector_obs.error_boundary', {}, 'This surface exposes aggregate runtime evidence only. Chunk text, embeddings, and query text remain hidden.')}</p></div> : null}
              </div> : null}
            </div>
          </BackofficeSectionPanel>

          <BackofficeDisclosure summary={t('admin.vector_obs.advanced_snapshots', {}, 'Advanced index snapshots')} contentClassName="grid gap-3 md:grid-cols-2">{data.indexSnapshots.slice(0, 8).map((snapshot) => <div key={`${snapshot.siteId}-${snapshot.capturedAt}`} className="min-w-0 rounded-xl border border-slate-200/80 p-3 text-sm dark:border-slate-800"><div className="flex flex-wrap items-center justify-between gap-2"><BackofficeIdentifier value={snapshot.siteId} /><BackofficeTag tone="info">{snapshot.vectorBackend || t('admin.vector_obs.backend_local', {}, 'local')}</BackofficeTag></div><div className="mt-2 text-slate-600 dark:text-slate-300">{t('admin.vector_obs.coverage_value', { docs: formatNumber(snapshot.documentCount), chunks: formatNumber(snapshot.chunkCount) }, '{{docs}} docs · {{chunks}} chunks')} · {snapshot.embeddingProvider || t('admin.vector_obs.embedding_deterministic', {}, 'deterministic')} {snapshot.embeddingDimensions}d</div></div>)}</BackofficeDisclosure>
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
