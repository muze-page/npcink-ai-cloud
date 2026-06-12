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
    request_cost?: number;
    cache_status?: string;
    cache_hit?: boolean;
    cache_expires_at?: string;
    cache_key?: string;
  };
  scope: string;
  ai_disclosure: {
    version: string;
    content_origin: string;
    generated_by_ai: boolean;
    ai_assisted: boolean;
    visible_label_required: boolean;
    visible_label: string;
    brand_label: string;
    visible_notice: string;
    review_status: string;
    provider_brand_visible: boolean;
    machine_readable_required: boolean;
    copy_export_notice: string;
    source_generation_mode: string;
    generated_at: string;
    reviewed_by: string;
    reviewed_at: string;
    review_note: string;
  };
  headline: string;
  operator_summary: string;
  support_draft: string;
  operator_next_step: string;
  safety_note: string;
  severity: string;
  status: string;
  agentRegistryMetadata: AgentHandoff;
  source_context: {
    advisor: {
      scope: string;
      agent_handoff: AgentHandoff;
      evidence: Array<{ kind: string; ref: string; label: string }>;
      signals: Array<Record<string, string | number | boolean | null>>;
      drilldown: Record<string, DrilldownValue>;
    };
  };
};

type ScalarValue = string | number | boolean | null;
type DrilldownValue = Array<Record<string, ScalarValue>> | Record<string, ScalarValue | Record<string, ScalarValue>>;

