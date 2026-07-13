'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  BackofficeEmptyState,
  BackofficeLayer,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { formatDate, formatNumber } from '@/lib/utils';

type RuntimeTelemetryAlert = {
  code: string;
  severity: string;
  title: string;
  summary: string;
  count: number;
  capabilities: string[];
  suggestedAction: string;
  href: string;
};

type RuntimeTelemetrySummary = {
  generatedAt: string;
  totals: {
    runs: number;
    providerCalls: number;
    usageMeterEvents: number;
    providerCallRunCoverageRate: number;
    meteredRunCoverageRate: number;
  };
  governanceGaps: {
    unmeteredCapabilities: string[];
    missingProviderCallCapabilities: string[];
    unmeteredRunCount: number;
    runsWithoutProviderCallCount: number;
    reviewGuidance: string;
  };
  alertSummary: {
    status: string;
    summary: string;
    nextAction: string;
    alertCount: number;
    alerts: RuntimeTelemetryAlert[];
  };
};

type EvidenceLane = {
  id: string;
  href: string;
  titleKey: string;
  titleFallback: string;
  descKey: string;
  descFallback: string;
};

type TranslationFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

const WINDOW_OPTIONS = [24, 72, 168] as const;

const evidenceLanes: EvidenceLane[] = [
  {
    id: 'plugin',
    href: '/admin/plugin-observability',
    titleKey: 'admin.nav_plugin_observability',
    titleFallback: 'Plugin observability',
    descKey: 'admin.advanced.plugin_observability_desc',
    descFallback: 'Plugin event volume, error pressure, latency, and recent failure evidence.',
  },
  {
    id: 'media',
    href: '/admin/media-observability',
    titleKey: 'admin.nav_media_observability',
    titleFallback: 'Media observability',
    descKey: 'admin.advanced.media_observability_desc',
    descFallback: 'Media processing jobs, failures, processing duration, and compression value.',
  },
  {
    id: 'vector',
    href: '/admin/vector-observability',
    titleKey: 'admin.nav_vector_observability',
    titleFallback: 'Vector observability',
    descKey: 'admin.advanced.vector_observability_desc',
    descFallback: 'Vector and Site Knowledge indexing health for support investigations.',
  },
  {
    id: 'feedback',
    href: '/admin/agent-feedback',
    titleKey: 'admin.nav_agent_feedback',
    titleFallback: 'Agent feedback quality',
    descKey: 'admin.advanced.agent_feedback_desc',
    descFallback: 'Read-only quality signals from local operator feedback across Cloud-backed AI assistance.',
  },
];

const runtimeEvidenceItems = [
  {
    titleKey: 'admin.advanced.runtime_resolution_title',
    titleFallback: 'Runtime resolution',
    descKey: 'admin.advanced.runtime_resolution_desc',
    descFallback: 'Capability to profile, supplier, and model selection evidence. Read-only, not a router editor.',
  },
  {
    titleKey: 'admin.advanced.capability_matrix_title',
    titleFallback: 'Capability matrix',
    descKey: 'admin.advanced.capability_matrix_desc',
    descFallback: 'Current Cloud runtime mapping across capabilities, selected providers, and write posture.',
  },
  {
    titleKey: 'admin.advanced.runtime_profiles_title',
    titleFallback: 'Runtime configurations',
    descKey: 'admin.advanced.runtime_profiles_desc',
    descFallback: 'Cloud runtime profile metadata and selected provider/model references.',
  },
  {
    titleKey: 'admin.advanced.recent_runtime_evidence_title',
    titleFallback: 'Recent runtime evidence',
    descKey: 'admin.advanced.recent_runtime_evidence_desc',
    descFallback: 'Recent run metadata used for diagnostics without exposing prompts, results, or provider secrets.',
  },
];

function normalizeWindow(value: string | null): 24 | 72 | 168 {
  const parsed = Number(value);
  return WINDOW_OPTIONS.includes(parsed as 24 | 72 | 168) ? parsed as 24 | 72 | 168 : 24;
}

