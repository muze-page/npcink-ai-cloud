'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { cn, formatNumber } from '@/lib/utils';

type SummaryBranch = {
  generation: {
    mode: string;
    provider_id: string;
    model_id: string;
    error_code: string;
    tokens_in?: number;
    tokens_out?: number;
    cost?: number;
  };
  headline: string;
  operator_summary: string;
  support_draft: string;
  operator_next_step: string;
  safety_note: string;
  severity: string;
  status: string;
  source_context: {
    advisor: {
      scope: string;
      evidence: Array<{ kind: string; ref: string; label: string }>;
      signals: Array<Record<string, string | number | boolean | null>>;
    };
  };
};

type AdvisorPreviewData = {
  previewVersion: string;
  baseline: SummaryBranch;
  ai: SummaryBranch;
  comparison: {
    baselineMode: string;
    aiMode: string;
    requestedProviderId: string;
    modelId: string;
    aiCalled: boolean;
    textChanged: boolean;
    tokensIn: number;
    tokensOut: number;
    cost: number;
    errorCode: string;
    valueCheck: string;
  };
  safety: {
    promptSaved: boolean;
    outputTextSaved: boolean;
    wordpressWriteAllowed: boolean;
    customerArticleGenerationAllowed: boolean;
    requiresOperatorReview: boolean;
  };
};

const SCOPE_OPTIONS = [
  { label: 'Operations', value: 'operations' },
  { label: 'Runtime', value: 'runtime' },
  { label: 'Commercial', value: 'commercial' },
  { label: 'Routing', value: 'routing' },
];

function normalizeBranch(raw: any): SummaryBranch {
  const generation = raw?.generation ?? {};
  return {
    generation: {
      mode: String(generation.mode ?? ''),
      provider_id: String(generation.provider_id ?? ''),
      model_id: String(generation.model_id ?? ''),
      error_code: String(generation.error_code ?? ''),
      tokens_in: Number(generation.tokens_in ?? 0),
      tokens_out: Number(generation.tokens_out ?? 0),
      cost: Number(generation.cost ?? 0),
    },
    headline: String(raw?.headline ?? ''),
    operator_summary: String(raw?.operator_summary ?? ''),
    support_draft: String(raw?.support_draft ?? ''),
    operator_next_step: String(raw?.operator_next_step ?? ''),
    safety_note: String(raw?.safety_note ?? ''),
    severity: String(raw?.severity ?? ''),
    status: String(raw?.status ?? ''),
    source_context: {
      advisor: {
        scope: String(raw?.source_context?.advisor?.scope ?? ''),
        evidence: Array.isArray(raw?.source_context?.advisor?.evidence)
          ? raw.source_context.advisor.evidence.map((item: any) => ({
              kind: String(item?.kind ?? ''),
              ref: String(item?.ref ?? ''),
              label: String(item?.label ?? ''),
            }))
          : [],
        signals: Array.isArray(raw?.source_context?.advisor?.signals)
          ? raw.source_context.advisor.signals
              .filter((item: any) => item && typeof item === 'object')
              .map((item: any) => item as Record<string, string | number | boolean | null>)
          : [],
      },
    },
  };
}

function normalizePreview(raw: any): AdvisorPreviewData {
  const comparison = raw?.comparison ?? {};
  const safety = raw?.safety ?? {};
  return {
    previewVersion: String(raw?.preview_version ?? ''),
    baseline: normalizeBranch(raw?.baseline ?? {}),
    ai: normalizeBranch(raw?.ai ?? {}),
    comparison: {
      baselineMode: String(comparison.baseline_mode ?? ''),
      aiMode: String(comparison.ai_mode ?? ''),
      requestedProviderId: String(comparison.requested_provider_id ?? ''),
      modelId: String(comparison.model_id ?? ''),
      aiCalled: Boolean(comparison.ai_called),
      textChanged: Boolean(comparison.text_changed),
      tokensIn: Number(comparison.tokens_in ?? 0),
      tokensOut: Number(comparison.tokens_out ?? 0),
      cost: Number(comparison.cost ?? 0),
      errorCode: String(comparison.error_code ?? ''),
      valueCheck: String(comparison.value_check ?? ''),
    },
    safety: {
      promptSaved: Boolean(safety.prompt_saved),
      outputTextSaved: Boolean(safety.output_text_saved),
      wordpressWriteAllowed: Boolean(safety.wordpress_write_allowed),
      customerArticleGenerationAllowed: Boolean(safety.customer_article_generation_allowed),
      requiresOperatorReview: Boolean(safety.requires_operator_review),
    },
  };
}

