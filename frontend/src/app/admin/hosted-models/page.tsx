'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import {
  BackofficeEmptyState,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber } from '@/lib/utils';

type GovernanceGroup = {
  groupKind: string;
  groupId: string;
  runsTotal: number;
  succeeded: number;
  failed: number;
  queued: number;
  running: number;
  canceled: number;
  providerCalls: number;
  providerErrors: number;
  tokensIn: number;
  tokensOut: number;
  tokensTotal: number;
  cost: number;
  meterEvents: number;
  meterTotals: Record<string, number>;
  avgLatencyMs: number;
  providerErrorRate: number;
  providerCallRunCoverageRate: number;
  meteredRunCoverageRate: number;
  profileIds: string[];
  executionKinds: string[];
  providerIds: string[];
  modelIds: string[];
  dataClassifications: string[];
};

type HostedModelGovernanceData = {
  generatedAt: string;
  filters: { siteId: string; recentMinutes: number; limit: number };
  totals: {
    runs: number;
    providerCalls: number;
    usageMeterEvents: number;
    providerCallRunCoverageRate: number;
    meteredRunCoverageRate: number;
  };
  capabilityGroups: GovernanceGroup[];
  profileGroups: GovernanceGroup[];
  executionKindGroups: GovernanceGroup[];
  providerModelGroups: GovernanceGroup[];
  governanceGaps: {
    unmeteredCapabilities: string[];
    missingProviderCallCapabilities: string[];
    unmeteredRunCount: number;
    runsWithoutProviderCallCount: number;
    reviewGuidance: string;
  };
  boundary: {
    surface: string;
    cloudRole: string;
    localControlPlane: string;
    directWordpressWrite: boolean;
    containsPromptOrResultPayloads: boolean;
  };
  alertSummary: {
    status: string;
    summary: string;
    nextAction: string;
    alertCount: number;
    alerts: Array<{
      code: string;
      severity: string;
      title: string;
      summary: string;
      count: number;
      capabilities: string[];
      suggestedAction: string;
    }>;
  };
};

type HostedModelGovernanceCadence = {
  available: boolean;
  source: string;
  generatedAt: string;
  filters: { recentMinutes: number };
  delivery: { owner: string; bufferKind: string; scopeKind: string };
  rollup: { siteScope: string; scopeKind: string; scopeId: string; generatedAt: string };
  alertSummary: HostedModelGovernanceData['alertSummary'] & {
    dailyDigest: {
      runs: number;
      providerCalls: number;
      meterEvents: number;
      meteredRunCoverageRate: number;
      providerCallRunCoverageRate: number;
      unmeteredRunCount: number;
      runsWithoutProviderCallCount: number;
    };
  };
};

type Translate = (key: string, params?: Record<string, string>, fallback?: string) => string;

const HOSTED_TEXT_KEYS: Record<string, string> = {
  'Hosted model governance has telemetry gaps to review before traffic expands.':
    'admin.hosted_models.text.telemetry_gaps',
  'Hosted model governance has coverage or provider errors that need review.':
    'admin.hosted_models.text.coverage_or_provider_errors',
  'Hosted model governance is covered in this window.':
    'admin.hosted_models.text.covered_window',
  'No hosted model runs were observed in this governance window.':
    'admin.hosted_models.text.no_runs_window',
  'Hosted model provider call coverage gap':
    'admin.hosted_models.text.provider_call_gap_title',
  'Hosted model meter coverage gap':
    'admin.hosted_models.text.meter_gap_title',
  'Hosted model provider errors':
    'admin.hosted_models.text.provider_errors_title',
  'Hosted model failed runs':
    'admin.hosted_models.text.failed_runs_title',
  'Some hosted runs do not have matching provider call telemetry.':
    'admin.hosted_models.text.provider_call_gap_summary',
  'Some hosted model runs are not represented in usage metering.':
    'admin.hosted_models.text.meter_gap_summary',
  'Provider calls are returning errors in the current governance window.':
    'admin.hosted_models.text.provider_errors_summary',
  'Hosted model runs are failing before or during provider execution.':
    'admin.hosted_models.text.failed_runs_summary',
  'Review hosted model families before promoting new providers.':
    'admin.hosted_models.text.review_guidance',
  continue_monitoring: 'admin.hosted_models.action.continue_monitoring',
  inspect_provider_call_recording_for_hosted_profiles:
    'admin.hosted_models.action.inspect_provider_call_recording',
  inspect_metering_callback_or_usage_event_mapping:
    'admin.hosted_models.action.inspect_metering_mapping',
  inspect_provider_credentials_quota_and_health:
    'admin.hosted_models.action.inspect_provider_health',
  inspect_runtime_failure_detail_for_hosted_models:
    'admin.hosted_models.action.inspect_runtime_failure',
  inspect_hosted_models: 'admin.hosted_models.action.inspect_hosted_models',
  internal_admin_readonly: 'admin.hosted_models.value.internal_admin_readonly',
  usage_rollup: 'admin.hosted_models.value.usage_rollup',
  internal_admin: 'admin.hosted_models.value.internal_admin',
  internal_admin_summary: 'admin.hosted_models.value.internal_admin_summary',
  hosted_runtime_detail: 'admin.hosted_models.value.hosted_runtime_detail',
  wordpress_plugin: 'admin.hosted_models.value.wordpress_plugin',
  runtime: 'admin.hosted_models.value.runtime',
  internal: 'admin.hosted_models.value.internal',
};

