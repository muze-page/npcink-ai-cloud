'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { generateIdempotencyKey } from '@/lib/idempotency';
import { formatDate } from '@/lib/utils';

type ResourceStatus = 'ready' | 'missing_secret' | 'missing_provider' | 'disabled' | string;
type AIResourceView = 'connections' | 'ability_models' | 'usage' | 'health' | 'matrix' | 'diagnostics';
type ConnectionStatusFilter = 'all' | 'ready' | 'missing_secret' | 'disabled';
type SupplierCategory = 'ai' | 'capability';
type SupplierSettingsTab = 'model' | 'capability';
type CapabilityProviderCategory = 'search' | 'image' | 'vector';
type CapabilityProviderCategoryFilter = 'all' | CapabilityProviderCategory;
type DiagnosticsTab = 'matrix' | 'usage' | 'health';

type Connection = {
  connection_id: string;
  provider_id: string;
  display_name: string;
  kind: string;
  enabled: boolean;
  configured: boolean;
  status: ResourceStatus;
  base_url: string;
  note: string;
  priority: number;
  capability_ids: string[];
  runtime_profile_ids: string[];
  model_ids?: string[];
  last_tested_at?: string;
  last_error_code?: string;
  last_error_message?: string;
  detail_href?: string;
  managed_by?: string;
  metadata?: Record<string, any>;
};

type Capability = {
  capability_id: string;
  label: string;
  status: ResourceStatus;
  default_profile_id: string;
  connection_ids: string[];
  used_by: string[];
  write_posture: string;
};

type RuntimeProfile = {
  profile_id: string;
  kind: string;
  capability_id: string;
  selected_connection_id: string;
  selected_provider_id: string;
  selected_model_id: string;
  status: ResourceStatus;
  selection_owner: string;
  used_by: string[];
  selected_for?: string[];
  last_run?: RuntimeEvidence | PipelineRuntimeEvidence;
};

type CapabilityMatrixRow = {
  capability_id: string;
  label: string;
  status: ResourceStatus;
  used_by: string[];
  write_posture: string;
  default_profile_id: string;
  connection_ids: string[];
  profiles: RuntimeProfile[];
  selection_owner: string;
  direct_wordpress_write: boolean;
};

type RuntimeResolutionRow = {
  capability_id: string;
  label: string;
  status: ResourceStatus;
  selected_profile_id: string;
  selected_provider_id: string;
  selected_model_id: string;
  selected_connection_ids: string[];
  ready_connection_ids: string[];
  runtime_provider_available: boolean;
  runtime_provider_ids: string[];
  write_posture: string;
  selection_owner: string;
  direct_wordpress_write: boolean;
};

type ProviderConnectionTestResult = {
  connection_id: string;
  provider_id: string;
  kind: string;
  status: ResourceStatus;
  stage: string;
  ok: boolean;
  error_code: string;
  message: string;
  tested_at: string;
  catalog?: {
    provider_id?: string;
    display_name?: string;
    adapter_type?: string;
    model_count?: number;
    sample_model_ids?: string[];
  };
  probe?: {
    provider_id?: string;
    result_count?: number;
    latency_ms?: number;
    write_posture?: string;
    direct_wordpress_write?: boolean;
  };
};

type ProviderCatalogPreview = {
  provider_id: string;
  display_name: string;
  adapter_type: string;
  model_count: number;
  model_ids: string[];
  models?: ProviderCatalogPreviewModel[];
  truncated: boolean;
};

type ProviderCatalogPreviewModel = {
  model_id: string;
  family: string;
  feature: string;
  status: string;
  is_deprecated: boolean;
  runtime_supported: boolean;
  verified: boolean;
  capability_tags: string[];
};

type ModelReferenceEntry = {
  source_id: string;
  source_label: string;
  provider_id: string;
  provider_label: string;
  model_id: string;
  display_name: string;
  family: string;
  feature: string;
  status: string;
  modalities: {
    input?: string[];
    output?: string[];
  };
  capability_flags: {
    reasoning?: boolean;
    tool_call?: boolean;
    structured_output?: boolean;
    attachment?: boolean;
    open_weights?: boolean;
  };
  context_window?: number | null;
  output_limit?: number | null;
  price: {
    input?: number | null;
    output?: number | null;
    cache_read?: number | null;
    cache_write?: number | null;
    unit: string;
    billing_truth: boolean;
  };
  source_updated_at: string;
  synced_at: string;
  is_deprecated: boolean;
  override_present: boolean;
};

type ModelReferenceSourceSummary = {
  source_id: string;
  display_name: string;
  source_url: string;
  status: string;
  last_synced_at: string;
  last_error_code: string;
  last_error_message: string;
};

type ModelReferenceFeatureFilter = 'all' | 'text' | 'image' | 'audio' | 'video' | 'embedding';
type ModelReferenceVisibilityFilter = 'all' | 'enabled' | 'disabled';

function modelReferenceSourceNeedsSync(source: ModelReferenceSourceSummary | null, total: number): boolean {
  if (total > 0) return false;
  if (!source) return true;
  if (source.last_synced_at) return false;
  return source.status !== 'active';
}

type ModelVisibilityRow = {
  modelId: string;
  family: string;
  feature: string;
  sourceLabel: string;
  sourceKind: 'reference' | 'catalog' | 'manual';
  selected: boolean;
  verified: boolean;
  deprecated: boolean;
  reference?: ModelReferenceEntry;
  catalog?: ProviderCatalogPreviewModel;
};

type RuntimeInstance = {
  instance_id: string;
  provider_id: string;
  model_id: string;
  endpoint_variant: string;
  region: string;
  health_status: string;
  weight: number;
  capability_tags: string[];
  model_status: string;
  model_feature: string;
};

type RoutingProfile = {
  profile_id: string;
  groupId: string;
  label: string;
  description: string;
  execution_kind: string;
  tasks: string[];
  candidate_instance_ids: string[];
  timeout_ms: number;
  max_timeout_ms: number;
  allow_fallback: boolean;
  max_retries: number;
  revision: string;
  updated_at: string;
  status: string;
};

type RoutingData = {
  surface: string;
  owner: string;
  local_control_plane: string;
  customer_model_selection: boolean;
  direct_wordpress_write: boolean;
  prompt_or_preset_editor: boolean;
  available_text_instances: RuntimeInstance[];
  available_image_instances: RuntimeInstance[];
  profiles: RoutingProfile[];
  boundary: {
    public_runtime_accepts_raw_model_instance: boolean;
    results_write_posture: string;
    admin_surface: string;
  };
  receipt?: {
    audit_event_id?: number;
    effective_summary?: string;
  };
};

type EditableRoutingProfile = RoutingProfile & {
  note: string;
};

type FeatureModelUsageRow = {
  feature_id: string;
  label: string;
  surface: string;
  capability_id: string;
  profile_id: string;
  status: ResourceStatus;
  provider_id: string;
  model_id: string;
  connection_ids: string[];
  connection_sources: string[];
  write_posture: string;
  selection_owner: string;
  last_run?: RuntimeEvidence;
  last_provider_call?: {
    provider_id?: string;
    model_id?: string;
    instance_id?: string;
    latency_ms?: number;
    tokens_in?: number;
    tokens_out?: number;
    cost?: number;
    retry_count?: number;
    fallback_used?: boolean;
    error_code?: string;
    created_at?: string;
  };
  evidence?: {
    run_metadata_only?: boolean;
    content_exposed?: boolean;
    source?: string;
  };
};

type ProviderModelHealthRow = {
  provider_id: string;
  model_id: string;
  status: ResourceStatus;
  call_count: number;
  success_count: number;
  error_count: number;
  success_rate: number;
  avg_latency_ms?: number;
  p95_latency_ms?: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  retry_count: number;
  fallback_count: number;
  last_error_code: string;
  last_observed_at: string;
  evidence?: {
    source?: string;
    content_exposed?: boolean;
    recent_call_limit?: number;
  };
};

type ProviderModelHealthAlert = {
  code: string;
  severity: ResourceStatus;
  provider_id: string;
  model_id: string;
  message: string;
  evidence?: {
    status?: string;
    call_count?: number;
    success_rate?: number;
    p95_latency_ms?: number;
    cost?: number;
    fallback_count?: number;
    content_exposed?: boolean;
  };
};

type ProviderModelHealthAlertSummary = {
  window_id: string;
  alert_count: number;
  severity_counts: {
    error?: number;
    warning?: number;
    info?: number;
  };
  thresholds: {
    minimum_success_rate?: number;
    p95_latency_ms?: number;
    cost?: number;
  };
  alerts: ProviderModelHealthAlert[];
};

type ProviderModelHealthWindow = {
  window_id: string;
  label: string;
  hours: number;
  started_at: string;
  ended_at: string;
  rows: ProviderModelHealthRow[];
  alert_summary?: ProviderModelHealthAlertSummary;
};

type ProviderModelHealth = {
  source: string;
  content_exposed: boolean;
  recent_call_limit: number;
  default_window_id?: string;
  rows: ProviderModelHealthRow[];
  windows?: ProviderModelHealthWindow[];
  alert_summary?: ProviderModelHealthAlertSummary;
};

type RuntimeTelemetryAlert = {
  code: string;
  severity: string;
  title: string;
  summary: string;
  count: number;
  capabilities: string[];
  suggestedAction: string;
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
  boundary: {
    directWordpressWrite: boolean;
    containsPromptOrResultPayloads: boolean;
  };
  alertSummary: {
    status: string;
    summary: string;
    nextAction: string;
    alertCount: number;
    alerts: RuntimeTelemetryAlert[];
  };
};

type RuntimeEvidence = {
  run_id?: string;
  site_id?: string;
  status?: string;
  profile_id?: string;
  provider_id?: string;
  model_id?: string;
  instance_id?: string;
  trace_id?: string;
  error_code?: string;
  started_at?: string;
  finished_at?: string;
};

type PipelineRuntimeEvidence = {
  text?: RuntimeEvidence;
  audio?: RuntimeEvidence;
  status?: string;
};

type AiResources = {
  surface: string;
  connections: Connection[];
  capabilities: Capability[];
  capability_matrix?: CapabilityMatrixRow[];
  runtime_resolution?: RuntimeResolutionRow[];
  feature_model_usage?: FeatureModelUsageRow[];
  provider_model_health?: ProviderModelHealth;
  runtime_profiles: RuntimeProfile[];
  recent_runtime_evidence?: {
    source: string;
    content_exposed: boolean;
    profiles: Record<string, RuntimeEvidence>;
  };
  boundary: {
    direct_wordpress_write: boolean;
    final_writes: string;
    secret_exposure: string;
    not_a_control_plane: boolean;
  };
};

type ProviderConnectionForm = {
  providerPreset: string;
  connectionId: string;
  providerId: string;
  displayName: string;
  kind: string;
  baseUrl: string;
  note: string;
  priority: string;
  sourceRole: string;
  capabilityIds: string;
  runtimeProfileIds: string;
  modelIds: string;
  credential: string;
  enabled: boolean;
};

const EMPTY_PROVIDER_CONNECTION_FORM: ProviderConnectionForm = {
  providerPreset: 'openai_compatible',
  connectionId: '',
  providerId: 'openai',
  displayName: 'OpenAI Compatible',
  kind: 'openai_compatible',
  baseUrl: 'https://api.openai.com/v1',
  note: '',
  priority: '100',
  sourceRole: 'execution_source',
  capabilityIds: 'text_generation, image_generation',
  runtimeProfileIds: 'text.ai, text.free-gpt55, grok-imagine-image-quality',
  modelIds: '',
  credential: '',
  enabled: true,
};

type ProviderPreset = {
  id: string;
  label: string;
  providerId: string;
  kind: string;
  displayName: string;
  baseUrl: string;
  capabilityIds: string;
  runtimeProfileIds: string;
  modelIds: string;
};

type CapabilityProviderTemplate = {
  id: string;
  label: string;
  category: CapabilityProviderCategory;
  kind: string;
  baseUrl: string;
  capabilityIds: string;
  runtimeProfileIds: string;
  modelIds: string;
  descriptionKey: string;
  descriptionFallback: string;
};

const QUIET_STATUS_BADGE_CLASS =
  'bg-slate-50 px-2 py-0.5 text-xs normal-case tracking-normal text-slate-600 dark:bg-slate-900 dark:text-slate-300';

const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'openai_compatible',
    label: 'OpenAI Compatible',
    providerId: 'openai',
    kind: 'openai_compatible',
    displayName: 'OpenAI Compatible',
    baseUrl: 'https://api.openai.com/v1',
    capabilityIds: 'text_generation, image_generation',
    runtimeProfileIds: 'text.ai, text.free-gpt55, grok-imagine-image-quality',
    modelIds: '',
  },
  {
    id: 'newapi',
    label: 'New API / One API',
    providerId: 'newapi',
    kind: 'openai_compatible',
    displayName: 'New API channel',
    baseUrl: 'https://api.example.com/v1',
    capabilityIds: 'text_generation, image_generation',
    runtimeProfileIds: 'text.ai, text.free-gpt55, grok-imagine-image-quality',
    modelIds: '',
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    providerId: 'deepseek',
    kind: 'openai_compatible',
    displayName: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/v1',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'deepseek-chat, deepseek-reasoner',
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    providerId: 'anthropic',
    kind: 'anthropic',
    displayName: 'Anthropic',
    baseUrl: 'https://api.anthropic.com',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'claude-3-5-sonnet-latest',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    providerId: 'openrouter',
    kind: 'openrouter',
    displayName: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: '',
  },
  {
    id: 'siliconflow',
    label: 'SiliconFlow',
    providerId: 'siliconflow',
    kind: 'siliconflow',
    displayName: 'SiliconFlow',
    baseUrl: 'https://api.siliconflow.cn/v1',
    capabilityIds: 'text_generation, embedding',
    runtimeProfileIds: 'text.ai, embed.default',
    modelIds: '',
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    providerId: 'minimax',
    kind: 'minimax',
    displayName: 'MiniMax',
    baseUrl: '',
    capabilityIds: 'text_generation, image_generation, audio_generation, video_generation',
    runtimeProfileIds: '',
    modelIds: '',
  },
  {
    id: 'custom',
    label: 'Custom',
    providerId: 'custom',
    kind: 'openai_compatible',
    displayName: 'Custom provider',
    baseUrl: '',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: '',
  },
];

const CAPABILITY_PROVIDER_TEMPLATES: CapabilityProviderTemplate[] = [
  {
    id: 'tavily',
    label: 'Tavily',
    category: 'search',
    kind: 'web_search_provider',
    baseUrl: 'https://api.tavily.com',
    capabilityIds: 'web_search',
    runtimeProfileIds: 'web-search.managed',
    modelIds: '',
    descriptionKey: 'web_search_help_tavily',
    descriptionFallback: 'General web search provider. Used directly or as the first auto fallback source.',
  },
  {
    id: 'bocha',
    label: 'Bocha',
    category: 'search',
    kind: 'web_search_provider',
    baseUrl: 'https://api.bochaai.com/v1',
    capabilityIds: 'web_search',
    runtimeProfileIds: 'web-search.managed',
    modelIds: '',
    descriptionKey: 'web_search_help_bocha',
    descriptionFallback: 'Search provider useful for Chinese and broader public source lookup.',
  },
  {
    id: 'jina_reader',
    label: 'Jina Reader',
    category: 'search',
    kind: 'web_search_provider',
    baseUrl: 'https://r.jina.ai',
    capabilityIds: 'web_search',
    runtimeProfileIds: 'web-search.reader',
    modelIds: '',
    descriptionKey: 'web_search_help_jina_reader',
    descriptionFallback: 'Reader enhancement for selected result URLs. It enriches search results but is not the primary search provider.',
  },
  {
    id: 'apify',
    label: 'Apify',
    category: 'search',
    kind: 'web_search_provider',
    baseUrl: 'https://api.apify.com/v2',
    capabilityIds: 'web_search',
    runtimeProfileIds: 'web-search.managed',
    modelIds: '',
    descriptionKey: 'web_search_help_apify',
    descriptionFallback: 'Apify actor-backed search. Configure an actor that returns dataset items with title, URL, and snippet-like fields.',
  },
  {
    id: 'zhihu',
    label: 'Zhihu Search',
    category: 'search',
    kind: 'web_search_provider',
    baseUrl: 'https://developer.zhihu.com',
    capabilityIds: 'web_search',
    runtimeProfileIds: 'web-search.managed',
    modelIds: '',
    descriptionKey: 'web_search_help_zhihu',
    descriptionFallback: 'Zhihu Open Platform search, hot list, global search, and direct-answer evidence lanes.',
  },
  {
    id: 'unsplash',
    label: 'Unsplash',
    category: 'image',
    kind: 'image_source_provider',
    baseUrl: 'https://api.unsplash.com',
    capabilityIds: 'image_source',
    runtimeProfileIds: 'image-source.managed',
    modelIds: '',
    descriptionKey: 'image_source_help_unsplash',
    descriptionFallback: 'Stock image reference source for editorial and product imagery.',
  },
  {
    id: 'pixabay',
    label: 'Pixabay',
    category: 'image',
    kind: 'image_source_provider',
    baseUrl: 'https://pixabay.com/api/',
    capabilityIds: 'image_source',
    runtimeProfileIds: 'image-source.managed',
    modelIds: '',
    descriptionKey: 'image_source_help_pixabay',
    descriptionFallback: 'Stock image reference source with broad public image coverage.',
  },
  {
    id: 'pexels',
    label: 'Pexels',
    category: 'image',
    kind: 'image_source_provider',
    baseUrl: 'https://api.pexels.com/v1',
    capabilityIds: 'image_source',
    runtimeProfileIds: 'image-source.managed',
    modelIds: '',
    descriptionKey: 'image_source_help_pexels',
    descriptionFallback: 'Stock image reference source for photography and visual references.',
  },
  {
    id: 'jina',
    label: 'Jina Rerank',
    category: 'vector',
    kind: 'rerank_provider',
    baseUrl: 'https://api.jina.ai',
    capabilityIds: 'site_knowledge_rerank',
    runtimeProfileIds: 'site-knowledge.rerank',
    modelIds: 'jina-reranker-v3',
    descriptionKey: 'vector_help_jina_rerank',
    descriptionFallback: 'Rerank provider for Site Knowledge search results.',
  },
  {
    id: 'zilliz',
    label: 'Zilliz',
    category: 'vector',
    kind: 'vector_store_provider',
    baseUrl: '',
    capabilityIds: 'vector_store',
    runtimeProfileIds: 'site-knowledge.vector-store',
    modelIds: '',
    descriptionKey: 'vector_help_zilliz',
    descriptionFallback: 'Vector database provider for Site Knowledge storage and search.',
  },
];

const LEGACY_HEALTH_WINDOW_FALLBACKS = [
  { window_id: 'last_24h', label: 'Last 24h', hours: 24 },
  { window_id: 'last_7d', label: 'Last 7d', hours: 168 },
];

const RUNTIME_TELEMETRY_TEXT_KEYS: Record<string, string> = {
  'Hosted model governance has telemetry gaps to review before traffic expands.':
    'runtime_telemetry_text_coverage_gaps',
  'Runtime telemetry has coverage gaps to review before traffic expands.':
    'runtime_telemetry_text_coverage_gaps',
  'Hosted model governance has coverage or provider errors that need review.':
    'runtime_telemetry_text_errors',
  'Runtime telemetry has coverage or provider errors that need review.':
    'runtime_telemetry_text_errors',
  'Hosted model governance is covered in this window.':
    'runtime_telemetry_text_covered',
  'Runtime telemetry is covered in this window.':
    'runtime_telemetry_text_covered',
  'No hosted model runs were observed in this governance window.':
    'runtime_telemetry_text_no_runs',
  'No runtime runs were observed in this telemetry window.':
    'runtime_telemetry_text_no_runs',
  'Hosted model provider call coverage gap':
    'runtime_telemetry_text_provider_call_gap_title',
  'Provider call coverage gap':
    'runtime_telemetry_text_provider_call_gap_title',
  'Hosted model meter coverage gap':
    'runtime_telemetry_text_meter_gap_title',
  'Runtime meter coverage gap':
    'runtime_telemetry_text_meter_gap_title',
  'Hosted model provider errors':
    'runtime_telemetry_text_provider_errors_title',
  'Provider call errors':
    'runtime_telemetry_text_provider_errors_title',
  'Hosted model failed runs':
    'runtime_telemetry_text_failed_runs_title',
  'Runtime runs failed':
    'runtime_telemetry_text_failed_runs_title',
  'Some hosted runs do not have matching provider call telemetry.':
    'runtime_telemetry_text_provider_call_gap_summary',
  'Some runtime runs do not have matching provider call telemetry.':
    'runtime_telemetry_text_provider_call_gap_summary',
  'Some hosted model runs are not represented in usage metering.':
    'runtime_telemetry_text_meter_gap_summary',
  'Some runtime runs are not represented in usage metering.':
    'runtime_telemetry_text_meter_gap_summary',
  'Provider calls are returning errors in the current governance window.':
    'runtime_telemetry_text_provider_errors_summary',
  'Provider calls are returning errors in the current telemetry window.':
    'runtime_telemetry_text_provider_errors_summary',
  'Hosted model runs are failing before or during provider execution.':
    'runtime_telemetry_text_failed_runs_summary',
  'Runtime runs are failing before or during provider execution.':
    'runtime_telemetry_text_failed_runs_summary',
  'Review hosted model families before promoting new providers.':
    'runtime_telemetry_text_review_guidance',
  'Inspect capabilities below full metering coverage before enabling new runtime providers at higher traffic.':
    'runtime_telemetry_text_review_guidance',
  continue_monitoring: 'runtime_telemetry_action_continue_monitoring',
  inspect_provider_call_recording_for_hosted_profiles:
    'runtime_telemetry_action_inspect_provider_calls',
  inspect_metering_callback_or_usage_event_mapping:
    'runtime_telemetry_action_inspect_metering',
  inspect_provider_credentials_quota_and_health:
    'runtime_telemetry_action_inspect_provider_health',
  inspect_runtime_failure_detail:
    'runtime_telemetry_action_inspect_runtime_failure',
  inspect_runtime_failure_detail_for_hosted_models:
    'runtime_telemetry_action_inspect_runtime_failure',
  inspect_runtime_telemetry: 'runtime_telemetry_action_inspect_runtime',
  inspect_hosted_models: 'runtime_telemetry_action_inspect_runtime',
};

