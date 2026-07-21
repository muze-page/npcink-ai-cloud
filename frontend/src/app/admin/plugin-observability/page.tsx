'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useToast } from '@/components/ui/Toast';
import { useLocale } from '@/contexts/LocaleContext';
import {
  BackofficeEmptyState,
  BackofficeLayer,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { AnalyticsBarChart, AnalyticsLineChart } from '@/components/ui/EChartsWrapper';
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber as formatInteger } from '@/lib/utils';

const pluginObservabilityClient = createApiClient({ idempotencyPrefix: 'plugin_observability' });

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
type PluginFilter =
  | 'all'
  | 'npcink-abilities-toolkit'
  | 'npcink-governance-core'
  | 'npcink-ai-client-adapter'
  | 'npcink-cloud-addon';
type AttentionWorkflowFilter = 'active' | 'acknowledged' | 'muted' | 'resolved' | 'all';
type AttentionSeverityFilter = 'all' | 'warning' | 'error';
type AttentionStateAction = 'acknowledge' | 'mute' | 'resolve' | 'clear';
type TranslationFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

const WINDOW_OPTIONS: { value: WindowOption; label: string }[] = [
  { value: 24, label: '24h' },
  { value: 72, label: '72h' },
  { value: 168, label: '168h' },
];

const PLUGIN_FILTER_OPTIONS: { value: PluginFilter; labelKey: string; fallback: string }[] = [
  { value: 'all', labelKey: 'admin.plugin_obs_filter_all', fallback: 'All plugins' },
  { value: 'npcink-abilities-toolkit', labelKey: 'admin.plugin_obs_filter_abilities', fallback: 'Abilities' },
  { value: 'npcink-governance-core', labelKey: 'admin.plugin_obs_filter_core', fallback: 'Core' },
  { value: 'npcink-ai-client-adapter', labelKey: 'admin.plugin_obs_filter_adapter', fallback: 'Adapter' },
  { value: 'npcink-cloud-addon', labelKey: 'admin.plugin_obs_filter_addon', fallback: 'Cloud Addon' },
];

const ATTENTION_WORKFLOW_OPTIONS: { value: AttentionWorkflowFilter; labelKey: string; fallback: string }[] = [
  { value: 'active', labelKey: 'admin.plugin_obs_workflow_active', fallback: 'Open' },
  { value: 'acknowledged', labelKey: 'admin.plugin_obs_workflow_acknowledged', fallback: 'Acknowledged' },
  { value: 'muted', labelKey: 'admin.plugin_obs_workflow_muted', fallback: 'Muted' },
  { value: 'resolved', labelKey: 'admin.plugin_obs_workflow_resolved', fallback: 'Resolved' },
  { value: 'all', labelKey: 'admin.plugin_obs_workflow_all', fallback: 'All states' },
];