const WINDOW_OPTIONS = [
  { label: '1h', value: 60 },
  { label: '24h', value: 1440 },
  { label: '7d', value: 10080 },
];

function asNumber(value: unknown): number {
  return Number(value ?? 0) || 0;
}

function normalizeGroup(raw: any): GovernanceGroup {
  return {
    groupKind: String(raw?.group_kind ?? ''),
    groupId: String(raw?.group_id ?? ''),
    runsTotal: asNumber(raw?.runs_total),
    succeeded: asNumber(raw?.succeeded),
    failed: asNumber(raw?.failed),
    queued: asNumber(raw?.queued),
    running: asNumber(raw?.running),
    canceled: asNumber(raw?.canceled),
    providerCalls: asNumber(raw?.provider_calls),
    providerErrors: asNumber(raw?.provider_errors),
    tokensIn: asNumber(raw?.tokens_in),
    tokensOut: asNumber(raw?.tokens_out),
    tokensTotal: asNumber(raw?.tokens_total),
    cost: asNumber(raw?.cost),
    meterEvents: asNumber(raw?.meter_events),
    meterTotals: raw?.meter_totals ?? {},
    avgLatencyMs: asNumber(raw?.avg_latency_ms),
    providerErrorRate: asNumber(raw?.provider_error_rate),
    providerCallRunCoverageRate: asNumber(raw?.provider_call_run_coverage_rate),
    meteredRunCoverageRate: asNumber(raw?.metered_run_coverage_rate),
    profileIds: Array.isArray(raw?.profile_ids) ? raw.profile_ids.map(String) : [],
    executionKinds: Array.isArray(raw?.execution_kinds) ? raw.execution_kinds.map(String) : [],
    providerIds: Array.isArray(raw?.provider_ids) ? raw.provider_ids.map(String) : [],
    modelIds: Array.isArray(raw?.model_ids) ? raw.model_ids.map(String) : [],
    dataClassifications: Array.isArray(raw?.data_classifications)
      ? raw.data_classifications.map(String)
      : [],
  };
}

