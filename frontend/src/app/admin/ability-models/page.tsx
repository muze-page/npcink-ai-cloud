'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BackofficeEmptyState,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { AdminMutationReceipt, type AdminMutationReceiptPayload } from '@/components/admin/AdminMutationReceipt';
import { BackofficeFilterPill } from '@/components/backoffice/BackofficeFilterPill';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { generateIdempotencyKey } from '@/lib/idempotency';

type ProviderConnectionProjection = {
  provider_id: string;
  display_name: string;
  kind: string;
  capability_ids: string[];
  enabled: boolean;
  configured: boolean;
  status: string;
};

type RuntimeInstance = {
  instance_id: string;
  provider_id: string;
  provider_display_name: string;
  adapter_type: string;
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
  routing_intent: string;
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
  available_text_instances: RuntimeInstance[];
  available_vision_instances: RuntimeInstance[];
  available_image_instances: RuntimeInstance[];
  available_audio_instances: RuntimeInstance[];
  available_embedding_instances: RuntimeInstance[];
  profiles: RoutingProfile[];
};

type EditableRoutingProfile = RoutingProfile & {
  note: string;
};

type AbilityModelTab = 'wordpress' | 'cloud';
type CloudAbilityMediaTab = 'text' | 'image' | 'vector' | 'audio' | 'video';
type CloudAbilityMediaFilter = 'all' | CloudAbilityMediaTab;
type CloudAbilityRuntimeStatus = 'connected' | 'missing_provider' | 'planned' | 'unknown';

const CLOUD_MEDIA_ORDER: CloudAbilityMediaTab[] = ['text', 'image', 'vector', 'audio', 'video'];

type CloudAbilityRuntimeRow = {
  ability_id: string;
  label: string;
  description: string;
  media: CloudAbilityMediaTab;
  status: CloudAbilityRuntimeStatus;
  raw_status: string;
  capability_id: string;
  model_kind: string;
  profile_id: string;
  provider_id: string;
  model_id: string;
  surface: string;
  can_configure: boolean;
  action: string;
};

type AbilityModelRouteRow = {
  profile: EditableRoutingProfile;
  primaryInstance?: RuntimeInstance;
  taskLabels: string[];
  routeTypeLabel: string;
};

type AudioPreviewJob = {
  run_id: string;
  status: string;
  trace_id?: string;
  provider_id?: string;
  model_id?: string;
  instance_id?: string;
  profile_id?: string;
  error_code?: string;
  error_message?: string;
  result_ready?: boolean;
  result?: {
    audios?: Array<{
      url?: string;
      b64_json?: string;
      mime_type?: string;
      duration_seconds?: number;
    }>;
  };
};

type AudioPreviewErrorState = {
  message: string;
  errorCode?: string;
  siteId?: string;
  siteStatus?: string;
  runtimeErrorCode?: string;
  providerId?: string;
  modelId?: string;
  instanceId?: string;
  profileId?: string;
  traceId?: string;
  runId?: string;
};

type AbilityModelInspectorTab = 'policy' | 'preview';

const MAX_DIALOG_CANDIDATE_OPTIONS = 24;

function isModelProviderConnection(connection: ProviderConnectionProjection): boolean {
  const capabilityProviderKinds = new Set([
    'web_search_provider',
    'image_source_provider',
    'embedding_provider',
    'rerank_provider',
    'vector_store_provider',
  ]);
  if (capabilityProviderKinds.has(connection.kind)) return false;
  return !connection.capability_ids.some((capabilityId) => (
    capabilityId === 'web_search' ||
    capabilityId === 'image_source' ||
    capabilityId === 'embedding' ||
    capabilityId === 'rerank' ||
    capabilityId === 'vector_store'
  ));
}

function normalizeProviderDisplayNames(raw: any): Record<string, string> {
  const rows = Array.isArray(raw?.connections) ? raw.connections : [];
  const ranked: Record<string, { label: string; score: number }> = {};
  rows.forEach((item: any) => {
    const connection: ProviderConnectionProjection = {
      provider_id: String(item?.provider_id ?? ''),
      display_name: String(item?.display_name ?? ''),
      kind: String(item?.kind ?? ''),
      capability_ids: Array.isArray(item?.capability_ids) ? item.capability_ids.map(String) : [],
      enabled: Boolean(item?.enabled),
      configured: Boolean(item?.configured),
      status: String(item?.status ?? ''),
    };
    if (!isModelProviderConnection(connection)) return;
    const providerId = connection.provider_id.trim();
    const label = connection.display_name.trim();
    if (!providerId || !label) return;
    const score =
      (connection.enabled ? 4 : 0) +
      (connection.configured ? 2 : 0) +
      (connection.status === 'ready' ? 1 : 0);
    if (!ranked[providerId] || score > ranked[providerId].score) {
      ranked[providerId] = { label, score };
    }
  });
  return Object.fromEntries(Object.entries(ranked).map(([providerId, entry]) => [providerId, entry.label]));
}

