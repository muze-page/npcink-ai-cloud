'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { BackofficeEmptyState, BackofficeMetricStrip, BackofficePageStack, BackofficePrimaryPanel, BackofficeSectionPanel, BackofficeStackCard } from '@/components/backoffice/BackofficeScaffold';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag, type BackofficeTagTone } from '@/components/backoffice/BackofficeTag';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber } from '@/lib/utils';

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

function AgentFeedbackQualityDashboard() {
  const { t } = useLocale();
  const [data, setData] = useState<AgentFeedbackSummary | null>(null);
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
      const response = await fetch(`/api/admin/agent-feedback?${params.toString()}`, {
        credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok || payload?.status === 'error') {
        throw payload;
      }
      setData(normalizeAgentFeedbackSummary(payload?.data ?? {}));
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

  const labelCounts = useMemo(() => sortedCounts(data?.labels || {}), [data]);
  const runtimeCounts = useMemo(() => sortedCounts(data?.sourceRuntimes || {}), [data]);
  const surfaceCounts = useMemo(() => sortedCounts(data?.localSurfaces || {}), [data]);
  const isEmpty = data !== null && data.eventsTotal === 0;

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
        title={t('admin.agent_feedback.title', {}, 'Agent Feedback Quality')}
        description={t(
          'admin.agent_feedback.desc',
          {},
          'Read-only quality signals from local operator feedback. Cloud summarizes feedback for evaluation; WordPress approval, preflight, and final writes stay local.'
        )}
        aside={data ? (
          <div className="w-full xl:w-[44rem]">
            <BackofficeMetricStrip
              columnsClassName="md:grid-cols-2 xl:grid-cols-4"
              items={[
                {
                  label: t('admin.agent_feedback.events', {}, 'Events'),
                  value: formatNumber(data.eventsTotal),
                  detail: metricWindowDetail(t, data),
                },
                {
                  label: t('admin.agent_feedback.accepted_rate', {}, 'Accepted'),
                  value: formatPercent(data.rates.acceptedRate),
                  toneClassName: data.rates.acceptedRate < 0.5 && data.eventsTotal > 0 ? 'text-amber-600 dark:text-amber-400' : undefined,
                },
                {
                  label: t('admin.agent_feedback.evidence_weak', {}, 'Evidence weak'),
                  value: formatPercent(data.rates.evidenceWeakRate),
                  toneClassName: data.rates.evidenceWeakRate > 0.2 ? 'text-amber-600 dark:text-amber-400' : undefined,
                },
                {
                  label: t('admin.agent_feedback.wrong_next_step', {}, 'Wrong next step'),
                  value: formatPercent(data.rates.wrongNextStepRate),
                  toneClassName: data.rates.wrongNextStepRate > 0 ? 'text-rose-600 dark:text-rose-400' : undefined,
                },
              ]}
            />
          </div>
        ) : undefined}
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
          <input
            type="text"
            value={siteIdInput}
            onChange={(event) => setSiteIdInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                setSiteIdFilter(siteIdInput.trim());
              }
            }}
            placeholder={t('admin.agent_feedback.site_filter', {}, 'Site ID')}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:placeholder:text-slate-500"
          />
          <button
            type="button"
            onClick={() => setSiteIdFilter(siteIdInput.trim())}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white"
          >
            {t('admin.agent_feedback.filter_action', {}, 'Filter')}
          </button>
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={loading}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white"
          >
            {t('common.refresh', {}, 'Refresh')}
          </button>
        </div>
        {data ? (
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <BackofficeStatusBadge status="read_only" label={t('admin.read_only', {}, 'Read-only')} />
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
      </BackofficePrimaryPanel>

      {data ? (
        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.agent_feedback.boundary_label', {}, 'Boundary')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.agent_feedback.boundary_title', {}, 'Quality detail only')}
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t(
                'admin.agent_feedback.boundary_desc',
                {},
                'This surface summarizes metadata-only feedback. It does not configure prompts, router profiles, approvals, publication, or WordPress writes.'
              )}
            </p>
          </div>
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-2 xl:grid-cols-5"
            items={[
              {
                label: t('admin.agent_feedback.contract', {}, 'Contract'),
                value: data.contractVersion || data.artifactType,
                size: 'compact',
              },
              {
                label: t('admin.agent_feedback.control_plane', {}, 'Control plane'),
                value: data.boundary.controlPlane || 'wordpress_local',
                size: 'compact',
              },
              {
                label: t('admin.agent_feedback.approval', {}, 'Approval'),
                value: data.approvalTruth || data.boundary.approvalTruth,
                size: 'compact',
              },
              {
                label: t('admin.agent_feedback.preflight', {}, 'Preflight'),
                value: data.preflightTruth || data.boundary.preflightTruth,
                size: 'compact',
              },
              {
                label: t('admin.agent_feedback.final_write', {}, 'Final write'),
                value: data.finalWriteTruth || data.boundary.finalWriteTruth,
                size: 'compact',
              },
            ]}
          />
        </BackofficeSectionPanel>
      ) : null}

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
                    <div className="mt-2 grid grid-cols-4 gap-2 text-xs text-slate-500 dark:text-slate-400">
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
