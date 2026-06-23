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
import { AnalyticsBarChart, AnalyticsLineChart } from '@/components/ui/EChartsWrapper';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber as formatInteger } from '@/lib/utils';

type PluginObservabilityTotals = {
  eventsTotal: number;
  okTotal: number;
  errorTotal: number;
  successRate: number;
  avgLatencyMs: number;
  lastSeenAt: string;
  activeSiteCount: number;
  activePluginCount: number;
};

type EventKindItem = {
  eventKind: string;
  eventsTotal: number;
  errorTotal: number;
  successRate: number;
  avgLatencyMs: number;
  lastSeenAt: string;
};

type PluginItem = {
  pluginSlug: string;
  eventsTotal: number;
  okTotal: number;
  errorTotal: number;
  successRate: number;
  avgLatencyMs: number;
  lastSeenAt: string;
  eventKinds: EventKindItem[];
};

type SiteItem = {
  siteId: string;
  eventsTotal: number;
  errorTotal: number;
  okTotal: number;
  successRate: number;
  avgLatencyMs: number;
  pluginCount: number;
  lastSeenAt: string;
  health: HealthSummary;
};

type ErrorItem = {
  siteId: string | null;
  pluginSlug: string;
  eventKind: string;
  errorCode: string;
  count: number;
  lastSeenAt: string;
};

type RecentErrorItem = {
  siteId: string;
  pluginSlug: string;
  eventKind: string;
  errorCode: string;
  status: string;
  abilityId: string;
  proposalId: string;
  route: string;
  receivedAt: string;
};

type TimelinePoint = {
  bucketStartAt: string;
  bucketEndAt: string;
  bucketHours: number;
  eventsTotal: number;
  okTotal: number;
  errorTotal: number;
  successRate: number;
  avgLatencyMs: number;
};

type HealthSummary = {
  status: string;
  score: number;
  summary: string;
  reasons: string[];
};

type AttentionItem = {
  attentionKey: string;
  severity: string;
  code: string;
  title: string;
  detail: string;
  suggestedAction: string;
  workflowStatus: string;
  siteId: string;
  pluginSlug: string;
  eventKind: string;
  errorCode: string;
  state: {
    mutedUntil: string;
    operatorNote: string;
    updatedAt: string;
  } | null;
};

type AttentionWorkflow = {
  active: number;
  acknowledged: number;
  muted: number;
  resolved: number;
  total: number;
  needsAttention: number;
};

type ObservabilityDigest = {
  periodLabel: string;
  windowHours: number;
  headline: string;
  bullets: string[];
  topPluginSlug: string;
  topErrorCode: string;
};

type PluginObservabilityData = {
  generatedAt: string;
  totals: PluginObservabilityTotals;
  health: HealthSummary;
  attention: AttentionItem[];
  attentionWorkflow: AttentionWorkflow;
  digest: ObservabilityDigest;
  plugins: PluginItem[];
  sites: SiteItem[];
  timeline: TimelinePoint[];
  errors: ErrorItem[];
  recentErrors: RecentErrorItem[];
  window: {
    hours: number;
    startAt: string;
    endAt: string;
  };
};