function formatCost(value: number): string {
  return `$${Number(value || 0).toFixed(6)}`;
}

function valueCheckLabel(value: string): string {
  switch (value) {
    case 'review_ai_output':
      return 'Review AI output';
    case 'configure_provider_allowlist':
      return 'Provider blocked';
    case 'configure_provider_adapter':
      return 'Provider missing';
    case 'pass_provider_id_to_test_llm':
      return 'Provider not selected';
    case 'no_material_difference':
      return 'No material difference';
    default:
      return value || 'Unknown';
  }
}

function valueCheckStatus(value: string): string {
  if (value === 'review_ai_output') return 'success';
  if (value === 'configure_provider_allowlist' || value === 'configure_provider_adapter') return 'warning';
  if (value === 'pass_provider_id_to_test_llm') return 'inactive';
  return 'inactive';
}

function BranchPanel({
  title,
  branch,
  accent,
}: {
  title: string;
  branch: SummaryBranch;
  accent: 'baseline' | 'ai';
}) {
  const generationStatus =
    branch.generation.mode === 'llm'
      ? 'success'
      : branch.generation.error_code
        ? 'warning'
        : 'inactive';

  return (
    <BackofficeSectionPanel className="flex min-h-[34rem] flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {accent === 'ai' ? 'AI branch' : 'Rule baseline'}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{title}</h2>
        </div>
        <BackofficeStatusBadge label={branch.generation.mode || 'unknown'} status={generationStatus} />
      </div>

      <div
        className={cn(
          'rounded-[1.1rem] border px-4 py-3',
          accent === 'ai'
            ? 'border-blue-200 bg-blue-50/70 dark:border-blue-900/60 dark:bg-blue-950/20'
            : 'border-slate-200 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-950/35'
        )}
      >
        <p className="text-sm font-semibold text-slate-950 dark:text-white">{branch.headline || 'No headline'}</p>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {branch.operator_summary || 'No operator summary.'}
        </p>
      </div>

      <div className="space-y-4">
        <TextBlock title="Support draft" value={branch.support_draft || 'No support draft.'} />
        <TextBlock title="Next step" value={branch.operator_next_step || 'No next step.'} compact />
        <TextBlock title="Safety note" value={branch.safety_note || 'No safety note.'} compact />
      </div>

      <div className="mt-auto grid gap-3 border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800 sm:grid-cols-3">
        <MiniMetric label="Provider" value={branch.generation.provider_id || '-'} />
        <MiniMetric label="Model" value={branch.generation.model_id || '-'} />
        <MiniMetric label="Error" value={branch.generation.error_code || '-'} />
      </div>
    </BackofficeSectionPanel>
  );
}

function TextBlock({
  title,
  value,
  compact = false,
}: {
  title: string;
  value: string;
  compact?: boolean;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{title}</p>
      <p
        className={cn(
          'mt-2 whitespace-pre-wrap rounded-xl border border-slate-200/80 bg-white/70 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-200',
          compact ? 'px-3 py-2' : 'min-h-[7.5rem] px-4 py-3'
        )}
      >
        {value}
      </p>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-1 truncate font-mono text-xs text-slate-700 dark:text-slate-200">{value}</p>
    </div>
  );
}

