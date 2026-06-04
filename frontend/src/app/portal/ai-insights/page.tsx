'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { PortalEmptyState, PortalLoadingState, PortalSignedOutState } from '@/components/portal/PortalPageState';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalAIInsightAnalysis,
  type PortalAIInsightHistoryItem,
  type PortalAIInsightHistoryResponse,
  type Site,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { getPortalSiteDisplayName } from '@/lib/portal-site-display';
import { cn, formatDate, formatNumber } from '@/lib/utils';

function resolveSelectedSite(
  sites: Site[],
  requestedSiteId: string,
  sessionSiteId: string
): Site | null {
  return (
    sites.find((site) => site.site_id === requestedSiteId && site.status !== 'archived') ||
    sites.find((site) => site.site_id === sessionSiteId && site.status !== 'archived') ||
    sites.find((site) => site.status !== 'archived') ||
    null
  );
}

function statusTone(status: string): string {
  if (status === 'ok') return 'active';
  if (status === 'attention' || status === 'warning') return 'warning';
  if (status === 'error' || status === 'critical') return 'error';
  return 'inactive';
}

function severityTone(severity: string): 'neutral' | 'success' | 'info' | 'warning' | 'danger' | 'accent' {
  if (severity === 'error' || severity === 'critical') return 'danger';
  if (severity === 'warning') return 'warning';
  if (severity === 'info') return 'info';
  return 'neutral';
}

function isAIGenerated(analysis: PortalAIInsightAnalysis | PortalAIInsightHistoryItem | null): boolean {
  return Boolean(analysis?.ai_disclosure?.generated_by_ai);
}

function getGenerationLabel(
  mode: string,
  t: (key: string, params?: Record<string, string>, fallback?: string) => string
): string {
  if (mode === 'llm_cached') return t('portal.ai_insights.mode_ai_cached', {}, 'AI cached');
  if (mode === 'llm') return t('portal.ai_insights.mode_ai_generated', {}, 'AI generated');
  return t('portal.ai_insights.mode_rule_analysis', {}, 'Rule analysis');
}

function AIContentLabel({ analysis }: { analysis: PortalAIInsightAnalysis | PortalAIInsightHistoryItem }) {
  const { t } = useLocale();
  const disclosure = analysis.ai_disclosure;
  const generatedByAI = isAIGenerated(analysis);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800 dark:border-blue-900/60 dark:bg-blue-950/35 dark:text-blue-200">
        <span className="brand-mark flex h-5 w-5 items-center justify-center" aria-hidden="true">
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
            <path d="M6 15.25 12.2 4l.6 6.55H18l-6.2 9.45-.5-6.2H6Z" fill="currentColor" />
          </svg>
        </span>
        {disclosure.brand_label || 'Magick AI'}
      </span>
      <BackofficeTag tone={generatedByAI ? 'accent' : 'neutral'}>
        {disclosure.visible_label || getGenerationLabel(analysis.generation.mode, t)}
      </BackofficeTag>
      <BackofficeTag tone={generatedByAI ? 'warning' : 'neutral'}>
        {disclosure.review_status || 'not_ai_generated'}
      </BackofficeTag>
    </div>
  );
}