function normalizePluginObservability(raw: any): PluginObservabilityData {
  const totals = raw?.totals ?? {};
  const window = raw?.window ?? {};
  const health = raw?.health ?? {};
  return {
    generatedAt: String(raw?.generated_at ?? ''),
    totals: {
      eventsTotal: Number(totals.events_total ?? 0),
      okTotal: Number(totals.ok_total ?? 0),
      errorTotal: Number(totals.error_total ?? 0),
      successRate: Number(totals.success_rate ?? 0),
      avgLatencyMs: Number(totals.avg_latency_ms ?? 0),
      lastSeenAt: String(totals.last_seen_at ?? ''),
      activeSiteCount: Number(totals.active_site_count ?? 0),
      activePluginCount: Number(totals.active_plugin_count ?? 0),
    },
    health: {
      status: String(health.status ?? 'inactive'),
      score: Number(health.score ?? 0),
      summary: String(health.summary ?? ''),
      reasons: Array.isArray(health.reasons) ? health.reasons.map((item: any) => String(item)) : [],
    },
    attention: Array.isArray(raw?.attention)
      ? raw.attention.map((item: any) => ({
          severity: String(item.severity ?? ''),
          code: String(item.code ?? ''),
          attentionKey: String(item.attention_key ?? ''),
          title: String(item.title ?? ''),
          detail: String(item.detail ?? ''),
          suggestedAction: String(item.suggested_action ?? ''),
          workflowStatus: String(item.workflow_status ?? 'active'),
          siteId: String(item.site_id ?? ''),
          pluginSlug: String(item.plugin_slug ?? ''),
          eventKind: String(item.event_kind ?? ''),
          errorCode: String(item.error_code ?? ''),
          state: item.state
            ? {
                mutedUntil: String(item.state.muted_until ?? ''),
                operatorNote: String(item.state.operator_note ?? ''),
                updatedAt: String(item.state.updated_at ?? ''),
              }
            : null,
        }))
      : [],
    attentionWorkflow: {
      active: Number(raw?.attention_workflow?.active ?? 0),
      acknowledged: Number(raw?.attention_workflow?.acknowledged ?? 0),
      muted: Number(raw?.attention_workflow?.muted ?? 0),
      resolved: Number(raw?.attention_workflow?.resolved ?? 0),
      total: Number(raw?.attention_workflow?.total ?? 0),
      needsAttention: Number(raw?.attention_workflow?.needs_attention ?? 0),
    },
    digest: {
      periodLabel: String(raw?.digest?.period_label ?? ''),
      windowHours: Number(raw?.digest?.window_hours ?? 0),
      headline: String(raw?.digest?.headline ?? ''),
      bullets: Array.isArray(raw?.digest?.bullets)
        ? raw.digest.bullets.map((item: any) => String(item))
        : [],
      topPluginSlug: String(raw?.digest?.top_plugin_slug ?? ''),
      topErrorCode: String(raw?.digest?.top_error_code ?? ''),
    },
    plugins: Array.isArray(raw?.plugins)
      ? raw.plugins.map((p: any) => ({
          pluginSlug: String(p.plugin_slug ?? ''),
          eventsTotal: Number(p.events_total ?? 0),
          okTotal: Number(p.ok_total ?? 0),
          errorTotal: Number(p.error_total ?? 0),
          successRate: Number(p.success_rate ?? 0),
          avgLatencyMs: Number(p.avg_latency_ms ?? 0),
          lastSeenAt: String(p.last_seen_at ?? ''),
          eventKinds: Array.isArray(p.event_kinds)
            ? p.event_kinds.map((ek: any) => ({
                eventKind: String(ek.event_kind ?? ''),
                eventsTotal: Number(ek.events_total ?? 0),
                errorTotal: Number(ek.error_total ?? 0),
                successRate: Number(ek.success_rate ?? 0),
                avgLatencyMs: Number(ek.avg_latency_ms ?? 0),
                lastSeenAt: String(ek.last_seen_at ?? ''),
              }))
            : [],
        }))
      : [],
    sites: Array.isArray(raw?.sites)
      ? raw.sites.map((s: any) => ({
          health: {
            status: String(s.health?.status ?? 'inactive'),
            score: Number(s.health?.score ?? 0),
            summary: String(s.health?.summary ?? ''),
            reasons: Array.isArray(s.health?.reasons) ? s.health.reasons.map((item: any) => String(item)) : [],
          },
          siteId: String(s.site_id ?? ''),
          eventsTotal: Number(s.events_total ?? 0),
          errorTotal: Number(s.error_total ?? 0),
          okTotal: Number(s.ok_total ?? 0),
          successRate: Number(s.success_rate ?? 0),
          avgLatencyMs: Number(s.avg_latency_ms ?? 0),
          pluginCount: Number(s.plugin_count ?? 0),
          lastSeenAt: String(s.last_seen_at ?? ''),
        }))
      : [],
    timeline: Array.isArray(raw?.timeline)
      ? raw.timeline.map((point: any) => ({
          bucketStartAt: String(point.bucket_start_at ?? ''),
          bucketEndAt: String(point.bucket_end_at ?? ''),
          bucketHours: Number(point.bucket_hours ?? 1),
          eventsTotal: Number(point.events_total ?? 0),
          okTotal: Number(point.ok_total ?? 0),
          errorTotal: Number(point.error_total ?? 0),
          successRate: Number(point.success_rate ?? 0),
          avgLatencyMs: Number(point.avg_latency_ms ?? 0),
        }))
      : [],
    errors: Array.isArray(raw?.errors)
      ? raw.errors.map((e: any) => ({
          siteId: e.site_id ?? null,
          pluginSlug: String(e.plugin_slug ?? ''),
          eventKind: String(e.event_kind ?? ''),
          errorCode: String(e.error_code ?? ''),
          count: Number(e.count ?? 0),
          lastSeenAt: String(e.last_seen_at ?? ''),
        }))
      : [],
    recentErrors: Array.isArray(raw?.recent_errors)
      ? raw.recent_errors.map((re: any) => ({
          siteId: String(re.site_id ?? ''),
          pluginSlug: String(re.plugin_slug ?? ''),
          eventKind: String(re.event_kind ?? ''),
          errorCode: String(re.error_code ?? ''),
          status: String(re.status ?? ''),
          abilityId: String(re.ability_id ?? ''),
          proposalId: String(re.proposal_id ?? ''),
          route: String(re.route ?? ''),
          receivedAt: String(re.received_at ?? ''),
        }))
      : [],
    window: {
      hours: Number(window.hours ?? 24),
      startAt: String(window.start_at ?? ''),
      endAt: String(window.end_at ?? ''),
    },
  };
}