function AdminAiAdvisorContent() {
  const { t } = useLocale();
  const [data, setData] = useState<AdvisorPreviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [scope, setScope] = useState('operations');
  const [siteIdInput, setSiteIdInput] = useState('');
  const [siteId, setSiteId] = useState('');
  const [providerIdInput, setProviderIdInput] = useState('openai');
  const [providerId, setProviderId] = useState('openai');
  const [modelIdInput, setModelIdInput] = useState('deepseek-v4-flash');
  const [modelId, setModelId] = useState('deepseek-v4-flash');
  const [reloadKey, setReloadKey] = useState(0);

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      params.set('scope', scope);
      if (siteId.trim()) {
        params.set('site_id', siteId.trim());
      }
      if (providerId.trim()) {
        params.set('provider_id', providerId.trim());
      }
      if (modelId.trim()) {
        params.set('model_id', modelId.trim());
      }

      const response = await fetch(`/api/admin/advisor/ops-summary-preview?${params.toString()}`, {
        credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok || payload?.status === 'error') {
        throw payload;
      }
      setData(normalizePreview(payload?.data ?? {}));
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [modelId, providerId, scope, siteId, t]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview, reloadKey]);

  const metricItems = useMemo(() => {
    const comparison = data?.comparison;
    return [
      {
        label: 'AI called',
        value: comparison?.aiCalled ? 'Yes' : 'No',
        detail: valueCheckLabel(comparison?.valueCheck || ''),
        toneClassName: comparison?.aiCalled ? 'text-emerald-600 dark:text-emerald-300' : 'text-slate-600 dark:text-slate-300',
      },
      {
        label: 'Text changed',
        value: comparison?.textChanged ? 'Yes' : 'No',
        detail: 'Baseline vs AI branch',
      },
      {
        label: 'Tokens',
        value: formatNumber((comparison?.tokensIn || 0) + (comparison?.tokensOut || 0)),
        detail: `${formatNumber(comparison?.tokensIn || 0)} in / ${formatNumber(comparison?.tokensOut || 0)} out`,
      },
      {
        label: 'Cost',
        value: formatCost(comparison?.cost || 0),
        detail: comparison?.errorCode ? `Error: ${comparison.errorCode}` : 'Provider reported cost',
        size: 'compact' as const,
      },
    ];
  }, [data]);

  if (loading && !data) {
    return <LoadingFallback />;
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-red-600">{t('common.error')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{error}</p>
          <button onClick={() => void loadPreview()} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow="Operator surface"
        title="AI Operations Advisor"
        description="Compare rule analysis against the AI branch using real cloud operations signals."
        aside={
          data ? (
            <div className="w-full xl:w-[42rem]">
              <BackofficeMetricStrip columnsClassName="md:grid-cols-2 xl:grid-cols-4" items={metricItems} />
            </div>
          ) : undefined
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          {SCOPE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setScope(option.value)}
              className={cn(
                'h-8 rounded-full border px-3 text-xs font-semibold transition',
                scope === option.value
                  ? 'border-blue-600 bg-blue-600 text-white dark:border-blue-400 dark:bg-blue-500'
                  : 'border-slate-200 bg-white/80 text-slate-700 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200'
              )}
            >
              {option.label}
            </button>
          ))}
          <span className="mx-1 h-5 w-px bg-slate-200 dark:bg-slate-700" />
          <input
            type="text"
            value={siteIdInput}
            onChange={(event) => setSiteIdInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                setSiteId(siteIdInput.trim());
              }
            }}
            placeholder="site_id"
            className="h-8 w-48 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
          />
          <input
            type="text"
            value={providerIdInput}
            onChange={(event) => setProviderIdInput(event.target.value)}
            placeholder="provider_id"
            className="h-8 w-40 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
          />
          <input
            type="text"
            value={modelIdInput}
            onChange={(event) => setModelIdInput(event.target.value)}
            placeholder="model_id"
            className="h-8 w-56 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
          />
          <button
            type="button"
            onClick={() => {
              setSiteId(siteIdInput.trim());
              setProviderId(providerIdInput.trim());
              setModelId(modelIdInput.trim() || 'deepseek-v4-flash');
              setReloadKey((current) => current + 1);
            }}
            disabled={loading}
            className="h-8 rounded-full bg-slate-950 px-4 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60 dark:bg-blue-500 dark:text-slate-950 dark:hover:bg-blue-400"
          >
            {loading ? 'Loading' : 'Run preview'}
          </button>
        </div>
      </BackofficePrimaryPanel>

      {data ? (
        <>
          <div className="grid gap-5 xl:grid-cols-2">
            <BranchPanel title="Baseline" branch={data.baseline} accent="baseline" />
            <BranchPanel title="AI output" branch={data.ai} accent="ai" />
          </div>

          <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
            <SignalPanel branch={data.ai} />

            <BackofficeSectionPanel className="space-y-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                    Decision
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                    {valueCheckLabel(data.comparison.valueCheck)}
                  </h2>
                </div>
                <BackofficeStatusBadge
                  label={data.comparison.valueCheck}
                  status={valueCheckStatus(data.comparison.valueCheck)}
                />
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <BackofficeStackCard>
                  <MiniMetric label="Baseline mode" value={data.comparison.baselineMode || '-'} />
                </BackofficeStackCard>
                <BackofficeStackCard>
                  <MiniMetric label="AI mode" value={data.comparison.aiMode || '-'} />
                </BackofficeStackCard>
                <BackofficeStackCard>
                  <MiniMetric label="Requested provider" value={data.comparison.requestedProviderId || '-'} />
                </BackofficeStackCard>
                <BackofficeStackCard>
                  <MiniMetric label="Model" value={data.comparison.modelId || '-'} />
                </BackofficeStackCard>
              </div>
            </BackofficeSectionPanel>
          </div>
          <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  Safety
                </p>
                <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">Execution boundary</h2>
              </div>
              <div className="space-y-3">
                <SafetyRow label="Prompt storage blocked" ok={!data.safety.promptSaved} />
                <SafetyRow label="Output text storage blocked" ok={!data.safety.outputTextSaved} />
                <SafetyRow label="WordPress writes blocked" ok={!data.safety.wordpressWriteAllowed} />
                <SafetyRow
                  label="Customer article generation blocked"
                  ok={!data.safety.customerArticleGenerationAllowed}
                />
                <SafetyRow label="Operator review required" ok={data.safety.requiresOperatorReview} />
              </div>
            </BackofficeSectionPanel>
          </div>
        </>
      ) : null}
    </BackofficePageStack>
  );
}

