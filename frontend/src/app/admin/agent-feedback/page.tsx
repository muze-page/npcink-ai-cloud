'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { BackofficeDiagnosticNotice, BackofficeDisclosure, BackofficeEmptyState, BackofficeLayer, BackofficeMetricStrip, BackofficePageStack, BackofficeSectionPanel, BackofficeStackCard, BackofficeSummaryStrip } from '@/components/backoffice/BackofficeScaffold';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag, type BackofficeTagTone } from '@/components/backoffice/BackofficeTag';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber } from '@/lib/utils';

const agentFeedbackClient = createApiClient({ idempotencyPrefix: 'agent_feedback' });

type CountMap = Record<string, number>;

type FeedbackScenario = {
  localSurface: string;
  sourceRuntime: string;
  eventsTotal: number;
  outcomes: CountMap;
  labels: CountMap;
  acceptedRate: number;
  evidenceWeakRate: number;
  wrongNextStepRate: number;
};

type FeedbackTrendPoint = {
  bucket: string;
  eventsTotal: number;
  accepted: number;
  rejected: number;
  evidenceWeak: number;
  wrongNextStep: number;
};

type FeedbackTopCount = {
  label: string;
  count: number;
};

type AgentFeedbackSummary = {
  artifactType: string;
  contractVersion: string;
  scope: string;
  siteId: string;
  windowHours: number;
  generatedAt: string;
  windowStartAt: string;
  lastEventAt: string;
  eventsTotal: number;
  limited: boolean;
  maxEvents: number;
  outcomes: CountMap;
  labels: CountMap;
  sourceRuntimes: CountMap;
  localSurfaces: CountMap;
  scenarios: FeedbackScenario[];
  qualityTrend: FeedbackTrendPoint[];
  lowQualityLabels: FeedbackTopCount[];
  rejectionReasons: FeedbackTopCount[];
  rates: {
    acceptedRate: number;
    evidenceUsefulRate: number;
    evidenceWeakRate: number;
    wrongNextStepRate: number;
  };
  readOnly: boolean;
  productionMutation: boolean;
  approvalTruth: string;
  preflightTruth: string;
  finalWriteTruth: string;
  boundary: {
    productionMutation: boolean;
    approvalTruth: string;
    preflightTruth: string;
    finalWriteTruth: string;
    controlPlane: string;
  };
};

type TranslationFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

const WINDOW_OPTIONS = [
  { label: '24h', value: 24 },
  { label: '7d', value: 168 },
];

const LABEL_FALLBACKS: Record<string, { key: string; fallback: string }> = {
  already_handled: { key: 'admin.agent_feedback.label_already_handled', fallback: 'Already handled' },
  duplicate_suggestion: { key: 'admin.agent_feedback.label_duplicate_suggestion', fallback: 'Duplicate suggestion' },
  evidence_useful: { key: 'admin.agent_feedback.label_evidence_useful', fallback: 'Evidence useful' },
  evidence_weak: { key: 'admin.agent_feedback.label_evidence_weak', fallback: 'Evidence weak' },
  good_but_needs_human_draft: { key: 'admin.agent_feedback.label_good_but_needs_human_draft', fallback: 'Needs human draft' },
  missing_context: { key: 'admin.agent_feedback.label_missing_context', fallback: 'Missing context' },
  not_relevant_to_site: { key: 'admin.agent_feedback.label_not_relevant_to_site', fallback: 'Not relevant' },
  operator_confidence_high: { key: 'admin.agent_feedback.label_operator_confidence_high', fallback: 'High confidence' },
  operator_confidence_low: { key: 'admin.agent_feedback.label_operator_confidence_low', fallback: 'Low confidence' },
  source_or_license_risk: { key: 'admin.agent_feedback.label_source_or_license_risk', fallback: 'Source/license risk' },
  too_generic: { key: 'admin.agent_feedback.label_too_generic', fallback: 'Too generic' },
  unsafe_or_overreaching: { key: 'admin.agent_feedback.label_unsafe_or_overreaching', fallback: 'Unsafe or overreaching' },
  visual_quality_low: { key: 'admin.agent_feedback.label_visual_quality_low', fallback: 'Visual quality low' },
  wrong_intent: { key: 'admin.agent_feedback.label_wrong_intent', fallback: 'Wrong intent' },
  wrong_next_step: { key: 'admin.agent_feedback.label_wrong_next_step', fallback: 'Wrong next step' },
  wrong_priority: { key: 'admin.agent_feedback.label_wrong_priority', fallback: 'Wrong priority' },
};

