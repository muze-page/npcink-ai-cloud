'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { createPortal } from 'react-dom';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AdminMutationReceipt, type AdminMutationReceiptPayload } from '@/components/admin/AdminMutationReceipt';
import {
  BackofficeDisclosure,
  BackofficeEmptyState,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ConfirmModal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { useLocale } from '@/contexts/LocaleContext';
import { useDialogKeyboard } from '@/hooks/useDialogKeyboard';
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';
import { cn } from '@/lib/utils';

const runtimeProfilesClient = createApiClient({ idempotencyPrefix: 'runtime_profiles' });
const MAX_VISIBLE_CANDIDATES = 80;
const SUPPORTED_EXECUTION_KINDS = new Set(['text', 'vision', 'image_generation', 'audio_generation']);
const SUPERSEDED_CONNECTOR_CONTRACT_FIELD = ['connector', 'contract', 'version'].join('_');

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

type RuntimeProfile = {
  profile_id: string;
  group_id: string;
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
  note: string;
  revision: string;
  updated_at: string;
  status: string;
  platform_kind: 'wordpress';
  connector_id: 'wordpress_ai_connector';
};

type RuntimeProfilesData = {
  contract_version: 'cloud-hosted-runtime-profiles.v1';
  surface: 'admin_hosted_runtime_profiles';
  projection_kind: 'hosted_runtime_profile_configuration';
  owner: 'cloud_runtime';
  platform_kind: 'wordpress';
  connector_id: 'wordpress_ai_connector';
  operation_contract_version: 'wordpress_operation.v1';
  available_instances: {
    text: RuntimeInstance[];
    vision: RuntimeInstance[];
    image_generation: RuntimeInstance[];
    audio_generation: RuntimeInstance[];
  };
  profiles: RuntimeProfile[];
  receipt?: AdminMutationReceiptPayload | null;
};

function normalizeRuntimeInstance(value: unknown): RuntimeInstance {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('Hosted runtime instance must be an object.');
  }
  const item = value as Record<string, unknown>;
  const instanceId = String(item.instance_id || '').trim();
  const providerId = String(item.provider_id || '').trim();
  const modelId = String(item.model_id || '').trim();
  if (!instanceId || !providerId || !modelId) {
    throw new TypeError('Hosted runtime instance requires instance_id, provider_id, and model_id.');
  }
  return {
    instance_id: instanceId,
    provider_id: providerId,
    provider_display_name: String(item.provider_display_name || ''),
    adapter_type: String(item.adapter_type || ''),
    model_id: modelId,
    endpoint_variant: String(item.endpoint_variant || ''),
    region: String(item.region || ''),
    health_status: String(item.health_status || ''),
    weight: Number(item.weight || 0),
    capability_tags: Array.isArray(item.capability_tags) ? item.capability_tags.map(String) : [],
    model_status: String(item.model_status || ''),
    model_feature: String(item.model_feature || ''),
  };
}

function normalizeRuntimeProfile(value: unknown): RuntimeProfile {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('Hosted runtime profile must be an object.');
  }
  const item = value as Record<string, unknown>;
  if (item.platform_kind !== 'wordpress' || item.connector_id !== 'wordpress_ai_connector') {
    throw new TypeError('Hosted runtime profile identity does not match the WordPress connector contract.');
  }
  const profileId = String(item.profile_id || '').trim();
  if (!profileId) {
    throw new TypeError('Hosted runtime profile requires a non-empty profile_id.');
  }
  if (!Array.isArray(item.tasks) || !Array.isArray(item.candidate_instance_ids)) {
    throw new TypeError(`Hosted runtime profile ${profileId} requires tasks and candidate_instance_ids arrays.`);
  }
  if (item.tasks.some((task) => typeof task !== 'string' || !task.trim())) {
    throw new TypeError(`Hosted runtime profile ${profileId} requires non-empty string task identifiers.`);
  }
  if (item.candidate_instance_ids.some((instanceId) => typeof instanceId !== 'string' || !instanceId.trim())) {
    throw new TypeError(`Hosted runtime profile ${profileId} requires non-empty string candidate instance identifiers.`);
  }
  if (item.candidate_instance_ids.length > 2) {
    throw new TypeError(`Hosted runtime profile ${profileId} supports at most two candidate instance identifiers.`);
  }
  const executionKind = String(item.execution_kind || '').trim();
  if (!SUPPORTED_EXECUTION_KINDS.has(executionKind)) {
    throw new TypeError(`Hosted runtime profile ${profileId} has an unsupported execution_kind.`);
  }
  return {
    profile_id: profileId,
    group_id: String(item.group_id || item.groupId || ''),
    routing_intent: String(item.routing_intent || ''),
    label: String(item.label || ''),
    description: String(item.description || ''),
    execution_kind: executionKind,
    tasks: item.tasks.map((task) => task.trim()),
    candidate_instance_ids: item.candidate_instance_ids.map((instanceId) => instanceId.trim()),
    timeout_ms: Number(item.timeout_ms || 0),
    max_timeout_ms: Number(item.max_timeout_ms || 0),
    allow_fallback: Boolean(item.allow_fallback),
    max_retries: Number(item.max_retries || 0),
    note: String(item.note || ''),
    revision: String(item.revision || ''),
    updated_at: String(item.updated_at || ''),
    status: String(item.status || ''),
    platform_kind: 'wordpress',
    connector_id: 'wordpress_ai_connector',
  };
}

