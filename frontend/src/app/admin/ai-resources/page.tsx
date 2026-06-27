'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { generateIdempotencyKey } from '@/lib/idempotency';

type ResourceStatus = 'ready' | 'missing_secret' | 'missing_provider' | 'disabled' | string;
type AIResourceView = 'connections' | 'ability_models' | 'usage' | 'health' | 'matrix' | 'diagnostics';
type ConnectionStatusFilter = 'all' | 'ready' | 'missing_secret' | 'disabled';
type SupplierCategory = 'ai' | 'capability';
type SupplierSettingsTab = 'model' | 'capability';
type CapabilityProviderCategory = 'search' | 'image' | 'vector';
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
  capability_ids: string[];
  runtime_profile_ids: string[];
  model_ids?: string[];
  detail_href?: string;
  managed_by?: string;
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

type ProfilePreferences = {
  env_path: string;
  requires_worker_restart_after_save: boolean;
  audio_summary_text_profile_id: string;
  audio_narration_profile_id: string;
  audio_summary_audio_profile_id: string;
  allowed: {
    text_profile_ids: string[];
    audio_profile_ids: string[];
  };
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
  profile_preferences: ProfilePreferences;
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
    capabilityIds: 'audio_generation',
    runtimeProfileIds: 'audio.narration.default, audio.summary.default',
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
    id: 'siliconflow',
    label: 'SiliconFlow Embedding',
    category: 'vector',
    kind: 'embedding_provider',
    baseUrl: 'https://api.siliconflow.cn/v1',
    capabilityIds: 'embedding',
    runtimeProfileIds: 'embed.default',
    modelIds: 'BAAI/bge-m3',
    descriptionKey: 'vector_help_siliconflow',
    descriptionFallback: 'Embedding provider for Site Knowledge semantic vectors.',
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

function supplierCategory(connection: Connection): SupplierCategory {
  if (
    connection.kind === 'web_search_provider' ||
    connection.kind === 'image_source_provider' ||
    connection.kind === 'embedding_provider' ||
    connection.kind === 'rerank_provider' ||
    connection.kind === 'vector_store_provider' ||
    connection.capability_ids.includes('web_search') ||
    connection.capability_ids.includes('image_source') ||
    connection.capability_ids.includes('embedding') ||
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
  const [preferences, setPreferences] = useState<ProfilePreferences | null>(null);
  const [activeView, setActiveView] = useState<AIResourceView>('connections');
  const [activeSupplierTab, setActiveSupplierTab] = useState<SupplierSettingsTab>('model');
  const [activeDiagnosticsTab, setActiveDiagnosticsTab] = useState<DiagnosticsTab>('matrix');
  const [activeCapabilityCategory, setActiveCapabilityCategory] = useState<CapabilityProviderCategory>('search');
  const [capabilityAddDialogOpen, setCapabilityAddDialogOpen] = useState(false);
  const [activeHealthWindowId, setActiveHealthWindowId] = useState('last_24h');
  const [connectionStatusFilter, setConnectionStatusFilter] = useState<ConnectionStatusFilter>('all');
  const [connectionSearch, setConnectionSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingRouting, setLoadingRouting] = useState(true);
  const [savingPreferences, setSavingPreferences] = useState(false);
  const [savingRouting, setSavingRouting] = useState(false);
  const [savingConnection, setSavingConnection] = useState(false);
  const [, setTestingConnectionId] = useState('');
  const [fetchingProviderCatalog, setFetchingProviderCatalog] = useState(false);
  const [providerCatalogPreview, setProviderCatalogPreview] = useState<ProviderCatalogPreview | null>(null);
  const [connectionTestResults, setConnectionTestResults] = useState<Record<string, ProviderConnectionTestResult>>({});
  const [providerFormOpen, setProviderFormOpen] = useState(false);
  const [providerFormMode, setProviderFormMode] = useState<'create' | 'edit'>('create');
  const [providerConnectionForm, setProviderConnectionForm] = useState<ProviderConnectionForm>(
    EMPTY_PROVIDER_CONNECTION_FORM
  );
  const [customModelInput, setCustomModelInput] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

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
      const normalized = payload.data as AiResources;
      setData(normalized);
      setPreferences(normalized.profile_preferences);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : aiText('error_load', 'Failed to load provider management.'));
    } finally {
      setLoading(false);
    }
  }, [aiText]);

  const loadRouting = useCallback(async () => {
    setLoadingRouting(true);
    setError('');
    try {
      const response = await fetch('/api/admin/wordpress-ai-routing', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_load_ability_models', 'Failed to load ability model routing.')));
      }
      const normalized = normalizeRoutingData(payload.data);
      setRoutingData(normalized);
      setRoutingDrafts(normalized.profiles.map((profile) => ({ ...profile, note: '' })));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : aiText('error_load_ability_models', 'Failed to load ability model routing.'));
    } finally {
      setLoadingRouting(false);
    }
  }, [aiText]);

  useEffect(() => {
    void loadResources();
  }, [loadResources]);

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
    }
  }, [searchParams]);

  async function saveProfilePreferences() {
    if (!preferences) return;
    setSavingPreferences(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/admin/ai-resources/profile-preferences', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audio_summary_text_profile_id: preferences.audio_summary_text_profile_id,
          audio_narration_profile_id: preferences.audio_narration_profile_id,
          audio_summary_audio_profile_id: preferences.audio_summary_audio_profile_id,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_save_preferences', 'Failed to save profile preferences.')));
      }
      const normalized = payload.data as AiResources;
      setData(normalized);
      setPreferences(normalized.profile_preferences);
      setMessage(aiText('message_preferences_saved', 'Profile preferences saved. Restart worker processes for queued runs to pick up the same values.'));
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : aiText('error_save_preferences', 'Failed to save profile preferences.'));
    } finally {
      setSavingPreferences(false);
    }
  }

  async function saveProviderConnection() {
    const normalizedConnectionId = providerConnectionForm.connectionId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.providerId);
    const normalizedProviderId = providerConnectionForm.providerId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.connectionId);
    const modelIds = splitList(providerConnectionForm.modelIds);
    const modelConfig = modelIds.length ? { model_ids: modelIds, model_id: modelIds[0] } : {};
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
          source_role: providerConnectionForm.sourceRole,
          capability_ids: splitList(providerConnectionForm.capabilityIds),
          runtime_profile_ids: splitList(providerConnectionForm.runtimeProfileIds),
          config: modelConfig,
          metadata: {
            ui_source: 'ai_resources_channel_form',
            provider_preset: providerConnectionForm.providerPreset,
            model_ids: modelIds,
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
        setMessage(result?.message || aiText('message_connection_tested', 'Provider connection tested.'));
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
      setAbilityModelDialogError(aiText('error_save_ability_models', 'Failed to save ability model routing.'));
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
            aiText('error_save_ability_models', 'Failed to save ability model routing.')
          )
        );
      }
      const normalized = normalizeRoutingData(payload.data);
      setRoutingData(normalized);
      setRoutingDrafts(normalized.profiles.map((item) => ({ ...item, note: '' })));
      setAbilityModelDialogMessage(aiText('message_ability_models_saved', 'Ability model routing saved.'));
    } catch (saveError) {
      setAbilityModelDialogError(
        saveError instanceof Error ? saveError.message : aiText('error_save_ability_models', 'Failed to save ability model routing.')
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
    setProviderFormOpen(true);
    setProviderCatalogPreview(null);
    setCustomModelInput('');
    setError('');
    setMessage('');
  }

  function editProviderConnection(connection: Connection) {
    setMessage(aiText('message_editing_connection', 'Editing {{name}}. Credential is left blank unless you replace it.', {
      name: connection.display_name,
    }));
    setError('');
    setProviderCatalogPreview(null);
    setCustomModelInput('');
    setProviderFormMode('edit');
    setProviderConnectionForm({
      providerPreset: inferProviderPreset(connection),
      connectionId: connection.connection_id,
      providerId: connection.provider_id,
      displayName: connection.display_name,
      kind: connection.kind,
      baseUrl: connection.base_url || '',
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

  function updatePreferences(patch: Partial<ProfilePreferences>) {
    setPreferences((current) => (current ? { ...current, ...patch } : current));
  }

  function updateProviderConnectionForm(patch: Partial<ProviderConnectionForm>) {
    setProviderConnectionForm((current) => ({ ...current, ...patch }));
    if (patch.kind || patch.baseUrl || patch.credential || patch.providerId) {
      setProviderCatalogPreview(null);
    }
  }

  function setProviderModelIds(modelIds: string[]) {
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
    setProviderCatalogPreview(null);
    setCustomModelInput('');
    setProviderConnectionForm({
      providerPreset: 'custom',
      connectionId: `${template.category}_${template.id}`,
      providerId: template.id,
      displayName: template.label,
      kind: template.kind,
      baseUrl: template.baseUrl,
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

  const metrics = useMemo(() => {
    const connections = data?.connections || [];
    const capabilities = data?.capabilities || [];
    const profiles = data?.runtime_profiles || [];
    return [
      {
        label: aiText('metric_connections', 'Connections'),
        value: connections.filter((item) => item.configured).length,
        detail: aiText('metric_connections_detail', '{{count}} runtime provider entries', { count: String(connections.length) }),
      },
      {
        label: aiText('metric_capabilities', 'Capabilities'),
        value: capabilities.filter((item) => item.status === 'ready').length,
        detail: aiText('metric_capabilities_detail', '{{count}} projected Cloud capabilities', { count: String(capabilities.length) }),
      },
      {
        label: aiText('metric_profiles', 'Profiles'),
        value: profiles.filter((item) => item.status === 'ready').length,
        detail: aiText('metric_profiles_detail', '{{count}} runtime or pipeline profiles', { count: String(profiles.length) }),
      },
      {
        label: aiText('metric_write_posture', 'Write posture'),
        value: data?.boundary?.direct_wordpress_write ? aiText('status_review', 'Review') : aiText('status_no_writes', 'No writes'),
        detail: data?.boundary?.final_writes || 'core_proposal_required',
      },
    ];
  }, [aiText, data]);

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

  const activeCapabilityConnections = capabilityConnectionsByCategory[activeCapabilityCategory];

  const capabilityCategoryLabel = useCallback((category: CapabilityProviderCategory): string => {
    if (category === 'search') return aiText('capability_category_search', 'Search');
    if (category === 'image') return aiText('capability_category_image', 'Images');
    return aiText('capability_category_vector', 'Vector');
  }, [aiText]);

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
    if (normalized === 'image_generation' || normalized === 'image_generations') {
      return aiText('ability_model_feature_image_generation', 'Image generation');
    }
    if (normalized === 'text_generation' || normalized === 'text_generations' || normalized === 'text') {
      return aiText('ability_model_feature_text_generation', 'Text generation');
    }
    if (normalized === 'audio_generation' || normalized === 'audio_generations') {
      return aiText('ability_model_feature_audio_generation', 'Audio generation');
    }
    if (normalized === 'video_generation' || normalized === 'video_generations') {
      return aiText('ability_model_feature_video_generation', 'Video generation');
    }
    return normalized || aiText('ability_model_feature_unknown', 'Unknown');
  }, [aiText]);

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
        description={aiText('description', 'Centralized model supplier, capability supplier, readiness, and profile mapping for Cloud runtime.')}
        aside={(
          <BackofficeStatusBadge
            label={data.boundary.not_a_control_plane ? aiText('badge_runtime_resources', 'Runtime resources') : aiText('badge_review_boundary', 'Review boundary')}
            status={data.boundary.not_a_control_plane ? 'success' : 'warning'}
          />
        )}
        contentClassName="py-5 md:py-5"
        summary={<BackofficeSummaryStrip items={metrics} />}
        summaryClassName="px-5 py-3 md:px-7 md:py-3"
      >
        {message ? (
          <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200">
            {message}
          </BackofficeStackCard>
        ) : null}
        {error ? (
          <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
            {error}
          </BackofficeStackCard>
        ) : null}
      </BackofficePrimaryPanel>

      <div className="flex flex-wrap gap-2">
        <BackofficeFilterPill
          active={activeView === 'connections' && activeSupplierTab === 'model'}
          onClick={() => {
            setActiveView('connections');
            setActiveSupplierTab('model');
          }}
        >
          {aiText('supplier_tab_model', 'Model suppliers')}
        </BackofficeFilterPill>
        <BackofficeFilterPill
          active={activeView === 'connections' && activeSupplierTab === 'capability'}
          onClick={() => {
            setActiveView('connections');
            setActiveSupplierTab('capability');
          }}
        >
          {aiText('supplier_tab_capability', 'Capability suppliers')}
        </BackofficeFilterPill>
        <BackofficeFilterPill
          active={activeView === 'diagnostics'}
          onClick={() => setActiveView('diagnostics')}
        >
          {aiText('tab_diagnostics', 'Diagnostics')}
        </BackofficeFilterPill>
      </div>

      {activeView === 'diagnostics' ? (
        <div className="flex flex-wrap gap-2">
          <BackofficeFilterPill
            active={activeDiagnosticsTab === 'matrix'}
            onClick={() => setActiveDiagnosticsTab('matrix')}
          >
            {aiText('tab_matrix', 'Capability Matrix')}
          </BackofficeFilterPill>
          <BackofficeFilterPill
            active={activeDiagnosticsTab === 'usage'}
            onClick={() => setActiveDiagnosticsTab('usage')}
          >
            {aiText('tab_usage', 'Feature usage')}
          </BackofficeFilterPill>
          <BackofficeFilterPill
            active={activeDiagnosticsTab === 'health'}
            onClick={() => setActiveDiagnosticsTab('health')}
          >
            {aiText('tab_health', 'Model health')}
          </BackofficeFilterPill>
        </div>
      ) : null}

      {activeView === 'connections' ? (
        <>
          <BackofficeSectionPanel>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('connections_title', 'Supplier settings')}</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {aiText('connections_desc', 'Masked provider connection status. Secrets are never returned to the browser.')}
            </p>
          </div>
          {activeSupplierTab === 'model' ? (
            <button type="button" className="btn btn-primary justify-center" onClick={openNewProviderConnection}>
              {aiText('action_add_provider_channel', 'Add provider')}
            </button>
          ) : null}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
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

        {activeSupplierTab === 'model' ? (
          <>
        {providerFormOpen ? (
          <div
            className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/45 px-4 py-6 backdrop-blur-sm sm:py-10"
            role="dialog"
            aria-modal="true"
            aria-labelledby="provider-channel-dialog-title"
          >
            <div className="w-full max-w-5xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-800 dark:bg-slate-950">
              <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 dark:border-slate-800 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 id="provider-channel-dialog-title" className="text-base font-semibold text-slate-950 dark:text-white">
                      {providerFormMode === 'edit'
                        ? aiText('channel_form_edit_title', 'Edit provider channel')
                        : aiText('channel_form_title', 'Add provider channel')}
                    </h3>
                    <BackofficeStatusBadge label={aiText('badge_save_and_test', 'Save and test')} status="info" />
                  </div>
                  <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {aiText('channel_form_desc', 'Choose a provider, paste the credential, then save and test. Advanced runtime fields stay folded unless you need them.')}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary justify-center"
                  disabled={savingConnection}
                  onClick={() => setProviderFormOpen(false)}
                >
                  {aiText('action_close_dialog', 'Close')}
                </button>
              </div>
              <form
                className="mt-4 grid gap-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void saveProviderConnection();
                }}
              >
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
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
                </div>

                <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  {aiText('field_base_url', 'Base URL')}
                  <input
                    className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                    value={providerConnectionForm.baseUrl}
                    onChange={(event) => updateProviderConnectionForm({ baseUrl: event.target.value })}
                    placeholder="https://api.example.com/v1"
                  />
                </label>

                <section className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50/60 p-4 dark:border-slate-800 dark:bg-slate-950/40">
                  <div className="grid gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-950 dark:text-white">{aiText('model_catalog_title', 'Model catalog')}</h3>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{aiText('model_catalog_desc', 'Sync provider-visible models, then enable only the models you want this channel to expose.')}</p>
                        <p className="mt-1 text-xs font-normal text-slate-500 dark:text-slate-400">
                          {aiText('enabled_model_summary', 'Enabled {{enabled}} models.', {
                            enabled: String(splitList(providerConnectionForm.modelIds).length),
                          })}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700"
                          disabled={!splitList(providerConnectionForm.modelIds).length || savingConnection}
                          onClick={() => setProviderModelIds([])}
                        >
                          {aiText('action_clear_all_models', 'Clear all')}
                        </button>
                        <button
                          type="button"
                          className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700"
                          disabled={fetchingProviderCatalog || savingConnection}
                          onClick={() => void fetchProviderCatalogPreview()}
                        >
                          {fetchingProviderCatalog
                            ? aiText('action_fetching_upstream_models', 'Fetching...')
                            : aiText('action_fetch_upstream_models', 'Sync model catalog')}
                        </button>
                      </div>
                    </div>
                    {providerCatalogPreview ? (
                      <div className="grid gap-2">
                        <span className="text-xs font-normal leading-5 text-slate-500 dark:text-slate-400">
                          {aiText('catalog_preview_loaded', 'Loaded {{count}} models from upstream.', {
                            count: String(providerCatalogPreview.model_count),
                          })}
                          {providerCatalogPreview.truncated ? ` ${aiText('catalog_preview_truncated', 'Showing first 100.')}` : ''}
                        </span>
                        {providerCatalogPreview.models?.length ? (
                          <div className="max-h-72 overflow-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
                            <table className="w-full min-w-[42rem] text-left text-xs font-normal">
                              <thead className="bg-slate-50 text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                                <tr>
                                  <th className="px-3 py-2 font-semibold">{aiText('catalog_model_header_status', 'Status')}</th>
                                  <th className="px-3 py-2 font-semibold">{aiText('catalog_model_header_model', 'Model')}</th>
                                  <th className="px-3 py-2 font-semibold">{aiText('catalog_model_header_feature', 'Feature')}</th>
                                  <th className="px-3 py-2 font-semibold">{aiText('catalog_model_header_action', 'Action')}</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                                {providerCatalogPreview.models.map((model) => {
                                  const selected = splitList(providerConnectionForm.modelIds).includes(model.model_id);
                                  return (
                                    <tr key={model.model_id} className="bg-white dark:bg-slate-950">
                                      <td className="px-3 py-2">
                                        <span className={`inline-flex rounded-full px-2 py-1 text-[11px] font-semibold ${
                                          model.verified
                                            ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
                                            : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                                        }`}
                                        >
                                          {model.verified
                                            ? aiText('catalog_model_status_verified', 'Verified')
                                            : aiText('catalog_model_status_catalog_only', 'Catalog only')}
                                        </span>
                                      </td>
                                      <td className="px-3 py-2">
                                        <div className="font-semibold text-slate-900 dark:text-white">{model.model_id}</div>
                                        <div className="text-slate-500 dark:text-slate-400">
                                          {model.family}
                                          {model.is_deprecated ? ` · ${aiText('catalog_model_deprecated', 'deprecated')}` : ''}
                                        </div>
                                      </td>
                                      <td className="px-3 py-2 text-slate-600 dark:text-slate-300">
                                        {abilityModelFeatureLabel(model.feature)}
                                      </td>
                                      <td className="px-3 py-2">
                                        <button
                                          type="button"
                                          className="rounded-full border border-slate-200 bg-white px-3 py-1 font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700"
                                          onClick={() => {
                                            if (selected) {
                                              removeProviderModelId(model.model_id);
                                            } else {
                                              setProviderModelIds([...splitList(providerConnectionForm.modelIds), model.model_id]);
                                            }
                                          }}
                                        >
                                          {selected
                                            ? aiText('action_disable_catalog_model', 'Disable')
                                            : aiText('action_enable_catalog_model', 'Enable')}
                                        </button>
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-sm font-normal text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
                        {aiText('model_catalog_empty', 'No catalog loaded yet. Sync the model catalog when you need to inspect provider-visible models.')}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col gap-2 border-t border-slate-200 pt-4 dark:border-slate-800 sm:flex-row">
                    <input
                      className="h-11 min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
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
                      className="btn btn-secondary shrink-0"
                      disabled={!customModelInput.trim()}
                      onClick={addCustomProviderModels}
                    >
                      {aiText('action_add_model', 'Add')}
                    </button>
                  </div>
                </section>

                <label className="inline-flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={providerConnectionForm.enabled}
                    onChange={(event) => updateProviderConnectionForm({ enabled: event.target.checked })}
                  />
                  {aiText('field_enabled_runtime', 'Enabled for runtime use')}
                </label>

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
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
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
                <div className="flex flex-col gap-3 text-sm text-slate-600 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between">
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
          <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-950 dark:text-white">{aiText('connection_list_title', 'Provider channels')}</h3>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {aiText('connection_list_desc', 'Configured runtime provider channels. This list does not edit abilities, prompts, router rules, or WordPress writes.')}
                </p>
              </div>
              <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200 lg:w-80">
                {aiText('field_search_connections', 'Search channels')}
                <input
                  className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                  value={connectionSearch}
                  onChange={(event) => setConnectionSearch(event.target.value)}
                  placeholder={aiText('placeholder_search_connections', 'Name, provider, capability, profile')}
                />
              </label>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {[
                ['all', aiText('filter_all', 'All')],
                ['ready', aiText('filter_ready', 'Ready')],
                ['missing_secret', aiText('filter_missing_secret', 'Missing secret')],
                ['disabled', aiText('filter_disabled', 'Disabled')],
              ].map(([filterId, label]) => (
                <button
                  key={filterId}
                  type="button"
                  className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                    connectionStatusFilter === filterId
                      ? 'border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700'
                  }`}
                  onClick={() => setConnectionStatusFilter(filterId as ConnectionStatusFilter)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {[
            {
              id: 'ai',
              title: aiText('ai_suppliers_title', 'Model suppliers'),
              description: aiText('ai_suppliers_desc', 'Model provider channels managed by Cloud runtime storage. Use edit, test, and delete here.'),
              connections: aiSupplierConnections,
              empty: aiText('ai_suppliers_empty', 'No model suppliers match the current filters.'),
            },
          ].map((supplierGroup) => (
            <div key={supplierGroup.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
              <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
                <h3 className="text-sm font-semibold text-slate-950 dark:text-white">{supplierGroup.title}</h3>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{supplierGroup.description}</p>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-[1120px] w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                    <tr>
                      <th className="px-4 py-3">{aiText('column_status', 'Status')}</th>
                      <th className="px-4 py-3">{aiText('column_provider', 'Provider')}</th>
                      <th className="px-4 py-3">{aiText('column_base_url', 'Base URL')}</th>
                      <th className="px-4 py-3">{aiText('column_enabled_configured', 'Enabled / configured')}</th>
                      <th className="px-4 py-3">{aiText('column_capabilities_profiles', 'Capabilities / profiles')}</th>
                      <th className="px-4 py-3">{aiText('last_test', 'Last test')}</th>
                      <th className="px-4 py-3 text-right">{aiText('column_actions', 'Actions')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                    {supplierGroup.connections.map((connection) => {
                      const category = supplierCategory(connection);
                      const isAiSupplier = category === 'ai';
                      const testResult = connectionTestResults[connection.connection_id];
                      return (
                        <tr key={connection.connection_id} className="align-top">
                          <td className="px-4 py-4">
                            <BackofficeStatusBadge label={resourceStatusLabel(connection.status)} status={statusTone(connection.status)} />
                          </td>
                          <td className="px-4 py-4">
                            <div className="font-semibold text-slate-950 dark:text-white">{connection.display_name}</div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {connection.provider_id} · {providerKindLabel(connection.kind)}
                            </div>
                            <div className="mt-2">
                              <BackofficeStatusBadge
                                label={
                                  isAiSupplier
                                    ? aiText('supplier_type_ai', 'Model supplier')
                                    : aiText('supplier_type_capability', 'Capability supplier')
                                }
                                status={isAiSupplier ? 'info' : 'disabled'}
                              />
                            </div>
                          </td>
                          <td className="max-w-[16rem] px-4 py-4">
                            <span className="break-all text-slate-600 dark:text-slate-300">{connection.base_url || '-'}</span>
                          </td>
                          <td className="px-4 py-4 text-slate-600 dark:text-slate-300">
                            <div>{aiText('field_enabled', 'Enabled')}: {connection.enabled ? aiText('common_yes', 'yes') : aiText('common_no', 'no')}</div>
                            <div>{aiText('field_configured', 'Configured')}: {connection.configured ? aiText('common_yes', 'yes') : aiText('common_no', 'no')}</div>
                          </td>
                          <td className="max-w-[18rem] px-4 py-4 text-slate-600 dark:text-slate-300">
                            <div>{aiText('field_capabilities', 'Capabilities')}: {labelList(connection.capability_ids)}</div>
                            <div className="mt-1">{aiText('field_profiles', 'Profiles')}: {labelList(connection.runtime_profile_ids)}</div>
                          </td>
                          <td className="max-w-[18rem] px-4 py-4 text-slate-600 dark:text-slate-300">
                            {testResult ? (
                              <div className="grid gap-1">
                                <div className="flex items-center gap-2">
                                  <BackofficeStatusBadge label={resourceStatusLabel(testResult.status)} status={testResult.ok ? 'success' : 'warning'} />
                                  <span className="text-xs text-slate-500 dark:text-slate-400">{testResult.stage}</span>
                                </div>
                                <div className="text-xs leading-5">{testResult.message}</div>
                                {testResult.catalog?.model_count ? (
                                  <div className="text-xs text-slate-500 dark:text-slate-400">
                                    {aiText('catalog_models', 'Catalog models')}: {testResult.catalog.model_count} · {labelList(testResult.catalog.sample_model_ids || [])}
                                  </div>
                                ) : null}
                              </div>
                            ) : '-'}
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex flex-wrap justify-end gap-2">
                              {isAiSupplier ? (
                                <button
                                  type="button"
                                  className="btn btn-secondary"
                                  onClick={() => editProviderConnection(connection)}
                                >
                                  {aiText('action_configure', 'Configure')}
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
                        <td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
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
            <BackofficeStackCard className="border-slate-200 bg-slate-50 text-sm leading-6 text-slate-600 dark:border-slate-800 dark:bg-slate-900/45 dark:text-slate-300">
              {aiText(
                'capability_suppliers_inline_notice',
                'Capability suppliers are configured here. Use the category list first, then open details only when needed. Existing projected rows: {{count}}.',
                { count: String(capabilitySupplierConnections.length) }
              )}
            </BackofficeStackCard>
            <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
              <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-950 dark:text-white">
                      {aiText('capability_supplier_list_title', 'Capability supplier list')}
                    </h3>
                    <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {aiText('capability_supplier_list_desc', 'Search, image, and vector suppliers are grouped so routine checks stay scannable.')}
                    </p>
                  </div>
                  <div className="flex flex-col gap-2 sm:items-end">
                    <button
                      type="button"
                      className="btn btn-primary justify-center"
                      onClick={() => setCapabilityAddDialogOpen(true)}
                    >
                      {aiText('action_add_capability_supplier', 'Add capability supplier')}
                    </button>
                    <div className="flex flex-wrap justify-end gap-2">
                      {(['search', 'image', 'vector'] as CapabilityProviderCategory[]).map((category) => (
                        <button
                          key={category}
                          type="button"
                          className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                            activeCapabilityCategory === category
                              ? 'border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950'
                              : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700'
                          }`}
                          onClick={() => setActiveCapabilityCategory(category)}
                        >
                          {capabilityCategoryLabel(category)} · {capabilityConnectionsByCategory[category].length}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-[1040px] w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
                    <tr>
                      <th className="px-4 py-3">{aiText('column_status', 'Status')}</th>
                      <th className="px-4 py-3">{aiText('column_provider', 'Provider')}</th>
                      <th className="px-4 py-3">{aiText('column_category', 'Category')}</th>
                      <th className="px-4 py-3">{aiText('column_base_url', 'Base URL')}</th>
                      <th className="px-4 py-3">{aiText('column_enabled_configured', 'Enabled / configured')}</th>
                      <th className="px-4 py-3">{aiText('column_profiles', 'Profiles')}</th>
                      <th className="px-4 py-3 text-right">{aiText('column_actions', 'Actions')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                    {activeCapabilityConnections.map((connection) => {
                      const category = capabilityProviderCategory(connection);
                      return (
                        <tr key={connection.connection_id} className="align-top">
                          <td className="px-4 py-4">
                            <BackofficeStatusBadge label={resourceStatusLabel(connection.status)} status={statusTone(connection.status)} />
                          </td>
                          <td className="px-4 py-4">
                            <div className="font-semibold text-slate-950 dark:text-white">{connection.display_name}</div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {connection.provider_id} · {providerKindLabel(connection.kind)}
                            </div>
                          </td>
                          <td className="px-4 py-4 text-slate-600 dark:text-slate-300">{capabilityCategoryLabel(category)}</td>
                          <td className="max-w-[16rem] px-4 py-4">
                            <span className="break-all text-slate-600 dark:text-slate-300">{connection.base_url || '-'}</span>
                          </td>
                          <td className="px-4 py-4 text-slate-600 dark:text-slate-300">
                            <div>{aiText('field_enabled', 'Enabled')}: {connection.enabled ? aiText('common_yes', 'yes') : aiText('common_no', 'no')}</div>
                            <div>{aiText('field_configured', 'Configured')}: {connection.configured ? aiText('common_yes', 'yes') : aiText('common_no', 'no')}</div>
                          </td>
                          <td className="max-w-[18rem] px-4 py-4 text-slate-600 dark:text-slate-300">
                            <div>{labelList(connection.runtime_profile_ids)}</div>
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex justify-end">
                              <button
                                type="button"
                                className="btn btn-secondary"
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
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {activeCapabilityConnections.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
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
                <div className="w-full max-w-4xl rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-800 dark:bg-slate-950">
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
                  <div className="mt-4 grid gap-4 lg:grid-cols-2">
                    {(['search', 'image', 'vector'] as Array<CapabilityProviderTemplate['category']>).map((category) => (
                      <div key={category} className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                        <h4 className="text-sm font-semibold text-slate-950 dark:text-white">
                          {capabilityCategoryLabel(category)}
                        </h4>
                        <div className="mt-3 grid gap-2">
                          {CAPABILITY_PROVIDER_TEMPLATES.filter((template) => template.category === category).map((template) => (
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
                        </div>
                      </div>
                    ))}
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
        {preferences ? (
          <BackofficeSectionPanel>
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('profile_preferences_title', 'Audio ability models')}</h2>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {aiText('profile_preferences_desc', 'Runtime profile selection for audio summary, narration, and playback. This does not edit prompts, router rules, or WordPress write policy.')}
                </p>
              </div>
              <BackofficeStatusBadge label={aiText('badge_runtime_metadata', 'Runtime metadata')} status="info" />
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                {aiText('field_audio_summary_text_profile', 'Audio summary text profile')}
                <select
                  className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                  value={preferences.audio_summary_text_profile_id}
                  onChange={(event) => updatePreferences({ audio_summary_text_profile_id: event.target.value })}
                >
                  {preferences.allowed.text_profile_ids.map((profileId) => (
                    <option key={profileId} value={profileId}>
                      {profileId}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                {aiText('field_article_narration_audio_profile', 'Article narration audio profile')}
                <select
                  className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                  value={preferences.audio_narration_profile_id}
                  onChange={(event) => updatePreferences({ audio_narration_profile_id: event.target.value })}
                >
                  {preferences.allowed.audio_profile_ids.map((profileId) => (
                    <option key={profileId} value={profileId}>
                      {profileId}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                {aiText('field_audio_summary_playback_profile', 'Audio summary playback profile')}
                <select
                  className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                  value={preferences.audio_summary_audio_profile_id}
                  onChange={(event) => updatePreferences({ audio_summary_audio_profile_id: event.target.value })}
                >
                  {preferences.allowed.audio_profile_ids.map((profileId) => (
                    <option key={profileId} value={profileId}>
                      {profileId}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="mt-4 flex flex-col gap-3 text-sm text-slate-600 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between">
              <span>{aiText('preferences_storage_notice', 'Stored in {{path}}. Secrets are not part of this save path.', { path: preferences.env_path })}</span>
              <button
                type="button"
                onClick={saveProfilePreferences}
                disabled={savingPreferences}
                className="btn btn-primary justify-center disabled:cursor-not-allowed disabled:opacity-60"
              >
                {savingPreferences ? aiText('saving', 'Saving...') : aiText('action_save_preferences', 'Save profile preferences')}
              </button>
            </div>
          </BackofficeSectionPanel>
        ) : null}

        <BackofficeSectionPanel>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
                {aiText('ability_models_title', 'Ability models')}
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
                  ? aiText('ability_models_loading', 'Loading ability model routing...')
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
                  {aiText('ability_model_dialog_title', 'Configure ability model')}
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
                    placeholder={aiText('placeholder_ability_model_note', 'Why this ability model binding is being changed')}
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
                  {savingRouting ? aiText('saving', 'Saving...') : aiText('action_save_ability_model', 'Save ability model')}
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
