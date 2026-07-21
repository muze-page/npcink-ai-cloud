'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BackofficeDiagnosticNotice,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { AdminRouteSkeleton } from '@/components/admin/AdminRouteSkeleton';
import { AdminMutationReceipt, type AdminMutationReceiptPayload } from '@/components/admin/AdminMutationReceipt';
import { ProviderConnectionDialog } from '@/components/admin/ProviderConnectionDialog';
import { ProviderReferenceLinks } from '@/components/admin/ProviderReferenceLinks';
import {
  ModelSupplierTable,
  type ConnectionStatusFilter,
  type ProviderConnectionTestResult,
  type SupplierConnection as Connection,
} from '@/components/admin/SupplierConnectionTables';
import { SupplierSummaryCards } from '@/components/admin/SupplierSummaryCards';
import { SupplierToolbar } from '@/components/admin/SupplierToolbar';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { ApiError, resolveUiErrorMessage } from '@/lib/errors';
import { useDialogKeyboard } from '@/hooks/useDialogKeyboard';
import { formatDate } from '@/lib/utils';

const aiResourcesClient = createApiClient({ idempotencyPrefix: 'ai_resources' });

type SupplierCategory = 'ai' | 'capability';

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

type AiResources = {
  connections: Connection[];
};

type ProviderConnectionTestResponse = ProviderConnectionTestResult & {
  receipt?: AdminMutationReceiptPayload | null;
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
  websiteUrl?: string;
  statusUrl?: string;
  docsUrl?: string;
  capabilityIds: string;
  runtimeProfileIds: string;
  modelIds: string;
};

type ProviderExternalLinkItem = {
  key: 'website' | 'status' | 'docs';
  labelKey: string;
  fallback: string;
  href: string;
};