function normalizeRuntimeProfilesData(value: unknown): RuntimeProfilesData {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('Hosted runtime profile response is not an object.');
  }
  const data = value as Record<string, unknown>;
  if (SUPERSEDED_CONNECTOR_CONTRACT_FIELD in data) {
    throw new TypeError('Hosted runtime profile contract contains superseded connector contract identity.');
  }
  const expectedIdentity: Record<string, string> = {
    contract_version: 'cloud-hosted-runtime-profiles.v1',
    surface: 'admin_hosted_runtime_profiles',
    projection_kind: 'hosted_runtime_profile_configuration',
    owner: 'cloud_runtime',
    platform_kind: 'wordpress',
    connector_id: 'wordpress_ai_connector',
    operation_contract_version: 'wordpress_operation.v1',
  };
  for (const [field, expected] of Object.entries(expectedIdentity)) {
    if (data[field] !== expected) {
      throw new TypeError(`Hosted runtime profile contract identity mismatch: ${field}.`);
    }
  }
  if (!data.available_instances || typeof data.available_instances !== 'object' || Array.isArray(data.available_instances)) {
    throw new TypeError('Hosted runtime profile contract requires available_instances object.');
  }
  const available = data.available_instances as Record<string, unknown>;
  const requiredInstanceKinds = ['text', 'vision', 'image_generation', 'audio_generation'] as const;
  for (const kind of requiredInstanceKinds) {
    if (!Array.isArray(available[kind])) {
      throw new TypeError(`Hosted runtime profile contract requires available_instances.${kind} array.`);
    }
  }
  if (!Array.isArray(data.profiles)) {
    throw new TypeError('Hosted runtime profile contract requires profiles array.');
  }
  const profiles = data.profiles.map(normalizeRuntimeProfile);
  const profileIds = new Set<string>();
  for (const profile of profiles) {
    if (profileIds.has(profile.profile_id)) {
      throw new TypeError(`Hosted runtime profile_id is duplicated: ${profile.profile_id}.`);
    }
    profileIds.add(profile.profile_id);
  }
  const list = (key: typeof requiredInstanceKinds[number]) => (
    available[key] as unknown[]
  ).map(normalizeRuntimeInstance);
  return {
    contract_version: 'cloud-hosted-runtime-profiles.v1',
    surface: 'admin_hosted_runtime_profiles',
    projection_kind: 'hosted_runtime_profile_configuration',
    owner: 'cloud_runtime',
    platform_kind: 'wordpress',
    connector_id: 'wordpress_ai_connector',
    operation_contract_version: 'wordpress_operation.v1',
    available_instances: {
      text: list('text'),
      vision: list('vision'),
      image_generation: list('image_generation'),
      audio_generation: list('audio_generation'),
    },
    profiles,
    receipt: data.receipt && typeof data.receipt === 'object'
      ? data.receipt as AdminMutationReceiptPayload
      : null,
  };
}