type AgentHandoff = {
  agentId: string;
  agentVersion: string;
  agentRole: string;
  handoffType: string;
  handoffOwner: string;
  requiresOperatorReview: boolean;
  directWordPressWrite: boolean;
  executionPattern: string;
  storageMode: string;
  allowedActions: string[];
  stopConditions: string[];
  forbiddenActions: string[];
  failClosedBehavior: string;
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
    aiUsed: boolean;
    aiCalled: boolean;
    cacheHit: boolean;
    cacheStatus: string;
    textChanged: boolean;
    tokensIn: number;
    tokensOut: number;
    cost: number;
    requestCost: number;
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

type AdvisorHistoryItem = {
  cacheKey: string;
  siteId: string;
  scope: string;
  status: string;
  severity: string;
  headline: string;
  operatorSummary: string;
  operatorNextStep: string;
  draftKind: string;
  generatedAt: string;
  freshUntil: string;
  isStale: boolean;
  generation: {
    mode: string;
    providerId: string;
    modelId: string;
    tokensIn: number;
    tokensOut: number;
    cost: number;
    requestCost: number;
    cacheStatus: string;
    cacheHit: boolean;
  };
  aiDisclosure: {
    contentOrigin: string;
    generatedByAi: boolean;
    visibleLabel: string;
    reviewStatus: string;
    reviewedBy: string;
    reviewedAt: string;
    sourceGenerationMode: string;
  };
};

type AdvisorValueMetrics = {
  valueMetricsVersion: string;
  window: {
    days: number;
    startAt: string;
    endAt: string;
  };
  totals: {
    analysisRequests: number;
    aiUsed: number;
    aiCalled: number;
    cacheHits: number;
    deterministicFallbacks: number;
    providerErrors: number;
    blocked: number;
    tokensIn: number;
    tokensOut: number;
    tokensTotal: number;
    cost: number;
    requestCost: number;
    estimatedCacheSavings: number;
  };
  rates: {
    aiUsageRate: number;
    aiCallRate: number;
    cacheHitRate: number;
    fallbackRate: number;
    reviewRate: number;
    confirmedRate: number;
    editedAfterAiRate: number;
    averageLiveRequestCost: number;
  };
  review: {
    cachedAiItems: number;
    needsReview: number;
    humanConfirmed: number;
    editedAfterAi: number;
    reviewed: number;
  };
  valueSignal: {
    status: string;
    headline: string;
    nextStep: string;
  };
  breakdown: {
    byGenerationMode: Record<string, number>;
    byOutcome: Record<string, number>;
    byProvider: Array<{
      providerId: string;
      requests: number;
      aiCalls: number;
      cost: number;
    }>;
    byModel: Array<{
      modelId: string;
      requests: number;
      aiCalls: number;
      cost: number;
    }>;
  };
  recentEvents: Array<{
    createdAt: string;
    siteId: string;
    scope: string;
    outcome: string;
    generationMode: string;
    providerId: string;
    modelId: string;
    tokensIn: number;
    tokensOut: number;
    cost: number;
    cacheHit: boolean;
    errorCode: string;
  }>;
};

type ScenarioCheck = {
  key: string;
  title: string;
  status: string;
  headline: string;
  evidence: string;
  aiValue: string;
};

const SCOPE_OPTIONS = [
  { label: 'Operations', value: 'operations' },
  { label: 'Runtime', value: 'runtime' },
  { label: 'Commercial', value: 'commercial' },
  { label: 'Routing', value: 'routing' },
];

function normalizeBranch(raw: any): SummaryBranch {
  const generation = raw?.generation ?? {};
  const disclosure = raw?.ai_disclosure ?? {};
  const handoff = raw?.source_context?.advisor?.agent_handoff ?? {};
  const registryHandoff = raw?.agent_registry_metadata ?? raw?.agent_handoff ?? handoff;
  return {
    generation: {
      mode: String(generation.mode ?? ''),
      provider_id: String(generation.provider_id ?? ''),
      model_id: String(generation.model_id ?? ''),
      error_code: String(generation.error_code ?? ''),
      tokens_in: Number(generation.tokens_in ?? 0),
      tokens_out: Number(generation.tokens_out ?? 0),
      cost: Number(generation.cost ?? 0),
      request_cost: Number(generation.request_cost ?? generation.cost ?? 0),
      cache_status: String(generation.cache_status ?? ''),
      cache_hit: Boolean(generation.cache_hit),
      cache_expires_at: String(generation.cache_expires_at ?? ''),
      cache_key: String(generation.cache_key ?? ''),
    },
    scope: String(raw?.scope ?? ''),
    ai_disclosure: {
      version: String(disclosure.version ?? ''),
      content_origin: String(disclosure.content_origin ?? ''),
      generated_by_ai: Boolean(disclosure.generated_by_ai),
      ai_assisted: Boolean(disclosure.ai_assisted),
      visible_label_required: Boolean(disclosure.visible_label_required),
      visible_label: String(disclosure.visible_label ?? ''),
      brand_label: String(disclosure.brand_label ?? 'Magick AI'),
      visible_notice: String(disclosure.visible_notice ?? ''),
      review_status: String(disclosure.review_status ?? ''),
      provider_brand_visible: Boolean(disclosure.provider_brand_visible),
      machine_readable_required: Boolean(disclosure.machine_readable_required),
      copy_export_notice: String(disclosure.copy_export_notice ?? ''),
      source_generation_mode: String(disclosure.source_generation_mode ?? ''),
      generated_at: String(disclosure.generated_at ?? ''),
      reviewed_by: String(disclosure.reviewed_by ?? ''),
      reviewed_at: String(disclosure.reviewed_at ?? ''),
      review_note: String(disclosure.review_note ?? ''),
    },
    headline: String(raw?.headline ?? ''),
    operator_summary: String(raw?.operator_summary ?? ''),
    support_draft: String(raw?.support_draft ?? ''),
    operator_next_step: String(raw?.operator_next_step ?? ''),
    safety_note: String(raw?.safety_note ?? ''),
    severity: String(raw?.severity ?? ''),
    status: String(raw?.status ?? ''),
    agentRegistryMetadata: normalizeAgentHandoff(registryHandoff),
    source_context: {
      advisor: {
        scope: String(raw?.source_context?.advisor?.scope ?? ''),
        agent_handoff: normalizeAgentHandoff(handoff),
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
        drilldown:
          raw?.source_context?.advisor?.drilldown && typeof raw.source_context.advisor.drilldown === 'object'
            ? (raw.source_context.advisor.drilldown as Record<string, DrilldownValue>)
            : {},
      },
    },
  };
}

function normalizeAgentHandoff(raw: any): AgentHandoff {
  return {
    agentId: String(raw?.agent_id ?? ''),
    agentVersion: String(raw?.agent_version ?? ''),
    agentRole: String(raw?.agent_role ?? ''),
    handoffType: String(raw?.handoff_type ?? ''),
    handoffOwner: String(raw?.handoff_owner ?? ''),
    requiresOperatorReview: Boolean(raw?.requires_operator_review),
    directWordPressWrite: Boolean(raw?.direct_wordpress_write),
    executionPattern: String(raw?.execution_pattern ?? ''),
    storageMode: String(raw?.storage_mode ?? ''),
    allowedActions: Array.isArray(raw?.allowed_actions) ? raw.allowed_actions.map(String) : [],
    stopConditions: Array.isArray(raw?.stop_conditions) ? raw.stop_conditions.map(String) : [],
    forbiddenActions: Array.isArray(raw?.forbidden_actions) ? raw.forbidden_actions.map(String) : [],
    failClosedBehavior: String(raw?.fail_closed_behavior ?? ''),
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
      aiUsed: Boolean(comparison.ai_used),
      aiCalled: Boolean(comparison.ai_called),
      cacheHit: Boolean(comparison.cache_hit),
      cacheStatus: String(comparison.cache_status ?? ''),
      textChanged: Boolean(comparison.text_changed),
      tokensIn: Number(comparison.tokens_in ?? 0),
      tokensOut: Number(comparison.tokens_out ?? 0),
      cost: Number(comparison.cost ?? 0),
      requestCost: Number(comparison.request_cost ?? comparison.cost ?? 0),
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

function normalizeHistoryItem(raw: any): AdvisorHistoryItem {
  const generation = raw?.generation ?? {};
  const disclosure = raw?.ai_disclosure ?? {};
  return {
    cacheKey: String(raw?.cache_key ?? ''),
    siteId: String(raw?.site_id ?? ''),
    scope: String(raw?.scope ?? ''),
    status: String(raw?.status ?? ''),
    severity: String(raw?.severity ?? ''),
    headline: String(raw?.headline ?? ''),
    operatorSummary: String(raw?.operator_summary ?? ''),
    operatorNextStep: String(raw?.operator_next_step ?? ''),
    draftKind: String(raw?.draft_kind ?? ''),
    generatedAt: String(raw?.generated_at ?? ''),
    freshUntil: String(raw?.fresh_until ?? ''),
    isStale: Boolean(raw?.is_stale),
    generation: {
      mode: String(generation.mode ?? ''),
      providerId: String(generation.provider_id ?? ''),
      modelId: String(generation.model_id ?? ''),
      tokensIn: Number(generation.tokens_in ?? 0),
      tokensOut: Number(generation.tokens_out ?? 0),
      cost: Number(generation.cost ?? 0),
      requestCost: Number(generation.request_cost ?? 0),
      cacheStatus: String(generation.cache_status ?? ''),
      cacheHit: Boolean(generation.cache_hit),
    },
    aiDisclosure: {
      contentOrigin: String(disclosure.content_origin ?? ''),
      generatedByAi: Boolean(disclosure.generated_by_ai),
      visibleLabel: String(disclosure.visible_label ?? ''),
      reviewStatus: String(disclosure.review_status ?? ''),
      reviewedBy: String(disclosure.reviewed_by ?? ''),
      reviewedAt: String(disclosure.reviewed_at ?? ''),
      sourceGenerationMode: String(disclosure.source_generation_mode ?? ''),
    },
  };
}

function normalizeValueMetrics(raw: any): AdvisorValueMetrics {
  const totals = raw?.totals ?? {};
  const rates = raw?.rates ?? {};
  const review = raw?.review ?? {};
  const valueSignal = raw?.value_signal ?? {};
  const breakdown = raw?.breakdown ?? {};
  const window = raw?.window ?? {};
  return {
    valueMetricsVersion: String(raw?.value_metrics_version ?? ''),
    window: {
      days: Number(window.days ?? 0),
      startAt: String(window.start_at ?? ''),
      endAt: String(window.end_at ?? ''),
    },
    totals: {
      analysisRequests: Number(totals.analysis_requests ?? 0),
      aiUsed: Number(totals.ai_used ?? 0),
      aiCalled: Number(totals.ai_called ?? 0),
      cacheHits: Number(totals.cache_hits ?? 0),
      deterministicFallbacks: Number(totals.deterministic_fallbacks ?? 0),
      providerErrors: Number(totals.provider_errors ?? 0),
      blocked: Number(totals.blocked ?? 0),
      tokensIn: Number(totals.tokens_in ?? 0),
      tokensOut: Number(totals.tokens_out ?? 0),
      tokensTotal: Number(totals.tokens_total ?? 0),
      cost: Number(totals.cost ?? 0),
      requestCost: Number(totals.request_cost ?? 0),
      estimatedCacheSavings: Number(totals.estimated_cache_savings ?? 0),
    },
    rates: {
      aiUsageRate: Number(rates.ai_usage_rate ?? 0),
      aiCallRate: Number(rates.ai_call_rate ?? 0),
      cacheHitRate: Number(rates.cache_hit_rate ?? 0),
      fallbackRate: Number(rates.fallback_rate ?? 0),
      reviewRate: Number(rates.review_rate ?? 0),
      confirmedRate: Number(rates.confirmed_rate ?? 0),
      editedAfterAiRate: Number(rates.edited_after_ai_rate ?? 0),
      averageLiveRequestCost: Number(rates.average_live_request_cost ?? 0),
    },
    review: {
      cachedAiItems: Number(review.cached_ai_items ?? 0),
      needsReview: Number(review.needs_review ?? 0),
      humanConfirmed: Number(review.human_confirmed ?? 0),
      editedAfterAi: Number(review.edited_after_ai ?? 0),
      reviewed: Number(review.reviewed ?? 0),
    },
    valueSignal: {
      status: String(valueSignal.status ?? ''),
      headline: String(valueSignal.headline ?? ''),
      nextStep: String(valueSignal.next_step ?? ''),
    },
    breakdown: {
      byGenerationMode: breakdown.by_generation_mode ?? {},
      byOutcome: breakdown.by_outcome ?? {},
      byProvider: Array.isArray(breakdown.by_provider)
        ? breakdown.by_provider.map((item: any) => ({
            providerId: String(item.provider_id ?? ''),
            requests: Number(item.requests ?? 0),
            aiCalls: Number(item.ai_calls ?? 0),
            cost: Number(item.cost ?? 0),
          }))
        : [],
      byModel: Array.isArray(breakdown.by_model)
        ? breakdown.by_model.map((item: any) => ({
            modelId: String(item.model_id ?? ''),
            requests: Number(item.requests ?? 0),
            aiCalls: Number(item.ai_calls ?? 0),
            cost: Number(item.cost ?? 0),
          }))
        : [],
    },
    recentEvents: Array.isArray(raw?.recent_events)
      ? raw.recent_events.map((item: any) => ({
          createdAt: String(item.created_at ?? ''),
          siteId: String(item.site_id ?? ''),
          scope: String(item.scope ?? ''),
          outcome: String(item.outcome ?? ''),
          generationMode: String(item.generation_mode ?? ''),
          providerId: String(item.provider_id ?? ''),
          modelId: String(item.model_id ?? ''),
          tokensIn: Number(item.tokens_in ?? 0),
          tokensOut: Number(item.tokens_out ?? 0),
          cost: Number(item.cost ?? 0),
          cacheHit: Boolean(item.cache_hit),
          errorCode: String(item.error_code ?? ''),
        }))
      : [],
  };
}

function formatCost(value: number): string {
  return `$${Number(value || 0).toFixed(6)}`;
}

function formatPercent(value: number): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function formatRatio(value: unknown): string {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) {
    return '0.0%';
  }
  return `${(numeric * 100).toFixed(1)}%`;
}

function humanizeKey(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function getSignal(branch: SummaryBranch, code: string): Record<string, string | number | boolean | null> {
  return branch.source_context.advisor.signals.find((signal) => signal.code === code) ?? {};
}

function getDrilldownRows(branch: SummaryBranch, key: string): Array<Record<string, ScalarValue>> {
  const value = branch.source_context.advisor.drilldown[key];
  return Array.isArray(value) ? value : [];
}

function textContainsAny(text: string, candidates: Array<string | number | null | undefined>): boolean {
  const normalized = text.toLowerCase();
  return candidates.some((candidate) => {
    const value = String(candidate ?? '').trim().toLowerCase();
    return Boolean(value && normalized.includes(value));
  });
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

function reviewStatusLabel(value: string): string {
  switch (value) {
    case 'needs_review':
      return 'Needs human review';
    case 'human_confirmed':
      return 'Human confirmed';
    case 'edited_after_ai':
      return 'Edited after AI';
    case 'not_ai_generated':
      return 'Rule generated';
    default:
      return value || 'Unknown';
  }
}

function reviewStatusBadge(value: string): string {
  if (value === 'needs_review') return 'warning';
  if (value === 'human_confirmed') return 'success';
  if (value === 'edited_after_ai') return 'warning';
  return 'inactive';
}

function buildDisclosureClipboardText(value: string, disclosure: SummaryBranch['ai_disclosure']): string {
  const notice = disclosure.copy_export_notice || disclosure.visible_notice || 'AI generated by Magick AI.';
  return `${notice}\n\n${value}`.trim();
}

function AiDisclosureBanner({
  branch,
  onReview,
  onCopy,
  reviewing = false,
}: {
  branch: SummaryBranch;
  onReview?: (reviewStatus: 'human_confirmed' | 'edited_after_ai') => void;
  onCopy?: (value: string, disclosure: SummaryBranch['ai_disclosure']) => void;
  reviewing?: boolean;
}) {
  const disclosure = branch.ai_disclosure;
  if (!disclosure.visible_label_required && !disclosure.generated_by_ai) {
    return null;
  }
  const canReview = Boolean(onReview && branch.generation.cache_key && disclosure.generated_by_ai);
  const isConfirmed = disclosure.review_status === 'human_confirmed';

  return (
    <div className="rounded-xl border border-blue-200 bg-white/80 px-3 py-3 dark:border-blue-900/70 dark:bg-slate-950/45">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-xs font-black text-white shadow-sm dark:bg-blue-400 dark:text-slate-950">
            AI
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {disclosure.brand_label || 'Magick AI'} · {disclosure.visible_label || 'AI generated'}
            </p>
            <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
              {disclosure.visible_notice || 'Generated by Magick AI. Human review required before use.'}
            </p>
          </div>
        </div>
        <BackofficeStatusBadge
          label={reviewStatusLabel(disclosure.review_status)}
          status={reviewStatusBadge(disclosure.review_status)}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-blue-100 pt-3 dark:border-blue-900/50">
        <button
          type="button"
          onClick={() => onCopy?.(branch.operator_summary, disclosure)}
          className="h-8 rounded-lg border border-blue-200 bg-blue-50 px-3 text-xs font-semibold text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 dark:border-blue-900/70 dark:bg-blue-950/35 dark:text-blue-300"
        >
          Copy summary with label
        </button>
        <button
          type="button"
          onClick={() => onReview?.('human_confirmed')}
          disabled={!canReview || reviewing || isConfirmed}
          className="h-8 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-blue-500 dark:text-slate-950 dark:hover:bg-blue-400"
        >
          {isConfirmed ? 'Confirmed' : reviewing ? 'Saving' : 'Confirm'}
        </button>
        <button
          type="button"
          onClick={() => onReview?.('edited_after_ai')}
          disabled={!canReview || reviewing}
          className="h-8 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:border-slate-300 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
        >
          Mark edited
        </button>
        {disclosure.reviewed_at ? (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Reviewed {disclosure.reviewed_at}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function BranchPanel({
  title,
  branch,
  accent,
  onReviewDisclosure,
  onCopyWithDisclosure,
  reviewingDisclosure = false,
}: {
  title: string;
  branch: SummaryBranch;
  accent: 'baseline' | 'ai';
  onReviewDisclosure?: (reviewStatus: 'human_confirmed' | 'edited_after_ai') => void;
  onCopyWithDisclosure?: (value: string, disclosure: SummaryBranch['ai_disclosure']) => void;
  reviewingDisclosure?: boolean;
}) {
  const generationStatus =
    branch.generation.mode === 'llm' || branch.generation.mode === 'llm_cached'
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
        {accent === 'ai' ? (
          <div className="mt-3">
            <AiDisclosureBanner
              branch={branch}
              onReview={onReviewDisclosure}
              onCopy={onCopyWithDisclosure}
              reviewing={reviewingDisclosure}
            />
          </div>
        ) : null}
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {branch.operator_summary || 'No operator summary.'}
        </p>
      </div>

      <div className="space-y-4">
        <TextBlock
          title="Support draft"
          value={branch.support_draft || 'No support draft.'}
          disclosure={accent === 'ai' ? branch.ai_disclosure : undefined}
          onCopyWithDisclosure={accent === 'ai' ? onCopyWithDisclosure : undefined}
        />
        <TextBlock title="Next step" value={branch.operator_next_step || 'No next step.'} compact />
        <TextBlock title="Safety note" value={branch.safety_note || 'No safety note.'} compact />
      </div>

      <div className="mt-auto grid gap-3 border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800 sm:grid-cols-3">
        <MiniMetric label="Provider" value={branch.generation.provider_id || '-'} />
        <MiniMetric label="Model" value={branch.generation.model_id || '-'} />
        <MiniMetric
          label="Cache"
          value={
            branch.generation.cache_hit
              ? `hit until ${branch.generation.cache_expires_at || '-'}`
              : branch.generation.cache_status || 'none'
          }
        />
      </div>
    </BackofficeSectionPanel>
  );
}

function TextBlock({
  title,
  value,
  compact = false,
  disclosure,
  onCopyWithDisclosure,
}: {
  title: string;
  value: string;
  compact?: boolean;
  disclosure?: SummaryBranch['ai_disclosure'];
  onCopyWithDisclosure?: (value: string, disclosure: SummaryBranch['ai_disclosure']) => void;
}) {
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{title}</p>
        {disclosure?.visible_label_required ? (
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[0.66rem] font-bold uppercase tracking-[0.14em] text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/35 dark:text-blue-300">
              {disclosure.visible_label || 'AI generated'}
            </span>
            <button
              type="button"
              onClick={() => onCopyWithDisclosure?.(value, disclosure)}
              className="text-xs font-semibold text-blue-700 underline-offset-4 hover:underline dark:text-blue-300"
            >
              Copy with AI label
            </button>
          </div>
        ) : null}
      </div>
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

function HistoryPanel({ items }: { items: AdvisorHistoryItem[] }) {
  return (
    <BackofficeSectionPanel className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            History
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">AI analysis history</h2>
        </div>
        <BackofficeStatusBadge label={`${items.length} stored`} status={items.length ? 'success' : 'inactive'} />
      </div>
      <div className="space-y-3">
        {items.length ? (
          items.map((item) => <HistoryRow key={item.cacheKey || `${item.generatedAt}-${item.headline}`} item={item} />)
        ) : (
          <p className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
            No stored AI analysis has been generated for this filter yet.
          </p>
        )}
      </div>
    </BackofficeSectionPanel>
  );
}

function HistoryRow({ item }: { item: AdvisorHistoryItem }) {
  return (
    <div className="rounded-xl border border-slate-200/80 bg-white/75 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/35">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.headline || 'AI analysis'}</p>
            <BackofficeStatusBadge
              label={reviewStatusLabel(item.aiDisclosure.reviewStatus)}
              status={reviewStatusBadge(item.aiDisclosure.reviewStatus)}
            />
            {item.isStale ? <BackofficeStatusBadge label="stale" status="warning" /> : null}
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {item.operatorSummary || 'No summary stored.'}
          </p>
        </div>
        <div className="grid min-w-[18rem] gap-2 text-right text-xs text-slate-500 dark:text-slate-400">
          <span>{item.generatedAt || '-'}</span>
          <span className="font-mono">
            {item.generation.mode || '-'} · {formatCost(item.generation.cost)}
          </span>
        </div>
      </div>
      <div className="mt-3 grid gap-3 border-t border-slate-200/80 pt-3 dark:border-slate-800 sm:grid-cols-4">
        <MiniMetric label="Scope" value={item.scope || '-'} />
        <MiniMetric label="Site" value={item.siteId || 'platform'} />
        <MiniMetric label="Model" value={item.generation.modelId || '-'} />
        <MiniMetric label="Next step" value={item.operatorNextStep || '-'} />
      </div>
    </div>
  );
}

function EffectComparisonPanel({ data }: { data: AdvisorPreviewData }) {
  const runtime = getSignal(data.ai, 'ops.runtime_quality');
  const usage = getSignal(data.ai, 'ops.usage_cost');
  const knowledge = getSignal(data.ai, 'ops.knowledge_quality');
  const failedRun = getDrilldownRows(data.ai, 'failed_runs')[0];
  const aiText = [
    data.ai.headline,
    data.ai.operator_summary,
    data.ai.support_draft,
    data.ai.operator_next_step,
  ].join(' ');
  const aiMentionsRun = textContainsAny(aiText, [
    String(failedRun?.run_id ?? ''),
    String(failedRun?.site_id ?? ''),
    String(failedRun?.error_code ?? ''),
    String(failedRun?.ability_name ?? ''),
  ]);
  const aiAddedSpecificity = data.comparison.textChanged && aiMentionsRun;

  return (
    <BackofficeSectionPanel className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            Effect check
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            Data, rule result, and AI result side by side
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            This view uses the same cloud operations evidence for both branches, so the visible difference is the AI
            layer&apos;s interpretation and next-step wording.
          </p>
        </div>
        <BackofficeStatusBadge
          label={data.comparison.aiUsed ? 'ai participated' : 'rule only'}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <ComparisonColumn
          eyebrow="Raw operations data"
          title={failedRun ? String(failedRun.error_code || 'Runtime signal') : 'Current operations signal'}
          statusLabel={`${formatNumber(Number(runtime.total_runs || 0))} runs`}
          status={Number(runtime.failed_runs || 0) > 0 ? 'warning' : 'success'}
          rows={[
            ['Failed runs', formatNumber(Number(runtime.failed_runs || 0))],
            ['Failure rate', formatRatio(runtime.run_failure_rate)],
            ['Guard events', formatNumber(Number(runtime.guard_events || 0))],
            ['Knowledge no-hit', formatRatio(knowledge.knowledge_no_hit_rate)],
            ['Usage events', formatNumber(Number(usage.usage_events || 0))],
          ]}
          detail={
            failedRun
              ? [
                  `run_id: ${String(failedRun.run_id || '-')}`,
                  `site_id: ${String(failedRun.site_id || '-')}`,
                  `ability: ${String(failedRun.ability_family || '-')}/${String(failedRun.ability_name || '-')}`,
                ]
              : ['No failed run detail in the current window.']
          }
        />
        <ComparisonColumn
          eyebrow="Rule analysis"
          title={data.baseline.headline || 'Rule baseline'}
          statusLabel={data.baseline.generation.mode || 'rule'}
          status="inactive"
          rows={[
            ['Mode', data.baseline.generation.mode || '-'],
            ['Status', data.baseline.status || '-'],
            ['Severity', data.baseline.severity || '-'],
            ['Next step', data.baseline.operator_next_step || '-'],
          ]}
          detail={[data.baseline.operator_summary || 'No rule summary.']}
        />
        <ComparisonColumn
          eyebrow="AI analysis"
          title={data.ai.headline || 'AI output'}
          statusLabel={data.comparison.aiCalled ? 'live ai' : data.comparison.cacheHit ? 'cached ai' : 'not called'}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
          rows={[
            ['Mode', data.ai.generation.mode || '-'],
            ['Model', data.comparison.modelId || data.ai.generation.model_id || '-'],
            ['Cost', formatCost(data.comparison.requestCost || 0)],
            ['AI changed text', data.comparison.textChanged ? 'yes' : 'no'],
          ]}
          detail={[
            data.ai.operator_summary || 'No AI summary.',
            aiAddedSpecificity
              ? 'AI added concrete run, site, error, or ability details.'
              : 'No extra concrete identifier was detected in this output.',
          ]}
        />
      </div>
    </BackofficeSectionPanel>
  );
}

function ComparisonColumn({
  eyebrow,
  title,
  statusLabel,
  status,
  rows,
  detail,
}: {
  eyebrow: string;
  title: string;
  statusLabel: string;
  status: string;
  rows: Array<[string, string]>;
  detail: string[];
}) {
  return (
    <div className="flex min-h-[22rem] flex-col rounded-xl border border-slate-200/80 bg-white/75 p-4 dark:border-slate-800 dark:bg-slate-950/35">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            {eyebrow}
          </p>
          <h3 className="mt-2 text-base font-semibold leading-6 text-slate-950 dark:text-white">{title}</h3>
        </div>
        <BackofficeStatusBadge label={statusLabel} status={status} />
      </div>
      <div className="mt-4 grid gap-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-start justify-between gap-3 text-sm">
            <span className="text-slate-500 dark:text-slate-400">{label}</span>
            <span className="max-w-[12rem] truncate text-right font-mono text-xs text-slate-800 dark:text-slate-100">
              {value}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-auto space-y-2 border-t border-slate-200/80 pt-4 dark:border-slate-800">
        {detail.map((item, index) => (
          <p key={`${eyebrow}-${index}`} className="text-sm leading-6 text-slate-600 dark:text-slate-300">
            {item}
          </p>
        ))}
      </div>
    </div>
  );
}

function AiParticipationPanel({ data }: { data: AdvisorPreviewData }) {
  const inputTypes = buildAiInputTypes(data.ai);
  const valueBullets = buildAiValueBullets(data);
  return (
    <BackofficeSectionPanel className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            AI participation proof
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            What was sent to AI and what changed
          </h2>
        </div>
        <BackofficeStatusBadge
          label={data.comparison.aiCalled ? 'live call' : data.comparison.cacheHit ? 'cache hit' : 'not called'}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="grid gap-3 sm:grid-cols-2">
          <BackofficeStackCard>
            <MiniMetric label="Provider adapter" value={data.comparison.requestedProviderId || data.ai.generation.provider_id || '-'} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label="Model" value={data.comparison.modelId || data.ai.generation.model_id || '-'} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label="Tokens" value={`${formatNumber(data.comparison.tokensIn)} in / ${formatNumber(data.comparison.tokensOut)} out`} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label="Request cost" value={formatCost(data.comparison.requestCost || 0)} />
          </BackofficeStackCard>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <EvidenceList title="Input data types" items={inputTypes} empty="No redacted input types detected." />
          <EvidenceList title="AI added value" items={valueBullets} empty="No AI-specific difference detected yet." />
        </div>
      </div>
    </BackofficeSectionPanel>
  );
}

function EvidenceList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="rounded-xl border border-slate-200/80 bg-white/75 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/35">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{title}</p>
      <div className="mt-3 space-y-2">
        {items.length ? (
          items.map((item) => (
            <p key={item} className="text-sm leading-6 text-slate-700 dark:text-slate-200">
              {item}
            </p>
          ))
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">{empty}</p>
        )}
      </div>
    </div>
  );
}

function buildAiInputTypes(branch: SummaryBranch): string[] {
  const signals = branch.source_context.advisor.signals;
  const drilldown = branch.source_context.advisor.drilldown;
  const items: string[] = [];
  if (signals.some((signal) => signal.code === 'ops.runtime_quality')) {
    items.push('Runtime run quality: run counts, failures, callbacks, guard events.');
  }
  if (Array.isArray(drilldown.failed_runs) && drilldown.failed_runs.length > 0) {
    items.push('Failed run drilldown: run id, site id, ability, error code, selected provider/model.');
  }
  if (signals.some((signal) => signal.code === 'ops.knowledge_quality')) {
    items.push('Knowledge search health: no-hit rate, search failures, indexed documents and chunks.');
  }
  if (signals.some((signal) => signal.code === 'ops.provider_quality')) {
    items.push('Provider quality: provider calls, error rate, fallback count, latency.');
  }
  if (signals.some((signal) => signal.code === 'ops.usage_cost')) {
    items.push('Usage and cost signal: usage events, meter quantity, reported/provider cost.');
  }
  return items;
}

function buildAiValueBullets(data: AdvisorPreviewData): string[] {
  const failedRun = getDrilldownRows(data.ai, 'failed_runs')[0];
  const aiText = [
    data.ai.headline,
    data.ai.operator_summary,
    data.ai.support_draft,
    data.ai.operator_next_step,
  ].join(' ');
  const bullets: string[] = [];
  if (data.comparison.aiCalled) {
    bullets.push('A live provider call generated this analysis instead of only using deterministic rules.');
  } else if (data.comparison.cacheHit) {
    bullets.push('A previous AI analysis was reused from cache, avoiding another provider call.');
  }
  if (data.comparison.textChanged) {
    bullets.push('AI changed the operator-facing summary or next-step wording.');
  }
  if (
    failedRun &&
    textContainsAny(aiText, [
      String(failedRun.run_id ?? ''),
      String(failedRun.error_code ?? ''),
      String(failedRun.site_id ?? ''),
      String(failedRun.ability_name ?? ''),
    ])
  ) {
    bullets.push('AI surfaced concrete failed-run identifiers that an operator can inspect directly.');
  }
  if (data.ai.operator_next_step && data.ai.operator_next_step !== data.baseline.operator_next_step) {
    bullets.push('AI proposed a more specific operator next step than the rule baseline.');
  }
  return bullets;
}

function ScenarioChecksPanel({ data }: { data: AdvisorPreviewData }) {
  const scenarios = buildScenarioChecks(data);
  return (
    <BackofficeSectionPanel className="space-y-5">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          Fixed scenarios
        </p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
          Three repeatable ways to judge AI usefulness
        </h2>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        {scenarios.map((scenario) => (
          <BackofficeStackCard key={scenario.key} className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-950 dark:text-white">{scenario.title}</p>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{scenario.headline}</p>
              </div>
              <BackofficeStatusBadge label={scenario.status} status={scenario.status === 'active' ? 'warning' : 'inactive'} />
            </div>
            <div className="space-y-2 border-t border-slate-200/80 pt-3 dark:border-slate-800">
              <MiniMetric label="Evidence" value={scenario.evidence} />
              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">{scenario.aiValue}</p>
            </div>
          </BackofficeStackCard>
        ))}
      </div>
    </BackofficeSectionPanel>
  );
}

function AgentHandoffPanel({ handoff }: { handoff: AgentHandoff }) {
  const hasHandoff = Boolean(handoff.agentId || handoff.handoffType || handoff.agentRole);
  if (!hasHandoff) {
    return null;
  }

  return (
    <BackofficeSectionPanel className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            Agent handoff
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            Internal advisor agent boundary
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            Read-only operator recommendation metadata from the redacted advisor context.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <BackofficeStatusBadge
            label={handoff.directWordPressWrite ? 'write allowed' : 'write blocked'}
            status={handoff.directWordPressWrite ? 'error' : 'success'}
          />
          <BackofficeStatusBadge
            label={handoff.requiresOperatorReview ? 'review required' : 'review optional'}
            status={handoff.requiresOperatorReview ? 'warning' : 'inactive'}
          />
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <BackofficeStackCard>
          <MiniMetric label="Agent" value={handoff.agentId || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="Version" value={handoff.agentVersion || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="Handoff" value={handoff.handoffType || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="Owner" value={handoff.handoffOwner || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="Pattern" value={handoff.executionPattern || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="Storage" value={handoff.storageMode || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard className="md:col-span-2">
          <MiniMetric label="Fail closed" value={handoff.failClosedBehavior || '-'} />
        </BackofficeStackCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <EvidenceList
          title="Allowed actions"
          items={handoff.allowedActions.map(humanizeKey)}
          empty="No allowed actions declared."
        />
        <EvidenceList
          title="Stop conditions"
          items={handoff.stopConditions.map(humanizeKey)}
          empty="No stop conditions declared."
        />
        <EvidenceList
          title="Forbidden actions"
          items={handoff.forbiddenActions.map(humanizeKey)}
          empty="No forbidden actions declared."
        />
      </div>
    </BackofficeSectionPanel>
  );
}

function buildScenarioChecks(data: AdvisorPreviewData): ScenarioCheck[] {
  const runtime = getSignal(data.ai, 'ops.runtime_quality');
  const knowledge = getSignal(data.ai, 'ops.knowledge_quality');
  const provider = getSignal(data.ai, 'ops.provider_quality');
  const failedRun = getDrilldownRows(data.ai, 'failed_runs')[0];
  const providerCalls = Number(provider.provider_calls || 0);
  const providerErrorRate = Number(provider.provider_error_rate || 0);
  const avgLatency = Number(provider.avg_latency_ms || 0);

  return [
    {
      key: 'runtime_failure',
      title: 'Runtime failure analysis',
      status: Number(runtime.failed_runs || 0) > 0 ? 'active' : 'quiet',
      headline: failedRun
        ? `${String(failedRun.site_id || 'site')} has ${String(failedRun.error_code || 'a failed run')}.`
        : 'No failed runtime run in the current window.',
      evidence: `${formatNumber(Number(runtime.failed_runs || 0))} failed / ${formatNumber(Number(runtime.total_runs || 0))} runs`,
      aiValue: failedRun
        ? 'AI should explain the likely failure path and point to the concrete run/operator action.'
        : 'AI should stay quiet or confirm no runtime failure driver.',
    },
    {
      key: 'knowledge_no_hit',
      title: 'Knowledge no-hit analysis',
      status: Number(knowledge.knowledge_no_hits || 0) > 0 ? 'active' : 'quiet',
      headline: `${formatNumber(Number(knowledge.knowledge_searches || 0))} searches, ${formatRatio(knowledge.knowledge_no_hit_rate)} no-hit rate.`,
      evidence: `${formatNumber(Number(knowledge.indexed_documents || 0))} docs / ${formatNumber(Number(knowledge.indexed_chunks || 0))} chunks`,
      aiValue: 'AI should connect no-hit patterns to indexing, content coverage, or query-intent gaps.',
    },
    {
      key: 'provider_cost_latency',
      title: 'Provider cost or latency anomaly',
      status: providerErrorRate > 0 || avgLatency > 0 || providerCalls > 0 ? 'active' : 'quiet',
      headline: `${formatNumber(providerCalls)} provider calls, ${formatRatio(providerErrorRate)} error rate.`,
      evidence: `${formatNumber(avgLatency)} ms avg latency`,
      aiValue: 'AI should separate provider degradation from app/runtime failures before recommending action.',
    },
  ];
}

function valueSignalBadge(value: string): string {
  if (value === 'promising') return 'success';
  if (value === 'needs_review_loop' || value === 'provider_blocked') return 'warning';
  if (value === 'not_using_ai' || value === 'insufficient_data') return 'inactive';
  return 'inactive';
}

function ValueMetricsPanel({ valueMetrics }: { valueMetrics: AdvisorValueMetrics | null }) {
  if (!valueMetrics) {
    return null;
  }
  const topProvider = valueMetrics.breakdown.byProvider[0];
  const topModel = valueMetrics.breakdown.byModel[0];
  return (
    <BackofficeSectionPanel className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            Value tracking
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {valueMetrics.valueSignal.headline || 'AI value is not measured yet'}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {valueMetrics.valueSignal.nextStep || 'Run manual analyses and review outputs before expanding AI usage.'}
          </p>
        </div>
        <BackofficeStatusBadge
          label={valueMetrics.valueSignal.status || 'unknown'}
          status={valueSignalBadge(valueMetrics.valueSignal.status)}
        />
      </div>

      <BackofficeMetricStrip
        columnsClassName="md:grid-cols-2 xl:grid-cols-5"
        items={[
          {
            label: 'Requests',
            value: formatNumber(valueMetrics.totals.analysisRequests),
            detail: `${valueMetrics.window.days || 7} day window`,
          },
          {
            label: 'AI called',
            value: formatNumber(valueMetrics.totals.aiCalled),
            detail: `${formatPercent(valueMetrics.rates.aiCallRate)} live call rate`,
          },
          {
            label: 'Cache hit',
            value: formatPercent(valueMetrics.rates.cacheHitRate),
            detail: `${formatNumber(valueMetrics.totals.cacheHits)} cached analyses`,
          },
          {
            label: 'Request cost',
            value: formatCost(valueMetrics.totals.requestCost),
            detail: `${formatCost(valueMetrics.totals.estimatedCacheSavings)} estimated saved`,
            size: 'compact',
          },
          {
            label: 'Confirmed',
            value: formatPercent(valueMetrics.rates.confirmedRate),
            detail: `${formatNumber(valueMetrics.review.humanConfirmed)} confirmed / ${formatNumber(valueMetrics.review.cachedAiItems)} AI items`,
          },
        ]}
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.65fr)]">
        <div className="grid gap-3 sm:grid-cols-3">
          <BackofficeStackCard>
            <MiniMetric
              label="Needs review"
              value={formatNumber(valueMetrics.review.needsReview)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="Edited after AI"
              value={formatNumber(valueMetrics.review.editedAfterAi)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="Fallbacks"
              value={formatNumber(valueMetrics.totals.deterministicFallbacks)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="Provider errors"
              value={formatNumber(valueMetrics.totals.providerErrors)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="Top provider"
              value={topProvider ? `${topProvider.providerId} · ${formatCost(topProvider.cost)}` : '-'}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="Top model"
              value={topModel ? `${topModel.modelId} · ${formatCost(topModel.cost)}` : '-'}
            />
          </BackofficeStackCard>
        </div>
        <BackofficeStackCard>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            Recent AI events
          </p>
          <div className="mt-3 space-y-2">
            {valueMetrics.recentEvents.slice(0, 4).map((item, index) => (
              <div key={`${item.createdAt}-${index}`} className="flex items-center justify-between gap-3 text-xs">
                <span className="truncate text-slate-600 dark:text-slate-300">
                  {item.generationMode || '-'} · {item.outcome || '-'}
                </span>
                <span className="shrink-0 font-mono text-slate-500 dark:text-slate-400">
                  {formatCost(item.cost)}
                </span>
              </div>
            ))}
            {!valueMetrics.recentEvents.length ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">No advisor usage events in this window.</p>
            ) : null}
          </div>
        </BackofficeStackCard>
      </div>
    </BackofficeSectionPanel>
  );
}

function AdminAiAdvisorContent() {
  const { t } = useLocale();
  const [data, setData] = useState<AdvisorPreviewData | null>(null);
  const [historyItems, setHistoryItems] = useState<AdvisorHistoryItem[]>([]);
  const [valueMetrics, setValueMetrics] = useState<AdvisorValueMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [scope, setScope] = useState('operations');
  const [siteIdInput, setSiteIdInput] = useState('');
  const [siteId, setSiteId] = useState('');
  const [providerIdInput, setProviderIdInput] = useState('');
  const [providerId, setProviderId] = useState('');
  const [modelIdInput, setModelIdInput] = useState('');
  const [modelId, setModelId] = useState('');
  const [forceRefresh, setForceRefresh] = useState(false);
  const [reviewingDisclosure, setReviewingDisclosure] = useState(false);
  const [copyMessage, setCopyMessage] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const historyScope = data?.ai.scope || data?.baseline.scope || '';

  const loadHistory = useCallback(async () => {
    const params = new URLSearchParams();
    params.set('limit', '10');
    if (historyScope) {
      params.set('scope', historyScope);
    }
    if (siteId.trim()) {
      params.set('site_id', siteId.trim());
    }
    const response = await fetch(`/api/admin/advisor/ops-summary-history?${params.toString()}`, {
      credentials: 'include',
    });
    const payload = await response.json();
    if (!response.ok || payload?.status === 'error') {
      throw payload;
    }
    const items = Array.isArray(payload?.data?.items)
      ? payload.data.items.map((item: any) => normalizeHistoryItem(item))
      : [];
    setHistoryItems(items);
  }, [historyScope, siteId]);

  const loadValueMetrics = useCallback(
    async (resolvedScope = scope) => {
      const valueParams = new URLSearchParams();
      valueParams.set('window_days', '7');
      valueParams.set('limit', '10');
      if (resolvedScope) {
        valueParams.set('scope', resolvedScope);
      }
      if (siteId.trim()) {
        valueParams.set('site_id', siteId.trim());
      }
      const valueResponse = await fetch(`/api/admin/advisor/ops-summary-value?${valueParams.toString()}`, {
        credentials: 'include',
      });
      const valuePayload = await valueResponse.json();
      if (!valueResponse.ok || valuePayload?.status === 'error') {
        throw valuePayload;
      }
      setValueMetrics(normalizeValueMetrics(valuePayload?.data ?? {}));
    },
    [scope, siteId]
  );

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      let nextData: AdvisorPreviewData | null = null;
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
        if (forceRefresh) {
          params.set('force_refresh', 'true');
        }

        const response = await fetch(`/api/admin/advisor/ops-summary-preview?${params.toString()}`, {
          credentials: 'include',
        });
        const payload = await response.json();
        if (!response.ok || payload?.status === 'error') {
          throw payload;
        }
        nextData = normalizePreview(payload?.data ?? {});
        setData(nextData);
      } catch (previewError) {
        setData(null);
        setError(resolveUiErrorMessage(previewError, t('error.failed_load')));
      }

      const resolvedScope = nextData?.ai.scope || nextData?.baseline.scope || scope;
      await loadValueMetrics(resolvedScope).catch(() => {
        setValueMetrics(null);
      });

      if (nextData) {
        const historyParams = new URLSearchParams();
        historyParams.set('limit', '10');
        if (resolvedScope) {
          historyParams.set('scope', resolvedScope);
        }
        if (siteId.trim()) {
          historyParams.set('site_id', siteId.trim());
        }
        const historyResponse = await fetch(`/api/admin/advisor/ops-summary-history?${historyParams.toString()}`, {
          credentials: 'include',
        });
        const historyPayload = await historyResponse.json();
        if (historyResponse.ok && historyPayload?.status !== 'error') {
          setHistoryItems(
            Array.isArray(historyPayload?.data?.items)
              ? historyPayload.data.items.map((item: any) => normalizeHistoryItem(item))
              : []
          );
        }
      }
    } finally {
      setLoading(false);
    }
  }, [forceRefresh, loadValueMetrics, modelId, providerId, scope, siteId, t]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview, reloadKey]);

  const copyWithDisclosure = useCallback(
    async (value: string, disclosure: SummaryBranch['ai_disclosure']) => {
      try {
        const text = buildDisclosureClipboardText(value, disclosure);
        await navigator.clipboard.writeText(text);
        setCopyMessage('Copied with AI label');
        window.setTimeout(() => setCopyMessage(''), 2200);
      } catch (err) {
        setError(resolveUiErrorMessage(err, 'Failed to copy AI labeled text.'));
      }
    },
    []
  );

  const reviewDisclosure = useCallback(
    async (reviewStatus: 'human_confirmed' | 'edited_after_ai') => {
      const cacheKey = data?.ai.generation.cache_key || '';
      if (!cacheKey) {
        setError('AI analysis cache key is missing. Run preview again before confirming.');
        return;
      }
      setReviewingDisclosure(true);
      setError('');
      try {
        const response = await fetch('/api/admin/advisor/ops-summary-review', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            cache_key: cacheKey,
            review_status: reviewStatus,
          }),
        });
        const payload = await response.json();
        if (!response.ok || payload?.status === 'error') {
          throw payload;
        }
        const nextDisclosure = payload?.data?.ai_disclosure;
        if (nextDisclosure && typeof nextDisclosure === 'object') {
          setData((current) => {
            if (!current) return current;
            return {
              ...current,
              ai: normalizeBranch({
                ...current.ai,
                ai_disclosure: nextDisclosure,
              }),
            };
          });
        }
        await loadHistory().catch(() => undefined);
        setReloadKey((current) => current + 1);
      } catch (err) {
        setError(resolveUiErrorMessage(err, t('error.failed_save')));
      } finally {
        setReviewingDisclosure(false);
      }
    },
    [data?.ai, loadHistory, t]
  );

  const metricItems = useMemo(() => {
    const comparison = data?.comparison;
    return [
      {
        label: 'AI used',
        value: comparison?.aiUsed ? 'Yes' : 'No',
        detail: comparison?.cacheHit ? 'Served from cache' : comparison?.aiCalled ? 'Live provider call' : valueCheckLabel(comparison?.valueCheck || ''),
        toneClassName: comparison?.aiUsed ? 'text-emerald-600 dark:text-emerald-300' : 'text-slate-600 dark:text-slate-300',
      },
      {
        label: 'Cache',
        value: comparison?.cacheHit ? 'Hit' : comparison?.cacheStatus === 'miss' ? 'Miss' : '-',
        detail: forceRefresh ? 'Force refresh on' : 'Default TTL 30 min',
      },
      {
        label: 'Tokens',
        value: formatNumber((comparison?.tokensIn || 0) + (comparison?.tokensOut || 0)),
        detail: `${formatNumber(comparison?.tokensIn || 0)} in / ${formatNumber(comparison?.tokensOut || 0)} out`,
      },
      {
        label: 'Request cost',
        value: formatCost(comparison?.requestCost || 0),
        detail: comparison?.cacheHit
          ? `Cached result, original ${formatCost(comparison?.cost || 0)}`
          : comparison?.errorCode
            ? `Error: ${comparison.errorCode}`
            : 'This page load',
        size: 'compact' as const,
      },
    ];
  }, [data, forceRefresh]);

  if (loading && !data) {
    return <LoadingFallback />;
  }

  if (error && !valueMetrics) {
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
          <label className="flex h-8 items-center gap-2 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
            <input
              type="checkbox"
              checked={forceRefresh}
              onChange={(event) => setForceRefresh(event.target.checked)}
              className="h-3.5 w-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            Force refresh
          </label>
          <button
            type="button"
            onClick={() => {
              setSiteId(siteIdInput.trim());
              setProviderId(providerIdInput.trim());
              setModelId(modelIdInput.trim());
              setReloadKey((current) => current + 1);
            }}
            disabled={loading}
            className="h-8 rounded-full bg-slate-950 px-4 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60 dark:bg-blue-500 dark:text-slate-950 dark:hover:bg-blue-400"
          >
            {loading ? 'Loading' : 'Run preview'}
          </button>
          <button
            type="button"
            onClick={() => {
              setSiteId(siteIdInput.trim());
              setProviderIdInput('openai');
              setProviderId('openai');
              setModelIdInput('deepseek-v4-flash');
              setModelId('deepseek-v4-flash');
              setReloadKey((current) => current + 1);
            }}
            disabled={loading}
            className="h-8 rounded-full border border-blue-200 bg-blue-50 px-4 text-xs font-semibold text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 disabled:opacity-60 dark:border-blue-900/70 dark:bg-blue-950/35 dark:text-blue-300"
          >
            Run DeepSeek comparison
          </button>
        </div>
        {copyMessage ? (
          <p className="mt-3 text-xs font-semibold text-emerald-600 dark:text-emerald-300">{copyMessage}</p>
        ) : null}
      </BackofficePrimaryPanel>

      {error ? (
        <BackofficeSectionPanel className="border border-amber-200 bg-amber-50/80 text-sm text-amber-900 dark:border-amber-900/70 dark:bg-amber-950/35 dark:text-amber-100">
          {error}
        </BackofficeSectionPanel>
      ) : null}

      {data ? (
        <>
          <EffectComparisonPanel data={data} />
          <AiParticipationPanel data={data} />
          <ScenarioChecksPanel data={data} />
          <AgentHandoffPanel handoff={data.ai.agentRegistryMetadata} />
        </>
      ) : null}

      <ValueMetricsPanel valueMetrics={valueMetrics} />

      {data ? (
        <>
          <div className="grid gap-5 xl:grid-cols-2">
            <BranchPanel title="Baseline" branch={data.baseline} accent="baseline" />
            <BranchPanel
              title="AI output"
              branch={data.ai}
              accent="ai"
              onReviewDisclosure={reviewDisclosure}
              onCopyWithDisclosure={copyWithDisclosure}
              reviewingDisclosure={reviewingDisclosure}
            />
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
                  <MiniMetric label="Cache hit" value={data.comparison.cacheHit ? 'yes' : 'no'} />
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
          <HistoryPanel items={historyItems} />
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
  const drilldown = branch.source_context.advisor.drilldown;
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
      <DrilldownPanel drilldown={drilldown} />
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

function DrilldownPanel({ drilldown }: { drilldown: Record<string, DrilldownValue> }) {
  const sections = [
    { key: 'failed_runs', label: 'Failed runs' },
    { key: 'run_sites', label: 'Run sites' },
    { key: 'ability_families', label: 'Ability families' },
    { key: 'provider_breakdown', label: 'Providers' },
    { key: 'model_breakdown', label: 'Models' },
    { key: 'knowledge_sites', label: 'Knowledge sites' },
    { key: 'knowledge_intents', label: 'Knowledge intents' },
  ];
  const visibleSections = sections.filter((section) => {
    const value = drilldown[section.key];
    return Array.isArray(value) && value.length > 0;
  });
  const usage = drilldown.usage && !Array.isArray(drilldown.usage) ? drilldown.usage : null;

  if (!visibleSections.length && !usage) {
    return null;
  }

  return (
    <div className="border-t border-slate-200/80 pt-4 dark:border-slate-800">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
        Operations drilldown
      </p>
      <div className="mt-3 space-y-4">
        {visibleSections.map((section) => (
          <DrilldownSection
            key={section.key}
            label={section.label}
            rows={drilldown[section.key] as Array<Record<string, ScalarValue>>}
          />
        ))}
        {usage ? <UsageDrilldown value={usage} /> : null}
      </div>
    </div>
  );
}

function DrilldownSection({
  label,
  rows,
}: {
  label: string;
  rows: Array<Record<string, ScalarValue>>;
}) {
  return (
    <div>
      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{label}</p>
      <div className="mt-2 overflow-hidden rounded-xl border border-slate-200/80 dark:border-slate-800">
        {rows.map((row, index) => (
          <div
            key={`${label}-${index}`}
            className="grid gap-x-4 gap-y-2 border-t border-slate-200/70 bg-white/70 px-3 py-2 first:border-t-0 dark:border-slate-800 dark:bg-slate-950/35 sm:grid-cols-2 lg:grid-cols-3"
          >
            {Object.entries(row).map(([key, value]) => (
              <div key={key} className="min-w-0">
                <p className="text-[0.66rem] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
                  {key}
                </p>
                <p className="mt-1 truncate font-mono text-xs text-slate-700 dark:text-slate-200">
                  {String(value ?? '-')}
                </p>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function UsageDrilldown({
  value,
}: {
  value: Record<string, ScalarValue | Record<string, ScalarValue>>;
}) {
  const totals = value.totals && typeof value.totals === 'object' ? value.totals : {};
  return (
    <div>
      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">Usage</p>
      <div className="mt-2 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/35">
        <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          <MiniMetric label="Events" value={String(value.event_count ?? '-')} />
          {Object.entries(totals).map(([key, item]) => (
            <MiniMetric key={key} label={key} value={String(item ?? '-')} />
          ))}
        </div>
      </div>
    </div>
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
