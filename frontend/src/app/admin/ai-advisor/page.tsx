'use client';

import Link from 'next/link';
import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BackofficeDiagnosticNotice,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';
import { cn, formatNumber } from '@/lib/utils';

const operationsAdvisorClient = createApiClient({ idempotencyPrefix: 'operations_advisor' });

type Translator = (key: string, params?: Record<string, string>, fallback?: string) => string;

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
  agentMetadataProjection: AgentHandoff;
  source_context: {
    advisor: {
      scope: string;
      status: string;
      severity: string;
      summary: string;
      confidence: string;
      agent_handoff: AgentHandoff;
      evidence: Array<{ kind: string; ref: string; label: string }>;
      recommendedActions: Array<{ action: string; requiresOperator: boolean }>;
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
  { labelKey: 'admin.ai_advisor.scope_operations', fallback: 'Operations', value: 'operations' },
  { labelKey: 'admin.ai_advisor.scope_runtime', fallback: 'Runtime', value: 'runtime' },
  { labelKey: 'admin.ai_advisor.scope_commercial', fallback: 'Commercial', value: 'commercial' },
  { labelKey: 'admin.ai_advisor.scope_routing', fallback: 'Routing recommendations', value: 'routing' },
];

function normalizeBranch(raw: any): SummaryBranch {
  const generation = raw?.generation ?? {};
  const disclosure = raw?.ai_disclosure ?? {};
  const handoff = raw?.source_context?.advisor?.agent_handoff ?? {};
  const metadataProjection =
    raw?.agent_metadata_projection ?? raw?.agent_handoff ?? handoff;
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
      brand_label: String(disclosure.brand_label ?? 'Npcink AI'),
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
    agentMetadataProjection: normalizeAgentHandoff(metadataProjection),
    source_context: {
      advisor: {
        scope: String(raw?.source_context?.advisor?.scope ?? ''),
        status: String(raw?.source_context?.advisor?.status ?? raw?.status ?? ''),
        severity: String(raw?.source_context?.advisor?.severity ?? raw?.severity ?? ''),
        summary: String(raw?.source_context?.advisor?.summary ?? ''),
        confidence: String(raw?.source_context?.advisor?.confidence ?? ''),
        agent_handoff: normalizeAgentHandoff(handoff),
        evidence: Array.isArray(raw?.source_context?.advisor?.evidence)
          ? raw.source_context.advisor.evidence.map((item: any) => ({
              kind: String(item?.kind ?? ''),
              ref: String(item?.ref ?? ''),
              label: String(item?.label ?? ''),
            }))
          : [],
        recommendedActions: Array.isArray(raw?.source_context?.advisor?.recommended_actions)
          ? raw.source_context.advisor.recommended_actions.map((item: any) => ({
              action: String(item?.action ?? ''),
              requiresOperator: Boolean(item?.requires_operator),
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

function advisorHeadlineText(value: string, t: Translator): string {
  const known: Record<string, [string, string]> = {
    'Operations posture is stable': ['admin.ai_advisor.diagnosis_operations_stable', 'Operations posture is stable'],
    'Runtime failures need operations review': ['admin.ai_advisor.diagnosis_runtime_failures', 'Runtime failures need operations review'],
    'Provider reliability needs review': ['admin.ai_advisor.diagnosis_provider_reliability', 'Provider reliability needs review'],
    'Knowledge search value may be low': ['admin.ai_advisor.diagnosis_knowledge_value', 'Knowledge search value may be low'],
    'Commercial follow-up is visible': ['admin.ai_advisor.diagnosis_commercial_followup', 'Commercial follow-up is visible'],
    'Runtime delivery needs operator review': ['admin.ai_advisor.diagnosis_runtime_delivery', 'Runtime delivery needs operator review'],
  };
  const copy = known[value];
  return copy ? t(copy[0], {}, copy[1]) : value || t('admin.ai_advisor.no_active_issue', {}, 'No active operator issue');
}

function advisorSummaryText(value: string, t: Translator): string {
  const known: Record<string, [string, string]> = {
    'Recent usage, runtime, provider, and knowledge signals do not show a high-priority operator action.': ['admin.ai_advisor.diagnosis_operations_stable_desc', 'Recent usage, runtime, provider, and knowledge signals do not show a high-priority operator action.'],
    'Recent run failures are visible in the selected operations window.': ['admin.ai_advisor.diagnosis_runtime_failures_desc', 'Recent run failures are visible in the selected operations window.'],
    'Provider errors or fallback pressure are present in recent traffic.': ['admin.ai_advisor.diagnosis_provider_reliability_desc', 'Provider errors or fallback pressure are present in recent traffic.'],
    'Knowledge searches show elevated no-hit pressure in the selected window.': ['admin.ai_advisor.diagnosis_knowledge_value_desc', 'Knowledge searches show elevated no-hit pressure in the selected window.'],
    'Subscription attention or near-term expiry signals are present.': ['admin.ai_advisor.diagnosis_commercial_followup_desc', 'Subscription attention or near-term expiry signals are present.'],
    'Queue or callback pressure is present in recent runtime diagnostics.': ['admin.ai_advisor.diagnosis_runtime_delivery_desc', 'Queue or callback pressure is present in recent runtime diagnostics.'],
  };
  const copy = known[value];
  return copy ? t(copy[0], {}, copy[1]) : value || t('admin.ai_advisor.no_summary', {}, 'Review the linked operational evidence.');
}

function advisorEvidenceLabel(kind: string, fallback: string, t: Translator): string {
  const known: Record<string, [string, string]> = {
    admin_overview: ['admin.ai_advisor.evidence_admin_overview', 'Commercial coverage and usage summary'],
    runtime_diagnostics: ['admin.ai_advisor.evidence_runtime_diagnostics', 'Runtime queue, callback, and guard summary'],
    site_knowledge_observability: ['admin.ai_advisor.evidence_site_knowledge', 'Knowledge search and index health summary'],
    provider_call_records: ['admin.ai_advisor.evidence_provider_calls', 'Provider call metrics aggregated from run telemetry'],
  };
  const copy = known[kind];
  return copy ? t(copy[0], {}, copy[1]) : fallback || humanizeKey(kind);
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

function valueCheckLabel(value: string, t: Translator): string {
  switch (value) {
    case 'review_ai_output':
      return t('admin.ai_advisor.value_review_ai_output', {}, 'Review AI output');
    case 'configure_provider_allowlist':
      return t('admin.ai_advisor.value_provider_not_allowed', {}, 'Provider is not allowlisted');
    case 'configure_provider_adapter':
      return t('admin.ai_advisor.value_provider_adapter_missing', {}, 'Provider adapter is missing');
    case 'pass_provider_id_to_test_llm':
      return t('admin.ai_advisor.value_provider_not_selected', {}, 'No test provider selected');
    case 'no_material_difference':
      return t('admin.ai_advisor.value_no_material_difference', {}, 'No material difference from rule output');
    default:
      return value || t('common.unknown', {}, 'Unknown');
  }
}

function valueCheckStatus(value: string): string {
  if (value === 'review_ai_output') return 'success';
  if (value === 'configure_provider_allowlist' || value === 'configure_provider_adapter') return 'warning';
  if (value === 'pass_provider_id_to_test_llm') return 'inactive';
  return 'inactive';
}

function reviewStatusLabel(value: string, t: Translator): string {
  switch (value) {
    case 'needs_review':
      return t('admin.ai_advisor.review_needs_review', {}, 'Needs human review');
    case 'human_confirmed':
      return t('admin.ai_advisor.review_human_confirmed', {}, 'Human confirmed');
    case 'edited_after_ai':
      return t('admin.ai_advisor.review_edited_after_ai', {}, 'Edited after AI output');
    case 'not_ai_generated':
      return t('admin.ai_advisor.review_not_ai_generated', {}, 'Rule generated');
    default:
      return value || t('common.unknown', {}, 'Unknown');
  }
}

function reviewStatusBadge(value: string): string {
  if (value === 'needs_review') return 'warning';
  if (value === 'human_confirmed') return 'success';
  if (value === 'edited_after_ai') return 'warning';
  return 'inactive';
}

function buildDisclosureClipboardText(value: string, disclosure: SummaryBranch['ai_disclosure'], t: Translator): string {
  const notice = disclosure.copy_export_notice || disclosure.visible_notice || t('admin.ai_advisor.default_ai_notice', {}, 'Generated by Npcink AI. Review before use.');
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
  const { t } = useLocale();
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
              {disclosure.brand_label || 'Npcink AI'} · {disclosure.visible_label || t('admin.ai_advisor.ai_generated_label', {}, 'AI generated')}
            </p>
            <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
              {disclosure.visible_notice || t('admin.ai_advisor.default_ai_notice', {}, 'Generated by Npcink AI. Review before use.')}
            </p>
          </div>
        </div>
        <BackofficeStatusBadge
          label={reviewStatusLabel(disclosure.review_status, t)}
          status={reviewStatusBadge(disclosure.review_status)}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-blue-100 pt-3 dark:border-blue-900/50">
        <button
          type="button"
          onClick={() => onCopy?.(branch.operator_summary, disclosure)}
          className="h-8 rounded-lg border border-blue-200 bg-blue-50 px-3 text-xs font-semibold text-blue-700 transition hover:border-blue-300 hover:bg-blue-100 dark:border-blue-900/70 dark:bg-blue-950/35 dark:text-blue-300"
        >
          {t('admin.ai_advisor.copy_summary_with_disclosure', {}, 'Copy summary with AI disclosure')}
        </button>
        <button
          type="button"
          onClick={() => onReview?.('human_confirmed')}
          disabled={!canReview || reviewing || isConfirmed}
          className="h-8 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-blue-500 dark:text-slate-950 dark:hover:bg-blue-400"
        >
          {isConfirmed
            ? t('admin.ai_advisor.confirmed', {}, 'Confirmed')
            : reviewing
              ? t('common.saving', {}, 'Saving...')
              : t('common.confirm', {}, 'Confirm')}
        </button>
        <button
          type="button"
          onClick={() => onReview?.('edited_after_ai')}
          disabled={!canReview || reviewing}
          className="h-8 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:border-slate-300 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
        >
          {t('admin.ai_advisor.mark_edited_after_ai', {}, 'Mark edited after AI')}
        </button>
        {disclosure.reviewed_at ? (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {t('admin.ai_advisor.reviewed_at', { date: disclosure.reviewed_at }, 'Reviewed {{date}}')}
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
  const { t } = useLocale();
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
            {accent === 'ai'
              ? t('admin.ai_advisor.branch_ai_label', {}, 'AI analysis')
              : t('admin.ai_advisor.branch_rule_label', {}, 'Rule baseline')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{title}</h2>
        </div>
        <BackofficeStatusBadge label={branch.generation.mode || t('common.unknown', {}, 'Unknown')} status={generationStatus} />
      </div>

      <div
        className={cn(
          'rounded-[1.1rem] border px-4 py-3',
          accent === 'ai'
            ? 'border-blue-200 bg-blue-50/70 dark:border-blue-900/60 dark:bg-blue-950/20'
            : 'border-slate-200 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-950/35'
        )}
      >
        <p className="text-sm font-semibold text-slate-950 dark:text-white">{branch.headline || t('admin.ai_advisor.no_headline', {}, 'No headline')}</p>
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
          {branch.operator_summary || t('admin.ai_advisor.no_operator_summary', {}, 'No operator summary.')}
        </p>
      </div>

      <div className="space-y-4">
        <TextBlock
          title={t('admin.ai_advisor.support_draft', {}, 'Support reply draft')}
          value={branch.support_draft || t('admin.ai_advisor.no_support_draft', {}, 'No support reply draft.')}
          disclosure={accent === 'ai' ? branch.ai_disclosure : undefined}
          onCopyWithDisclosure={accent === 'ai' ? onCopyWithDisclosure : undefined}
        />
        <TextBlock title={t('admin.ai_advisor.next_step', {}, 'Next step')} value={branch.operator_next_step || t('admin.ai_advisor.no_next_step', {}, 'No next step.')} compact />
        <TextBlock title={t('admin.ai_advisor.safety_note', {}, 'Safety note')} value={branch.safety_note || t('admin.ai_advisor.no_safety_note', {}, 'No safety note.')} compact />
      </div>

      <div className="mt-auto grid gap-3 border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800 sm:grid-cols-3">
        <MiniMetric label={t('admin.ai_advisor.provider', {}, 'Provider')} value={branch.generation.provider_id || '-'} />
        <MiniMetric label={t('admin.ai_advisor.model', {}, 'Model')} value={branch.generation.model_id || '-'} />
        <MiniMetric
          label={t('admin.ai_advisor.metric_cache', {}, 'Cache')}
          value={
            branch.generation.cache_hit
              ? t('admin.ai_advisor.cache_hit_until', { date: branch.generation.cache_expires_at || '-' }, 'Hit, valid until {{date}}')
              : branch.generation.cache_status || t('admin.ai_advisor.cache_none', {}, 'None')
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
  const { t } = useLocale();
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">{title}</p>
        {disclosure?.visible_label_required ? (
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[0.66rem] font-bold uppercase tracking-[0.14em] text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/35 dark:text-blue-300">
              {disclosure.visible_label || t('admin.ai_advisor.ai_generated_label', {}, 'AI generated')}
            </span>
            <button
              type="button"
              onClick={() => onCopyWithDisclosure?.(value, disclosure)}
              className="text-xs font-semibold text-blue-700 underline-offset-4 hover:underline dark:text-blue-300"
            >
              {t('admin.ai_advisor.copy_with_disclosure', {}, 'Copy with AI disclosure')}
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
  const { t } = useLocale();
  return (
    <BackofficeSectionPanel className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {t('admin.ai_advisor.history_label', {}, 'History')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{t('admin.ai_advisor.history_title', {}, 'Saved diagnostic summaries')}</h2>
        </div>
        <BackofficeStatusBadge label={t('admin.ai_advisor.history_count', { count: String(items.length) }, '{{count}} items')} status={items.length ? 'success' : 'inactive'} />
      </div>
      <div className="space-y-3">
        {items.length ? (
          items.map((item) => <HistoryRow key={item.cacheKey || `${item.generatedAt}-${item.headline}`} item={item} />)
        ) : (
          <p className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
            {t('admin.ai_advisor.history_empty', {}, 'No saved AI diagnostic summaries match the current filters.')}
          </p>
        )}
      </div>
    </BackofficeSectionPanel>
  );
}

function HistoryRow({ item }: { item: AdvisorHistoryItem }) {
  const { t } = useLocale();
  return (
    <div className="rounded-xl border border-slate-200/80 bg-white/75 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/35">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.headline || t('admin.ai_advisor.history_default_headline', {}, 'AI diagnostic summary')}</p>
            <BackofficeStatusBadge
              label={reviewStatusLabel(item.aiDisclosure.reviewStatus, t)}
              status={reviewStatusBadge(item.aiDisclosure.reviewStatus)}
            />
            {item.isStale ? <BackofficeStatusBadge label={t('admin.ai_advisor.stale', {}, 'Stale')} status="warning" /> : null}
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {item.operatorSummary || t('admin.ai_advisor.no_saved_summary', {}, 'No saved summary.')}
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
        <MiniMetric label={t('admin.ai_advisor.scope', {}, 'Scope')} value={item.scope || '-'} />
        <MiniMetric label={t('admin.ai_advisor.site', {}, 'Site')} value={item.siteId || 'platform'} />
        <MiniMetric label={t('admin.ai_advisor.model', {}, 'Model')} value={item.generation.modelId || '-'} />
        <MiniMetric label={t('admin.ai_advisor.next_step', {}, 'Next step')} value={item.operatorNextStep || '-'} />
      </div>
    </div>
  );
}

function OperationsWorkPanel({ data }: { data: AdvisorPreviewData }) {
  const { t } = useLocale();
  const branch = data.ai;
  const advisor = branch.source_context.advisor;
  const runtime = getSignal(branch, 'ops.runtime_quality');
  const provider = getSignal(branch, 'ops.provider_quality');
  const knowledge = getSignal(branch, 'ops.knowledge_quality');
  const usage = getSignal(branch, 'ops.usage_cost');
  const actions = advisor.recommendedActions.length
    ? advisor.recommendedActions
    : [{ action: branch.operator_next_step || 'continue_operations_monitoring', requiresOperator: true }];
  const status = advisor.status || branch.status || 'ok';
  const severity = advisor.severity || branch.severity || 'info';

  return (
    <BackofficeSectionPanel className="space-y-5" data-ui="advisor-current-diagnosis">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {t('admin.ai_advisor.current_diagnosis', {}, 'Current diagnosis')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {advisorHeadlineText(branch.headline, t)}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {advisorSummaryText(advisor.summary || branch.operator_summary, t)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <BackofficeStatusBadge label={statusLabel(status, t)} status={statusBadge(status, severity)} />
          <BackofficeStatusBadge label={severityLabel(severity, t)} status={statusBadge(status, severity)} />
        </div>
      </div>

      <BackofficeMetricStrip
        columnsClassName="md:grid-cols-2 xl:grid-cols-4"
        items={[
          {
            label: t('admin.ai_advisor.metric_failed_runs', {}, 'Failed runs'),
            value: formatNumber(Number(runtime.failed_runs || 0)),
            detail: t(
              'admin.ai_advisor.detail_total_runs',
              { total: formatNumber(Number(runtime.total_runs || 0)) },
              '{{total}} total runs'
            ),
            toneClassName: Number(runtime.failed_runs || 0) > 0 ? 'text-amber-600 dark:text-amber-300' : undefined,
          },
          {
            label: t('admin.ai_advisor.metric_provider_errors', {}, 'Provider errors'),
            value: formatNumber(Number(provider.provider_errors || 0)),
            detail: t(
              'admin.ai_advisor.detail_provider_calls',
              { rate: formatRatio(provider.provider_error_rate), calls: formatNumber(Number(provider.provider_calls || 0)) },
              '{{rate}} · {{calls}} calls'
            ),
            toneClassName: Number(provider.provider_errors || 0) > 0 ? 'text-amber-600 dark:text-amber-300' : undefined,
          },
          {
            label: t('admin.ai_advisor.metric_knowledge_no_hits', {}, 'Knowledge no-hits'),
            value: formatNumber(Number(knowledge.knowledge_no_hits || 0)),
            detail: t(
              'admin.ai_advisor.detail_knowledge_searches',
              { rate: formatRatio(knowledge.knowledge_no_hit_rate), searches: formatNumber(Number(knowledge.knowledge_searches || 0)) },
              '{{rate}} · {{searches}} searches'
            ),
            toneClassName: Number(knowledge.knowledge_no_hits || 0) > 0 ? 'text-amber-600 dark:text-amber-300' : undefined,
          },
          {
            label: t('admin.ai_advisor.metric_usage_cost', {}, 'Usage cost'),
            value: formatCost(Number(usage.provider_cost || 0)),
            detail: t(
              'admin.ai_advisor.detail_usage_events',
              { events: formatNumber(Number(usage.usage_events || 0)) },
              '{{events}} usage events'
            ),
            size: 'compact',
          },
        ]}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,0.7fr)]">
        <div className="rounded-xl border border-slate-200/80 bg-white/75 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/35">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('admin.ai_advisor.recommended_actions', {}, 'Recommended actions')}
            </p>
            <BackofficeStatusBadge
              label={advisor.confidence || t('admin.ai_advisor.confidence_unknown', {}, 'confidence unknown')}
              status={advisor.confidence === 'high' ? 'success' : 'inactive'}
            />
          </div>
          <div className="mt-3 space-y-3">
            {actions.map((item, index) => {
              const action = actionDisplay(item.action, t);
              return (
                <div key={`${item.action}-${index}`} className="flex items-start gap-3 rounded-lg border border-slate-200/80 bg-slate-50/80 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/45">
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-950 text-xs font-semibold text-white dark:bg-blue-500 dark:text-slate-950">
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{action.label}</p>
                    <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">{action.detail}</p>
                    {action.href ? (
                      <Link href={action.href} className="mt-2 inline-flex text-xs font-semibold text-blue-700 underline-offset-4 hover:underline dark:text-blue-300">
                        {t('admin.ai_advisor.open_evidence', {}, 'Open evidence')}
                      </Link>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200/80 bg-white/75 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/35">
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('admin.ai_advisor.evidence_entry', {}, 'Evidence entry')}
          </p>
          <div className="mt-3 space-y-2">
            {advisor.evidence.length ? (
              advisor.evidence.slice(0, 5).map((item) => (
                <div key={`${item.kind}-${item.ref}`} className="rounded-lg border border-slate-200/80 bg-slate-50/80 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/45">
                  <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{advisorEvidenceLabel(item.kind, item.label, t)}</p>
                  <p className="mt-1 truncate font-mono text-[0.7rem] text-slate-500 dark:text-slate-400">{item.ref || item.kind}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t('admin.ai_advisor.no_evidence', {}, 'No evidence references returned.')}
              </p>
            )}
          </div>
        </div>
      </div>
    </BackofficeSectionPanel>
  );
}

function AdvisorEvaluationDetails({
  children,
  onToggle,
}: {
  children: React.ReactNode;
  onToggle?: (open: boolean) => void;
}) {
  const { t } = useLocale();
  return (
    <details
      className="rounded-xl border border-slate-200/80 bg-white/65 dark:border-slate-800 dark:bg-slate-950/30"
      onToggle={(event) => onToggle?.(event.currentTarget.open)}
    >
      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-800 hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-900/60">
        {t('admin.ai_advisor.evaluation_details', {}, 'AI evaluation details')}
      </summary>
      <div className="space-y-5 border-t border-slate-200/80 p-4 dark:border-slate-800">
        {children}
      </div>
    </details>
  );
}

function statusBadge(status: string, severity = ''): string {
  if (severity === 'error' || status === 'error') return 'error';
  if (status === 'attention' || status === 'warning' || severity === 'warning') return 'warning';
  if (status === 'ok' || status === 'ready') return 'success';
  return 'inactive';
}

type Translate = (key: string, params?: Record<string, string>, fallback?: string) => string;

function statusLabel(status: string, t: Translate): string {
  switch (status) {
    case 'attention':
      return t('admin.ai_advisor.status_attention', {}, 'Needs attention');
    case 'ready':
      return t('admin.ai_advisor.status_ready', {}, 'Ready');
    case 'ok':
      return t('admin.ai_advisor.status_ok', {}, 'Stable');
    case 'error':
      return t('admin.ai_advisor.status_error', {}, 'Error');
    default:
      return status || t('admin.ai_advisor.status_unknown', {}, 'Unknown status');
  }
}

function severityLabel(severity: string, t: Translate): string {
  switch (severity) {
    case 'warning':
      return t('admin.ai_advisor.severity_warning', {}, 'Warning');
    case 'error':
      return t('admin.ai_advisor.severity_error', {}, 'Error');
    case 'info':
      return t('admin.ai_advisor.severity_info', {}, 'Info');
    default:
      return severity || t('admin.ai_advisor.severity_unknown', {}, 'Unknown severity');
  }
}

function actionDisplay(action: string, t: Translate): { label: string; detail: string; href?: string } {
  switch (action) {
    case 'inspect_failed_runs_by_site_and_ability':
      return {
        label: t('admin.ai_advisor.action_inspect_failed_runs', {}, 'Inspect failed runs'),
        detail: t('admin.ai_advisor.action_inspect_failed_runs_detail', {}, 'Locate failed runs by site, ability, and error code, then decide whether the issue is runtime, provider, or contract related.'),
        href: '/admin/ai-resources',
      };
    case 'inspect_provider_errors_latency_and_fallbacks':
      return {
        label: t('admin.ai_advisor.action_inspect_provider_errors', {}, 'Inspect provider errors and latency'),
        detail: t('admin.ai_advisor.action_inspect_provider_errors_detail', {}, 'Check provider error rate, fallback behavior, latency, and recent model-call evidence.'),
        href: '/admin/ai-resources',
      };
    case 'review_site_knowledge_no_hit_queries_and_index_coverage':
      return {
        label: t('admin.ai_advisor.action_review_knowledge_no_hits', {}, 'Review Site Knowledge no-hits'),
        detail: t('admin.ai_advisor.action_review_knowledge_no_hits_detail', {}, 'Review no-hit queries, index coverage, and intent distribution before deciding whether indexing or local content coverage needs work.'),
        href: '/admin/vector-observability',
      };
    case 'review_subscription_attention_and_expiry_coverage':
      return {
        label: t('admin.ai_advisor.action_review_subscription_risk', {}, 'Review subscription and coverage risk'),
        detail: t('admin.ai_advisor.action_review_subscription_risk_detail', {}, 'Check customers needing follow-up, expiring subscriptions, and service coverage state.'),
        href: '/admin/coverage',
      };
    case 'inspect_queue_worker_and_callback_delivery':
      return {
        label: t('admin.ai_advisor.action_inspect_queue_callbacks', {}, 'Inspect queue and callback delivery'),
        detail: t('admin.ai_advisor.action_inspect_queue_callbacks_detail', {}, 'Confirm whether queued/running pressure, worker handling, or callback failures need operator intervention.'),
        href: '/admin/ai-resources',
      };
    case 'inspect_commercial_entitlement_and_runtime_guard':
      return {
        label: t('admin.ai_advisor.action_inspect_entitlement_guard', {}, 'Inspect entitlement and runtime guard'),
        detail: t('admin.ai_advisor.action_inspect_entitlement_guard_detail', {}, 'Check commercial coverage, runtime denials, and guard events to confirm whether a plan or rate limit triggered the issue.'),
        href: '/admin/coverage',
      };
    case 'continue_operations_monitoring':
      return {
        label: t('admin.ai_advisor.action_continue_monitoring', {}, 'Continue monitoring'),
        detail: t('admin.ai_advisor.action_continue_monitoring_detail', {}, 'No high-priority blocker is visible in the current window. Keep watching for new failure, cost, or coverage signals.'),
      };
    default:
      return {
        label: humanizeKey(action || 'continue_operations_monitoring'),
        detail: t('admin.ai_advisor.action_unknown_detail', {}, 'This is a read-only recommendation. An operator still needs to judge it against the evidence.'),
      };
  }
}

function EffectComparisonPanel({ data }: { data: AdvisorPreviewData }) {
  const { t } = useLocale();
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
            {t('admin.ai_advisor.effect_comparison_label', {}, 'Effect comparison')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {t('admin.ai_advisor.effect_comparison_title', {}, 'Compare operations data, rule baseline, and AI output')}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t('admin.ai_advisor.effect_comparison_desc', {}, 'Both branches use the same Cloud operational evidence. Differences come only from how AI describes the issue and next step.')}
          </p>
        </div>
        <BackofficeStatusBadge
          label={data.comparison.aiUsed ? t('admin.ai_advisor.ai_used', {}, 'AI used') : t('admin.ai_advisor.rules_only', {}, 'Rules only')}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <ComparisonColumn
          eyebrow={t('admin.ai_advisor.raw_ops_data', {}, 'Raw operations data')}
          title={failedRun ? String(failedRun.error_code || t('admin.ai_advisor.runtime_signal', {}, 'Runtime signal')) : t('admin.ai_advisor.current_ops_signal', {}, 'Current operations signal')}
          statusLabel={t('admin.ai_advisor.run_count', { count: formatNumber(Number(runtime.total_runs || 0)) }, '{{count}} runs')}
          status={Number(runtime.failed_runs || 0) > 0 ? 'warning' : 'success'}
          rows={[
            [t('admin.ai_advisor.metric_failed_runs', {}, 'Failed runs'), formatNumber(Number(runtime.failed_runs || 0))],
            [t('admin.ai_advisor.failure_rate', {}, 'Failure rate'), formatRatio(runtime.run_failure_rate)],
            [t('admin.ai_advisor.guard_events', {}, 'Guard events'), formatNumber(Number(runtime.guard_events || 0))],
            [t('admin.ai_advisor.knowledge_no_hits', {}, 'Knowledge no-hits'), formatRatio(knowledge.knowledge_no_hit_rate)],
            [t('admin.ai_advisor.usage_events', {}, 'Usage events'), formatNumber(Number(usage.usage_events || 0))],
          ]}
          detail={
            failedRun
              ? [
                  `run_id: ${String(failedRun.run_id || '-')}`,
                  `site_id: ${String(failedRun.site_id || '-')}`,
                  t('admin.ai_advisor.ability_detail', { family: String(failedRun.ability_family || '-'), name: String(failedRun.ability_name || '-') }, 'Ability: {{family}}/{{name}}'),
                ]
              : [t('admin.ai_advisor.no_failed_run_detail', {}, 'No failed run detail in the current window.')]
          }
        />
        <ComparisonColumn
          eyebrow={t('admin.ai_advisor.rule_analysis', {}, 'Rule analysis')}
          title={data.baseline.headline || t('admin.ai_advisor.branch_baseline', {}, 'Rule baseline')}
          statusLabel={data.baseline.generation.mode || 'rule'}
          status="inactive"
          rows={[
            [t('admin.ai_advisor.mode', {}, 'Mode'), data.baseline.generation.mode || '-'],
            [t('admin.ai_advisor.status', {}, 'Status'), data.baseline.status || '-'],
            [t('admin.ai_advisor.severity', {}, 'Severity'), data.baseline.severity || '-'],
            [t('admin.ai_advisor.next_step', {}, 'Next step'), data.baseline.operator_next_step || '-'],
          ]}
          detail={[data.baseline.operator_summary || t('admin.ai_advisor.no_rule_summary', {}, 'No rule summary.')]}
        />
        <ComparisonColumn
          eyebrow={t('admin.ai_advisor.branch_ai_label', {}, 'AI analysis')}
          title={data.ai.headline || t('admin.ai_advisor.branch_ai_output', {}, 'AI output')}
          statusLabel={data.comparison.aiCalled
            ? t('admin.ai_advisor.live_call', {}, 'Live call')
            : data.comparison.cacheHit
              ? t('admin.ai_advisor.cache_hit_label', {}, 'Cache hit')
              : t('admin.ai_advisor.not_called', {}, 'Not called')}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
          rows={[
            [t('admin.ai_advisor.mode', {}, 'Mode'), data.ai.generation.mode || '-'],
            [t('admin.ai_advisor.model', {}, 'Model'), data.comparison.modelId || data.ai.generation.model_id || '-'],
            [t('admin.ai_advisor.cost', {}, 'Cost'), formatCost(data.comparison.requestCost || 0)],
            [t('admin.ai_advisor.text_changed', {}, 'Text changed'), data.comparison.textChanged ? t('common.yes', {}, 'Yes') : t('common.no', {}, 'No')],
          ]}
          detail={[
            data.ai.operator_summary || t('admin.ai_advisor.no_ai_summary', {}, 'No AI summary.'),
            aiAddedSpecificity
              ? t('admin.ai_advisor.ai_added_specificity', {}, 'AI added concrete run, site, error, or ability clues.')
              : t('admin.ai_advisor.no_extra_specificity', {}, 'No additional concrete identifier was detected in the current output.'),
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
  const { t } = useLocale();
  const inputTypes = buildAiInputTypes(data.ai, t);
  const valueBullets = buildAiValueBullets(data, t);
  return (
    <BackofficeSectionPanel className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {t('admin.ai_advisor.ai_participation_evidence', {}, 'AI participation evidence')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {t('admin.ai_advisor.ai_participation_title', {}, 'Evidence sent to AI and output changes')}
          </h2>
        </div>
        <BackofficeStatusBadge
          label={data.comparison.aiCalled
            ? t('admin.ai_advisor.live_call', {}, 'Live call')
            : data.comparison.cacheHit
              ? t('admin.ai_advisor.cache_hit_label', {}, 'Cache hit')
              : t('admin.ai_advisor.not_called', {}, 'Not called')}
          status={data.comparison.aiUsed ? 'success' : 'inactive'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="grid gap-3 sm:grid-cols-2">
          <BackofficeStackCard>
            <MiniMetric label={t('admin.ai_advisor.provider_adapter', {}, 'Provider adapter')} value={data.comparison.requestedProviderId || data.ai.generation.provider_id || '-'} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label={t('admin.ai_advisor.model', {}, 'Model')} value={data.comparison.modelId || data.ai.generation.model_id || '-'} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label={t('admin.ai_advisor.metric_tokens', {}, 'Tokens')} value={t('admin.ai_advisor.detail_tokens_io', { input: formatNumber(data.comparison.tokensIn), output: formatNumber(data.comparison.tokensOut) }, '{{input}} in / {{output}} out')} />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric label={t('admin.ai_advisor.current_cost', {}, 'Current cost')} value={formatCost(data.comparison.requestCost || 0)} />
          </BackofficeStackCard>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <EvidenceList title={t('admin.ai_advisor.input_data_types', {}, 'Input data types')} items={inputTypes} empty={t('admin.ai_advisor.no_input_types', {}, 'No redacted input types were detected.')} />
          <EvidenceList title={t('admin.ai_advisor.ai_incremental_value', {}, 'AI incremental value')} items={valueBullets} empty={t('admin.ai_advisor.no_ai_incremental_value', {}, 'No AI-only difference was detected yet.')} />
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

function buildAiInputTypes(branch: SummaryBranch, t: Translator): string[] {
  const signals = branch.source_context.advisor.signals;
  const drilldown = branch.source_context.advisor.drilldown;
  const items: string[] = [];
  if (signals.some((signal) => signal.code === 'ops.runtime_quality')) {
    items.push(t('admin.ai_advisor.input_runtime_quality', {}, 'Runtime quality: run count, failures, callbacks, and guard events.'));
  }
  if (Array.isArray(drilldown.failed_runs) && drilldown.failed_runs.length > 0) {
    items.push(t('admin.ai_advisor.input_failed_run_detail', {}, 'Failed run detail: run id, site id, ability, error code, and selected provider/model.'));
  }
  if (signals.some((signal) => signal.code === 'ops.knowledge_quality')) {
    items.push(t('admin.ai_advisor.input_knowledge_quality', {}, 'Site Knowledge search health: no-hit rate, search failures, indexed documents, and chunks.'));
  }
  if (signals.some((signal) => signal.code === 'ops.provider_quality')) {
    items.push(t('admin.ai_advisor.input_provider_quality', {}, 'Provider quality: calls, error rate, fallback count, and latency.'));
  }
  if (signals.some((signal) => signal.code === 'ops.usage_cost')) {
    items.push(t('admin.ai_advisor.input_usage_cost', {}, 'Usage and cost signals: usage events, metered quantity, reported cost, and provider cost.'));
  }
  return items;
}

function buildAiValueBullets(data: AdvisorPreviewData, t: Translator): string[] {
  const failedRun = getDrilldownRows(data.ai, 'failed_runs')[0];
  const aiText = [
    data.ai.headline,
    data.ai.operator_summary,
    data.ai.support_draft,
    data.ai.operator_next_step,
  ].join(' ');
  const bullets: string[] = [];
  if (data.comparison.aiCalled) {
    bullets.push(t('admin.ai_advisor.value_live_provider_call', {}, 'This analysis used a live provider call instead of deterministic rules only.'));
  } else if (data.comparison.cacheHit) {
    bullets.push(t('admin.ai_advisor.value_cached_result', {}, 'A previous AI cached result was reused to avoid another provider call.'));
  }
  if (data.comparison.textChanged) {
    bullets.push(t('admin.ai_advisor.value_text_changed', {}, 'AI rewrote the operator-facing summary or next-step wording.'));
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
    bullets.push(t('admin.ai_advisor.value_extracted_failed_run', {}, 'AI extracted failed run identifiers an operator can inspect directly.'));
  }
  if (data.ai.operator_next_step && data.ai.operator_next_step !== data.baseline.operator_next_step) {
    bullets.push(t('admin.ai_advisor.value_more_specific_next_step', {}, 'AI gave a more specific operational next step than the rule baseline.'));
  }
  return bullets;
}

function ScenarioChecksPanel({ data }: { data: AdvisorPreviewData }) {
  const { t } = useLocale();
  const scenarios = buildScenarioChecks(data, t);
  return (
    <BackofficeSectionPanel className="space-y-5">
      <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          {t('admin.ai_advisor.scenarios_label', {}, 'Fixed scenarios')}
        </p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
          {t('admin.ai_advisor.scenarios_title', {}, 'Use stable scenarios to judge whether AI is useful')}
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
              <BackofficeStatusBadge label={scenario.status === 'active' ? t('admin.ai_advisor.active', {}, 'Active') : t('admin.ai_advisor.quiet', {}, 'Quiet')} status={scenario.status === 'active' ? 'warning' : 'inactive'} />
            </div>
            <div className="space-y-2 border-t border-slate-200/80 pt-3 dark:border-slate-800">
              <MiniMetric label={t('admin.ai_advisor.evidence', {}, 'Evidence')} value={scenario.evidence} />
              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">{scenario.aiValue}</p>
            </div>
          </BackofficeStackCard>
        ))}
      </div>
    </BackofficeSectionPanel>
  );
}

function AgentHandoffPanel({ handoff }: { handoff: AgentHandoff }) {
  const { t } = useLocale();
  const hasHandoff = Boolean(handoff.agentId || handoff.handoffType || handoff.agentRole);
  if (!hasHandoff) {
    return null;
  }

  return (
    <BackofficeSectionPanel className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
            {t('admin.ai_advisor.agent_boundary_label', {}, 'Agent boundary')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {t('admin.ai_advisor.agent_boundary_title', {}, 'Internal diagnostic agent handoff boundary')}
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t('admin.ai_advisor.agent_boundary_desc', {}, 'This metadata comes from redacted diagnostic context and is only used to show handoff boundaries and forbidden actions.')}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <BackofficeStatusBadge
            label={handoff.directWordPressWrite ? t('admin.ai_advisor.write_allowed', {}, 'Write allowed') : t('admin.ai_advisor.write_blocked', {}, 'Write blocked')}
            status={handoff.directWordPressWrite ? 'error' : 'success'}
          />
          <BackofficeStatusBadge
            label={handoff.requiresOperatorReview ? t('admin.ai_advisor.review_required', {}, 'Review required') : t('admin.ai_advisor.review_optional', {}, 'Review optional')}
            status={handoff.requiresOperatorReview ? 'warning' : 'inactive'}
          />
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <BackofficeStackCard>
          <MiniMetric label="Agent" value={handoff.agentId || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label={t('admin.ai_advisor.version', {}, 'Version')} value={handoff.agentVersion || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label={t('admin.ai_advisor.handoff_type', {}, 'Handoff type')} value={handoff.handoffType || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label={t('admin.ai_advisor.owner', {}, 'Owner')} value={handoff.handoffOwner || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label={t('admin.ai_advisor.execution_pattern', {}, 'Execution pattern')} value={handoff.executionPattern || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard>
          <MiniMetric label={t('admin.ai_advisor.storage_mode', {}, 'Storage mode')} value={handoff.storageMode || '-'} />
        </BackofficeStackCard>
        <BackofficeStackCard className="md:col-span-2">
          <MiniMetric label={t('admin.ai_advisor.fail_closed_behavior', {}, 'Fail-closed behavior')} value={handoff.failClosedBehavior || '-'} />
        </BackofficeStackCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <EvidenceList
          title={t('admin.ai_advisor.allowed_actions', {}, 'Allowed actions')}
          items={handoff.allowedActions.map(humanizeKey)}
          empty={t('admin.ai_advisor.no_allowed_actions', {}, 'No allowed actions declared.')}
        />
        <EvidenceList
          title={t('admin.ai_advisor.stop_conditions', {}, 'Stop conditions')}
          items={handoff.stopConditions.map(humanizeKey)}
          empty={t('admin.ai_advisor.no_stop_conditions', {}, 'No stop conditions declared.')}
        />
        <EvidenceList
          title={t('admin.ai_advisor.forbidden_actions', {}, 'Forbidden actions')}
          items={handoff.forbiddenActions.map(humanizeKey)}
          empty={t('admin.ai_advisor.no_forbidden_actions', {}, 'No forbidden actions declared.')}
        />
      </div>
    </BackofficeSectionPanel>
  );
}

function buildScenarioChecks(data: AdvisorPreviewData, t: Translator): ScenarioCheck[] {
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
      title: t('admin.ai_advisor.scenario_runtime_failure_title', {}, 'Runtime failure analysis'),
      status: Number(runtime.failed_runs || 0) > 0 ? 'active' : 'quiet',
      headline: failedRun
        ? t('admin.ai_advisor.scenario_runtime_failure_headline', { site: String(failedRun.site_id || 'site'), error: String(failedRun.error_code || t('admin.ai_advisor.failed_run', {}, 'failed run')) }, '{{site}} has {{error}}.')
        : t('admin.ai_advisor.scenario_no_failed_run', {}, 'No failed run in the current window.'),
      evidence: t('admin.ai_advisor.scenario_failure_evidence', { failed: formatNumber(Number(runtime.failed_runs || 0)), total: formatNumber(Number(runtime.total_runs || 0)) }, '{{failed}} failed / {{total}} runs'),
      aiValue: failedRun
        ? t('admin.ai_advisor.scenario_failure_ai_value', {}, 'AI should explain the likely failure path and point to the specific run and operator action.')
        : t('admin.ai_advisor.scenario_no_failure_ai_value', {}, 'AI should stay quiet or confirm there is no primary failed-run cause right now.'),
    },
    {
      key: 'knowledge_no_hit',
      title: t('admin.ai_advisor.scenario_knowledge_title', {}, 'Knowledge no-hit analysis'),
      status: Number(knowledge.knowledge_no_hits || 0) > 0 ? 'active' : 'quiet',
      headline: t('admin.ai_advisor.scenario_knowledge_headline', { searches: formatNumber(Number(knowledge.knowledge_searches || 0)), rate: formatRatio(knowledge.knowledge_no_hit_rate) }, '{{searches}} searches, {{rate}} no-hit rate.'),
      evidence: t('admin.ai_advisor.scenario_knowledge_evidence', { documents: formatNumber(Number(knowledge.indexed_documents || 0)), chunks: formatNumber(Number(knowledge.indexed_chunks || 0)) }, '{{documents}} documents / {{chunks}} chunks'),
      aiValue: t('admin.ai_advisor.scenario_knowledge_ai_value', {}, 'AI should connect no-hit patterns to indexing, content coverage, or query intent gaps.'),
    },
    {
      key: 'provider_cost_latency',
      title: t('admin.ai_advisor.scenario_provider_title', {}, 'Provider cost or latency anomaly'),
      status: providerErrorRate > 0 || avgLatency > 0 || providerCalls > 0 ? 'active' : 'quiet',
      headline: t('admin.ai_advisor.scenario_provider_headline', { calls: formatNumber(providerCalls), rate: formatRatio(providerErrorRate) }, '{{calls}} provider calls, {{rate}} error rate.'),
      evidence: t('admin.ai_advisor.scenario_provider_evidence', { latency: formatNumber(avgLatency) }, '{{latency}} ms average latency'),
      aiValue: t('admin.ai_advisor.scenario_provider_ai_value', {}, 'AI should first distinguish provider degradation from application/runtime failure, then recommend an action.'),
    },
  ];
}

function valueSignalBadge(value: string): string {
  if (value === 'promising') return 'success';
  if (value === 'needs_review_loop' || value === 'provider_blocked') return 'warning';
  if (value === 'not_using_ai' || value === 'insufficient_data') return 'inactive';
  return 'inactive';
}

function valueSignalLabel(value: string, t: Translator): string {
  switch (value) {
    case 'promising':
      return t('admin.ai_advisor.value_signal_promising', {}, 'Value signal');
    case 'needs_review_loop':
      return t('admin.ai_advisor.value_signal_needs_review_loop', {}, 'Needs review loop');
    case 'provider_blocked':
      return t('admin.ai_advisor.value_signal_provider_blocked', {}, 'Provider blocked');
    case 'not_using_ai':
      return t('admin.ai_advisor.value_signal_not_using_ai', {}, 'AI not used');
    case 'insufficient_data':
      return t('admin.ai_advisor.value_signal_insufficient_data', {}, 'Insufficient data');
    default:
      return value || t('common.unknown', {}, 'Unknown');
  }
}

function ValueMetricsPanel({ valueMetrics }: { valueMetrics: AdvisorValueMetrics | null }) {
  const { t } = useLocale();
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
            {t('admin.ai_advisor.value_tracking_label', {}, 'Value tracking')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
            {valueMetrics.valueSignal.headline || t('admin.ai_advisor.value_tracking_default_headline', {}, 'AI value does not have enough evidence yet')}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {valueMetrics.valueSignal.nextStep || t('admin.ai_advisor.value_tracking_default_next_step', {}, 'Run operator-triggered diagnostics and review the output before expanding AI usage.')}
          </p>
        </div>
        <BackofficeStatusBadge
          label={valueSignalLabel(valueMetrics.valueSignal.status, t)}
          status={valueSignalBadge(valueMetrics.valueSignal.status)}
        />
      </div>

      <BackofficeMetricStrip
        columnsClassName="md:grid-cols-2 xl:grid-cols-5"
        items={[
          {
            label: t('admin.ai_advisor.requests', {}, 'Requests'),
            value: formatNumber(valueMetrics.totals.analysisRequests),
            detail: t('admin.ai_advisor.days_window', { days: String(valueMetrics.window.days || 7) }, '{{days}} day window'),
          },
          {
            label: t('admin.ai_advisor.ai_calls', {}, 'AI calls'),
            value: formatNumber(valueMetrics.totals.aiCalled),
            detail: t('admin.ai_advisor.live_call_rate', { rate: formatPercent(valueMetrics.rates.aiCallRate) }, '{{rate}} live call rate'),
          },
          {
            label: t('admin.ai_advisor.cache_hits', {}, 'Cache hits'),
            value: formatPercent(valueMetrics.rates.cacheHitRate),
            detail: t('admin.ai_advisor.cached_diagnostics_count', { count: formatNumber(valueMetrics.totals.cacheHits) }, '{{count}} cached diagnostics'),
          },
          {
            label: t('admin.ai_advisor.metric_request_cost', {}, 'Request cost'),
            value: formatCost(valueMetrics.totals.requestCost),
            detail: t('admin.ai_advisor.estimated_savings', { cost: formatCost(valueMetrics.totals.estimatedCacheSavings) }, 'Estimated savings {{cost}}'),
            size: 'compact',
          },
          {
            label: t('admin.ai_advisor.confirmed', {}, 'Confirmed'),
            value: formatPercent(valueMetrics.rates.confirmedRate),
            detail: t('admin.ai_advisor.confirmed_ai_items', { confirmed: formatNumber(valueMetrics.review.humanConfirmed), total: formatNumber(valueMetrics.review.cachedAiItems) }, '{{confirmed}} confirmed / {{total}} AI items'),
          },
        ]}
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.65fr)]">
        <div className="grid gap-3 sm:grid-cols-3">
          <BackofficeStackCard>
            <MiniMetric
              label={t('admin.ai_advisor.pending_review', {}, 'Pending review')}
              value={formatNumber(valueMetrics.review.needsReview)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label={t('admin.ai_advisor.edited_after_ai', {}, 'Edited after AI')}
              value={formatNumber(valueMetrics.review.editedAfterAi)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label={t('admin.ai_advisor.rule_fallbacks', {}, 'Rule fallbacks')}
              value={formatNumber(valueMetrics.totals.deterministicFallbacks)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label={t('admin.ai_advisor.provider_errors', {}, 'Provider errors')}
              value={formatNumber(valueMetrics.totals.providerErrors)}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label={t('admin.ai_advisor.primary_provider', {}, 'Primary provider')}
              value={topProvider ? `${topProvider.providerId} · ${formatCost(topProvider.cost)}` : '-'}
            />
          </BackofficeStackCard>
          <BackofficeStackCard>
            <MiniMetric
              label={t('admin.ai_advisor.primary_model', {}, 'Primary model')}
              value={topModel ? `${topModel.modelId} · ${formatCost(topModel.cost)}` : '-'}
            />
          </BackofficeStackCard>
        </div>
        <BackofficeStackCard>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
            {t('admin.ai_advisor.recent_ai_events', {}, 'Recent AI events')}
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
              <p className="text-sm text-slate-500 dark:text-slate-400">{t('admin.ai_advisor.no_recent_events', {}, 'No diagnostic usage events in the current window.')}</p>
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
  const [evaluationDetailsOpen, setEvaluationDetailsOpen] = useState(false);
  const [evaluationDetailsLoading, setEvaluationDetailsLoading] = useState(false);
  const [evaluationDetailsError, setEvaluationDetailsError] = useState('');
  const [loadedEvaluationDetailsKey, setLoadedEvaluationDetailsKey] = useState('');
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
  const previewRequestActiveRef = useRef('');
  const previewRequestCompletedRef = useRef('');
  const previewRequestSequenceRef = useRef(0);
  const evaluationDetailsRequestActiveRef = useRef('');
  const evaluationDetailsRequestSequenceRef = useRef(0);
  const historyScope = data?.ai.scope || data?.baseline.scope || '';
  const evaluationDetailsKey = [
    historyScope || scope,
    siteId.trim(),
    data?.ai.generation.cache_key || data?.ai.ai_disclosure.generated_at || 'current',
  ].join('|');

  const loadHistory = useCallback(async () => {
    const params = new URLSearchParams();
    params.set('limit', '10');
    if (historyScope) {
      params.set('scope', historyScope);
    }
    if (siteId.trim()) {
      params.set('site_id', siteId.trim());
    }
    const response = await operationsAdvisorClient.request<unknown>(
      `/api/admin/advisor/ops-summary-history?${params.toString()}`
    );
    const payload = response.data as { items?: unknown };
    const items = Array.isArray(payload?.items)
      ? payload.items.map((item: any) => normalizeHistoryItem(item))
      : [];
    return items;
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
      const valueResponse = await operationsAdvisorClient.request<unknown>(
        `/api/admin/advisor/ops-summary-value?${valueParams.toString()}`
      );
      return normalizeValueMetrics(valueResponse.data ?? {});
    },
    [scope, siteId]
  );

  const loadPreview = useCallback(async (force = false) => {
    const requestKey = [scope, siteId.trim(), providerId.trim(), modelId.trim(), forceRefresh, reloadKey].join('|');
    if (
      previewRequestActiveRef.current === requestKey ||
      (!force && previewRequestCompletedRef.current === requestKey)
    ) {
      return;
    }
    const sequence = previewRequestSequenceRef.current + 1;
    previewRequestSequenceRef.current = sequence;
    previewRequestActiveRef.current = requestKey;
    setLoading(true);
    setError('');
    setEvaluationDetailsError('');
    setLoadedEvaluationDetailsKey('');
    setHistoryItems([]);
    setValueMetrics(null);
    try {
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

        const response = await operationsAdvisorClient.request<unknown>(
          `/api/admin/advisor/ops-summary-preview?${params.toString()}`
        );
        const nextData = normalizePreview(response.data ?? {});
        if (sequence === previewRequestSequenceRef.current) {
          setData(nextData);
        }
      } catch (previewError) {
        if (sequence === previewRequestSequenceRef.current) {
          setData(null);
          setError(resolveUiErrorMessage(previewError, t('error.failed_load')));
        }
      }
    } finally {
      if (sequence === previewRequestSequenceRef.current) {
        previewRequestActiveRef.current = '';
        previewRequestCompletedRef.current = requestKey;
        setLoading(false);
      }
    }
  }, [forceRefresh, modelId, providerId, reloadKey, scope, siteId, t]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview, reloadKey]);

  const loadEvaluationDetails = useCallback(
    async (force = false) => {
      if (
        !data ||
        loading ||
        (!force &&
          (evaluationDetailsRequestActiveRef.current === evaluationDetailsKey ||
            loadedEvaluationDetailsKey === evaluationDetailsKey))
      ) {
        return;
      }

      const sequence = evaluationDetailsRequestSequenceRef.current + 1;
      evaluationDetailsRequestSequenceRef.current = sequence;
      evaluationDetailsRequestActiveRef.current = evaluationDetailsKey;
      setEvaluationDetailsLoading(true);
      setEvaluationDetailsError('');
      const results = await Promise.allSettled([
        loadHistory(),
        loadValueMetrics(historyScope || scope),
      ] as const);
      if (sequence !== evaluationDetailsRequestSequenceRef.current) {
        return;
      }
      if (results[0].status === 'fulfilled') {
        setHistoryItems(results[0].value);
      }
      if (results[1].status === 'fulfilled') {
        setValueMetrics(results[1].value);
      }
      const failures = results.filter(
        (result): result is PromiseRejectedResult => result.status === 'rejected'
      );
      if (failures.length > 0) {
        setEvaluationDetailsError(
          resolveUiErrorMessage(
            failures[0].reason,
            t(
              'admin.ai_advisor.error_evaluation_details',
              {},
              'Some evaluation details could not be loaded.'
            )
          )
        );
      }
      evaluationDetailsRequestActiveRef.current = '';
      setLoadedEvaluationDetailsKey(evaluationDetailsKey);
      setEvaluationDetailsLoading(false);
    },
    [
      data,
      evaluationDetailsKey,
      historyScope,
      loadHistory,
      loadedEvaluationDetailsKey,
      loading,
      loadValueMetrics,
      scope,
      t,
    ]
  );

  useEffect(() => {
    if (evaluationDetailsOpen) {
      void loadEvaluationDetails();
    }
  }, [evaluationDetailsOpen, loadEvaluationDetails]);

  const copyWithDisclosure = useCallback(
    async (value: string, disclosure: SummaryBranch['ai_disclosure']) => {
      try {
        const text = buildDisclosureClipboardText(value, disclosure, t);
        await navigator.clipboard.writeText(text);
        setCopyMessage(t('admin.ai_advisor.message_copied_with_disclosure', {}, 'Copied with AI disclosure'));
        window.setTimeout(() => setCopyMessage(''), 2200);
      } catch (err) {
        setError(resolveUiErrorMessage(err, t('admin.ai_advisor.error_copy_disclosure', {}, 'Failed to copy text with AI disclosure.')));
      }
    },
    [t]
  );

  const reviewDisclosure = useCallback(
    async (reviewStatus: 'human_confirmed' | 'edited_after_ai') => {
      const cacheKey = data?.ai.generation.cache_key || '';
      if (!cacheKey) {
        setError(t('admin.ai_advisor.error_missing_cache_key', {}, 'Missing AI diagnosis cache key. Run diagnosis again before confirming.'));
        return;
      }
      setReviewingDisclosure(true);
      setError('');
      try {
        const response = await operationsAdvisorClient.request<unknown>(
          '/api/admin/advisor/ops-summary-review',
          {
          method: 'POST',
          body: {
            cache_key: cacheKey,
            review_status: reviewStatus,
          },
          }
        );
        const payload = response.data as { ai_disclosure?: unknown };
        const nextDisclosure = payload?.ai_disclosure;
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
        if (evaluationDetailsOpen) {
          void loadEvaluationDetails(true);
        }
      } catch (err) {
        setError(resolveUiErrorMessage(err, t('error.failed_save')));
      } finally {
        setReviewingDisclosure(false);
      }
    },
    [data?.ai, evaluationDetailsOpen, loadEvaluationDetails, t]
  );

  const metricItems = useMemo(() => {
    const comparison = data?.comparison;
    return [
      {
        label: t('admin.ai_advisor.metric_ai_participation', {}, 'AI participation'),
        value: comparison?.aiUsed ? t('common.yes', {}, 'Yes') : t('common.no', {}, 'No'),
        detail: comparison?.cacheHit
          ? t('admin.ai_advisor.detail_from_cache', {}, 'From cache')
          : comparison?.aiCalled
            ? t('admin.ai_advisor.detail_live_provider_call', {}, 'Live provider call')
            : valueCheckLabel(comparison?.valueCheck || '', t),
        toneClassName: comparison?.aiUsed ? 'text-emerald-600 dark:text-emerald-300' : 'text-slate-600 dark:text-slate-300',
      },
      {
        label: t('admin.ai_advisor.metric_cache', {}, 'Cache'),
        value: comparison?.cacheHit
          ? t('admin.ai_advisor.cache_hit', {}, 'Hit')
          : comparison?.cacheStatus === 'miss'
            ? t('admin.ai_advisor.cache_miss', {}, 'Miss')
            : '-',
        detail: forceRefresh
          ? t('admin.ai_advisor.detail_force_refresh_on', {}, 'Force refresh is on')
          : t('admin.ai_advisor.detail_default_cache', {}, 'Default cache: 30 minutes'),
      },
      {
        label: t('admin.ai_advisor.metric_tokens', {}, 'Tokens'),
        value: formatNumber((comparison?.tokensIn || 0) + (comparison?.tokensOut || 0)),
        detail: t(
          'admin.ai_advisor.detail_tokens_io',
          { input: formatNumber(comparison?.tokensIn || 0), output: formatNumber(comparison?.tokensOut || 0) },
          '{{input}} in / {{output}} out'
        ),
      },
      {
        label: t('admin.ai_advisor.metric_request_cost', {}, 'Request cost'),
        value: formatCost(comparison?.requestCost || 0),
        detail: comparison?.cacheHit
          ? t('admin.ai_advisor.detail_cached_original_cost', { cost: formatCost(comparison?.cost || 0) }, 'Cached result, original cost {{cost}}')
          : comparison?.errorCode
            ? t('admin.ai_advisor.detail_error_code', { code: comparison.errorCode }, 'Error: {{code}}')
            : t('admin.ai_advisor.detail_this_page_load', {}, 'This page load'),
        size: 'compact' as const,
      },
    ];
  }, [data, forceRefresh, t]);

  if (loading && !data) {
    return <LoadingFallback />;
  }

  if (error && !data) {
    return (
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow={t('admin.ai_advisor.eyebrow', {}, 'Internal operations')}
          title={t('admin.ai_advisor.title', {}, 'Operations Advisor')}
          description={t('admin.ai_advisor.load_error_desc', {}, 'The current diagnostic summary could not be loaded. No provider, routing, package, or WordPress state was changed.')}
        />
        <BackofficeDiagnosticNotice message={error} retryLabel={t('common.retry')} onRetry={() => void loadPreview(true)} />
      </BackofficePageStack>
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.ai_advisor.eyebrow', {}, 'Internal operations')}
        title={t('admin.ai_advisor.title', {}, 'Operations Advisor')}
        description={t(
          'admin.ai_advisor.description',
          {},
          'Generate read-only diagnostic summaries from Cloud operational evidence and compare rule baseline output with AI output.'
        )}
        aside={data ? <BackofficeStatusBadge label={data.comparison.aiUsed ? t('admin.ai_advisor.ai_used', {}, 'AI used') : t('admin.ai_advisor.rules_only', {}, 'Rules only')} status={data.comparison.aiUsed ? 'success' : 'inactive'} /> : undefined}
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
              {t(option.labelKey, {}, option.fallback)}
            </button>
          ))}
          <span className="mx-1 h-5 w-px bg-slate-200 dark:bg-slate-700" />
          <input
            type="text"
            value={siteIdInput}
            aria-label={t('admin.ai_advisor.site_filter_label', {}, 'Site ID')}
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
            {loading ? t('common.loading', {}, 'Loading...') : t('admin.ai_advisor.action_run_diagnosis', {}, 'Run diagnosis')}
          </button>
        </div>
        <details className="mt-4 rounded-xl border border-slate-200/80 bg-white/65 dark:border-slate-800 dark:bg-slate-950/30">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-800 hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-900/60">
            {t('admin.ai_advisor.advanced_params', {}, 'Advanced evaluation parameters')}
          </summary>
          <div className="space-y-4 border-t border-slate-200/80 px-4 py-3 dark:border-slate-800">
            <BackofficeMetricStrip columnsClassName="md:grid-cols-2 xl:grid-cols-4" items={metricItems} />
            <div className="flex flex-wrap items-center gap-3">
            <input
              type="text"
              value={providerIdInput}
              aria-label={t('admin.ai_advisor.provider_filter_label', {}, 'Provider ID')}
              onChange={(event) => setProviderIdInput(event.target.value)}
              placeholder="provider_id"
              className="h-8 w-40 rounded-full border border-slate-200/80 bg-white/80 px-3 text-xs text-slate-700 placeholder:text-slate-400 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
            />
            <input
              type="text"
              value={modelIdInput}
              aria-label={t('admin.ai_advisor.model_filter_label', {}, 'Model ID')}
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
              {t('admin.ai_advisor.force_refresh', {}, 'Force refresh')}
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
              {t('admin.ai_advisor.action_run_deepseek_comparison', {}, 'Run DeepSeek comparison')}
            </button>
            <p className="basis-full text-xs leading-5 text-slate-500 dark:text-slate-400">
              {t(
                'admin.ai_advisor.advanced_params_desc',
                {},
                'These parameters are only for internal AI summary evaluation. They do not change routing, packages, WordPress content, or customer state.'
              )}
            </p>
            </div>
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
          <OperationsWorkPanel data={data} />

          <AdvisorEvaluationDetails onToggle={setEvaluationDetailsOpen}>
            <SignalPanel branch={data.ai} />
            {evaluationDetailsLoading ? <LoadingFallback /> : null}
            {evaluationDetailsError ? (
              <BackofficeDiagnosticNotice
                message={evaluationDetailsError}
                retryLabel={t('common.retry')}
                onRetry={() => void loadEvaluationDetails(true)}
              />
            ) : null}
            {loadedEvaluationDetailsKey === evaluationDetailsKey ? (
              <>
                <HistoryPanel items={historyItems} />
                <ValueMetricsPanel valueMetrics={valueMetrics} />
              </>
            ) : null}
            <EffectComparisonPanel data={data} />
            <AiParticipationPanel data={data} />
            <ScenarioChecksPanel data={data} />

            <div className="grid gap-5 xl:grid-cols-2">
              <BranchPanel title={t('admin.ai_advisor.branch_baseline', {}, 'Rule baseline')} branch={data.baseline} accent="baseline" />
              <BranchPanel
                title={t('admin.ai_advisor.branch_ai_output', {}, 'AI output')}
                branch={data.ai}
                accent="ai"
                onReviewDisclosure={reviewDisclosure}
                onCopyWithDisclosure={copyWithDisclosure}
                reviewingDisclosure={reviewingDisclosure}
              />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
              <BackofficeSectionPanel className="space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t('admin.ai_advisor.judgement', {}, 'Judgement')}
                    </p>
                    <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                      {valueCheckLabel(data.comparison.valueCheck, t)}
                    </h2>
                  </div>
                  <BackofficeStatusBadge
                    label={data.comparison.valueCheck}
                    status={valueCheckStatus(data.comparison.valueCheck)}
                  />
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <BackofficeStackCard>
                    <MiniMetric label={t('admin.ai_advisor.baseline_mode', {}, 'Rule mode')} value={data.comparison.baselineMode || '-'} />
                  </BackofficeStackCard>
                  <BackofficeStackCard>
                    <MiniMetric label={t('admin.ai_advisor.ai_mode', {}, 'AI mode')} value={data.comparison.aiMode || '-'} />
                  </BackofficeStackCard>
                  <BackofficeStackCard>
                    <MiniMetric label={t('admin.ai_advisor.cache_hit_label', {}, 'Cache hit')} value={data.comparison.cacheHit ? t('common.yes', {}, 'Yes') : t('common.no', {}, 'No')} />
                  </BackofficeStackCard>
                  <BackofficeStackCard>
                    <MiniMetric label={t('admin.ai_advisor.requested_provider', {}, 'Requested provider')} value={data.comparison.requestedProviderId || '-'} />
                  </BackofficeStackCard>
                  <BackofficeStackCard>
                    <MiniMetric label={t('admin.ai_advisor.model', {}, 'Model')} value={data.comparison.modelId || '-'} />
                  </BackofficeStackCard>
                </div>
              </BackofficeSectionPanel>

              <BackofficeSectionPanel className="space-y-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                    {t('admin.ai_advisor.safety_boundary_label', {}, 'Safety boundary')}
                  </p>
                  <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{t('admin.ai_advisor.execution_boundary_title', {}, 'Execution boundary')}</h2>
                </div>
                <div className="space-y-3">
                  <SafetyRow label={t('admin.ai_advisor.prompt_storage_blocked', {}, 'Prompt storage blocked')} ok={!data.safety.promptSaved} />
                  <SafetyRow label={t('admin.ai_advisor.output_storage_blocked', {}, 'Output text storage blocked')} ok={!data.safety.outputTextSaved} />
                  <SafetyRow label={t('admin.ai_advisor.wordpress_write_blocked', {}, 'WordPress write blocked')} ok={!data.safety.wordpressWriteAllowed} />
                  <SafetyRow
                    label={t('admin.ai_advisor.customer_article_generation_blocked', {}, 'Customer article generation blocked')}
                    ok={!data.safety.customerArticleGenerationAllowed}
                  />
                  <SafetyRow label={t('admin.ai_advisor.operator_review_required', {}, 'Operator review required')} ok={data.safety.requiresOperatorReview} />
                </div>
              </BackofficeSectionPanel>
            </div>

            <AgentHandoffPanel handoff={data.ai.agentMetadataProjection} />
          </AdvisorEvaluationDetails>
        </>
      ) : null}
    </BackofficePageStack>
  );
}

function SignalPanel({ branch }: { branch: SummaryBranch }) {
  const { t } = useLocale();
  const signals = branch.source_context.advisor.signals;
  const evidence = branch.source_context.advisor.evidence;
  const drilldown = branch.source_context.advisor.drilldown;
  return (
    <BackofficeSectionPanel className="space-y-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          {t('admin.ai_advisor.evidence', {}, 'Evidence')}
        </p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{t('admin.ai_advisor.ai_input_signals', {}, 'AI input signals')}</h2>
      </div>
      <div className="space-y-3">
        {signals.length ? (
          signals.map((signal, index) => <SignalRow key={`${String(signal.code || 'signal')}-${index}`} signal={signal} />)
        ) : (
          <p className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
            {t('admin.ai_advisor.no_ai_input_signals', {}, 'No redacted operational signals were passed to the AI branch.')}
          </p>
        )}
      </div>
      <DrilldownPanel drilldown={drilldown} />
      <div className="border-t border-slate-200/80 pt-4 dark:border-slate-800">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
          {t('admin.ai_advisor.sources', {}, 'Sources')}
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
  const { t } = useLocale();
  const sections = [
    { key: 'failed_runs', label: t('admin.ai_advisor.drilldown_failed_runs', {}, 'Failed runs') },
    { key: 'run_sites', label: t('admin.ai_advisor.drilldown_run_sites', {}, 'Run sites') },
    { key: 'ability_families', label: t('admin.ai_advisor.drilldown_ability_families', {}, 'Ability families') },
    { key: 'provider_breakdown', label: t('admin.ai_advisor.drilldown_providers', {}, 'Providers') },
    { key: 'model_breakdown', label: t('admin.ai_advisor.drilldown_models', {}, 'Models') },
    { key: 'knowledge_sites', label: t('admin.ai_advisor.drilldown_knowledge_sites', {}, 'Knowledge sites') },
    { key: 'knowledge_intents', label: t('admin.ai_advisor.drilldown_knowledge_intents', {}, 'Knowledge intents') },
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
        {t('admin.ai_advisor.ops_detail', {}, 'Operations detail')}
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
  const { t } = useLocale();
  const totals = value.totals && typeof value.totals === 'object' ? value.totals : {};
  return (
    <div>
      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{t('admin.ai_advisor.usage', {}, 'Usage')}</p>
      <div className="mt-2 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/35">
        <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          <MiniMetric label={t('admin.ai_advisor.events', {}, 'Events')} value={String(value.event_count ?? '-')} />
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
  const { t } = useLocale();
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/35">
      <span className="text-sm text-slate-700 dark:text-slate-200">{label}</span>
      <BackofficeStatusBadge label={ok ? t('admin.ai_advisor.safety_passed', {}, 'Passed') : t('admin.ai_advisor.safety_blocked', {}, 'Blocked')} status={ok ? 'success' : 'error'} />
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