function profileSnapshot(profiles: RuntimeProfile[]): string {
  return JSON.stringify(profiles.map((profile) => ({
    profile_id: profile.profile_id,
    candidate_instance_ids: profile.candidate_instance_ids,
    timeout_ms: profile.timeout_ms,
    allow_fallback: profile.allow_fallback,
    max_retries: profile.max_retries,
    note: profile.note,
  })));
}

function profileTone(profile: RuntimeProfile, instances: Map<string, RuntimeInstance>): 'success' | 'warning' | 'error' {
  const primary = instances.get(profile.candidate_instance_ids[0] || '');
  if (!primary) return 'warning';
  const modelStatus = primary.model_status.trim().toLowerCase();
  const healthStatus = primary.health_status.trim().toLowerCase();
  if (modelStatus !== 'available' || healthStatus === 'unhealthy') return 'error';
  if (healthStatus !== 'healthy') return 'warning';
  return 'success';
}

export default function RuntimeProfilesPage() {
  const { t } = useLocale();
  const toast = useToast();
  const router = useRouter();
  const copy = useCallback(
    (key: string, fallback: string, params?: Record<string, string>) => t(`admin.runtime_profiles.${key}`, params, fallback),
    [t]
  );
  const [data, setData] = useState<RuntimeProfilesData | null>(null);
  const [drafts, setDrafts] = useState<RuntimeProfile[]>([]);
  const [baseline, setBaseline] = useState('[]');
  const [activeProfileId, setActiveProfileId] = useState('');
  const [editingProfileId, setEditingProfileId] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [modelSearch, setModelSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [receipt, setReceipt] = useState<AdminMutationReceiptPayload | null>(null);
  const [pendingNavigationHref, setPendingNavigationHref] = useState('');
  const dialogRef = useDialogKeyboard<HTMLDivElement>({
    open: Boolean(editingProfileId),
    onClose: () => setEditingProfileId(''),
    closeDisabled: saving,
  });

  const applyData = useCallback((next: RuntimeProfilesData) => {
    setData(next);
    setDrafts(next.profiles);
    setBaseline(profileSnapshot(next.profiles));
    const requestedProfileId = typeof window === 'undefined'
      ? ''
      : new URLSearchParams(window.location.search).get('profile') || '';
    setActiveProfileId((current) => {
      if (next.profiles.some((profile) => profile.profile_id === requestedProfileId)) return requestedProfileId;
      if (next.profiles.some((profile) => profile.profile_id === current)) return current;
      return next.profiles[0]?.profile_id || '';
    });
    setReceipt(next.receipt || null);
  }, []);

  const loadProfiles = useCallback(async () => {
    setLoading(true);
    setError('');
    setData(null);
    setDrafts([]);
    setBaseline('[]');
    setActiveProfileId('');
    setEditingProfileId('');
    try {
      const response = await runtimeProfilesClient.request<RuntimeProfilesData>('/api/admin/runtime-profiles');
      applyData(normalizeRuntimeProfilesData(response.data));
    } catch (cause) {
      setError(resolveUiErrorMessage(cause, copy('error_load', 'Failed to load hosted runtime profiles.')));
    } finally {
      setLoading(false);
    }
  }, [applyData, copy]);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  const allInstances = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    return Object.values(data.available_instances).flat().filter((instance) => {
      if (seen.has(instance.instance_id)) return false;
      seen.add(instance.instance_id);
      return true;
    });
  }, [data]);
  const instancesById = useMemo(
    () => new Map(allInstances.map((instance) => [instance.instance_id, instance])),
    [allInstances]
  );
  const activeProfile = drafts.find((profile) => profile.profile_id === activeProfileId) || null;
  const editingProfile = drafts.find((profile) => profile.profile_id === editingProfileId) || null;
  const dirty = profileSnapshot(drafts) !== baseline;
  const configuredCount = drafts.filter((profile) => profile.candidate_instance_ids.length > 0).length;
  const attentionCount = drafts.filter((profile) => profileTone(profile, instancesById) !== 'success').length;

  useEffect(() => {
    if (!dirty) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    const handleAnchorClick = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest('a[href]') : null;
      if (!(target instanceof HTMLAnchorElement) || target.target === '_blank') return;
      const destination = new URL(target.href, window.location.href);
      if (destination.origin !== window.location.origin || destination.pathname === window.location.pathname) return;
      event.preventDefault();
      event.stopPropagation();
      setPendingNavigationHref(`${destination.pathname}${destination.search}${destination.hash}`);
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    document.addEventListener('click', handleAnchorClick, true);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      document.removeEventListener('click', handleAnchorClick, true);
    };
  }, [dirty]);

  const candidates = useMemo(() => {
    if (!editingProfile || !data) return [];
    const available = editingProfile.execution_kind === 'vision'
      ? data.available_instances.vision
      : editingProfile.execution_kind === 'image_generation'
        ? data.available_instances.image_generation
        : editingProfile.execution_kind === 'audio_generation'
          ? data.available_instances.audio_generation
          : data.available_instances.text;
    const selectedIds = editingProfile.candidate_instance_ids;
    const selected = selectedIds
      .map((instanceId) => instancesById.get(instanceId))
      .filter((instance): instance is RuntimeInstance => Boolean(instance));
    const merged = [...selected, ...available.filter((item) => !selectedIds.includes(item.instance_id))];
    const query = modelSearch.trim().toLowerCase();
    return merged.filter((instance) => {
      if (providerFilter && instance.provider_id !== providerFilter) return false;
      if (!query) return true;
      return [
        instance.provider_display_name,
        instance.provider_id,
        instance.model_id,
        instance.instance_id,
        instance.region,
        ...instance.capability_tags,
      ].join(' ').toLowerCase().includes(query);
    }).slice(0, MAX_VISIBLE_CANDIDATES);
  }, [data, editingProfile, instancesById, modelSearch, providerFilter]);
  const providers = useMemo(() => {
    const values = new Map<string, string>();
    candidates.forEach((instance) => values.set(
      instance.provider_id,
      instance.provider_display_name || instance.provider_id
    ));
    return [...values.entries()].sort((left, right) => left[1].localeCompare(right[1]));
  }, [candidates]);

  function updateProfile(profileId: string, patch: Partial<RuntimeProfile>) {
    setDrafts((current) => current.map((profile) => profile.profile_id === profileId
      ? { ...profile, ...patch }
      : profile));
  }

  function selectProfile(profileId: string) {
    setActiveProfileId(profileId);
    const params = new URLSearchParams(window.location.search);
    params.set('profile', profileId);
    router.replace(`/admin/runtime-profiles?${params.toString()}`, { scroll: false });
  }

  function setCandidate(profileId: string, position: 0 | 1, instanceId: string) {
    const profile = drafts.find((item) => item.profile_id === profileId);
    if (!profile) return;
    const next = [...profile.candidate_instance_ids];
    next[position] = instanceId;
    updateProfile(profileId, {
      candidate_instance_ids: next.filter(Boolean).filter((value, index, values) => values.indexOf(value) === index),
    });
  }

  function clearCandidate(profileId: string, position: 0 | 1) {
    const profile = drafts.find((item) => item.profile_id === profileId);
    if (!profile) return;
    updateProfile(profileId, {
      candidate_instance_ids: position === 0
        ? []
        : profile.candidate_instance_ids.slice(0, 1),
    });
  }

  async function saveProfiles() {
    if (!dirty || saving) return;
    setSaving(true);
    setError('');
    try {
      const response = await runtimeProfilesClient.request<RuntimeProfilesData>('/api/admin/runtime-profiles', {
        method: 'PUT',
        body: {
          contract_version: 'cloud-hosted-runtime-profiles.v1',
          platform_kind: 'wordpress',
          connector_id: 'wordpress_ai_connector',
          operation_contract_version: 'wordpress_operation.v1',
          profiles: drafts.map((profile) => ({
            profile_id: profile.profile_id,
            candidate_instance_ids: profile.candidate_instance_ids,
            timeout_ms: profile.timeout_ms,
            allow_fallback: profile.allow_fallback,
            max_retries: profile.max_retries,
            note: profile.note,
          })),
        },
      });
      const next = normalizeRuntimeProfilesData(response.data);
      applyData(next);
      toast.success(copy('message_saved', 'Hosted runtime profiles saved.'), t('common.success'));
    } catch (cause) {
      setError(resolveUiErrorMessage(cause, copy('error_save', 'Failed to save hosted runtime profiles.')));
    } finally {
      setSaving(false);
    }
  }

  function instanceLabel(instance: RuntimeInstance | undefined): string {
    if (!instance) return copy('model_unassigned', 'Not assigned');
    return `${instance.provider_display_name || instance.provider_id} / ${instance.model_id}`;
  }

  if (loading) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={copy('eyebrow', 'Runtime plane')}
        title={copy('title', 'Runtime Profiles')}
        description={copy('description', 'Configure the Cloud-hosted candidate chain for WordPress connector tasks. This is runtime routing metadata, not local ability or workflow truth.')}
        aside={(
          <div className="flex flex-wrap items-center gap-2">
            <Link href="/admin/ai-resources" className="btn btn-secondary">
              {copy('action_open_suppliers', 'Model suppliers')}
            </Link>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!dirty || saving}
              onClick={() => void saveProfiles()}
            >
              {saving ? copy('action_saving', 'Saving...') : copy('action_save', 'Save profiles')}
            </button>
          </div>
        )}
        contentClassName="py-5 md:py-5"
      >
        <BackofficeSummaryStrip items={[
          { label: copy('summary_platform', 'Platform'), value: 'WordPress' },
          { label: copy('summary_profiles', 'Profiles'), value: String(drafts.length) },
          { label: copy('summary_configured', 'Configured'), value: `${configuredCount}/${drafts.length}` },
          { label: copy('summary_attention', 'Needs attention'), value: String(attentionCount) },
          {
            label: t('common.status'),
            value: dirty ? copy('unsaved_status', 'Unsaved') : t('common.saved'),
            toneClassName: dirty ? 'text-amber-700 dark:text-amber-300' : undefined,
          },
        ]} />
        <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
          {copy('boundary_notice', 'The local plugin still owns abilities, workflows, prompts, profile adoption, approvals, audit, and final WordPress writes.')}
        </p>
      </BackofficePrimaryPanel>

      {error ? (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>{error}</span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadProfiles()}>
              {t('common.retry')}
            </button>
          </div>
        </div>
      ) : null}
      {data ? <AdminMutationReceipt receipt={receipt} title={copy('receipt_title', 'Latest profile change')} /> : null}

      {data ? drafts.length === 0 ? (
        <BackofficeEmptyState
          title={copy('empty_title', 'No hosted runtime profiles')}
          description={copy('empty_description', 'The WordPress connector has not projected any Cloud-hosted task profiles.')}
        />
      ) : (
        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
          <BackofficeSectionPanel className="min-w-0 overflow-hidden p-0 md:p-0">
            <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-800 md:px-6">
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
                {copy('directory_title', 'Hosted profile directory')}
              </h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {copy('directory_description', 'Select a WordPress-first task profile to inspect its Cloud candidate chain.')}
              </p>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-slate-800">
              {drafts.map((profile) => {
                const tone = profileTone(profile, instancesById);
                const primary = instancesById.get(profile.candidate_instance_ids[0] || '');
                const active = profile.profile_id === activeProfileId;
                return (
                  <button
                    type="button"
                    key={profile.profile_id}
                    className={cn(
                      'grid w-full min-w-0 cursor-pointer gap-3 px-5 py-4 text-left transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500/40 dark:hover:bg-slate-900/45 md:grid-cols-[minmax(0,1fr)_minmax(10rem,0.55fr)_auto] md:items-center md:px-6',
                      active && 'bg-blue-50/70 dark:bg-blue-950/20'
                    )}
                    aria-pressed={active}
                    onClick={() => selectProfile(profile.profile_id)}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-semibold text-slate-950 dark:text-white">
                        {profile.label || profile.routing_intent || profile.profile_id}
                      </span>
                      <span className="mt-1 block truncate text-xs text-slate-500 dark:text-slate-400">
                        {profile.routing_intent} · {profile.tasks.length} {copy('task_count_suffix', 'tasks')}
                      </span>
                    </span>
                    <span className="min-w-0 truncate text-sm text-slate-700 dark:text-slate-200">
                      {instanceLabel(primary)}
                    </span>
                    <BackofficeStatusBadge
                      label={tone === 'success' ? copy('status_ready', 'Ready') : tone === 'error' ? copy('status_error', 'Blocked') : copy('status_attention', 'Needs config')}
                      status={tone}
                    />
                  </button>
                );
              })}
            </div>
          </BackofficeSectionPanel>

          <BackofficeSectionPanel className="min-w-0 self-start xl:sticky xl:top-6">
            {activeProfile ? (
              <div className="space-y-5">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    {copy('inspector_label', 'Profile inspector')}
                  </p>
                  <h2 className="mt-2 break-words text-lg font-semibold text-slate-950 dark:text-white">
                    {activeProfile.label || activeProfile.profile_id}
                  </h2>
                  <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {activeProfile.description || activeProfile.routing_intent}
                  </p>
                </div>
                <dl className="divide-y divide-slate-200 border-y border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-800">
                  <div className="grid gap-1 py-3 sm:grid-cols-[7rem_minmax(0,1fr)]">
                    <dt className="text-slate-500 dark:text-slate-400">{copy('primary_model', 'Primary model')}</dt>
                    <dd className="min-w-0 break-words font-medium text-slate-950 dark:text-white">{instanceLabel(instancesById.get(activeProfile.candidate_instance_ids[0] || ''))}</dd>
                  </div>
                  <div className="grid gap-1 py-3 sm:grid-cols-[7rem_minmax(0,1fr)]">
                    <dt className="text-slate-500 dark:text-slate-400">{copy('fallback_model', 'Fallback model')}</dt>
                    <dd className="min-w-0 break-words font-medium text-slate-950 dark:text-white">{instanceLabel(instancesById.get(activeProfile.candidate_instance_ids[1] || ''))}</dd>
                  </div>
                  <div className="grid gap-1 py-3 sm:grid-cols-[7rem_minmax(0,1fr)]">
                    <dt className="text-slate-500 dark:text-slate-400">{copy('execution_kind', 'Execution kind')}</dt>
                    <dd className="break-words font-medium text-slate-950 dark:text-white">{activeProfile.execution_kind}</dd>
                  </div>
                </dl>
                <button
                  type="button"
                  className="btn btn-secondary w-full justify-center"
                  onClick={() => {
                    setProviderFilter('');
                    setModelSearch('');
                    setEditingProfileId(activeProfile.profile_id);
                  }}
                >
                  {copy('action_configure_chain', 'Configure candidate chain')}
                </button>
                <div>
                  <h3 className="text-sm font-semibold text-slate-950 dark:text-white">{copy('tasks_title', 'Connector tasks')}</h3>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {activeProfile.tasks.map((task) => (
                      <code key={task} className="max-w-full break-all rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-300">{task}</code>
                    ))}
                  </div>
                </div>
                <details className="border-t border-slate-200 pt-4 dark:border-slate-800">
                  <summary className="cursor-pointer text-sm font-semibold text-slate-900 dark:text-white">
                    {copy('advanced_policy', 'Advanced runtime policy')}
                  </summary>
                  <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                    <div><dt className="text-xs text-slate-500 dark:text-slate-400">{copy('timeout', 'Timeout')}</dt><dd className="mt-1 font-medium text-slate-950 dark:text-white">{Math.round(activeProfile.timeout_ms / 1000)}s</dd></div>
                    <div><dt className="text-xs text-slate-500 dark:text-slate-400">{copy('fallback', 'Fallback')}</dt><dd className="mt-1 font-medium text-slate-950 dark:text-white">{activeProfile.allow_fallback ? copy('enabled', 'Enabled') : copy('disabled', 'Disabled')}</dd></div>
                    <div><dt className="text-xs text-slate-500 dark:text-slate-400">{copy('retries', 'Retries')}</dt><dd className="mt-1 font-medium text-slate-950 dark:text-white">{activeProfile.max_retries}</dd></div>
                    <div><dt className="text-xs text-slate-500 dark:text-slate-400">{copy('revision', 'Revision')}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-700 dark:text-slate-300">{activeProfile.revision || '—'}</dd></div>
                  </dl>
                </details>
              </div>
            ) : (
              <BackofficeEmptyState
                title={copy('inspector_empty_title', 'Select a profile')}
                description={copy('inspector_empty_description', 'Choose a hosted profile to inspect its current Cloud candidate chain.')}
              />
            )}
          </BackofficeSectionPanel>
        </div>
      ) : null}

      {data ? <BackofficeDisclosure summary={copy('contract_details', 'Hosted runtime contract details')}>
        <dl className="grid gap-4 text-sm md:grid-cols-2 xl:grid-cols-4">
          <div><dt className="text-xs text-slate-500 dark:text-slate-400">{copy('contract_version', 'Contract version')}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-950 dark:text-white">{data?.contract_version || '—'}</dd></div>
          <div><dt className="text-xs text-slate-500 dark:text-slate-400">{copy('connector', 'Connector')}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-950 dark:text-white">{data?.connector_id || '—'}</dd></div>
          <div><dt className="text-xs text-slate-500 dark:text-slate-400">{copy('operation_contract', 'Operation contract')}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-950 dark:text-white">{data?.operation_contract_version || '—'}</dd></div>
          <div><dt className="text-xs text-slate-500 dark:text-slate-400">{copy('surface', 'Surface')}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-950 dark:text-white">{data?.surface || '—'}</dd></div>
        </dl>
      </BackofficeDisclosure> : null}

      {editingProfile && typeof document !== 'undefined' ? createPortal(
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/55 p-3 backdrop-blur-sm sm:p-6" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !saving) setEditingProfileId('');
        }}>
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="runtime-profile-dialog-title"
            tabIndex={-1}
            className="flex max-h-[90svh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950"
          >
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 dark:border-slate-800 sm:px-6">
              <div className="min-w-0">
                <h2 id="runtime-profile-dialog-title" className="truncate text-lg font-semibold text-slate-950 dark:text-white">
                  {copy('dialog_title', 'Configure candidate chain')}
                </h2>
                <p className="mt-1 truncate text-sm text-slate-600 dark:text-slate-300">{editingProfile.label || editingProfile.profile_id}</p>
              </div>
              <button type="button" className="btn btn-secondary btn-sm" disabled={saving} onClick={() => setEditingProfileId('')}>
                {t('common.close')}
              </button>
            </div>
            <div className="grid min-h-0 flex-1 overflow-hidden lg:grid-cols-[minmax(14rem,0.42fr)_minmax(0,1fr)]">
              <div className="space-y-5 overflow-y-auto border-b border-slate-200 p-5 dark:border-slate-800 lg:border-b-0 lg:border-r sm:p-6">
                <div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{copy('primary_model', 'Primary model')}</p>
                  <p className="mt-1 break-words text-sm font-semibold text-slate-950 dark:text-white">{instanceLabel(instancesById.get(editingProfile.candidate_instance_ids[0] || ''))}</p>
                  {editingProfile.candidate_instance_ids[0] ? (
                    <button type="button" className="mt-2 text-sm font-medium text-blue-700 hover:underline dark:text-blue-300" onClick={() => clearCandidate(editingProfile.profile_id, 0)}>
                      {copy('action_clear_primary', 'Clear candidate chain')}
                    </button>
                  ) : null}
                </div>
                <div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{copy('fallback_model', 'Fallback model')}</p>
                  <p className="mt-1 break-words text-sm font-semibold text-slate-950 dark:text-white">{instanceLabel(instancesById.get(editingProfile.candidate_instance_ids[1] || ''))}</p>
                  {editingProfile.candidate_instance_ids[1] ? (
                    <button type="button" className="mt-2 text-sm font-medium text-blue-700 hover:underline dark:text-blue-300" onClick={() => clearCandidate(editingProfile.profile_id, 1)}>
                      {copy('action_clear_fallback', 'Clear fallback')}
                    </button>
                  ) : null}
                </div>
                <div className="border-t border-slate-200 pt-4 dark:border-slate-800">
                  <label className="block text-sm font-medium text-slate-800 dark:text-slate-200" htmlFor="runtime-profile-timeout">{copy('timeout', 'Timeout')}</label>
                  <input
                    id="runtime-profile-timeout"
                    type="number"
                    min={1000}
                    max={editingProfile.max_timeout_ms || 120000}
                    step={1000}
                    value={editingProfile.timeout_ms}
                    onChange={(event) => updateProfile(editingProfile.profile_id, { timeout_ms: Number(event.target.value) })}
                    className="input mt-2 w-full"
                  />
                  <label className="mt-4 flex cursor-pointer items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                    <input type="checkbox" checked={editingProfile.allow_fallback} onChange={(event) => updateProfile(editingProfile.profile_id, { allow_fallback: event.target.checked })} />
                    {copy('allow_fallback', 'Allow fallback')}
                  </label>
                  <label className="mt-4 block text-sm font-medium text-slate-800 dark:text-slate-200" htmlFor="runtime-profile-retries">{copy('retries', 'Retries')}</label>
                  <input
                    id="runtime-profile-retries"
                    type="number"
                    min={0}
                    max={1}
                    value={editingProfile.max_retries}
                    onChange={(event) => updateProfile(editingProfile.profile_id, { max_retries: Number(event.target.value) })}
                    className="input mt-2 w-full"
                  />
                </div>
              </div>
              <div className="flex min-h-0 min-w-0 flex-col overflow-hidden">
                <div className="grid gap-3 border-b border-slate-200 p-4 dark:border-slate-800 sm:grid-cols-2 sm:p-5">
                  <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {copy('provider_filter', 'Supplier')}
                    <select className="input mt-2 w-full" value={providerFilter} onChange={(event) => setProviderFilter(event.target.value)}>
                      <option value="">{copy('provider_all', 'All suppliers')}</option>
                      {providers.map(([providerId, label]) => <option key={providerId} value={providerId}>{label}</option>)}
                    </select>
                  </label>
                  <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {copy('model_search', 'Search models')}
                    <input className="input mt-2 w-full" type="search" value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} placeholder={copy('model_search_placeholder', 'Supplier or model ID')} />
                  </label>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-slate-200 dark:divide-slate-800">
                  {candidates.length ? candidates.map((instance) => {
                    const primary = editingProfile.candidate_instance_ids[0] === instance.instance_id;
                    const fallback = editingProfile.candidate_instance_ids[1] === instance.instance_id;
                    return (
                      <div key={instance.instance_id} className="grid min-w-0 gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-5">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-slate-950 dark:text-white">{instanceLabel(instance)}</p>
                          <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{instance.region || '—'} · {instance.health_status || 'unknown'} · {instance.instance_id}</p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button type="button" className={cn('btn btn-secondary btn-sm', primary && 'border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950/35 dark:text-blue-200')} onClick={() => setCandidate(editingProfile.profile_id, 0, instance.instance_id)}>
                            {primary ? copy('selected_primary', 'Primary') : copy('action_set_primary', 'Set primary')}
                          </button>
                          <button type="button" className={cn('btn btn-secondary btn-sm', fallback && 'border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950/35 dark:text-blue-200')} disabled={primary || !editingProfile.candidate_instance_ids[0]} onClick={() => setCandidate(editingProfile.profile_id, 1, instance.instance_id)}>
                            {fallback ? copy('selected_fallback', 'Fallback') : copy('action_set_fallback', 'Set fallback')}
                          </button>
                        </div>
                      </div>
                    );
                  }) : (
                    <div className="p-6">
                      <BackofficeEmptyState title={copy('models_empty_title', 'No matching models')} description={copy('models_empty_description', 'Enable a compatible model in Model suppliers or clear the current filters.')} />
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-5 py-4 dark:border-slate-800 sm:px-6">
              <p className="text-xs text-slate-500 dark:text-slate-400">{copy('dialog_save_notice', 'Changes remain local to this draft until you use Save profiles on the page.')}</p>
              <button type="button" className="btn btn-secondary" onClick={() => setEditingProfileId('')}>{copy('action_done', 'Done')}</button>
            </div>
          </div>
        </div>,
        document.body
      ) : null}

      <ConfirmModal
        isOpen={Boolean(pendingNavigationHref)}
        title={copy('unsaved_leave_title', 'Leave with unsaved changes?')}
        message={copy('unsaved_leave_desc', 'Leaving this page will discard the hosted runtime profile draft. Saved profiles are not affected.')}
        confirmLabel={copy('discard_and_leave', 'Discard and leave')}
        cancelLabel={t('common.cancel')}
        variant="danger"
        onClose={() => setPendingNavigationHref('')}
        onConfirm={() => {
          const href = pendingNavigationHref;
          if (data) {
            setDrafts(data.profiles);
            setBaseline(profileSnapshot(data.profiles));
          }
          setEditingProfileId('');
          setProviderFilter('');
          setModelSearch('');
          setPendingNavigationHref('');
          if (href) router.push(href);
        }}
      />
    </BackofficePageStack>
  );
}