function normalizeRoutingData(raw: any): RoutingData {
  const data = raw ?? {};
  const routingGroupKey = ['group', 'id'].join('_');
  const normalizeInstance = (item: any): RuntimeInstance => ({
    instance_id: String(item?.instance_id ?? ''),
    provider_id: String(item?.provider_id ?? ''),
    provider_display_name: String(item?.provider_display_name ?? ''),
    adapter_type: String(item?.adapter_type ?? ''),
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
    available_text_instances: Array.isArray(data.available_text_instances)
      ? data.available_text_instances.map(normalizeInstance)
      : [],
    available_vision_instances: Array.isArray(data.available_vision_instances)
      ? data.available_vision_instances.map(normalizeInstance)
      : [],
    available_image_instances: Array.isArray(data.available_image_instances)
      ? data.available_image_instances.map(normalizeInstance)
      : [],
    available_audio_instances: Array.isArray(data.available_audio_instances)
      ? data.available_audio_instances.map(normalizeInstance)
      : [],
    available_embedding_instances: Array.isArray(data.available_embedding_instances)
      ? data.available_embedding_instances.map(normalizeInstance)
      : [],
    profiles: Array.isArray(data.profiles)
      ? data.profiles.map((profile: any) => ({
          profile_id: String(profile?.profile_id ?? ''),
          groupId: String(profile?.[routingGroupKey] ?? ''),
          routing_intent: String(profile?.routing_intent ?? ''),
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
  };
}

function normalizeCloudAbilityRuntimeRows(raw: any): CloudAbilityRuntimeRow[] {
  const rows = Array.isArray(raw?.rows) ? raw.rows : [];
  const mediaValues = new Set(['text', 'image', 'vector', 'audio', 'video']);
  const statusValues = new Set(['connected', 'missing_provider', 'planned', 'unknown']);
  return rows.map((row: any): CloudAbilityRuntimeRow => {
    const media = String(row?.media ?? 'text');
    const status = String(row?.status ?? 'unknown');
    return {
      ability_id: String(row?.ability_id ?? row?.feature_id ?? ''),
      label: String(row?.label ?? ''),
      description: String(row?.description ?? ''),
      media: (mediaValues.has(media) ? media : 'text') as CloudAbilityMediaTab,
      status: (statusValues.has(status) ? status : 'unknown') as CloudAbilityRuntimeStatus,
      raw_status: String(row?.raw_status ?? ''),
      capability_id: String(row?.capability_id ?? ''),
      model_kind: String(row?.model_kind ?? ''),
      profile_id: String(row?.profile_id ?? ''),
      provider_id: String(row?.provider_id ?? ''),
      model_id: String(row?.model_id ?? ''),
      surface: String(row?.surface ?? ''),
      can_configure: Boolean(row?.can_configure),
      action: String(row?.action ?? 'runtime_managed'),
    };
  });
}

function resolveAdminApiPayloadMessage(payload: any, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const message = typeof payload.message === 'string' ? payload.message : '';
    if (message.trim()) return resolveUiErrorMessage(message, fallback);
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
      if (detailMessage) return resolveUiErrorMessage(detailMessage, fallback);
    }
    if (typeof detail === 'string' && detail.trim()) return resolveUiErrorMessage(detail, fallback);
    if (typeof payload.error_code === 'string' && payload.error_code.trim()) {
      return resolveUiErrorMessage(payload.error_code, fallback);
    }
  }
  return resolveUiErrorMessage(payload, fallback);
}

function normalizeAudioPreviewError(payload: any, fallback: string): AudioPreviewErrorState {
  const data = payload && typeof payload === 'object' && payload.data && typeof payload.data === 'object'
    ? payload.data
    : {};
  return {
    message: resolveAdminApiPayloadMessage(payload, fallback),
    errorCode: typeof payload?.error_code === 'string' ? payload.error_code : undefined,
    siteId: typeof data.site_id === 'string' ? data.site_id : undefined,
    siteStatus: typeof data.site_status === 'string' ? data.site_status : undefined,
    runtimeErrorCode: typeof data.runtime_error_code === 'string' ? data.runtime_error_code : undefined,
    providerId: typeof data.provider_id === 'string' ? data.provider_id : undefined,
    modelId: typeof data.model_id === 'string' ? data.model_id : undefined,
    instanceId: typeof data.instance_id === 'string' ? data.instance_id : undefined,
    profileId: typeof data.profile_id === 'string' ? data.profile_id : undefined,
    traceId: typeof data.trace_id === 'string' ? data.trace_id : undefined,
    runId: typeof data.run_id === 'string' ? data.run_id : undefined,
  };
}

function audioPreviewErrorFromJob(job: AudioPreviewJob | null, fallback: string): AudioPreviewErrorState | null {
  if (!job || job.status !== 'failed') return null;
  return {
    message: job.error_message || fallback,
    errorCode: job.error_code,
    providerId: job.provider_id,
    modelId: job.model_id,
    instanceId: job.instance_id,
    profileId: job.profile_id,
    traceId: job.trace_id,
    runId: job.run_id,
  };
}

function audioPreviewSource(job: AudioPreviewJob | null): string {
  const audio = job?.result?.audios?.[0];
  if (!audio) return '';
  if (audio.url) return `/api/admin/audio-preview?url=${encodeURIComponent(audio.url)}`;
  if (audio.b64_json) return `data:${audio.mime_type || 'audio/mpeg'};base64,${audio.b64_json}`;
  return '';
}

export default function AbilityModelsPage() {
  const { t } = useLocale();
  const text = useCallback(
    (key: string, fallback: string, params?: Record<string, string>) => t(`admin.ability_models.${key}`, params, fallback),
    [t]
  );
  const aiText = useCallback(
    (key: string, fallback: string, params?: Record<string, string>) => t(`admin.ai_resources.${key}`, params, fallback),
    [t]
  );

  const [providerDisplayNames, setProviderDisplayNames] = useState<Record<string, string>>({});
  const [routingData, setRoutingData] = useState<RoutingData | null>(null);
  const [routingDrafts, setRoutingDrafts] = useState<EditableRoutingProfile[]>([]);
  const [cloudAbilityRows, setCloudAbilityRows] = useState<CloudAbilityRuntimeRow[]>([]);
  const [activeAbilityTab, setActiveAbilityTab] = useState<AbilityModelTab>('wordpress');
  const [activeCloudMediaFilter, setActiveCloudMediaFilter] = useState<CloudAbilityMediaFilter>('all');
  const [activeProfileId, setActiveProfileId] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingRouting, setLoadingRouting] = useState(true);
  const [savingRouting, setSavingRouting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [pageMessage, setPageMessage] = useState('');
  const [dialogError, setDialogError] = useState('');
  const [dialogMessage, setDialogMessage] = useState('');
  const [dialogReceipt, setDialogReceipt] = useState<AdminMutationReceiptPayload | null>(null);
  const [modelProviderFilter, setModelProviderFilter] = useState('');
  const [modelSearchQuery, setModelSearchQuery] = useState('');
  const [cloudBindingDialogRow, setCloudBindingDialogRow] = useState<CloudAbilityRuntimeRow | null>(null);
  const [cloudBindingProviderFilter, setCloudBindingProviderFilter] = useState('');
  const [cloudBindingModelSearchQuery, setCloudBindingModelSearchQuery] = useState('');
  const [savingCloudBinding, setSavingCloudBinding] = useState(false);
  const [advancedRuntimePolicyOpen, setAdvancedRuntimePolicyOpen] = useState(false);
  const [abilityModelInspectorTab, setAbilityModelInspectorTab] = useState<AbilityModelInspectorTab>('policy');
  const [audioPreviewCreating, setAudioPreviewCreating] = useState(false);
  const [audioPreviewJob, setAudioPreviewJob] = useState<AudioPreviewJob | null>(null);
  const [audioPreviewError, setAudioPreviewError] = useState<AudioPreviewErrorState | null>(null);
  const [audioPreviewText, setAudioPreviewText] = useState(() => text('audio_preview_sample_text', 'This is a short audio sample for checking the selected voice model.'));

  const loadProviderDisplayNames = useCallback(async () => {
    setLoading(true);
    setPageError('');
    try {
      const response = await fetch('/api/admin/ai-resources', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, text('error_load_provider_labels', 'Failed to load provider labels.')));
      }
      setProviderDisplayNames(normalizeProviderDisplayNames(payload.data));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : text('error_load_provider_labels', 'Failed to load provider labels.'));
    } finally {
      setLoading(false);
    }
  }, [text]);

  const loadRouting = useCallback(async () => {
    setLoadingRouting(true);
    setPageError('');
    try {
      const response = await fetch('/api/admin/ability-models/plugin-routing', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_load_ability_models', 'Failed to load ability-model routing.')));
      }
      const normalized = normalizeRoutingData(payload.data);
      setRoutingData(normalized);
      setRoutingDrafts(normalized.profiles.map((profile) => ({ ...profile, note: '' })));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : aiText('error_load_ability_models', 'Failed to load ability-model routing.'));
    } finally {
      setLoadingRouting(false);
    }
  }, [aiText]);

  const loadCloudAbilityRuntimeProjection = useCallback(async () => {
    setPageError('');
    try {
      const response = await fetch('/api/admin/ability-models/runtime-projection', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, text('error_load_cloud_runtime_projection', 'Failed to load Cloud-native ability runtime projection.')));
      }
      setCloudAbilityRows(normalizeCloudAbilityRuntimeRows(payload.data));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : text('error_load_cloud_runtime_projection', 'Failed to load Cloud-native ability runtime projection.'));
    }
  }, [text]);

  useEffect(() => {
    void loadProviderDisplayNames();
    void loadRouting();
    void loadCloudAbilityRuntimeProjection();
  }, [loadCloudAbilityRuntimeProjection, loadProviderDisplayNames, loadRouting]);

  const runtimeInstancesById = useMemo(() => {
    const instances = [
      ...(routingData?.available_text_instances || []),
      ...(routingData?.available_vision_instances || []),
      ...(routingData?.available_image_instances || []),
      ...(routingData?.available_audio_instances || []),
      ...(routingData?.available_embedding_instances || []),
    ];
    return new Map(instances.map((instance) => [instance.instance_id, instance]));
  }, [routingData]);

  const routingCandidateInstancesFor = useCallback((profile: RoutingProfile): RuntimeInstance[] => {
    if (profile.execution_kind === 'image_generation') {
      return routingData?.available_image_instances || [];
    }
    if (profile.execution_kind === 'vision') {
      return routingData?.available_vision_instances || [];
    }
    if (profile.execution_kind === 'audio_generation') {
      return routingData?.available_audio_instances || [];
    }
    return (routingData?.available_text_instances || []).filter((instance) => {
      const modelId = instance.model_id.toLowerCase();
      if (/(speech|audio|voice|tts|ocr|vision|image|embed)/i.test(modelId)) {
        return false;
      }
      const featureTokens = [
        instance.model_feature,
        instance.endpoint_variant,
        ...instance.capability_tags,
      ].join(' ').toLowerCase();
      if (featureTokens.includes('text')) return true;
      if (featureTokens.includes('image') || featureTokens.includes('audio') || featureTokens.includes('video')) {
        return false;
      }
      return true;
    });
  }, [routingData]);

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
      audio_summary_script: text('route_audio_summary_text', 'Audio summary text'),
      article_narration: text('route_article_narration_audio', 'Article narration audio'),
      article_audio_summary: text('route_audio_summary_playback', 'Audio summary playback'),
    };
    return labels[taskId] || taskId;
  }, [aiText, text]);

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
      audio_summary_script: text('audio_summary_text_desc', 'Text model configuration used before generating audio summaries.'),
      article_narration: text('audio_narration_desc', 'Audio model configuration used for article narration.'),
      article_audio_summary: text('audio_summary_playback_desc', 'Audio model configuration used for summary playback.'),
    };
    return descriptions[taskId] || aiText('ability_task_default_desc', 'Cloud runtime task from the WordPress AI connector.');
  }, [aiText, text]);

  const abilityModelFeatureLabel = useCallback((feature: string): string => {
    const normalized = feature.trim();
    if (normalized === 'image_generation' || normalized === 'image_generations') {
      return aiText('ability_model_feature_image_generation', 'Image generation');
    }
    if (normalized === 'text_generation' || normalized === 'text_generations' || normalized === 'text') {
      return aiText('ability_model_feature_text_generation', 'Text generation');
    }
    if (normalized === 'audio_generation' || normalized === 'audio_generations' || normalized === 'audio') {
      return text('route_type_audio', 'Audio');
    }
    if (normalized === 'embedding' || normalized === 'embeddings') {
      return text('cloud_model_kind_embedding', 'Embedding model');
    }
    return normalized || aiText('ability_model_feature_unknown', 'Unknown');
  }, [aiText, text]);

  const abilityModelRegionLabel = useCallback((region: string): string => {
    const normalized = region.trim();
    return normalized && normalized !== 'global' ? normalized : aiText('ability_model_region_global', 'Global');
  }, [aiText]);

  const abilityModelHealthLabel = useCallback((status: string): string => {
    const normalized = status.trim();
    if (normalized === 'healthy') return aiText('status_healthy_label', 'Healthy');
    if (normalized === 'degraded') return aiText('status_degraded_label', 'Degraded');
    if (normalized === 'error') return aiText('status_error_label', 'Error');
    if (normalized === 'warning') return aiText('status_warning_label', 'Warning');
    return normalized || aiText('status_not_observed', 'not observed');
  }, [aiText]);

  const providerDisplayName = useCallback((providerId: string): string => {
    const normalized = providerId.trim();
    return providerDisplayNames[normalized] || normalized;
  }, [providerDisplayNames]);

  const modelRouteLabel = useCallback((providerId?: string, modelId?: string, providerLabelOverride?: string): string => {
    const providerLabel = providerLabelOverride?.trim() || (providerId ? providerDisplayName(providerId) : '');
    const normalizedModelId = String(modelId || '').trim();
    if (!providerLabel && !normalizedModelId) return '-';
    if (!providerLabel) return normalizedModelId;
    if (!normalizedModelId) return providerLabel;
    return `${providerLabel} / ${normalizedModelId}`;
  }, [providerDisplayName]);

  const runtimeModelRouteLabel = useCallback((instance?: RuntimeInstance): string => (
    instance
      ? modelRouteLabel(instance.provider_id, instance.model_id, instance.provider_display_name)
      : '-'
  ), [modelRouteLabel]);

  const runtimeModelCandidateLabel = useCallback((instance: RuntimeInstance): string => {
    const filteredProviderId = modelProviderFilter.trim();
    if (filteredProviderId && filteredProviderId === instance.provider_id.trim()) {
      return instance.model_id.trim() || runtimeModelRouteLabel(instance);
    }
    return runtimeModelRouteLabel(instance);
  }, [modelProviderFilter, runtimeModelRouteLabel]);

  const abilityModelInstanceDetail = useCallback((instance: RuntimeInstance): string => (
    aiText('ability_model_instance_detail', 'Instance: {{instance}} · Capability: {{feature}} · Region: {{region}} · Status: {{status}}', {
      instance: instance.instance_id,
      feature: abilityModelFeatureLabel(instance.model_feature || instance.endpoint_variant),
      region: abilityModelRegionLabel(instance.region),
      status: abilityModelHealthLabel(instance.health_status),
    })
  ), [abilityModelFeatureLabel, abilityModelHealthLabel, abilityModelRegionLabel, aiText]);

  const abilityModelRuntimeSummary = useCallback((instance: RuntimeInstance): string => (
    aiText('ability_model_runtime_summary', '{{feature}} · {{region}} · {{status}}', {
      feature: abilityModelFeatureLabel(instance.model_feature || instance.endpoint_variant),
      region: abilityModelRegionLabel(instance.region),
      status: abilityModelHealthLabel(instance.health_status),
    })
  ), [abilityModelFeatureLabel, abilityModelHealthLabel, abilityModelRegionLabel, aiText]);

  const cloudAbilityLabel = useCallback((row: CloudAbilityRuntimeRow): string => {
    const labels: Record<string, string> = {
      site_knowledge_embedding: text('cloud_ability_site_knowledge_embedding', 'Site Knowledge embedding'),
      evidence_preflight: text('cloud_ability_external_evidence', 'External evidence preflight'),
      image_source_candidates: text('cloud_ability_image_source_candidates', 'Image source candidates'),
    };
    return labels[row.ability_id] || row.label || row.ability_id;
  }, [text]);

  const cloudAbilityDescription = useCallback((row: CloudAbilityRuntimeRow): string => {
    const descriptions: Record<string, string> = {
      site_knowledge_embedding: text('cloud_ability_site_knowledge_embedding_desc', 'Embedding runtime used by Site Knowledge detail and retrieval support.'),
      evidence_preflight: text('cloud_ability_external_evidence_desc', 'Prepare evidence grounding before handing control back to the local WordPress path.'),
      image_source_candidates: text('cloud_ability_image_source_candidates_desc', 'Search external image sources and return reviewable media candidates.'),
    };
    return descriptions[row.ability_id] || row.description;
  }, [text]);

  const cloudAbilityModelKindLabel = useCallback((modelKind: string): string => {
    const labels: Record<string, string> = {
      text_model: text('cloud_model_kind_text', 'Text model'),
      audio_model: text('cloud_model_kind_audio', 'Audio model'),
      image_model: text('cloud_model_kind_vision_image', 'Vision / image model'),
      embedding_model: text('cloud_model_kind_embedding', 'Embedding model'),
      search_text_model: text('cloud_model_kind_search_text', 'Search + text model'),
      image_source_provider: text('cloud_model_kind_image_source', 'Image source provider'),
      runtime_model: text('cloud_model_kind_runtime', 'Runtime model'),
    };
    return labels[modelKind] || modelKind || text('cloud_model_kind_runtime', 'Runtime model');
  }, [text]);

  const cloudAbilityRuntimeLabel = useCallback((row: CloudAbilityRuntimeRow): string => {
    if (row.provider_id.trim() || row.model_id.trim()) {
      return modelRouteLabel(row.provider_id, row.model_id);
    }
    if (row.model_kind === 'search_text_model') {
      return text('cloud_runtime_managed_search_text', 'Cloud-managed search service');
    }
    if (row.model_kind === 'image_source_provider') {
      return text('cloud_runtime_managed_image_source', 'Cloud-managed image source');
    }
    if (row.profile_id.trim()) {
      return text('cloud_runtime_managed_projection', 'Cloud-managed runtime');
    }
    return text('cloud_native_runtime_unassigned', 'Not connected');
  }, [modelRouteLabel, text]);

  const cloudManagedDependencyLabel = useCallback((row: CloudAbilityRuntimeRow): string => {
    if (row.model_kind === 'search_text_model') {
      return text('cloud_native_managed_by_search_supplier', 'Controlled by search supplier settings');
    }
    if (row.model_kind === 'image_source_provider') {
      return text('cloud_native_managed_by_image_supplier', 'Controlled by image supplier settings');
    }
    return text('cloud_native_action_readonly', 'Cloud managed');
  }, [text]);

  const cloudAbilityStatusLabel = useCallback((status: CloudAbilityRuntimeStatus): string => {
    if (status === 'connected') return text('cloud_native_status_connected', 'Connected');
    if (status === 'missing_provider') return text('cloud_native_status_missing_provider', 'Missing provider');
    if (status === 'planned') return text('cloud_native_status_planned', 'Planned');
    return text('cloud_native_status_unknown', 'Unknown');
  }, [text]);

  const cloudAbilityStatusClassName = useCallback((status: CloudAbilityRuntimeStatus): string => {
    if (status === 'missing_provider') return 'text-amber-700 dark:text-amber-300';
    if (status === 'planned') return 'text-slate-500 dark:text-slate-400';
    if (status === 'unknown') return 'text-rose-700 dark:text-rose-300';
    return 'text-slate-600 dark:text-slate-300';
  }, []);

  const abilityRouteTitle = useCallback((profile: RoutingProfile): string => {
    const labels: Record<string, string> = {
      'content.short_text': text('route_content_short_text', 'Short text suggestions'),
      'content.editorial': text('route_content_editorial', 'Editorial assistance'),
      'content.classification': text('route_content_classification', 'Content classification'),
      'media.alt_text_vision': text('route_media_alt_text_vision', 'Alt text vision'),
      'media.image_generation': text('route_media_image_generation', 'Image generation candidates'),
      'audio.generation': text('route_audio_generation', 'Audio generation'),
    };
    if (profile.routing_intent && labels[profile.routing_intent]) return labels[profile.routing_intent];
    if (profile.tasks.length === 1) return abilityTaskLabel(profile.tasks[0]);
    if (profile.tasks.length > 1) {
      return aiText('ability_model_group_title', '{{name}} and {{count}} abilities', {
        name: abilityTaskLabel(profile.tasks[0]),
        count: String(profile.tasks.length),
      });
    }
    return profile.label || profile.profile_id;
  }, [abilityTaskLabel, aiText, text]);

  const abilityRouteTypeLabel = useCallback((profile: RoutingProfile): string => {
    if (profile.routing_intent === 'media.image_generation' || profile.execution_kind === 'image_generation') {
      return text('route_type_image', 'Image');
    }
    if (profile.routing_intent.startsWith('audio.') || profile.execution_kind === 'audio_generation') {
      return text('route_type_audio', 'Audio');
    }
    if (profile.routing_intent === 'content.classification') {
      return text('route_type_classification', 'Classification');
    }
    if (profile.routing_intent === 'content.editorial') {
      return text('route_type_editorial', 'Editorial');
    }
    return text('route_type_text', 'Text');
  }, [text]);

  const abilityRouteStatus = useCallback((profile: RoutingProfile, primaryInstance?: RuntimeInstance): {
    label: string;
    status: string;
  } => {
    if (!primaryInstance) {
      return { label: text('status_unconfigured', 'Not configured'), status: 'warning' };
    }
    const normalizedHealth = primaryInstance.health_status.trim().toLowerCase();
    if (normalizedHealth === 'error') {
      return { label: abilityModelHealthLabel(primaryInstance.health_status), status: 'error' };
    }
    if (normalizedHealth === 'degraded' || normalizedHealth === 'warning') {
      return { label: abilityModelHealthLabel(primaryInstance.health_status), status: 'warning' };
    }
    const normalizedProfileStatus = profile.status.trim().toLowerCase();
    if (normalizedProfileStatus && !['active', 'ready', 'configured', 'ok'].includes(normalizedProfileStatus)) {
      return { label: text('status_needs_config', 'Needs config'), status: 'pending' };
    }
    return { label: text('status_ok', 'Normal'), status: 'success' };
  }, [abilityModelHealthLabel, text]);

  function renderRouteStatus(routeStatus: { label: string; status: string }) {
    if (routeStatus.status === 'success') {
      return (
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {routeStatus.label}
        </span>
      );
    }
    return <BackofficeStatusBadge label={routeStatus.label} status={routeStatus.status} />;
  }

  const abilityRoutePolicySummary = useCallback((profile: RoutingProfile): string => {
    const timeoutSeconds = Math.round(profile.timeout_ms / 1000);
    const fallbackLabel = profile.allow_fallback
      ? text('policy_auto_fallback_enabled', 'Auto fallback enabled')
      : text('policy_auto_fallback_disabled', 'Fallback disabled');
    const retryLabel = profile.max_retries > 0
      ? text('policy_retry_suffix', ' · retry {{retries}}', { retries: String(profile.max_retries) })
      : '';
    return text('runtime_policy_summary', '{{timeout}}s · {{fallback}}{{retry}}', {
      fallback: fallbackLabel,
      timeout: String(timeoutSeconds),
      retry: retryLabel,
    });
  }, [text]);

  const abilityModelRows: AbilityModelRouteRow[] = useMemo(() => routingDrafts.map((profile) => {
    const primaryInstance = runtimeInstancesById.get(profile.candidate_instance_ids[0] || '');
    return {
      profile,
      primaryInstance,
      taskLabels: profile.tasks.map(abilityTaskLabel),
      routeTypeLabel: abilityRouteTypeLabel(profile),
    };
  }), [abilityRouteTypeLabel, abilityTaskLabel, routingDrafts, runtimeInstancesById]);

  const activeProfile = useMemo(
    () => routingDrafts.find((profile) => profile.profile_id === activeProfileId) || null,
    [activeProfileId, routingDrafts]
  );

  const activeProfileTitle = useMemo(() => {
    if (!activeProfile) return '';
    return abilityRouteTitle(activeProfile);
  }, [abilityRouteTitle, activeProfile]);

  const activeDialogModelData = useMemo(() => {
    if (!activeProfile) return null;
    const selectedIds = [activeProfile.candidate_instance_ids[0] || '', activeProfile.candidate_instance_ids[1] || ''];
    const selectedInstances = selectedIds
      .map((instanceId) => runtimeInstancesById.get(instanceId))
      .filter((instance): instance is RuntimeInstance => Boolean(instance));
    const candidates = routingCandidateInstancesFor(activeProfile);
    const allCandidates = [
      ...selectedInstances.filter((selected) => !candidates.some((candidate) => candidate.instance_id === selected.instance_id)),
      ...candidates,
    ].sort((left, right) => {
      if (selectedIds.includes(left.instance_id) && !selectedIds.includes(right.instance_id)) return -1;
      if (!selectedIds.includes(left.instance_id) && selectedIds.includes(right.instance_id)) return 1;
      const leftHealthy = left.health_status === 'healthy' ? 0 : 1;
      const rightHealthy = right.health_status === 'healthy' ? 0 : 1;
      if (leftHealthy !== rightHealthy) return leftHealthy - rightHealthy;
      return runtimeModelRouteLabel(left).localeCompare(runtimeModelRouteLabel(right));
    });
    const candidateCountsByProvider = allCandidates.reduce((counts, instance) => {
      counts.set(instance.provider_id, (counts.get(instance.provider_id) || 0) + 1);
      return counts;
    }, new Map<string, number>());
    const providerOptionsById = new Map<string, { providerId: string; label: string; candidateCount: number }>();
    Object.entries(providerDisplayNames).forEach(([providerId, label]) => {
      providerOptionsById.set(providerId, {
        providerId,
        label,
        candidateCount: candidateCountsByProvider.get(providerId) || 0,
      });
    });
    allCandidates.forEach((instance) => {
      if (providerOptionsById.has(instance.provider_id)) return;
      providerOptionsById.set(instance.provider_id, {
        providerId: instance.provider_id,
        label: instance.provider_display_name.trim() || providerDisplayName(instance.provider_id),
        candidateCount: candidateCountsByProvider.get(instance.provider_id) || 0,
      });
    });
    const providerOptions = Array.from(providerOptionsById.values())
      .sort((left, right) => left.label.localeCompare(right.label));
    const normalizedSearch = modelSearchQuery.trim().toLowerCase();
    const filteredCandidates = allCandidates.filter((instance) => {
      if (modelProviderFilter && instance.provider_id !== modelProviderFilter) return false;
      if (!normalizedSearch) return true;
      const haystack = [
        instance.provider_display_name || providerDisplayName(instance.provider_id),
        instance.provider_id,
        instance.adapter_type,
        instance.model_id,
        instance.instance_id,
        instance.endpoint_variant,
        instance.model_feature,
        instance.health_status,
        ...instance.capability_tags,
      ].join(' ').toLowerCase();
      return haystack.includes(normalizedSearch);
    }).slice(0, MAX_DIALOG_CANDIDATE_OPTIONS);
    return {
      selectedIds,
      selectedInstances,
      allCandidates,
      filteredCandidates,
      providerOptions,
    };
  }, [
    activeProfile,
    modelProviderFilter,
    modelSearchQuery,
    providerDisplayName,
    providerDisplayNames,
    routingCandidateInstancesFor,
    runtimeInstancesById,
    runtimeModelRouteLabel,
  ]);

  const activeProfileIsAudioGeneration = Boolean(
    activeProfile && (
      activeProfile.execution_kind === 'audio_generation' ||
      activeProfile.routing_intent.startsWith('audio.')
    )
  );
  const activeInspectorTab: AbilityModelInspectorTab = activeProfileIsAudioGeneration ? abilityModelInspectorTab : 'policy';
  const activeAudioPreviewSource = audioPreviewSource(audioPreviewJob);
  const activeAudioPreviewError = audioPreviewError ?? audioPreviewErrorFromJob(
    audioPreviewJob,
    text('audio_preview_error_failed_job', 'Audio preview generation failed.')
  );
  const activeAudioPreviewEvidence = activeAudioPreviewError
    ? [
      [text('audio_preview_error_code', 'Error code'), activeAudioPreviewError.errorCode],
      [text('audio_preview_site', 'Site'), activeAudioPreviewError.siteId],
      [text('audio_preview_site_status', 'Site status'), activeAudioPreviewError.siteStatus],
      [text('audio_preview_runtime_error_code', 'Runtime error'), activeAudioPreviewError.runtimeErrorCode],
      [text('audio_preview_model', 'Preview model'), [activeAudioPreviewError.providerId, activeAudioPreviewError.modelId].filter(Boolean).join(' / ')],
      [text('audio_preview_instance', 'Instance'), activeAudioPreviewError.instanceId],
      [text('audio_preview_profile', 'Route'), activeAudioPreviewError.profileId],
      [text('audio_preview_trace', 'Trace'), activeAudioPreviewError.traceId],
      [text('audio_preview_run', 'Run'), activeAudioPreviewError.runId],
    ].filter((item): item is [string, string] => Boolean(item[1]))
    : [];
  const activeAudioPreviewStatusLabel = audioPreviewJob?.status === 'succeeded'
    ? text('audio_preview_status_succeeded', 'Preview ready')
    : audioPreviewJob?.status === 'failed'
      ? text('audio_preview_status_failed', 'Preview failed')
      : audioPreviewJob?.status
        ? text('audio_preview_status_running', 'Generating')
        : '';
  const audioPreviewTextLength = audioPreviewText.trim().length;

  const activeCloudBindingModelData = useMemo(() => {
    if (!cloudBindingDialogRow) return null;
    const candidates = [...(routingData?.available_embedding_instances || [])].sort((left, right) => {
      const leftSelected = left.provider_id === cloudBindingDialogRow.provider_id && left.model_id === cloudBindingDialogRow.model_id;
      const rightSelected = right.provider_id === cloudBindingDialogRow.provider_id && right.model_id === cloudBindingDialogRow.model_id;
      if (leftSelected && !rightSelected) return -1;
      if (!leftSelected && rightSelected) return 1;
      const leftHealthy = left.health_status === 'healthy' ? 0 : 1;
      const rightHealthy = right.health_status === 'healthy' ? 0 : 1;
      if (leftHealthy !== rightHealthy) return leftHealthy - rightHealthy;
      return runtimeModelRouteLabel(left).localeCompare(runtimeModelRouteLabel(right));
    });
    const candidateCountsByProvider = candidates.reduce((counts, instance) => {
      counts.set(instance.provider_id, (counts.get(instance.provider_id) || 0) + 1);
      return counts;
    }, new Map<string, number>());
    const providerOptions = Array.from(candidateCountsByProvider.entries())
      .map(([providerId, candidateCount]) => ({
        providerId,
        label: candidates.find((instance) => instance.provider_id === providerId)?.provider_display_name.trim()
          || providerDisplayName(providerId),
        candidateCount,
      }))
      .sort((left, right) => left.label.localeCompare(right.label));
    const normalizedSearch = cloudBindingModelSearchQuery.trim().toLowerCase();
    const filteredCandidates = candidates.filter((instance) => {
      if (cloudBindingProviderFilter && instance.provider_id !== cloudBindingProviderFilter) return false;
      if (!normalizedSearch) return true;
      const haystack = [
        instance.provider_display_name || providerDisplayName(instance.provider_id),
        instance.provider_id,
        instance.adapter_type,
        instance.model_id,
        instance.instance_id,
        instance.endpoint_variant,
        instance.model_feature,
        instance.health_status,
        ...instance.capability_tags,
      ].join(' ').toLowerCase();
      return haystack.includes(normalizedSearch);
    }).slice(0, MAX_DIALOG_CANDIDATE_OPTIONS);
    return {
      candidates,
      filteredCandidates,
      providerOptions,
    };
  }, [
    cloudBindingDialogRow,
    cloudBindingModelSearchQuery,
    cloudBindingProviderFilter,
    providerDisplayName,
    routingData,
    runtimeModelRouteLabel,
  ]);

  const abilityScenarioCount = useMemo(
    () => routingDrafts.reduce((count, profile) => count + profile.tasks.length, 0),
    [routingDrafts]
  );
  const routeCount = routingDrafts.length;
  const modelCandidateCount =
    (routingData?.available_text_instances.length || 0) +
    (routingData?.available_vision_instances.length || 0) +
    (routingData?.available_image_instances.length || 0) +
    (routingData?.available_audio_instances.length || 0) +
    (routingData?.available_embedding_instances.length || 0);
  const headerSummary = text('header_summary', '{{abilities}} ability scenarios / {{routes}} routes / {{models}} model candidates', {
    abilities: String(abilityScenarioCount),
    routes: String(routeCount),
    models: String(modelCandidateCount),
  });

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
        return {
          ...profile,
          candidate_instance_ids: nextCandidates
            .map((value) => value.trim())
            .filter(Boolean)
            .filter((value, candidateIndex, values) => values.indexOf(value) === candidateIndex),
        };
      })
    );
  }

  async function saveAbilityModelProfile(profileId: string) {
    const profile = routingDrafts.find((item) => item.profile_id === profileId);
    if (!profile) {
      setDialogError(aiText('error_save_ability_models', 'Failed to save ability-model routing.'));
      return;
    }
    setSavingRouting(true);
    setDialogError('');
    setDialogMessage('');
    setDialogReceipt(null);
    setPageError('');
    setPageMessage('');
    try {
      const response = await fetch('/api/admin/ability-models/plugin-routing', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': generateIdempotencyKey('ability_models_routing'),
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
        throw new Error(resolveAdminApiPayloadMessage(payload, aiText('error_save_ability_models', 'Failed to save ability-model routing.')));
      }
      const normalized = normalizeRoutingData(payload.data);
      setRoutingData(normalized);
      setRoutingDrafts(normalized.profiles.map((item) => ({ ...item, note: '' })));
      setDialogReceipt((payload.data?.receipt || null) as AdminMutationReceiptPayload | null);
      setDialogMessage(aiText('message_ability_models_saved', 'Ability-model routing saved.'));
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : aiText('error_save_ability_models', 'Failed to save ability-model routing.'));
    } finally {
      setSavingRouting(false);
    }
  }

  async function saveCloudAbilityRuntimeBinding(instanceId: string) {
    if (!cloudBindingDialogRow) return;
    setSavingCloudBinding(true);
    setDialogError('');
    setDialogMessage('');
    setDialogReceipt(null);
    setPageError('');
    setPageMessage('');
    try {
      const response = await fetch('/api/admin/ability-models/runtime-binding', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': generateIdempotencyKey('ability_models_runtime_binding'),
        },
        body: JSON.stringify({
          ability_id: cloudBindingDialogRow.ability_id,
          instance_id: instanceId,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveAdminApiPayloadMessage(payload, text('error_save_cloud_binding', 'Failed to save runtime model binding.')));
      }
      const updatedRows = normalizeCloudAbilityRuntimeRows(payload.data);
      setCloudAbilityRows(updatedRows);
      setCloudBindingDialogRow(
        updatedRows.find((row) => row.ability_id === cloudBindingDialogRow.ability_id) || cloudBindingDialogRow
      );
      setDialogReceipt((payload.data?.receipt || null) as AdminMutationReceiptPayload | null);
      setDialogMessage(text('message_cloud_binding_saved', 'Runtime model binding saved.'));
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : text('error_save_cloud_binding', 'Failed to save runtime model binding.'));
    } finally {
      setSavingCloudBinding(false);
    }
  }

  const loadAudioPreviewJob = useCallback(async (runId: string) => {
    try {
      const response = await fetch(`/api/admin/audio-jobs/${encodeURIComponent(runId)}`, {
        credentials: 'include',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setAudioPreviewError(normalizeAudioPreviewError(payload, text('audio_preview_error_load', 'Failed to load audio preview.')));
        return;
      }
      setAudioPreviewJob(payload.data as AudioPreviewJob);
    } catch (error) {
      setAudioPreviewError({
        message: error instanceof Error ? error.message : text('audio_preview_error_load', 'Failed to load audio preview.'),
      });
    }
  }, [text]);

  async function createAudioPreview() {
    if (!activeProfile || !activeProfileIsAudioGeneration) return;
    const previewInstanceId = activeProfile.candidate_instance_ids[0] || '';
    if (!previewInstanceId) {
      setAudioPreviewError({ message: text('audio_preview_error_no_model', 'Select a primary audio model before previewing.') });
      return;
    }
    const previewText = audioPreviewText.trim();
    if (previewText.length < 10) {
      setAudioPreviewError({ message: text('audio_preview_error_text_required', 'Enter at least 10 characters for the audio preview.') });
      return;
    }
    setAudioPreviewCreating(true);
    setAudioPreviewError(null);
    setAudioPreviewJob(null);
    try {
      const response = await fetch('/api/admin/audio-jobs', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': generateIdempotencyKey('ability_audio_preview'),
        },
        body: JSON.stringify({
          intent: 'article_narration',
          title: text('audio_preview_title', 'Audio model preview'),
          body: previewText,
          format: 'mp3',
          preview_instance_id: previewInstanceId,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setAudioPreviewError(normalizeAudioPreviewError(payload, text('audio_preview_error_create', 'Failed to create audio preview.')));
        return;
      }
      setAudioPreviewJob(payload.data as AudioPreviewJob);
    } catch (error) {
      setAudioPreviewError({
        message: error instanceof Error ? error.message : text('audio_preview_error_create', 'Failed to create audio preview.'),
      });
    } finally {
      setAudioPreviewCreating(false);
    }
  }

  useEffect(() => {
    if (!audioPreviewJob?.run_id || ['succeeded', 'failed', 'canceled'].includes(audioPreviewJob.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadAudioPreviewJob(audioPreviewJob.run_id);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [audioPreviewJob?.run_id, audioPreviewJob?.status, loadAudioPreviewJob]);

  function openAbilityModelDialog(profileId: string) {
    const profile = routingDrafts.find((item) => item.profile_id === profileId);
    setActiveProfileId(profileId);
    setModelProviderFilter('');
    setModelSearchQuery('');
    setAdvancedRuntimePolicyOpen(false);
    setAbilityModelInspectorTab(
      profile && (profile.execution_kind === 'audio_generation' || profile.routing_intent.startsWith('audio.'))
        ? 'preview'
        : 'policy'
    );
    setDialogError('');
    setDialogMessage('');
    setDialogReceipt(null);
    setPageError('');
    setPageMessage('');
    setAudioPreviewJob(null);
    setAudioPreviewError(null);
    setAudioPreviewText(text('audio_preview_sample_text', 'This is a short audio sample for checking the selected voice model.'));
    setAudioPreviewCreating(false);
  }

  function openCloudBindingDialog(row: CloudAbilityRuntimeRow) {
    if (!row.can_configure) return;
    setCloudBindingDialogRow(row);
    setCloudBindingProviderFilter('');
    setCloudBindingModelSearchQuery('');
    setDialogError('');
    setDialogMessage('');
    setDialogReceipt(null);
    setPageError('');
    setPageMessage('');
  }

  function closeAbilityModelDialog() {
    setActiveProfileId('');
    setModelProviderFilter('');
    setModelSearchQuery('');
    setAdvancedRuntimePolicyOpen(false);
    setAbilityModelInspectorTab('policy');
    setDialogError('');
    setDialogMessage('');
    setDialogReceipt(null);
    setAudioPreviewJob(null);
    setAudioPreviewError(null);
    setAudioPreviewText(text('audio_preview_sample_text', 'This is a short audio sample for checking the selected voice model.'));
    setAudioPreviewCreating(false);
  }

  function closeCloudBindingDialog() {
    setCloudBindingDialogRow(null);
    setCloudBindingProviderFilter('');
    setCloudBindingModelSearchQuery('');
    setDialogError('');
    setDialogMessage('');
    setDialogReceipt(null);
  }

  const availableCloudMediaTabs = useMemo(
    () => CLOUD_MEDIA_ORDER.filter((media) => cloudAbilityRows.some((row) => row.media === media)),
    [cloudAbilityRows]
  );
  const activeCloudNativeAbilityRows = activeCloudMediaFilter === 'all'
    ? cloudAbilityRows
    : cloudAbilityRows.filter((row) => row.media === activeCloudMediaFilter);

  useEffect(() => {
    if (activeCloudMediaFilter !== 'all' && !availableCloudMediaTabs.includes(activeCloudMediaFilter)) {
      setActiveCloudMediaFilter('all');
    }
  }, [activeCloudMediaFilter, availableCloudMediaTabs]);

  if (loading) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={text('eyebrow', 'Runtime model routing')}
        title={text('title', 'Ability-model routing')}
        description={text('description', 'Configure shared plugin ability-to-model routing and Cloud-native runtime model bindings.')}
        descriptionDisplay="hint"
        aside={(
          <div className="flex flex-col items-start gap-2 xl:items-end">
            <BackofficeStatusBadge label={text('badge_runtime_binding', 'Runtime binding')} status="success" />
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
              {headerSummary}
            </p>
          </div>
        )}
        contentClassName="py-5 md:py-5"
      >
        {pageMessage ? (
          <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200">
            {pageMessage}
          </BackofficeStackCard>
        ) : null}
        {pageError ? (
          <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
            {pageError}
          </BackofficeStackCard>
        ) : null}
      </BackofficePrimaryPanel>

      <div className="flex flex-wrap gap-2">
        <BackofficeFilterPill
          active={activeAbilityTab === 'wordpress'}
          onClick={() => setActiveAbilityTab('wordpress')}
        >
          {text('tab_wordpress', 'Plugin ability routing')}
        </BackofficeFilterPill>
        <BackofficeFilterPill
          active={activeAbilityTab === 'cloud'}
          onClick={() => setActiveAbilityTab('cloud')}
        >
          {text('tab_cloud', 'Cloud-native abilities')}
        </BackofficeFilterPill>
      </div>

      {activeAbilityTab === 'wordpress' ? (
        <BackofficeSectionPanel>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
              {text('wordpress_title', 'WordPress plugin AI ability-model routes')}
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {aiText('ability_models_desc', 'WordPress plugin AI ability scenarios mapped to Cloud runtime model configurations. Plugin-specific overrides can be added later when a plugin needs a different model.')}
            </p>
          </div>
          <button
            type="button"
            className="btn btn-secondary justify-center"
            disabled={loadingRouting}
            onClick={() => void loadRouting()}
          >
            {loadingRouting ? aiText('loading', 'Loading...') : aiText('action_refresh', 'Refresh')}
          </button>
        </div>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="hidden grid-cols-[7rem_1.7fr_6rem_1.45fr_1.15fr_7rem] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400 md:grid">
            <span>{aiText('column_status', 'Status')}</span>
            <span>{text('column_route_group', 'Ability scenario')}</span>
            <span>{text('column_route_type', 'Type')}</span>
            <span>{text('column_current_model', 'Current model')}</span>
            <span>{text('column_runtime_policy', 'Runtime policy')}</span>
            <span className="text-right">{aiText('column_actions', 'Actions')}</span>
          </div>
          {abilityModelRows.map((row) => (
            <div
              key={row.profile.profile_id}
              className="grid gap-3 border-b border-slate-200 px-4 py-4 text-sm last:border-b-0 dark:border-slate-800 md:grid-cols-[7rem_1.7fr_6rem_1.45fr_1.15fr_7rem] md:items-center"
            >
              {(() => {
                const routeStatus = abilityRouteStatus(row.profile, row.primaryInstance);
                return renderRouteStatus(routeStatus);
              })()}
              <div>
                <div className="font-medium text-slate-950 dark:text-white">{abilityRouteTitle(row.profile)}</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {row.taskLabels.map((label) => (
                    <span
                      key={`${row.profile.profile_id}-${label}`}
                      className="rounded-full border border-slate-200 px-2 py-0.5 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300"
                    >
                      {label}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400 md:hidden">
                  {text('column_route_type', 'Type')}
                </div>
                <span className="mt-1 inline-flex rounded-full border border-slate-200 px-2 py-0.5 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300 md:mt-0">
                  {row.routeTypeLabel}
                </span>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400 md:hidden">
                  {text('column_current_model', 'Current model')}
                </div>
                <div className="mt-1 text-sm font-medium text-slate-800 dark:text-slate-100 md:mt-0">
                  {runtimeModelRouteLabel(row.primaryInstance)}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400 md:hidden">
                  {text('column_runtime_policy', 'Runtime policy')}
                </div>
                <div className="mt-1 md:mt-0">{abilityRoutePolicySummary(row.profile)}</div>
              </div>
              <div className="md:text-right">
                <button
                  type="button"
                  className="btn btn-secondary w-full justify-center md:w-auto"
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
                : aiText('ability_models_empty', 'No plugin ability-model routing is available.')}
            </div>
          )}
        </div>
          <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {aiText('ability_models_boundary_notice', 'This changes Cloud runtime model routing only. It does not enable plugin abilities, edit prompts, or write to WordPress.')}
          </div>
        <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
          {text('plugin_default_notice', 'These are common defaults for plugin abilities. Plugin switches, prompts, approvals, and final WordPress writes stay in the local plugin path.')}
        </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeAbilityTab === 'cloud' ? (
        <BackofficeSectionPanel>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
                {text('cloud_native_title', 'Cloud runtime dependencies')}
              </h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {text('cloud_native_desc', 'Read-only projection for Cloud-owned services. It shows runtime dependencies and only exposes bounded model binding where Cloud supports it.')}
              </p>
            </div>
            <BackofficeStatusBadge label={text('cloud_native_badge_runtime_binding', 'Runtime binding')} status="success" />
          </div>

          {cloudAbilityRows.length > 0 ? (
            <>
              <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
              <div className="hidden grid-cols-[7rem_8rem_1.55fr_1.05fr_1.3fr_9rem] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400 md:grid md:items-center">
                <span>{aiText('column_status', 'Status')}</span>
                <span>
                  <select
                    className="h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold normal-case tracking-normal text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200"
                    value={activeCloudMediaFilter}
                    onChange={(event) => setActiveCloudMediaFilter(event.target.value as CloudAbilityMediaFilter)}
                    aria-label={text('field_category_filter', 'Category filter')}
                  >
                    <option value="all">{text('filter_category_all', 'All categories')}</option>
                    {availableCloudMediaTabs.map((tab) => (
                      <option key={tab} value={tab}>
                        {text(`cloud_media_tab_${tab}`, tab)}
                      </option>
                    ))}
                  </select>
                </span>
                <span>{aiText('column_ability', 'Ability')}</span>
                <span>{text('column_runtime_dependency', 'Runtime dependency')}</span>
                <span>{text('column_current_runtime', 'Current runtime')}</span>
                <span className="text-right">{aiText('column_actions', 'Actions')}</span>
              </div>
              {activeCloudNativeAbilityRows.length > 0 ? (
                activeCloudNativeAbilityRows.map((row) => (
                  <div
                    key={row.ability_id}
                    className="grid gap-3 border-b border-slate-200 px-4 py-4 text-sm last:border-b-0 dark:border-slate-800 md:grid-cols-[7rem_8rem_1.55fr_1.05fr_1.3fr_9rem] md:items-center"
                  >
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400 md:hidden">
                        {aiText('column_status', 'Status')}
                      </div>
                      <div className={`mt-1 text-sm font-medium md:mt-0 ${cloudAbilityStatusClassName(row.status)}`}>
                        {cloudAbilityStatusLabel(row.status)}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400 md:hidden">
                        {text('column_category', 'Category')}
                      </div>
                      <span className="mt-1 inline-flex rounded-full border border-slate-200 px-2 py-0.5 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300 md:mt-0">
                        {text(`cloud_media_tab_${row.media}`, row.media)}
                      </span>
                    </div>
                    <div>
                      <div className="font-medium text-slate-950 dark:text-white">{cloudAbilityLabel(row)}</div>
                      <div className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{cloudAbilityDescription(row)}</div>
                      <details className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        <summary className="cursor-pointer select-none font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
                          {text('cloud_native_internal_details', 'Internal details')}
                        </summary>
                        <dl className="mt-2 grid gap-1 rounded-lg bg-slate-50 p-2 dark:bg-slate-900/45">
                          <div className="grid gap-1 sm:grid-cols-[6rem_1fr]">
                            <dt>{text('cloud_native_internal_config_id', 'Config ID')}</dt>
                            <dd className="font-mono text-slate-700 dark:text-slate-200">
                              {row.profile_id || text('cloud_native_internal_none', 'None')}
                            </dd>
                          </div>
                          <div className="grid gap-1 sm:grid-cols-[6rem_1fr]">
                            <dt>{text('cloud_native_internal_supplier', 'Supplier')}</dt>
                            <dd>{row.provider_id ? providerDisplayName(row.provider_id) : text('cloud_native_internal_managed', 'Cloud managed')}</dd>
                          </div>
                          <div className="grid gap-1 sm:grid-cols-[6rem_1fr]">
                            <dt>{text('cloud_native_internal_model', 'Model')}</dt>
                            <dd>{row.model_id || text('cloud_native_internal_no_model', 'No model binding required')}</dd>
                          </div>
                        </dl>
                      </details>
                    </div>
                    <div className="text-slate-600 dark:text-slate-300">
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400 md:hidden">
                        {text('column_runtime_dependency', 'Runtime dependency')}
                      </div>
                      <div className="mt-1 md:mt-0">{cloudAbilityModelKindLabel(row.model_kind)}</div>
                    </div>
                    <div className="text-slate-600 dark:text-slate-300">
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400 md:hidden">
                        {text('column_current_runtime', 'Current runtime')}
                      </div>
                      <div className="mt-1 font-medium text-slate-800 dark:text-slate-100 md:mt-0">
                        {cloudAbilityRuntimeLabel(row)}
                      </div>
                      {!row.provider_id && !row.model_id ? (
                        <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {text('cloud_native_no_model_note', 'No separate provider/model choice is required for this row.')}
                        </div>
                      ) : null}
                    </div>
                    <div className="text-right">
                      {row.can_configure ? (
                        <button
                          type="button"
                          className="btn btn-secondary justify-center"
                          onClick={() => openCloudBindingDialog(row)}
                        >
                          {text('cloud_native_action_configure_model', 'Configure model')}
                        </button>
                      ) : (
                        <span className="inline-flex max-w-full justify-end text-xs font-medium leading-5 text-slate-500 dark:text-slate-400">
                          {cloudManagedDependencyLabel(row)}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="px-4 py-6 text-sm text-slate-500 dark:text-slate-400">
                  {text('cloud_category_filter_empty', 'No Cloud runtime abilities match this category.')}
                </div>
              )}
              </div>
            </>
          ) : null}

          {cloudAbilityRows.length === 0 ? (
            <div className="mt-4">
              <BackofficeEmptyState
                title={text('cloud_all_empty_title', 'No Cloud runtime abilities')}
                description={text('cloud_all_empty_desc', 'No read-only runtime projection is available yet.')}
              />
            </div>
          ) : null}

          <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {text('cloud_native_boundary_notice', 'This surface only binds supported Cloud runtime models. It does not define abilities, edit prompts or routers, or write to WordPress.')}
          </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeProfile && typeof document !== 'undefined' ? createPortal((
        <div
          className="fixed inset-0 z-[2147483647] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="ability-model-dialog-title"
        >
          <div className="absolute inset-0 bg-slate-950/55" />
          <div className="relative z-10 max-h-[90vh] w-full max-w-6xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-950">
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 dark:border-slate-800 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 id="ability-model-dialog-title" className="text-xl font-semibold text-slate-950 dark:text-white">
                  {aiText('ability_model_dialog_title', 'Configure ability-model route')}
                </h2>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {aiText('ability_model_dialog_desc', 'This updates one shared Cloud runtime route. Plugin switches, prompts, approvals, and final writes are not changed.')}
                </p>
              </div>
              <button type="button" className="btn btn-secondary" onClick={closeAbilityModelDialog}>
                {aiText('action_close_dialog', 'Close')}
              </button>
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
              <div className="space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="text-base font-semibold text-slate-950 dark:text-white">{activeProfileTitle}</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {activeProfile.tasks.map((taskId) => (
                        <span
                          key={taskId}
                          className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300"
                        >
                          {abilityTaskLabel(taskId)}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  {[0, 1].map((index) => {
                    const selectedId = activeDialogModelData?.selectedIds[index] || '';
                    const selected = selectedId ? runtimeInstancesById.get(selectedId) : undefined;
                    return (
                      <div
                        key={`${activeProfile.profile_id}-selected-${index}`}
                        className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-900/30"
                      >
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                          {index === 0 ? aiText('ability_model_primary_model', 'Primary model') : aiText('ability_model_fallback_model', 'Fallback model')}
                        </div>
                        <div className="mt-2 truncate text-sm font-semibold text-slate-950 dark:text-white">
                          {selected
                            ? runtimeModelRouteLabel(selected)
                            : aiText('ability_model_unassigned', 'Unassigned')}
                        </div>
                        {selected ? (
                          <>
                            <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                              {abilityModelRuntimeSummary(selected)}
                            </p>
                            <details className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              <summary className="cursor-pointer select-none font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
                                {text('cloud_native_internal_details', 'Internal details')}
                              </summary>
                              <div className="mt-1 rounded-lg bg-white p-2 font-mono text-[0.7rem] leading-5 text-slate-600 dark:bg-slate-950/70 dark:text-slate-300">
                                {abilityModelInstanceDetail(selected)}
                              </div>
                            </details>
                          </>
                        ) : null}
                        {index === 1 && selected ? (
                          <button
                            type="button"
                            className="mt-2 text-xs font-semibold text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                            onClick={() => updateRoutingCandidate(activeProfile.profile_id, 1, '')}
                          >
                            {text('action_clear_fallback_model', 'Clear fallback')}
                          </button>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
                  <div className="grid gap-3 border-b border-slate-200 bg-slate-50/80 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/35 lg:grid-cols-[minmax(0,1fr)_180px_220px] lg:items-end">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                        {text('available_models_title', 'Available models')}
                      </div>
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {text('ability_model_candidate_count', '{{count}} matching runtime candidates shown', {
                          count: String(activeDialogModelData?.filteredCandidates.length || 0),
                        })}
                      </div>
                    </div>
                    <label className="block">
                      <span className="sr-only">{text('field_model_provider_filter', 'Supplier')}</span>
                      <select
                        value={modelProviderFilter}
                        onChange={(event) => setModelProviderFilter(event.target.value)}
                        className="h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                        aria-label={text('field_model_provider_filter', 'Supplier')}
                      >
                        <option value="">{text('filter_provider_all', 'All suppliers')}</option>
                        {(activeDialogModelData?.providerOptions || []).map((option) => (
                          <option
                            key={option.providerId}
                            value={option.providerId}
                            disabled={option.candidateCount === 0}
                          >
                            {option.label} ({option.candidateCount})
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block">
                      <span className="sr-only">{text('field_model_search', 'Search models')}</span>
                      <input
                        type="search"
                        value={modelSearchQuery}
                        onChange={(event) => setModelSearchQuery(event.target.value)}
                        placeholder={text('placeholder_model_search', 'Search by supplier or model name')}
                        className="h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                        aria-label={text('field_model_search', 'Search models')}
                      />
                    </label>
                  </div>
                  <div className="max-h-[360px] overflow-y-auto">
                    {(activeDialogModelData?.filteredCandidates.length || 0) > 0 ? (
                      activeDialogModelData?.filteredCandidates.map((instance) => {
                        const isPrimary = activeDialogModelData.selectedIds[0] === instance.instance_id;
                        const isFallback = activeDialogModelData.selectedIds[1] === instance.instance_id;
                        const statusLabel = abilityModelHealthLabel(instance.health_status);
                        return (
                          <div
                            key={`${activeProfile.profile_id}-candidate-${instance.instance_id}`}
                            className="grid gap-3 border-b border-slate-200 px-3 py-2.5 last:border-b-0 dark:border-slate-800 md:grid-cols-[minmax(0,1fr)_120px_190px] md:items-center"
                          >
                            <div className="min-w-0">
                              <div className="flex min-w-0 flex-wrap items-center gap-2">
                                <span className="truncate text-sm font-semibold text-slate-950 dark:text-white">
                                  {runtimeModelCandidateLabel(instance)}
                                </span>
                                <span className="rounded-full border border-slate-200 px-2 py-0.5 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
                                  {statusLabel}
                                </span>
                              </div>
                              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                                {abilityModelRuntimeSummary(instance)}
                              </p>
                              <details className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                <summary className="cursor-pointer select-none font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
                                  {text('cloud_native_internal_details', 'Internal details')}
                                </summary>
                                <div className="mt-1 rounded-lg bg-slate-50 p-2 font-mono text-[0.7rem] leading-5 text-slate-600 dark:bg-slate-900/55 dark:text-slate-300">
                                  {abilityModelInstanceDetail(instance)}
                                </div>
                              </details>
                            </div>
                            <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
                              {isPrimary
                                ? aiText('ability_model_primary_model', 'Primary model')
                                : isFallback
                                  ? aiText('ability_model_fallback_model', 'Fallback model')
                                  : text('candidate_role_available', 'Available')}
                            </div>
                            <div className="flex flex-wrap gap-2 md:justify-end">
                              <button
                                type="button"
                                className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:text-slate-200 dark:hover:bg-slate-900"
                                disabled={isPrimary}
                                onClick={() => updateRoutingCandidate(activeProfile.profile_id, 0, instance.instance_id)}
                              >
                                {text('action_set_primary_model', 'Set primary')}
                              </button>
                              <button
                                type="button"
                                className="rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:text-slate-200 dark:hover:bg-slate-900"
                                disabled={isFallback}
                                onClick={() => updateRoutingCandidate(activeProfile.profile_id, 1, instance.instance_id)}
                              >
                                {text('action_set_fallback_model', 'Set fallback')}
                              </button>
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="grid gap-1 px-3 py-5 text-sm text-slate-500 dark:text-slate-400">
                        <div className="font-semibold text-slate-700 dark:text-slate-200">
                          {text('model_search_empty', 'No enabled runtime model matches the current filters.')}
                        </div>
                        <div className="text-xs leading-5">
                          {text('model_search_empty_hint', 'Enable models in Model suppliers first. Ability routes can only use models listed in the supplier model allowlist.')}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              <div className="space-y-3 lg:sticky lg:top-0 lg:self-start">
                <div className="overflow-hidden rounded-xl border border-slate-200 bg-white/70 dark:border-slate-800 dark:bg-slate-950/40">
                  {activeProfileIsAudioGeneration ? (
                    <div className="grid grid-cols-2 border-b border-slate-200 bg-slate-50/80 p-1 dark:border-slate-800 dark:bg-slate-900/35">
                      {(['policy', 'preview'] as AbilityModelInspectorTab[]).map((tab) => (
                        <button
                          key={tab}
                          type="button"
                          className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                            activeInspectorTab === tab
                              ? 'bg-white text-slate-950 shadow-sm dark:bg-slate-950 dark:text-white'
                              : 'text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
                          }`}
                          onClick={() => setAbilityModelInspectorTab(tab)}
                        >
                          {tab === 'policy'
                            ? text('inspector_tab_policy', 'Policy')
                            : text('inspector_tab_preview', 'Preview')}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  <div className="p-3">
                    {activeInspectorTab === 'policy' ? (
                      <div className="space-y-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                          {text('runtime_policy_summary_title', 'Runtime policy')}
                        </div>
                        <dl className="grid gap-2 text-sm">
                          <div className="flex items-center justify-between gap-3">
                            <dt className="text-slate-500 dark:text-slate-400">{text('field_timeout_seconds', 'Timeout')}</dt>
                            <dd className="font-medium text-slate-950 dark:text-white">
                              {text('timeout_seconds_value', '{{seconds}}s', { seconds: String(Math.round(activeProfile.timeout_ms / 1000)) })}
                            </dd>
                          </div>
                          <div className="flex items-center justify-between gap-3">
                            <dt className="text-slate-500 dark:text-slate-400">{aiText('field_allow_fallback', 'Provider fallback')}</dt>
                            <dd className="font-medium text-slate-950 dark:text-white">
                              {activeProfile.allow_fallback ? text('policy_enabled', 'Enabled') : text('policy_disabled', 'Disabled')}
                            </dd>
                          </div>
                          <div className="flex items-center justify-between gap-3">
                            <dt className="text-slate-500 dark:text-slate-400">{aiText('field_retry_max', 'Retry max')}</dt>
                            <dd className="font-medium text-slate-950 dark:text-white">{activeProfile.max_retries}</dd>
                          </div>
                        </dl>
                        <button
                          type="button"
                          className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-left text-sm font-semibold text-slate-800 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-100 dark:hover:bg-slate-900"
                          aria-expanded={advancedRuntimePolicyOpen}
                          onClick={() => setAdvancedRuntimePolicyOpen((current) => !current)}
                        >
                          <span>{text('advanced_runtime_policy_title', 'Advanced runtime policy')}</span>
                          <span className="text-slate-500 dark:text-slate-400">{advancedRuntimePolicyOpen ? '-' : '+'}</span>
                        </button>
                        {advancedRuntimePolicyOpen ? (
                          <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/40">
                            <label className="block">
                              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                                {aiText('field_timeout_ms', 'Timeout ms')}
                              </span>
                              <input
                                type="number"
                                min={1000}
                                max={activeProfile.max_timeout_ms}
                                step={1000}
                                value={activeProfile.timeout_ms}
                                onChange={(event) =>
                                  updateRoutingDraft(activeProfile.profile_id, {
                                    timeout_ms: Number(event.target.value) || 30000,
                                  })
                                }
                                className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                              />
                            </label>
                            <label className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
                              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                                {aiText('field_allow_fallback', 'Provider fallback')}
                              </span>
                              <input
                                type="checkbox"
                                checked={activeProfile.allow_fallback}
                                onChange={(event) =>
                                  updateRoutingDraft(activeProfile.profile_id, {
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
                                value={activeProfile.max_retries}
                                onChange={(event) =>
                                  updateRoutingDraft(activeProfile.profile_id, {
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
                                value={activeProfile.note}
                                onChange={(event) => updateRoutingDraft(activeProfile.profile_id, { note: event.target.value })}
                                rows={3}
                                className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                                placeholder={aiText('placeholder_ability_model_note', 'Why this ability-model route is being changed')}
                              />
                            </label>
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div className="space-y-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                              {text('audio_preview_title_panel', 'Audio preview')}
                            </div>
                            <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                              {text('audio_preview_desc', 'Generate a short sample with the selected primary model. This does not save the route or write to WordPress.')}
                            </p>
                          </div>
                          {activeAudioPreviewStatusLabel ? (
                            <span
                              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                                audioPreviewJob?.status === 'failed'
                                  ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/35 dark:text-rose-200'
                                  : audioPreviewJob?.status === 'succeeded'
                                    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/35 dark:text-emerald-200'
                                    : 'bg-blue-50 text-blue-700 dark:bg-blue-950/35 dark:text-blue-200'
                              }`}
                            >
                              {activeAudioPreviewStatusLabel}
                            </span>
                          ) : null}
                        </div>
                        {activeAudioPreviewSource ? (
                          <audio className="w-full" controls src={activeAudioPreviewSource}>
                            {text('audio_preview_unsupported', 'Your browser does not support audio playback.')}
                          </audio>
                        ) : audioPreviewJob && !['failed', 'canceled'].includes(audioPreviewJob.status) ? (
                          <div className="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                            {text('audio_preview_waiting', 'Waiting for a playable preview artifact.')}
                          </div>
                        ) : null}
                        <label className={`grid gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300 ${activeAudioPreviewSource ? 'rounded-lg border border-slate-200 p-2 dark:border-slate-800' : ''}`}>
                          {activeAudioPreviewSource ? text('audio_preview_edit_text', 'Preview text') : text('audio_preview_text_label', 'Preview text')}
                          <textarea
                            className="min-h-20 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal leading-6 text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                            value={audioPreviewText}
                            maxLength={500}
                            onChange={(event) => {
                              setAudioPreviewText(event.target.value);
                              setAudioPreviewError(null);
                            }}
                            placeholder={text('audio_preview_text_placeholder', 'Enter the text to read in the selected audio model.')}
                          />
                          <span className="font-normal text-slate-500 dark:text-slate-400">
                            {text('audio_preview_text_help', '{{count}}/500 characters. Use a short sentence or paragraph for model audition.', {
                              count: String(audioPreviewTextLength),
                            })}
                          </span>
                        </label>
                        <button
                          type="button"
                          className="btn btn-secondary w-full justify-center disabled:cursor-not-allowed disabled:opacity-60"
                          disabled={audioPreviewCreating || !activeProfile.candidate_instance_ids[0]}
                          onClick={() => void createAudioPreview()}
                        >
                          {audioPreviewCreating ? text('audio_preview_creating', 'Creating preview...') : text('audio_preview_action', 'Preview audio')}
                        </button>
                        {activeAudioPreviewError ? (
                          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
                            <div className="font-semibold">{activeAudioPreviewError.message}</div>
                            {activeAudioPreviewEvidence.length ? (
                              <div className="mt-2 grid gap-1 text-rose-700 dark:text-rose-200/80">
                                {activeAudioPreviewEvidence.map(([label, value]) => (
                                  <div key={label}>
                                    {label}: {value}
                                  </div>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        {audioPreviewJob ? (
                          <details className="rounded-lg border border-slate-200 px-3 py-2 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">
                            <summary className="cursor-pointer font-semibold text-slate-600 dark:text-slate-300">
                              {text('audio_preview_run_detail', 'Run detail')}
                            </summary>
                            <div className="mt-2 break-all">
                              {text('audio_preview_model', 'Preview model')}: {audioPreviewJob.provider_id || '-'} / {audioPreviewJob.model_id || '-'}
                            </div>
                            <div className="mt-1 break-all">
                              {text('audio_preview_run', 'Run')}: {audioPreviewJob.run_id}
                            </div>
                          </details>
                        ) : null}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
            <div className="sticky bottom-0 z-10 -mx-6 mt-5 grid gap-3 border-t border-slate-200 bg-white/95 px-6 py-4 text-sm text-slate-600 shadow-[0_-12px_24px_rgba(15,23,42,0.04)] backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 dark:text-slate-300">
              <div className="grid gap-2">
                <span>{aiText('ability_model_save_notice', 'Saving updates the Cloud runtime profile binding used by this ability route.')}</span>
                {dialogMessage ? (
                  <span
                    className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200"
                    role="status"
                    aria-live="polite"
                  >
                    {dialogMessage}
                  </span>
                ) : null}
                {dialogError ? (
                  <span
                    className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200"
                    role="alert"
                  >
                    {dialogError}
                  </span>
                ) : null}
                <AdminMutationReceipt receipt={dialogReceipt} />
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
                  disabled={savingRouting || !activeProfile.candidate_instance_ids.length}
                  onClick={() => void saveAbilityModelProfile(activeProfile.profile_id)}
                >
                  {savingRouting ? aiText('saving', 'Saving...') : aiText('action_save_ability_model', 'Save route')}
                </button>
              </div>
            </div>
          </div>
        </div>
      ), document.body) : null}

      {cloudBindingDialogRow && typeof document !== 'undefined' ? createPortal((
        <div
          className="fixed inset-0 z-[2147483647] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="cloud-binding-dialog-title"
        >
          <div className="absolute inset-0 bg-slate-950/55" />
          <div className="relative z-10 max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-950">
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 dark:border-slate-800 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 id="cloud-binding-dialog-title" className="text-xl font-semibold text-slate-950 dark:text-white">
                  {text('cloud_binding_dialog_title', 'Configure runtime model')}
                </h2>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {text('cloud_binding_dialog_desc', 'Select the embedding model used by Site Knowledge retrieval. WordPress abilities, prompts, routers, and writes are not changed.')}
                </p>
              </div>
              <button type="button" className="btn btn-secondary" onClick={closeCloudBindingDialog}>
                {aiText('action_close_dialog', 'Close')}
              </button>
            </div>

            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/40">
              <div className="text-base font-semibold text-slate-950 dark:text-white">
                {cloudAbilityLabel(cloudBindingDialogRow)}
              </div>
              <div className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {cloudAbilityDescription(cloudBindingDialogRow)}
              </div>
              <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    {text('cloud_binding_current_model', 'Current model')}
                  </dt>
                  <dd className="mt-1 font-medium text-slate-900 dark:text-slate-100">
                    {modelRouteLabel(cloudBindingDialogRow.provider_id, cloudBindingDialogRow.model_id)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    {text('column_category', 'Category')}
                  </dt>
                  <dd className="mt-1 font-medium text-slate-900 dark:text-slate-100">
                    {text(`cloud_media_tab_${cloudBindingDialogRow.media}`, cloudBindingDialogRow.media)}
                  </dd>
                </div>
              </dl>
              <details className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                <summary className="cursor-pointer select-none font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
                  {text('cloud_native_internal_details', 'Internal details')}
                </summary>
                <dl className="mt-2 grid gap-1 rounded-lg bg-white p-2 dark:bg-slate-950/70">
                  <div className="grid gap-1 sm:grid-cols-[6rem_1fr]">
                    <dt>{text('cloud_native_internal_config_id', 'Config ID')}</dt>
                    <dd className="font-mono text-slate-700 dark:text-slate-200">
                      {cloudBindingDialogRow.profile_id || 'embed.default'}
                    </dd>
                  </div>
                </dl>
              </details>
            </div>

            <div className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-950 md:grid-cols-[0.85fr_1.15fr]">
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                  {text('field_model_provider_filter', 'Supplier')}
                </span>
                <select
                  value={cloudBindingProviderFilter}
                  onChange={(event) => setCloudBindingProviderFilter(event.target.value)}
                  className="mt-2 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                >
                  <option value="">{text('filter_provider_all', 'All suppliers')}</option>
                  {(activeCloudBindingModelData?.providerOptions || []).map((option) => (
                    <option key={option.providerId} value={option.providerId}>
                      {option.label} ({option.candidateCount})
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                  {text('field_model_search', 'Search models')}
                </span>
                <input
                  type="search"
                  value={cloudBindingModelSearchQuery}
                  onChange={(event) => setCloudBindingModelSearchQuery(event.target.value)}
                  placeholder={text('placeholder_embedding_model_search', 'Search embedding models')}
                  className="mt-2 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                />
              </label>
            </div>

            <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/60">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                  {text('available_embedding_models_title', 'Available embedding models')}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {text('ability_model_candidate_count', '{{count}} matching runtime candidates shown', {
                    count: String(activeCloudBindingModelData?.filteredCandidates.length || 0),
                  })}
                </div>
              </div>
              <div className="max-h-[380px] overflow-y-auto">
                {(activeCloudBindingModelData?.filteredCandidates.length || 0) > 0 ? (
                  activeCloudBindingModelData?.filteredCandidates.map((instance) => {
                    const isSelected =
                      instance.provider_id === cloudBindingDialogRow.provider_id &&
                      instance.model_id === cloudBindingDialogRow.model_id;
                    return (
                      <div
                        key={`cloud-binding-${instance.instance_id}`}
                        className="grid gap-3 border-b border-slate-200 px-3 py-3 last:border-b-0 dark:border-slate-800 md:grid-cols-[1fr_auto] md:items-center"
                      >
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold text-slate-950 dark:text-white">
                              {runtimeModelRouteLabel(instance)}
                            </span>
                            <span className="rounded-full border border-slate-200 px-2 py-0.5 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
                              {abilityModelHealthLabel(instance.health_status)}
                            </span>
                            {isSelected ? (
                              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-950/35 dark:text-blue-200">
                                {text('cloud_binding_selected', 'Current')}
                              </span>
                            ) : null}
                          </div>
                          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                            {abilityModelRuntimeSummary(instance)}
                          </p>
                          <details className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                            <summary className="cursor-pointer select-none font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
                              {text('cloud_native_internal_details', 'Internal details')}
                            </summary>
                            <div className="mt-1 rounded-lg bg-slate-50 p-2 font-mono text-[0.7rem] leading-5 text-slate-600 dark:bg-slate-900/55 dark:text-slate-300">
                              {abilityModelInstanceDetail(instance)}
                            </div>
                          </details>
                        </div>
                        <div className="md:text-right">
                          <button
                            type="button"
                            className="btn btn-secondary justify-center text-xs disabled:cursor-not-allowed disabled:opacity-60"
                            disabled={savingCloudBinding || isSelected}
                            onClick={() => void saveCloudAbilityRuntimeBinding(instance.instance_id)}
                          >
                            {savingCloudBinding ? aiText('saving', 'Saving...') : text('action_use_runtime_model', 'Use model')}
                          </button>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div className="px-3 py-5 text-sm text-slate-500 dark:text-slate-400">
                    {text('embedding_model_search_empty', 'No embedding runtime model matches the current filters.')}
                  </div>
                )}
              </div>
            </div>

            <div className="mt-5 grid gap-3 border-t border-slate-200 pt-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
              <span>{text('cloud_binding_save_notice', 'Saving updates the Cloud Site Knowledge embedding runtime binding only.')}</span>
              {dialogMessage ? (
                <span
                  className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200"
                  role="status"
                  aria-live="polite"
                >
                  {dialogMessage}
                </span>
              ) : null}
              {dialogError ? (
                <span
                  className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200"
                  role="alert"
                >
                  {dialogError}
                </span>
              ) : null}
              <AdminMutationReceipt receipt={dialogReceipt} />
              <div className="flex justify-end">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={savingCloudBinding}
                  onClick={closeCloudBindingDialog}
                >
                  {aiText('action_close_dialog', 'Close')}
                </button>
              </div>
            </div>
          </div>
        </div>
      ), document.body) : null}
    </BackofficePageStack>
  );
}
