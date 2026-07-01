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
  { label: '运营总览', value: 'operations' },
  { label: '运行时', value: 'runtime' },
  { label: '商业状态', value: 'commercial' },
  { label: '路由建议', value: 'routing' },
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
      return '复核 AI 输出';
    case 'configure_provider_allowlist':
      return '提供方未在允许名单';
    case 'configure_provider_adapter':
      return '提供方适配缺失';
    case 'pass_provider_id_to_test_llm':
      return '未选择测试提供方';
    case 'no_material_difference':
      return '与规则结果差异不明显';
    default:
      return value || '未知';
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
      return '需要人工复核';
    case 'human_confirmed':
      return '人工已确认';
    case 'edited_after_ai':
      return '已在 AI 输出后编辑';
    case 'not_ai_generated':
      return '规则生成';
    default:
      return value || '未知';
  }
}

function reviewStatusBadge(value: string): string {
  if (value === 'needs_review') return 'warning';
  if (value === 'human_confirmed') return 'success';
  if (value === 'edited_after_ai') return 'warning';
  return 'inactive';
}

function buildDisclosureClipboardText(value: string, disclosure: SummaryBranch['ai_disclosure']): string {
  const notice = disclosure.copy_export_notice || disclosure.visible_notice || '由 Magick AI 生成，使用前需要人工复核。';
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
              {disclosure.brand_label || 'Magick AI'} · {disclosure.visible_label || 'AI 生成'}
            </p>
            <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
              {disclosure.visible_notice || '由 Magick AI 生成，使用前需要人工复核。'}
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
          复制摘要和 AI 标识
        </button>
        <button
          type="button"
          onClick={() => onReview?.('human_confirmed')}
          disabled={!canReview || reviewing || isConfirmed}
          className="h-8 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-blue-500 dark:text-slate-950 dark:hover:bg-blue-400"
        >
          {isConfirmed ? '已确认' : reviewing ? '保存中' : '确认'}
        </button>
        <button
          type="button"
          onClick={() => onReview?.('edited_after_ai')}
          disabled={!canReview || reviewing}
          className="h-8 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:border-slate-300 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
        >
          标记为已编辑
        </button>
        {disclosure.reviewed_at ? (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            已复核 {disclosure.reviewed_at}
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
            {accent === 'ai' ? 'AI 分析' : '规则基线'}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{title}</h2>
        </div>
        <BackofficeStatusBadge label={branch.generation.mode || '未知'} status={generationStatus} />
      </div>

      <div
        className={cn(
          'rounded-[1.1rem] border px-4 py-3',
          accent === 'ai'
            ? 'border-blue-200 bg-blue-50/70 dark:border-blue-900/60 dark:bg-blue-950/20'
            : 'border-slate-200 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-950/35'
        )}
      >
        <p className="text-sm font-semibold text-slate-950 dark:text-white">{branch.headline || '暂无标题'}</p>
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
          {branch.operator_summary || '暂无运营摘要。'}
        </p>
      </div>

      <div className="space-y-4">
        <TextBlock
          title="支持回复草稿"
          value={branch.support_draft || '暂无支持回复草稿。'}
          disclosure={accent === 'ai' ? branch.ai_disclosure : undefined}
          onCopyWithDisclosure={accent === 'ai' ? onCopyWithDisclosure : undefined}
        />
        <TextBlock title="下一步" value={branch.operator_next_step || '暂无下一步。'} compact />
        <TextBlock title="安全说明" value={branch.safety_note || '暂无安全说明。'} compact />
      </div>

      <div className="mt-auto grid gap-3 border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800 sm:grid-cols-3">
        <MiniMetric label="提供方" value={branch.generation.provider_id || '-'} />
        <MiniMetric label="模型" value={branch.generation.model_id || '-'} />
        <MiniMetric
          label="缓存"
          value={
            branch.generation.cache_hit
              ? `命中，有效至 ${branch.generation.cache_expires_at || '-'}`
              : branch.generation.cache_status || '无'
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
              {disclosure.visible_label || 'AI 生成'}
            </span>
            <button
              type="button"
              onClick={() => onCopyWithDisclosure?.(value, disclosure)}
              className="text-xs font-semibold text-blue-700 underline-offset-4 hover:underline dark:text-blue-300"
            >
              复制并附带 AI 标识
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
            历史记录
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">已保存的诊断摘要</h2>
        </div>
        <BackofficeStatusBadge label={`${items.length} 条`} status={items.length ? 'success' : 'inactive'} />
      </div>
      <div className="space-y-3">
        {items.length ? (
          items.map((item) => <HistoryRow key={item.cacheKey || `${item.generatedAt}-${item.headline}`} item={item} />)
        ) : (
          <p className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
            当前筛选条件下还没有保存过 AI 诊断摘要。
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
            <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.headline || 'AI 诊断摘要'}</p>
            <BackofficeStatusBadge
              label={reviewStatusLabel(item.aiDisclosure.reviewStatus)}
              status={reviewStatusBadge(item.aiDisclosure.reviewStatus)}
            />
            {item.isStale ? <BackofficeStatusBadge label="已过期" status="warning" /> : null}
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {item.operatorSummary || '暂无已保存摘要。'}
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
        <MiniMetric label="范围" value={item.scope || '-'} />
        <MiniMetric label="站点" value={item.siteId || 'platform'} />
        <MiniMetric label="模型" value={item.generation.modelId || '-'} />
        <MiniMetric label="下一步" value={item.operatorNextStep || '-'} />
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
            效果对比
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            运营数据、规则基线和 AI 结果并排检查
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            两条分支使用同一份 Cloud 运营证据，差异只来自 AI 对问题和下一步的表达。
          </p>
        </div>
        <BackofficeStatusBadge
          label={data.comparison.aiUsed ? 'AI 已参与' : '仅规则'}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <ComparisonColumn
          eyebrow="原始运营数据"
          title={failedRun ? String(failedRun.error_code || '运行时信号') : '当前运营信号'}
          statusLabel={`${formatNumber(Number(runtime.total_runs || 0))} 次运行`}
          status={Number(runtime.failed_runs || 0) > 0 ? 'warning' : 'success'}
          rows={[
            ['失败运行', formatNumber(Number(runtime.failed_runs || 0))],
            ['失败率', formatRatio(runtime.run_failure_rate)],
            ['守卫事件', formatNumber(Number(runtime.guard_events || 0))],
            ['知识库无命中', formatRatio(knowledge.knowledge_no_hit_rate)],
            ['用量事件', formatNumber(Number(usage.usage_events || 0))],
          ]}
          detail={
            failedRun
              ? [
                  `run_id: ${String(failedRun.run_id || '-')}`,
                  `site_id: ${String(failedRun.site_id || '-')}`,
                  `能力: ${String(failedRun.ability_family || '-')}/${String(failedRun.ability_name || '-')}`,
                ]
              : ['当前窗口没有失败运行详情。']
          }
        />
        <ComparisonColumn
          eyebrow="规则分析"
          title={data.baseline.headline || '规则基线'}
          statusLabel={data.baseline.generation.mode || 'rule'}
          status="inactive"
          rows={[
            ['模式', data.baseline.generation.mode || '-'],
            ['状态', data.baseline.status || '-'],
            ['级别', data.baseline.severity || '-'],
            ['下一步', data.baseline.operator_next_step || '-'],
          ]}
          detail={[data.baseline.operator_summary || '暂无规则摘要。']}
        />
        <ComparisonColumn
          eyebrow="AI 分析"
          title={data.ai.headline || 'AI 输出'}
          statusLabel={data.comparison.aiCalled ? '实时调用' : data.comparison.cacheHit ? '缓存命中' : '未调用'}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
          rows={[
            ['模式', data.ai.generation.mode || '-'],
            ['模型', data.comparison.modelId || data.ai.generation.model_id || '-'],
            ['成本', formatCost(data.comparison.requestCost || 0)],
            ['改写文案', data.comparison.textChanged ? '是' : '否'],
          ]}
          detail={[
            data.ai.operator_summary || '暂无 AI 摘要。',
            aiAddedSpecificity
              ? 'AI 补充了具体运行、站点、错误或能力线索。'
              : '当前输出没有检测到额外具体标识。',
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
            AI 参与证据
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            输入给 AI 的证据，以及输出变化
          </h2>
        </div>
        <BackofficeStatusBadge
          label={data.comparison.aiCalled ? '实时调用' : data.comparison.cacheHit ? '缓存命中' : '未调用'}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="grid gap-3 sm:grid-cols-2">
          <BackofficeStackCard>
            <MiniMetric label="提供方适配" value={data.comparison.requestedProviderId || data.ai.generation.provider_id || '-'} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label="模型" value={data.comparison.modelId || data.ai.generation.model_id || '-'} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label="Token" value={`${formatNumber(data.comparison.tokensIn)} 输入 / ${formatNumber(data.comparison.tokensOut)} 输出`} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label="本次成本" value={formatCost(data.comparison.requestCost || 0)} />
          </BackofficeStackCard>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <EvidenceList title="输入数据类型" items={inputTypes} empty="未检测到已脱敏的输入类型。" />
          <EvidenceList title="AI 增量价值" items={valueBullets} empty="暂未检测到 AI 独有差异。" />
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
    items.push('运行质量：运行次数、失败、回调和守卫事件。');
  }
  if (Array.isArray(drilldown.failed_runs) && drilldown.failed_runs.length > 0) {
    items.push('失败运行详情：run id、site id、能力、错误码和选中提供方/模型。');
  }
  if (signals.some((signal) => signal.code === 'ops.knowledge_quality')) {
    items.push('知识库搜索健康度：无命中率、搜索失败、已索引文档和分块。');
  }
  if (signals.some((signal) => signal.code === 'ops.provider_quality')) {
    items.push('提供方质量：调用次数、错误率、回退次数和延迟。');
  }
  if (signals.some((signal) => signal.code === 'ops.usage_cost')) {
    items.push('用量和成本信号：用量事件、计量数量、上报成本和提供方成本。');
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
    bullets.push('本次通过实时提供方调用生成分析，而不是只使用确定性规则。');
  } else if (data.comparison.cacheHit) {
    bullets.push('复用了之前的 AI 缓存结果，避免重复调用提供方。');
  }
  if (data.comparison.textChanged) {
    bullets.push('AI 改写了面向运营人员的摘要或下一步表达。');
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
    bullets.push('AI 提取了运营人员可直接检查的失败运行标识。');
  }
  if (data.ai.operator_next_step && data.ai.operator_next_step !== data.baseline.operator_next_step) {
    bullets.push('AI 给出了比规则基线更具体的运营下一步。');
  }
  return bullets;
}

function ScenarioChecksPanel({ data }: { data: AdvisorPreviewData }) {
  const scenarios = buildScenarioChecks(data);
  return (
    <BackofficeSectionPanel className="space-y-5">
      <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          固定场景
        </p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
          用三类稳定场景判断 AI 是否有用
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
              <BackofficeStatusBadge label={scenario.status === 'active' ? '活跃' : '安静'} status={scenario.status === 'active' ? 'warning' : 'inactive'} />
            </div>
            <div className="space-y-2 border-t border-slate-200/80 pt-3 dark:border-slate-800">
              <MiniMetric label="证据" value={scenario.evidence} />
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
            Agent 边界
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            内部诊断 Agent 的交接边界
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            这些元数据来自已脱敏的诊断上下文，只用于展示交接边界和禁止动作。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <BackofficeStatusBadge
            label={handoff.directWordPressWrite ? '允许写入' : '禁止写入'}
            status={handoff.directWordPressWrite ? 'error' : 'success'}
          />
          <BackofficeStatusBadge
            label={handoff.requiresOperatorReview ? '需要人工复核' : '可选复核'}
            status={handoff.requiresOperatorReview ? 'warning' : 'inactive'}
          />
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <BackofficeStackCard>
          <MiniMetric label="Agent" value={handoff.agentId || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="版本" value={handoff.agentVersion || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="交接类型" value={handoff.handoffType || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="归属方" value={handoff.handoffOwner || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="执行模式" value={handoff.executionPattern || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label="存储模式" value={handoff.storageMode || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard className="md:col-span-2">
          <MiniMetric label="失败关闭策略" value={handoff.failClosedBehavior || '-'} />
        </BackofficeStackCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <EvidenceList
          title="允许动作"
          items={handoff.allowedActions.map(humanizeKey)}
          empty="未声明允许动作。"
        />
        <EvidenceList
          title="停止条件"
          items={handoff.stopConditions.map(humanizeKey)}
          empty="未声明停止条件。"
        />
        <EvidenceList
          title="禁止动作"
          items={handoff.forbiddenActions.map(humanizeKey)}
          empty="未声明禁止动作。"
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
      title: '运行失败分析',
      status: Number(runtime.failed_runs || 0) > 0 ? 'active' : 'quiet',
      headline: failedRun
        ? `${String(failedRun.site_id || 'site')} 出现 ${String(failedRun.error_code || '失败运行')}。`
        : '当前窗口没有失败运行。',
      evidence: `${formatNumber(Number(runtime.failed_runs || 0))} 失败 / ${formatNumber(Number(runtime.total_runs || 0))} 次运行`,
      aiValue: failedRun
        ? 'AI 应解释可能失败路径，并指向具体运行和运营动作。'
        : 'AI 应保持安静，或确认当前没有运行失败主因。',
    },
    {
      key: 'knowledge_no_hit',
      title: '知识库无命中分析',
      status: Number(knowledge.knowledge_no_hits || 0) > 0 ? 'active' : 'quiet',
      headline: `${formatNumber(Number(knowledge.knowledge_searches || 0))} 次搜索，${formatRatio(knowledge.knowledge_no_hit_rate)} 无命中率。`,
      evidence: `${formatNumber(Number(knowledge.indexed_documents || 0))} 文档 / ${formatNumber(Number(knowledge.indexed_chunks || 0))} 分块`,
      aiValue: 'AI 应把无命中模式关联到索引、内容覆盖或查询意图缺口。',
    },
    {
      key: 'provider_cost_latency',
      title: '提供方成本或延迟异常',
      status: providerErrorRate > 0 || avgLatency > 0 || providerCalls > 0 ? 'active' : 'quiet',
      headline: `${formatNumber(providerCalls)} 次提供方调用，${formatRatio(providerErrorRate)} 错误率。`,
      evidence: `${formatNumber(avgLatency)} ms 平均延迟`,
      aiValue: 'AI 应先区分提供方退化和应用/运行时失败，再给出动作建议。',
    },
  ];
}

function valueSignalBadge(value: string): string {
  if (value === 'promising') return 'success';
  if (value === 'needs_review_loop' || value === 'provider_blocked') return 'warning';
  if (value === 'not_using_ai' || value === 'insufficient_data') return 'inactive';
  return 'inactive';
}

function valueSignalLabel(value: string): string {
  switch (value) {
    case 'promising':
      return '有价值信号';
    case 'needs_review_loop':
      return '需要复核闭环';
    case 'provider_blocked':
      return '提供方受限';
    case 'not_using_ai':
      return '未使用 AI';
    case 'insufficient_data':
      return '数据不足';
    default:
      return value || '未知';
  }
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
            价值追踪
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {valueMetrics.valueSignal.headline || 'AI 价值尚未形成足够证据'}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {valueMetrics.valueSignal.nextStep || '先运行人工触发的诊断并复核输出，再扩大 AI 使用范围。'}
          </p>
        </div>
        <BackofficeStatusBadge
          label={valueSignalLabel(valueMetrics.valueSignal.status)}
          status={valueSignalBadge(valueMetrics.valueSignal.status)}
        />
      </div>

      <BackofficeMetricStrip
        columnsClassName="md:grid-cols-2 xl:grid-cols-5"
        items={[
          {
            label: '请求数',
            value: formatNumber(valueMetrics.totals.analysisRequests),
            detail: `${valueMetrics.window.days || 7} 天窗口`,
          },
          {
            label: 'AI 调用',
            value: formatNumber(valueMetrics.totals.aiCalled),
            detail: `${formatPercent(valueMetrics.rates.aiCallRate)} 实时调用率`,
          },
          {
            label: '缓存命中',
            value: formatPercent(valueMetrics.rates.cacheHitRate),
            detail: `${formatNumber(valueMetrics.totals.cacheHits)} 条缓存诊断`,
          },
          {
            label: '请求成本',
            value: formatCost(valueMetrics.totals.requestCost),
            detail: `预计节省 ${formatCost(valueMetrics.totals.estimatedCacheSavings)}`,
            size: 'compact',
          },
          {
            label: '已确认',
            value: formatPercent(valueMetrics.rates.confirmedRate),
            detail: `${formatNumber(valueMetrics.review.humanConfirmed)} 确认 / ${formatNumber(valueMetrics.review.cachedAiItems)} 条 AI 项`,
          },
        ]}
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.65fr)]">
        <div className="grid gap-3 sm:grid-cols-3">
          <BackofficeStackCard>
            <MiniMetric
              label="待复核"
              value={formatNumber(valueMetrics.review.needsReview)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="AI 后编辑"
              value={formatNumber(valueMetrics.review.editedAfterAi)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="规则回退"
              value={formatNumber(valueMetrics.totals.deterministicFallbacks)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="提供方错误"
              value={formatNumber(valueMetrics.totals.providerErrors)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="主要提供方"
              value={topProvider ? `${topProvider.providerId} · ${formatCost(topProvider.cost)}` : '-'}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label="主要模型"
              value={topModel ? `${topModel.modelId} · ${formatCost(topModel.cost)}` : '-'}
            />
          </BackofficeStackCard>
        </div>
        <BackofficeStackCard>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            最近 AI 事件
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
              <p className="text-sm text-slate-500 dark:text-slate-400">当前窗口没有诊断使用事件。</p>
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
        setCopyMessage('已复制，并附带 AI 标识');
        window.setTimeout(() => setCopyMessage(''), 2200);
      } catch (err) {
        setError(resolveUiErrorMessage(err, '复制带 AI 标识的文本失败。'));
      }
    },
    []
  );

  const reviewDisclosure = useCallback(
    async (reviewStatus: 'human_confirmed' | 'edited_after_ai') => {
      const cacheKey = data?.ai.generation.cache_key || '';
      if (!cacheKey) {
        setError('缺少 AI 诊断缓存键。请重新运行诊断后再确认。');
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
        label: 'AI 参与',
        value: comparison?.aiUsed ? '是' : '否',
        detail: comparison?.cacheHit ? '来自缓存' : comparison?.aiCalled ? '实时调用提供方' : valueCheckLabel(comparison?.valueCheck || ''),
        toneClassName: comparison?.aiUsed ? 'text-emerald-600 dark:text-emerald-300' : 'text-slate-600 dark:text-slate-300',
      },
      {
        label: '缓存',
        value: comparison?.cacheHit ? '命中' : comparison?.cacheStatus === 'miss' ? '未命中' : '-',
        detail: forceRefresh ? '强制刷新已开启' : '默认缓存 30 分钟',
      },
      {
        label: 'Token',
        value: formatNumber((comparison?.tokensIn || 0) + (comparison?.tokensOut || 0)),
        detail: `${formatNumber(comparison?.tokensIn || 0)} 输入 / ${formatNumber(comparison?.tokensOut || 0)} 输出`,
      },
      {
        label: '请求成本',
        value: formatCost(comparison?.requestCost || 0),
        detail: comparison?.cacheHit
          ? `缓存结果，原始成本 ${formatCost(comparison?.cost || 0)}`
          : comparison?.errorCode
            ? `错误：${comparison.errorCode}`
            : '本次页面加载',
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
        eyebrow="内部运营"
        title="运营诊断助手"
        description="用 Cloud 运营证据生成只读诊断摘要，并对比规则基线和 AI 输出。"
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
            {loading ? '加载中' : '运行诊断'}
          </button>
        </div>
        <details className="mt-4 rounded-xl border border-slate-200/80 bg-white/65 dark:border-slate-800 dark:bg-slate-950/30">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-800 hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-900/60">
            高级评估参数
          </summary>
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-200/80 px-4 py-3 dark:border-slate-800">
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
              强制刷新
            </label>
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
              运行 DeepSeek 对比
            </button>
            <p className="basis-full text-xs leading-5 text-slate-500 dark:text-slate-400">
              这些参数只用于内部评估 AI 摘要质量，不会改变路由、套餐、WordPress 内容或客户状态。
            </p>
          </div>
        </details>
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
            <BranchPanel title="规则基线" branch={data.baseline} accent="baseline" />
            <BranchPanel
              title="AI 输出"
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
                    判断
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
                  <MiniMetric label="规则模式" value={data.comparison.baselineMode || '-'} />
                </BackofficeStackCard>
                <BackofficeStackCard>
                  <MiniMetric label="AI 模式" value={data.comparison.aiMode || '-'} />
                </BackofficeStackCard>
                <BackofficeStackCard>
                  <MiniMetric label="缓存命中" value={data.comparison.cacheHit ? '是' : '否'} />
                </BackofficeStackCard>
                <BackofficeStackCard>
                  <MiniMetric label="请求提供方" value={data.comparison.requestedProviderId || '-'} />
                </BackofficeStackCard>
                <BackofficeStackCard>
                  <MiniMetric label="模型" value={data.comparison.modelId || '-'} />
                </BackofficeStackCard>
              </div>
            </BackofficeSectionPanel>
          </div>
          <HistoryPanel items={historyItems} />
          <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
            <BackofficeSectionPanel className="space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  安全边界
                </p>
                <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">执行边界</h2>
              </div>
              <div className="space-y-3">
                <SafetyRow label="Prompt 存储已阻断" ok={!data.safety.promptSaved} />
                <SafetyRow label="输出文本存储已阻断" ok={!data.safety.outputTextSaved} />
                <SafetyRow label="WordPress 写入已阻断" ok={!data.safety.wordpressWriteAllowed} />
                <SafetyRow
                  label="客户文章生成已阻断"
                  ok={!data.safety.customerArticleGenerationAllowed}
                />
                <SafetyRow label="需要运营人员复核" ok={data.safety.requiresOperatorReview} />
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
          证据
        </p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">AI 输入信号</h2>
      </div>
      <div className="space-y-3">
        {signals.length ? (
          signals.map((signal, index) => <SignalRow key={`${String(signal.code || 'signal')}-${index}`} signal={signal} />)
        ) : (
          <p className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
            当前没有传递给 AI 分支的脱敏运营信号。
          </p>
        )}
      </div>
      <DrilldownPanel drilldown={drilldown} />
      <div className="border-t border-slate-200/80 pt-4 dark:border-slate-800">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
          来源
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
    { key: 'failed_runs', label: '失败运行' },
    { key: 'run_sites', label: '运行站点' },
    { key: 'ability_families', label: '能力族' },
    { key: 'provider_breakdown', label: '提供方' },
    { key: 'model_breakdown', label: '模型' },
    { key: 'knowledge_sites', label: '知识库站点' },
    { key: 'knowledge_intents', label: '知识库意图' },
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
        运营详情
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
      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">用量</p>
      <div className="mt-2 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/35">
        <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          <MiniMetric label="事件" value={String(value.event_count ?? '-')} />
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
      <BackofficeStatusBadge label={ok ? '通过' : '阻断'} status={ok ? 'success' : 'error'} />
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
