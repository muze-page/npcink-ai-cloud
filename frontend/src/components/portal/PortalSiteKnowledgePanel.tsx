'use client';

import {
  PortalCard,
  PortalMetricStrip,
  PortalSection,
} from '@/components/portal/PortalScaffold';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import { useLocale } from '@/contexts/LocaleContext';
import type { PortalVectorObservabilitySummary } from '@/lib/portal-client';
import { formatDate, formatNumber } from '@/lib/utils';

type PortalSiteKnowledgePanelProps = {
  summary: PortalVectorObservabilitySummary | null;
  isLoading?: boolean;
  error?: string;
  onRetry?: () => void;
};

export function PortalSiteKnowledgePanel({
  summary,
  isLoading = false,
  error = '',
  onRetry,
}: PortalSiteKnowledgePanelProps) {
  const { t } = useLocale();
  const totals = summary?.totals || null;
  const snapshot = summary?.index_snapshots?.[0] || null;
  const indexedPages = Number(snapshot?.document_count ?? totals?.current_document_count ?? 0);
  const searchCount = Number(totals?.search_queries_total || 0);
  const noAnswerCount = Number(totals?.no_hit_total || 0);
  const lastUpdatedAt = snapshot?.last_indexed_at || totals?.last_index_job_finished_at || '';
  const hasKnowledge = indexedPages > 0 || Number(totals?.index_jobs_total || 0) > 0;
  const needsAttention = Boolean(
    hasKnowledge && summary && ['warning', 'error'].includes(summary.health.status)
  );
  const windowDays = Math.max(1, Math.round(Number(summary?.window?.hours || 168) / 24));
  const statusLabel = !hasKnowledge
    ? t('portal.vector_obs.status_empty', {}, 'Not set up')
    : needsAttention
      ? t('portal.vector_obs.status_attention', {}, 'Needs attention')
      : t('portal.vector_obs.status_ready', {}, 'Ready');
  const displayedStatusLabel = error
    ? t('portal.home.package_pending_label', {}, 'To confirm')
    : summary
      ? statusLabel
      : t('common.loading');
  const statusTone = error || !hasKnowledge ? 'inactive' : needsAttention ? 'warning' : 'active';

  return (
    <PortalSection
      id="site-knowledge"
      className="scroll-mt-24 space-y-5"
      data-portal-site="site-knowledge"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
            {t('portal.vector_obs.title', {}, 'Site knowledge')}
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t(
              'portal.vector_obs.customer_desc',
              {},
              'Site knowledge helps AI use the pages already indexed from this site.'
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PortalStatusBadge
            status={statusTone}
            label={displayedStatusLabel}
            className="normal-case tracking-normal"
          />
          {onRetry ? (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onRetry}
              disabled={isLoading}
            >
              {t('common.refresh', {}, 'Refresh')}
            </button>
          ) : null}
        </div>
      </div>

      {isLoading ? (
        <PortalCard className="text-sm text-slate-600 dark:text-slate-300">
          {t('common.loading')}
        </PortalCard>
      ) : null}

      {error ? (
        <PortalCard className="border-amber-200 bg-amber-50/70 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
          {t(
            'portal.vector_obs.load_failed',
            {},
            'Site knowledge status could not be loaded. Try again later.'
          )}
        </PortalCard>
      ) : null}

      {!isLoading && !error && summary && !hasKnowledge ? (
        <PortalCard className="text-sm leading-6 text-slate-600 dark:text-slate-300">
          {t(
            'portal.vector_obs.customer_empty_desc',
            {},
            'No pages have been indexed yet. Sync site knowledge from the WordPress plugin.'
          )}
        </PortalCard>
      ) : null}

      {!isLoading && !error && summary && hasKnowledge ? (
        <PortalMetricStrip
          columnsClassName="md:grid-cols-3"
          items={[
            {
              label: t('portal.vector_obs.indexed', {}, 'Saved pages'),
              value: formatNumber(indexedPages),
              detail: t(
                'portal.vector_obs.indexed_detail',
                {},
                'Pages currently available to site knowledge.'
              ),
            },
            {
              label: t('portal.vector_obs.last_indexed', {}, 'Last updated'),
              value: lastUpdatedAt
                ? formatDate(lastUpdatedAt)
                : t('portal.home.package_pending_label', {}, 'To confirm'),
              detail: t(
                'portal.vector_obs.update_hint',
                {},
                'Update from the WordPress plugin when site content changes.'
              ),
              size: 'compact',
            },
            {
              label: t(
                'portal.vector_obs.recent_usage',
                { days: String(windowDays) },
                'Recent use'
              ),
              value: t(
                'portal.vector_obs.search_count',
                { count: formatNumber(searchCount) },
                '{{count}} searches'
              ),
              detail: t(
                'portal.vector_obs.no_answer_detail',
                { count: formatNumber(noAnswerCount) },
                '{{count}} could not find related content.'
              ),
              size: 'compact',
            },
          ]}
        />
      ) : null}
    </PortalSection>
  );
}