function SignalPanel({ branch }: { branch: SummaryBranch }) {
  const signals = branch.source_context.advisor.signals;
  const evidence = branch.source_context.advisor.evidence;
  return (
    <BackofficeSectionPanel className="space-y-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          Evidence
        </p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">AI input signals</h2>
      </div>
      <div className="space-y-3">
        {signals.length ? (
          signals.map((signal, index) => <SignalRow key={`${String(signal.code || 'signal')}-${index}`} signal={signal} />)
        ) : (
          <p className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
            No redacted operations signals were passed to the AI branch.
          </p>
        )}
      </div>
      <div className="border-t border-slate-200/80 pt-4 dark:border-slate-800">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
          Sources
        </p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {evidence.map((item) => (
            <div
              key={`${item.kind}-${item.ref}`}
              className="rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/35"
            >
              <p className="text-sm font-medium text-slate-800 dark:text-slate-100">{item.label || item.kind}</p>
              <p className="mt-1 truncate font-mono text-[0.7rem] text-slate-500 dark:text-slate-400">{item.ref}</p>
            </div>
          ))}
        </div>
      </div>
    </BackofficeSectionPanel>
  );
}

function SignalRow({ signal }: { signal: Record<string, string | number | boolean | null> }) {
  const entries = Object.entries(signal).filter(([key]) => key !== 'code');
  return (
    <div className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/35">
      <p className="font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">{String(signal.code || 'signal')}</p>
      <div className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map(([key, value]) => (
          <div key={key} className="min-w-0">
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
              {key}
            </p>
            <p className="mt-1 truncate font-mono text-xs text-slate-700 dark:text-slate-200">{String(value ?? '-')}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function SafetyRow({
  label,
  ok,
}: {
  label: string;
  ok: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/35">
      <span className="text-sm text-slate-700 dark:text-slate-200">{label}</span>
      <BackofficeStatusBadge label={ok ? 'ok' : 'blocked'} status={ok ? 'success' : 'error'} />
    </div>
  );
}

export default function AdminAiAdvisorPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminAiAdvisorContent />
    </Suspense>
  );
}