function asNumber(value: unknown): number {
  return Number(value ?? 0) || 0;
}

function normalizeRuntimeTelemetry(raw: any): RuntimeTelemetrySummary {
  const totals = raw?.totals ?? {};
  const gaps = raw?.governance_gaps ?? {};
  const alertSummary = raw?.alert_summary ?? {};
  return {
    generatedAt: String(raw?.generated_at ?? ''),
    totals: {
      runs: asNumber(totals.runs),
      providerCalls: asNumber(totals.provider_calls),
      usageMeterEvents: asNumber(totals.usage_meter_events),
      providerCallRunCoverageRate: asNumber(totals.provider_call_run_coverage_rate),
      meteredRunCoverageRate: asNumber(totals.metered_run_coverage_rate),
    },
    governanceGaps: {
      unmeteredCapabilities: Array.isArray(gaps.unmetered_capabilities) ? gaps.unmetered_capabilities.map(String) : [],
      missingProviderCallCapabilities: Array.isArray(gaps.missing_provider_call_capabilities) ? gaps.missing_provider_call_capabilities.map(String) : [],
      unmeteredRunCount: asNumber(gaps.unmetered_run_count),
      runsWithoutProviderCallCount: asNumber(gaps.runs_without_provider_call_count),
      reviewGuidance: String(gaps.review_guidance ?? ''),
    },
    alertSummary: {
      status: String(alertSummary.status ?? 'inactive'),
      summary: String(alertSummary.summary ?? ''),
      nextAction: String(alertSummary.next_action ?? ''),
      alertCount: asNumber(alertSummary.alert_count),
      alerts: Array.isArray(alertSummary.alerts)
        ? alertSummary.alerts.map((item: any) => ({
            code: String(item?.code ?? ''),
            severity: String(item?.severity ?? 'warning'),
            title: String(item?.title ?? ''),
            summary: String(item?.summary ?? ''),
            count: asNumber(item?.count),
            capabilities: Array.isArray(item?.capabilities) ? item.capabilities.map(String) : [],
            suggestedAction: String(item?.suggested_action ?? ''),
            href: String(item?.href ?? ''),
          }))
        : [],
    },
  };
}

