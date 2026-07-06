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
import type { PortalVectorObservabilitySummary } from '@/lib/portal-client';
import { formatDate, formatNumber } from '@/lib/utils';

type PortalSiteKnowledgePanelProps = {
  summary: PortalVectorObservabilitySummary | null;
  isLoading?: boolean;
  error?: string;
  onRetry?: () => void;
};

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

export function PortalSiteKnowledgePanel({
  summary,
  isLoading = false,
  error = '',
  onRetry,
}: PortalSiteKnowledgePanelProps) {
  const { t } = useLocale();
  const totals = summary?.totals || null;
  const hasActivity =
    Number(totals?.index_jobs_total || 0) > 0 ||
    Number(totals?.search_queries_total || 0) > 0 ||
    Number(totals?.current_chunk_count || 0) > 0;
  const timelineData = (summary?.timeline || []).map((point) => ({
    label: timelineLabel(point.bucket_start_at),
    value: Number(point.search_queries_total || 0),
    secondaryValue: Number(point.no_hit_total || 0),
  }));
  const intentData = (summary?.intents || []).map((item) => ({
    label: item.intent || 'unknown',
    value: Number(item.queries_total || 0),
    color: Number(item.no_hit_total || 0) > 0 ? '#f59e0b' : '#2563eb',
  }));
  const snapshot = summary?.index_snapshots?.[0] || null;

  return (
    <BackofficeSectionPanel className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {t('portal.vector_obs.eyebrow', {}, 'Site knowledge')}
          </p>
	          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
	            {t('portal.vector_obs.title', {}, 'Site knowledge')}
	          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-300">
            {t(
              'portal.vector_obs.desc',
              {},
	              'Read-only status for site knowledge search.'
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
      ) : !hasActivity ? (
        <BackofficeEmptyState
	          title={t('portal.vector_obs.empty_title', {}, 'No site knowledge activity yet')}
          description={t(
            'portal.vector_obs.empty_desc',
            {},
	            'Activity will appear after site knowledge sync or search runs.'
          )}
        />
      ) : (
        <>
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-4"
            items={[
              {
	                label: t('portal.vector_obs.indexed', {}, 'Saved pages'),
	                value: formatNumber(Number(totals?.current_document_count || 0)),
	                detail: t('portal.vector_obs.saved_piece_count', { count: formatNumber(Number(totals?.current_chunk_count || 0)) }, '{{count}} saved piece(s)'),
              },
              {
                label: t('portal.vector_obs.searches', {}, 'Searches'),
                value: formatNumber(Number(totals?.search_queries_total || 0)),
                detail: `${summary?.window?.hours || 24}h`,
              },
              {
	                label: t('portal.vector_obs.no_hit', {}, 'No answer rate'),
	                value: formatPercent(Number(totals?.no_hit_rate || 0)),
	                detail: t('portal.vector_obs.no_answer_count', { count: formatNumber(Number(totals?.no_hit_total || 0)) }, '{{count}} no answer'),
                toneClassName:
                  Number(totals?.no_hit_rate || 0) >= 0.25
                    ? 'text-amber-700 dark:text-amber-200'
                    : '',
              },
              {
	                label: t('portal.vector_obs.p95', {}, 'Search time'),
	                value: `${formatNumber(Number(totals?.p95_search_latency_ms || 0))}ms`,
	                detail: t('portal.vector_obs.match_score', { score: formatScore(Number(totals?.avg_top1_score || 0)) }, 'Match {{score}}'),
                size: 'compact',
              },
            ]}
          />

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
	                {t('portal.vector_obs.trend', {}, 'Searches and no answers')}
              </h3>
              <AnalyticsLineChart
                data={timelineData}
                height={240}
                primarySeriesName={t('portal.vector_obs.searches', {}, 'Searches')}
	                secondarySeriesName={t('portal.vector_obs.no_hit_count', {}, 'No answer')}
                primaryColor="#2563eb"
                secondaryColor="#f59e0b"
              />
            </BackofficeStackCard>
            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
	                  {t('portal.vector_obs.intents', {}, 'Search topics')}
              </h3>
              <AnalyticsBarChart data={intentData} height={240} barColor="#2563eb" />
            </BackofficeStackCard>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeStackCard className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
	                  {t('portal.vector_obs.coverage', {}, 'Knowledge coverage')}
	                </h3>
              </div>
              <div className="space-y-2 text-sm text-slate-700 dark:text-slate-300">
                <div className="flex justify-between gap-3">
	                  <span>{t('portal.vector_obs.last_indexed', {}, 'Last updated')}</span>
                  <span className="font-semibold text-slate-950 dark:text-white">
                    {snapshot?.last_indexed_at ? formatDate(snapshot.last_indexed_at) : t('common.not_found')}
                  </span>
                </div>
                <div className="flex flex-wrap gap-2 pt-1">
                  {Object.entries(snapshot?.source_type_counts || {}).map(([key, value]) => (
                    <BackofficeTag key={key} tone="info">
                      {key}: {formatNumber(Number(value || 0))}
                    </BackofficeTag>
                  ))}
                </div>
              </div>
            </BackofficeStackCard>

            <BackofficeStackCard className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
	                  {t('portal.vector_obs.failures', {}, 'Issues')}
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
	                          {t('portal.vector_obs.issue_item', {}, 'Knowledge issue')}
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
	                  {t('portal.vector_obs.no_failures', {}, 'No issues in this period.')}
                </p>
              )}
            </BackofficeStackCard>
          </div>
        </>
      )}
    </BackofficeSectionPanel>
  );
}