const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'openai_compatible',
    label: 'OpenAI Compatible',
    providerId: 'openai',
    kind: 'openai_compatible',
    displayName: 'OpenAI Compatible',
    baseUrl: 'https://api.openai.com/v1',
    websiteUrl: 'https://openai.com/',
    statusUrl: 'https://status.openai.com/',
    docsUrl: 'https://developers.openai.com/api/docs',
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
    websiteUrl: 'https://www.newapi.ai/en',
    docsUrl: 'https://www.newapi.ai/en/docs',
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
    websiteUrl: 'https://www.deepseek.com/',
    statusUrl: 'https://status.deepseek.com/',
    docsUrl: 'https://api-docs.deepseek.com/',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'deepseek-v4-flash, deepseek-v4-pro',
  },
  {
    id: 'kimi',
    label: 'Kimi',
    providerId: 'kimi',
    kind: 'openai_compatible',
    displayName: 'Kimi',
    baseUrl: 'https://api.moonshot.cn/v1',
    websiteUrl: 'https://www.kimi.com/',
    docsUrl: 'https://platform.kimi.com/docs/api/overview',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'kimi-k2.6',
  },
  {
    id: 'doubao',
    label: 'Doubao / Volcengine Ark',
    providerId: 'doubao',
    kind: 'openai_compatible',
    displayName: 'Doubao / Volcengine Ark',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    websiteUrl: 'https://www.volcengine.com/product/ark',
    docsUrl: 'https://docs.volcengine.com/docs/82379/1795150',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'doubao-seed-2-0-lite-260215',
  },
  {
    id: 'xiaomi_mimo',
    label: 'Xiaomi MiMo',
    providerId: 'xiaomi_mimo',
    kind: 'openai_compatible',
    displayName: 'Xiaomi MiMo',
    baseUrl: 'https://api.xiaomimimo.com/v1',
    websiteUrl: 'https://mimo.mi.com/',
    docsUrl: 'https://mimo.mi.com/docs/quick-start/first-api-call',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'mimo-v2.5-pro',
  },
  {
    id: 'longcat',
    label: 'LongCat / Meituan',
    providerId: 'longcat',
    kind: 'openai_compatible',
    displayName: 'LongCat / Meituan',
    baseUrl: 'https://api.longcat.chat/openai/v1',
    websiteUrl: 'https://longcat.chat/',
    docsUrl: 'https://longcat.chat/platform/docs/APIDocs.html',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'LongCat-2.0',
  },
  {
    id: 'qwen',
    label: 'Qwen / Alibaba Cloud Model Studio',
    providerId: 'qwen',
    kind: 'openai_compatible',
    displayName: 'Qwen / Alibaba Cloud Model Studio',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    websiteUrl: 'https://www.aliyun.com/product/bailian',
    docsUrl: 'https://help.aliyun.com/zh/model-studio/base-url',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'qwen3.6-plus',
  },
  {
    id: 'hunyuan',
    label: 'Hunyuan / Tencent TokenHub',
    providerId: 'hunyuan',
    kind: 'openai_compatible',
    displayName: 'Hunyuan / Tencent TokenHub',
    baseUrl: 'https://tokenhub.tencentmaas.com/v1',
    websiteUrl: 'https://cloud.tencent.com/product/hunyuan',
    docsUrl: 'https://cloud.tencent.com/document/product/1729/131925',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'hy3-preview',
  },
  {
    id: 'zhipu_glm',
    label: 'Zhipu GLM',
    providerId: 'zhipu_glm',
    kind: 'openai_compatible',
    displayName: 'Zhipu GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    websiteUrl: 'https://www.bigmodel.cn/',
    docsUrl: 'https://docs.bigmodel.cn/cn/guide/develop/openai/introduction',
    capabilityIds: 'text_generation',
    runtimeProfileIds: 'text.ai',
    modelIds: 'glm-5.1',
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    providerId: 'anthropic',
    kind: 'anthropic',
    displayName: 'Anthropic',
    baseUrl: 'https://api.anthropic.com',
    websiteUrl: 'https://www.anthropic.com/',
    statusUrl: 'https://status.claude.com/',
    docsUrl: 'https://platform.claude.com/docs',
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
    websiteUrl: 'https://openrouter.ai/',
    statusUrl: 'https://status.openrouter.ai/',
    docsUrl: 'https://openrouter.ai/docs',
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
    websiteUrl: 'https://www.siliconflow.com/',
    docsUrl: 'https://docs.siliconflow.com/en/userguide/introduction',
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
    websiteUrl: 'https://www.minimax.io/',
    statusUrl: 'https://status.minimax.io/',
    docsUrl: 'https://platform.minimax.io/docs',
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

function connectionHost(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '-';
  try {
    return new URL(trimmed).host || trimmed;
  } catch {
    return trimmed.replace(/^https?:\/\//, '').split('/')[0] || trimmed;
  }
}

function externalUrlValue(value: unknown): string {
  if (typeof value !== 'string') return '';
  const trimmed = value.trim();
  if (!trimmed) return '';
  try {
    const url = new URL(trimmed);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : '';
  } catch {
    return '';
  }
}

function providerExternalLinkItems(values: {
  websiteUrl?: unknown;
  statusUrl?: unknown;
  docsUrl?: unknown;
}): ProviderExternalLinkItem[] {
  return [
    {
      key: 'website' as const,
      labelKey: 'provider_link_website',
      fallback: 'Website',
      href: externalUrlValue(values.websiteUrl),
    },
    {
      key: 'status' as const,
      labelKey: 'provider_link_status',
      fallback: 'Status',
      href: externalUrlValue(values.statusUrl),
    },
    {
      key: 'docs' as const,
      labelKey: 'provider_link_docs',
      fallback: 'Docs',
      href: externalUrlValue(values.docsUrl),
    },
  ].filter((item) => item.href);
}

function providerReferenceLinksForForm(form: ProviderConnectionForm): {
  websiteUrl?: unknown;
  statusUrl?: unknown;
  docsUrl?: unknown;
} {
  const preset = providerPresetById(form.providerPreset);
  return preset.id === 'custom' ? {} : preset;
}

function providerReferenceLinksForConnection(connection: Connection): {
  websiteUrl?: unknown;
  statusUrl?: unknown;
  docsUrl?: unknown;
} {
  const preset = providerPresetById(inferProviderPreset(connection));
  if (preset.id === 'custom') return {};
  if (
    preset.id === 'openai_compatible' &&
    connection.provider_id.toLowerCase() !== 'openai' &&
    !isExactOpenAIBaseUrl(connection.base_url)
  ) {
    return {};
  }
  return preset;
}

function isExactOpenAIBaseUrl(baseUrl: string): boolean {
  try {
    return new URL(baseUrl).hostname.toLowerCase() === 'api.openai.com';
  } catch {
    return false;
  }
}

function connectionExternalLinkItems(connection: Connection): ProviderExternalLinkItem[] {
  return providerExternalLinkItems(providerReferenceLinksForConnection(connection));
}

function supplierCategory(connection: Connection): SupplierCategory {
  if (
    connection.metadata?.managed_surface === 'site_knowledge_vector_profile' ||
    connection.kind === 'web_search_provider' ||
    connection.kind === 'image_source_provider' ||
    connection.kind === 'embedding_provider' ||
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

function providerHostname(baseUrl: string): string {
  try {
    return new URL(baseUrl).hostname.toLowerCase().replace(/\.$/, '');
  } catch {
    return '';
  }
}

function matchesProviderHostname(hostname: string, allowedDomains: string[]): boolean {
  return allowedDomains.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`));
}

function inferProviderPreset(connection: Connection): string {
  const kind = connection.kind.toLowerCase();
  const providerId = connection.provider_id.toLowerCase();
  const hostname = providerHostname(connection.base_url);
  if (providerId.includes('newapi')) return 'newapi';
  if (providerId.includes('deepseek') || matchesProviderHostname(hostname, ['deepseek.com'])) return 'deepseek';
  if (providerId.includes('kimi') || providerId.includes('moonshot') || matchesProviderHostname(hostname, ['moonshot.cn'])) return 'kimi';
  if (providerId.includes('doubao') || providerId.includes('volcengine') || matchesProviderHostname(hostname, ['volces.com'])) return 'doubao';
  if (providerId.includes('xiaomi_mimo') || providerId === 'mimo' || matchesProviderHostname(hostname, ['xiaomimimo.com'])) return 'xiaomi_mimo';
  if (providerId.includes('longcat') || providerId.includes('meituan') || matchesProviderHostname(hostname, ['longcat.chat'])) return 'longcat';
  if (providerId.includes('qwen') || providerId.includes('dashscope') || matchesProviderHostname(hostname, ['dashscope.aliyuncs.com', 'maas.aliyuncs.com'])) return 'qwen';
  if (providerId.includes('hunyuan') || providerId.includes('tencent') || matchesProviderHostname(hostname, ['tencentmaas.com', 'hunyuan.cloud.tencent.com'])) return 'hunyuan';
  if (providerId.includes('zhipu') || providerId.includes('glm') || matchesProviderHostname(hostname, ['bigmodel.cn'])) return 'zhipu_glm';
  if (kind === 'anthropic') return 'anthropic';
  if (kind === 'openrouter') return 'openrouter';
  if (kind === 'siliconflow') return 'siliconflow';
  if (kind === 'minimax' || kind === 'audio_provider' || kind === 'minimax_audio') return 'minimax';
  if (kind === 'openai_compatible') return 'openai_compatible';
  return 'custom';
}

function normalizeAiResources(raw: any): AiResources {
  const value = raw && typeof raw === 'object' ? raw : {};
  return {
    connections: Array.isArray(value.connections) ? value.connections : [],
  };
}

function providerConnectionTestResultFromError(error: unknown): ProviderConnectionTestResponse | undefined {
  if (!(error instanceof ApiError) || !error.details || typeof error.details !== 'object' || Array.isArray(error.details)) {
    return undefined;
  }
  const details = error.details as Record<string, unknown>;
  return typeof details.connection_id === 'string'
    ? details as ProviderConnectionTestResponse
    : undefined;
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

function AiResourcesContent() {
  const { t } = useLocale();
  const toast = useToast();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedConnectionId = searchParams.get('focus') || '';
  const aiText = useCallback(
    (key: string, fallback: string, params?: Record<string, string>) => t(`admin.ai_resources.${key}`, params, fallback),
    [t]
  );
  const [data, setData] = useState<AiResources | null>(null);
  const [connectionStatusFilter, setConnectionStatusFilter] = useState<ConnectionStatusFilter>('all');
  const [connectionSearch, setConnectionSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [savingConnection, setSavingConnection] = useState(false);
  const [testingConnectionId, setTestingConnectionId] = useState('');
  const [deletingConnectionId, setDeletingConnectionId] = useState('');
  const [confirmingDeleteConnectionId, setConfirmingDeleteConnectionId] = useState('');
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
  const [modelReferenceShowDeprecated, setModelReferenceShowDeprecated] = useState(false);
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
  const [lastReceipt, setLastReceipt] = useState<AdminMutationReceiptPayload | null>(null);
  const [receiptDetailsOpen, setReceiptDetailsOpen] = useState(false);
  const autoSyncedReferenceProviders = useRef<Set<string>>(new Set());
  const resourcesRequestActiveRef = useRef(false);
  const resourcesRequestSequenceRef = useRef(0);
  const resourcesLoadedRef = useRef(false);
  const updateWorkspaceParams = useCallback((updates: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value) params.set(key, value);
      else params.delete(key);
    });
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  const handleConnectionSearchChange = useCallback((value: string) => {
    setConnectionSearch(value);
    updateWorkspaceParams({ q: value.trim() || null, focus: null });
  }, [updateWorkspaceParams]);

  const handleConnectionStatusFilterChange = useCallback((value: ConnectionStatusFilter) => {
    setConnectionStatusFilter(value);
    updateWorkspaceParams({ status: value === 'all' ? null : value, focus: null });
  }, [updateWorkspaceParams]);

  const handleSelectConnection = useCallback((connectionId: string) => {
    updateWorkspaceParams({ focus: connectionId });
  }, [updateWorkspaceParams]);
  const loadResources = useCallback(async (options: { showLoading?: boolean } = {}) => {
    if (resourcesRequestActiveRef.current) return;
    resourcesRequestActiveRef.current = true;
    const sequence = ++resourcesRequestSequenceRef.current;
    if (options.showLoading !== false && !resourcesLoadedRef.current) {
      setLoading(true);
    }
    setError('');
    try {
      const response = await aiResourcesClient.request<AiResources>('/api/admin/ai-resources');
      if (sequence !== resourcesRequestSequenceRef.current) return;
      const normalized = normalizeAiResources(response.data);
      setData(normalized);
      resourcesLoadedRef.current = true;
    } catch (loadError) {
      if (sequence !== resourcesRequestSequenceRef.current) return;
      setError(resolveUiErrorMessage(loadError, aiText('error_load', 'Failed to load provider management.')));
    } finally {
      if (sequence === resourcesRequestSequenceRef.current) {
        resourcesRequestActiveRef.current = false;
        setLoading(false);
      }
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
      const response = await aiResourcesClient.request<{
        items?: ModelReferenceEntry[];
        total?: number;
        source_summary?: ModelReferenceSourceSummary[];
      }>(`/api/admin/model-references?${params.toString()}`);
      setModelReferences(Array.isArray(response.data.items) ? response.data.items : []);
      setModelReferenceTotal(Number(response.data.total ?? 0) || 0);
      setModelReferenceSources(Array.isArray(response.data.source_summary) ? response.data.source_summary : []);
      setLoadedModelReferenceProviderId(normalizedProviderId);
    } catch (referenceError) {
      setModelReferences([]);
      setModelReferenceTotal(0);
      setModelReferenceSources([]);
      setLoadedModelReferenceProviderId('');
      setError(resolveUiErrorMessage(referenceError, aiText('error_load_model_references', 'Failed to load model reference data.')));
    } finally {
      setLoadingModelReferences(false);
    }
  }, [aiText]);

  useEffect(() => {
    void loadResources();
  }, [loadResources]);

  useEffect(() => {
    if (!providerFormOpen) return;
    void loadModelReferences(modelReferenceProviderId);
  }, [loadModelReferences, modelReferenceProviderId, providerFormOpen]);

  useEffect(() => {
    const requestedStatus = searchParams.get('status');
    if (requestedStatus === 'ready' || requestedStatus === 'missing_secret' || requestedStatus === 'disabled') {
      setConnectionStatusFilter(requestedStatus);
    } else {
      setConnectionStatusFilter('all');
    }
    setConnectionSearch(searchParams.get('q') || '');
  }, [searchParams]);

  async function saveProviderConnection() {
    const normalizedConnectionId = providerConnectionForm.connectionId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.providerId);
    const normalizedProviderId = providerConnectionForm.providerId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.connectionId);
    const modelIds = splitList(providerConnectionForm.modelIds);
    const modelConfig = modelIds.length ? { model_ids: modelIds, model_id: modelIds[0] } : {};
    const referenceLinks = providerReferenceLinksForForm(providerConnectionForm);
    const websiteUrl = externalUrlValue(referenceLinks.websiteUrl);
    const statusUrl = externalUrlValue(referenceLinks.statusUrl);
    const docsUrl = externalUrlValue(referenceLinks.docsUrl);
    setSavingConnection(true);
    setError('');
    setMessage('');
    try {
      const response = await aiResourcesClient.request<{
        connection_id?: string;
        receipt?: AdminMutationReceiptPayload | null;
      }>('/api/admin/provider-connections', {
        method: 'POST',
        body: {
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
            website_url: websiteUrl || undefined,
            status_url: statusUrl || undefined,
            docs_url: docsUrl || undefined,
            model_ids: modelIds,
            model_catalog_preview: catalogPreviewForMetadata(providerCatalogPreview),
          },
          credential: providerConnectionForm.credential || undefined,
        },
      });
      const savedConnectionId = String(response.data.connection_id || normalizedConnectionId);
      setLastReceipt(response.data.receipt || null);
      let testFailed = false;
      let successMessage = '';
      setMessage(aiText('message_connection_saved_testing', 'Provider connection saved. Running connection test now.'));
      try {
        await runProviderConnectionTest(savedConnectionId, { announce: false, reload: false });
        successMessage = aiText('message_connection_saved_and_tested', 'Provider connection saved and tested. Credential status is masked in this page.');
        setMessage(successMessage);
      } catch (testError) {
        testFailed = true;
        setError(
          aiText('message_connection_saved_test_failed', 'Provider connection saved, but the connection test failed: {{message}}', {
            message: resolveUiErrorMessage(testError, aiText('error_test_connection', 'Provider connection test failed.')),
          })
        );
      }
      await loadResources({ showLoading: false });
      if (!testFailed) {
        setProviderConnectionForm(EMPTY_PROVIDER_CONNECTION_FORM);
        setProviderFormMode('create');
        setProviderFormOpen(false);
        setMessage('');
        toast.success(successMessage, t('common.success'));
      }
    } catch (saveError) {
      setError(resolveUiErrorMessage(saveError, aiText('error_save_connection', 'Failed to save provider connection.')));
    } finally {
      setSavingConnection(false);
    }
  }

  async function deleteProviderConnection(connection: Connection) {
    if (connection.managed_by !== 'cloud_provider_connections') return;
    setDeletingConnectionId(connection.connection_id);
    setError('');
    setMessage('');
    try {
      const response = await aiResourcesClient.request<{ receipt?: AdminMutationReceiptPayload | null }>(
        `/api/admin/provider-connections/${encodeURIComponent(connection.connection_id)}`,
        {
          method: 'DELETE',
        }
      );
      setLastReceipt(response.data.receipt || null);
      const successMessage = aiText('message_connection_deleted', 'Provider connection deleted.');
      setMessage('');
      toast.success(successMessage, t('common.success'));
      if (providerConnectionForm.connectionId === connection.connection_id) {
        setProviderFormOpen(false);
        setProviderConnectionForm(EMPTY_PROVIDER_CONNECTION_FORM);
        setProviderFormMode('create');
      }
      setConfirmingDeleteConnectionId('');
      await loadResources({ showLoading: false });
    } catch (deleteError) {
      const deleteMessage = resolveUiErrorMessage(deleteError, aiText('error_delete_connection', 'Failed to delete provider connection.'));
      setError(deleteMessage);
      toast.error(deleteMessage, t('common.error'));
    } finally {
      setDeletingConnectionId('');
    }
  }

  async function syncModelReferencesForProvider(
    providerId: string,
    options: { announce?: boolean } = {}
  ): Promise<void> {
    const normalizedProviderId = providerId.trim().toLowerCase();
    if (!normalizedProviderId || normalizedProviderId === 'custom') return;
    setSyncingModelReferences(true);
    setModelReferenceAutoSyncError('');
    try {
      await aiResourcesClient.request<unknown>('/api/admin/model-references/sync', {
        method: 'POST',
        body: {},
      });
      await loadModelReferences(normalizedProviderId);
      if (options.announce) {
        setMessage(aiText('message_model_references_synced', 'Model reference data synced. It is reference-only and does not change billing or routing.'));
      }
    } finally {
      setSyncingModelReferences(false);
    }
  }

  async function fetchProviderCatalogPreview() {
    const normalizedConnectionId = providerConnectionForm.connectionId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.providerId);
    const normalizedProviderId = providerConnectionForm.providerId || slugifyProviderValue(providerConnectionForm.displayName || providerConnectionForm.connectionId);
    const modelIds = splitList(providerConnectionForm.modelIds);
    const modelConfig = modelIds.length ? { model_ids: modelIds, model_id: modelIds[0] } : {};
    const referenceLinks = providerReferenceLinksForForm(providerConnectionForm);
    const websiteUrl = externalUrlValue(referenceLinks.websiteUrl);
    const statusUrl = externalUrlValue(referenceLinks.statusUrl);
    const docsUrl = externalUrlValue(referenceLinks.docsUrl);
    if (!providerConnectionForm.credential.trim() && providerFormMode === 'create') {
      setError(aiText('error_fetch_catalog_credential_required', 'Enter an API key before fetching upstream models. Existing saved credentials are not returned to the browser.'));
      return;
    }
    setFetchingProviderCatalog(true);
    setProviderCatalogPreview(null);
    setError('');
    setMessage('');
    try {
      const response = await aiResourcesClient.request<ProviderCatalogPreview>('/api/admin/provider-connections/preview-catalog', {
        method: 'POST',
        body: {
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
            website_url: websiteUrl || undefined,
            status_url: statusUrl || undefined,
            docs_url: docsUrl || undefined,
          },
          credential: providerConnectionForm.credential,
        },
      });
      const preview = response.data;
      setProviderCatalogPreview(preview);
      const verifiedModelIds = (preview.models || [])
        .filter((model) => !model.is_deprecated && (model.verified || model.runtime_supported))
        .map((model) => model.model_id);
      if (!splitList(providerConnectionForm.modelIds).length && verifiedModelIds.length) {
        setProviderModelIds(verifiedModelIds);
      }
      const referenceProviderId = inferReferenceProviderFromModelIds(
        verifiedModelIds.length ? verifiedModelIds : (preview.model_ids || []),
        defaultReferenceProviderId(normalizedProviderId, providerConnectionForm.providerPreset)
      );
      if (referenceProviderId !== modelReferenceProviderId) {
        setModelReferenceProviderId(referenceProviderId);
      }
      let referenceSyncFailed = '';
      try {
        await syncModelReferencesForProvider(referenceProviderId);
      } catch (syncError) {
        referenceSyncFailed = resolveUiErrorMessage(
          syncError,
          aiText('error_sync_model_references', 'Failed to sync model reference data.')
        );
        setModelReferenceAutoSyncError(referenceSyncFailed);
        await loadModelReferences(referenceProviderId);
      }
      setMessage(aiText(
        referenceSyncFailed ? 'message_catalog_fetched_reference_failed' : 'message_catalog_and_references_synced',
        referenceSyncFailed
          ? 'Fetched {{count}} upstream models. Reference intelligence refresh failed; saved models and runtime calls are not affected.'
          : 'Fetched {{count}} upstream models and refreshed reference intelligence.',
        {
          count: String(preview.model_count || preview.model_ids?.length || 0),
        }
      ));
    } catch (catalogError) {
      setError(resolveUiErrorMessage(catalogError, aiText('error_fetch_catalog', 'Failed to fetch upstream models.')));
    } finally {
      setFetchingProviderCatalog(false);
    }
  }

  async function syncModelReferences() {
    setError('');
    setMessage('');
    try {
      const effectiveReferenceProviderId = inferReferenceProviderFromModelIds(
        splitList(providerConnectionForm.modelIds),
        modelReferenceProviderId
      );
      if (effectiveReferenceProviderId !== modelReferenceProviderId) {
        setModelReferenceProviderId(effectiveReferenceProviderId);
      }
      await syncModelReferencesForProvider(effectiveReferenceProviderId, {
        announce: true,
      });
    } catch (syncError) {
      const effectiveReferenceProviderId = inferReferenceProviderFromModelIds(
        splitList(providerConnectionForm.modelIds),
        modelReferenceProviderId
      );
      await loadModelReferences(effectiveReferenceProviderId);
      setError(resolveUiErrorMessage(syncError, aiText('error_sync_model_references', 'Failed to sync model reference data.')));
    }
  }

  const autoSyncModelReferences = useCallback(async (providerId: string) => {
    setAutoSyncingModelReferences(true);
    setModelReferenceAutoSyncError('');
    try {
      await aiResourcesClient.request<unknown>('/api/admin/model-references/sync', {
        method: 'POST',
        body: {},
      });
      await loadModelReferences(providerId);
    } catch (syncError) {
      await loadModelReferences(providerId);
      setModelReferenceAutoSyncError(
        resolveUiErrorMessage(
          syncError,
          aiText('model_reference_status_auto_sync_failed', 'Reference intelligence auto sync failed. Saved models and runtime calls are not affected.')
        )
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
      const response = await aiResourcesClient.request<ProviderConnectionTestResponse>(
        `/api/admin/provider-connections/${encodeURIComponent(connectionId)}/test`,
        { method: 'POST' }
      );
      const result = response.data;
      if (result?.connection_id) {
        setConnectionTestResults((current) => ({
          ...current,
          [result.connection_id]: result,
        }));
      }
      if (announce) {
        setLastReceipt(result.receipt || null);
        const successMessage = result ? providerTestMessage(result) : aiText('message_connection_tested', 'Provider connection tested.');
        setMessage('');
        toast.success(successMessage, t('common.success'));
      }
      if (reload) {
        await loadResources({ showLoading: false });
      }
      return result;
    } catch (testError) {
      const result = providerConnectionTestResultFromError(testError);
      if (result?.connection_id) {
        setConnectionTestResults((current) => ({
          ...current,
          [result.connection_id]: result,
        }));
      }
      if (announce) {
        setLastReceipt(result?.receipt || null);
        const testMessage = resolveUiErrorMessage(
          testError,
          result?.message || aiText('error_test_connection', 'Provider connection test failed.')
        );
        setError(testMessage);
        toast.error(testMessage, t('common.error'));
      }
      throw testError;
    } finally {
      setTestingConnectionId('');
    }
  }

  function openNewProviderConnection() {
    setConfirmingDeleteConnectionId('');
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
    setConfirmingDeleteConnectionId('');
    const storedCatalogPreview = catalogPreviewFromConnection(connection);
    const providerPreset = inferProviderPreset(connection);
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
      providerPreset,
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
    setProviderFormOpen(true);
  }

  function closeProviderForm() {
    setProviderFormOpen(false);
    setMessage('');
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
    ? aiText('channel_form_edit_named_title', 'Edit {{name}}', { name: providerDialogName })
    : aiText('channel_form_title', 'Add provider channel');

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

  const modelFeatureLabel = useCallback((feature: string): string => {
    const normalized = feature.trim();
    if (normalized === 'image_generation' || normalized === 'image_generations' || normalized === 'image') {
      return aiText('model_feature_image_generation', 'Image generation');
    }
    if (normalized === 'text_generation' || normalized === 'text_generations' || normalized === 'text') {
      return aiText('model_feature_text_generation', 'Text generation');
    }
    if (normalized === 'audio_generation' || normalized === 'audio_generations' || normalized === 'audio') {
      return aiText('model_feature_audio_generation', 'Audio generation');
    }
    if (normalized === 'video_generation' || normalized === 'video_generations' || normalized === 'video') {
      return aiText('model_feature_video_generation', 'Video generation');
    }
    if (normalized === 'embedding' || normalized === 'embeddings') {
      return aiText('model_feature_embedding', 'Embedding');
    }
    return normalized || aiText('model_feature_unknown', 'Unknown');
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
  const providerUsesCustomRuntimeFields = providerConnectionForm.providerPreset === 'custom';
  const providerFormExternalLinkItems = providerExternalLinkItems(
    providerReferenceLinksForForm(providerConnectionForm)
  );

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
    if (!providerFormOpen) return;
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
        if (!modelReferenceShowDeprecated && row.deprecated && !row.selected) return false;
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
  if (loading) {
    return <AdminRouteSkeleton />;
  }

  if (!data) {
    return (
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow={aiText('eyebrow', 'Runtime plane')}
          title={aiText('title', 'Model suppliers')}
          description={aiText('unavailable_desc', 'Cloud runtime provider resources are unavailable.')}
        >
          <BackofficeDiagnosticNotice
            message={error || aiText('unavailable_message', 'Provider management is unavailable.')}
            retryLabel={t('common.retry')}
            onRetry={() => void loadResources()}
          />
        </BackofficePrimaryPanel>
      </BackofficePageStack>
    );
  }

  const readyModelSupplierCount = data.connections.filter(
    (connection) => supplierCategory(connection) === 'ai' && connection.status === 'ready'
  ).length;
  const modelSupplierCount = data.connections.filter(
    (connection) => supplierCategory(connection) === 'ai'
  ).length;
  const attentionSupplierCount = data.connections.filter(
    (connection) => supplierCategory(connection) === 'ai' && connection.status !== 'ready'
  ).length;
  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={aiText('eyebrow', 'Runtime plane')}
        title={aiText('title', 'Model suppliers')}
        description={aiText('description', 'Manage Cloud runtime model-provider connections and model visibility. Search, image, and vector services use their dedicated fixed-configuration pages.')}
        descriptionDisplay="hint"
        aside={(
          <div className="flex flex-col gap-2 sm:flex-row">
            <Link href="/admin/runtime-profiles" className="btn btn-secondary justify-center">
              {aiText('action_open_runtime_profiles', 'Open runtime profiles')}
            </Link>
            <Link href="/admin/troubleshooting" className="btn btn-secondary justify-center">
              {aiText('action_view_diagnostics', 'View diagnostics')}
            </Link>
          </div>
        )}
        actions={null}
        contentClassName="py-4 md:py-4"
      >
        <SupplierSummaryCards
          readyModelSupplierCount={readyModelSupplierCount}
          modelSupplierCount={modelSupplierCount}
          attentionSupplierCount={attentionSupplierCount}
          translate={aiText}
        />
        <p className="border-t border-slate-200 pt-4 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">
          {aiText('workspace_boundary_notice', 'This page opens Cloud service-plane detail only. Local plugin prompts, routers, approval, and WordPress writes stay outside Cloud.')}
        </p>
      </BackofficePrimaryPanel>

      <BackofficeSectionPanel>
        <SupplierToolbar
          connectionSearch={connectionSearch}
          onConnectionSearchChange={handleConnectionSearchChange}
          hasLatestOperation={Boolean(lastReceipt)}
          onOpenLatestOperation={() => setReceiptDetailsOpen(true)}
          onAddModelSupplier={openNewProviderConnection}
          translate={aiText}
        />

        <ProviderConnectionDialog
          open={providerFormOpen}
          title={providerDialogTitle}
          titleId="provider-channel-dialog-title"
          message={message}
          error={error}
          saving={savingConnection}
          closeLabel={aiText('action_close_dialog', 'Close')}
          cancelLabel={aiText('action_cancel', 'Cancel')}
          saveLabel={aiText('action_save_and_test_connection', 'Save and test provider')}
          savingLabel={aiText('saving', 'Saving...')}
          footerNotice={aiText('save_test_notice', 'Saving will immediately run a masked provider test. Secrets are never returned to the browser.')}
          onClose={closeProviderForm}
          onSubmit={() => void saveProviderConnection()}
        >
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
                        {providerFormExternalLinkItems.length ? (
                          <>
                            <span className="mx-1 text-slate-300 dark:text-slate-700">·</span>
                            {aiText('provider_links_configured', 'Reference links configured')}
                          </>
                        ) : null}
                      </p>
                    </div>
                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                      {aiText('connection_section_toggle_hint', 'Low-frequency settings')}
                    </span>
                  </summary>
                  <div className="mt-3 grid gap-3 px-1">
                    <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {aiText('connection_section_desc', 'Choose the service, name, base URL, and credential for this runtime channel.')}
                    </p>
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

                    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                      <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                        {aiText('field_base_url', 'Base URL')}
                        <input
                          className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                          value={providerConnectionForm.baseUrl}
                          onChange={(event) => updateProviderConnectionForm({ baseUrl: event.target.value })}
                          placeholder="https://api.example.com/v1"
                        />
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

                    <ProviderReferenceLinks
                      items={providerFormExternalLinkItems}
                      label={aiText('provider_links_title', 'Reference links')}
                      translate={aiText}
                    />
                  </div>
                </details>

                <section className="grid gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
                  <div className="grid gap-3">
                    <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
                      <div className="min-w-0">
                        <h3 className="text-sm font-semibold text-slate-950 dark:text-white">{aiText('model_visibility_title', 'Model visibility')}</h3>
                        <p className="mt-1 text-xs font-normal text-slate-500 dark:text-slate-400">
                          {aiText('model_visibility_allowlist_desc', 'Only enabled models in this list can enter hosted runtime profile candidate chains or be used by Cloud runtime.')}
                        </p>
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
                          <span className="sr-only">{aiText('field_search_models', 'Search models')}</span>
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
                                    disabled={fetchingProviderCatalog || syncingModelReferences || autoSyncingModelReferences || savingConnection}
                                    onClick={() => void fetchProviderCatalogPreview()}
                                  >
                                    {fetchingProviderCatalog || syncingModelReferences
                                      ? aiText('action_fetching_upstream_models', 'Syncing...')
                                      : aiText('action_fetch_upstream_models', 'Sync models and intelligence')}
                                  </button>
                                  <button
                                    type="button"
                                    className="h-9 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700"
                                    disabled={syncingModelReferences || autoSyncingModelReferences || loadingModelReferences || savingConnection}
                                    onClick={() => void syncModelReferences()}
                                  >
                                    {syncingModelReferences || autoSyncingModelReferences
                                      ? aiText('action_syncing_model_references', 'Syncing...')
                                      : aiText('action_sync_model_references', 'Retry intelligence only')}
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
                                    {aiText('field_show_deprecated_models', 'Show historical/deprecated')}
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
                                    <option value="text">{aiText('model_feature_text_generation', 'Text generation')}</option>
                                    <option value="image">{aiText('model_feature_image_generation', 'Image generation')}</option>
                                    <option value="audio">{aiText('model_feature_audio_generation', 'Audio generation')}</option>
                                    <option value="video">{aiText('model_feature_video_generation', 'Video generation')}</option>
                                    <option value="embedding">{aiText('model_feature_embedding', 'Embedding')}</option>
                                  </select>
                                </th>
                                <th className="px-3 py-2 font-semibold">{aiText('column_context_output', 'Context / output')}</th>
                                <th className="px-3 py-2 font-semibold">
                                  <span>{aiText('column_reference_price', 'Reference price')}</span>
                                  <span className="mt-0.5 block text-[11px] font-normal text-slate-400 dark:text-slate-500">
                                    {aiText('price_unit_per_1m', 'per 1M tokens')}
                                  </span>
                                </th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                              {modelVisibilityRows.map((row) => {
                                const tags = row.reference ? modelReferenceCapabilityTags(row.reference) : [];
                                const tagLabels = tags.map(modelReferenceCapabilityLabel);
                                const visibleTagLabels = tagLabels.slice(0, 3);
                                const canRemoveManualModel = row.sourceKind === 'manual' && row.selected;
                                const deprecatedEnableBlocked = row.deprecated && !row.selected;
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
                                        } hover:ring-2 hover:ring-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60 dark:hover:ring-slate-700`}
                                          aria-pressed={row.selected}
                                          disabled={deprecatedEnableBlocked}
                                          title={
                                            deprecatedEnableBlocked
                                              ? aiText('action_enable_deprecated_model_blocked', 'Deprecated models cannot be newly enabled')
                                              : row.selected
                                                ? aiText('action_disable_catalog_model', 'Disable')
                                                : aiText('action_enable_catalog_model', 'Enable')
                                          }
                                          onClick={() => {
                                            if (row.selected) {
                                              removeProviderModelId(row.modelId);
                                            } else if (!row.deprecated) {
                                              setProviderModelIds([...selectedProviderModelIds, row.modelId]);
                                            }
                                          }}
                                        >
                                          {row.selected
                                            ? aiText('status_model_enabled', 'Enabled')
                                            : deprecatedEnableBlocked
                                              ? aiText('status_model_deprecated_disabled', 'Deprecated')
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
                                      {row.deprecated && row.selected ? (
                                        <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                                          {aiText('deprecated_selected_model_hint', 'Deprecated model is kept only because it is already saved. Remove it before saving new model visibility choices.')}
                                        </div>
                                      ) : null}
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
                                      {modelFeatureLabel(row.feature)}
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
                        {aiText('field_profiles', 'Runtime configurations')}
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
        </ProviderConnectionDialog>
        <ModelSupplierTable
          connections={aiSupplierConnections}
          statusFilter={connectionStatusFilter}
          onStatusFilterChange={handleConnectionStatusFilterChange}
          selectedConnectionId={selectedConnectionId}
          onSelectConnection={handleSelectConnection}
          testResults={connectionTestResults}
          testingConnectionId={testingConnectionId}
          deletingConnectionId={deletingConnectionId}
          confirmingDeleteConnectionId={confirmingDeleteConnectionId}
          providerKindLabel={providerKindLabel}
          providerTestStageLabel={providerTestStageLabel}
          providerTestMessage={providerTestMessage}
          referenceLinksForConnection={connectionExternalLinkItems}
          onConfigure={editProviderConnection}
          onTest={(connectionId) => void runProviderConnectionTest(connectionId)}
          onDelete={(connection) => void deleteProviderConnection(connection)}
          onRequestDelete={setConfirmingDeleteConnectionId}
          onCancelDelete={() => setConfirmingDeleteConnectionId('')}
          translate={aiText}
        />
      </BackofficeSectionPanel>

      <Modal
        isOpen={receiptDetailsOpen && Boolean(lastReceipt)}
        onClose={() => setReceiptDetailsOpen(false)}
        title={aiText('latest_operation_title', 'Latest operation')}
        description={aiText('latest_operation_desc', 'Audit evidence from the most recent supplier change in this session.')}
        size="lg"
      >
        <AdminMutationReceipt receipt={lastReceipt} title={aiText('latest_operation_receipt', 'Operation receipt')} />
      </Modal>

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