function AnalysisPanel({
  analysis,
  isLoading,
}: {
  analysis: PortalAIInsightAnalysis | null;
  isLoading: boolean;
}) {
  const { t } = useLocale();
  if (!analysis) {
    return (
      <PortalEmptyState
        title={t('portal.ai_insights.empty_title', {}, 'No AI analysis yet')}
        description={t(
          'portal.ai_insights.empty_desc',
          {},
          'Run a manual analysis to see Magick AI summarize operations signals and suggest the next action.'
        )}
      />
    );
  }

  const generation = analysis.generation;
  const disclosure = analysis.ai_disclosure;
  return (
    <BackofficeSectionPanel className={cn(isLoading ? 'opacity-70' : '')}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-3">
          <AIContentLabel analysis={analysis} />
          <div>
            <h2 className="text-xl font-semibold leading-tight text-slate-950 dark:text-white">
              {analysis.headline || t('portal.ai_insights.analysis_title', {}, 'Operations analysis')}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {analysis.operator_summary}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <BackofficeStatusBadge
            status={statusTone(analysis.status)}
            label={analysis.status || 'unknown'}
          />
          <BackofficeTag tone={severityTone(analysis.severity)}>
            {analysis.severity || 'neutral'}
          </BackofficeTag>
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <BackofficeStackCard>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            {t('portal.ai_insights.next_step', {}, 'Next step')}
          </p>
          <p className="mt-2 text-sm font-medium leading-6 text-slate-900 dark:text-slate-100">
            {analysis.operator_next_step || t('common.not_found')}
          </p>
        </BackofficeStackCard>
        <BackofficeStackCard>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            {t('portal.ai_insights.cache_state', {}, 'Analysis state')}
          </p>
          <div className="mt-2 space-y-1 text-sm text-slate-700 dark:text-slate-200">
            <p>{getGenerationLabel(generation.mode, t)}</p>
            {generation.cache_hit ? (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('portal.ai_insights.cache_hit', {}, 'Served from recent analysis')}
              </p>
            ) : null}
            {generation.cache_expires_at ? (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('portal.ai_insights.cache_fresh_until', {}, 'Fresh until')} {formatDate(generation.cache_expires_at)}
              </p>
            ) : null}
          </div>
        </BackofficeStackCard>
      </div>

      {disclosure.visible_notice ? (
        <div className="mt-4 rounded-[1rem] border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
          {disclosure.visible_notice}
        </div>
      ) : null}
      {analysis.safety_note ? (
        <p className="mt-4 text-xs leading-5 text-slate-500 dark:text-slate-400">{analysis.safety_note}</p>
      ) : null}
    </BackofficeSectionPanel>
  );
}

function HistoryPanel({
  history,
  onSelect,
}: {
  history: PortalAIInsightHistoryItem[];
  onSelect: (item: PortalAIInsightHistoryItem) => void;
}) {
  const { t } = useLocale();
  return (
    <BackofficeSectionPanel>
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
            {t('portal.ai_insights.history_title', {}, 'Analysis history')}
          </h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {t('portal.ai_insights.history_desc', {}, 'History loads without calling AI again.')}
          </p>
        </div>
        <BackofficeTag tone="neutral">{formatNumber(history.length)}</BackofficeTag>
      </div>
      <div className="mt-4 space-y-3">
        {history.length ? (
          history.map((item) => (
            <button
              key={`${item.generated_at}-${item.headline}`}
              type="button"
              className="block w-full rounded-[1.1rem] border border-slate-200/80 bg-white/75 px-4 py-3 text-left transition hover:border-blue-300 hover:bg-blue-50/60 dark:border-slate-800 dark:bg-slate-950/45 dark:hover:border-blue-800 dark:hover:bg-blue-950/25"
              onClick={() => onSelect(item)}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <AIContentLabel analysis={item} />
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {formatDate(item.generated_at)}
                </span>
              </div>
              <p className="mt-3 text-sm font-semibold text-slate-950 dark:text-white">
                {item.headline || t('portal.ai_insights.history_item', {}, 'Operations analysis')}
              </p>
              <p className="mt-1 line-clamp-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {item.operator_summary}
              </p>
            </button>
          ))
        ) : (
          <p className="rounded-[1rem] border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
            {t('portal.ai_insights.history_empty', {}, 'No previous analysis for this site.')}
          </p>
        )}
      </div>
    </BackofficeSectionPanel>
  );
}

