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
import type { PortalPluginObservabilitySummary } from '@/lib/portal-client';
import { cn, formatDate, formatNumber } from '@/lib/utils';

type PortalPluginMonitoringPanelProps = {
  siteId: string;
  summary: PortalPluginObservabilitySummary | null;
  isLoading?: boolean;
  error?: string;
  compact?: boolean;
  onRetry?: () => void;
};

const PLUGIN_LABELS: Record<string, string> = {
  'npcink-abilities-toolkit': 'Abilities',
  'npcink-governance-core': 'Core',
  'npcink-ai-client-adapter': 'Adapter',
};

function formatSuccessRate(rate: number): string {
  return `${(Number(rate || 0) * 100).toFixed(1)}%`;
}

function successStatus(rate: number, errorTotal: number): string {
  if (errorTotal > 0) return 'warning';
  if (rate >= 0.99) return 'active';
  if (rate >= 0.95) return 'warning';
  return 'error';
}

function attentionTone(severity: string): 'warning' | 'danger' | 'info' {
  if (severity === 'error') return 'danger';
  if (severity === 'warning') return 'warning';
  return 'info';
}

function pluginLabel(slug: string): string {
  return PLUGIN_LABELS[slug] || slug;
}

function timelineLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return `${String(date.getHours()).padStart(2, '0')}:00`;
}