const LOW_QUALITY_LABELS = new Set([
  'duplicate_suggestion',
  'evidence_weak',
  'missing_context',
  'not_relevant_to_site',
  'operator_confidence_low',
  'source_or_license_risk',
  'too_generic',
  'unsafe_or_overreaching',
  'visual_quality_low',
  'wrong_intent',
  'wrong_next_step',
]);

function countMap(value: unknown): CountMap {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, count]) => [key, Number(count || 0)])
  );
}

function normalizeAgentFeedbackSummary(raw: any): AgentFeedbackSummary {
  const rates = raw?.rates ?? {};
  const boundary = raw?.boundary ?? {};
  return {
    artifactType: String(raw?.artifact_type ?? ''),
    contractVersion: String(raw?.contract_version ?? ''),
    scope: String(raw?.scope ?? ''),
    siteId: String(raw?.site_id ?? ''),
    windowHours: Number(raw?.window_hours ?? 24),
    generatedAt: String(raw?.generated_at ?? ''),
    windowStartAt: String(raw?.window_start_at ?? ''),
    lastEventAt: String(raw?.last_event_at ?? ''),
    eventsTotal: Number(raw?.events_total ?? 0),
    limited: Boolean(raw?.limited),
    maxEvents: Number(raw?.max_events ?? 0),
    outcomes: countMap(raw?.outcomes),
    labels: countMap(raw?.labels),
    sourceRuntimes: countMap(raw?.source_runtimes),
    localSurfaces: countMap(raw?.local_surfaces),
    scenarios: Array.isArray(raw?.scenarios)
      ? raw.scenarios.map((item: any) => ({
          localSurface: String(item?.local_surface ?? ''),
          sourceRuntime: String(item?.source_runtime ?? ''),
          eventsTotal: Number(item?.events_total ?? 0),
          outcomes: countMap(item?.outcomes),
          labels: countMap(item?.labels),
          acceptedRate: Number(item?.accepted_rate ?? 0),
          evidenceWeakRate: Number(item?.evidence_weak_rate ?? 0),
          wrongNextStepRate: Number(item?.wrong_next_step_rate ?? 0),
        }))
      : [],
    qualityTrend: Array.isArray(raw?.quality_trend)
      ? raw.quality_trend.map((item: any) => ({
          bucket: String(item?.bucket ?? ''),
          eventsTotal: Number(item?.events_total ?? 0),
          accepted: Number(item?.accepted ?? 0),
          rejected: Number(item?.rejected ?? 0),
          evidenceWeak: Number(item?.evidence_weak ?? 0),
          wrongNextStep: Number(item?.wrong_next_step ?? 0),
        }))
      : [],
    lowQualityLabels: Array.isArray(raw?.low_quality_labels)
      ? raw.low_quality_labels.map((item: any) => ({
          label: String(item?.label ?? ''),
          count: Number(item?.count ?? 0),
        }))
      : [],
    rejectionReasons: Array.isArray(raw?.rejection_reasons)
      ? raw.rejection_reasons.map((item: any) => ({
          label: String(item?.label ?? ''),
          count: Number(item?.count ?? 0),
        }))
      : [],
    rates: {
      acceptedRate: Number(rates.accepted_rate ?? 0),
      evidenceUsefulRate: Number(rates.evidence_useful_rate ?? 0),
      evidenceWeakRate: Number(rates.evidence_weak_rate ?? 0),
      wrongNextStepRate: Number(rates.wrong_next_step_rate ?? 0),
    },
    readOnly: Boolean(raw?.read_only),
    productionMutation: Boolean(raw?.production_mutation),
    approvalTruth: String(raw?.approval_truth ?? ''),
    preflightTruth: String(raw?.preflight_truth ?? ''),
    finalWriteTruth: String(raw?.final_write_truth ?? ''),
    boundary: {
      productionMutation: Boolean(boundary.production_mutation),
      approvalTruth: String(boundary.approval_truth ?? ''),
      preflightTruth: String(boundary.preflight_truth ?? ''),
      finalWriteTruth: String(boundary.final_write_truth ?? ''),
      controlPlane: String(boundary.control_plane ?? ''),
    },
  };
}

function formatPercent(value: number): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function labelText(t: TranslationFn, label: string): string {
  const copy = LABEL_FALLBACKS[label];
  return copy ? t(copy.key, {}, copy.fallback) : label.replaceAll('_', ' ');
}