function normalizeHostedModelGovernance(raw: any): HostedModelGovernanceData {
  const totals = raw?.totals ?? {};
  const filters = raw?.filters ?? {};
  const gaps = raw?.governance_gaps ?? {};
  const boundary = raw?.boundary ?? {};
  const alertSummary = raw?.alert_summary ?? {};
  return {
    generatedAt: String(raw?.generated_at ?? ''),
    filters: {
      siteId: String(filters.site_id ?? ''),
      recentMinutes: asNumber(filters.recent_minutes),
      limit: asNumber(filters.limit),
    },
    totals: {
      runs: asNumber(totals.runs),
      providerCalls: asNumber(totals.provider_calls),
      usageMeterEvents: asNumber(totals.usage_meter_events),
      providerCallRunCoverageRate: asNumber(totals.provider_call_run_coverage_rate),
      meteredRunCoverageRate: asNumber(totals.metered_run_coverage_rate),
    },
    capabilityGroups: Array.isArray(raw?.capability_groups)
      ? raw.capability_groups.map(normalizeGroup)
      : [],
    profileGroups: Array.isArray(raw?.profile_groups)
      ? raw.profile_groups.map(normalizeGroup)
      : [],
    executionKindGroups: Array.isArray(raw?.execution_kind_groups)
      ? raw.execution_kind_groups.map(normalizeGroup)
      : [],
    providerModelGroups: Array.isArray(raw?.provider_model_groups)
      ? raw.provider_model_groups.map(normalizeGroup)
      : [],
    governanceGaps: {
      unmeteredCapabilities: Array.isArray(gaps.unmetered_capabilities)
        ? gaps.unmetered_capabilities.map(String)
        : [],
      missingProviderCallCapabilities: Array.isArray(gaps.missing_provider_call_capabilities)
        ? gaps.missing_provider_call_capabilities.map(String)
        : [],
      unmeteredRunCount: asNumber(gaps.unmetered_run_count),
      runsWithoutProviderCallCount: asNumber(gaps.runs_without_provider_call_count),
      reviewGuidance: String(gaps.review_guidance ?? ''),
    },
    boundary: {
      surface: String(boundary.surface ?? ''),
      cloudRole: String(boundary.cloud_role ?? ''),
      localControlPlane: String(boundary.local_control_plane ?? ''),
      directWordpressWrite: Boolean(boundary.direct_wordpress_write),
      containsPromptOrResultPayloads: Boolean(boundary.contains_prompt_or_result_payloads),
    },
    alertSummary: {
      status: String(alertSummary.status ?? 'inactive'),
      summary: String(alertSummary.summary ?? ''),
      nextAction: String(alertSummary.next_action ?? ''),
      alertCount: asNumber(alertSummary.alert_count),
      alerts: Array.isArray(alertSummary.alerts)
        ? alertSummary.alerts.map((item: any) => ({
            code: String(item?.code ?? ''),
            severity: String(item?.severity ?? ''),
            title: String(item?.title ?? ''),
            summary: String(item?.summary ?? ''),
            count: asNumber(item?.count),
            capabilities: Array.isArray(item?.capabilities) ? item.capabilities.map(String) : [],
            suggestedAction: String(item?.suggested_action ?? ''),
          }))
        : [],
    },
  };
}

function normalizeHostedModelGovernanceCadence(raw: any): HostedModelGovernanceCadence {
  const filters = raw?.filters ?? {};
  const delivery = raw?.delivery ?? {};
  const rollup = raw?.rollup ?? {};
  const alertSummary = raw?.alert_summary ?? {};
  const dailyDigest = alertSummary?.daily_digest ?? {};
  return {
    available: Boolean(raw?.available ?? raw?.source === 'cloud_hosted_model_governance'),
    source: String(raw?.source ?? ''),
    generatedAt: String(raw?.generated_at ?? ''),
    filters: {
      recentMinutes: asNumber(filters.recent_minutes),
    },
    delivery: {
      owner: String(delivery.owner ?? ''),
      bufferKind: String(delivery.buffer_kind ?? ''),
      scopeKind: String(delivery.scope_kind ?? ''),
    },
    rollup: {
      siteScope: String(rollup.site_scope ?? ''),
      scopeKind: String(rollup.scope_kind ?? ''),
      scopeId: String(rollup.scope_id ?? ''),
      generatedAt: String(rollup.generated_at ?? ''),
    },
    alertSummary: {
      status: String(alertSummary.status ?? 'inactive'),
      summary: String(alertSummary.summary ?? ''),
      nextAction: String(alertSummary.next_action ?? ''),
      alertCount: asNumber(alertSummary.alert_count),
      alerts: Array.isArray(alertSummary.alerts)
        ? alertSummary.alerts.map((item: any) => ({
            code: String(item?.code ?? ''),
            severity: String(item?.severity ?? ''),
            title: String(item?.title ?? ''),
            summary: String(item?.summary ?? ''),
            count: asNumber(item?.count),
            capabilities: Array.isArray(item?.capabilities) ? item.capabilities.map(String) : [],
            suggestedAction: String(item?.suggested_action ?? ''),
          }))
        : [],
      dailyDigest: {
        runs: asNumber(dailyDigest.runs),
        providerCalls: asNumber(dailyDigest.provider_calls),
        meterEvents: asNumber(dailyDigest.meter_events),
        meteredRunCoverageRate: asNumber(dailyDigest.metered_run_coverage_rate),
        providerCallRunCoverageRate: asNumber(dailyDigest.provider_call_run_coverage_rate),
        unmeteredRunCount: asNumber(dailyDigest.unmetered_run_count),
        runsWithoutProviderCallCount: asNumber(dailyDigest.runs_without_provider_call_count),
      },
    },
  };
}