const ATTENTION_SEVERITY_OPTIONS: { value: AttentionSeverityFilter; labelKey: string; fallback: string }[] = [
  { value: 'all', labelKey: 'admin.plugin_obs_severity_all', fallback: 'All severity' },
  { value: 'error', labelKey: 'admin.plugin_obs_severity_error', fallback: 'Error' },
  { value: 'warning', labelKey: 'admin.plugin_obs_severity_warning', fallback: 'Warning' },
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

function statusLabel(t: TranslationFn, status: string): string {
  return t(`status.${status || 'unknown'}`, {}, status || 'unknown');
}

function pluginHealthSummary(t: TranslationFn, data: PluginObservabilityData): string {
  if (data.totals.eventsTotal <= 0 || data.health.status === 'inactive') {
    return t(
      'admin.plugin_obs_health_summary_inactive',
      {},
      'No plugin events in this window.'
    );
  }
  return t(
    'admin.plugin_obs_health_summary_active',
    {
      events: formatInteger(data.totals.eventsTotal),
      errors: formatInteger(data.totals.errorTotal),
      latency: formatInteger(data.totals.avgLatencyMs),
    },
    '{{events}} events · {{errors}} errors · avg {{latency}}ms'
  );
}

function pluginDigestCopy(t: TranslationFn, data: PluginObservabilityData) {
  if (data.totals.eventsTotal <= 0) return null;
  const topPlugin = data.digest.topPluginSlug || data.plugins[0]?.pluginSlug || t('common.not_available');
  const topError = data.digest.topErrorCode || data.errors[0]?.errorCode || t('admin.plugin_obs_no_errors_short', {}, 'None');
  const hours = String(data.digest.windowHours || data.window.hours || 24);
  const periodKey = data.digest.periodLabel
    ? `admin.plugin_obs_period_${data.digest.periodLabel}`
    : 'admin.plugin_obs_period_hours';
  return {
    period: t(periodKey, { hours }, data.digest.periodLabel || `${hours}h`),
    headline: t(
      'admin.plugin_obs_digest_headline',
      {
        events: formatInteger(data.totals.eventsTotal),
        errors: formatInteger(data.totals.errorTotal),
        sites: formatInteger(data.totals.activeSiteCount),
        plugins: formatInteger(data.totals.activePluginCount),
      },
      '{{events}} plugin events across {{sites}} sites and {{plugins}} plugins.'
    ),
    bullets: [
      t('admin.plugin_obs_digest_bullet_success', { rate: formatSuccessRate(data.totals.successRate) }, 'Success rate: {{rate}}'),
      t('admin.plugin_obs_digest_bullet_latency', { latency: formatInteger(data.totals.avgLatencyMs) }, 'Average latency: {{latency}}ms'),
      t('admin.plugin_obs_digest_bullet_top_plugin', { plugin: topPlugin }, 'Top reporting plugin: {{plugin}}'),
      t('admin.plugin_obs_digest_bullet_top_error', { error: topError }, 'Top error: {{error}}'),
    ],
  };
}

function attentionCodeSuffix(code: string): string {
  return (
    code
      .trim()
      .toLowerCase()
      .replace(/^plugin_observability[._-]*/, '')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'default'
  );
}

function missingPluginsFromDetail(detail: string): string {
  return detail.replace(/^Missing plugin telemetry:\s*/i, '').trim();
}

function attentionParams(t: TranslationFn, item: AttentionItem): Record<string, string> {
  const fallback = t('common.not_available');
  return {
    site: item.siteId || fallback,
    plugin: item.pluginSlug || fallback,
    plugins: missingPluginsFromDetail(item.detail) || item.pluginSlug || fallback,
    eventKind: item.eventKind || fallback,
    errorCode: item.errorCode || fallback,
  };
}

function attentionCopy(
  t: TranslationFn,
  item: AttentionItem,
  field: 'title' | 'detail' | 'action'
): string {
  const params = attentionParams(t, item);
  const suffix = attentionCodeSuffix(item.code);
  const defaultFallback =
    field === 'title'
      ? 'Watch item'
      : field === 'detail'
        ? 'Review this plugin observability signal against the related metadata.'
        : 'Review the linked metadata and local plugin logs.';
  const defaultCopy = t(`admin.plugin_obs_attention_${field}_default`, params, defaultFallback);
  return t(`admin.plugin_obs_attention_${field}_${suffix}`, params, defaultCopy);
}

function attentionActionLabel(t: TranslationFn, action: AttentionStateAction): string {
  return t(
    `admin.plugin_obs_action_${action}`,
    {},
    action === 'acknowledge'
      ? 'Acknowledge'
      : action === 'mute'
        ? 'Mute 24h'
        : action === 'resolve'
          ? 'Resolve'
          : 'Clear state'
  );
}

function normalizeWindowOption(value: string | null): WindowOption {
  const parsed = Number(value);
  return parsed === 72 || parsed === 168 ? parsed : 24;
}

function normalizePluginFilter(value: string | null): PluginFilter {
  return PLUGIN_FILTER_OPTIONS.some((option) => option.value === value) ? value as PluginFilter : 'all';
}

function AdminPluginObservabilityContent() {
  const { t } = useLocale();
  const toast = useToast();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const windowHours = normalizeWindowOption(searchParams.get('window'));
  const pluginFilter = normalizePluginFilter(searchParams.get('plugin'));
  const siteIdFilter = searchParams.get('site') || '';
  const focusedAttentionKey = searchParams.get('focus') || '';
  const [data, setData] = useState<PluginObservabilityData | null>(null);
  const [error, setError] = useState('');
  const [siteIdInput, setSiteIdInput] = useState(siteIdFilter);
  const [loading, setLoading] = useState(true);
  const [siteSort, setSiteSort] = useState<SiteSortKey>('errors');
  const [attentionWorkflowFilter, setAttentionWorkflowFilter] =
    useState<AttentionWorkflowFilter>('active');
  const [attentionSeverityFilter, setAttentionSeverityFilter] =
    useState<AttentionSeverityFilter>('all');
  const [attentionCodeFilter, setAttentionCodeFilter] = useState('all');
  const [attentionActionKey, setAttentionActionKey] = useState('');
  const requestActiveRef = useRef(false);
  const requestSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);

  const updateUrl = useCallback((updates: {
    window?: WindowOption | null;
    plugin?: PluginFilter | null;
    site?: string | null;
    focus?: string | null;
  }) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value && !(key === 'window' && value === 24) && !(key === 'plugin' && value === 'all')) params.set(key, String(value));
      else params.delete(key);
    });
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  const loadData = useCallback(async (refresh = false) => {
    if (requestActiveRef.current) return;
    requestActiveRef.current = true;
    const sequence = ++requestSequenceRef.current;
    if (!hasLoadedRef.current || !refresh) setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ window_hours: String(windowHours) });
      if (pluginFilter !== 'all') params.set('plugin_slug', pluginFilter);
      if (siteIdFilter) params.set('site_id', siteIdFilter);
      const response = await pluginObservabilityClient.request<unknown>(
        `/api/admin/plugin-observability?${params.toString()}`
      );
      if (sequence !== requestSequenceRef.current) return;
      setData(normalizePluginObservability(response.data));
      hasLoadedRef.current = true;
    } catch (err) {
      if (sequence !== requestSequenceRef.current) return;
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
    } finally {
      if (sequence === requestSequenceRef.current) {
        requestActiveRef.current = false;
        setLoading(false);
      }
    }
  }, [windowHours, pluginFilter, siteIdFilter, t]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    setSiteIdInput(siteIdFilter);
  }, [siteIdFilter]);

  const handleSiteIdSubmit = () => {
    updateUrl({ site: siteIdInput.trim() || null, focus: null });
  };

  const handleSiteIdKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSiteIdSubmit();
  };

  const handleAttentionStateAction = useCallback(
    async (item: AttentionItem, action: AttentionStateAction) => {
      if (!item.attentionKey) return;
      setAttentionActionKey(`${item.attentionKey}-${action}`);
      try {
        await pluginObservabilityClient.request<unknown>('/api/admin/plugin-observability/attention-state', {
          method: 'POST',
          body: {
            attention_key: item.attentionKey,
            attention_code: item.code,
            action,
            site_id: item.siteId,
            plugin_slug: item.pluginSlug,
            event_kind: item.eventKind,
            error_code: item.errorCode,
            mute_hours: 24,
          },
        });
        await loadData();
        toast.success(
          t('admin.plugin_obs_attention_state_updated', {}, 'Watch item state updated.'),
          t('common.success')
        );
      } catch (err) {
        const message = resolveUiErrorMessage(err, t('error.failed_load'));
        setError(message);
        toast.error(message, t('common.error'));
      } finally {
        setAttentionActionKey('');
      }
    },
    [loadData, t, toast]
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
  const selectedAttention = filteredAttention.find((item) => item.attentionKey === focusedAttentionKey)
    || filteredAttention[0]
    || null;

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

  const digestCopy = useMemo(() => (data ? pluginDigestCopy(t, data) : null), [data, t]);

  if (loading && !data) {
    return <LoadingFallback />;
  }

  const isEmpty = data !== null && data.totals.eventsTotal === 0 && data.attention.length === 0;
  const effectiveHealthStatus = data && data.attentionWorkflow.needsAttention > 0
    ? data.attention.some((item) => item.severity === 'error') ? 'error' : 'warning'
    : data?.health.status || 'inactive';
  const effectiveHealthLabel = data && data.attentionWorkflow.needsAttention > 0
    ? t('admin.plugin_obs_health_needs_attention', {}, 'Needs attention')
    : data ? `${statusLabel(t, data.health.status)} · ${data.health.score}` : '';

  return (
    <BackofficePageStack>
      <BackofficeLayer
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.plugin_observability_title', {}, 'Plugin Observability')}
        description={t(
          'admin.plugin_observability_desc',
          {},
          'Cross-site plugin event volume, error rates, latency, and recent errors for npcink-abilities-toolkit, npcink-governance-core, npcink-ai-client-adapter, and npcink-cloud-addon.'
        )}
        aside={data ? <BackofficeStatusBadge status={effectiveHealthStatus} label={effectiveHealthLabel} /> : undefined}
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
          {PLUGIN_FILTER_OPTIONS.map((opt) => (
            <BackofficeFilterPill
              key={opt.value}
              active={pluginFilter === opt.value}
              tone="accent"
              onClick={() => updateUrl({ plugin: opt.value, focus: null })}
            >
              {t(opt.labelKey, {}, opt.fallback)}
            </BackofficeFilterPill>
          ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input type="text" value={siteIdInput} aria-label={t('admin.plugin_obs_site_filter_label', {}, 'Filter by site ID')} onChange={(e) => setSiteIdInput(e.target.value)} onKeyDown={handleSiteIdKeyDown} placeholder={t('admin.plugin_obs_site_filter', {}, 'Site ID')} className="input h-9 min-w-0 flex-1 sm:max-w-xs" />
            <button type="button" onClick={handleSiteIdSubmit} className="btn btn-secondary btn-sm justify-center">{t('common.apply', {}, 'Apply')}</button>
            {siteIdFilter ? <button type="button" className="btn btn-ghost btn-sm justify-center" onClick={() => { setSiteIdInput(''); updateUrl({ site: null, focus: null }); }}>{t('common.clear_filters', {}, 'Clear filters')}</button> : null}
            {data?.generatedAt ? <p className="text-xs text-slate-500 sm:ml-auto dark:text-slate-400">{t('common.updated_at', {}, 'Updated')}: {formatDate(data.generatedAt)}</p> : null}
          </div>
        </div>
      </BackofficeSectionPanel>

      {data ? <BackofficeSummaryStrip items={[
        { label: t('admin.plugin_obs_events', {}, 'Events'), value: formatInteger(data.totals.eventsTotal) },
        { label: t('admin.plugin_obs_success_rate', {}, 'Success rate'), value: formatSuccessRate(data.totals.successRate), toneClassName: successRateStatus(data.totals.successRate) === 'error' ? 'text-rose-600 dark:text-rose-400' : successRateStatus(data.totals.successRate) === 'warning' ? 'text-amber-600 dark:text-amber-400' : undefined },
        { label: t('admin.plugin_obs_avg_latency', {}, 'Avg latency'), value: `${data.totals.avgLatencyMs}ms` },
        { label: t('admin.plugin_obs_active_sites', {}, 'Active sites'), value: formatInteger(data.totals.activeSiteCount) },
        { label: t('admin.plugin_obs_attention_open', {}, 'Open watch items'), value: formatInteger(data.attentionWorkflow.needsAttention), toneClassName: data.attentionWorkflow.needsAttention > 0 ? 'text-amber-700 dark:text-amber-300' : undefined },
      ]} /> : null}

      {error ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200"><div className="font-semibold">{error}</div>{data ? <div className="mt-1 text-xs">{t('admin.plugin_obs_stale_notice', {}, 'The last successfully loaded plugin snapshot remains visible.')}</div> : null}</div> : null}

      {isEmpty ? (
        <BackofficeEmptyState
          title={t('admin.plugin_obs_empty_title', {}, 'No plugin observability events')}
          description={t(
            'admin.plugin_obs_empty_desc',
            {},
            'No plugin observability events have been received in the selected time window. Events will appear here once plugins start reporting.'
          )}
        />
      ) : (
        <>
          {digestCopy ? (
            <BackofficeSectionPanel className="space-y-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {t('admin.plugin_obs_digest_label', {}, 'Digest')}
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                    {digestCopy.headline}
                  </h2>
                </div>
                <BackofficeTag tone="info">
                  {digestCopy.period}
                </BackofficeTag>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {digestCopy.bullets.map((item) => (
                  <div
                    key={item}
                    className="rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-300"
                  >
                    {item}
                  </div>
                ))}
              </div>
            </BackofficeSectionPanel>
          ) : null}

          {data?.attention.length ? (
            <BackofficeSectionPanel className="overflow-hidden p-0 md:p-0">
              <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800 md:px-6">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('admin.plugin_obs_attention_label', {}, 'Attention')}</p><h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">{t('admin.plugin_obs_attention_title', {}, 'Current watch items')}</h2><p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('admin.plugin_obs_attention_count_detail', { open: formatInteger(data.attentionWorkflow.needsAttention), total: formatInteger(data.attentionWorkflow.total) }, '{{open}} open / {{total}} total')}</p></div>
                  <BackofficeStatusBadge status={effectiveHealthStatus} label={effectiveHealthLabel} />
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {ATTENTION_WORKFLOW_OPTIONS.map((option) => <BackofficeFilterPill key={option.value} active={attentionWorkflowFilter === option.value} tone="info" onClick={() => { setAttentionWorkflowFilter(option.value); updateUrl({ focus: null }); }}>{t(option.labelKey, {}, option.fallback)}</BackofficeFilterPill>)}
                  {ATTENTION_SEVERITY_OPTIONS.map((option) => <BackofficeFilterPill key={option.value} active={attentionSeverityFilter === option.value} tone="accent" onClick={() => { setAttentionSeverityFilter(option.value); updateUrl({ focus: null }); }}>{t(option.labelKey, {}, option.fallback)}</BackofficeFilterPill>)}
                  <select value={attentionCodeFilter} aria-label={t('admin.plugin_obs_attention_code_filter', {}, 'Watch item code')} onChange={(event) => { setAttentionCodeFilter(event.target.value); updateUrl({ focus: null }); }} className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">{attentionCodeOptions.map((code) => <option key={code} value={code}>{code === 'all' ? t('admin.plugin_obs_attention_all_codes', {}, 'All codes') : code}</option>)}</select>
                </div>
              </div>
              <div className="grid xl:grid-cols-[minmax(0,1fr)_22rem]">
                <div className="max-h-[38rem] divide-y divide-slate-200 overflow-y-auto dark:divide-slate-800">
                  {filteredAttention.slice(0, 12).map((item) => {
                    const selected = selectedAttention?.attentionKey === item.attentionKey;
                    return <button key={item.attentionKey || `${item.code}-${item.siteId}`} type="button" data-ui="plugin-attention-item" aria-pressed={selected} aria-controls="plugin-attention-inspector" className={`grid w-full cursor-pointer gap-3 px-5 py-4 text-left transition hover:bg-slate-50 dark:hover:bg-slate-900/45 md:grid-cols-[minmax(0,1fr)_8rem] md:items-center md:px-6 ${selected ? 'bg-blue-50/65 dark:bg-blue-950/20' : ''}`} onClick={() => updateUrl({ focus: item.attentionKey })}>
                      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-slate-950 dark:text-white">{attentionCopy(t, item, 'title')}</span><BackofficeTag tone={attentionTone(item.severity)}>{t(`admin.plugin_obs_severity_${item.severity}`, {}, item.severity)}</BackofficeTag></div><p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{attentionCopy(t, item, 'detail')}</p><p className="mt-2 truncate text-xs text-slate-500 dark:text-slate-400">{[item.siteId, item.pluginSlug, item.errorCode].filter(Boolean).join(' · ')}</p></div>
                      <div className="text-sm font-medium text-slate-500 md:text-right dark:text-slate-400">{t(`admin.plugin_obs_workflow_${item.workflowStatus}`, {}, item.workflowStatus)}</div>
                    </button>;
                  })}
                  {!filteredAttention.length ? <BackofficeEmptyState className="m-5 md:m-6" title={t('admin.plugin_obs_attention_filtered_empty', {}, 'No watch items match the selected filters.')} description={t('admin.plugin_obs_attention_filtered_empty_desc', {}, 'Clear a workflow, severity, or code filter to return to the active watch queue.')} /> : null}
                </div>
                <div id="plugin-attention-inspector" className="border-t border-slate-200 p-5 dark:border-slate-800 xl:border-l xl:border-t-0 xl:p-6">
                  {selectedAttention ? <div className="space-y-5"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('admin.plugin_obs_selected_watch_item', {}, 'Selected watch item')}</p><div className="mt-2 flex items-start justify-between gap-3"><h3 className="text-lg font-semibold text-slate-950 dark:text-white">{attentionCopy(t, selectedAttention, 'title')}</h3><BackofficeTag tone={attentionTone(selectedAttention.severity)}>{t(`admin.plugin_obs_severity_${selectedAttention.severity}`, {}, selectedAttention.severity)}</BackofficeTag></div><p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{attentionCopy(t, selectedAttention, 'detail')}</p></div>
                    <dl className="grid gap-3 text-sm"><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.plugin_obs_suggested_step', {}, 'Suggested review step')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{attentionCopy(t, selectedAttention, 'action')}</dd></div>{selectedAttention.siteId ? <div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('common.site', {}, 'Site')}</dt><dd className="mt-1"><BackofficeIdentifier value={selectedAttention.siteId} /></dd></div> : null}{selectedAttention.pluginSlug ? <div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.plugin_obs_plugins', {}, 'Plugin')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{selectedAttention.pluginSlug}</dd></div> : null}{selectedAttention.errorCode ? <div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.plugin_obs_error_codes', {}, 'Error code')}</dt><dd className="mt-1 break-all font-mono text-xs text-rose-700 dark:text-rose-300">{selectedAttention.errorCode}</dd></div> : null}</dl>
                    <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-1">{(['acknowledge', 'mute', 'resolve'] as AttentionStateAction[]).map((action) => <button key={action} type="button" className={action === 'resolve' ? 'btn btn-primary justify-center' : 'btn btn-secondary justify-center'} disabled={Boolean(attentionActionKey)} onClick={() => void handleAttentionStateAction(selectedAttention, action)}>{attentionActionLabel(t, action)}</button>)}</div>
                    {selectedAttention.workflowStatus !== 'active' ? <button type="button" className="btn btn-ghost w-full justify-center" disabled={Boolean(attentionActionKey)} onClick={() => void handleAttentionStateAction(selectedAttention, 'clear')}>{attentionActionLabel(t, 'clear')}</button> : null}
                    <p className="rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-500 dark:bg-slate-900/45 dark:text-slate-400">{t('admin.plugin_obs_attention_scope_notice', {}, 'Attention state is Cloud display state only. It does not mutate local plugin settings, approvals, ability definitions, routing, or WordPress content.')}</p>
                  </div> : <BackofficeEmptyState title={t('admin.plugin_obs_attention_filtered_empty', {}, 'No watch items match the selected filters.')} description={t('admin.plugin_obs_attention_filtered_empty_desc', {}, 'Clear a workflow, severity, or code filter to return to the active watch queue.')} />}
                </div>
              </div>
            </BackofficeSectionPanel>
          ) : null}

          {(data?.totals.eventsTotal || 0) > 0 ? <>
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
                          {t(
                            'admin.plugin_obs_plugin_detail',
                            {
                              events: formatInteger(plugin.eventsTotal),
                              rate: formatSuccessRate(plugin.successRate),
                              latency: formatInteger(plugin.avgLatencyMs),
                            },
                            '{{events}} events · {{rate}} · avg {{latency}}ms'
                          )}
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
                              {t(
                                'admin.plugin_obs_plugins_detail',
                                { count: formatInteger(site.pluginCount) },
                                '{{count}} plugins'
                              )}
                            </p>
                          </td>
                          <td className="px-4 py-3">
                            <BackofficeStatusBadge
                              status={site.health.status}
                              label={`${statusLabel(t, site.health.status)} · ${site.health.score}`}
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
                            {err.pluginSlug} &middot; {err.eventKind} &middot;{' '}
                            {t(
                              'admin.plugin_obs_error_occurrences',
                              { count: formatInteger(err.count) },
                              '{{count}} occurrences'
                            )}
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
                          <BackofficeStatusBadge status="error" label={statusLabel(t, re.status)} />
                        </div>
                        <p className="text-sm text-slate-600 dark:text-slate-300">
                          {re.pluginSlug} &middot; {re.eventKind}
                        </p>
                        {re.siteId ? (
                          <BackofficeIdentifier value={re.siteId} className="text-xs text-slate-500 dark:text-slate-400" />
                        ) : null}
                        {re.abilityId ? (
                          <p className="text-xs text-slate-500 dark:text-slate-400">
                            {t('admin.plugin_obs_recent_ability', {}, 'Ability')}:{' '}
                            <BackofficeIdentifier value={re.abilityId} />
                          </p>
                        ) : null}
                        {re.proposalId ? (
                          <p className="text-xs text-slate-500 dark:text-slate-400">
                            {t('admin.plugin_obs_recent_proposal', {}, 'Proposal')}:{' '}
                            <BackofficeIdentifier value={re.proposalId} />
                          </p>
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
          </> : null}
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
