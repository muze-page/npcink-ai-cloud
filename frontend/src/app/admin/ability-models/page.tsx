'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BackofficeEmptyState,
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
import { generateIdempotencyKey } from '@/lib/idempotency';

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
  available_text_instances: RuntimeInstance[];
  available_image_instances: RuntimeInstance[];
  profiles: RoutingProfile[];
};

type EditableRoutingProfile = RoutingProfile & {
  note: string;
};

function normalizeProfilePreferences(raw: any): ProfilePreferences | null {
  if (!raw || typeof raw !== 'object') return null;
  const allowed = raw.allowed && typeof raw.allowed === 'object' ? raw.allowed : {};
  return {
    env_path: String(raw.env_path ?? ''),
    requires_worker_restart_after_save: Boolean(raw.requires_worker_restart_after_save),
    audio_summary_text_profile_id: String(raw.audio_summary_text_profile_id ?? ''),
    audio_narration_profile_id: String(raw.audio_narration_profile_id ?? ''),
    audio_summary_audio_profile_id: String(raw.audio_summary_audio_profile_id ?? ''),
    allowed: {
      text_profile_ids: Array.isArray(allowed.text_profile_ids) ? allowed.text_profile_ids.map(String) : [],
      audio_profile_ids: Array.isArray(allowed.audio_profile_ids) ? allowed.audio_profile_ids.map(String) : [],
    },
  };
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
  };
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

  const [preferences, setPreferences] = useState<ProfilePreferences | null>(null);
  const [routingData, setRoutingData] = useState<RoutingData | null>(null);
  const [routingDrafts, setRoutingDrafts] = useState<EditableRoutingProfile[]>([]);
  const [activeProfileId, setActiveProfileId] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingRouting, setLoadingRouting] = useState(true);
  const [savingPreferences, setSavingPreferences] = useState(false);
  const [savingRouting, setSavingRouting] = useState(false);
  const [pageError, setPageError] = useState('');
  const [pageMessage, setPageMessage] = useState('');
  const [dialogError, setDialogError] = useState('');
  const [dialogMessage, setDialogMessage] = useState('');

  const loadPreferences = useCallback(async () => {
    setLoading(true);
    setPageError('');
    try {
      const response = await fetch('/api/admin/ai-resources', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, text('error_load_audio_models', 'Failed to load audio ability models.')));
      }
      setPreferences(normalizeProfilePreferences(payload.data?.profile_preferences));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : text('error_load_audio_models', 'Failed to load audio ability models.'));
    } finally {
      setLoading(false);
    }
  }, [text]);

  const loadRouting = useCallback(async () => {
    setLoadingRouting(true);
    setPageError('');
    try {
      const response = await fetch('/api/admin/wordpress-ai-routing', { credentials: 'include' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, aiText('error_load_ability_models', 'Failed to load ability model routing.')));
      }
      const normalized = normalizeRoutingData(payload.data);
      setRoutingData(normalized);
      setRoutingDrafts(normalized.profiles.map((profile) => ({ ...profile, note: '' })));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : aiText('error_load_ability_models', 'Failed to load ability model routing.'));
    } finally {
      setLoadingRouting(false);
    }
  }, [aiText]);

  useEffect(() => {
    void loadPreferences();
    void loadRouting();
  }, [loadPreferences, loadRouting]);

  const runtimeInstancesById = useMemo(() => {
    const instances = [
      ...(routingData?.available_text_instances || []),
      ...(routingData?.available_image_instances || []),
    ];
    return new Map(instances.map((instance) => [instance.instance_id, instance]));
  }, [routingData]);

  const routingCandidateInstancesFor = useCallback((profile: RoutingProfile): RuntimeInstance[] => (
    profile.execution_kind === 'image_generation'
      ? routingData?.available_image_instances || []
      : routingData?.available_text_instances || []
  ), [routingData]);

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
    return normalized || aiText('ability_model_feature_unknown', 'Unknown');
  }, [aiText]);

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

  const abilityModelInstanceDetail = useCallback((instance: RuntimeInstance): string => (
    aiText('ability_model_instance_detail', 'Instance: {{instance}} · Capability: {{feature}} · Region: {{region}} · Status: {{status}}', {
      instance: instance.instance_id,
      feature: abilityModelFeatureLabel(instance.model_feature || instance.endpoint_variant),
      region: abilityModelRegionLabel(instance.region),
      status: abilityModelHealthLabel(instance.health_status),
    })
  ), [abilityModelFeatureLabel, abilityModelHealthLabel, abilityModelRegionLabel, aiText]);

  const abilityModelRows = useMemo(() => routingDrafts.flatMap((profile) => {
    const primaryInstance = runtimeInstancesById.get(profile.candidate_instance_ids[0] || '');
    const fallbackCount = Math.max(0, profile.candidate_instance_ids.length - 1);
    return profile.tasks.map((taskId) => ({
      taskId,
      label: abilityTaskLabel(taskId),
      description: abilityTaskDescription(taskId),
      profile,
      primaryInstance,
      fallbackCount,
    }));
  }), [abilityTaskDescription, abilityTaskLabel, routingDrafts, runtimeInstancesById]);

  const activeProfile = useMemo(
    () => routingDrafts.find((profile) => profile.profile_id === activeProfileId) || null,
    [activeProfileId, routingDrafts]
  );

  const activeProfileTitle = useMemo(() => {
    if (!activeProfile) return '';
    if (activeProfile.tasks.length === 1) return abilityTaskLabel(activeProfile.tasks[0]);
    if (activeProfile.tasks.length > 1) {
      return aiText('ability_model_group_title', '{{name}} 等 {{count}} 个能力', {
        name: abilityTaskLabel(activeProfile.tasks[0]),
        count: String(activeProfile.tasks.length),
      });
    }
    return activeProfile.label;
  }, [abilityTaskLabel, activeProfile, aiText]);

  const metrics = useMemo(() => [
    {
      label: text('metric_audio_profiles', 'Audio profiles'),
      value: preferences ? 3 : 0,
      detail: text('metric_audio_profiles_detail', 'Summary, narration, and playback'),
    },
    {
      label: aiText('ability_models_metric_abilities', 'Abilities'),
      value: abilityModelRows.length,
      detail: aiText('ability_models_metric_abilities_detail', 'WordPress AI connector tasks'),
    },
    {
      label: aiText('ability_models_metric_text_instances', 'Text models'),
      value: routingData?.available_text_instances.length || 0,
      detail: aiText('ability_models_metric_text_instances_detail', 'Available text runtime instances'),
    },
    {
      label: aiText('ability_models_metric_image_instances', 'Image models'),
      value: routingData?.available_image_instances.length || 0,
      detail: aiText('ability_models_metric_image_instances_detail', 'Available image runtime instances'),
    },
  ], [abilityModelRows.length, aiText, preferences, routingData, text]);

  function updatePreferences(patch: Partial<ProfilePreferences>) {
    setPreferences((current) => current ? { ...current, ...patch } : current);
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

  async function saveProfilePreferences() {
    if (!preferences) return;
    setSavingPreferences(true);
    setPageError('');
    setPageMessage('');
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
      setPreferences(normalizeProfilePreferences(payload.data?.profile_preferences));
      setPageMessage(aiText('message_preferences_saved', 'Profile preferences saved. Restart worker processes for queued runs to pick up the same values.'));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : aiText('error_save_preferences', 'Failed to save profile preferences.'));
    } finally {
      setSavingPreferences(false);
    }
  }

  async function saveAbilityModelProfile(profileId: string) {
    const profile = routingDrafts.find((item) => item.profile_id === profileId);
    if (!profile) {
      setDialogError(aiText('error_save_ability_models', 'Failed to save ability model routing.'));
      return;
    }
    setSavingRouting(true);
    setDialogError('');
    setDialogMessage('');
    setPageError('');
    setPageMessage('');
    try {
      const response = await fetch('/api/admin/wordpress-ai-routing', {
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
        throw new Error(resolveAdminApiPayloadMessage(payload, aiText('error_save_ability_models', 'Failed to save ability model routing.')));
      }
      const normalized = normalizeRoutingData(payload.data);
      setRoutingData(normalized);
      setRoutingDrafts(normalized.profiles.map((item) => ({ ...item, note: '' })));
      setDialogMessage(aiText('message_ability_models_saved', 'Ability model routing saved.'));
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : aiText('error_save_ability_models', 'Failed to save ability model routing.'));
    } finally {
      setSavingRouting(false);
    }
  }

  function openAbilityModelDialog(profileId: string) {
    setActiveProfileId(profileId);
    setDialogError('');
    setDialogMessage('');
    setPageError('');
    setPageMessage('');
  }

  function closeAbilityModelDialog() {
    setActiveProfileId('');
    setDialogError('');
    setDialogMessage('');
  }

  if (loading) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={text('eyebrow', 'Runtime model routing')}
        title={text('title', 'Ability models')}
        description={text('description', 'Configure the Cloud runtime profiles and model instances used by audio abilities, WordPress AI connector abilities, and future Cloud-native abilities.')}
        aside={<BackofficeStatusBadge label={text('badge_runtime_binding', 'Runtime binding')} status="success" />}
        summary={<BackofficeMetricStrip items={metrics} columnsClassName="xl:grid-cols-4" />}
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

      {preferences ? (
        <BackofficeSectionPanel>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{aiText('profile_preferences_title', 'Audio ability models')}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {aiText('profile_preferences_desc', 'Runtime profile selection for audio summary, narration, and playback. This does not edit prompts, router rules, or WordPress write policy.')}
              </p>
            </div>
            <BackofficeStatusBadge label={text('badge_audio', 'Audio ability')} status="success" />
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
                  <option key={profileId} value={profileId}>{profileId}</option>
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
                  <option key={profileId} value={profileId}>{profileId}</option>
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
                  <option key={profileId} value={profileId}>{profileId}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-4 flex flex-col gap-3 text-sm text-slate-600 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between">
            <span>{text('audio_save_notice', 'Only Cloud runtime profile preferences are changed here.')}</span>
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
              {text('wordpress_title', 'WordPress ability models')}
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {aiText('ability_models_desc', 'WordPress AI connector abilities mapped to Cloud runtime profiles and model instances. Local plugin enablement and WordPress writes stay outside this page.')}
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

      <BackofficeSectionPanel>
        <BackofficeEmptyState
          title={text('cloud_native_title', 'Cloud-native ability models')}
          description={text('cloud_native_desc', 'No Cloud-native ability model bindings are configurable yet. When Cloud-owned runtime abilities are added, they will appear here without becoming a WordPress control plane.')}
        />
      </BackofficeSectionPanel>

      {activeProfile && typeof document !== 'undefined' ? createPortal((
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
                  <div className="text-base font-semibold text-slate-950 dark:text-white">{activeProfileTitle}</div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{activeProfile.profile_id}</div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {activeProfile.tasks.map((taskId) => (
                    <span
                      key={taskId}
                      className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300"
                    >
                      {abilityTaskLabel(taskId)}
                    </span>
                  ))}
                </div>
                {[0, 1].map((index) => {
                  const selectedId = activeProfile.candidate_instance_ids[index] || '';
                  const selected = runtimeInstancesById.get(selectedId);
                  const candidates = routingCandidateInstancesFor(activeProfile);
                  return (
                    <label
                      key={`${activeProfile.profile_id}-${index}`}
                      className="block rounded-xl border border-slate-200 bg-white/70 p-3 dark:border-slate-800 dark:bg-slate-950/40"
                    >
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                        {index === 0 ? aiText('ability_model_primary_model', 'Primary model') : aiText('ability_model_fallback_model', 'Fallback model')}
                      </span>
                      <select
                        value={selectedId}
                        onChange={(event) => updateRoutingCandidate(activeProfile.profile_id, index, event.target.value)}
                        className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                      >
                        <option value="">{aiText('ability_model_unassigned', 'Unassigned')}</option>
                        {candidates.map((instance) => (
                          <option
                            key={`${activeProfile.profile_id}-${index}-${instance.instance_id}`}
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
                <label className="flex items-center justify-between rounded-xl border border-slate-200 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/40">
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
                    placeholder={aiText('placeholder_ability_model_note', 'Why this ability model binding is being changed')}
                  />
                </label>
              </div>
            </div>
            <div className="mt-5 grid gap-3 border-t border-slate-200 pt-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
              <div className="grid gap-2">
                <span>{aiText('ability_model_save_notice', 'Saving updates the Cloud runtime routing profile used by this ability group.')}</span>
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