function formatPercent(value: number): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function formatCost(value: number): string {
  return `$${Number(value || 0).toFixed(4)}`;
}

function coverageStatus(value: number): string {
  if (value >= 1) return 'ok';
  if (value >= 0.9) return 'warning';
  return 'error';
}

function groupTone(group: GovernanceGroup): string {
  if (group.failed > 0 || group.providerErrorRate >= 0.1) return 'error';
  if (group.meteredRunCoverageRate < 1 || group.providerCallRunCoverageRate < 1) return 'warning';
  return 'ok';
}

function translateHostedText(t: Translate, value: string | undefined): string {
  const text = String(value || '').trim();
  if (!text) {
    return '';
  }
  const key = HOSTED_TEXT_KEYS[text];
  return key ? t(key, {}, text) : text;
}

function translateHostedStatus(t: Translate, value: string | undefined): string {
  const status = String(value || 'inactive');
  if (status === 'missing') {
    return t('admin.hosted_models.status_missing', {}, 'Missing');
  }
  if (status === 'covered') {
    return t('admin.hosted_models.status_covered', {}, 'Covered');
  }
  return t(`status.${status}`, {}, status);
}

function AdminHostedModelsContent() {
  const { t } = useLocale();
  const [data, setData] = useState<HostedModelGovernanceData | null>(null);
  const [cadence, setCadence] = useState<HostedModelGovernanceCadence | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [recentMinutes, setRecentMinutes] = useState(1440);
  const [siteIdInput, setSiteIdInput] = useState('');
  const [siteIdFilter, setSiteIdFilter] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      params.set('recent_minutes', String(recentMinutes));
      params.set('limit', '25');
      if (siteIdFilter.trim()) {
        params.set('site_id', siteIdFilter.trim());
      }
      const response = await fetch(`/api/admin/hosted-model-governance?${params.toString()}`, {
        credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok || payload?.status === 'error') {
        throw payload;
      }
      setData(normalizeHostedModelGovernance(payload?.data ?? {}));
      try {
        const cadenceResponse = await fetch(
          `/api/admin/hosted-model-governance-cadence?recent_minutes=${encodeURIComponent(String(recentMinutes))}`,
          { credentials: 'include' }
        );
        const cadencePayload = await cadenceResponse.json();
        if (cadenceResponse.ok && cadencePayload?.status !== 'error') {
          setCadence(normalizeHostedModelGovernanceCadence(cadencePayload?.data ?? {}));
        } else {
          setCadence(null);
        }
      } catch {
        setCadence(null);
      }
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
      setData(null);
      setCadence(null);
    } finally {
      setLoading(false);
    }
  }, [recentMinutes, siteIdFilter, t]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const governanceStatus = useMemo(() => {
    if (!data) return 'inactive';
    if (
      data.governanceGaps.unmeteredCapabilities.length > 0 ||
      data.governanceGaps.missingProviderCallCapabilities.length > 0
    ) {
      return 'warning';
    }
    return data.totals.runs > 0 ? 'ok' : 'inactive';
  }, [data]);

  const isEmpty = data !== null && data.totals.runs === 0;

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
        title={t('admin.hosted_models.title', {}, 'Hosted model runtime')}
        description={t(
          'admin.hosted_models.desc',
          {},
          'Read-only runtime posture for hosted model families. Start with alert status; open advanced detail only when you need metering, provider, or boundary evidence.'
        )}
        aside={
          data ? (
            <div className="w-full xl:w-[48rem]">
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-2 xl:grid-cols-5"
                items={[
                  {
                    label: t('common.status', {}, 'Status'),
                    value: translateHostedStatus(t, governanceStatus),
                    detail: translateHostedText(t, data.governanceGaps.reviewGuidance),
                    toneClassName:
                      governanceStatus === 'warning'
                        ? 'text-amber-600 dark:text-amber-400'
                        : governanceStatus === 'ok'
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : undefined,
                    size: 'compact',
                  },
                  {
                    label: t('admin.hosted_models.metric_runs', {}, 'Runs'),
                    value: formatNumber(data.totals.runs),
                    detail: t(
                      'admin.hosted_models.provider_calls_detail',
                      { count: formatNumber(data.totals.providerCalls) },
                      `${formatNumber(data.totals.providerCalls)} provider calls`
                    ),
                  },
                  {
                    label: t('admin.hosted_models.metric_meter_coverage', {}, 'Meter coverage'),
                    value: formatPercent(data.totals.meteredRunCoverageRate),
                    toneClassName:
                      data.totals.meteredRunCoverageRate < 1
                        ? 'text-amber-600 dark:text-amber-400'
                        : undefined,
                  },
                  {
                    label: t('admin.hosted_models.metric_provider_coverage', {}, 'Provider coverage'),
                    value: formatPercent(data.totals.providerCallRunCoverageRate),
                    toneClassName:
                      data.totals.providerCallRunCoverageRate < 1
                        ? 'text-amber-600 dark:text-amber-400'
                        : undefined,
                  },
                  {
                    label: t('admin.hosted_models.metric_meter_events', {}, 'Meter events'),
                    value: formatNumber(data.totals.usageMeterEvents),
                    detail: data.generatedAt ? formatDate(data.generatedAt) : '',
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
              active={recentMinutes === opt.value}
              tone="info"
              onClick={() => setRecentMinutes(opt.value)}
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
            placeholder={t('admin.hosted_models.site_filter_placeholder', {}, 'site_id')}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:placeholder:text-slate-500"
          />
          <button
            type="button"
            onClick={() => setSiteIdFilter(siteIdInput.trim())}
            className="h-8 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white"
          >
            {t('common.apply_filters', {}, 'Filter')}
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
      </BackofficePrimaryPanel>

      {isEmpty ? (
        <BackofficeEmptyState
          title={t('admin.hosted_models.empty_title', {}, 'No hosted runs in this window')}
          description={t(
            'admin.hosted_models.empty_desc',
            {},
            'Hosted model governance signals will appear after Cloud accepts runtime runs.'
          )}
        />
      ) : (
        <>
          <BackofficeSectionPanel className="space-y-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.hosted_models.cadence_eyebrow', {}, 'Cadence record')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.hosted_models.cadence_title', {}, 'Latest cadence record')}
                </h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  {cadence?.available
                    ? translateHostedText(t, cadence.alertSummary.summary)
                    : t(
                        'admin.hosted_models.no_cadence_desc',
                        {},
                        'No background governance rollup has been recorded for this window yet.'
                      )}
                </p>
              </div>
              <BackofficeStatusBadge
                status={cadence?.alertSummary.status || 'inactive'}
                label={cadence?.available ? translateHostedStatus(t, cadence.alertSummary.status) : translateHostedStatus(t, 'missing')}
              />
            </div>
            <BackofficeMetricStrip
              columnsClassName="md:grid-cols-2 xl:grid-cols-5"
              items={[
                {
                  label: t('admin.hosted_models.metric_runs', {}, 'Runs'),
                  value: formatNumber(cadence?.alertSummary.dailyDigest.runs || 0),
                  detail: cadence?.generatedAt
                    ? formatDate(cadence.generatedAt)
                    : t('admin.hosted_models.no_cadence_record', {}, 'No cadence record'),
                  size: 'compact',
                },
                {
                  label: t('admin.hosted_models.metric_meter_coverage', {}, 'Meter coverage'),
                  value: formatPercent(cadence?.alertSummary.dailyDigest.meteredRunCoverageRate || 0),
                },
                {
                  label: t('admin.hosted_models.metric_provider_coverage', {}, 'Provider coverage'),
                  value: formatPercent(cadence?.alertSummary.dailyDigest.providerCallRunCoverageRate || 0),
                },
                {
                  label: t('admin.hosted_models.metric_alerts', {}, 'Alerts'),
                  value: formatNumber(cadence?.alertSummary.alertCount || 0),
                  detail: translateHostedText(t, cadence?.alertSummary.nextAction || 'continue_monitoring'),
                  size: 'compact',
                },
                {
                  label: t('admin.hosted_models.metric_owner', {}, 'Owner'),
                  value: translateHostedText(t, cadence?.delivery.owner || 'internal_admin_readonly'),
                  detail: translateHostedText(t, cadence?.rollup.scopeId || cadence?.source || 'usage_rollup'),
                  size: 'compact',
                },
              ]}
            />
          </BackofficeSectionPanel>

          <BackofficeSectionPanel className="space-y-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.hosted_models.alert_eyebrow', {}, 'Runtime signal')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.hosted_models.alert_title', {}, 'Signals needing model follow-up')}
                </h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  {translateHostedText(t, data?.alertSummary.summary)}
                </p>
              </div>
              <BackofficeStatusBadge
                status={data?.alertSummary.status || governanceStatus}
                label={translateHostedStatus(t, data?.alertSummary.status || governanceStatus)}
              />
            </div>
            {data?.alertSummary.alerts.length ? (
              <div className="grid gap-3 xl:grid-cols-2">
                {data.alertSummary.alerts.map((alert) => (
                  <BackofficeStackCard key={alert.code} className="space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-950 dark:text-white">
                          {translateHostedText(t, alert.title)}
                        </p>
                        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                          {translateHostedText(t, alert.summary)}
                        </p>
                      </div>
                      <BackofficeTag tone={alert.severity === 'error' ? 'warning' : 'info'}>
                        {formatNumber(alert.count)}
                      </BackofficeTag>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {alert.capabilities.length ? (
                        alert.capabilities.slice(0, 4).map((capability) => (
                          <BackofficeTag key={`${alert.code}-${capability}`} tone="info">
                            {capability}
                          </BackofficeTag>
                        ))
                      ) : (
                        <BackofficeTag tone="info">{alert.code}</BackofficeTag>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {translateHostedText(t, alert.suggestedAction)}
                    </p>
                  </BackofficeStackCard>
                ))}
              </div>
            ) : (
              <BackofficeStackCard className="text-sm text-slate-600 dark:text-slate-300">
                {t('admin.hosted_models.no_alerts', {}, 'No hosted model governance alerts in this window.')}
              </BackofficeStackCard>
            )}
          </BackofficeSectionPanel>

          <details className="rounded-2xl border border-dashed border-slate-200 px-5 py-4 dark:border-slate-800">
            <summary className="cursor-pointer list-none text-sm font-semibold text-slate-700 hover:text-slate-950 dark:text-slate-300 dark:hover:text-white">
              {t('admin.hosted_models.advanced_detail_title', {}, 'Advanced model evidence')}
              <span className="ml-3 font-normal text-slate-500 dark:text-slate-400">
                {t('admin.hosted_models.advanced_detail_desc', {}, 'Metering, provider, capability, and read-only boundary detail')}
              </span>
            </summary>
            <div className="mt-5 space-y-5">
          <BackofficeSectionPanel className="space-y-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.hosted_models.capability_eyebrow', {}, 'Capability posture')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.hosted_models.capability_title', {}, 'Ability families')}
                </h2>
              </div>
              <BackofficeStatusBadge
                status={governanceStatus}
                label={translateHostedStatus(t, governanceStatus === 'ok' ? 'covered' : governanceStatus)}
              />
            </div>
            <div className="grid gap-3 xl:grid-cols-3">
              {(data?.capabilityGroups || []).map((group) => (
                <BackofficeStackCard key={group.groupId} className="space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-950 dark:text-white">
                        {group.groupId}
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {group.executionKinds.join(', ') || t('common.unknown', {}, 'unknown')}
                      </p>
                    </div>
                    <BackofficeStatusBadge status={groupTone(group)} label={groupTone(group)} />
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <MetricLine label={t('admin.hosted_models.metric_runs', {}, 'Runs')} value={formatNumber(group.runsTotal)} />
                    <MetricLine label={t('admin.hosted_models.metric_calls', {}, 'Calls')} value={formatNumber(group.providerCalls)} />
                    <MetricLine label={t('common.tokens', {}, 'Tokens')} value={formatNumber(group.tokensTotal)} />
                    <MetricLine label={t('common.cost', {}, 'Cost')} value={formatCost(group.cost)} />
                    <MetricLine
                      label={t('admin.hosted_models.metric_meter', {}, 'Meter')}
                      value={formatPercent(group.meteredRunCoverageRate)}
                    />
                    <MetricLine
                      label={t('admin.hosted_models.metric_provider', {}, 'Provider')}
                      value={formatPercent(group.providerCallRunCoverageRate)}
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {group.profileIds.slice(0, 3).map((profileId) => (
                      <BackofficeTag key={profileId} tone="info">
                        {profileId}
                      </BackofficeTag>
                    ))}
                  </div>
                </BackofficeStackCard>
              ))}
            </div>
          </BackofficeSectionPanel>

          <div className="grid gap-5 xl:grid-cols-2">
            <GovernanceTable
              title={t('admin.hosted_models.profiles_title', {}, 'Profiles')}
              eyebrow={t('admin.hosted_models.profiles_eyebrow', {}, 'Routing profile')}
              rows={data?.profileGroups || []}
              firstColumn={t('admin.hosted_models.column_profile', {}, 'Profile')}
              t={t}
            />
            <GovernanceTable
              title={t('admin.hosted_models.provider_models_title', {}, 'Provider models')}
              eyebrow={t('admin.hosted_models.provider_models_eyebrow', {}, 'Upstream')}
              rows={data?.providerModelGroups || []}
              firstColumn={t('admin.hosted_models.column_provider_model', {}, 'Provider/model')}
              t={t}
            />
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.hosted_models.coverage_eyebrow', {}, 'Coverage')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.hosted_models.gaps_title', {}, 'Governance gaps')}
                </h2>
              </div>
              <BackofficeStackCard>
                <div className="grid gap-3 sm:grid-cols-2">
                  <MetricLine
                    label={t('admin.hosted_models.metric_unmetered_runs', {}, 'Unmetered runs')}
                    value={formatNumber(data?.governanceGaps.unmeteredRunCount || 0)}
                  />
                  <MetricLine
                    label={t('admin.hosted_models.metric_runs_without_provider_calls', {}, 'Runs without provider calls')}
                    value={formatNumber(data?.governanceGaps.runsWithoutProviderCallCount || 0)}
                  />
                </div>
                <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {translateHostedText(t, data?.governanceGaps.reviewGuidance)}
                </p>
              </BackofficeStackCard>
              <div className="flex flex-wrap gap-2">
                {(data?.governanceGaps.unmeteredCapabilities || []).map((item) => (
                  <BackofficeTag key={`unmetered-${item}`} tone="warning">
                    {t('admin.hosted_models.tag_unmetered', { item }, `unmetered: ${item}`)}
                  </BackofficeTag>
                ))}
                {(data?.governanceGaps.missingProviderCallCapabilities || []).map((item) => (
                  <BackofficeTag key={`missing-provider-${item}`} tone="warning">
                    {t('admin.hosted_models.tag_provider_gap', { item }, `provider gap: ${item}`)}
                  </BackofficeTag>
                ))}
                {!data?.governanceGaps.unmeteredCapabilities.length &&
                !data?.governanceGaps.missingProviderCallCapabilities.length ? (
                  <BackofficeTag tone="info">
                    {t('admin.hosted_models.no_coverage_gaps', {}, 'No coverage gaps in window')}
                  </BackofficeTag>
                ) : null}
              </div>
            </BackofficeSectionPanel>

            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.hosted_models.boundary_eyebrow', {}, 'Boundary')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.hosted_models.boundary_title', {}, 'Read-only runtime detail')}
                </h2>
              </div>
              <BackofficeStackCard className="space-y-3">
                <MetricLine
                  label={t('admin.hosted_models.boundary_surface', {}, 'Surface')}
                  value={translateHostedText(t, data?.boundary.surface || 'internal')}
                />
                <MetricLine
                  label={t('admin.hosted_models.boundary_cloud_role', {}, 'Cloud role')}
                  value={translateHostedText(t, data?.boundary.cloudRole || 'runtime')}
                />
                <MetricLine
                  label={t('admin.hosted_models.boundary_local_control_plane', {}, 'Local control plane')}
                  value={translateHostedText(t, data?.boundary.localControlPlane || 'wordpress_plugin')}
                />
                <MetricLine
                  label={t('admin.hosted_models.boundary_wordpress_write', {}, 'WordPress write')}
                  value={
                    data?.boundary.directWordpressWrite
                      ? t('admin.hosted_models.value_allowed', {}, 'allowed')
                      : t('admin.hosted_models.value_not_allowed', {}, 'not allowed')
                  }
                />
                <MetricLine
                  label={t('admin.hosted_models.boundary_payloads', {}, 'Prompt/result payloads')}
                  value={
                    data?.boundary.containsPromptOrResultPayloads
                      ? t('admin.hosted_models.value_included', {}, 'included')
                      : t('admin.hosted_models.value_excluded', {}, 'excluded')
                  }
                />
              </BackofficeStackCard>
            </BackofficeSectionPanel>
          </div>
            </div>
          </details>
        </>
      )}
    </BackofficePageStack>
  );
}

function MetricLine({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-950 dark:text-white">
        {value}
      </p>
    </div>
  );
}

function GovernanceTable({
  eyebrow,
  title,
  rows,
  firstColumn,
  t,
}: {
  eyebrow: string;
  title: string;
  rows: GovernanceGroup[];
  firstColumn: string;
  t: Translate;
}) {
  return (
    <BackofficeSectionPanel className="overflow-hidden p-0">
      <div className="border-b border-slate-200/80 px-5 py-4 dark:border-slate-800 md:px-6">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
          {eyebrow}
        </p>
        <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200/80 text-sm dark:divide-slate-800">
          <thead className="bg-slate-50/80 text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-950/30 dark:text-slate-400">
            <tr>
              <th className="px-5 py-3 text-left font-semibold">{firstColumn}</th>
              <th className="px-5 py-3 text-right font-semibold">
                {t('admin.hosted_models.metric_runs', {}, 'Runs')}
              </th>
              <th className="px-5 py-3 text-right font-semibold">
                {t('admin.hosted_models.metric_calls', {}, 'Calls')}
              </th>
              <th className="px-5 py-3 text-right font-semibold">
                {t('admin.hosted_models.metric_error', {}, 'Error')}
              </th>
              <th className="px-5 py-3 text-right font-semibold">
                {t('admin.hosted_models.metric_meter', {}, 'Meter')}
              </th>
              <th className="px-5 py-3 text-right font-semibold">
                {t('admin.hosted_models.metric_latency', {}, 'Latency')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200/80 dark:divide-slate-800">
            {rows.map((row) => (
              <tr key={`${row.groupKind}-${row.groupId}`} className="bg-white/55 dark:bg-slate-950/20">
                <td className="max-w-[18rem] px-5 py-3">
                  <BackofficeIdentifier value={row.groupId} />
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {row.providerIds.slice(0, 2).map((providerId) => (
                      <BackofficeTag key={providerId} tone="info">
                        {providerId}
                      </BackofficeTag>
                    ))}
                  </div>
                </td>
                <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                  {formatNumber(row.runsTotal)}
                </td>
                <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                  {formatNumber(row.providerCalls)}
                </td>
                <td className="px-5 py-3 text-right">
                  <BackofficeTag tone={row.providerErrorRate > 0 ? 'warning' : 'info'}>
                    {formatPercent(row.providerErrorRate)}
                  </BackofficeTag>
                </td>
                <td className="px-5 py-3 text-right">
                  <BackofficeTag tone={coverageStatus(row.meteredRunCoverageRate) === 'ok' ? 'info' : 'warning'}>
                    {formatPercent(row.meteredRunCoverageRate)}
                  </BackofficeTag>
                </td>
                <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-200">
                  {formatNumber(row.avgLatencyMs)}ms
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </BackofficeSectionPanel>
  );
}

export default function AdminHostedModelsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminHostedModelsContent />
    </Suspense>
  );
}