type WindowOption = 24 | 72 | 168;
type PluginFilter = 'all' | 'npcink-abilities-toolkit' | 'npcink-governance-core' | 'npcink-ai-client-adapter';
type AttentionWorkflowFilter = 'active' | 'acknowledged' | 'muted' | 'resolved' | 'all';
type AttentionSeverityFilter = 'all' | 'warning' | 'error';
type AttentionStateAction = 'acknowledge' | 'mute' | 'resolve' | 'clear';

const WINDOW_OPTIONS: { value: WindowOption; label: string }[] = [
  { value: 24, label: '24h' },
  { value: 72, label: '72h' },
  { value: 168, label: '168h' },
];

const PLUGIN_FILTER_OPTIONS: { value: PluginFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'npcink-abilities-toolkit', label: 'Abilities' },
  { value: 'npcink-governance-core', label: 'Core' },
  { value: 'npcink-ai-client-adapter', label: 'Adapter' },
];

const ATTENTION_WORKFLOW_OPTIONS: { value: AttentionWorkflowFilter; label: string }[] = [
  { value: 'active', label: 'Open' },
  { value: 'acknowledged', label: 'Ack' },
  { value: 'muted', label: 'Muted' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'all', label: 'All' },
];

const ATTENTION_SEVERITY_OPTIONS: { value: AttentionSeverityFilter; label: string }[] = [
  { value: 'all', label: 'All severity' },
  { value: 'error', label: 'Error' },
  { value: 'warning', label: 'Warning' },
];

function formatSuccessRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function successRateStatus(rate: number): string {
  if (rate >= 0.99) return 'success';
  if (rate >= 0.95) return 'warning';
  return 'error';
}

function attentionTone(severity: string): 'warning' | 'danger' | 'info' {
  if (severity === 'error') return 'danger';
  if (severity === 'warning') return 'warning';
  return 'info';
}

function timelineLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${String(date.getHours()).padStart(2, '0')}:00`;
}

function timestampValue(value: string): number {
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : 0;
}

type SiteSortKey = 'errors' | 'success' | 'events' | 'latency' | 'lastSeen';

function AdminPluginObservabilityContent() {
  const { t } = useLocale();
  const [data, setData] = useState<PluginObservabilityData | null>(null);
  const [error, setError] = useState('');
  const [windowHours, setWindowHours] = useState<WindowOption>(24);
  const [pluginFilter, setPluginFilter] = useState<PluginFilter>('all');
  const [siteIdFilter, setSiteIdFilter] = useState('');
  const [siteIdInput, setSiteIdInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [siteSort, setSiteSort] = useState<SiteSortKey>('errors');
  const [attentionWorkflowFilter, setAttentionWorkflowFilter] =
    useState<AttentionWorkflowFilter>('active');
  const [attentionSeverityFilter, setAttentionSeverityFilter] =
    useState<AttentionSeverityFilter>('all');
  const [attentionCodeFilter, setAttentionCodeFilter] = useState('all');
  const [attentionActionKey, setAttentionActionKey] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ window_hours: String(windowHours) });
      if (pluginFilter !== 'all') params.set('plugin_slug', pluginFilter);
      if (siteIdFilter) params.set('site_id', siteIdFilter);
      const response = await fetch(`/api/admin/plugin-observability?${params}`, { credentials: 'include' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setData(normalizePluginObservability(payload.data));
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setLoading(false);
    }
  }, [windowHours, pluginFilter, siteIdFilter, t]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleSiteIdSubmit = () => {
    setSiteIdFilter(siteIdInput.trim());
  };

  const handleSiteIdKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSiteIdSubmit();
  };

  const handleAttentionStateAction = useCallback(
    async (item: AttentionItem, action: AttentionStateAction) => {
      if (!item.attentionKey) return;
      setAttentionActionKey(`${item.attentionKey}-${action}`);
      try {
        const response = await fetch('/api/admin/plugin-observability/attention-state', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': crypto.randomUUID(),
          },
          body: JSON.stringify({
            attention_key: item.attentionKey,
            attention_code: item.code,
            action,
            site_id: item.siteId,
            plugin_slug: item.pluginSlug,
            event_kind: item.eventKind,
            error_code: item.errorCode,
            mute_hours: 24,
          }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await loadData();
      } catch (err) {
        setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
      } finally {
        setAttentionActionKey('');
      }
    },
    [loadData, t]
  );

  const timelineData = useMemo(
    () =>
      (data?.timeline || []).map((point) => ({
        label: timelineLabel(point.bucketStartAt),
        value: point.eventsTotal,
        secondaryValue: point.errorTotal,
      })),
    [data]
  );

  const pluginErrorData = useMemo(
    () =>
      (data?.plugins || []).map((plugin) => ({
        label: plugin.pluginSlug.replace('npcink-', ''),
        value: plugin.errorTotal,
        color: plugin.errorTotal > 0 ? '#f59e0b' : '#22c55e',
      })),
    [data]
  );

  const pluginVolumeData = useMemo(
    () =>
      (data?.plugins || []).map((plugin) => ({
        label: plugin.pluginSlug.replace('npcink-', ''),
        value: plugin.eventsTotal,
        color: plugin.errorTotal > 0 ? '#f59e0b' : '#2563eb',
      })),
    [data]
  );

  const hasPluginErrors = pluginErrorData.some((item) => item.value > 0);

  const attentionCodeOptions = useMemo(() => {
    const codes = new Set((data?.attention || []).map((item) => item.code).filter(Boolean));
    return ['all', ...Array.from(codes).sort()];
  }, [data]);

  const filteredAttention = useMemo(() => {
    return (data?.attention || []).filter((item) => {
      if (
        attentionWorkflowFilter !== 'all' &&
        item.workflowStatus !== attentionWorkflowFilter
      ) {
        return false;
      }
      if (attentionSeverityFilter !== 'all' && item.severity !== attentionSeverityFilter) {
        return false;
      }
      if (attentionCodeFilter !== 'all' && item.code !== attentionCodeFilter) {
        return false;
      }
      return true;
    });
  }, [attentionCodeFilter, attentionSeverityFilter, attentionWorkflowFilter, data]);

  const sortedSites = useMemo(() => {
    const sites = [...(data?.sites || [])];
    return sites.sort((a, b) => {
      if (siteSort === 'success') return a.successRate - b.successRate;
      if (siteSort === 'events') return b.eventsTotal - a.eventsTotal;
      if (siteSort === 'latency') return b.avgLatencyMs - a.avgLatencyMs;
      if (siteSort === 'lastSeen') {
        return timestampValue(b.lastSeenAt) - timestampValue(a.lastSeenAt);
      }
      return b.errorTotal - a.errorTotal || a.successRate - b.successRate;
    });
  }, [data, siteSort]);

  const errorBySite = useMemo(() => {
    const lookup = new Map<string, ErrorItem>();
    for (const item of data?.errors || []) {
      if (item.siteId && !lookup.has(item.siteId)) {
        lookup.set(item.siteId, item);
      }
    }
    return lookup;
  }, [data]);

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-red-600">{t('common.error')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{error}</p>
          <button onClick={() => window.location.reload()} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  if (loading && !data) {
    return <LoadingFallback />;
  }

  const isEmpty = data !== null && data.totals.eventsTotal === 0;

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.plugin_observability_title', {}, 'Plugin Observability')}
        description={t(
          'admin.plugin_observability_desc',
          {},
          'Cross-site plugin event volume, error rates, latency, and recent errors for npcink-abilities-toolkit, npcink-governance-core, and npcink-ai-client-adapter.'
        )}
        aside={
          data ? (
            <div className="w-full xl:w-[48rem]">
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-2 xl:grid-cols-5"
                items={[
                  {
                    label: t('admin.plugin_obs_health', {}, 'Health'),
                    value: `${data.health.status} · ${data.health.score}`,
                    detail: data.health.summary,
                    toneClassName: data.health.status === 'error' ? 'text-rose-600 dark:text-rose-400' : data.health.status === 'warning' ? 'text-amber-600 dark:text-amber-400' : undefined,
                    size: 'compact',
                  },
                  {
                    label: t('admin.plugin_obs_events', {}, 'Events'),
                    value: formatInteger(data.totals.eventsTotal),
                    detail: `${formatInteger(data.totals.okTotal)} ok / ${formatInteger(data.totals.errorTotal)} error`,
                  },
                  {
                    label: t('admin.plugin_obs_success_rate', {}, 'Success rate'),
                    value: formatSuccessRate(data.totals.successRate),
                    toneClassName: successRateStatus(data.totals.successRate) === 'error' ? 'text-rose-600 dark:text-rose-400' : successRateStatus(data.totals.successRate) === 'warning' ? 'text-amber-600 dark:text-amber-400' : undefined,
                  },
                  {
                    label: t('admin.plugin_obs_avg_latency', {}, 'Avg latency'),
                    value: `${data.totals.avgLatencyMs}ms`,
                    size: 'compact',
                  },
                  {
                    label: t('admin.plugin_obs_active', {}, 'Active'),
                    value: `${formatInteger(data.totals.activeSiteCount)}s / ${formatInteger(data.totals.activePluginCount)}p`,
                    detail: 'sites / plugins',
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
          {PLUGIN_FILTER_OPTIONS.map((opt) => (
            <BackofficeFilterPill
              key={opt.value}
              active={pluginFilter === opt.value}
              tone="accent"
              onClick={() => setPluginFilter(opt.value)}
            >
              {opt.label}
            </BackofficeFilterPill>
          ))}
          <span className="mx-1 h-5 w-px bg-slate-200 dark:bg-slate-700" />
          <input
            type="text"
            value={siteIdInput}
            onChange={(e) => setSiteIdInput(e.target.value)}
            onKeyDown={handleSiteIdKeyDown}
            placeholder="site_id"
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:placeholder:text-slate-500"
          />
          <button
            type="button"
            onClick={handleSiteIdSubmit}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white"
          >
            Filter
          </button>
          <button
            type="button"
            onClick={loadData}
            disabled={loading}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white"
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

      {isEmpty ? (
        <BackofficeEmptyState
          title={t('admin.plugin_obs_empty_title', {}, '暂无插件监控事件')}
          description={t(
            'admin.plugin_obs_empty_desc',
            {},
            'No plugin observability events have been received in the selected time window. Events will appear here once plugins start reporting.'
          )}
        />
      ) : (
        <>
          {data?.digest.headline ? (
            <BackofficeSectionPanel className="space-y-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {t('admin.plugin_obs_digest_label', {}, 'Digest')}
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                    {data.digest.headline}
                  </h2>
                </div>
                <BackofficeTag tone="info">
                  {data.digest.periodLabel || `${data.digest.windowHours}h`}
                </BackofficeTag>
              </div>
              {data.digest.bullets.length ? (
                <div className="grid gap-2 md:grid-cols-2">
                  {data.digest.bullets.map((item) => (
                    <div
                      key={item}
                      className="rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-300"
                    >
                      {item}
                    </div>
                  ))}
                </div>
              ) : null}
            </BackofficeSectionPanel>
          ) : null}

          {data?.attention.length ? (
            <BackofficeSectionPanel className="space-y-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {t('admin.plugin_obs_attention_label', {}, 'Attention')}
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                    {t('admin.plugin_obs_attention_title', {}, 'Current watch items')}
                  </h2>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                    {formatInteger(data.attentionWorkflow.needsAttention)} open /{' '}
                    {formatInteger(data.attentionWorkflow.total)} total
                  </p>
                </div>
                <BackofficeStatusBadge
                  status={data.health.status}
                  label={`${data.health.status} · ${data.health.score}`}
                />
              </div>
              <div className="flex flex-wrap gap-2">
                {ATTENTION_WORKFLOW_OPTIONS.map((option) => (
                  <BackofficeFilterPill
                    key={option.value}
                    active={attentionWorkflowFilter === option.value}
                    tone="info"
                    onClick={() => setAttentionWorkflowFilter(option.value)}
                  >
                    {option.label}
                  </BackofficeFilterPill>
                ))}
                <span className="mx-1 h-5 w-px bg-slate-200 dark:bg-slate-700" />
                {ATTENTION_SEVERITY_OPTIONS.map((option) => (
                  <BackofficeFilterPill
                    key={option.value}
                    active={attentionSeverityFilter === option.value}
                    tone="accent"
                    onClick={() => setAttentionSeverityFilter(option.value)}
                  >
                    {option.label}
                  </BackofficeFilterPill>
                ))}
                <select
                  value={attentionCodeFilter}
                  onChange={(event) => setAttentionCodeFilter(event.target.value)}
                  className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
                >
                  {attentionCodeOptions.map((code) => (
                    <option key={code} value={code}>
                      {code === 'all' ? 'All codes' : code}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {filteredAttention.slice(0, 8).map((item) => (
                  <BackofficeStackCard key={item.attentionKey || `${item.code}-${item.siteId}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-semibold text-slate-950 dark:text-white">{item.title}</p>
                        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{item.detail}</p>
                        {item.suggestedAction ? (
                          <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                            {item.suggestedAction}
                          </p>
                        ) : null}
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {item.siteId ? <BackofficeTag>{item.siteId}</BackofficeTag> : null}
                          {item.pluginSlug ? <BackofficeTag tone="info">{item.pluginSlug}</BackofficeTag> : null}
                          {item.errorCode ? <BackofficeTag tone="danger">{item.errorCode}</BackofficeTag> : null}
                          <BackofficeTag tone={item.workflowStatus === 'active' ? 'warning' : 'info'}>
                            {item.workflowStatus}
                          </BackofficeTag>
                          {item.state?.mutedUntil ? (
                            <BackofficeTag tone="info">
                              muted until {formatDate(item.state.mutedUntil)}
                            </BackofficeTag>
                          ) : null}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(['acknowledge', 'mute', 'resolve'] as AttentionStateAction[]).map((action) => (
                            <button
                              key={action}
                              type="button"
                              className="h-7 rounded-full border border-slate-200/80 bg-white px-2.5 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600"
                              disabled={attentionActionKey === `${item.attentionKey}-${action}`}
                              onClick={() => void handleAttentionStateAction(item, action)}
                            >
                              {action === 'acknowledge' ? 'Ack' : action === 'mute' ? 'Mute 24h' : 'Resolve'}
                            </button>
                          ))}
                          {item.workflowStatus !== 'active' ? (
                            <button
                              type="button"
                              className="h-7 rounded-full border border-slate-200/80 bg-white px-2.5 text-xs font-medium text-slate-500 transition hover:border-slate-300 hover:text-slate-900 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600"
                              disabled={attentionActionKey === `${item.attentionKey}-clear`}
                              onClick={() => void handleAttentionStateAction(item, 'clear')}
                            >
                              Clear state
                            </button>
                          ) : null}
                        </div>
                      </div>
                      <BackofficeTag tone={attentionTone(item.severity)}>{item.severity}</BackofficeTag>
                    </div>
                  </BackofficeStackCard>
                ))}
              </div>
              {!filteredAttention.length ? (
                <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
                  {t('admin.plugin_obs_attention_filtered_empty', {}, 'No watch items match the selected filters.')}
                </BackofficeStackCard>
              ) : null}
            </BackofficeSectionPanel>
          ) : null}

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.plugin_obs_trend_label', {}, 'Trend')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.plugin_obs_trend_title', {}, 'Events and errors')}
                </h2>
              </div>
              <AnalyticsLineChart
                data={timelineData}
                height={280}
                primarySeriesName={t('admin.plugin_obs_events', {}, 'Events')}
                secondarySeriesName={t('admin.plugin_obs_error_codes', {}, 'Errors')}
                primaryColor="#2563eb"
                secondaryColor="#f59e0b"
              />
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.plugin_obs_plugin_compare_label', {}, 'Plugin comparison')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {hasPluginErrors
                    ? t('admin.plugin_obs_plugin_error_title', {}, 'Error pressure')
                    : t('admin.plugin_obs_plugin_volume_title', {}, 'Event volume')}
                </h2>
              </div>
              <AnalyticsBarChart
                data={hasPluginErrors ? pluginErrorData : pluginVolumeData}
                height={280}
                barColor={hasPluginErrors ? '#f59e0b' : '#2563eb'}
              />
            </BackofficeSectionPanel>
          </div>

          <div className="space-y-5">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.plugin_obs_plugins', {}, 'Plugins')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.plugin_obs_plugin_breakdown', {}, 'Plugin breakdown')}
                </h2>
              </div>
              <div className="space-y-3">
                {data?.plugins.map((plugin) => (
                  <BackofficeStackCard key={plugin.pluginSlug}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-semibold text-slate-950 dark:text-white">{plugin.pluginSlug}</p>
                        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                          {formatInteger(plugin.eventsTotal)} events &middot; {formatSuccessRate(plugin.successRate)} &middot; {plugin.avgLatencyMs}ms avg
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {plugin.eventKinds.map((ek) => (
                            <BackofficeTag key={ek.eventKind} tone={ek.errorTotal > 0 ? 'warning' : 'info'}>
                              {ek.eventKind}
                            </BackofficeTag>
                          ))}
                        </div>
                      </div>
                      <BackofficeStatusBadge
                        status={successRateStatus(plugin.successRate)}
                        label={formatSuccessRate(plugin.successRate)}
                      />
                    </div>
                  </BackofficeStackCard>
                ))}
              </div>
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {t('admin.plugin_obs_sites', {}, 'Sites')}
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                    {t('admin.plugin_obs_site_health', {}, 'Site health')}
                  </h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  {[
                    ['errors', t('admin.plugin_obs_sort_errors', {}, 'Errors')],
                    ['success', t('admin.plugin_obs_sort_success', {}, 'Success')],
                    ['events', t('admin.plugin_obs_sort_events', {}, 'Events')],
                    ['latency', t('admin.plugin_obs_sort_latency', {}, 'Latency')],
                    ['lastSeen', t('admin.plugin_obs_sort_last_seen', {}, 'Last seen')],
                  ].map(([value, label]) => (
                    <BackofficeFilterPill
                      key={value}
                      active={siteSort === value}
                      tone="info"
                      onClick={() => setSiteSort(value as SiteSortKey)}
                    >
                      {label}
                    </BackofficeFilterPill>
                  ))}
                </div>
              </div>
              <BackofficeStackCard className="overflow-x-auto p-0">
                <table className="min-w-full divide-y divide-slate-200/80 text-sm dark:divide-slate-800">
                  <thead className="bg-slate-50/80 text-xs uppercase text-slate-500 dark:bg-slate-900/40 dark:text-slate-400">
                    <tr>
                      <th className="px-4 py-3 text-left font-semibold">{t('common.site', {}, 'Site')}</th>
                      <th className="px-4 py-3 text-left font-semibold">{t('admin.plugin_obs_health', {}, 'Health')}</th>
                      <th className="px-4 py-3 text-right font-semibold">{t('admin.plugin_obs_events', {}, 'Events')}</th>
                      <th className="px-4 py-3 text-right font-semibold">{t('admin.plugin_obs_error_codes', {}, 'Errors')}</th>
                      <th className="px-4 py-3 text-right font-semibold">{t('admin.plugin_obs_success_rate', {}, 'Success rate')}</th>
                      <th className="px-4 py-3 text-right font-semibold">{t('admin.plugin_obs_avg_latency', {}, 'Avg latency')}</th>
                      <th className="px-4 py-3 text-left font-semibold">{t('admin.plugin_obs_top_error', {}, 'Top error')}</th>
                      <th className="px-4 py-3 text-right font-semibold">{t('admin.plugin_obs_last_seen', {}, 'Last seen')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200/80 dark:divide-slate-800">
                    {sortedSites.map((site) => {
                      const topError = errorBySite.get(site.siteId);
                      return (
                        <tr key={site.siteId} className="align-top">
                          <td className="px-4 py-3">
                            <BackofficeIdentifier value={site.siteId} className="font-medium text-slate-950 dark:text-white" />
                            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {formatInteger(site.pluginCount)} plugins
                            </p>
                          </td>
                          <td className="px-4 py-3">
                            <BackofficeStatusBadge
                              status={site.health.status}
                              label={`${site.health.status} · ${site.health.score}`}
                            />
                          </td>
                          <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-200">
                            {formatInteger(site.eventsTotal)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <BackofficeTag tone={site.errorTotal > 0 ? 'warning' : 'success'}>
                              {formatInteger(site.errorTotal)}
                            </BackofficeTag>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <BackofficeStatusBadge
                              status={successRateStatus(site.successRate)}
                              label={formatSuccessRate(site.successRate)}
                              className="justify-end"
                            />
                          </td>
                          <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-200">
                            {site.avgLatencyMs}ms
                          </td>
                          <td className="px-4 py-3">
                            {topError ? (
                              <div className="min-w-0">
                                <p className="font-mono text-xs font-semibold text-rose-700 dark:text-rose-300">
                                  {topError.errorCode}
                                </p>
                                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                  {topError.pluginSlug} &middot; {formatInteger(topError.count)}
                                </p>
                              </div>
                            ) : (
                              <span className="text-xs text-slate-500 dark:text-slate-400">
                                {t('admin.plugin_obs_no_errors_short', {}, 'None')}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-right text-xs text-slate-500 dark:text-slate-400">
                            {site.lastSeenAt ? formatDate(site.lastSeenAt) : t('common.not_found')}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </BackofficeStackCard>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t(
                  'admin.plugin_obs_site_health_desc',
                  {},
                  'Sorted by operational pressure. Payloads and raw requests stay excluded.'
                )}
              </div>
            </BackofficeSectionPanel>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.plugin_obs_error_codes', {}, 'Error codes')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.plugin_obs_error_ranking', {}, 'Error code ranking')}
                </h2>
              </div>
              <div className="space-y-3">
                {data?.errors.length ? (
                  data.errors.map((err, idx) => (
                    <BackofficeStackCard key={`err-${err.errorCode}-${err.pluginSlug}-${idx}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="font-mono text-sm font-semibold text-rose-700 dark:text-rose-300">{err.errorCode}</p>
                          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                            {err.pluginSlug} &middot; {err.eventKind} &middot; {formatInteger(err.count)} occurrences
                          </p>
                          {err.siteId ? (
                            <BackofficeIdentifier value={err.siteId} className="mt-1 text-xs text-slate-500 dark:text-slate-400" />
                          ) : null}
                        </div>
                        <BackofficeTag tone="danger">{formatInteger(err.count)}</BackofficeTag>
                      </div>
                    </BackofficeStackCard>
                  ))
                ) : (
                  <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
                    {t('admin.plugin_obs_no_errors', {}, 'No errors in the selected time window.')}
                  </BackofficeStackCard>
                )}
              </div>
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.plugin_obs_recent_errors', {}, 'Recent errors')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.plugin_obs_recent_errors_title', {}, 'Latest error events')}
                </h2>
              </div>
              <div className="space-y-3">
                {data?.recentErrors.length ? (
                  data.recentErrors.map((re, idx) => (
                    <BackofficeStackCard key={`recent-${idx}`}>
                      <div className="min-w-0 space-y-1">
                        <div className="flex items-start justify-between gap-3">
                          <p className="font-mono text-sm font-semibold text-rose-700 dark:text-rose-300">{re.errorCode}</p>
                          <BackofficeStatusBadge status="error" label={re.status} />
                        </div>
                        <p className="text-sm text-slate-600 dark:text-slate-300">
                          {re.pluginSlug} &middot; {re.eventKind}
                        </p>
                        {re.siteId ? (
                          <BackofficeIdentifier value={re.siteId} className="text-xs text-slate-500 dark:text-slate-400" />
                        ) : null}
                        {re.abilityId ? (
                          <p className="text-xs text-slate-500 dark:text-slate-400">ability: <BackofficeIdentifier value={re.abilityId} /></p>
                        ) : null}
                        {re.proposalId ? (
                          <p className="text-xs text-slate-500 dark:text-slate-400">proposal: <BackofficeIdentifier value={re.proposalId} /></p>
                        ) : null}
                        {re.route ? (
                          <p className="font-mono text-xs text-slate-500 dark:text-slate-400">{re.route}</p>
                        ) : null}
                        <p className="text-xs text-slate-400 dark:text-slate-500">{formatDate(re.receivedAt)}</p>
                      </div>
                    </BackofficeStackCard>
                  ))
                ) : (
                  <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
                    {t('admin.plugin_obs_no_recent_errors', {}, 'No recent error events.')}
                  </BackofficeStackCard>
                )}
              </div>
            </BackofficeSectionPanel>
          </div>
        </>
      )}
    </BackofficePageStack>
  );
}

export default function AdminPluginObservabilityPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminPluginObservabilityContent />
    </Suspense>
  );
}