function formatRate(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function statusTone(status: string): 'success' | 'warning' | 'error' | 'pending' {
  const normalized = status.trim().toLowerCase();
  if (['ok', 'healthy', 'success', 'ready'].includes(normalized)) return 'success';
  if (['error', 'critical', 'failed'].includes(normalized)) return 'error';
  if (['warning', 'degraded'].includes(normalized)) return 'warning';
  return 'pending';
}

function issueDestination(issue: RuntimeTelemetryAlert): string {
  if (issue.href && issue.href !== '/admin/troubleshooting') return issue.href;
  if (issue.code === 'hosted_model.failed_runs') return '/admin/plugin-observability';
  return '#runtime-evidence';
}

function issueTitle(issue: RuntimeTelemetryAlert, t: TranslationFn): string {
  const knownTitles: Record<string, [string, string]> = {
    'hosted_model.provider_errors': ['admin.troubleshooting.issue_provider_errors', 'Provider call errors'],
    'hosted_model.failed_runs': ['admin.troubleshooting.issue_runtime_failed', 'Runtime runs failed'],
    'hosted_model.provider_call_gap': ['admin.troubleshooting.issue_provider_gap', 'Provider call coverage gap'],
  };
  const known = knownTitles[issue.code];
  return known ? t(known[0], {}, known[1]) : issue.title || issue.code;
}

function issueSummary(issue: RuntimeTelemetryAlert, t: TranslationFn): string {
  const knownSummaries: Record<string, [string, string]> = {
    'hosted_model.provider_errors': ['admin.troubleshooting.issue_provider_errors_desc', 'Provider calls are returning errors in the current telemetry window.'],
    'hosted_model.failed_runs': ['admin.troubleshooting.issue_runtime_failed_desc', 'Runtime runs are failing before or during provider execution.'],
    'hosted_model.provider_call_gap': ['admin.troubleshooting.issue_provider_gap_desc', 'Some runtime runs do not have matching provider-call telemetry.'],
  };
  const known = knownSummaries[issue.code];
  return known ? t(known[0], {}, known[1]) : issue.summary;
}

function issueAction(issue: RuntimeTelemetryAlert, t: TranslationFn): string {
  const knownActions: Record<string, [string, string]> = {
    inspect_provider_credentials_quota_and_health: ['admin.troubleshooting.action_check_provider_health', 'Check supplier health, credentials, and quota evidence.'],
    inspect_runtime_failure_detail: ['admin.troubleshooting.action_check_runtime_failures', 'Inspect runtime failure codes and provider health evidence.'],
    inspect_runtime_failure_codes_and_provider_health: ['admin.troubleshooting.action_check_runtime_failures', 'Inspect runtime failure codes and provider health evidence.'],
    inspect_provider_call_recording_for_hosted_profiles: ['admin.troubleshooting.action_check_telemetry_gap', 'Inspect provider-call recording coverage for hosted profiles.'],
  };
  const known = knownActions[issue.suggestedAction];
  return known ? t(known[0], {}, known[1]) : issue.suggestedAction;
}

function severityLabel(severity: string, t: TranslationFn): string {
  return statusTone(severity) === 'error'
    ? t('admin.troubleshooting.severity_error', {}, 'Error')
    : statusTone(severity) === 'warning'
      ? t('admin.troubleshooting.severity_warning', {}, 'Warning')
      : t('admin.troubleshooting.severity_notice', {}, 'Notice');
}

export default function AdminTroubleshootingPage() {
  const { t } = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const windowHours = normalizeWindow(searchParams.get('window'));
  const focusedIssueCode = searchParams.get('focus') || '';
  const [data, setData] = useState<RuntimeTelemetrySummary | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const requestActiveRef = useRef(false);
  const requestSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);

  const updateUrl = useCallback((updates: { window?: number | null; focus?: string | null }) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value && !(key === 'window' && value === 24)) params.set(key, String(value));
      else params.delete(key);
    });
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  const loadTelemetry = useCallback(async (refresh = false) => {
    if (requestActiveRef.current) return;
    requestActiveRef.current = true;
    const sequence = ++requestSequenceRef.current;
    if (refresh || hasLoadedRef.current) setRefreshing(true);
    else setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ recent_minutes: String(windowHours * 60), limit: '25' });
      const response = await fetch(`/api/admin/runtime-telemetry?${params.toString()}`, {
        credentials: 'include',
        cache: 'no-store',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload?.status === 'error') {
        throw new Error(resolveUiErrorMessage(payload, t('admin.troubleshooting.load_error', {}, 'Failed to load runtime diagnostics.')));
      }
      if (sequence !== requestSequenceRef.current) return;
      setData(normalizeRuntimeTelemetry(payload?.data ?? {}));
      hasLoadedRef.current = true;
    } catch (loadError) {
      if (sequence !== requestSequenceRef.current) return;
      setError(loadError instanceof Error ? loadError.message : t('admin.troubleshooting.load_error', {}, 'Failed to load runtime diagnostics.'));
    } finally {
      if (sequence === requestSequenceRef.current) {
        requestActiveRef.current = false;
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [t, windowHours]);

  useEffect(() => {
    void loadTelemetry();
  }, [loadTelemetry]);

  const issues = data?.alertSummary.alerts || [];
  const selectedIssue = issues.find((issue) => issue.code === focusedIssueCode) || issues[0] || null;
  const conclusionStatus = data?.alertSummary.status || (loading ? 'pending' : 'inactive');
  const conclusionLabel = statusTone(conclusionStatus) === 'success'
    ? t('admin.troubleshooting.status_healthy', {}, 'Healthy')
    : statusTone(conclusionStatus) === 'error'
      ? t('admin.troubleshooting.status_critical', {}, 'Critical')
      : statusTone(conclusionStatus) === 'warning'
        ? t('admin.troubleshooting.status_warning', {}, 'Needs attention')
        : t('admin.troubleshooting.status_unknown', {}, 'Awaiting evidence');
  const conclusionSummary = statusTone(conclusionStatus) === 'error'
    ? t('admin.troubleshooting.conclusion_error', {}, 'Runtime telemetry has errors or coverage gaps that require operator review.')
    : statusTone(conclusionStatus) === 'warning'
      ? t('admin.troubleshooting.conclusion_warning', {}, 'Runtime telemetry has coverage gaps that should be reviewed.')
      : statusTone(conclusionStatus) === 'success'
        ? t('admin.troubleshooting.conclusion_healthy', {}, 'Runtime telemetry is healthy in the selected window.')
        : data?.alertSummary.summary || t('admin.troubleshooting.queue_desc', {}, 'Select an anomaly to inspect its evidence scope and next diagnostic step.');

  return (
    <BackofficePageStack>
      <BackofficeLayer
        eyebrow={t('admin.operator_surface', {}, 'Operator surface')}
        title={t('admin.troubleshooting.title', {}, 'Runtime diagnostics')}
        description={t('admin.troubleshooting.description', {}, 'Review the current runtime conclusion, open active anomalies, and continue into the narrowest evidence view.')}
        aside={<BackofficeStatusBadge label={conclusionLabel} status={statusTone(conclusionStatus)} />}
        actions={(
          <button type="button" className="btn btn-secondary btn-sm" disabled={loading || refreshing} onClick={() => void loadTelemetry(true)}>
            {refreshing ? t('admin.troubleshooting.refreshing', {}, 'Refreshing...') : t('admin.troubleshooting.refresh', {}, 'Refresh')}
          </button>
        )}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" aria-label={t('admin.troubleshooting.window_label', {}, 'Diagnostic window')}>
          {WINDOW_OPTIONS.map((hours) => (
            <button
              key={hours}
              type="button"
              aria-pressed={windowHours === hours}
              className={`cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium transition ${windowHours === hours ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300'}`}
              onClick={() => updateUrl({ window: hours, focus: null })}
            >
              {hours === 24 ? '24h' : hours === 72 ? '72h' : '7d'}
            </button>
          ))}
        </div>
        {data?.generatedAt ? <p className="text-xs text-slate-500 dark:text-slate-400">{t('admin.troubleshooting.generated_at', { time: formatDate(data.generatedAt) }, 'Generated {{time}}')}</p> : null}
      </div>

      {data ? <BackofficeSummaryStrip items={[
        { label: t('admin.troubleshooting.runs', {}, 'Runs'), value: formatNumber(data.totals.runs) },
        { label: t('admin.troubleshooting.provider_coverage', {}, 'Provider-call coverage'), value: formatRate(data.totals.providerCallRunCoverageRate), toneClassName: data.totals.providerCallRunCoverageRate < 1 ? 'text-amber-700 dark:text-amber-300' : undefined },
        { label: t('admin.troubleshooting.metering_coverage', {}, 'Metering coverage'), value: formatRate(data.totals.meteredRunCoverageRate), toneClassName: data.totals.meteredRunCoverageRate < 1 ? 'text-amber-700 dark:text-amber-300' : undefined },
        { label: t('admin.troubleshooting.open_issues', {}, 'Open anomalies'), value: data.alertSummary.alertCount, toneClassName: data.alertSummary.alertCount > 0 ? 'text-amber-700 dark:text-amber-300' : undefined },
      ]} /> : null}

      {error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200" role="alert">
          <div className="font-semibold">{error}</div>
          {data ? <div className="mt-1 text-xs">{t('admin.troubleshooting.stale_notice', {}, 'The last successfully loaded diagnostic snapshot remains visible.')}</div> : null}
        </div>
      ) : null}

      {loading && !data ? (
        <BackofficeSectionPanel className="animate-pulse space-y-3" aria-label={t('admin.troubleshooting.loading', {}, 'Loading runtime diagnostics')}>
          <div className="h-5 w-48 rounded bg-slate-200 dark:bg-slate-800" />
          <div className="h-20 rounded-xl bg-slate-100 dark:bg-slate-900" />
          <div className="h-20 rounded-xl bg-slate-100 dark:bg-slate-900" />
        </BackofficeSectionPanel>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <BackofficeSectionPanel className="overflow-hidden p-0 md:p-0">
            <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800 md:px-6">
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{t('admin.troubleshooting.queue_title', {}, 'Runtime anomaly queue')}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{conclusionSummary}</p>
            </div>
            <div className="max-h-[36rem] divide-y divide-slate-200 overflow-y-auto dark:divide-slate-800 xl:max-h-[42rem]">
              {issues.map((issue) => {
                const selected = selectedIssue?.code === issue.code;
                return (
                  <button
                    key={issue.code}
                    type="button"
                    data-ui="runtime-diagnostic-issue"
                    aria-pressed={selected}
                    aria-controls="runtime-diagnostic-inspector"
                    className={`grid w-full cursor-pointer gap-3 px-5 py-4 text-left transition hover:bg-slate-50 dark:hover:bg-slate-900/45 md:grid-cols-[minmax(12rem,1fr)_8rem] md:items-center md:px-6 ${selected ? 'bg-blue-50/65 dark:bg-blue-950/20' : ''}`}
                    onClick={() => updateUrl({ focus: issue.code })}
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-slate-950 dark:text-white">{issueTitle(issue, t)}</span>
                        <BackofficeStatusBadge label={severityLabel(issue.severity, t)} status={statusTone(issue.severity)} />
                      </div>
                      <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{issueSummary(issue, t)}</p>
                      {issue.capabilities.length ? <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{t('admin.troubleshooting.capabilities', { values: issue.capabilities.join(', ') }, 'Capabilities: {{values}}')}</p> : null}
                    </div>
                    <div className="text-sm font-medium text-slate-500 md:text-right dark:text-slate-400">{t('admin.troubleshooting.occurrences', { count: String(issue.count) }, '{{count}} occurrences')}</div>
                  </button>
                );
              })}
              {issues.length ? null : (
                <BackofficeEmptyState className="m-5 md:m-6" title={t('admin.troubleshooting.no_issue_title', {}, 'No active runtime anomalies')} description={t('admin.troubleshooting.no_issue_desc', {}, 'The selected window has no runtime telemetry alerts. Continue with a narrow evidence lane only when investigating a specific support question.')} />
              )}
            </div>
          </BackofficeSectionPanel>

          <BackofficeSectionPanel id="runtime-diagnostic-inspector" className="h-fit xl:sticky xl:top-4">
            {selectedIssue ? (
              <div className="space-y-5">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('admin.troubleshooting.inspector_eyebrow', {}, 'Selected anomaly')}</p>
                  <div className="mt-2 flex items-start justify-between gap-3"><h2 className="text-lg font-semibold text-slate-950 dark:text-white">{issueTitle(selectedIssue, t)}</h2><BackofficeStatusBadge label={severityLabel(selectedIssue.severity, t)} status={statusTone(selectedIssue.severity)} /></div>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{issueSummary(selectedIssue, t)}</p>
                </div>
                <dl className="grid gap-3 text-sm">
                  <div><dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.troubleshooting.issue_code', {}, 'Evidence code')}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-800 dark:text-slate-100">{selectedIssue.code}</dd></div>
                  <div><dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.troubleshooting.suggested_action', {}, 'Suggested diagnostic step')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{issueAction(selectedIssue, t) || data?.governanceGaps.reviewGuidance || data?.alertSummary.nextAction}</dd></div>
                  <div><dt className="text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.troubleshooting.affected_scope', {}, 'Affected scope')}</dt><dd className="mt-1 text-slate-800 dark:text-slate-100">{selectedIssue.capabilities.join(', ') || t('admin.troubleshooting.runtime_scope', {}, 'Cloud runtime')}</dd></div>
                </dl>
                <Link href={issueDestination(selectedIssue)} className="btn btn-primary w-full justify-center">{t('admin.troubleshooting.open_evidence', {}, 'Open matching evidence')}</Link>
                <p className="rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-500 dark:bg-slate-900/45 dark:text-slate-400">{t('admin.troubleshooting.boundary', {}, 'Diagnostics are read-only Cloud runtime evidence. They do not change providers, model routing, local abilities, prompts, approval state, or WordPress content.')}</p>
              </div>
            ) : (
              <div className="space-y-4">
                <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{t('admin.troubleshooting.health_conclusion', {}, 'Health conclusion')}</p><h2 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{conclusionLabel}</h2><p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{conclusionSummary}</p></div>
                <Link href="#evidence-lanes" className="btn btn-secondary w-full justify-center">{t('admin.troubleshooting.review_lanes', {}, 'Review evidence lanes')}</Link>
              </div>
            )}
          </BackofficeSectionPanel>
        </div>
      )}

      <BackofficeSectionPanel id="evidence-lanes" className="overflow-hidden p-0 md:p-0">
        <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800 md:px-6"><h2 className="text-lg font-semibold text-slate-950 dark:text-white">{t('admin.troubleshooting.lanes_title', {}, 'Evidence lanes')}</h2><p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{t('admin.troubleshooting.lanes_desc', {}, 'Open the narrowest read-only detail view that matches the support question.')}</p></div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {evidenceLanes.map((lane) => (
            <Link key={lane.id} href={lane.href} className="grid cursor-pointer gap-2 px-5 py-4 transition hover:bg-slate-50 dark:hover:bg-slate-900/45 md:grid-cols-[minmax(12rem,0.65fr)_minmax(0,1fr)_auto] md:items-center md:px-6">
              <span className="font-semibold text-slate-950 dark:text-white">{t(lane.titleKey, {}, lane.titleFallback)}</span><span className="text-sm leading-6 text-slate-600 dark:text-slate-300">{t(lane.descKey, {}, lane.descFallback)}</span><span className="text-sm font-semibold text-blue-700 dark:text-blue-300">{t('admin.troubleshooting.inspect', {}, 'Inspect')} →</span>
            </Link>
          ))}
        </div>
      </BackofficeSectionPanel>

      <details id="runtime-evidence" className="rounded-[1.35rem] border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <summary className="cursor-pointer select-none px-5 py-4 text-sm font-semibold text-slate-900 dark:text-white md:px-6">{t('admin.troubleshooting.runtime_metadata_title', {}, 'Advanced runtime metadata')}</summary>
        <div className="border-t border-slate-200 px-5 py-5 dark:border-slate-800 md:px-6">
          <div className="grid gap-4 md:grid-cols-2">
            {runtimeEvidenceItems.map((item) => <div key={item.titleKey}><h3 className="text-sm font-semibold text-slate-950 dark:text-white">{t(item.titleKey, {}, item.titleFallback)}</h3><p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{t(item.descKey, {}, item.descFallback)}</p></div>)}
          </div>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-800"><p className="max-w-3xl text-xs leading-5 text-slate-500 dark:text-slate-400">{t('admin.advanced.runtime_evidence_boundary', {}, 'Evidence source remains Cloud runtime metadata such as run records, provider-call records, usage meter events, runtime profiles, and capability projection rows.')}</p><Link href="/admin/ability-models" className="btn btn-secondary btn-sm">{t('admin.advanced.action_open_model_binding', {}, 'Open model binding')}</Link></div>
        </div>
      </details>
    </BackofficePageStack>
  );
}