function PortalAIInsightsContent() {
  const { t } = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { session, isLoading, isAuthenticated, selectSite } = useSession();
  const [analysis, setAnalysis] = useState<PortalAIInsightAnalysis | null>(null);
  const [historyPayload, setHistoryPayload] = useState<PortalAIInsightHistoryResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);
  const requestedSiteId = searchParams.get('site') || '';
  const sites = useMemo(() => session?.sites || [], [session?.sites]);
  const selectedSite = resolveSelectedSite(sites, requestedSiteId, session?.site_id || '');
  const selectedSiteId = selectedSite?.site_id || '';

  useEffect(() => {
    setAnalysis(null);
    setHistoryPayload(null);
    setError('');
  }, [selectedSiteId]);

  useEffect(() => {
    if (!selectedSiteId) {
      return;
    }
    let isCancelled = false;
    setIsHistoryLoading(true);
    setError('');
    void portalClient
      .listAIInsightHistory(selectedSiteId, { limit: 10 })
      .then((response) => {
        if (!isCancelled) {
          setHistoryPayload(response.data);
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          setHistoryPayload(null);
          setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setIsHistoryLoading(false);
        }
      });
    return () => {
      isCancelled = true;
    };
  }, [refreshNonce, selectedSiteId, t]);

  const handleSiteChange = useCallback(
    async (siteId: string) => {
      if (!siteId || siteId === selectedSiteId) {
        return;
      }
      await selectSite(siteId);
      const params = new URLSearchParams(searchParams?.toString() || '');
      params.set('site', siteId);
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams, selectSite, selectedSiteId]
  );

  const handleAnalyze = useCallback(
    async (forceRefresh = false) => {
      if (!selectedSiteId) {
        return;
      }
      setIsAnalyzing(true);
      setError('');
      try {
        const response = await portalClient.analyzeAIInsight(selectedSiteId, { forceRefresh });
        setAnalysis(response.data.analysis);
        setHistoryPayload((current) =>
          current
            ? {
                ...current,
                items: [
                  {
                    site_id: response.data.site_id,
                    scope: response.data.analysis.scope,
                    status: response.data.analysis.status,
                    severity: response.data.analysis.severity,
                    headline: response.data.analysis.headline,
                    operator_summary: response.data.analysis.operator_summary,
                    operator_next_step: response.data.analysis.operator_next_step,
                    generated_at: response.data.analysis.generated_at,
                    fresh_until: response.data.analysis.generation.cache_expires_at,
                    is_stale: false,
                    generation: response.data.analysis.generation,
                    ai_disclosure: response.data.analysis.ai_disclosure,
                  },
                  ...current.items,
                ].slice(0, 10),
              }
            : current
        );
        setRefreshNonce((current) => current + 1);
      } catch (err) {
        setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
      } finally {
        setIsAnalyzing(false);
      }
    },
    [selectedSiteId, t]
  );

  if (isLoading) {
    return <PortalLoadingState message={t('common.loading')} />;
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('auth.not_signed_in')}
        description={t('auth.please_sign_in')}
        actionLabel={t('nav.sign_in')}
      />
    );
  }

  if (!selectedSite) {
    return (
      <PortalEmptyState
        title={t('portal.no_sites', {}, 'No sites')}
        description={t(
          'portal.ai_insights.no_site_desc',
          {},
          'Provision or select a site before opening AI Insights.'
        )}
      />
    );
  }

  const activeAnalysis = analysis;
  const history = historyPayload?.items || [];
  const latestHistory = history[0] || null;
  const selectedSiteName = getPortalSiteDisplayName(selectedSite);

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.workspace_label', {}, 'Portal')}
        title={t('portal.ai_insights.title', {}, 'AI Insights')}
        description={t(
          'portal.ai_insights.subtitle',
          {},
          'Manual operations analysis for the selected site. Provider, model, token usage, cost, and cache keys stay internal.'
        )}
        currentPage="ai-insights"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSiteName}
        showSiteContextSummary
        sites={sites}
        onSiteChange={handleSiteChange}
        metrics={[
          {
            label: t('portal.ai_insights.metric_mode', {}, 'Current mode'),
            value: activeAnalysis
              ? getGenerationLabel(activeAnalysis.generation.mode, t)
              : t('portal.ai_insights.mode_manual', {}, 'Manual'),
            detail: activeAnalysis?.generation.cache_hit
              ? t('portal.ai_insights.metric_cache_hit', {}, 'Recent cached analysis')
              : t('portal.ai_insights.metric_manual_detail', {}, 'No automatic AI call on page load'),
            size: 'compact',
          },
          {
            label: t('portal.ai_insights.metric_review', {}, 'Review'),
            value: activeAnalysis?.ai_disclosure.review_status || latestHistory?.ai_disclosure.review_status || t('portal.ai_insights.none', {}, 'None'),
            detail: t('portal.ai_insights.metric_review_detail', {}, 'AI text is labeled for human review'),
            size: 'compact',
          },
          {
            label: t('portal.ai_insights.metric_history', {}, 'History'),
            value: formatNumber(history.length),
            detail: t('portal.ai_insights.metric_history_detail', {}, 'Read without new AI call'),
          },
        ]}
        metricsColumnsClassName="lg:grid-cols-3"
        primaryAction={
          <button
            type="button"
            className="btn btn-primary"
            disabled={isAnalyzing}
            onClick={() => void handleAnalyze(false)}
          >
            {isAnalyzing
              ? t('portal.ai_insights.analyzing', {}, 'Analyzing...')
              : t('portal.ai_insights.analyze', {}, 'Generate AI analysis')}
          </button>
        }
        secondaryActions={
          <button
            type="button"
            className="btn btn-secondary"
            disabled={isAnalyzing}
            onClick={() => void handleAnalyze(true)}
          >
            {t('portal.ai_insights.refresh', {}, 'Refresh analysis')}
          </button>
        }
      />

      {error ? (
        <div className="rounded-[1rem] border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200">
          {error}
        </div>
      ) : null}

      <BackofficeMetricStrip
        columnsClassName="lg:grid-cols-4"
        items={[
          {
            label: t('portal.ai_insights.boundary_manual', {}, 'Trigger'),
            value: t('portal.ai_insights.mode_manual', {}, 'Manual'),
            detail: t('portal.ai_insights.boundary_manual_detail', {}, 'A page refresh only reads history'),
            size: 'compact',
          },
          {
            label: t('portal.ai_insights.boundary_payload', {}, 'Payload'),
            value: t('portal.ai_insights.boundary_payload_value', {}, 'Redacted'),
            detail: t('portal.ai_insights.boundary_payload_detail', {}, 'No secrets or raw WordPress content'),
            size: 'compact',
          },
          {
            label: t('portal.ai_insights.boundary_write', {}, 'WordPress write'),
            value: t('portal.ai_insights.boundary_write_value', {}, 'Blocked'),
            detail: t('portal.ai_insights.boundary_write_detail', {}, 'Analysis cannot publish or modify content'),
            size: 'compact',
          },
          {
            label: t('portal.ai_insights.boundary_internal', {}, 'Internal fields'),
            value: t('portal.ai_insights.boundary_internal_value', {}, 'Hidden'),
            detail: t('portal.ai_insights.boundary_internal_detail', {}, 'Provider, cost, tokens, cache key'),
            size: 'compact',
          },
        ]}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(22rem,0.85fr)]">
        <AnalysisPanel analysis={activeAnalysis} isLoading={isAnalyzing} />
        <HistoryPanel history={history} onSelect={(item) => setAnalysis({
          summary_version: 'internal-ops-summarizer-v1',
          scope: item.scope,
          status: item.status,
          severity: item.severity,
          headline: item.headline,
          operator_summary: item.operator_summary,
          operator_next_step: item.operator_next_step,
          safety_note: '',
          generated_at: item.generated_at,
          generation: item.generation,
          ai_disclosure: item.ai_disclosure,
        })} />
      </div>

      {isHistoryLoading && !history.length ? (
        <p className="text-center text-sm text-slate-500 dark:text-slate-400">
          {t('portal.ai_insights.loading_history', {}, 'Loading analysis history...')}
        </p>
      ) : null}
    </BackofficePageStack>
  );
}

export default function PortalAIInsightsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalAIInsightsContent />
    </Suspense>
  );
}
