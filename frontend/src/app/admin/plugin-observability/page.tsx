'use client';

import React, { Suspense, useCallback, useEffect, useState } from 'react';
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

type PluginObservabilityData = {
  generatedAt: string;
  totals: PluginObservabilityTotals;
  plugins: PluginItem[];
  sites: SiteItem[];
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
type PluginFilter = 'all' | 'magick-ai-abilities' | 'magick-ai-core' | 'magick-ai-adapter';

const WINDOW_OPTIONS: { value: WindowOption; label: string }[] = [
  { value: 24, label: '24h' },
  { value: 72, label: '72h' },
  { value: 168, label: '168h' },
];

const PLUGIN_FILTER_OPTIONS: { value: PluginFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'magick-ai-abilities', label: 'Abilities' },
  { value: 'magick-ai-core', label: 'Core' },
  { value: 'magick-ai-adapter', label: 'Adapter' },
];

function formatSuccessRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function successRateStatus(rate: number): string {
  if (rate >= 0.99) return 'success';
  if (rate >= 0.95) return 'warning';
  return 'error';
}

function AdminPluginObservabilityContent() {
  const { t } = useLocale();
  const [data, setData] = useState<PluginObservabilityData | null>(null);
  const [error, setError] = useState('');
  const [windowHours, setWindowHours] = useState<WindowOption>(24);
  const [pluginFilter, setPluginFilter] = useState<PluginFilter>('all');
  const [siteIdFilter, setSiteIdFilter] = useState('');
  const [siteIdInput, setSiteIdInput] = useState('');
  const [loading, setLoading] = useState(true);

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
          'Cross-site plugin event volume, error rates, latency, and recent errors for magick-ai-abilities, magick-ai-core, and magick-ai-adapter.'
        )}
        aside={
          data ? (
            <div className="w-full xl:w-[40rem]">
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-2 xl:grid-cols-4"
                items={[
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
          <div className="grid gap-5 xl:grid-cols-2">
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
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.plugin_obs_sites', {}, 'Sites')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.plugin_obs_site_breakdown', {}, 'Site breakdown')}
                </h2>
              </div>
              <div className="space-y-3">
                {data?.sites.map((site) => (
                  <BackofficeStackCard key={site.siteId}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <BackofficeIdentifier value={site.siteId} className="text-sm font-semibold text-slate-950 dark:text-white" />
                        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                          {formatInteger(site.eventsTotal)} events &middot; {formatInteger(site.pluginCount)} plugins &middot; {site.avgLatencyMs}ms avg
                        </p>
                      </div>
                      <BackofficeStatusBadge
                        status={successRateStatus(site.successRate)}
                        label={formatSuccessRate(site.successRate)}
                      />
                    </div>
                  </BackofficeStackCard>
                ))}
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