function labelTone(label: string): BackofficeTagTone {
  if (label === 'evidence_useful' || label === 'operator_confidence_high') {
    return 'success';
  }
  if (LOW_QUALITY_LABELS.has(label)) {
    return 'warning';
  }
  return 'neutral';
}

function sortedCounts(counts: CountMap): FeedbackTopCount[] {
  return Object.entries(counts)
    .filter(([, count]) => Number(count || 0) > 0)
    .sort(([leftLabel, leftCount], [rightLabel, rightCount]) => {
      if (rightCount !== leftCount) return rightCount - leftCount;
      return leftLabel.localeCompare(rightLabel);
    })
    .map(([label, count]) => ({ label, count }));
}

function trendBucketLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');
  return `${month}/${day} ${hour}:00`;
}

function metricWindowDetail(t: TranslationFn, data: AgentFeedbackSummary): string {
  if (data.limited) {
    return t(
      'admin.agent_feedback.limited_detail',
      { count: formatNumber(data.maxEvents) },
      'Limited to {{count}} events'
    );
  }
  return t(
    'admin.agent_feedback.window_detail',
    { hours: formatNumber(data.windowHours) },
    '{{hours}}h window'
  );
}

function normalizeFeedbackWindow(value: string | null): number {
  return Number(value) === 168 ? 168 : 24;
}