export function PortalPluginMonitoringPanel({
  siteId,
  summary,
  isLoading = false,
  error = '',
  compact = false,
  onRetry,
}: PortalPluginMonitoringPanelProps) {
  const { t } = useLocale();
  const totals = summary?.totals || null;
  const plugins = summary?.plugins || [];
  const timeline = summary?.timeline || [];
  const recentErrors = summary?.recent_errors || [];
  const attention = summary?.attention || [];
  const health = summary?.health || null;
  const digest = summary?.digest || null;
  const hasEvents = Number(totals?.events_total || 0) > 0;
  const timelineData = timeline.map((point) => ({
    label: timelineLabel(point.bucket_start_at),
    value: Number(point.events_total || 0),
    secondaryValue: Number(point.error_total || 0),
  }));
  const pluginErrorData = plugins.map((plugin) => ({
    label: pluginLabel(plugin.plugin_slug),
    value: Number(plugin.error_total || 0),
    color: Number(plugin.error_total || 0) > 0 ? '#f59e0b' : '#22c55e',
  }));
  const hasPluginErrors = pluginErrorData.some((item) => item.value > 0);
  const pluginVolumeData = plugins.map((plugin) => ({
    label: pluginLabel(plugin.plugin_slug),
    value: Number(plugin.events_total || 0),
    color: Number(plugin.error_total || 0) > 0 ? '#f59e0b' : '#3b82f6',
  }));

  return (
    <BackofficeSectionPanel className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
	          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
	            {t('portal.monitoring.eyebrow', {}, 'Site connection')}
	          </p>
	          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
	            {t('portal.monitoring.title', {}, 'Site connection status')}
	          </h2>
	          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-300">
	            {t(
	              'portal.monitoring.desc',
	              {},
	              'Read-only connection activity from this WordPress site.'
	            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 lg:justify-end">
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
      ) : !hasEvents ? (
	        <BackofficeEmptyState
	          title={t('portal.monitoring.empty_title', {}, 'No connection activity yet')}
	          description={t(
	            'portal.monitoring.empty_desc',
	            {},
	            'Activity will appear after the site connects and sends service checks.'
	          )}
	        />
      ) : (
        <>
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-4"
            items={[
	              {
	                label: t('portal.monitoring.events', {}, 'Activity'),
	                value: formatNumber(Number(totals?.events_total || 0)),
	                detail: `${summary?.window?.hours || 24}h`,
	              },
	              {
	                label: t('portal.monitoring.errors', {}, 'Issues'),
	                value: formatNumber(Number(totals?.error_total || 0)),
	                detail: t('portal.monitoring.error_detail', {}, 'No private content shown'),
	                toneClassName: Number(totals?.error_total || 0) > 0 ? 'text-amber-700 dark:text-amber-200' : '',
	              },
	              {
	                label: t('portal.monitoring.success_rate', {}, 'OK rate'),
	                value: formatSuccessRate(Number(totals?.success_rate || 0)),
	                detail: t('portal.monitoring.success_detail', {}, 'Activity without issues'),
              },
              {
                label: t('portal.monitoring.last_seen', {}, 'Last seen'),
                value: totals?.last_seen_at ? formatDate(totals.last_seen_at) : t('common.not_found'),
                detail: t('portal.monitoring.last_seen_detail', {}, 'Updated'),
              },
            ]}
          />

          {health || attention.length ? (
            <BackofficeStackCard className="space-y-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
	                    {t('portal.monitoring.health_label', {}, 'Status')}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-slate-950 dark:text-white">
	                    {health?.summary || t('portal.monitoring.health_default', {}, 'Connection status')}
                  </h3>
                </div>
                {health ? (
                  <BackofficeStatusBadge
	                    status={health.status}
	                    label={t(`status.${health.status}`, {}, health.status)}
                    className="shrink-0"
                  />
                ) : null}
              </div>
              {attention.length ? (
                <div className="grid gap-2 lg:grid-cols-3">
                  {attention.slice(0, compact ? 2 : 3).map((item) => (
                    <div
                      key={`${item.code}-${item.plugin_slug || ''}-${item.error_code || ''}`}
                      className="rounded-xl border border-slate-200/80 bg-white/70 px-3 py-3 text-sm dark:border-slate-800 dark:bg-slate-900/40"
                    >
	                      <div className="flex items-start justify-between gap-2">
	                        <p className="font-semibold text-slate-950 dark:text-white">{item.title}</p>
	                        <BackofficeTag tone={attentionTone(item.severity)}>{item.severity}</BackofficeTag>
	                      </div>
	                      <p className="mt-2 text-xs leading-5 text-slate-600 dark:text-slate-300">{item.detail}</p>
	                      {item.suggested_action ? (
                        <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                          {item.suggested_action}
                        </p>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </BackofficeStackCard>
          ) : null}

          {digest?.headline && !compact ? (
            <BackofficeStackCard className="space-y-3">
              <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                    {t('portal.monitoring.digest_label', {}, 'Digest')}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-slate-950 dark:text-white">
                    {digest.headline}
                  </h3>
                </div>
                <BackofficeTag tone="info">{digest.period_label || `${digest.window_hours}h`}</BackofficeTag>
              </div>
              {Array.isArray(digest.bullets) && digest.bullets.length ? (
                <div className="grid gap-2 md:grid-cols-2">
                  {digest.bullets.slice(0, 4).map((item) => (
                    <div
                      key={item}
                      className="rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 text-xs leading-5 text-slate-600 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-300"
                    >
                      {item}
                    </div>
                  ))}
                </div>
              ) : null}
            </BackofficeStackCard>
          ) : null}

          {!compact ? (
            <div className="grid gap-3 lg:grid-cols-2">
              <BackofficeStackCard className="space-y-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                    {t('portal.monitoring.trend_label', {}, 'Trend')}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-slate-950 dark:text-white">
	                    {t('portal.monitoring.trend_title', {}, 'Activity and issues')}
                  </h3>
                </div>
                <AnalyticsLineChart
                  data={timelineData}
                  height={220}
	                  primarySeriesName={t('portal.monitoring.events', {}, 'Activity')}
	                  secondarySeriesName={t('portal.monitoring.errors', {}, 'Issues')}
                  primaryColor="#2563eb"
                  secondaryColor="#f59e0b"
                />
              </BackofficeStackCard>
              <BackofficeStackCard className="space-y-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
	                    {t('portal.monitoring.plugin_compare_label', {}, 'Connection parts')}
                  </p>
                  <h3 className="mt-1 text-sm font-semibold text-slate-950 dark:text-white">
                    {hasPluginErrors
	                      ? t('portal.monitoring.plugin_errors_title', {}, 'Issue count')
	                      : t('portal.monitoring.plugin_volume_title', {}, 'Activity volume')}
                  </h3>
                </div>
                <AnalyticsBarChart
                  data={hasPluginErrors ? pluginErrorData : pluginVolumeData}
                  height={220}
                  barColor={hasPluginErrors ? '#f59e0b' : '#2563eb'}
                />
              </BackofficeStackCard>
            </div>
          ) : null}

          <div className={cn('grid gap-3', compact ? 'lg:grid-cols-3' : 'lg:grid-cols-3')}>
            {plugins.map((plugin) => (
              <BackofficeStackCard key={plugin.plugin_slug} className="space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
	                    <p className="truncate text-sm font-semibold text-slate-950 dark:text-white">
	                      {pluginLabel(plugin.plugin_slug)}
	                    </p>
                  </div>
                  <BackofficeStatusBadge
                    status={successStatus(plugin.success_rate, plugin.error_total)}
                    label={plugin.error_total > 0 ? t('common.warning', {}, 'Warning') : t('common.ok', {}, 'OK')}
                    className="shrink-0 text-[0.68rem]"
                  />
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-slate-600 dark:text-slate-300">
	                  <BackofficeTag>{formatNumber(plugin.events_total)} {t('portal.monitoring.events', {}, 'Activity')}</BackofficeTag>
	                  <BackofficeTag tone={plugin.error_total > 0 ? 'warning' : 'success'}>
	                    {formatNumber(plugin.error_total)} {t('portal.monitoring.errors', {}, 'Issues')}
	                  </BackofficeTag>
                  <BackofficeTag>{formatSuccessRate(plugin.success_rate)}</BackofficeTag>
                </div>
                {!compact && plugin.event_kinds.length ? (
                  <details className="border-t border-slate-200/80 pt-3 text-xs dark:border-slate-800">
                    <summary className="cursor-pointer font-semibold text-slate-500 dark:text-slate-400">
                      {t('portal.monitoring.support_event_types', {}, 'Support event types')}
                    </summary>
                    <div className="mt-2 space-y-2">
                      {plugin.event_kinds.slice(0, 3).map((eventKind) => (
                        <div key={`${plugin.plugin_slug}-${eventKind.event_kind}`} className="flex items-center justify-between gap-3">
                          <span className="min-w-0 truncate text-slate-600 dark:text-slate-300">
                            {eventKind.event_kind}
                          </span>
                          <span className="shrink-0 text-slate-500 dark:text-slate-400">
                            {formatNumber(eventKind.events_total)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
              </BackofficeStackCard>
            ))}
          </div>

          {!compact && recentErrors.length ? (
            <BackofficeStackCard className="space-y-3">
              <div>
                <p className="text-sm font-semibold text-slate-950 dark:text-white">
	                  {t('portal.monitoring.recent_errors', {}, 'Recent issues')}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
	                  {t('portal.monitoring.recent_errors_desc', {}, 'Private content and raw requests are not shown.')}
                </p>
              </div>
              <div className="divide-y divide-slate-200/80 dark:divide-slate-800">
                {recentErrors.slice(0, 5).map((item, index) => (
                  <div key={`${item.plugin_slug}-${item.event_kind}-${item.received_at}-${index}`} className="grid gap-2 py-3 text-sm lg:grid-cols-[160px_minmax(0,1fr)_180px] lg:items-center">
                    <span className="font-medium text-slate-900 dark:text-slate-100">{pluginLabel(item.plugin_slug)}</span>
	                    <span className="min-w-0 truncate text-slate-600 dark:text-slate-300">
	                      {t('portal.monitoring.recent_issue_item', {}, 'Connection issue')}
	                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400 lg:text-right">
                      {formatDate(item.received_at)}
                    </span>
                  </div>
                ))}
              </div>
            </BackofficeStackCard>
          ) : null}
        </>
      )}
    </BackofficeSectionPanel>
  );
}