function statusTone(status: ResourceStatus): 'success' | 'warning' | 'disabled' | 'info' {
  if (status === 'ready') return 'success';
  if (status === 'disabled') return 'disabled';
  if (status === 'missing_secret' || status === 'missing_provider') return 'warning';
  return 'info';
}

function healthTone(status: ResourceStatus): 'success' | 'warning' | 'disabled' | 'info' | 'error' {
  if (status === 'healthy') return 'success';
  if (status === 'degraded') return 'warning';
  if (status === 'error') return 'error';
  if (status === 'not_observed') return 'disabled';
  return 'info';
}

function severityTone(status: ResourceStatus): 'success' | 'warning' | 'disabled' | 'info' | 'error' {
  if (status === 'error') return 'error';
  if (status === 'warning') return 'warning';
  if (status === 'info') return 'info';
  return 'disabled';
}

function labelList(values: string[]): string {
  return values.length ? values.join(', ') : '-';
}

function connectionHost(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '-';
  try {
    return new URL(trimmed).host || trimmed;
  } catch {
    return trimmed.replace(/^https?:\/\//, '').split('/')[0] || trimmed;
  }
}

function supplierCategory(connection: Connection): SupplierCategory {
  if (
    connection.kind === 'web_search_provider' ||
    connection.kind === 'image_source_provider' ||
    connection.kind === 'rerank_provider' ||
    connection.kind === 'vector_store_provider' ||
    connection.capability_ids.includes('web_search') ||
    connection.capability_ids.includes('image_source') ||
    connection.capability_ids.includes('site_knowledge_rerank') ||
    connection.capability_ids.includes('vector_store')
  ) {
    return 'capability';
  }
  return 'ai';
}

function capabilityProviderCategory(connection: Connection): CapabilityProviderCategory {
  if (connection.kind === 'web_search_provider' || connection.capability_ids.includes('web_search')) return 'search';
  if (connection.kind === 'image_source_provider' || connection.capability_ids.includes('image_source')) return 'image';
  return 'vector';
}

function isCapabilityProviderDescriptor(kind: string, capabilityIds: string[]): boolean {
  return (
    kind === 'web_search_provider' ||
    kind === 'image_source_provider' ||
    kind === 'rerank_provider' ||
    kind === 'vector_store_provider' ||
    capabilityIds.includes('web_search') ||
    capabilityIds.includes('image_source') ||
    capabilityIds.includes('site_knowledge_rerank') ||
    capabilityIds.includes('vector_store')
  );
}

function capabilityProviderDescriptorCategory(kind: string, capabilityIds: string[]): CapabilityProviderCategory {
  if (kind === 'web_search_provider' || capabilityIds.includes('web_search')) return 'search';
  if (kind === 'image_source_provider' || capabilityIds.includes('image_source')) return 'image';
  return 'vector';
}

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function uniqueList(values: string[]): string[] {
  const normalized: string[] = [];
  for (const value of values) {
    const item = value.trim();
    if (item && !normalized.includes(item)) {
      normalized.push(item);
    }
  }
  return normalized;
}

function joinList(values: string[]): string {
  return uniqueList(values).join(', ');
}

function normalizeRoutingData(raw: any): RoutingData {
  const data = raw ?? {};
  const routingGroupKey = ['group', 'id'].join('_');
  const normalizeInstance = (item: any): RuntimeInstance => ({
    instance_id: String(item?.instance_id ?? ''),
    provider_id: String(item?.provider_id ?? ''),
    model_id: String(item?.model_id ?? ''),
    endpoint_variant: String(item?.endpoint_variant ?? ''),
    region: String(item?.region ?? ''),
    health_status: String(item?.health_status ?? ''),
    weight: Number(item?.weight ?? 0) || 0,
    capability_tags: Array.isArray(item?.capability_tags) ? item.capability_tags.map(String) : [],
    model_status: String(item?.model_status ?? ''),
    model_feature: String(item?.model_feature ?? ''),
  });
  return {
    surface: String(data.surface ?? ''),
    owner: String(data.owner ?? ''),
    local_control_plane: String(data.local_control_plane ?? ''),
    customer_model_selection: Boolean(data.customer_model_selection),
    direct_wordpress_write: Boolean(data.direct_wordpress_write),
    prompt_or_preset_editor: Boolean(data.prompt_or_preset_editor),
    available_text_instances: Array.isArray(data.available_text_instances)
      ? data.available_text_instances.map(normalizeInstance)
      : [],
    available_image_instances: Array.isArray(data.available_image_instances)
      ? data.available_image_instances.map(normalizeInstance)
      : [],
    profiles: Array.isArray(data.profiles)
      ? data.profiles.map((profile: any) => ({
          profile_id: String(profile?.profile_id ?? ''),
          groupId: String(profile?.[routingGroupKey] ?? ''),
          label: String(profile?.label ?? ''),
          description: String(profile?.description ?? ''),
          execution_kind: String(profile?.execution_kind ?? 'text'),
          tasks: Array.isArray(profile?.tasks) ? profile.tasks.map(String) : [],
          candidate_instance_ids: Array.isArray(profile?.candidate_instance_ids)
            ? profile.candidate_instance_ids.map(String)
            : [],
          timeout_ms: Number(profile?.timeout_ms ?? 30000) || 30000,
          max_timeout_ms: Number(profile?.max_timeout_ms ?? 60000) || 60000,
          allow_fallback: Boolean(profile?.allow_fallback),
          max_retries: Number(profile?.max_retries ?? 0) || 0,
          revision: String(profile?.revision ?? ''),
          updated_at: String(profile?.updated_at ?? ''),
          status: String(profile?.status ?? 'unknown'),
        }))
      : [],
    boundary: {
      public_runtime_accepts_raw_model_instance: Boolean(
        data.boundary?.public_runtime_accepts_raw_model_instance
      ),
      results_write_posture: String(data.boundary?.results_write_posture ?? ''),
      admin_surface: String(data.boundary?.admin_surface ?? ''),
    },
    receipt: data.receipt,
  };
}

function slugifyProviderValue(value: string): string {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return slug || 'provider';
}

function providerPresetById(presetId: string): ProviderPreset {
  return PROVIDER_PRESETS.find((preset) => preset.id === presetId) || PROVIDER_PRESETS[0];
}

function inferProviderPreset(connection: Connection): string {
  const kind = connection.kind.toLowerCase();
  const providerId = connection.provider_id.toLowerCase();
  if (providerId.includes('newapi') || connection.base_url.toLowerCase().includes('newapi')) return 'newapi';
  if (providerId.includes('deepseek') || connection.base_url.toLowerCase().includes('deepseek')) return 'deepseek';
  if (kind === 'anthropic') return 'anthropic';
  if (kind === 'openrouter') return 'openrouter';
  if (kind === 'siliconflow') return 'siliconflow';
  if (kind === 'minimax' || kind === 'audio_provider' || kind === 'minimax_audio') return 'minimax';
  if (kind === 'openai_compatible') return 'openai_compatible';
  return 'custom';
}

function isRuntimeEvidence(value: RuntimeEvidence | PipelineRuntimeEvidence | undefined): value is RuntimeEvidence {
  return Boolean(value && 'run_id' in value);
}

function evidenceSummary(profile: RuntimeProfile): RuntimeEvidence | null {
  const lastRun = profile.last_run;
  if (!lastRun) return null;
  if (isRuntimeEvidence(lastRun)) {
    return lastRun.run_id ? lastRun : null;
  }
  return lastRun.audio?.run_id ? lastRun.audio : lastRun.text?.run_id ? lastRun.text : null;
}

function profileModelSummary(profiles: RuntimeProfile[]): string {
  const pairs = profiles
    .map((profile) => `${profile.selected_provider_id || '-'} / ${profile.selected_model_id || '-'}`)
    .filter((value, index, values) => values.indexOf(value) === index);
  return pairs.length ? pairs.join(', ') : '-';
}

function profileIds(profiles: RuntimeProfile[]): string {
  return profiles.map((profile) => profile.profile_id).join(', ') || '-';
}

function formatCost(value: number | undefined): string {
  if (typeof value !== 'number') return '-';
  if (value === 0) return '0';
  return value < 0.0001 ? '<0.0001' : value.toFixed(4);
}

function formatRate(value: number | undefined): string {
  if (typeof value !== 'number') return '-';
  return `${Math.round(value * 100)}%`;
}

function formatPreciseRate(value: number | undefined): string {
  if (typeof value !== 'number') return '-';
  return `${(value * 100).toFixed(1)}%`;
}

function formatInteger(value: number | undefined): string {
  return new Intl.NumberFormat().format(Number(value ?? 0));
}

function asNumber(value: unknown): number {
  return Number(value ?? 0) || 0;
}

function normalizeRuntimeTelemetry(raw: any): RuntimeTelemetrySummary {
  const totals = raw?.totals ?? {};
  const gaps = raw?.governance_gaps ?? {};
  const boundary = raw?.boundary ?? {};
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

function normalizeAiResources(raw: any): AiResources {
  const value = raw && typeof raw === 'object' ? raw : {};
  const boundary = value.boundary && typeof value.boundary === 'object' ? value.boundary : {};
  return {
    surface: String(value.surface ?? 'admin_ai_resources'),
    connections: Array.isArray(value.connections) ? value.connections : [],
    capabilities: Array.isArray(value.capabilities) ? value.capabilities : [],
    capability_matrix: Array.isArray(value.capability_matrix) ? value.capability_matrix : [],
    runtime_resolution: Array.isArray(value.runtime_resolution) ? value.runtime_resolution : [],
    feature_model_usage: Array.isArray(value.feature_model_usage) ? value.feature_model_usage : [],
    provider_model_health:
      value.provider_model_health && typeof value.provider_model_health === 'object'
        ? value.provider_model_health
        : undefined,
    runtime_profiles: Array.isArray(value.runtime_profiles) ? value.runtime_profiles : [],
    recent_runtime_evidence:
      value.recent_runtime_evidence && typeof value.recent_runtime_evidence === 'object'
        ? value.recent_runtime_evidence
        : undefined,
    boundary: {
      direct_wordpress_write: Boolean(boundary.direct_wordpress_write),
      final_writes: String(boundary.final_writes ?? 'excluded'),
      secret_exposure: String(boundary.secret_exposure ?? 'masked'),
      not_a_control_plane: Boolean(boundary.not_a_control_plane),
    },
  };
}

function formatCompactTokenCount(value: number | null): string {
  if (typeof value !== 'number') return '-';
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

function formatRawTokenCount(value: number | null): string {
  if (typeof value !== 'number') return '-';
  return new Intl.NumberFormat('en-US').format(value);
}

function formatReferenceContext(reference: ModelReferenceEntry, missingLabel: string): string {
  const contextWindow = typeof reference.context_window === 'number' ? reference.context_window : null;
  const outputLimit = typeof reference.output_limit === 'number' ? reference.output_limit : null;
  if (contextWindow === null && outputLimit === null) {
    return missingLabel;
  }
  return `${formatCompactTokenCount(contextWindow)} / ${formatCompactTokenCount(outputLimit)}`;
}

function formatReferenceContextTitle(reference: ModelReferenceEntry): string {
  const contextWindow = typeof reference.context_window === 'number' ? reference.context_window : null;
  const outputLimit = typeof reference.output_limit === 'number' ? reference.output_limit : null;
  return `${formatRawTokenCount(contextWindow)} / ${formatRawTokenCount(outputLimit)} tokens`;
}

function hasReferencePrice(reference: ModelReferenceEntry): boolean {
  return typeof reference.price.input === 'number'
    || typeof reference.price.output === 'number'
    || typeof reference.price.cache_read === 'number'
    || typeof reference.price.cache_write === 'number';
}

function formatReferencePrice(reference: ModelReferenceEntry, cacheLabel: string, missingLabel: string): string {
  if (!hasReferencePrice(reference)) {
    return missingLabel;
  }
  const input = typeof reference.price.input === 'number' ? `$${reference.price.input}` : '-';
  const output = typeof reference.price.output === 'number' ? `$${reference.price.output}` : '-';
  const cacheRead = typeof reference.price.cache_read === 'number' ? `$${reference.price.cache_read}` : '';
  const cacheWrite = typeof reference.price.cache_write === 'number' ? `$${reference.price.cache_write}` : '';
  const cache = cacheRead || cacheWrite ? ` · ${cacheLabel} ${cacheRead || '-'} / ${cacheWrite || '-'}` : '';
  return `${input} / ${output}${cache}`;
}

function modelReferenceCapabilityTags(reference: ModelReferenceEntry): string[] {
  return [
    reference.capability_flags.reasoning ? 'reasoning' : '',
    reference.capability_flags.tool_call ? 'tool_call' : '',
    reference.capability_flags.structured_output ? 'structured_output' : '',
    reference.capability_flags.attachment ? 'attachment' : '',
    reference.capability_flags.open_weights ? 'open_weights' : '',
  ].filter(Boolean);
}

function modelReferenceSearchText(row: ModelVisibilityRow): string {
  return [
    row.modelId,
    row.family,
    row.feature,
    row.sourceLabel,
    row.reference?.display_name,
    row.reference?.provider_label,
  ].filter(Boolean).join(' ').toLowerCase();
}

function defaultReferenceProviderId(providerId: string, presetId: string): string {
  const normalizedProviderId = providerId.trim().toLowerCase();
  if (normalizedProviderId && normalizedProviderId !== 'custom') return normalizedProviderId;
  const presetProviderId = providerPresetById(presetId).providerId.trim().toLowerCase();
  return presetProviderId === 'custom' ? 'openai' : presetProviderId;
}

function canChooseReferenceProvider(presetId: string): boolean {
  return ['openai_compatible', 'newapi', 'openrouter', 'custom'].includes(presetId);
}

function referenceProviderLabel(providerId: string): string {
  const normalizedProviderId = providerId.trim().toLowerCase();
  const preset = PROVIDER_PRESETS.find((item) => item.providerId === normalizedProviderId);
  return preset?.label || normalizedProviderId || 'OpenAI';
}

function modelProviderPrefix(modelId: string): string {
  const normalizedModelId = modelId.trim().toLowerCase();
  const slashIndex = normalizedModelId.indexOf('/');
  if (slashIndex <= 0) return '';
  return normalizedModelId.slice(0, slashIndex);
}

function inferReferenceProviderFromModelIds(modelIds: string[], fallbackProviderId: string): string {
  const normalizedFallback = fallbackProviderId.trim().toLowerCase();
  const prefixes = uniqueList(modelIds.map(modelProviderPrefix).filter(Boolean));
  if (prefixes.length === 1) {
    return prefixes[0];
  }
  return normalizedFallback || 'openai';
}

function referenceProviderForConnection(connection: Connection): string {
  const presetId = inferProviderPreset(connection);
  const fallbackProviderId = defaultReferenceProviderId(connection.provider_id, presetId);
  if (!canChooseReferenceProvider(presetId)) {
    return fallbackProviderId;
  }
  return inferReferenceProviderFromModelIds(connection.model_ids || [], fallbackProviderId);
}

function normalizeModelReferenceFeature(feature: string): ModelReferenceFeatureFilter {
  const normalized = feature.trim().toLowerCase();
  if (normalized.includes('image')) return 'image';
  if (normalized.includes('audio')) return 'audio';
  if (normalized.includes('video')) return 'video';
  if (normalized.includes('embedding') || normalized.includes('vector')) return 'embedding';
  if (normalized.includes('text')) return 'text';
  return 'all';
}

function normalizeModelLookupValue(value: string): string {
  return value.trim().toLowerCase();
}

function modelLookupKeys(modelId: string, providerId: string): string[] {
  const normalizedModelId = normalizeModelLookupValue(modelId);
  const normalizedProviderId = normalizeModelLookupValue(providerId);
  const keys = new Set<string>();
  if (normalizedModelId) {
    keys.add(normalizedModelId);
    const slashIndex = normalizedModelId.indexOf('/');
    if (slashIndex > 0 && slashIndex < normalizedModelId.length - 1) {
      keys.add(normalizedModelId.slice(slashIndex + 1));
    }
    if (normalizedProviderId && normalizedModelId.startsWith(`${normalizedProviderId}/`)) {
      keys.add(normalizedModelId.slice(normalizedProviderId.length + 1));
    }
    if (normalizedProviderId && !normalizedModelId.includes('/')) {
      keys.add(`${normalizedProviderId}/${normalizedModelId}`);
    }
  }
  return Array.from(keys);
}

function modelLookupKeySet(modelId: string, providerId: string): Set<string> {
  return new Set(modelLookupKeys(modelId, providerId));
}

function selectedModelIdFor(
  modelId: string,
  providerId: string,
  selectedModelIds: string[],
  selectedLookup: Map<string, string>
): string {
  for (const key of modelLookupKeys(modelId, providerId)) {
    const selectedModelId = selectedLookup.get(key);
    if (selectedModelId) return selectedModelId;
  }
  return selectedModelIds.includes(modelId) ? modelId : '';
}

function hasModelMetadataFor(
  modelId: string,
  providerId: string,
  references: ModelReferenceEntry[],
  catalogModels: ProviderCatalogPreviewModel[]
): boolean {
  const keys = modelLookupKeySet(modelId, providerId);
  return references.some((reference) => modelLookupKeys(reference.model_id, reference.provider_id || providerId).some((key) => keys.has(key)))
    || catalogModels.some((model) => modelLookupKeys(model.model_id, providerId).some((key) => keys.has(key)));
}

function normalizeProviderCatalogPreview(value: any): ProviderCatalogPreview | null {
  if (!value || typeof value !== 'object') return null;
  const models: ProviderCatalogPreviewModel[] = Array.isArray(value.models)
    ? value.models
      .map((model: any): ProviderCatalogPreviewModel => ({
        model_id: String(model?.model_id ?? ''),
        family: String(model?.family ?? ''),
        feature: String(model?.feature ?? ''),
        status: String(model?.status ?? ''),
        is_deprecated: Boolean(model?.is_deprecated),
        runtime_supported: Boolean(model?.runtime_supported),
        verified: Boolean(model?.verified),
        capability_tags: Array.isArray(model?.capability_tags) ? model.capability_tags.map(String) : [],
      }))
      .filter((model: ProviderCatalogPreviewModel) => model.model_id)
    : [];
  const modelIds = Array.isArray(value.model_ids)
    ? value.model_ids.map(String).filter(Boolean)
    : models.map((model) => model.model_id);
  if (!modelIds.length && !models.length) return null;
  return {
    provider_id: String(value.provider_id ?? ''),
    display_name: String(value.display_name ?? ''),
    adapter_type: String(value.adapter_type ?? ''),
    model_count: Number(value.model_count ?? modelIds.length) || modelIds.length,
    model_ids: modelIds,
    models,
    truncated: Boolean(value.truncated),
  };
}

function catalogPreviewForMetadata(preview: ProviderCatalogPreview | null): ProviderCatalogPreview | undefined {
  if (!preview) return undefined;
  return {
    provider_id: preview.provider_id,
    display_name: preview.display_name,
    adapter_type: preview.adapter_type,
    model_count: preview.model_count,
    model_ids: preview.model_ids,
    models: (preview.models || []).map((model) => ({
      model_id: model.model_id,
      family: model.family,
      feature: model.feature,
      status: model.status,
      is_deprecated: model.is_deprecated,
      runtime_supported: model.runtime_supported,
      verified: model.verified,
      capability_tags: model.capability_tags,
    })),
    truncated: preview.truncated,
  };
}

function catalogPreviewFromConnection(connection: Connection): ProviderCatalogPreview | null {
  return normalizeProviderCatalogPreview(
    connection.metadata?.model_catalog_preview || connection.metadata?.model_catalog
  );
}

function routingIdempotencyKey(): string {
  return generateIdempotencyKey('ai_resources_routing');
}

function resolveAdminApiPayloadMessage(payload: any, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const message = typeof payload.message === 'string' ? payload.message : '';
    if (message.trim()) {
      return resolveUiErrorMessage(message, fallback);
    }
    const detail = payload.detail;
    if (Array.isArray(detail)) {
      const detailMessage = detail
        .map((item) => {
          if (typeof item === 'string') return item;
          if (item && typeof item === 'object' && typeof item.msg === 'string') return item.msg;
          return '';
        })
        .filter(Boolean)
        .join('; ');
      if (detailMessage) {
        return resolveUiErrorMessage(detailMessage, fallback);
      }
    }
    if (typeof detail === 'string' && detail.trim()) {
      return resolveUiErrorMessage(detail, fallback);
    }
    if (typeof payload.error_code === 'string' && payload.error_code.trim()) {
      return resolveUiErrorMessage(payload.error_code, fallback);
    }
  }
  return resolveUiErrorMessage(payload, fallback);
}

function AiResourcesContent() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const aiText = useCallback(
    (key: string, fallback: string, params?: Record<string, string>) => t(`admin.ai_resources.${key}`, params, fallback),
    [t]
  );
  const [data, setData] = useState<AiResources | null>(null);
  const [routingData, setRoutingData] = useState<RoutingData | null>(null);
  const [routingDrafts, setRoutingDrafts] = useState<EditableRoutingProfile[]>([]);
  const [abilityModelDialogProfileId, setAbilityModelDialogProfileId] = useState('');
  const [abilityModelDialogError, setAbilityModelDialogError] = useState('');
  const [abilityModelDialogMessage, setAbilityModelDialogMessage] = useState('');
  const [activeView, setActiveView] = useState<AIResourceView>('connections');
  const [activeSupplierTab, setActiveSupplierTab] = useState<SupplierSettingsTab>('model');
  const [activeDiagnosticsTab, setActiveDiagnosticsTab] = useState<DiagnosticsTab>('matrix');
  const [activeCapabilityCategory, setActiveCapabilityCategory] = useState<CapabilityProviderCategory>('search');
  const [capabilityCategoryFilter, setCapabilityCategoryFilter] = useState<CapabilityProviderCategoryFilter>('all');
  const [capabilityAddDialogOpen, setCapabilityAddDialogOpen] = useState(false);
  const [activeHealthWindowId, setActiveHealthWindowId] = useState('last_24h');
  const [connectionStatusFilter, setConnectionStatusFilter] = useState<ConnectionStatusFilter>('all');
  const [connectionSearch, setConnectionSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingRouting, setLoadingRouting] = useState(true);
  const [savingRouting, setSavingRouting] = useState(false);
  const [savingConnection, setSavingConnection] = useState(false);
  const [testingConnectionId, setTestingConnectionId] = useState('');
  const [deletingConnectionId, setDeletingConnectionId] = useState('');
  const [fetchingProviderCatalog, setFetchingProviderCatalog] = useState(false);
  const [providerCatalogPreview, setProviderCatalogPreview] = useState<ProviderCatalogPreview | null>(null);
  const [loadingModelReferences, setLoadingModelReferences] = useState(false);
  const [syncingModelReferences, setSyncingModelReferences] = useState(false);
  const [autoSyncingModelReferences, setAutoSyncingModelReferences] = useState(false);
  const [modelReferenceAutoSyncError, setModelReferenceAutoSyncError] = useState('');
  const [modelReferences, setModelReferences] = useState<ModelReferenceEntry[]>([]);
  const [modelReferenceTotal, setModelReferenceTotal] = useState(0);
  const [modelReferenceSources, setModelReferenceSources] = useState<ModelReferenceSourceSummary[]>([]);
  const [loadedModelReferenceProviderId, setLoadedModelReferenceProviderId] = useState('');
  const [modelReferenceProviderId, setModelReferenceProviderId] = useState('openai');
  const [modelReferenceSearch, setModelReferenceSearch] = useState('');
  const [modelReferenceFeatureFilter, setModelReferenceFeatureFilter] = useState<ModelReferenceFeatureFilter>('all');
  const [modelReferenceVisibilityFilter, setModelReferenceVisibilityFilter] = useState<ModelReferenceVisibilityFilter>('all');
  const [modelReferenceShowDeprecated, setModelReferenceShowDeprecated] = useState(true);
  const [connectionTestResults, setConnectionTestResults] = useState<Record<string, ProviderConnectionTestResult>>({});
  const [providerFormOpen, setProviderFormOpen] = useState(false);
  const [providerFormMode, setProviderFormMode] = useState<'create' | 'edit'>('create');
  const [connectionDetailsOpen, setConnectionDetailsOpen] = useState(true);
  const [providerConnectionForm, setProviderConnectionForm] = useState<ProviderConnectionForm>(
    EMPTY_PROVIDER_CONNECTION_FORM
  );
  const [customModelInput, setCustomModelInput] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [runtimeTelemetry, setRuntimeTelemetry] = useState<RuntimeTelemetrySummary | null>(null);
  const [runtimeTelemetryError, setRuntimeTelemetryError] = useState('');
  const autoSyncedReferenceProviders = useRef<Set<string>>(new Set());
  const providerFormCapabilityIds = splitList(providerConnectionForm.capabilityIds);
  const isCapabilityProviderForm = isCapabilityProviderDescriptor(providerConnectionForm.kind, providerFormCapabilityIds);
  const providerFormCapabilityCategory = capabilityProviderDescriptorCategory(
    providerConnectionForm.kind,
    providerFormCapabilityIds
  );
  const knownCapabilityProviderTemplate = CAPABILITY_PROVIDER_TEMPLATES.find(
    (template) => template.id === providerConnectionForm.providerId && template.kind === providerConnectionForm.kind
  );
  const shouldLockCapabilityBaseUrl = isCapabilityProviderForm && Boolean(knownCapabilityProviderTemplate);
  const visibleCapabilityTemplates = CAPABILITY_PROVIDER_TEMPLATES.filter(
    (template) => template.category === activeCapabilityCategory
  );
  const loadResources = useCallback(async (options: { showLoading?: boolean } = {}) => {
    if (options.showLoading !== false) {
      setLoading(true);
    }
    setError('');
    try {
      const response = await fetch('/api/admin/ai-resources', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_load', 'Failed to load provider management.')));
      }
      const normalized = normalizeAiResources(payload.data);
      setData(normalized);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : aiText('error_load', 'Failed to load provider management.'));
    } finally {
      setLoading(false);
    }
  }, [aiText]);

  const loadRuntimeTelemetry = useCallback(async () => {
    setRuntimeTelemetryError('');
    try {
      const params = new URLSearchParams({
        recent_minutes: '1440',
        limit: '25',
      });
      const response = await fetch(`/api/admin/hosted-model-governance?${params.toString()}`, {
        credentials: 'include',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload?.status === 'error') {
        throw new Error(resolveAdminApiPayloadMessage(payload, aiText('runtime_telemetry_error_load', 'Failed to load runtime telemetry.')));
      }
      setRuntimeTelemetry(normalizeRuntimeTelemetry(payload?.data ?? {}));
    } catch (telemetryError) {
      setRuntimeTelemetry(null);
      setRuntimeTelemetryError(
        telemetryError instanceof Error
          ? telemetryError.message
          : aiText('runtime_telemetry_error_load', 'Failed to load runtime telemetry.')
      );
    }
  }, [aiText]);

  const loadRouting = useCallback(async () => {
    setLoadingRouting(true);
    setError('');
    try {
      const response = await fetch('/api/admin/wordpress-ai-routing', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_load_ability_models', 'Failed to load ability-model routing.')));
      }
      const normalized = normalizeRoutingData(payload.data);
      setRoutingData(normalized);
      setRoutingDrafts(normalized.profiles.map((profile) => ({ ...profile, note: '' })));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : aiText('error_load_ability_models', 'Failed to load ability-model routing.'));
    } finally {
      setLoadingRouting(false);
    }
  }, [aiText]);

  const loadModelReferences = useCallback(async (providerId: string) => {
    const normalizedProviderId = providerId.trim().toLowerCase();
    if (!normalizedProviderId || normalizedProviderId === 'custom') {
      setModelReferences([]);
      setModelReferenceTotal(0);
      setModelReferenceSources([]);
      setLoadedModelReferenceProviderId(normalizedProviderId);
      return;
    }
    setLoadingModelReferences(true);
    setLoadedModelReferenceProviderId('');
    try {
      const params = new URLSearchParams({
        provider_id: normalizedProviderId,
        limit: '500',
        include_deprecated: 'true',
      });
      const response = await fetch(`/api/admin/model-references?${params.toString()}`, {
        credentials: 'include',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_load_model_references', 'Failed to load model reference data.')));
      }
      setModelReferences(Array.isArray(payload.data?.items) ? payload.data.items : []);
      setModelReferenceTotal(Number(payload.data?.total ?? 0) || 0);
      setModelReferenceSources(Array.isArray(payload.data?.source_summary) ? payload.data.source_summary : []);
      setLoadedModelReferenceProviderId(normalizedProviderId);
    } catch (referenceError) {
      setModelReferences([]);
      setModelReferenceTotal(0);
      setModelReferenceSources([]);
      setLoadedModelReferenceProviderId('');
      setError(referenceError instanceof Error ? referenceError.message : aiText('error_load_model_references', 'Failed to load model reference data.'));
    } finally {
      setLoadingModelReferences(false);
    }
  }, [aiText]);

  useEffect(() => {
    void loadResources();
  }, [loadResources]);

  useEffect(() => {
    if (activeView === 'diagnostics') {
      void loadRuntimeTelemetry();
    }
  }, [activeView, loadRuntimeTelemetry]);

  useEffect(() => {
    if (!providerFormOpen) return;
    if (isCapabilityProviderForm) {
      setModelReferences([]);
      setProviderCatalogPreview(null);
      return;
    }
    void loadModelReferences(modelReferenceProviderId);
  }, [isCapabilityProviderForm, loadModelReferences, modelReferenceProviderId, providerFormOpen]);

  useEffect(() => {
    const requestedView = searchParams.get('view');
    if (requestedView === 'connections') {
      setActiveView(requestedView);
    }
    if (requestedView === 'overview') {
      setActiveView('diagnostics');
      setActiveDiagnosticsTab('matrix');
    }
    if (requestedView === 'matrix' || requestedView === 'usage' || requestedView === 'health') {
      setActiveView('diagnostics');
      setActiveDiagnosticsTab(requestedView);
    }
    if (requestedView === 'diagnostics') {
      setActiveView('diagnostics');
      const requestedDiagnostic = searchParams.get('diagnostic');
      if (
        requestedDiagnostic === 'matrix' ||
        requestedDiagnostic === 'usage' ||
        requestedDiagnostic === 'health'
      ) {
        setActiveDiagnosticsTab(requestedDiagnostic);
      }
    }
    const requestedSupplier = searchParams.get('supplier');
    if (requestedSupplier === 'capability') {
      setActiveView('connections');
      setActiveSupplierTab('capability');
    }
    if (requestedSupplier === 'model') {
      setActiveView('connections');
      setActiveSupplierTab('model');
    }
    const requestedCategory = searchParams.get('category');
    if (requestedCategory === 'search' || requestedCategory === 'image' || requestedCategory === 'vector') {
      setActiveCapabilityCategory(requestedCategory);
      setCapabilityCategoryFilter(requestedCategory);
    }
  }, [searchParams]);

  async function saveProviderConnection() {
    const normalizedConnectionId = providerConnectionForm.connectionId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.providerId);
    const normalizedProviderId = providerConnectionForm.providerId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.connectionId);
    const modelIds = splitList(providerConnectionForm.modelIds);
    const modelConfig = !isCapabilityProviderForm && modelIds.length ? { model_ids: modelIds, model_id: modelIds[0] } : {};
    setSavingConnection(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/admin/provider-connections', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          connection_id: normalizedConnectionId,
          provider_id: normalizedProviderId,
          provider_type: providerConnectionForm.kind,
          kind: providerConnectionForm.kind,
          display_name: providerConnectionForm.displayName,
          enabled: providerConnectionForm.enabled,
          base_url: providerConnectionForm.baseUrl,
          note: providerConnectionForm.note,
          priority: Number(providerConnectionForm.priority) || 100,
          source_role: providerConnectionForm.sourceRole,
          capability_ids: splitList(providerConnectionForm.capabilityIds),
          runtime_profile_ids: splitList(providerConnectionForm.runtimeProfileIds),
          config: modelConfig,
          metadata: {
            ui_source: 'ai_resources_channel_form',
            provider_preset: providerConnectionForm.providerPreset,
            note: providerConnectionForm.note,
            priority: Number(providerConnectionForm.priority) || 100,
            model_ids: isCapabilityProviderForm ? [] : modelIds,
            model_catalog_preview: isCapabilityProviderForm
              ? undefined
              : catalogPreviewForMetadata(providerCatalogPreview),
          },
          credential: providerConnectionForm.credential || undefined,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_save_connection', 'Failed to save provider connection.')));
      }
      const savedConnectionId = String(payload.data?.connection_id || normalizedConnectionId);
      let testFailed = false;
      setMessage(aiText('message_connection_saved_testing', 'Provider connection saved. Running connection test now.'));
      try {
        await runProviderConnectionTest(savedConnectionId, { announce: false, reload: false });
        setMessage(aiText('message_connection_saved_and_tested', 'Provider connection saved and tested. Credential status is masked in this page.'));
      } catch (testError) {
        testFailed = true;
        setError(
          aiText('message_connection_saved_test_failed', 'Provider connection saved, but the connection test failed: {{message}}', {
            message: testError instanceof Error ? testError.message : aiText('error_test_connection', 'Provider connection test failed.'),
          })
        );
      }
      await loadResources({ showLoading: false });
      if (!testFailed) {
        setProviderConnectionForm(EMPTY_PROVIDER_CONNECTION_FORM);
        setProviderFormMode('create');
        setProviderFormOpen(false);
      }
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : aiText('error_save_connection', 'Failed to save provider connection.'));
    } finally {
      setSavingConnection(false);
    }
  }

  async function deleteProviderConnection(connection: Connection) {
    if (connection.managed_by !== 'cloud_provider_connections') return;
    const confirmed = window.confirm(
      aiText('confirm_delete_connection', 'Delete {{name}}? Its saved credential will be removed from Cloud provider connections.', {
        name: connection.display_name,
      })
    );
    if (!confirmed) return;
    setDeletingConnectionId(connection.connection_id);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`/api/admin/provider-connections/${encodeURIComponent(connection.connection_id)}`, {
        method: 'DELETE',
        credentials: 'include',
        headers: {
          'Idempotency-Key': generateIdempotencyKey(`provider_connection_delete_${connection.connection_id}`),
        },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_delete_connection', 'Failed to delete provider connection.')));
      }
      setMessage(aiText('message_connection_deleted', 'Provider connection deleted.'));
      if (providerConnectionForm.connectionId === connection.connection_id) {
        setProviderFormOpen(false);
        setProviderConnectionForm(EMPTY_PROVIDER_CONNECTION_FORM);
        setProviderFormMode('create');
      }
      await loadResources({ showLoading: false });
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : aiText('error_delete_connection', 'Failed to delete provider connection.'));
    } finally {
      setDeletingConnectionId('');
    }
  }

  async function fetchProviderCatalogPreview() {
    const normalizedConnectionId = providerConnectionForm.connectionId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.providerId);
    const normalizedProviderId = providerConnectionForm.providerId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.connectionId);
    const modelIds = splitList(providerConnectionForm.modelIds);
    const modelConfig = modelIds.length ? { model_ids: modelIds, model_id: modelIds[0] } : {};
    if (!providerConnectionForm.credential.trim() && providerFormMode === 'create') {
      setError(aiText('error_fetch_catalog_credential_required', 'Enter an API key before fetching upstream models. Existing saved credentials are not returned to the browser.'));
      return;
    }
    setFetchingProviderCatalog(true);
    setProviderCatalogPreview(null);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/admin/provider-connections/preview-catalog', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          connection_id: normalizedConnectionId,
          provider_id: normalizedProviderId,
          provider_type: providerConnectionForm.kind,
          kind: providerConnectionForm.kind,
          display_name: providerConnectionForm.displayName,
          enabled: providerConnectionForm.enabled,
          base_url: providerConnectionForm.baseUrl,
          source_role: providerConnectionForm.sourceRole,
          capability_ids: splitList(providerConnectionForm.capabilityIds),
          runtime_profile_ids: splitList(providerConnectionForm.runtimeProfileIds),
          config: modelConfig,
          metadata: {
            ui_source: 'ai_resources_catalog_preview',
            provider_preset: providerConnectionForm.providerPreset,
          },
          credential: providerConnectionForm.credential,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_fetch_catalog', 'Failed to fetch upstream models.')));
      }
      const preview = payload.data as ProviderCatalogPreview;
      setProviderCatalogPreview(preview);
      const verifiedModelIds = (preview.models || [])
        .filter((model) => model.verified || model.runtime_supported)
        .map((model) => model.model_id);
      if (!splitList(providerConnectionForm.modelIds).length && verifiedModelIds.length) {
        setProviderModelIds(verifiedModelIds);
      }
      setMessage(aiText('message_catalog_fetched', 'Fetched {{count}} upstream models.', {
        count: String(preview.model_count || preview.model_ids?.length || 0),
      }));
    } catch (catalogError) {
      setError(catalogError instanceof Error ? catalogError.message : aiText('error_fetch_catalog', 'Failed to fetch upstream models.'));
    } finally {
      setFetchingProviderCatalog(false);
    }
  }

  async function syncModelReferences() {
    setSyncingModelReferences(true);
    setError('');
    setMessage('');
    setModelReferenceAutoSyncError('');
    try {
      const response = await fetch('/api/admin/model-references/sync', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': generateIdempotencyKey('model_references_sync'),
        },
        body: JSON.stringify({}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_sync_model_references', 'Failed to sync model reference data.')));
      }
      const effectiveReferenceProviderId = inferReferenceProviderFromModelIds(
        splitList(providerConnectionForm.modelIds),
        modelReferenceProviderId
      );
      if (effectiveReferenceProviderId !== modelReferenceProviderId) {
        setModelReferenceProviderId(effectiveReferenceProviderId);
      }
      await loadModelReferences(effectiveReferenceProviderId);
      setMessage(aiText('message_model_references_synced', 'Model reference data synced. It is reference-only and does not change billing or routing.'));
    } catch (syncError) {
      const effectiveReferenceProviderId = inferReferenceProviderFromModelIds(
        splitList(providerConnectionForm.modelIds),
        modelReferenceProviderId
      );
      await loadModelReferences(effectiveReferenceProviderId);
      setError(syncError instanceof Error ? syncError.message : aiText('error_sync_model_references', 'Failed to sync model reference data.'));
    } finally {
      setSyncingModelReferences(false);
    }
  }

  const autoSyncModelReferences = useCallback(async (providerId: string) => {
    setAutoSyncingModelReferences(true);
    setModelReferenceAutoSyncError('');
    try {
      const response = await fetch('/api/admin/model-references/sync', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': generateIdempotencyKey(`model_references_auto_sync_${providerId}`),
        },
        body: JSON.stringify({}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_sync_model_references', 'Failed to sync model reference data.')));
      }
      await loadModelReferences(providerId);
    } catch (syncError) {
      await loadModelReferences(providerId);
      setModelReferenceAutoSyncError(
        syncError instanceof Error
          ? syncError.message
          : aiText('model_reference_status_auto_sync_failed', 'Reference intelligence auto sync failed. Saved models and runtime calls are not affected.')
      );
    } finally {
      setAutoSyncingModelReferences(false);
    }
  }, [aiText, loadModelReferences]);

  async function runProviderConnectionTest(
    connectionId: string,
    options: { announce?: boolean; reload?: boolean } = {}
  ) {
    const announce = options.announce !== false;
    const reload = options.reload !== false;
    setTestingConnectionId(connectionId);
    setError('');
    if (announce) {
      setMessage('');
    }
    try {
      const response = await fetch(`/api/admin/provider-connections/${encodeURIComponent(connectionId)}/test`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Idempotency-Key': generateIdempotencyKey('provider_connection_test'),
        },
      });
      const payload = await response.json().catch(() => ({}));
      const result = payload.data as ProviderConnectionTestResult | undefined;
      if (result?.connection_id) {
        setConnectionTestResults((current) => ({
          ...current,
          [result.connection_id]: result,
        }));
      }
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, result?.message || aiText('error_test_connection', 'Provider connection test failed.')));
      }
      if (announce) {
        setMessage(result ? providerTestMessage(result) : aiText('message_connection_tested', 'Provider connection tested.'));
      }
      if (reload) {
        await loadResources({ showLoading: false });
      }
      return result;
    } catch (testError) {
      if (announce) {
        setError(testError instanceof Error ? testError.message : aiText('error_test_connection', 'Provider connection test failed.'));
      }
      throw testError;
    } finally {
      setTestingConnectionId('');
    }
  }

  function updateRoutingDraft(profileId: string, patch: Partial<EditableRoutingProfile>) {
    setRoutingDrafts((current) =>
      current.map((profile) => (profile.profile_id === profileId ? { ...profile, ...patch } : profile))
    );
  }

  function updateRoutingCandidate(profileId: string, index: number, instanceId: string) {
    setRoutingDrafts((current) =>
      current.map((profile) => {
        if (profile.profile_id !== profileId) return profile;
        const nextCandidates = [...profile.candidate_instance_ids];
        nextCandidates[index] = instanceId;
        const uniqueCandidates = nextCandidates
          .map((value) => value.trim())
          .filter(Boolean)
          .filter((value, candidateIndex, values) => values.indexOf(value) === candidateIndex);
        return { ...profile, candidate_instance_ids: uniqueCandidates };
      })
    );
  }

  async function saveAbilityModelProfile(profileId: string) {
    const profile = routingDrafts.find((item) => item.profile_id === profileId);
    if (!profile) {
      setAbilityModelDialogError(aiText('error_save_ability_models', 'Failed to save ability-model routing.'));
      return;
    }
    setSavingRouting(true);
    setAbilityModelDialogError('');
    setAbilityModelDialogMessage('');
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/admin/wordpress-ai-routing', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': routingIdempotencyKey(),
        },
        body: JSON.stringify({
          profiles: [
            {
              profile_id: profile.profile_id,
              candidate_instance_ids: profile.candidate_instance_ids,
              timeout_ms: profile.timeout_ms,
              allow_fallback: profile.allow_fallback,
              max_retries: profile.max_retries,
              note: profile.note,
            },
          ],
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          resolveAdminApiPayloadMessage(
            payload,
            aiText('error_save_ability_models', 'Failed to save ability-model routing.')
          )
        );
      }
      const normalized = normalizeRoutingData(payload.data);
      setRoutingData(normalized);
      setRoutingDrafts(normalized.profiles.map((item) => ({ ...item, note: '' })));
      setAbilityModelDialogMessage(aiText('message_ability_models_saved', 'Ability model routing saved.'));
    } catch (saveError) {
      setAbilityModelDialogError(
        saveError instanceof Error ? saveError.message : aiText('error_save_ability_models', 'Failed to save ability-model routing.')
      );
    } finally {
      setSavingRouting(false);
    }
  }

  function openAbilityModelDialog(profileId: string) {
    setAbilityModelDialogProfileId(profileId);
    setAbilityModelDialogError('');
    setAbilityModelDialogMessage('');
    setError('');
    setMessage('');
  }

  function closeAbilityModelDialog() {
    setAbilityModelDialogProfileId('');
    setAbilityModelDialogError('');
    setAbilityModelDialogMessage('');
  }

  function openNewProviderConnection() {
    setProviderConnectionForm(EMPTY_PROVIDER_CONNECTION_FORM);
    setProviderFormMode('create');
    setConnectionDetailsOpen(true);
    setProviderFormOpen(true);
    setProviderCatalogPreview(null);
    setModelReferenceProviderId(defaultReferenceProviderId(EMPTY_PROVIDER_CONNECTION_FORM.providerId, EMPTY_PROVIDER_CONNECTION_FORM.providerPreset));
    setModelReferenceSearch('');
    setModelReferenceFeatureFilter('all');
    setModelReferenceVisibilityFilter('all');
    setModelReferenceShowDeprecated(true);
    setCustomModelInput('');
    setError('');
    setMessage('');
  }

  function editProviderConnection(connection: Connection) {
    const storedCatalogPreview = catalogPreviewFromConnection(connection);
    setMessage(aiText('message_editing_connection', 'Editing {{name}}. Credential is left blank unless you replace it.', {
      name: connection.display_name,
    }));
    setError('');
    setProviderCatalogPreview(storedCatalogPreview);
    setModelReferenceProviderId(referenceProviderForConnection(connection));
    setModelReferenceSearch('');
    setModelReferenceFeatureFilter('all');
    setModelReferenceVisibilityFilter('all');
    setModelReferenceShowDeprecated(true);
    setCustomModelInput('');
    setProviderFormMode('edit');
    setConnectionDetailsOpen(false);
    setProviderConnectionForm({
      providerPreset: inferProviderPreset(connection),
      connectionId: connection.connection_id,
      providerId: connection.provider_id,
      displayName: connection.display_name,
      kind: connection.kind,
      baseUrl: connection.base_url || '',
      note: connection.note || '',
      priority: String(connection.priority ?? 100),
      sourceRole: 'execution_source',
      capabilityIds: connection.capability_ids.join(', '),
      runtimeProfileIds: connection.runtime_profile_ids.join(', '),
      modelIds: (connection.model_ids || []).join(', '),
      credential: '',
      enabled: connection.enabled,
    });
    setActiveView('connections');
    setProviderFormOpen(true);
  }

  function addProviderCredentialChannel() {
    const sourceConnectionId = providerConnectionForm.connectionId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.providerId);
    const nextConnectionId = `${sourceConnectionId}_backup`;
    setProviderFormMode('create');
    setConnectionDetailsOpen(true);
    setProviderConnectionForm((current) => ({
      ...current,
      connectionId: nextConnectionId,
      displayName: `${current.displayName || current.providerId} ${aiText('channel_backup_suffix', 'backup')}`,
      credential: '',
      note: current.note || aiText('channel_backup_note_default', 'Backup channel'),
      priority: String(Math.min(999, (Number(current.priority) || 100) + 10)),
      enabled: true,
    }));
    setMessage(aiText('message_creating_credential_channel', 'Adding a credential channel. Enter a credential, then save and test.'));
    setError('');
  }

  function updateProviderConnectionForm(patch: Partial<ProviderConnectionForm>) {
    setProviderConnectionForm((current) => ({ ...current, ...patch }));
    if (patch.providerId !== undefined) {
      setModelReferenceProviderId(defaultReferenceProviderId(patch.providerId, providerConnectionForm.providerPreset));
    }
    if (patch.kind || patch.baseUrl || patch.credential || patch.providerId) {
      setProviderCatalogPreview(null);
    }
  }

  function setProviderModelIds(modelIds: string[]) {
    const inferredReferenceProviderId = inferReferenceProviderFromModelIds(modelIds, modelReferenceProviderId);
    if (modelIds.length && inferredReferenceProviderId !== modelReferenceProviderId) {
      setModelReferenceProviderId(inferredReferenceProviderId);
    }
    updateProviderConnectionForm({ modelIds: joinList(modelIds) });
  }

  function addProviderModelIds(modelIds: string[]) {
    setProviderModelIds([...splitList(providerConnectionForm.modelIds), ...modelIds]);
  }

  function removeProviderModelId(modelId: string) {
    setProviderModelIds(splitList(providerConnectionForm.modelIds).filter((item) => item !== modelId));
  }

  function addCustomProviderModels() {
    const modelIds = splitList(customModelInput);
    if (!modelIds.length) return;
    addProviderModelIds(modelIds);
    setCustomModelInput('');
  }

  function applyProviderPreset(presetId: string) {
    const preset = providerPresetById(presetId);
    setProviderCatalogPreview(null);
    setModelReferenceProviderId(defaultReferenceProviderId(preset.providerId, preset.id));
    setModelReferenceSearch('');
    setModelReferenceFeatureFilter('all');
    setModelReferenceVisibilityFilter('all');
    setModelReferenceShowDeprecated(true);
    setCustomModelInput('');
    setProviderConnectionForm((current) => {
      const displayName = current.displayName && current.providerPreset === presetId ? current.displayName : preset.displayName;
      return {
        ...current,
        providerPreset: preset.id,
        providerId: preset.providerId,
        displayName,
        kind: preset.kind,
        baseUrl: preset.baseUrl,
        capabilityIds: preset.capabilityIds,
        runtimeProfileIds: preset.runtimeProfileIds,
        modelIds: preset.modelIds,
        connectionId: current.connectionId || slugifyProviderValue(displayName || preset.providerId),
      };
    });
  }

  function openCapabilityProviderTemplate(template: CapabilityProviderTemplate) {
    setActiveCapabilityCategory(template.category);
    setCapabilityAddDialogOpen(false);
    setProviderFormMode('create');
    setConnectionDetailsOpen(true);
    setProviderCatalogPreview(null);
    setModelReferenceProviderId(defaultReferenceProviderId(template.id, 'custom'));
    setModelReferenceSearch('');
    setModelReferenceFeatureFilter('all');
    setModelReferenceVisibilityFilter('all');
    setModelReferenceShowDeprecated(true);
    setCustomModelInput('');
    setProviderConnectionForm({
      providerPreset: 'custom',
      connectionId: `${template.category}_${template.id}`,
      providerId: template.id,
      displayName: template.label,
      kind: template.kind,
      baseUrl: template.baseUrl,
      note: '',
      priority: '100',
      sourceRole: 'execution_source',
      capabilityIds: template.capabilityIds,
      runtimeProfileIds: template.runtimeProfileIds,
      modelIds: template.modelIds,
      credential: '',
      enabled: true,
    });
    setProviderFormOpen(true);
    setMessage(
      aiText('message_capability_provider_template_existing', '{{name}} already exists. Opening its configuration instead of creating a duplicate row.', {
        name: template.label,
      })
    );
    setError('');
  }

  const resourceStatusLabel = useCallback((status: ResourceStatus): string => {
    switch (status) {
      case 'ready':
        return aiText('status_ready_label', 'Ready');
      case 'missing_secret':
        return aiText('status_missing_secret_label', 'Missing secret');
      case 'missing_provider':
        return aiText('status_missing_provider_label', 'Missing provider');
      case 'disabled':
        return aiText('status_disabled_label', 'Disabled');
      case 'healthy':
        return aiText('status_healthy_label', 'Healthy');
      case 'degraded':
        return aiText('status_degraded_label', 'Degraded');
      case 'error':
        return aiText('status_error_label', 'Error');
      case 'warning':
        return aiText('status_warning_label', 'Warning');
      case 'info':
        return aiText('status_info_label', 'Info');
      case 'not_observed':
        return aiText('status_not_observed', 'Not observed');
      default:
        return status;
    }
  }, [aiText]);

  const providerTestStageLabel = useCallback((stage: string): string => {
    const normalizedStage = stage.trim();
    const labels: Record<string, string> = {
      preflight: aiText('test_stage_preflight', 'Preflight'),
      config_preflight: aiText('test_stage_config_preflight', 'Config preflight'),
      adapter_build: aiText('test_stage_adapter_build', 'Adapter build'),
      catalog_fetch: aiText('test_stage_catalog_fetch', 'Catalog fetch'),
      web_search_probe: aiText('test_stage_web_search_probe', 'Search probe'),
      web_search_reader_probe: aiText('test_stage_web_search_reader_probe', 'Reader probe'),
    };
    return labels[normalizedStage] || normalizedStage || '-';
  }, [aiText]);

  const providerTestMessage = useCallback((result: ProviderConnectionTestResult): string => {
    const normalizedMessage = result.message.trim();
    if (result.stage === 'web_search_probe') {
      return aiText('test_message_web_search_candidates', 'Search provider returned {{count}} source candidates.', {
        count: String(result.probe?.result_count ?? 0),
      });
    }
    if (result.stage === 'web_search_reader_probe') {
      return aiText('test_message_web_search_reader_candidates', 'Reader provider returned {{count}} readable source candidates.', {
        count: String(result.probe?.result_count ?? 0),
      });
    }
    const messages: Record<string, string> = {
      'provider connection is disabled': aiText('test_message_disabled', 'Provider connection is disabled.'),
      'provider credential is missing': aiText('test_message_missing_secret', 'Provider credential is missing.'),
      'provider runtime configuration is present': aiText('test_message_runtime_config_ready', 'Provider runtime configuration is ready.'),
      'provider kind is not supported by the runtime adapter registry': aiText(
        'test_message_unsupported_kind',
        'This provider kind is not supported by the runtime adapter registry.'
      ),
      'provider catalog returned no usable models': aiText('test_message_catalog_empty', 'Provider catalog returned no usable models.'),
      'provider connection is ready': aiText('test_message_ready', 'Provider connection is ready.'),
      'web search reader returned no readable content': aiText('test_message_web_search_reader_empty', 'Reader provider returned no readable content.'),
      'web search reader base URL is missing': aiText('test_message_web_search_reader_missing_base_url', 'Reader provider base URL is missing.'),
    };
    return messages[normalizedMessage] || normalizedMessage || aiText('message_connection_tested', 'Provider connection tested.');
  }, [aiText]);

  const providerKindLabel = useCallback((kind: string): string => {
    switch (kind) {
      case 'text_provider':
        return aiText('kind_text_provider', 'Text provider');
      case 'audio_provider':
        return aiText('kind_audio_provider', 'Audio provider');
      case 'web_search_provider':
        return aiText('kind_web_search_provider', 'Web search provider');
      case 'image_source_provider':
        return aiText('kind_image_source_provider', 'Image source provider');
      case 'embedding_provider':
        return aiText('kind_embedding_provider', 'Embedding provider');
      case 'rerank_provider':
        return aiText('kind_rerank_provider', 'Rerank provider');
      case 'vector_store_provider':
        return aiText('kind_vector_store_provider', 'Vector store provider');
      case 'openai_compatible':
        return aiText('kind_openai_compatible', 'OpenAI compatible');
      case 'anthropic':
        return aiText('kind_anthropic', 'Anthropic');
      case 'openrouter':
        return aiText('kind_openrouter', 'OpenRouter');
      case 'siliconflow':
        return aiText('kind_siliconflow', 'SiliconFlow');
      case 'minimax':
      case 'minimax_audio':
        return aiText('kind_minimax', 'MiniMax');
      case 'litellm_gateway':
        return aiText('kind_litellm_gateway', 'LiteLLM gateway');
      case 'vllm':
        return aiText('kind_vllm', 'vLLM');
      case 'tei':
        return aiText('kind_tei', 'TEI');
      default:
        return kind;
    }
  }, [aiText]);

  const providerDialogName = providerConnectionForm.displayName || providerKindLabel(providerConnectionForm.kind);
  const providerDialogTitle = providerFormMode === 'edit'
    ? isCapabilityProviderForm
      ? aiText('capability_channel_form_edit_named_title', 'Edit {{name}}', { name: providerDialogName })
      : aiText('channel_form_edit_named_title', 'Edit {{name}}', { name: providerDialogName })
    : isCapabilityProviderForm
      ? aiText('capability_channel_form_title', 'Add capability supplier')
      : aiText('channel_form_title', 'Add provider channel');

  const renderConnectionIssue = useCallback((connection: Connection) => {
    if (connection.enabled && connection.configured) {
      return null;
    }

    return (
      <div className="mt-2 text-xs font-medium leading-5">
        {!connection.enabled ? (
          <span className="text-slate-500 dark:text-slate-400">
            {aiText('provider_issue_runtime_disabled', 'Runtime calls are disabled')}
          </span>
        ) : null}
        {!connection.enabled && !connection.configured ? (
          <span className="mx-1 text-slate-300 dark:text-slate-700">·</span>
        ) : null}
        {!connection.configured ? (
          <span className="text-amber-700 dark:text-amber-300">
            {aiText('provider_issue_missing_credential', 'Provider credential is not configured')}
          </span>
        ) : null}
      </div>
    );
  }, [aiText]);

  const filteredConnections = useMemo(() => {
    const query = connectionSearch.trim().toLowerCase();
    return (data?.connections || []).filter((connection) => {
      const matchesFilter =
        connectionStatusFilter === 'all'
        || (connectionStatusFilter === 'ready' && connection.status === 'ready')
        || (connectionStatusFilter === 'missing_secret' && (connection.status === 'missing_secret' || !connection.configured))
        || (connectionStatusFilter === 'disabled' && (!connection.enabled || connection.status === 'disabled'));
      if (!matchesFilter) return false;
      if (!query) return true;
      return [
        connection.display_name,
        connection.provider_id,
        connection.kind,
        connection.status,
        connection.base_url,
        ...(connection.model_ids || []),
        ...connection.capability_ids,
        ...connection.runtime_profile_ids,
      ].some((value) => value.toLowerCase().includes(query));
    });
  }, [connectionSearch, connectionStatusFilter, data]);

  const aiSupplierConnections = useMemo(
    () => filteredConnections.filter((connection) => supplierCategory(connection) === 'ai'),
    [filteredConnections]
  );

  const capabilitySupplierConnections = useMemo(
    () => filteredConnections.filter((connection) => supplierCategory(connection) === 'capability'),
    [filteredConnections]
  );

  const capabilityConnectionsByCategory = useMemo(() => ({
    search: capabilitySupplierConnections.filter((connection) => capabilityProviderCategory(connection) === 'search'),
    image: capabilitySupplierConnections.filter((connection) => capabilityProviderCategory(connection) === 'image'),
    vector: capabilitySupplierConnections.filter((connection) => capabilityProviderCategory(connection) === 'vector'),
  }), [capabilitySupplierConnections]);

  const activeCapabilityConnections = capabilityCategoryFilter === 'all'
    ? capabilitySupplierConnections
    : capabilityConnectionsByCategory[capabilityCategoryFilter];

  const capabilityChannelCounts = useMemo(() => {
    const counts = new Map<string, number>();
    activeCapabilityConnections.forEach((connection) => {
      const key = `${connection.kind}:${connection.provider_id}`;
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return counts;
  }, [activeCapabilityConnections]);

  const capabilityCategoryLabel = useCallback((category: CapabilityProviderCategory): string => {
    if (category === 'search') return aiText('capability_category_search', 'Search');
    if (category === 'image') return aiText('capability_category_image', 'Images');
    return aiText('capability_category_vector', 'Vector');
  }, [aiText]);

  const capabilityProviderPurposeLabel = useCallback((connection: Connection): string => {
    if (connection.kind === 'web_search_provider' || connection.capability_ids.includes('web_search')) {
      return aiText('capability_provider_purpose_search', 'Web search source');
    }
    if (connection.kind === 'image_source_provider' || connection.capability_ids.includes('image_source')) {
      return aiText('capability_provider_purpose_image', 'Image source');
    }
    if (connection.kind === 'embedding_provider' || connection.capability_ids.includes('embedding')) {
      return aiText('capability_provider_purpose_embedding', 'Embedding model');
    }
    if (connection.kind === 'rerank_provider' || connection.capability_ids.includes('site_knowledge_rerank')) {
      return aiText('capability_provider_purpose_rerank', 'Rerank model');
    }
    if (connection.kind === 'vector_store_provider' || connection.capability_ids.includes('vector_store')) {
      return aiText('capability_provider_purpose_vector_store', 'Vector store');
    }
    return providerKindLabel(connection.kind);
  }, [aiText, providerKindLabel]);

  const routingInstancesById = useMemo(() => {
    const map = new Map<string, RuntimeInstance>();
    for (const instance of [
      ...(routingData?.available_text_instances || []),
      ...(routingData?.available_image_instances || []),
    ]) {
      map.set(instance.instance_id, instance);
    }
    return map;
  }, [routingData]);

  const routingCandidateInstancesFor = useCallback(
    (profile: RoutingProfile): RuntimeInstance[] =>
      profile.execution_kind === 'image_generation'
        ? routingData?.available_image_instances || []
        : routingData?.available_text_instances || [],
    [routingData]
  );

  const abilityTaskLabel = useCallback((taskId: string): string => {
    const labels: Record<string, string> = {
      alt_text_suggest: aiText('ability_task_alt_text_suggest', 'Alt text generation'),
      excerpt_generation: aiText('ability_task_excerpt_generation', 'Excerpt generation'),
      meta_description: aiText('ability_task_meta_description', 'Meta description generation'),
      title_generation: aiText('ability_task_title_generation', 'Title generation'),
      comment_reply_suggest: aiText('ability_task_comment_reply_suggest', 'Comment reply suggestion'),
      content_rewrite: aiText('ability_task_content_rewrite', 'Content resizing'),
      content_summary: aiText('ability_task_content_summary', 'Content summary'),
      comment_moderation: aiText('ability_task_comment_moderation', 'Comment moderation'),
      content_classification: aiText('ability_task_content_classification', 'Content classification'),
      image_generation: aiText('ability_task_image_generation', 'Image generation'),
    };
    return labels[taskId] || taskId;
  }, [aiText]);

  const abilityTaskDescription = useCallback((taskId: string): string => {
    const descriptions: Record<string, string> = {
      alt_text_suggest: aiText('ability_task_alt_text_suggest_desc', 'Generate accessible alt text suggestions for media.'),
      excerpt_generation: aiText('ability_task_excerpt_generation_desc', 'Generate reviewable excerpt suggestions from post content.'),
      meta_description: aiText('ability_task_meta_description_desc', 'Generate reviewable SEO meta description suggestions.'),
      title_generation: aiText('ability_task_title_generation_desc', 'Generate title suggestions for the editor.'),
      comment_reply_suggest: aiText('ability_task_comment_reply_suggest_desc', 'Draft reviewable comment reply suggestions.'),
      content_rewrite: aiText('ability_task_content_rewrite_desc', 'Shorten, expand, or rephrase selected editor content.'),
      content_summary: aiText('ability_task_content_summary_desc', 'Summarize content for editor assistance.'),
      comment_moderation: aiText('ability_task_comment_moderation_desc', 'Classify comments for moderation assistance.'),
      content_classification: aiText('ability_task_content_classification_desc', 'Suggest tags and categories from content context.'),
      image_generation: aiText('ability_task_image_generation_desc', 'Generate image candidates for review before WordPress use.'),
    };
    return descriptions[taskId] || aiText('ability_task_default_desc', 'Cloud runtime task from the WordPress AI connector.');
  }, [aiText]);

  const abilityModelFeatureLabel = useCallback((feature: string): string => {
    const normalized = feature.trim();
    if (normalized === 'image_generation' || normalized === 'image_generations' || normalized === 'image') {
      return aiText('ability_model_feature_image_generation', 'Image generation');
    }
    if (normalized === 'text_generation' || normalized === 'text_generations' || normalized === 'text') {
      return aiText('ability_model_feature_text_generation', 'Text generation');
    }
    if (normalized === 'audio_generation' || normalized === 'audio_generations' || normalized === 'audio') {
      return aiText('ability_model_feature_audio_generation', 'Audio generation');
    }
    if (normalized === 'video_generation' || normalized === 'video_generations' || normalized === 'video') {
      return aiText('ability_model_feature_video_generation', 'Video generation');
    }
    if (normalized === 'embedding' || normalized === 'embeddings') {
      return aiText('ability_model_feature_embedding', 'Embedding');
    }
    return normalized || aiText('ability_model_feature_unknown', 'Unknown');
  }, [aiText]);

  const modelReferenceCapabilityLabel = useCallback((tag: string): string => {
    const labels: Record<string, string> = {
      reasoning: aiText('model_reference_capability_reasoning', 'Reasoning'),
      tool_call: aiText('model_reference_capability_tool_call', 'Tool calling'),
      structured_output: aiText('model_reference_capability_structured_output', 'Structured output'),
      attachment: aiText('model_reference_capability_attachment', 'Attachment'),
      open_weights: aiText('model_reference_capability_open_weights', 'Open weights'),
    };
    return labels[tag] || tag;
  }, [aiText]);

  const selectedProviderModelIds = useMemo(
    () => splitList(providerConnectionForm.modelIds),
    [providerConnectionForm.modelIds]
  );

  const modelReferenceProviderOptions = useMemo(() => {
    const currentProviderId = defaultReferenceProviderId(
      providerConnectionForm.providerId,
      providerConnectionForm.providerPreset
    );
    return uniqueList([
      currentProviderId,
      ...PROVIDER_PRESETS.map((preset) => preset.providerId).filter((providerId) => providerId !== 'custom'),
      ...modelReferences.map((reference) => reference.provider_id),
    ]);
  }, [modelReferences, providerConnectionForm.providerId, providerConnectionForm.providerPreset]);

  const referenceProviderCanBeChanged = canChooseReferenceProvider(providerConnectionForm.providerPreset);
  const providerUsesCustomRuntimeFields = !isCapabilityProviderForm && providerConnectionForm.providerPreset === 'custom';

  const selectedModelLookup = useMemo(() => {
    const lookup = new Map<string, string>();
    for (const modelId of selectedProviderModelIds) {
      for (const key of modelLookupKeys(modelId, modelReferenceProviderId)) {
        if (!lookup.has(key)) {
          lookup.set(key, modelId);
        }
      }
    }
    return lookup;
  }, [modelReferenceProviderId, selectedProviderModelIds]);

  const selectedModelMetadataGapCount = useMemo(
    () => selectedProviderModelIds.filter((modelId) => !hasModelMetadataFor(
      modelId,
      modelReferenceProviderId,
      modelReferences,
      providerCatalogPreview?.models || []
    )).length,
    [modelReferenceProviderId, modelReferences, providerCatalogPreview, selectedProviderModelIds]
  );

  const modelsDevReferenceSource = useMemo(
    () => modelReferenceSources.find((source) => source.source_id === 'models.dev') || null,
    [modelReferenceSources]
  );

  useEffect(() => {
    const normalizedProviderId = modelReferenceProviderId.trim().toLowerCase();
    if (!providerFormOpen || isCapabilityProviderForm) return;
    if (!normalizedProviderId || normalizedProviderId === 'custom') return;
    if (loadedModelReferenceProviderId !== normalizedProviderId) return;
    if (loadingModelReferences || syncingModelReferences || autoSyncingModelReferences) return;
    if (!modelReferenceSourceNeedsSync(modelsDevReferenceSource, modelReferenceTotal)) return;
    if (autoSyncedReferenceProviders.current.has(normalizedProviderId)) return;
    autoSyncedReferenceProviders.current.add(normalizedProviderId);
    void autoSyncModelReferences(normalizedProviderId);
  }, [
    autoSyncModelReferences,
    autoSyncingModelReferences,
    isCapabilityProviderForm,
    loadedModelReferenceProviderId,
    loadingModelReferences,
    modelReferenceProviderId,
    modelReferenceTotal,
    modelsDevReferenceSource,
    providerFormOpen,
    syncingModelReferences,
  ]);

  const modelReferenceStatusText = useMemo(() => {
    const providerLabel = referenceProviderLabel(modelReferenceProviderId);
    if (autoSyncingModelReferences) {
      return aiText('model_reference_status_auto_syncing', 'Reference intelligence: {{provider}} · syncing models.dev automatically...', {
        provider: providerLabel,
      });
    }
    if (loadingModelReferences) {
      return aiText('model_reference_status_loading', 'Reference intelligence: {{provider}} · loading...', {
        provider: providerLabel,
      });
    }
    if (modelReferenceAutoSyncError && modelReferenceTotal <= 0) {
      return aiText('model_reference_status_auto_sync_failed', 'Reference intelligence: {{provider}} · automatic sync failed: {{message}}', {
        provider: providerLabel,
        message: modelReferenceAutoSyncError,
      });
    }
    if (modelReferenceTotal > 0) {
      return aiText('model_reference_status_loaded', 'Reference intelligence: {{provider}} · {{count}} local records from models.dev.', {
        provider: providerLabel,
        count: String(modelReferenceTotal),
      });
    }
    if (modelsDevReferenceSource?.status === 'error') {
      return aiText('model_reference_status_error', 'Reference intelligence: {{provider}} · models.dev sync failed: {{message}}', {
        provider: providerLabel,
        message: modelsDevReferenceSource.last_error_message || modelsDevReferenceSource.last_error_code || aiText('unknown', 'unknown'),
      });
    }
    if (modelsDevReferenceSource?.last_synced_at) {
      return aiText('model_reference_status_empty_after_sync', 'Reference intelligence: {{provider}} · no local match after models.dev sync at {{time}}.', {
        provider: providerLabel,
        time: formatDate(modelsDevReferenceSource.last_synced_at),
      });
    }
    return aiText('model_reference_status_not_synced', 'Reference intelligence: {{provider}} · not synced locally yet.', {
      provider: providerLabel,
    });
  }, [
    aiText,
    autoSyncingModelReferences,
    loadingModelReferences,
    modelReferenceAutoSyncError,
    modelReferenceProviderId,
    modelReferenceTotal,
    modelsDevReferenceSource,
  ]);

  const modelReferenceCompactStatusText = useMemo(() => {
    if (autoSyncingModelReferences) {
      return aiText('model_reference_compact_auto_syncing', 'reference syncing');
    }
    if (loadingModelReferences) {
      return aiText('model_reference_compact_loading', 'reference loading');
    }
    if (modelReferenceTotal > 0) {
      return aiText('model_reference_compact_synced', 'reference synced');
    }
    if (modelsDevReferenceSource?.status === 'error' || modelReferenceAutoSyncError) {
      return aiText('model_reference_compact_failed', 'reference sync failed');
    }
    return aiText('model_reference_compact_not_synced', 'reference not synced');
  }, [
    aiText,
    autoSyncingModelReferences,
    loadingModelReferences,
    modelReferenceAutoSyncError,
    modelReferenceTotal,
    modelsDevReferenceSource,
  ]);

  const modelVisibilityRows = useMemo<ModelVisibilityRow[]>(() => {
    const rows = new Map<string, ModelVisibilityRow>();

    for (const reference of modelReferences) {
      const selectedModelId = selectedModelIdFor(
        reference.model_id,
        reference.provider_id || modelReferenceProviderId,
        selectedProviderModelIds,
        selectedModelLookup
      );
      const rowModelId = selectedModelId || reference.model_id;
      rows.set(rowModelId, {
        modelId: rowModelId,
        family: reference.family || reference.source_label,
        feature: reference.feature,
        sourceLabel: reference.source_label,
        sourceKind: 'reference',
        selected: Boolean(selectedModelId),
        verified: false,
        deprecated: reference.is_deprecated,
        reference,
      });
    }

    for (const model of providerCatalogPreview?.models || []) {
      const selectedModelId = selectedModelIdFor(
        model.model_id,
        modelReferenceProviderId,
        selectedProviderModelIds,
        selectedModelLookup
      );
      const rowModelId = selectedModelId || model.model_id;
      const existing = rows.get(rowModelId);
      rows.set(rowModelId, {
        modelId: rowModelId,
        family: existing?.family || model.family,
        feature: existing?.feature || model.feature,
        sourceLabel: existing?.sourceLabel || aiText('model_source_upstream', 'Upstream catalog'),
        sourceKind: existing?.sourceKind || 'catalog',
        selected: Boolean(selectedModelId),
        verified: model.verified || existing?.verified || false,
        deprecated: model.is_deprecated || existing?.deprecated || false,
        reference: existing?.reference,
        catalog: model,
      });
    }

    for (const modelId of selectedProviderModelIds) {
      if (!rows.has(modelId)) {
        rows.set(modelId, {
          modelId,
          family: aiText('model_source_manual', 'Manually added'),
          feature: '',
          sourceLabel: aiText('model_source_enabled_only', 'Saved model ID only'),
          sourceKind: 'manual',
          selected: true,
          verified: false,
          deprecated: false,
        });
      }
    }

    const normalizedSearch = modelReferenceSearch.trim().toLowerCase();
    return Array.from(rows.values())
      .filter((row) => {
        if (!modelReferenceShowDeprecated && row.deprecated) return false;
        if (modelReferenceVisibilityFilter === 'enabled' && !row.selected) return false;
        if (modelReferenceVisibilityFilter === 'disabled' && row.selected) return false;
        if (modelReferenceFeatureFilter !== 'all' && normalizeModelReferenceFeature(row.feature) !== modelReferenceFeatureFilter) {
          return false;
        }
        if (normalizedSearch && !modelReferenceSearchText(row).includes(normalizedSearch)) {
          return false;
        }
        return true;
      })
      .sort((left, right) => {
        if (left.selected !== right.selected) return left.selected ? -1 : 1;
        if (left.deprecated !== right.deprecated) return left.deprecated ? 1 : -1;
        return left.modelId.localeCompare(right.modelId);
      });
  }, [
    aiText,
    modelReferenceFeatureFilter,
    modelReferenceSearch,
    modelReferenceShowDeprecated,
    modelReferenceVisibilityFilter,
    modelReferenceProviderId,
    modelReferences,
    providerCatalogPreview,
    selectedModelLookup,
    selectedProviderModelIds,
  ]);

  const availableModelCount = Math.max(
    modelReferenceTotal,
    Number(providerCatalogPreview?.model_count ?? 0) || 0,
    modelVisibilityRows.length,
    selectedProviderModelIds.length
  );

  const abilityModelRegionLabel = useCallback((region: string): string => {
    const normalized = region.trim();
    if (!normalized || normalized === 'global') {
      return aiText('ability_model_region_global', 'Global');
    }
    return normalized;
  }, [aiText]);

  const abilityModelHealthLabel = useCallback((status: string): string => {
    const normalized = status.trim();
    if (normalized === 'healthy') return aiText('status_healthy_label', 'Healthy');
    if (normalized === 'degraded') return aiText('status_degraded_label', 'Degraded');
    if (normalized === 'error') return aiText('status_error_label', 'Error');
    if (normalized === 'warning') return aiText('status_warning_label', 'Warning');
    return normalized || aiText('status_not_observed', 'not observed');
  }, [aiText]);

  const abilityModelInstanceDetail = useCallback((instance: RuntimeInstance): string => (
    aiText('ability_model_instance_detail', 'Instance: {{instance}} · Capability: {{feature}} · Region: {{region}} · Status: {{status}}', {
      instance: instance.instance_id,
      feature: abilityModelFeatureLabel(instance.model_feature || instance.endpoint_variant),
      region: abilityModelRegionLabel(instance.region),
      status: abilityModelHealthLabel(instance.health_status),
    })
  ), [abilityModelFeatureLabel, abilityModelHealthLabel, abilityModelRegionLabel, aiText]);

  const abilityModelRows = useMemo(() => {
    return routingDrafts.flatMap((profile) => {
      const primaryInstance = routingInstancesById.get(profile.candidate_instance_ids[0] || '');
      const fallbackCount = Math.max(0, profile.candidate_instance_ids.length - 1);
      return profile.tasks.map((taskId) => ({
        taskId,
        label: abilityTaskLabel(taskId),
        description: abilityTaskDescription(taskId),
        profile,
        primaryInstance,
        fallbackCount,
      }));
    });
  }, [abilityTaskDescription, abilityTaskLabel, routingDrafts, routingInstancesById]);

  const activeAbilityModelProfile = useMemo(
    () => routingDrafts.find((profile) => profile.profile_id === abilityModelDialogProfileId) || null,
    [abilityModelDialogProfileId, routingDrafts]
  );

  const activeAbilityModelTitle = useMemo(() => {
    if (!activeAbilityModelProfile) return '';
    if (activeAbilityModelProfile.tasks.length === 1) {
      return abilityTaskLabel(activeAbilityModelProfile.tasks[0]);
    }
    if (activeAbilityModelProfile.tasks.length > 1) {
      return aiText('ability_model_group_title', '{{name}} 等 {{count}} 个能力', {
        name: abilityTaskLabel(activeAbilityModelProfile.tasks[0]),
        count: String(activeAbilityModelProfile.tasks.length),
      });
    }
    return activeAbilityModelProfile.label;
  }, [abilityTaskLabel, activeAbilityModelProfile, aiText]);

  const matrixRows = useMemo<CapabilityMatrixRow[]>(() => {
    if (!data) return [];
    if (data.capability_matrix?.length) return data.capability_matrix;
    return data.capabilities.map((capability) => ({
      capability_id: capability.capability_id,
      label: capability.label,
      status: capability.status,
      used_by: capability.used_by,
      write_posture: capability.write_posture,
      default_profile_id: capability.default_profile_id,
      connection_ids: capability.connection_ids,
      profiles: data.runtime_profiles.filter((profile) => profile.capability_id === capability.capability_id),
      selection_owner: 'cloud_runtime_metadata',
      direct_wordpress_write: false,
    }));
  }, [data]);

  const runtimeResolutionRows = useMemo<RuntimeResolutionRow[]>(() => {
    if (!data) return [];
    if (data.runtime_resolution?.length) return data.runtime_resolution;
    return matrixRows.map((row) => ({
      capability_id: row.capability_id,
      label: row.label,
      status: row.status,
      selected_profile_id: row.default_profile_id,
      selected_provider_id: row.profiles[0]?.selected_provider_id || '',
      selected_model_id: row.profiles[0]?.selected_model_id || '',
      selected_connection_ids: row.connection_ids,
      ready_connection_ids: row.connection_ids,
      runtime_provider_available: row.status === 'ready',
      runtime_provider_ids: [],
      write_posture: row.write_posture,
      selection_owner: row.selection_owner,
      direct_wordpress_write: row.direct_wordpress_write,
    }));
  }, [data, matrixRows]);

  const healthWindows = useMemo<ProviderModelHealthWindow[]>(() => {
    const configured = data?.provider_model_health?.windows || [];
    if (configured.length) return configured;
    return LEGACY_HEALTH_WINDOW_FALLBACKS.map((windowItem) => ({
      ...windowItem,
      started_at: '',
      ended_at: '',
      rows: data?.provider_model_health?.rows || [],
      alert_summary: data?.provider_model_health?.alert_summary,
    }));
  }, [data]);

  const activeHealthWindow = useMemo<ProviderModelHealthWindow | null>(() => {
    if (!healthWindows.length) return null;
    return (
      healthWindows.find((windowItem) => windowItem.window_id === activeHealthWindowId) ||
      healthWindows.find((windowItem) => windowItem.window_id === data?.provider_model_health?.default_window_id) ||
      healthWindows[0]
    );
  }, [activeHealthWindowId, data, healthWindows]);

  function healthWindowLabel(windowItem: ProviderModelHealthWindow): string {
    if (windowItem.window_id === 'last_24h') {
      return aiText('window_last_24h', 'Last 24h');
    }
    if (windowItem.window_id === 'last_7d') {
      return aiText('window_last_7d', 'Last 7d');
    }
    return windowItem.label;
  }

  const activeDiagnosticView: DiagnosticsTab | AIResourceView =
    activeView === 'diagnostics' ? activeDiagnosticsTab : activeView;
  const translateRuntimeTelemetryText = useCallback(
    (value: string | undefined): string => {
      const text = String(value || '').trim();
      if (!text) return '';
      const key = RUNTIME_TELEMETRY_TEXT_KEYS[text];
      return key ? aiText(key, text) : text;
    },
    [aiText]
  );
  const runtimeTelemetryStatus = runtimeTelemetry?.alertSummary.status || 'inactive';

  if (loading) {
    return <LoadingFallback />;
  }

  if (!data) {
    return (
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow={aiText('eyebrow', 'Provider settings')}
          title={aiText('title', 'Provider management')}
          description={aiText('unavailable_desc', 'Cloud runtime provider resources are unavailable.')}
        >
          <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
            {error || aiText('unavailable_message', 'Provider management is unavailable.')}
          </BackofficeStackCard>
        </BackofficePrimaryPanel>
      </BackofficePageStack>
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={aiText('eyebrow', 'Provider settings')}
        title={aiText('title', 'Provider management')}
        description={aiText('description', 'Manage Cloud runtime suppliers, credentials, and visibility.')}
        aside={(
          activeView === 'diagnostics' ? (
            <button
              type="button"
              className="btn btn-secondary justify-center"
              onClick={() => setActiveView('connections')}
            >
              {aiText('action_back_to_suppliers', 'Back to suppliers')}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-secondary justify-center"
              onClick={() => setActiveView('diagnostics')}
            >
              {aiText('action_view_diagnostics', 'View diagnostics')}
            </button>
          )
        )}
        actions={null}
        contentClassName="py-4 md:py-4"
      >
        {!providerFormOpen && message ? (
          <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200">
            {message}
          </BackofficeStackCard>
        ) : null}
        {!providerFormOpen && error ? (
          <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
            {error}
          </BackofficeStackCard>
        ) : null}
      </BackofficePrimaryPanel>

      {activeView === 'diagnostics' ? (
        <BackofficeSectionPanel>
          <div>
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('diagnostics_title', 'Diagnostics')}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {aiText('diagnostics_desc', 'Read-only runtime evidence for provider troubleshooting. It does not edit suppliers, routing, prompts, abilities, or WordPress writes.')}
              </p>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {runtimeTelemetryError ? (
              <BackofficeStackCard className="border-amber-200 bg-amber-50 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/25 dark:text-amber-200">
                {runtimeTelemetryError}
              </BackofficeStackCard>
            ) : null}
            {runtimeTelemetry ? (
              <>
                <BackofficeMetricStrip
                  columnsClassName="md:grid-cols-2 xl:grid-cols-5"
                  items={[
                    {
                      label: aiText('runtime_telemetry_status', 'Runtime telemetry'),
                      value: translateRuntimeTelemetryText(runtimeTelemetryStatus),
                      detail: translateRuntimeTelemetryText(runtimeTelemetry.alertSummary.summary),
                      toneClassName:
                        runtimeTelemetryStatus === 'error'
                          ? 'text-rose-600 dark:text-rose-400'
                          : runtimeTelemetryStatus === 'warning'
                            ? 'text-amber-600 dark:text-amber-400'
                            : runtimeTelemetryStatus === 'ok'
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : undefined,
                      size: 'compact',
                    },
                    {
                      label: aiText('runtime_telemetry_runs', 'Runs'),
                      value: formatInteger(runtimeTelemetry.totals.runs),
                      detail: aiText('runtime_telemetry_provider_calls_detail', '{{count}} provider calls', {
                        count: formatInteger(runtimeTelemetry.totals.providerCalls),
                      }),
                      size: 'compact',
                    },
                    {
                      label: aiText('runtime_telemetry_meter_coverage', 'Meter coverage'),
                      value: formatPreciseRate(runtimeTelemetry.totals.meteredRunCoverageRate),
                      toneClassName:
                        runtimeTelemetry.totals.meteredRunCoverageRate < 1
                          ? 'text-amber-600 dark:text-amber-400'
                          : undefined,
                      size: 'compact',
                    },
                    {
                      label: aiText('runtime_telemetry_provider_coverage', 'Provider coverage'),
                      value: formatPreciseRate(runtimeTelemetry.totals.providerCallRunCoverageRate),
                      toneClassName:
                        runtimeTelemetry.totals.providerCallRunCoverageRate < 1
                          ? 'text-amber-600 dark:text-amber-400'
                          : undefined,
                      size: 'compact',
                    },
                    {
                      label: aiText('runtime_telemetry_meter_events', 'Meter events'),
                      value: formatInteger(runtimeTelemetry.totals.usageMeterEvents),
                      detail: runtimeTelemetry.generatedAt ? formatDate(runtimeTelemetry.generatedAt) : '',
                      size: 'compact',
                    },
                  ]}
                />
                {runtimeTelemetry.alertSummary.alerts.length ? (
                  <div className="grid gap-3 xl:grid-cols-2">
                    {runtimeTelemetry.alertSummary.alerts.slice(0, 2).map((alert) => (
                      <BackofficeStackCard key={alert.code} className="space-y-2">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-slate-950 dark:text-white">
                              {translateRuntimeTelemetryText(alert.title)}
                            </p>
                            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                              {translateRuntimeTelemetryText(alert.summary)}
                            </p>
                          </div>
                          <BackofficeStatusBadge
                            label={alert.severity || runtimeTelemetryStatus}
                            status={severityTone(alert.severity || runtimeTelemetryStatus)}
                          />
                        </div>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {translateRuntimeTelemetryText(alert.suggestedAction)}
                        </p>
                      </BackofficeStackCard>
                    ))}
                  </div>
                ) : null}
                <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {aiText(
                    'runtime_telemetry_boundary_notice',
                    'Evidence source: run_records, provider_call_records, and usage_meter_events. This summary is read-only and excludes prompts, results, provider secrets, and WordPress write controls.'
                  )}
                </p>
              </>
            ) : null}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                activeDiagnosticsTab === 'matrix'
                  ? 'border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700'
              }`}
              onClick={() => setActiveDiagnosticsTab('matrix')}
            >
              {aiText('tab_matrix', 'Capability Matrix')}
            </button>
            <button
              type="button"
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                activeDiagnosticsTab === 'usage'
                  ? 'border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700'
              }`}
              onClick={() => setActiveDiagnosticsTab('usage')}
            >
              {aiText('tab_usage', 'Feature usage')}
            </button>
            <button
              type="button"
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                activeDiagnosticsTab === 'health'
                  ? 'border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950'
                  : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700'
              }`}
              onClick={() => setActiveDiagnosticsTab('health')}
            >
              {aiText('tab_health', 'Model health')}
            </button>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeView === 'connections' ? (
        <>
          <BackofficeSectionPanel>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="flex flex-wrap gap-2">
            {[
              ['model', aiText('supplier_tab_model', 'Model suppliers')],
              ['capability', aiText('supplier_tab_capability', 'Capability suppliers')],
            ].map(([tabId, label]) => (
              <button
                key={tabId}
                type="button"
                className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${
                  activeSupplierTab === tabId
                    ? 'border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950'
                    : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700'
                }`}
                onClick={() => setActiveSupplierTab(tabId as SupplierSettingsTab)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center xl:justify-end">
            <label className="grid min-w-[16rem] gap-1 sm:w-[22rem]">
              <span className="sr-only">{aiText('field_search_connections', 'Search suppliers')}</span>
              <input
                className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={connectionSearch}
                onChange={(event) => setConnectionSearch(event.target.value)}
                placeholder={aiText('placeholder_search_connections', 'Name, provider, model, capability')}
              />
            </label>
            {activeSupplierTab === 'model' ? (
              <button type="button" className="btn btn-primary justify-center" onClick={openNewProviderConnection}>
                {aiText('action_add_model_supplier', 'Add model supplier')}
              </button>
            ) : (
              <button type="button" className="btn btn-primary justify-center" onClick={() => setCapabilityAddDialogOpen(true)}>
                {aiText('action_add_capability_supplier', 'Add capability supplier')}
              </button>
            )}
          </div>
        </div>

        {activeSupplierTab === 'model' || providerFormOpen ? (
          <>
        {providerFormOpen ? (
          <div
            className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/45 px-4 py-6 backdrop-blur-sm sm:py-10"
            role="dialog"
            aria-modal="true"
            aria-labelledby="provider-channel-dialog-title"
          >
            <div className="flex max-h-[calc(100vh-3rem)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950">
              <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-3 dark:border-slate-800">
                <div className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <h3 id="provider-channel-dialog-title" className="text-base font-semibold text-slate-950 dark:text-white">
                      {providerDialogTitle}
                    </h3>
                    {isCapabilityProviderForm ? (
                      <BackofficeStatusBadge
                        label={aiText('capability_supplier_badge', '{{category}} supplier', {
                          category: capabilityCategoryLabel(providerFormCapabilityCategory),
                        })}
                        status="info"
                      />
                    ) : null}
                    {providerFormMode === 'edit' ? (
                      <button
                        type="button"
                        className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:text-white"
                        disabled={savingConnection}
                        onClick={addProviderCredentialChannel}
                      >
                        {aiText('action_add_credential_channel', 'Add credential')}
                      </button>
                    ) : null}
                  </div>
                </div>
                <button
                  type="button"
                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-sm font-semibold text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400 dark:hover:border-slate-700 dark:hover:text-white"
                  disabled={savingConnection}
                  onClick={() => setProviderFormOpen(false)}
                  aria-label={aiText('action_close_dialog', 'Close')}
                >
                  <span aria-hidden="true">X</span>
                </button>
              </div>
              {message || error ? (
                <div className="grid gap-2 border-b border-slate-200 px-5 py-3 dark:border-slate-800">
                  {message ? (
                    <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200">
                      {message}
                    </div>
                  ) : null}
                  {error ? (
                    <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
                      {error}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <form
                className="flex min-h-0 flex-1 flex-col"
                onSubmit={(event) => {
                  event.preventDefault();
                  void saveProviderConnection();
                }}
              >
                <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto px-5 py-4">
                <details
                  className="group border-b border-slate-200 pb-3 dark:border-slate-800"
                  open={connectionDetailsOpen}
                  onToggle={(event) => setConnectionDetailsOpen(event.currentTarget.open)}
                >
                  <summary className="flex cursor-pointer list-none flex-col gap-2 rounded-lg px-1 py-1.5 transition hover:bg-slate-50 dark:hover:bg-slate-900/50 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                        <span className="mr-2 inline-block text-slate-400 transition group-open:rotate-90 dark:text-slate-500">›</span>
                        {aiText('connection_section_title', 'Connection')}
                      </h3>
                      <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                        {providerConnectionForm.displayName || providerKindLabel(providerConnectionForm.kind)}
                        <span className="mx-1 text-slate-300 dark:text-slate-700">·</span>
                        {connectionHost(providerConnectionForm.baseUrl) || aiText('connection_summary_base_url_missing', 'No base URL')}
                        <span className="mx-1 text-slate-300 dark:text-slate-700">·</span>
                        {providerConnectionForm.enabled ? aiText('field_enabled', 'Enabled') : aiText('status_disabled_label', 'Disabled')}
                      </p>
                    </div>
                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                      {aiText('connection_section_toggle_hint', 'Low-frequency settings')}
                    </span>
                  </summary>
                  <div className="mt-3 grid gap-3 px-1">
                    <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {isCapabilityProviderForm
                        ? aiText('capability_connection_section_desc', 'Configure service identity, base URL, credential, and runtime enablement for this capability supplier.')
                        : aiText('connection_section_desc', 'Choose the service, name, base URL, and credential for this runtime channel.')}
                    </p>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                      {!isCapabilityProviderForm ? (
                        <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                          {aiText('field_provider_type', 'Provider type')}
                          <select
                            className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                            value={providerConnectionForm.providerPreset}
                            onChange={(event) => applyProviderPreset(event.target.value)}
                          >
                            {PROVIDER_PRESETS.map((preset) => (
                              <option key={preset.id} value={preset.id}>
                                {preset.label}
                              </option>
                            ))}
                          </select>
                        </label>
                      ) : null}
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_display_name', 'Display name')}
                        <input
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          value={providerConnectionForm.displayName}
                          onChange={(event) => {
                            const displayName = event.target.value;
                            updateProviderConnectionForm({
                              displayName,
                              connectionId: providerConnectionForm.connectionId ? providerConnectionForm.connectionId : slugifyProviderValue(displayName),
                            });
                          }}
                          placeholder="GPT-5.5 via NewAPI"
                          required
                        />
                      </label>
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_credential', 'API Key')}
                        <input
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          type="password"
                          value={providerConnectionForm.credential}
                          onChange={(event) => updateProviderConnectionForm({ credential: event.target.value })}
                          placeholder={aiText('placeholder_keep_current_credential', 'leave blank to keep current')}
                        />
                      </label>
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_channel_priority', 'Priority')}
                        <input
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          type="number"
                          min={0}
                          max={999}
                          value={providerConnectionForm.priority}
                          onChange={(event) => updateProviderConnectionForm({ priority: event.target.value })}
                        />
                        <span className="text-xs font-normal leading-5 text-slate-500 dark:text-slate-400">
                          {aiText('field_channel_priority_help', 'Lower numbers are used first. Default is 100.')}
                        </span>
                      </label>
                    </div>

                    <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                      {aiText('field_channel_note', 'Channel note')}
                      <textarea
                        className="min-h-20 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                        value={providerConnectionForm.note}
                        onChange={(event) => updateProviderConnectionForm({ note: event.target.value })}
                        placeholder={aiText('placeholder_channel_note', 'Primary account, backup key, customer account, quota note')}
                        maxLength={512}
                      />
                    </label>

                    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_base_url', 'Base URL')}
                        <input
                          className={`h-11 rounded-lg border px-3 text-sm ${
                            shouldLockCapabilityBaseUrl
                              ? 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-200'
                              : 'border-slate-300 bg-white text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white'
                          }`}
                          value={providerConnectionForm.baseUrl}
                          onChange={(event) => updateProviderConnectionForm({ baseUrl: event.target.value })}
                          placeholder="https://api.example.com/v1"
                          readOnly={shouldLockCapabilityBaseUrl}
                        />
                        {shouldLockCapabilityBaseUrl ? (
                          <span className="text-xs font-normal leading-5 text-slate-500 dark:text-slate-400">
                            {aiText('capability_base_url_template_notice', 'Template value for this known supplier. Override only from diagnostics.')}
                          </span>
                        ) : null}
                      </label>
                      <label className="inline-flex min-h-11 items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                        <input
                          type="checkbox"
                          checked={providerConnectionForm.enabled}
                          onChange={(event) => updateProviderConnectionForm({ enabled: event.target.checked })}
                        />
                        {aiText('field_enabled_runtime', 'Enabled for runtime use')}
                      </label>
                    </div>
                  </div>
                </details>

                {isCapabilityProviderForm ? null : (
                <section className="grid gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
                  <div className="grid gap-3">
                    <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
                      <div className="min-w-0">
                        <h3 className="text-sm font-semibold text-slate-950 dark:text-white">{aiText('model_visibility_title', 'Model visibility')}</h3>
                        <p className="mt-1 text-xs font-normal text-slate-500 dark:text-slate-400">
                          {aiText('model_visibility_compact_summary', 'Enabled {{enabled}} / available {{available}} · {{status}}', {
                            enabled: String(splitList(providerConnectionForm.modelIds).length),
                            available: String(availableModelCount),
                            status: modelReferenceCompactStatusText,
                          })}
                          {selectedModelMetadataGapCount ? (
                            <>
                              {' '}
                              {aiText('model_metadata_gap_hint', '{{count}} models only have saved IDs. Sync the model catalog or reference data to fill capability, context, and price.', {
                                count: String(selectedModelMetadataGapCount),
                              })}
                            </>
                          ) : null}
                        </p>
                      </div>

                      <div className="flex flex-col gap-2 sm:flex-row sm:items-end xl:justify-end">
                        <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600 dark:text-slate-300 sm:w-80">
                          {aiText('field_search_models', 'Search models')}
                          <input
                            className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                            value={modelReferenceSearch}
                            onChange={(event) => setModelReferenceSearch(event.target.value)}
                            placeholder={aiText('placeholder_search_models', 'model, family, provider')}
                          />
                        </label>

                        <details className="relative text-xs text-slate-600 dark:text-slate-300">
                          <summary className="flex h-10 cursor-pointer list-none items-center justify-center rounded-full border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700">
                            {aiText('model_visibility_more_operations', 'More operations')}
                          </summary>
                          <div className="mt-2 grid gap-4 rounded-xl border border-slate-200 bg-slate-50 p-3 shadow-xl dark:border-slate-800 dark:bg-slate-900 sm:absolute sm:right-0 sm:z-30 sm:w-[42rem]">
                            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)]">
                              <div className="grid gap-2">
                                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
                                  {aiText('model_visibility_operations_title', 'Actions')}
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                  <button
                                    type="button"
                                    className="btn btn-primary h-9 px-3 py-1 text-xs"
                                    disabled={fetchingProviderCatalog || savingConnection}
                                    onClick={() => void fetchProviderCatalogPreview()}
                                  >
                                    {fetchingProviderCatalog
                                      ? aiText('action_fetching_upstream_models', 'Fetching...')
                                      : aiText('action_fetch_upstream_models', 'Sync model catalog')}
                                  </button>
                                  <button
                                    type="button"
                                    className="h-9 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700"
                                    disabled={syncingModelReferences || autoSyncingModelReferences || loadingModelReferences || savingConnection}
                                    onClick={() => void syncModelReferences()}
                                  >
                                    {syncingModelReferences || autoSyncingModelReferences
                                      ? aiText('action_syncing_model_references', 'Syncing...')
                                      : aiText('action_sync_model_references', 'Sync reference data')}
                                  </button>
                                  <button
                                    type="button"
                                    className="h-9 rounded-full border border-transparent bg-transparent px-3 py-1 text-xs font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                                    disabled={!splitList(providerConnectionForm.modelIds).length || savingConnection}
                                    onClick={() => setProviderModelIds([])}
                                  >
                                    {aiText('action_clear_all_models', 'Clear all')}
                                  </button>
                                  <label className="flex h-9 items-center gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
                                    <input
                                      type="checkbox"
                                      checked={modelReferenceShowDeprecated}
                                      onChange={(event) => setModelReferenceShowDeprecated(event.target.checked)}
                                    />
                                    {aiText('field_show_deprecated_models', 'Show deprecated')}
                                  </label>
                                </div>
                              </div>

                              <div className="grid gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
                                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">
                                  {aiText('model_visibility_status_title', 'Status')}
                                </div>
                                <div className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                                  <div>
                                    {providerCatalogPreview
                                      ? aiText('catalog_preview_loaded', 'Loaded {{count}} models from upstream.', {
                                        count: String(providerCatalogPreview.model_count),
                                      })
                                      : aiText('model_catalog_empty_compact', 'Upstream catalog has not been synced yet.')}
                                  </div>
                                  <div>{modelReferenceStatusText}</div>
                                </div>
                              </div>
                            </div>

                            {referenceProviderCanBeChanged ? (
                              <details className="rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
                                <summary className="cursor-pointer font-semibold text-slate-700 dark:text-slate-200">
                                  {aiText('reference_provider_summary', 'Reference intelligence source: {{provider}}', {
                                    provider: referenceProviderLabel(modelReferenceProviderId),
                                  })}
                                </summary>
                                <label className="mt-3 grid max-w-sm gap-1 font-semibold">
                                  {aiText('field_reference_provider', 'Reference source')}
                                  <select
                                    className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                                    value={modelReferenceProviderId}
                                    onChange={(event) => setModelReferenceProviderId(event.target.value)}
                                  >
                                    {modelReferenceProviderOptions.map((providerId) => (
                                      <option key={providerId} value={providerId}>
                                        {referenceProviderLabel(providerId)}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                                <p className="mt-2 leading-5 text-slate-500 dark:text-slate-400">
                                  {aiText('reference_provider_desc', 'Only compatible or custom channels need this. Clear provider types automatically use their own reference intelligence.')}
                                </p>
                              </details>
                            ) : null}

                            <div className="grid gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
                              <div>
                                <div className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                                  {aiText('manual_model_add_title', 'Add model ID manually')}
                                </div>
                                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                                  {aiText('manual_model_add_desc', 'Use this only for models missing from the upstream catalog. Manual-only rows can be removed from the list.')}
                                </p>
                              </div>
                              <div className="flex flex-col gap-2 sm:flex-row">
                                <input
                                  className="h-10 min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                                  value={customModelInput}
                                  onChange={(event) => setCustomModelInput(event.target.value)}
                                  onKeyDown={(event) => {
                                    if (event.key === 'Enter') {
                                      event.preventDefault();
                                      addCustomProviderModels();
                                    }
                                  }}
                                  placeholder={aiText('placeholder_add_custom_models', 'Add specified models, separated by commas')}
                                />
                                <button
                                  type="button"
                                  className="btn btn-secondary h-10 shrink-0"
                                  disabled={!customModelInput.trim()}
                                  onClick={addCustomProviderModels}
                                >
                                  {aiText('action_add_model', 'Add')}
                                </button>
                              </div>
                            </div>
                          </div>
                        </details>
                      </div>
                    </div>

                    {loadingModelReferences ? (
                        <div className="rounded-lg border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                          {aiText('loading_model_references', 'Loading model reference data...')}
                        </div>
                      ) : modelVisibilityRows.length ? (
                        <div className="relative max-h-[22rem] overflow-auto border-t border-slate-200 dark:border-slate-800">
                          <table className="w-full min-w-[50rem] text-left text-xs">
                            <thead className="sticky top-0 z-10 bg-slate-50 text-slate-500 shadow-[0_1px_0_rgba(148,163,184,0.25)] dark:bg-slate-900 dark:text-slate-400 dark:shadow-[0_1px_0_rgba(30,41,59,0.9)]">
                              <tr>
                                <th className="px-3 py-2 font-semibold">
                                  <select
                                    className="h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold normal-case tracking-normal text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200"
                                    value={modelReferenceVisibilityFilter}
                                    onChange={(event) => setModelReferenceVisibilityFilter(event.target.value as ModelReferenceVisibilityFilter)}
                                    aria-label={aiText('field_visibility_filter', 'Visibility')}
                                  >
                                    <option value="all">{aiText('filter_all', 'All')}</option>
                                    <option value="enabled">{aiText('filter_enabled_models', 'Enabled')}</option>
                                    <option value="disabled">{aiText('filter_disabled_models', 'Disabled')}</option>
                                  </select>
                                </th>
                                <th className="px-3 py-2 font-semibold">{aiText('catalog_model_header_model', 'Model')}</th>
                                <th className="px-3 py-2 font-semibold">
                                  <select
                                    className="h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold normal-case tracking-normal text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200"
                                    value={modelReferenceFeatureFilter}
                                    onChange={(event) => setModelReferenceFeatureFilter(event.target.value as ModelReferenceFeatureFilter)}
                                    aria-label={aiText('field_feature_filter', 'Feature')}
                                  >
                                    <option value="all">{aiText('filter_all', 'All')}</option>
                                    <option value="text">{aiText('ability_model_feature_text_generation', 'Text generation')}</option>
                                    <option value="image">{aiText('ability_model_feature_image_generation', 'Image generation')}</option>
                                    <option value="audio">{aiText('ability_model_feature_audio_generation', 'Audio generation')}</option>
                                    <option value="video">{aiText('ability_model_feature_video_generation', 'Video generation')}</option>
                                    <option value="embedding">{aiText('ability_model_feature_embedding', 'Embedding')}</option>
                                  </select>
                                </th>
                                <th className="px-3 py-2 font-semibold">{aiText('column_context_output', 'Context / output')}</th>
                                <th className="px-3 py-2 font-semibold">{aiText('column_reference_price', 'Reference price')}</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                              {modelVisibilityRows.map((row) => {
                                const tags = row.reference ? modelReferenceCapabilityTags(row.reference) : [];
                                const tagLabels = tags.map(modelReferenceCapabilityLabel);
                                const visibleTagLabels = tagLabels.slice(0, 3);
                                const canRemoveManualModel = row.sourceKind === 'manual' && row.selected;
                                return (
                                  <tr key={row.modelId}>
                                    <td className="px-3 py-2">
                                      <div className="flex flex-col gap-1">
                                        <button
                                          type="button"
                                          className={`inline-flex w-fit rounded-full px-2 py-1 text-[11px] font-semibold transition ${
                                          row.selected
                                            ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                                            : 'bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-300'
                                        } hover:ring-2 hover:ring-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:hover:ring-slate-700`}
                                          aria-pressed={row.selected}
                                          title={
                                            row.selected
                                              ? aiText('action_disable_catalog_model', 'Disable')
                                              : aiText('action_enable_catalog_model', 'Enable')
                                          }
                                          onClick={() => {
                                            if (row.selected) {
                                              removeProviderModelId(row.modelId);
                                            } else {
                                              setProviderModelIds([...selectedProviderModelIds, row.modelId]);
                                            }
                                          }}
                                        >
                                          {row.selected
                                            ? aiText('status_model_enabled', 'Enabled')
                                            : aiText('status_model_disabled', 'Not enabled')}
                                        </button>
                                        {row.deprecated ? (
                                          <span className="inline-flex w-fit rounded-full bg-amber-100 px-2 py-1 text-[11px] font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                                            {aiText('catalog_model_deprecated', 'deprecated')}
                                          </span>
                                        ) : null}
                                      </div>
                                    </td>
                                    <td className="px-3 py-2">
                                      <div className="font-semibold text-slate-900 dark:text-white">{row.modelId}</div>
                                      <div className="text-slate-500 dark:text-slate-400">
                                        {row.family}
                                        {row.sourceKind === 'manual' ? ` · ${row.sourceLabel}` : ''}
                                        {row.verified ? ` · ${aiText('catalog_model_status_verified', 'Verified')}` : ''}
                                        {row.reference?.override_present ? ` · ${aiText('model_reference_override', 'manual override')}` : ''}
                                      </div>
                                      {canRemoveManualModel ? (
                                        <button
                                          type="button"
                                          className="mt-1 text-xs font-semibold text-slate-500 underline-offset-2 transition hover:text-rose-700 hover:underline dark:text-slate-400 dark:hover:text-rose-300"
                                          onClick={() => removeProviderModelId(row.modelId)}
                                        >
                                          {aiText('action_remove_manual_model', 'Remove manual model')}
                                        </button>
                                      ) : null}
                                    </td>
                                    <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                                      {abilityModelFeatureLabel(row.feature)}
                                      {tagLabels.length ? (
                                        <div
                                          className="mt-1 max-w-[16rem] truncate text-slate-500 dark:text-slate-400"
                                          title={tagLabels.join(' · ')}
                                        >
                                          {visibleTagLabels.join(' · ')}
                                          {tagLabels.length > visibleTagLabels.length ? ` · +${tagLabels.length - visibleTagLabels.length}` : ''}
                                        </div>
                                      ) : null}
                                    </td>
                                    <td
                                      className="px-3 py-2 text-slate-600 dark:text-slate-300"
                                      title={row.reference ? formatReferenceContextTitle(row.reference) : undefined}
                                    >
                                      {row.reference
                                        ? formatReferenceContext(row.reference, aiText('model_reference_missing_context', 'No reference data'))
                                        : aiText('model_reference_missing_context', 'No reference data')}
                                    </td>
                                    <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                                      {row.reference
                                        ? formatReferencePrice(
                                          row.reference,
                                          aiText('price_cache_label', 'Cache'),
                                          aiText('model_reference_missing_price', 'No reference price')
                                        )
                                        : aiText('model_reference_missing_price', 'No reference price')}
                                      {row.reference && hasReferencePrice(row.reference) ? (
                                        <div className="mt-1 text-slate-500 dark:text-slate-400">{aiText('price_unit_per_1m', 'per 1M tokens')}</div>
                                      ) : null}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <div className="rounded-lg border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                          {aiText('model_visibility_empty', 'No models match the current filters. Sync a catalog, sync reference intelligence, or add a model manually.')}
                        </div>
                    )}
                  </div>
                </section>
                )}

                {isCapabilityProviderForm ? (
                  <details className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
                    <summary className="cursor-pointer text-sm font-semibold text-slate-900 dark:text-white">
                      {aiText('capability_diagnostics_title', 'Technical information')}
                    </summary>
                    <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {aiText('capability_diagnostics_desc', 'Read-only runtime metadata for support and migration. These values are not normal setup fields.')}
                    </p>
                    <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      {[
                        [aiText('field_base_url', 'Base URL'), providerConnectionForm.baseUrl],
                        [aiText('field_capabilities', 'Capabilities'), providerConnectionForm.capabilityIds],
                        [aiText('field_profiles', 'Profiles'), providerConnectionForm.runtimeProfileIds],
                        [aiText('field_connection_id', 'Connection ID'), providerConnectionForm.connectionId],
                        [aiText('field_provider_id', 'Provider ID'), providerConnectionForm.providerId],
                        [aiText('field_kind', 'Kind'), providerConnectionForm.kind],
                        [aiText('field_source_role', 'Source role'), providerConnectionForm.sourceRole],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/40">
                          <div className="text-xs font-semibold text-slate-500 dark:text-slate-400">{label}</div>
                          <code className="mt-2 block break-all text-sm font-semibold text-slate-800 dark:text-slate-100">
                            {value || '-'}
                          </code>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}

                {providerUsesCustomRuntimeFields ? (
                  <details className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
                    <summary className="cursor-pointer text-sm font-semibold text-slate-900 dark:text-white">
                      {aiText('advanced_settings_title', 'Advanced runtime settings')}
                    </summary>
                    <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {aiText('advanced_settings_desc', 'These values are kept for runtime metadata and diagnostics. They do not edit prompts, router rules, abilities, or WordPress writes.')}
                    </p>
                    <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_connection_id', 'Connection ID')}
                        <input
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          value={providerConnectionForm.connectionId}
                          onChange={(event) => updateProviderConnectionForm({ connectionId: event.target.value })}
                          placeholder="openai_primary"
                        />
                      </label>
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_provider_id', 'Provider ID')}
                        <input
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          value={providerConnectionForm.providerId}
                          onChange={(event) => updateProviderConnectionForm({ providerId: event.target.value })}
                          placeholder="openai"
                        />
                      </label>
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_kind', 'Kind')}
                        <select
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          value={providerConnectionForm.kind}
                          onChange={(event) => updateProviderConnectionForm({ kind: event.target.value })}
                        >
                          <option value="openai_compatible">openai_compatible</option>
                          <option value="anthropic">anthropic</option>
                          <option value="litellm_gateway">litellm_gateway</option>
                          <option value="vllm">vllm</option>
                          <option value="tei">tei</option>
                          <option value="openrouter">openrouter</option>
                          <option value="siliconflow">siliconflow</option>
                          <option value="minimax">minimax</option>
                          <option value="audio_provider">audio_provider</option>
                          <option value="web_search_provider">web_search_provider</option>
                          <option value="image_source_provider">image_source_provider</option>
                          <option value="embedding_provider">embedding_provider</option>
                          <option value="rerank_provider">rerank_provider</option>
                          <option value="vector_store_provider">vector_store_provider</option>
                        </select>
                      </label>
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_source_role', 'Source role')}
                        <select
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          value={providerConnectionForm.sourceRole}
                          onChange={(event) => updateProviderConnectionForm({ sourceRole: event.target.value })}
                        >
                          <option value="execution_source">execution_source</option>
                          <option value="runtime_metadata">runtime_metadata</option>
                          <option value="diagnostic_source">diagnostic_source</option>
                        </select>
                      </label>
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_capabilities', 'Capabilities')}
                        <input
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          value={providerConnectionForm.capabilityIds}
                          onChange={(event) => updateProviderConnectionForm({ capabilityIds: event.target.value })}
                          placeholder="text_generation, image_generation"
                        />
                      </label>
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_profiles', 'Profiles')}
                        <input
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          value={providerConnectionForm.runtimeProfileIds}
                          onChange={(event) => updateProviderConnectionForm({ runtimeProfileIds: event.target.value })}
                          placeholder="text.ai"
                        />
                      </label>
                    </div>
                  </details>
                ) : null}
                </div>
                <div className="flex flex-col gap-3 border-t border-slate-200 bg-white px-5 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between">
                  <span>{aiText('save_test_notice', 'Saving will immediately run a masked provider test. Secrets are never returned to the browser.')}</span>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={savingConnection}
                      onClick={() => setProviderFormOpen(false)}
                    >
                      {aiText('action_cancel', 'Cancel')}
                    </button>
                    <button
                      type="submit"
                      disabled={savingConnection}
                      className="btn btn-primary justify-center disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {savingConnection ? aiText('saving', 'Saving...') : aiText('action_save_and_test_connection', 'Save and test provider')}
                    </button>
                  </div>
                </div>
              </form>
            </div>
          </div>
        ) : null}
        <div className="mt-4 space-y-4">
          {[
            {
              id: 'ai',
              connections: aiSupplierConnections,
              empty: aiText('ai_suppliers_empty', 'No model suppliers match the current filters.'),
            },
          ].map((supplierGroup) => (
            <div key={supplierGroup.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
              <div className="overflow-x-auto">
                <table className="min-w-[760px] w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                    <tr>
                      <th className="px-4 py-3">
                        <select
                          className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold normal-case tracking-normal text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200"
                          value={connectionStatusFilter}
                          onChange={(event) => setConnectionStatusFilter(event.target.value as ConnectionStatusFilter)}
                          aria-label={aiText('status_filter_label', 'Status')}
                        >
                          <option value="all">{aiText('filter_all', 'All')}</option>
                          <option value="ready">{aiText('filter_ready', 'Ready')}</option>
                          <option value="missing_secret">{aiText('filter_missing_secret', 'Missing secret')}</option>
                          <option value="disabled">{aiText('filter_disabled', 'Disabled')}</option>
                        </select>
                      </th>
                      <th className="px-4 py-3">{aiText('column_provider', 'Provider')}</th>
                      <th className="px-4 py-3">{aiText('column_enabled_models', 'Enabled models')}</th>
                      <th className="px-4 py-3">{aiText('last_test', 'Last test')}</th>
                      <th className="px-4 py-3 text-right">{aiText('column_actions', 'Actions')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                    {supplierGroup.connections.map((connection) => {
                      const category = supplierCategory(connection);
                      const isAiSupplier = category === 'ai';
                      const testResult = connectionTestResults[connection.connection_id];
                      const isDeleting = deletingConnectionId === connection.connection_id;
                      const modelIds = connection.model_ids || [];
                      return (
                        <tr key={connection.connection_id} className="align-top">
                          <td className="px-4 py-4">
                            <BackofficeStatusBadge
                              label={resourceStatusLabel(connection.status)}
                              status={statusTone(connection.status)}
                              className={connection.status === 'ready' ? QUIET_STATUS_BADGE_CLASS : undefined}
                            />
                          </td>
                          <td className="px-4 py-4">
                            <div className="font-semibold text-slate-950 dark:text-white">{connection.display_name}</div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {connection.provider_id} · {providerKindLabel(connection.kind)}
                            </div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {aiText('channel_priority_summary', 'Priority {{priority}}', {
                                priority: String(connection.priority ?? 100),
                              })}
                              {connection.note ? ` · ${connection.note}` : ''}
                            </div>
                            {renderConnectionIssue(connection)}
                          </td>
                          <td className="px-4 py-4 text-slate-600 dark:text-slate-300">
                            <div className="font-semibold text-slate-900 dark:text-white">
                              {modelIds.length
                                ? aiText('model_catalog_enabled_count', '{{count}} enabled models', { count: String(modelIds.length) })
                                : aiText('model_catalog_none_enabled', 'No enabled models')}
                            </div>
                          </td>
                          <td className="max-w-[18rem] px-4 py-4 text-slate-600 dark:text-slate-300">
                            {testResult ? (
                              <div className="grid gap-1">
                                <div className="flex items-center gap-2">
                                  <BackofficeStatusBadge label={resourceStatusLabel(testResult.status)} status={testResult.ok ? 'success' : 'warning'} />
                                  <span className="text-xs text-slate-500 dark:text-slate-400">{providerTestStageLabel(testResult.stage)}</span>
                                </div>
                                <div className="text-xs leading-5">{providerTestMessage(testResult)}</div>
                                {testResult.catalog?.model_count ? (
                                  <div className="text-xs text-slate-500 dark:text-slate-400">
                                    {aiText('catalog_models', 'Catalog models')}: {testResult.catalog.model_count} · {labelList(testResult.catalog.sample_model_ids || [])}
                                  </div>
                                ) : null}
                              </div>
                            ) : connection.last_tested_at ? (
                              <div className="grid gap-1">
                                <div className="text-xs text-slate-500 dark:text-slate-400">
                                  {formatDate(connection.last_tested_at)}
                                </div>
                                {connection.last_error_code ? (
                                  <div className="text-xs leading-5 text-amber-700 dark:text-amber-300">
                                    {connection.last_error_code}
                                  </div>
                                ) : null}
                              </div>
                            ) : (
                              <span className="text-slate-400 dark:text-slate-500">-</span>
                            )}
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex flex-wrap justify-end gap-2">
                              {isAiSupplier ? (
                                <button
                                  type="button"
                                  className="btn btn-secondary"
                                  disabled={isDeleting}
                                  onClick={() => editProviderConnection(connection)}
                                >
                                  {aiText('action_configure', 'Configure')}
                                </button>
                              ) : null}
                              {connection.managed_by === 'cloud_provider_connections' ? (
                                <button
                                  type="button"
                                  className="rounded-full border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 transition hover:border-rose-300 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-900 dark:bg-slate-950 dark:text-rose-300 dark:hover:border-rose-800 dark:hover:bg-rose-950/20"
                                  disabled={isDeleting}
                                  onClick={() => {
                                    void deleteProviderConnection(connection);
                                  }}
                                >
                                  {isDeleting ? aiText('deleting', 'Deleting...') : aiText('action_delete', 'Delete')}
                                </button>
                              ) : null}
                              {!isAiSupplier && connection.detail_href ? (
                                <Link href={connection.detail_href} className="btn btn-secondary">
                                  {aiText('action_open_config', 'Open config')}
                                </Link>
                              ) : null}
                              {!isAiSupplier && !connection.detail_href ? (
                                <span className="text-sm text-slate-400 dark:text-slate-500">-</span>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {supplierGroup.connections.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
                          {supplierGroup.empty}
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
          </>
        ) : (
          <div className="mt-4 space-y-4">
            <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
              <div className="overflow-x-auto">
                <table className="min-w-[960px] w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                    <tr>
                      <th className="px-4 py-3">{aiText('column_provider', 'Provider')}</th>
                      <th className="px-4 py-3">
                        <select
                          className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold normal-case tracking-normal text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200"
                          value={capabilityCategoryFilter}
                          onChange={(event) => setCapabilityCategoryFilter(event.target.value as CapabilityProviderCategoryFilter)}
                          aria-label={aiText('capability_category_filter', 'Capability category')}
                        >
                          <option value="all">{aiText('filter_all', 'All')}</option>
                          {(['search', 'image', 'vector'] as CapabilityProviderCategory[]).map((category) => (
                            <option key={category} value={category}>
                              {capabilityCategoryLabel(category)} · {capabilityConnectionsByCategory[category].length}
                            </option>
                          ))}
                        </select>
                      </th>
                      <th className="px-4 py-3">
                        <select
                          className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold normal-case tracking-normal text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200"
                          value={connectionStatusFilter}
                          onChange={(event) => setConnectionStatusFilter(event.target.value as ConnectionStatusFilter)}
                          aria-label={aiText('status_filter_label', 'Status')}
                        >
                          <option value="all">{aiText('filter_all', 'All')}</option>
                          <option value="ready">{aiText('filter_ready', 'Ready')}</option>
                          <option value="missing_secret">{aiText('filter_missing_secret', 'Missing secret')}</option>
                          <option value="disabled">{aiText('filter_disabled', 'Disabled')}</option>
                        </select>
                      </th>
                      <th className="px-4 py-3">{aiText('column_connection', 'Connection')}</th>
                      <th className="px-4 py-3">{aiText('last_test', 'Last test')}</th>
                      <th className="px-4 py-3 text-right">{aiText('column_actions', 'Actions')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                    {activeCapabilityConnections.map((connection) => {
                      const category = capabilityProviderCategory(connection);
                      const testResult = connectionTestResults[connection.connection_id];
                      const isTesting = testingConnectionId === connection.connection_id;
                      const isDeleting = deletingConnectionId === connection.connection_id;
                      const canTestConnection = connection.managed_by === 'cloud_provider_connections';
                      const channelCount = capabilityChannelCounts.get(`${connection.kind}:${connection.provider_id}`) || 0;
                      const showPriority = channelCount > 1 || Number(connection.priority ?? 100) !== 100;
                      return (
                        <tr key={connection.connection_id} className="align-top">
                          <td className="px-4 py-4 align-middle">
                            <div className="font-semibold text-slate-950 dark:text-white">{connection.display_name}</div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {capabilityProviderPurposeLabel(connection)}
                            </div>
                          </td>
                          <td className="px-4 py-4 align-middle text-xs font-semibold text-slate-600 dark:text-slate-300">
                            {capabilityCategoryLabel(category)}
                          </td>
                          <td className="px-4 py-4 align-middle">
                            <BackofficeStatusBadge
                              label={resourceStatusLabel(connection.status)}
                              status={statusTone(connection.status)}
                              className={connection.status === 'ready' ? QUIET_STATUS_BADGE_CLASS : undefined}
                            />
                          </td>
                          <td className="px-4 py-4 align-middle">
                            <div className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                              <span className={connection.enabled ? 'text-slate-500 dark:text-slate-400' : 'font-semibold text-slate-500 dark:text-slate-400'}>
                                {connection.enabled ? aiText('field_enabled', 'Enabled') : aiText('status_disabled_label', 'Disabled')}
                              </span>
                              <span className="mx-1 text-slate-300 dark:text-slate-700">·</span>
                              <span className={connection.configured ? 'text-slate-500 dark:text-slate-400' : 'font-semibold text-amber-700 dark:text-amber-300'}>
                                {connection.configured ? aiText('status_configured_label', 'Configured') : aiText('status_missing_secret_label', 'Missing secret')}
                              </span>
                              {showPriority ? (
                                <>
                                  <span className="mx-1 text-slate-300 dark:text-slate-700">·</span>
                                  <span className={Number(connection.priority ?? 100) === 100 ? 'text-slate-400 dark:text-slate-500' : 'font-semibold text-slate-600 dark:text-slate-300'}>
                                    {aiText('channel_priority_summary', 'Priority {{priority}}', {
                                      priority: String(connection.priority ?? 100),
                                    })}
                                  </span>
                                </>
                              ) : null}
                              {connection.note ? (
                                <div className="mt-1 max-w-[16rem] truncate text-slate-400 dark:text-slate-500">
                                  {connection.note}
                                </div>
                              ) : null}
                            </div>
                          </td>
                          <td className="max-w-[18rem] px-4 py-4 align-middle text-slate-600 dark:text-slate-300">
                            {testResult ? (
                              <div className="grid gap-1">
                                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                                  <span
                                    className={`h-1.5 w-1.5 rounded-full ${
                                      testResult.ok ? 'bg-emerald-500' : 'bg-amber-500'
                                    }`}
                                    aria-hidden="true"
                                  />
                                  <span className={testResult.ok ? 'font-semibold text-slate-700 dark:text-slate-200' : 'font-semibold text-amber-700 dark:text-amber-300'}>
                                    {testResult.ok ? aiText('test_passed', 'Passed') : resourceStatusLabel(testResult.status)}
                                  </span>
                                  <span className="text-slate-300 dark:text-slate-700">·</span>
                                  <span className="text-slate-500 dark:text-slate-400">{formatDate(testResult.tested_at)}</span>
                                  <span className="text-slate-300 dark:text-slate-700">·</span>
                                  <span className="text-slate-500 dark:text-slate-400">{providerTestStageLabel(testResult.stage)}</span>
                                </div>
                                {!testResult.ok ? (
                                  <div className="text-xs leading-5 text-amber-700 dark:text-amber-300">{providerTestMessage(testResult)}</div>
                                ) : null}
                              </div>
                            ) : connection.last_tested_at ? (
                              <div className="grid gap-1">
                                {connection.last_error_code ? (
                                  <div className="text-xs leading-5 text-amber-700 dark:text-amber-300">
                                    {aiText('test_failed', 'Failed')} · {formatDate(connection.last_tested_at)} · {connection.last_error_code}
                                  </div>
                                ) : (
                                  <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
                                    <span className="font-semibold text-slate-700 dark:text-slate-200">{aiText('test_passed', 'Passed')}</span>
                                    <span className="text-slate-300 dark:text-slate-700">·</span>
                                    <span>{formatDate(connection.last_tested_at)}</span>
                                  </div>
                                )}
                              </div>
                            ) : (
                              <span className="text-slate-400 dark:text-slate-500">-</span>
                            )}
                          </td>
                          <td className="px-4 py-4 align-middle">
                            <div className="flex flex-wrap justify-end gap-2">
                              {canTestConnection ? (
                                <button
                                  type="button"
                                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700"
                                  disabled={isTesting || isDeleting}
                                  onClick={() => {
                                    void runProviderConnectionTest(connection.connection_id);
                                  }}
                                >
                                  {isTesting ? aiText('testing', 'Testing...') : aiText('action_test', 'Test')}
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700"
                                disabled={isDeleting}
                                onClick={() => {
                                  setActiveCapabilityCategory(category);
                                  if (connection.managed_by === 'cloud_provider_connections') {
                                    editProviderConnection(connection);
                                    return;
                                  }
                                  const template = CAPABILITY_PROVIDER_TEMPLATES.find(
                                    (item) => item.category === category && item.id === connection.provider_id
                                  );
                                  if (template) {
                                    openCapabilityProviderTemplate(template);
                                    return;
                                  }
                                  editProviderConnection(connection);
                                }}
                              >
                                {aiText('action_configure', 'Configure')}
                              </button>
                              {connection.managed_by === 'cloud_provider_connections' ? (
                                <button
                                  type="button"
                                  className="rounded-full border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 transition hover:border-rose-300 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-900 dark:bg-slate-950 dark:text-rose-300 dark:hover:border-rose-800 dark:hover:bg-rose-950/20"
                                  disabled={isDeleting}
                                  onClick={() => {
                                    void deleteProviderConnection(connection);
                                  }}
                                >
                                  {isDeleting ? aiText('deleting', 'Deleting...') : aiText('action_delete', 'Delete')}
                                </button>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {activeCapabilityConnections.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
                          {aiText('capability_category_empty', 'No suppliers match the current category and filters.')}
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
            {capabilityAddDialogOpen ? (
              <div
                className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/45 px-4 py-6 backdrop-blur-sm sm:py-10"
                role="dialog"
                aria-modal="true"
                aria-labelledby="capability-provider-dialog-title"
              >
                <div className="max-h-[calc(100vh-4rem)] w-full max-w-4xl overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-800 dark:bg-slate-950">
                  <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 dark:border-slate-800 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 id="capability-provider-dialog-title" className="text-base font-semibold text-slate-950 dark:text-white">
                          {aiText('capability_add_dialog_title', 'Choose built-in capability supplier')}
                        </h3>
                        <BackofficeStatusBadge label={aiText('badge_builtin_template', 'Built-in template')} status="info" />
                      </div>
                      <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                        {aiText('capability_add_dialog_desc', 'Existing suppliers are not duplicated. Choosing a template opens its current configuration.')}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn btn-secondary justify-center"
                      onClick={() => setCapabilityAddDialogOpen(false)}
                    >
                      {aiText('action_close_dialog', 'Close')}
                    </button>
                  </div>
                  <div
                    className="mt-4 flex flex-wrap gap-2"
                    role="tablist"
                    aria-label={aiText('capability_add_category_tabs', 'Capability supplier categories')}
                  >
                    {(['search', 'image', 'vector'] as Array<CapabilityProviderTemplate['category']>).map((category) => (
                      <button
                        key={category}
                        type="button"
                        role="tab"
                        aria-selected={activeCapabilityCategory === category}
                        className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${
                          activeCapabilityCategory === category
                            ? 'border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950'
                            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700'
                        }`}
                        onClick={() => setActiveCapabilityCategory(category)}
                      >
                        {capabilityCategoryLabel(category)} · {CAPABILITY_PROVIDER_TEMPLATES.filter((template) => template.category === category).length}
                      </button>
                    ))}
                  </div>
                  <div className="mt-4 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <h4 className="text-sm font-semibold text-slate-950 dark:text-white">
                        {capabilityCategoryLabel(activeCapabilityCategory)}
                      </h4>
                      <BackofficeStatusBadge
                        label={aiText('capability_add_active_category_count', '{{count}} templates', {
                          count: String(visibleCapabilityTemplates.length),
                        })}
                        status="info"
                      />
                    </div>
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      {visibleCapabilityTemplates.map((template) => (
                        <button
                          key={template.id}
                          type="button"
                          className="rounded-lg border border-slate-200 p-3 text-left transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-slate-700 dark:hover:bg-slate-900/45"
                          onClick={() => openCapabilityProviderTemplate(template)}
                        >
                          <div className="font-semibold text-slate-950 dark:text-white">{template.label}</div>
                          <div className="mt-1 text-sm leading-5 text-slate-600 dark:text-slate-300">
                            {aiText(template.descriptionKey, template.descriptionFallback)}
                          </div>
                        </button>
                      ))}
                      {visibleCapabilityTemplates.length === 0 ? (
                        <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
                          {aiText('capability_add_empty_category', 'No built-in templates in this category.')}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        )}
          </BackofficeSectionPanel>
        </>
      ) : null}

      {activeView === 'ability_models' ? (
        <>
        <BackofficeSectionPanel>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
                {aiText('ability_models_title', 'Ability-model routing')}
              </h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {aiText('ability_models_desc', 'WordPress AI connector abilities mapped to Cloud runtime profiles and model instances. Local plugin enablement and WordPress writes stay outside this page.')}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn btn-secondary justify-center"
                disabled={loadingRouting}
                onClick={() => void loadRouting()}
              >
                {loadingRouting ? aiText('loading', 'Loading...') : aiText('action_refresh', 'Refresh')}
              </button>
            </div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-4">
            <BackofficeStackCard>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                {aiText('ability_models_metric_abilities', 'Abilities')}
              </div>
              <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">{abilityModelRows.length}</div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {aiText('ability_models_metric_abilities_detail', 'WordPress AI connector tasks')}
              </div>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                {aiText('ability_models_metric_profiles', 'Profiles')}
              </div>
              <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">{routingDrafts.length}</div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {aiText('ability_models_metric_profiles_detail', 'Shared runtime routing groups')}
              </div>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                {aiText('ability_models_metric_text_instances', 'Text models')}
              </div>
              <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">
                {routingData?.available_text_instances.length || 0}
              </div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {aiText('ability_models_metric_text_instances_detail', 'Available text runtime instances')}
              </div>
            </BackofficeStackCard>
            <BackofficeStackCard>
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                {aiText('ability_models_metric_image_instances', 'Image models')}
              </div>
              <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">
                {routingData?.available_image_instances.length || 0}
              </div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {aiText('ability_models_metric_image_instances_detail', 'Available image runtime instances')}
              </div>
            </BackofficeStackCard>
          </div>
          <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
            <div className="grid grid-cols-[8rem_1.4fr_1fr_1.4fr_8rem_8rem] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
              <span>{aiText('column_status', 'Status')}</span>
              <span>{aiText('column_ability', 'Ability')}</span>
              <span>{aiText('column_profile', 'Profile')}</span>
              <span>{aiText('column_provider_model', 'Provider / model')}</span>
              <span>{aiText('column_fallback', 'Fallback')}</span>
              <span className="text-right">{aiText('column_actions', 'Actions')}</span>
            </div>
            {abilityModelRows.map((row) => (
              <div
                key={`${row.profile.profile_id}-${row.taskId}`}
                className="grid grid-cols-[8rem_1.4fr_1fr_1.4fr_8rem_8rem] gap-3 border-b border-slate-200 px-4 py-3 text-sm last:border-b-0 dark:border-slate-800"
              >
                <BackofficeStatusBadge
                  label={row.primaryInstance ? aiText('status_ready', 'Ready') : aiText('status_missing', 'Missing')}
                  status={row.primaryInstance ? 'success' : 'warning'}
                />
                <div>
                  <div className="font-medium text-slate-950 dark:text-white">{row.label}</div>
                  <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{row.description}</div>
                </div>
                <div className="text-slate-600 dark:text-slate-300">
                  <div>{row.profile.label}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{row.profile.profile_id}</div>
                </div>
                <div className="text-slate-600 dark:text-slate-300">
                  <div>{row.primaryInstance?.provider_id || '-'}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {row.primaryInstance?.model_id || '-'}
                  </div>
                </div>
                <div className="text-slate-600 dark:text-slate-300">
                  {row.fallbackCount
                    ? aiText('fallback_count', '{{count}} fallback', { count: String(row.fallbackCount) })
                    : aiText('fallback_none', 'None')}
                </div>
                <div className="text-right">
                  <button
                    type="button"
                    className="btn btn-secondary justify-center"
                    onClick={() => openAbilityModelDialog(row.profile.profile_id)}
                  >
                    {aiText('action_configure', 'Configure')}
                  </button>
                </div>
              </div>
            ))}
            {abilityModelRows.length ? null : (
              <div className="px-4 py-6 text-sm text-slate-500 dark:text-slate-400">
                {loadingRouting
                  ? aiText('ability_models_loading', 'Loading ability-model routing...')
                  : aiText('ability_models_empty', 'No WordPress AI connector abilities are available.')}
              </div>
            )}
          </div>
          <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {aiText('ability_models_boundary_notice', 'This changes Cloud runtime profile bindings only. It does not enable plugin abilities, edit prompts, or write to WordPress.')}
          </div>
        </BackofficeSectionPanel>
        </>
      ) : null}

      {activeDiagnosticView === 'usage' ? (
        <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('usage_title', 'Feature usage')}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {aiText('usage_desc', 'Feature-to-model evidence from Cloud runtime metadata. Prompt text, result content, and provider secrets are not exposed.')}
        </p>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1.1fr_8rem_1fr_1.2fr_1fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>{aiText('column_feature', 'Feature')}</span>
            <span>{aiText('column_status', 'Status')}</span>
            <span>{aiText('column_profile', 'Profile')}</span>
            <span>{aiText('column_provider_model', 'Provider / model')}</span>
            <span>{aiText('column_last_run', 'Last run')}</span>
            <span>{aiText('column_cost_latency', 'Cost / latency')}</span>
          </div>
          {(data.feature_model_usage || []).map((row) => (
            <div
              key={row.feature_id}
              className="grid grid-cols-[1.1fr_8rem_1fr_1.2fr_1fr_1fr] gap-3 border-b border-slate-200 px-4 py-3 text-sm last:border-b-0 dark:border-slate-800"
            >
              <div>
                <div className="font-medium text-slate-950 dark:text-white">{row.label}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {row.surface} · {row.write_posture}
                </div>
              </div>
              <BackofficeStatusBadge label={row.status} status={statusTone(row.status)} />
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.profile_id || '-'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{row.selection_owner}</div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.provider_id || '-'} / {row.model_id || '-'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {labelList(row.connection_ids)} · {labelList(row.connection_sources)}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.last_run?.status || aiText('status_not_observed', 'not observed')}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {row.last_run?.run_id || '-'}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{aiText('credits_value', '{{value}} credits', { value: formatCost(row.last_provider_call?.cost) })}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {row.last_provider_call?.latency_ms ? `${row.last_provider_call.latency_ms}ms` : '-'}
                  {row.last_provider_call?.error_code ? ` · ${row.last_provider_call.error_code}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
          {aiText('usage_evidence_notice', 'Evidence source: run_records and provider_call_records. This view is read-only and does not change routing, prompts, abilities, or WordPress writes.')}
        </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeDiagnosticView === 'health' ? (
        <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('health_title', 'Model health')}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {aiText('health_desc', 'Provider/model health from provider_call_records. Metadata only: prompts, results, and provider secrets are not exposed.')}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {healthWindows.map((windowItem) => (
            <BackofficeFilterPill
              key={windowItem.window_id}
              active={activeHealthWindow?.window_id === windowItem.window_id}
              onClick={() => setActiveHealthWindowId(windowItem.window_id)}
            >
              {healthWindowLabel(windowItem)}
            </BackofficeFilterPill>
          ))}
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-4">
          <BackofficeStackCard>
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{aiText('health_alerts', 'Alerts')}</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">
              {activeHealthWindow?.alert_summary?.alert_count || 0}
            </div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{aiText('health_readonly_diagnostics', 'read-only diagnostics')}</div>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{aiText('health_errors', 'Errors')}</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">
              {activeHealthWindow?.alert_summary?.severity_counts?.error || 0}
            </div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{aiText('health_all_calls_failed', 'all calls failed')}</div>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{aiText('health_warnings', 'Warnings')}</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">
              {activeHealthWindow?.alert_summary?.severity_counts?.warning || 0}
            </div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{aiText('health_warning_detail', 'latency, success, or cost')}</div>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{aiText('health_window', 'Window')}</div>
            <div className="mt-2 text-2xl font-semibold text-slate-950 dark:text-white">
              {activeHealthWindow?.hours || 24}h
            </div>
            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {aiText('health_call_limit', 'limit {{count}} calls', { count: String(data.provider_model_health?.recent_call_limit || 200) })}
            </div>
          </BackofficeStackCard>
        </div>
        {activeHealthWindow?.alert_summary?.alerts?.length ? (
          <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
            <div className="grid grid-cols-[8rem_1fr_1fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
              <span>{aiText('column_severity', 'Severity')}</span>
              <span>{aiText('column_provider_model', 'Provider / model')}</span>
              <span>{aiText('column_signal', 'Signal')}</span>
              <span>{aiText('column_evidence', 'Evidence')}</span>
            </div>
            {activeHealthWindow.alert_summary.alerts.map((alert, index) => (
              <div
                key={`${alert.code}-${alert.provider_id}-${alert.model_id}-${index}`}
                className="grid grid-cols-[8rem_1fr_1fr_1fr] gap-3 border-b border-slate-200 px-4 py-3 text-sm last:border-b-0 dark:border-slate-800"
              >
                <BackofficeStatusBadge label={alert.severity} status={severityTone(alert.severity)} />
                <div className="text-slate-600 dark:text-slate-300">
                  <div>{alert.provider_id || '-'}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{alert.model_id || '-'}</div>
                </div>
                <div className="text-slate-600 dark:text-slate-300">
                  <div>{alert.code}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{alert.message}</div>
                </div>
                <div className="text-slate-600 dark:text-slate-300">
                  <div>{aiText('success_rate_value', '{{value}} success', { value: formatRate(alert.evidence?.success_rate) })}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {alert.evidence?.p95_latency_ms ? `${alert.evidence.p95_latency_ms}ms p95` : '-'} · {aiText('credits_value', '{{value}} credits', { value: formatCost(alert.evidence?.cost) })}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1.2fr_8rem_1fr_1fr_1fr_1.2fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>{aiText('column_provider_model', 'Provider / model')}</span>
            <span>{aiText('column_status', 'Status')}</span>
            <span>{aiText('column_calls', 'Calls')}</span>
            <span>{aiText('column_latency', 'Latency')}</span>
            <span>{aiText('column_tokens_cost', 'Tokens / cost')}</span>
            <span>{aiText('column_last_error', 'Last error')}</span>
          </div>
          {(activeHealthWindow?.rows || []).map((row) => (
            <div
              key={`${row.provider_id}-${row.model_id}`}
              className="grid grid-cols-[1.2fr_8rem_1fr_1fr_1fr_1.2fr] gap-3 border-b border-slate-200 px-4 py-3 text-sm last:border-b-0 dark:border-slate-800"
            >
              <div>
                <div className="font-medium text-slate-950 dark:text-white">{row.provider_id || '-'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{row.model_id || '-'}</div>
              </div>
              <BackofficeStatusBadge label={row.status} status={healthTone(row.status)} />
              <div className="text-slate-600 dark:text-slate-300">
                <div>{aiText('calls_rate_value', '{{calls}} calls · {{rate}}', {
                  calls: String(row.call_count),
                  rate: formatRate(row.success_rate),
                })}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {aiText('ok_errors_value', '{{ok}} ok · {{errors}} errors', {
                    ok: String(row.success_count),
                    errors: String(row.error_count),
                  })}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{typeof row.avg_latency_ms === 'number' ? `${row.avg_latency_ms}ms avg` : '-'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {typeof row.p95_latency_ms === 'number' ? `${row.p95_latency_ms}ms p95` : '-'}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{aiText('tokens_value', '{{count}} tokens', { count: String(row.tokens_in + row.tokens_out) })}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {aiText('health_cost_retry_fallback', '{{cost}} credits · {{retries}} retries · {{fallback}} fallback', {
                    cost: formatCost(row.cost),
                    retries: String(row.retry_count),
                    fallback: String(row.fallback_count),
                  })}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.last_error_code || '-'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {row.last_observed_at || '-'}
                </div>
              </div>
            </div>
          ))}
          {activeHealthWindow?.rows?.length ? null : (
            <div className="px-4 py-6 text-sm text-slate-500 dark:text-slate-400">
              {aiText('health_empty', 'No provider call records observed in the current evidence window.')}
            </div>
          )}
        </div>
        <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
          {aiText('health_evidence_notice', 'Evidence source: {{source}}; recent call limit {{limit}}. Health alerts are diagnostic only and do not change routing, prompts, abilities, or WordPress writes.', {
            source: data.provider_model_health?.source || 'provider_call_records',
            limit: String(data.provider_model_health?.recent_call_limit || 200),
          })}
        </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeDiagnosticView === 'matrix' ? (
        <>
          <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('runtime_resolution_title', 'Runtime resolution')}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {aiText('runtime_resolution_desc', 'Current Cloud runtime resolution by capability. This is read-only operator evidence, not a router editor.')}
        </p>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1fr_8rem_1fr_1.2fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>{aiText('column_capability', 'Capability')}</span>
            <span>{aiText('column_status', 'Status')}</span>
            <span>{aiText('column_profile', 'Profile')}</span>
            <span>{aiText('column_provider_model', 'Provider / model')}</span>
            <span>{aiText('column_connections', 'Connections')}</span>
          </div>
          {runtimeResolutionRows.map((row) => (
            <div
              key={`runtime-resolution-${row.capability_id}`}
              className="grid grid-cols-[1fr_8rem_1fr_1.2fr_1fr] gap-3 border-b border-slate-200 px-4 py-3 text-sm last:border-b-0 dark:border-slate-800"
            >
              <div>
                <div className="font-medium text-slate-950 dark:text-white">{row.label}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {row.write_posture}
                </div>
              </div>
              <BackofficeStatusBadge label={row.status} status={statusTone(row.status)} />
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.selected_profile_id || '-'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{row.selection_owner}</div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.selected_provider_id || '-'} / {row.selected_model_id || '-'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {aiText('adapter_status', 'adapter {{status}}', {
                    status: row.runtime_provider_available ? aiText('status_available', 'available') : aiText('status_not_loaded', 'not loaded'),
                  })}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{labelList(row.ready_connection_ids)}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {aiText('selected_connections', 'selected {{connections}}', { connections: labelList(row.selected_connection_ids) })}
                </div>
              </div>
            </div>
          ))}
        </div>
          </BackofficeSectionPanel>

          <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('matrix_title', 'Capability Matrix')}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {aiText('matrix_desc', 'Cloud runtime mapping from capability to profile, provider, model, and write posture. This is operator detail, not a WordPress ability editor.')}
        </p>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1fr_8rem_1.1fr_1.2fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>{aiText('column_capability', 'Capability')}</span>
            <span>{aiText('column_status', 'Status')}</span>
            <span>{aiText('column_profiles', 'Profiles')}</span>
            <span>{aiText('column_provider_model', 'Provider / model')}</span>
            <span>{aiText('column_write_posture', 'Write posture')}</span>
          </div>
          {matrixRows.map((row) => (
            <div
              key={row.capability_id}
              className="grid grid-cols-[1fr_8rem_1.1fr_1.2fr_1fr] gap-3 border-b border-slate-200 px-4 py-3 text-sm last:border-b-0 dark:border-slate-800"
            >
              <div>
                <div className="font-medium text-slate-950 dark:text-white">{row.label}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {labelList(row.used_by)}
                </div>
              </div>
              <BackofficeStatusBadge label={row.status} status={statusTone(row.status)} />
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.default_profile_id}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{profileIds(row.profiles)}</div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">{profileModelSummary(row.profiles)}</div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.write_posture}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{row.selection_owner}</div>
              </div>
            </div>
          ))}
        </div>
          </BackofficeSectionPanel>

          <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('runtime_profiles_title', 'Runtime profiles')}</h2>
        <div className="mt-4 grid gap-3">
          {data.runtime_profiles.map((profile) => (
            <BackofficeStackCard key={profile.profile_id} className="grid gap-3 lg:grid-cols-[1fr_9rem_1.2fr_1fr] lg:items-center">
              <div>
                <div className="font-semibold text-slate-950 dark:text-white">{profile.profile_id}</div>
                <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {profile.kind} · {labelList(profile.used_by)}
                  {profile.selected_for?.length ? ` · ${aiText('selected_for', 'selected for {{values}}', { values: labelList(profile.selected_for) })}` : ''}
                </div>
              </div>
              <BackofficeStatusBadge label={profile.status} status={statusTone(profile.status)} />
              <div className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {profile.selected_provider_id} / {profile.selected_model_id}
              </div>
              <div className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {profile.selection_owner}
              </div>
            </BackofficeStackCard>
          ))}
        </div>
          </BackofficeSectionPanel>

          <BackofficeSectionPanel>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('recent_evidence_title', 'Recent runtime evidence')}</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {aiText('recent_evidence_desc', 'Last observed run metadata for each profile. Prompt and result content are not exposed here.')}
            </p>
          </div>
          <BackofficeStatusBadge
            label={data.recent_runtime_evidence?.content_exposed ? aiText('status_review', 'Review') : aiText('status_metadata_only', 'Metadata only')}
            status={data.recent_runtime_evidence?.content_exposed ? 'warning' : 'success'}
          />
        </div>
        <div className="mt-4 grid gap-3">
          {data.runtime_profiles.map((profile) => {
            const evidence = evidenceSummary(profile);
            return (
              <BackofficeStackCard key={`evidence-${profile.profile_id}`} className="grid gap-3 lg:grid-cols-[1fr_8rem_1.2fr_1fr] lg:items-center">
                <div>
                  <div className="font-semibold text-slate-950 dark:text-white">{profile.profile_id}</div>
                  <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {evidence?.run_id || aiText('no_recent_run', 'No recent run')}
                  </div>
                </div>
                <BackofficeStatusBadge
                  label={evidence?.status || aiText('status_not_observed', 'not observed')}
                  status={evidence?.status === 'failed' ? 'error' : evidence?.status === 'succeeded' ? 'success' : 'disabled'}
                />
                <div className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {evidence?.provider_id || '-'} / {evidence?.model_id || '-'}
                </div>
                <div className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {evidence?.trace_id || '-'}
                </div>
              </BackofficeStackCard>
            );
          })}
        </div>
          </BackofficeSectionPanel>
        </>
      ) : null}
      {activeAbilityModelProfile && typeof document !== 'undefined' ? createPortal((
        <div
          className="fixed inset-0 z-[2147483647] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="ability-model-dialog-title"
        >
          <div className="absolute inset-0 bg-slate-950/55" />
          <div className="relative z-10 max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-950">
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 dark:border-slate-800 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 id="ability-model-dialog-title" className="text-xl font-semibold text-slate-950 dark:text-white">
                  {aiText('ability_model_dialog_title', 'Configure ability-model route')}
                </h2>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {aiText('ability_model_dialog_desc', 'This updates one shared Cloud runtime profile. WordPress plugin feature switches and final writes are not changed.')}
                </p>
              </div>
              <button type="button" className="btn btn-secondary" onClick={closeAbilityModelDialog}>
                {aiText('action_close_dialog', 'Close')}
              </button>
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
              <div className="space-y-3">
                <div>
                  <div className="text-base font-semibold text-slate-950 dark:text-white">{activeAbilityModelTitle}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{activeAbilityModelProfile.profile_id}</div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {activeAbilityModelProfile.tasks.map((taskId) => (
                    <span
                      key={taskId}
                      className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300"
                    >
                      {abilityTaskLabel(taskId)}
                    </span>
                  ))}
                </div>
                {[0, 1].map((index) => {
                  const selectedId = activeAbilityModelProfile.candidate_instance_ids[index] || '';
                  const selected = routingInstancesById.get(selectedId);
                  const candidates = routingCandidateInstancesFor(activeAbilityModelProfile);
                  return (
                    <label
                      key={`${activeAbilityModelProfile.profile_id}-${index}`}
                      className="block rounded-xl border border-slate-200 bg-white/70 p-3 dark:border-slate-800 dark:bg-slate-950/40"
                    >
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                        {index === 0 ? aiText('ability_model_primary_model', 'Primary model') : aiText('ability_model_fallback_model', 'Fallback model')}
                      </span>
                      <select
                        value={selectedId}
                        onChange={(event) =>
                          updateRoutingCandidate(activeAbilityModelProfile.profile_id, index, event.target.value)
                        }
                        className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                      >
                        <option value="">{aiText('ability_model_unassigned', 'Unassigned')}</option>
                        {candidates.map((instance) => (
                          <option
                            key={`${activeAbilityModelProfile.profile_id}-${index}-${instance.instance_id}`}
                            value={instance.instance_id}
                          >
                            {instance.provider_id} · {instance.model_id}
                          </option>
                        ))}
                      </select>
                      {selected ? (
                        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                          {abilityModelInstanceDetail(selected)}
                        </p>
                      ) : null}
                    </label>
                  );
                })}
              </div>
              <div className="space-y-3">
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    {aiText('field_timeout_ms', 'Timeout ms')}
                  </span>
                  <input
                    type="number"
                    min={1000}
                    max={activeAbilityModelProfile.max_timeout_ms}
                    step={1000}
                    value={activeAbilityModelProfile.timeout_ms}
                    onChange={(event) =>
                      updateRoutingDraft(activeAbilityModelProfile.profile_id, {
                        timeout_ms: Number(event.target.value) || 30000,
                      })
                    }
                    className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>
                <label className="flex items-center justify-between rounded-xl border border-slate-200 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/40">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {aiText('field_allow_fallback', 'Provider fallback')}
                  </span>
                  <input
                    type="checkbox"
                    checked={activeAbilityModelProfile.allow_fallback}
                    onChange={(event) =>
                      updateRoutingDraft(activeAbilityModelProfile.profile_id, {
                        allow_fallback: event.target.checked,
                      })
                    }
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    {aiText('field_retry_max', 'Retry max')}
                  </span>
                  <select
                    value={activeAbilityModelProfile.max_retries}
                    onChange={(event) =>
                      updateRoutingDraft(activeAbilityModelProfile.profile_id, {
                        max_retries: Number(event.target.value) || 0,
                      })
                    }
                    className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  >
                    <option value={0}>0</option>
                    <option value={1}>1</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    {aiText('field_operator_note', 'Operator note')}
                  </span>
                  <textarea
                    value={activeAbilityModelProfile.note}
                    onChange={(event) =>
                      updateRoutingDraft(activeAbilityModelProfile.profile_id, { note: event.target.value })
                    }
                    rows={3}
                    className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    placeholder={aiText('placeholder_ability_model_note', 'Why this ability-model route is being changed')}
                  />
                </label>
              </div>
            </div>
            <div className="mt-5 grid gap-3 border-t border-slate-200 pt-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
              <div className="grid gap-2">
                <span>
                  {aiText('ability_model_save_notice', 'Saving updates the Cloud runtime routing profile used by this ability group.')}
                </span>
                {abilityModelDialogMessage ? (
                  <span
                    className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200"
                    role="status"
                    aria-live="polite"
                  >
                    {abilityModelDialogMessage}
                  </span>
                ) : null}
                {abilityModelDialogError ? (
                  <span
                    className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200"
                    role="alert"
                  >
                    {abilityModelDialogError}
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={savingRouting}
                  onClick={closeAbilityModelDialog}
                >
                  {aiText('action_cancel', 'Cancel')}
                </button>
                <button
                  type="button"
                  className="btn btn-primary justify-center disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={savingRouting || !activeAbilityModelProfile.candidate_instance_ids.length}
                  onClick={() => void saveAbilityModelProfile(activeAbilityModelProfile.profile_id)}
                >
                  {savingRouting ? aiText('saving', 'Saving...') : aiText('action_save_ability_model', 'Save route')}
                </button>
              </div>
            </div>
          </div>
        </div>
      ), document.body) : null}
    </BackofficePageStack>
  );
}

export default function AiResourcesPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AiResourcesContent />
    </Suspense>
  );
}