function AgentFeedbackQualityDashboard() {
  const { t } = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const windowHours = normalizeFeedbackWindow(searchParams.get('window'));
  const siteIdFilter = searchParams.get('site') || '';
  const focusedLabel = searchParams.get('focus') || '';
  const [data, setData] = useState<AgentFeedbackSummary | null>(null);
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
      const response = await agentFeedbackClient.request<unknown>(`/api/admin/agent-feedback?${params.toString()}`, {
        signal: controller.signal,
      });
      if (sequence === requestSequenceRef.current) {
        setData(normalizeAgentFeedbackSummary(response.data));
        hasLoadedRef.current = true;
      }
    } catch (err) {
      if (sequence === requestSequenceRef.current) {
        setError(resolveUiErrorMessage(err, t('admin.agent_feedback.load_error', {}, 'Failed to load Agent feedback diagnostics.')));
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

  const labelCounts = useMemo(() => sortedCounts(data?.labels || {}), [data]);
  const runtimeCounts = useMemo(() => sortedCounts(data?.sourceRuntimes || {}), [data]);
  const surfaceCounts = useMemo(() => sortedCounts(data?.localSurfaces || {}), [data]);
  const qualityIssues = useMemo(() => {
    if (data?.lowQualityLabels.length) return data.lowQualityLabels;
    return labelCounts.filter((item) => LOW_QUALITY_LABELS.has(item.label));
  }, [data, labelCounts]);
  const selectedQualityIssue = qualityIssues.find((item) => item.label === focusedLabel)
    || qualityIssues[0]
    || null;
  const isEmpty = data !== null && data.eventsTotal === 0;

  if (loading && !data) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficeLayer
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.agent_feedback.title', {}, 'Agent Feedback Quality')}
        description={t(
          'admin.agent_feedback.desc',
          {},
          'Read-only quality signals from local operator feedback. Cloud summarizes feedback for evaluation; WordPress approval, preflight, and final writes stay local.'
        )}
        aside={data ? <BackofficeStatusBadge status="read_only" label={t('admin.read_only', {}, 'Read-only')} /> : undefined}
        actions={<button type="button" onClick={() => void loadData(true)} disabled={loading} className="btn btn-secondary btn-sm">{t('common.refresh', {}, 'Refresh')}</button>}
      />

      <BackofficeSectionPanel className="p-4 md:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
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
          <input
            type="text"
            value={siteIdInput}
            aria-label={t('admin.agent_feedback.site_filter_label', {}, 'Filter by site ID')}
            onChange={(event) => setSiteIdInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                updateUrl({ site: siteIdInput.trim() || null, focus: null });
              }
            }}
            placeholder={t('admin.agent_feedback.site_filter', {}, 'Site ID')}
            className="input h-9 min-w-0 sm:w-56"
          />
          <button
            type="button"
            onClick={() => updateUrl({ site: siteIdInput.trim() || null, focus: null })}
            className="btn btn-secondary btn-sm"
          >
            {t('admin.agent_feedback.filter_action', {}, 'Filter')}
          </button>
          {siteIdFilter ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setSiteIdInput(''); updateUrl({ site: null, focus: null }); }}>{t('common.clear_filters', {}, 'Clear filters')}</button> : null}
        </div>
        {data ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <BackofficeStatusBadge
              status="inactive"
              label={
                data.productionMutation
                  ? t('admin.agent_feedback.mutation_enabled', {}, 'Mutation enabled')
                  : t('admin.agent_feedback.no_mutation', {}, 'No mutation')
              }
            />
            <BackofficeTag tone="neutral">{data.scope || 'all_sites'}</BackofficeTag>
            {data.siteId ? <BackofficeIdentifier value={data.siteId} /> : null}
            {data.generatedAt ? <span>{t('common.updated_at', {}, 'Updated')}: {formatDate(data.generatedAt)}</span> : null}
            {data.lastEventAt ? <span>{t('admin.agent_feedback.last_event', {}, 'Last feedback')}: {formatDate(data.lastEventAt)}</span> : null}
          </div>
        ) : null}
      </BackofficeSectionPanel>

      {data ? <BackofficeSummaryStrip items={[
        { label: t('admin.agent_feedback.events', {}, 'Events'), value: formatNumber(data.eventsTotal), detail: metricWindowDetail(t, data) },
        { label: t('admin.agent_feedback.accepted_rate', {}, 'Accepted'), value: formatPercent(data.rates.acceptedRate), toneClassName: data.rates.acceptedRate < 0.5 && data.eventsTotal > 0 ? 'text-amber-600 dark:text-amber-400' : undefined },
        { label: t('admin.agent_feedback.evidence_weak', {}, 'Evidence weak'), value: formatPercent(data.rates.evidenceWeakRate), toneClassName: data.rates.evidenceWeakRate > 0.2 ? 'text-amber-600 dark:text-amber-400' : undefined },
        { label: t('admin.agent_feedback.wrong_next_step', {}, 'Wrong next step'), value: formatPercent(data.rates.wrongNextStepRate), toneClassName: data.rates.wrongNextStepRate > 0 ? 'text-rose-600 dark:text-rose-400' : undefined },
        { label: t('admin.agent_feedback.quality_issues', {}, 'Quality issues'), value: formatNumber(qualityIssues.reduce((total, item) => total + item.count, 0)), toneClassName: qualityIssues.length ? 'text-rose-600 dark:text-rose-400' : undefined },
      ]} /> : null}

      {error ? <BackofficeDiagnosticNotice message={error} staleDescription={data ? t('admin.agent_feedback.stale_notice', {}, 'The last successfully loaded feedback snapshot remains visible.') : undefined} retryLabel={t('common.retry')} onRetry={() => void loadData(true)} /> : null}

      {isEmpty ? (
        <BackofficeEmptyState
          title={t('admin.agent_feedback.empty_title', {}, 'No feedback in this window')}
          description={t(
            'admin.agent_feedback.empty_desc',
            {},
            'Feedback quality metrics will appear after local operator surfaces submit metadata-only feedback events.'
          )}
        />
      ) : data ? (
        <>
          <BackofficeSectionPanel className="overflow-hidden p-0 md:p-0">
            <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800 md:px-6"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('admin.agent_feedback.attention_label', {}, 'Attention')}</p><h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">{t('admin.agent_feedback.issue_queue_title', {}, 'Quality issue queue')}</h2><p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('admin.agent_feedback.issue_queue_desc', {}, 'Select a low-quality feedback label to inspect its volume, rate, scope, and governance boundary.')}</p></div>
            <div className={qualityIssues.length ? 'grid xl:grid-cols-[minmax(0,1fr)_22rem]' : ''}>
              <div className="max-h-[32rem] divide-y divide-slate-200 overflow-y-auto dark:divide-slate-800">
                {qualityIssues.map((item) => { const selected = selectedQualityIssue?.label === item.label; return <button key={item.label} type="button" data-ui="feedback-quality-item" aria-pressed={selected} aria-controls="feedback-quality-inspector" className={`grid w-full cursor-pointer gap-3 px-5 py-4 text-left transition hover:bg-slate-50 dark:hover:bg-slate-900/45 md:grid-cols-[minmax(0,1fr)_8rem] md:items-center md:px-6 ${selected ? 'bg-blue-50/65 dark:bg-blue-950/20' : ''}`} onClick={() => updateUrl({ focus: item.label })}><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><BackofficeTag tone={labelTone(item.label)}>{labelText(t, item.label)}</BackofficeTag><span className="font-mono text-xs text-slate-500 dark:text-slate-400">{item.label}</span></div></div><div className="text-sm font-semibold text-slate-700 md:text-right dark:text-slate-200">{formatNumber(item.count)}</div></button>; })}
                {qualityIssues.length ? null : <BackofficeEmptyState className="m-5 md:m-6" title={t('admin.agent_feedback.no_quality_issues', {}, 'No quality issues in this window.')} description={t('admin.agent_feedback.no_quality_issues_desc', {}, 'The selected scope has no low-quality feedback labels that require evidence review.')} />}
              </div>
              {qualityIssues.length ? <div id="feedback-quality-inspector" className="border-t border-slate-200 p-5 dark:border-slate-800 xl:border-l xl:border-t-0 xl:p-6">
                {selectedQualityIssue ? <div className="space-y-5"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('admin.agent_feedback.selected_issue', {}, 'Selected issue')}</p><h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{labelText(t, selectedQualityIssue.label)}</h3><p className="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">{selectedQualityIssue.label}</p></div><dl className="grid gap-3 text-sm"><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.agent_feedback.events', {}, 'Events')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{formatNumber(selectedQualityIssue.count)}</dd></div><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.agent_feedback.issue_rate', {}, 'Share of feedback')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{formatPercent(data.eventsTotal ? selectedQualityIssue.count / data.eventsTotal : 0)}</dd></div><div><dt className="text-xs text-slate-500 dark:text-slate-400">{t('admin.agent_feedback.issue_scope', {}, 'Current scope')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{siteIdFilter || t('admin.agent_feedback.all_sites', {}, 'All sites')} · {windowHours}h</dd></div></dl><p className="rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-500 dark:bg-slate-900/45 dark:text-slate-400">{t('admin.agent_feedback.issue_boundary', {}, 'Cloud summarizes this metadata for evaluation only. Approval, preflight, and final writes remain local to WordPress.')}</p></div> : null}
              </div> : null}
            </div>
          </BackofficeSectionPanel>

          <BackofficeSectionPanel className="overflow-hidden p-0">
            <div className="border-b border-slate-200/80 px-5 py-4 dark:border-slate-800 md:px-6">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('admin.agent_feedback.scenarios_label', {}, 'Scenarios')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('admin.agent_feedback.scenarios_title', {}, 'Runtime and surface quality')}
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200/80 text-sm dark:divide-slate-800">
                <thead className="bg-slate-50/80 text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-950/30 dark:text-slate-400">
                  <tr>
                    <th className="px-5 py-3 text-left font-semibold">{t('admin.agent_feedback.runtime', {}, 'Runtime')}</th>
                    <th className="px-5 py-3 text-left font-semibold">{t('admin.agent_feedback.surface', {}, 'Surface')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.agent_feedback.events', {}, 'Events')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.agent_feedback.accepted_rate', {}, 'Accepted')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.agent_feedback.evidence_weak', {}, 'Evidence weak')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.agent_feedback.wrong_next_step_short', {}, 'Wrong step')}</th>
                    <th className="px-5 py-3 text-right font-semibold">{t('admin.agent_feedback.top_labels', {}, 'Top labels')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200/80 dark:divide-slate-800">
                  {data.scenarios.map((scenario) => (
                    <tr key={`${scenario.sourceRuntime}:${scenario.localSurface}`} className="bg-white/55 dark:bg-slate-950/20">
                      <td className="px-5 py-3">
                        <BackofficeIdentifier value={scenario.sourceRuntime || t('common.unknown')} />
                      </td>
                      <td className="px-5 py-3">
                        <BackofficeIdentifier value={scenario.localSurface || t('common.unknown')} />
                      </td>
                      <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                        {formatNumber(scenario.eventsTotal)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <BackofficeTag tone={scenario.acceptedRate >= 0.5 ? 'success' : 'warning'}>
                          {formatPercent(scenario.acceptedRate)}
                        </BackofficeTag>
                      </td>
                      <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                        {formatPercent(scenario.evidenceWeakRate)}
                      </td>
                      <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                        {formatPercent(scenario.wrongNextStepRate)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <div className="flex flex-wrap justify-end gap-1.5">
                          {sortedCounts(scenario.labels).slice(0, 3).map((item) => (
                            <BackofficeTag key={item.label} tone={labelTone(item.label)}>
                              {labelText(t, item.label)} · {formatNumber(item.count)}
                            </BackofficeTag>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </BackofficeSectionPanel>

          <div className="grid gap-5 xl:grid-cols-3">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.agent_feedback.labels_label', {}, 'Labels')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.agent_feedback.labels_title', {}, 'Feedback label mix')}
                </h2>
              </div>
              <div className="space-y-2">
                {labelCounts.map((item) => (
                  <BackofficeStackCard key={item.label} className="flex items-center justify-between gap-3">
                    <BackofficeTag tone={labelTone(item.label)}>{labelText(t, item.label)}</BackofficeTag>
                    <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{formatNumber(item.count)}</span>
                  </BackofficeStackCard>
                ))}
              </div>
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.agent_feedback.sources_label', {}, 'Sources')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.agent_feedback.sources_title', {}, 'Runtime and surface counts')}
                </h2>
              </div>
              <div className="space-y-3">
                <div className="space-y-2">
                  {runtimeCounts.map((item) => (
                    <BackofficeStackCard key={`runtime:${item.label}`} className="flex items-center justify-between gap-3">
                      <BackofficeIdentifier value={item.label} />
                      <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{formatNumber(item.count)}</span>
                    </BackofficeStackCard>
                  ))}
                </div>
                <div className="space-y-2">
                  {surfaceCounts.map((item) => (
                    <BackofficeStackCard key={`surface:${item.label}`} className="flex items-center justify-between gap-3">
                      <BackofficeIdentifier value={item.label} />
                      <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">{formatNumber(item.count)}</span>
                    </BackofficeStackCard>
                  ))}
                </div>
              </div>
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.agent_feedback.trend_label', {}, 'Trend')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.agent_feedback.trend_title', {}, 'Hourly buckets')}
                </h2>
              </div>
              <div className="space-y-2">
                {data.qualityTrend.slice(-8).map((point) => (
                  <BackofficeStackCard key={point.bucket}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-semibold text-slate-950 dark:text-white">{trendBucketLabel(point.bucket)}</span>
                      <span className="text-sm text-slate-600 dark:text-slate-300">
                        {t(
                          'admin.agent_feedback.trend_events',
                          { count: formatNumber(point.eventsTotal) },
                          '{{count}} events'
                        )}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-500 dark:text-slate-400 sm:grid-cols-4">
                      <span>
                        {t('admin.agent_feedback.trend_accepted', { count: formatNumber(point.accepted) }, 'Accepted {{count}}')}
                      </span>
                      <span>
                        {t('admin.agent_feedback.trend_rejected', { count: formatNumber(point.rejected) }, 'Rejected {{count}}')}
                      </span>
                      <span>
                        {t('admin.agent_feedback.trend_evidence', { count: formatNumber(point.evidenceWeak) }, 'Evidence {{count}}')}
                      </span>
                      <span>
                        {t('admin.agent_feedback.trend_wrong_step', { count: formatNumber(point.wrongNextStep) }, 'Wrong step {{count}}')}
                      </span>
                    </div>
                  </BackofficeStackCard>
                ))}
              </div>
            </BackofficeSectionPanel>
          </div>
        </>
      ) : null}

      {data ? <BackofficeDisclosure summary={t('admin.agent_feedback.advanced_boundary', {}, 'Advanced contract and governance boundary')} contentClassName="space-y-4"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('admin.agent_feedback.boundary_label', {}, 'Boundary')}</p><h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">{t('admin.agent_feedback.boundary_title', {}, 'Quality detail only')}</h2><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">{t('admin.agent_feedback.boundary_desc', {}, 'This surface summarizes metadata-only feedback. It does not configure prompts, router profiles, approvals, publication, or WordPress writes.')}</p></div><BackofficeMetricStrip columnsClassName="md:grid-cols-2 xl:grid-cols-5" items={[
        { label: t('admin.agent_feedback.contract', {}, 'Contract'), value: data.contractVersion || data.artifactType, size: 'compact' },
        { label: t('admin.agent_feedback.control_plane', {}, 'Control plane'), value: data.boundary.controlPlane || 'wordpress_local', size: 'compact' },
        { label: t('admin.agent_feedback.approval', {}, 'Approval'), value: data.approvalTruth || data.boundary.approvalTruth, size: 'compact' },
        { label: t('admin.agent_feedback.preflight', {}, 'Preflight'), value: data.preflightTruth || data.boundary.preflightTruth, size: 'compact' },
        { label: t('admin.agent_feedback.final_write', {}, 'Final write'), value: data.finalWriteTruth || data.boundary.finalWriteTruth, size: 'compact' },
      ]} /></BackofficeDisclosure> : null}
    </BackofficePageStack>
  );
}

export default function AdminAgentFeedbackPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AgentFeedbackQualityDashboard />
    </Suspense>
  );
}
