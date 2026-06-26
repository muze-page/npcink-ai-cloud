'use client';

import Link from 'next/link';
import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
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
import { resolveUiErrorMessage } from '@/lib/errors';

type ResourceStatus = 'ready' | 'missing_secret' | 'missing_provider' | 'disabled' | string;

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

type EnvMigrationSource = {
  connection_id: string;
  provider_id: string;
  label: string;
  source: string;
  configured: boolean;
  managed_connection_present: boolean;
  env_keys: string[];
  import_supported: boolean;
};

type EnvMigration = {
  env_path: string;
  configured_env_source_count: number;
  importable_source_count: number;
  sources: EnvMigrationSource[];
  recommended_primary: string;
  env_role: string;
  secret_exposure: string;
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

type ProviderModelHealth = {
  source: string;
  content_exposed: boolean;
  recent_call_limit: number;
  rows: ProviderModelHealthRow[];
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
  env_migration?: EnvMigration;
  profile_preferences: ProfilePreferences;
  boundary: {
    direct_wordpress_write: boolean;
    final_writes: string;
    secret_exposure: string;
    not_a_control_plane: boolean;
  };
};

type ProviderConnectionForm = {
  connectionId: string;
  providerId: string;
  displayName: string;
  kind: string;
  baseUrl: string;
  sourceRole: string;
  capabilityIds: string;
  runtimeProfileIds: string;
  credential: string;
  enabled: boolean;
};

const EMPTY_PROVIDER_CONNECTION_FORM: ProviderConnectionForm = {
  connectionId: '',
  providerId: '',
  displayName: '',
  kind: 'openai_compatible',
  baseUrl: '',
  sourceRole: 'execution_source',
  capabilityIds: 'text_generation',
  runtimeProfileIds: 'text.ai',
  credential: '',
  enabled: true,
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

function labelList(values: string[]): string {
  return values.length ? values.join(', ') : '-';
}

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
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

function AiResourcesContent() {
  const [data, setData] = useState<AiResources | null>(null);
  const [preferences, setPreferences] = useState<ProfilePreferences | null>(null);
  const [activeView, setActiveView] = useState<'connections' | 'usage' | 'health' | 'matrix'>('connections');
  const [loading, setLoading] = useState(true);
  const [savingPreferences, setSavingPreferences] = useState(false);
  const [savingConnection, setSavingConnection] = useState(false);
  const [testingConnectionId, setTestingConnectionId] = useState('');
  const [importingEnv, setImportingEnv] = useState(false);
  const [connectionTestResults, setConnectionTestResults] = useState<Record<string, ProviderConnectionTestResult>>({});
  const [providerConnectionForm, setProviderConnectionForm] = useState<ProviderConnectionForm>(
    EMPTY_PROVIDER_CONNECTION_FORM
  );
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
        throw new Error(resolveUiErrorMessage(payload, 'Failed to load AI resources.'));
      }
      const normalized = payload.data as AiResources;
      setData(normalized);
      setPreferences(normalized.profile_preferences);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load AI resources.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadResources();
  }, [loadResources]);

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
        throw new Error(resolveUiErrorMessage(payload, 'Failed to save profile preferences.'));
      }
      const normalized = payload.data as AiResources;
      setData(normalized);
      setPreferences(normalized.profile_preferences);
      setMessage('Profile preferences saved. Restart worker processes for queued runs to pick up the same values.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save profile preferences.');
    } finally {
      setSavingPreferences(false);
    }
  }

  async function saveProviderConnection() {
    setSavingConnection(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/admin/provider-connections', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          connection_id: providerConnectionForm.connectionId,
          provider_id: providerConnectionForm.providerId,
          provider_type: providerConnectionForm.kind,
          kind: providerConnectionForm.kind,
          display_name: providerConnectionForm.displayName,
          enabled: providerConnectionForm.enabled,
          base_url: providerConnectionForm.baseUrl,
          source_role: providerConnectionForm.sourceRole,
          capability_ids: splitList(providerConnectionForm.capabilityIds),
          runtime_profile_ids: splitList(providerConnectionForm.runtimeProfileIds),
          credential: providerConnectionForm.credential || undefined,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to save provider connection.'));
      }
      setProviderConnectionForm(EMPTY_PROVIDER_CONNECTION_FORM);
      setMessage('Provider connection saved. Credential status is masked in this page.');
      await loadResources({ showLoading: false });
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save provider connection.');
    } finally {
      setSavingConnection(false);
    }
  }

  async function deleteProviderConnection(connectionId: string) {
    setSavingConnection(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`/api/admin/provider-connections/${encodeURIComponent(connectionId)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to delete provider connection.'));
      }
      setMessage('Provider connection deleted.');
      await loadResources({ showLoading: false });
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Failed to delete provider connection.');
    } finally {
      setSavingConnection(false);
    }
  }

  async function testProviderConnection(connectionId: string) {
    setTestingConnectionId(connectionId);
    setError('');
    setMessage('');
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
        throw new Error(resolveUiErrorMessage(payload, result?.message || 'Provider connection test failed.'));
      }
      setMessage(result?.message || 'Provider connection tested.');
      await loadResources({ showLoading: false });
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : 'Provider connection test failed.');
    } finally {
      setTestingConnectionId('');
    }
  }

  async function importEnvConnections() {
    setImportingEnv(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/admin/provider-connections/import-env', {
        method: 'POST',
        credentials: 'include',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to import environment providers.'));
      }
      const imported = Array.isArray(payload.data?.imported) ? payload.data.imported.length : 0;
      const skipped = Array.isArray(payload.data?.skipped) ? payload.data.skipped.length : 0;
      setMessage(`Environment import completed. Imported ${imported}; skipped ${skipped}.`);
      await loadResources({ showLoading: false });
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : 'Failed to import environment providers.');
    } finally {
      setImportingEnv(false);
    }
  }

  function editProviderConnection(connection: Connection) {
    setProviderConnectionForm({
      connectionId: connection.connection_id,
      providerId: connection.provider_id,
      displayName: connection.display_name,
      kind: connection.kind,
      baseUrl: connection.base_url || '',
      sourceRole: 'execution_source',
      capabilityIds: connection.capability_ids.join(', '),
      runtimeProfileIds: connection.runtime_profile_ids.join(', '),
      credential: '',
      enabled: connection.enabled,
    });
    setActiveView('connections');
  }

  function updatePreferences(patch: Partial<ProfilePreferences>) {
    setPreferences((current) => (current ? { ...current, ...patch } : current));
  }

  function updateProviderConnectionForm(patch: Partial<ProviderConnectionForm>) {
    setProviderConnectionForm((current) => ({ ...current, ...patch }));
  }

  const metrics = useMemo(() => {
    const connections = data?.connections || [];
    const capabilities = data?.capabilities || [];
    const profiles = data?.runtime_profiles || [];
    return [
      {
        label: 'Connections',
        value: connections.filter((item) => item.configured).length,
        detail: `${connections.length} runtime provider entries`,
      },
      {
        label: 'Capabilities',
        value: capabilities.filter((item) => item.status === 'ready').length,
        detail: `${capabilities.length} projected Cloud capabilities`,
      },
      {
        label: 'Profiles',
        value: profiles.filter((item) => item.status === 'ready').length,
        detail: `${profiles.length} runtime or pipeline profiles`,
      },
      {
        label: 'Write posture',
        value: data?.boundary?.direct_wordpress_write ? 'Review' : 'No writes',
        detail: data?.boundary?.final_writes || 'core_proposal_required',
      },
    ];
  }, [data]);

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

  if (loading) {
    return <LoadingFallback />;
  }

  if (!data) {
    return (
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow="Provider settings"
          title="AI resources"
          description="Cloud runtime provider resources are unavailable."
        >
          <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
            {error || 'AI resources are unavailable.'}
          </BackofficeStackCard>
        </BackofficePrimaryPanel>
      </BackofficePageStack>
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow="Provider settings"
        title="AI resources"
        description="Cloud-owned runtime provider connections, capability readiness, and profile mapping."
        aside={(
          <BackofficeStatusBadge
            label={data.boundary.not_a_control_plane ? 'Runtime resources' : 'Review boundary'}
            status={data.boundary.not_a_control_plane ? 'success' : 'warning'}
          />
        )}
        summary={<BackofficeMetricStrip items={metrics} columnsClassName="xl:grid-cols-4" />}
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
        <BackofficeStackCard className="flex flex-col gap-3 text-sm leading-6 text-slate-600 dark:text-slate-300 lg:flex-row lg:items-center lg:justify-between">
          <span>
            Provider connections can be managed in Cloud runtime storage. WordPress writes, approvals, abilities, workflows, prompts, and router truth stay outside this page.
          </span>
          <div className="flex flex-wrap gap-2">
            <Link href="/admin/audio-providers" className="btn btn-secondary">
              Audio providers
            </Link>
            <Link href="/admin/audio-workbench" className="btn btn-primary">
              Audio workbench
            </Link>
          </div>
        </BackofficeStackCard>
      </BackofficePrimaryPanel>

      <div className="flex flex-wrap gap-2">
        <BackofficeFilterPill
          active={activeView === 'connections'}
          onClick={() => setActiveView('connections')}
        >
          Connections
        </BackofficeFilterPill>
        <BackofficeFilterPill
          active={activeView === 'matrix'}
          onClick={() => setActiveView('matrix')}
        >
          Capability Matrix
        </BackofficeFilterPill>
        <BackofficeFilterPill
          active={activeView === 'usage'}
          onClick={() => setActiveView('usage')}
        >
          Feature usage
        </BackofficeFilterPill>
        <BackofficeFilterPill
          active={activeView === 'health'}
          onClick={() => setActiveView('health')}
        >
          Model health
        </BackofficeFilterPill>
      </div>

      {activeView === 'connections' ? (
        <>
          <BackofficeSectionPanel>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Connections</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              Masked provider connection status. Secrets are never returned to the browser.
            </p>
          </div>
        </div>
        <form
          className="mt-4 grid gap-4 border-b border-slate-200 pb-5 dark:border-slate-800"
          onSubmit={(event) => {
            event.preventDefault();
            void saveProviderConnection();
          }}
        >
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Connection ID
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={providerConnectionForm.connectionId}
                onChange={(event) => updateProviderConnectionForm({ connectionId: event.target.value })}
                placeholder="openai_primary"
                required
              />
            </label>
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Provider ID
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={providerConnectionForm.providerId}
                onChange={(event) => updateProviderConnectionForm({ providerId: event.target.value })}
                placeholder="openai"
                required
              />
            </label>
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Display name
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={providerConnectionForm.displayName}
                onChange={(event) => updateProviderConnectionForm({ displayName: event.target.value })}
                placeholder="OpenAI primary"
                required
              />
            </label>
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Kind
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
              </select>
            </label>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Base URL
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={providerConnectionForm.baseUrl}
                onChange={(event) => updateProviderConnectionForm({ baseUrl: event.target.value })}
                placeholder="https://api.example.com/v1"
              />
            </label>
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Capabilities
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={providerConnectionForm.capabilityIds}
                onChange={(event) => updateProviderConnectionForm({ capabilityIds: event.target.value })}
                placeholder="text_generation, image_generation"
              />
            </label>
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Profiles
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={providerConnectionForm.runtimeProfileIds}
                onChange={(event) => updateProviderConnectionForm({ runtimeProfileIds: event.target.value })}
                placeholder="text.ai"
              />
            </label>
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Credential
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                type="password"
                value={providerConnectionForm.credential}
                onChange={(event) => updateProviderConnectionForm({ credential: event.target.value })}
                placeholder="leave blank to keep current"
              />
            </label>
          </div>
          <div className="flex flex-col gap-3 text-sm text-slate-600 dark:text-slate-300 sm:flex-row sm:items-center sm:justify-between">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={providerConnectionForm.enabled}
                onChange={(event) => updateProviderConnectionForm({ enabled: event.target.checked })}
              />
              Enabled for runtime use
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setProviderConnectionForm(EMPTY_PROVIDER_CONNECTION_FORM)}
              >
                Clear
              </button>
              <button
                type="submit"
                disabled={savingConnection}
                className="btn btn-primary justify-center disabled:cursor-not-allowed disabled:opacity-60"
              >
                {savingConnection ? 'Saving...' : 'Save provider connection'}
              </button>
            </div>
          </div>
        </form>
        {data.env_migration ? (
          <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/50">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-950 dark:text-white">Environment migration</h3>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  DB provider connections are the primary runtime source. Environment values remain fallback only.
                </p>
                <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  {data.env_migration.configured_env_source_count} configured env sources · {data.env_migration.importable_source_count} importable · {data.env_migration.env_path}
                </div>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={importingEnv || data.env_migration.importable_source_count === 0}
                onClick={() => void importEnvConnections()}
              >
                {importingEnv ? 'Importing...' : 'Import env providers'}
              </button>
            </div>
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {data.env_migration.sources.map((source) => (
                <div
                  key={source.connection_id}
                  className="rounded-md border border-slate-200 bg-white p-3 text-sm dark:border-slate-800 dark:bg-slate-950"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-slate-900 dark:text-white">{source.label}</span>
                    <BackofficeStatusBadge
                      label={source.managed_connection_present ? 'DB managed' : source.configured ? 'env fallback' : 'missing'}
                      status={source.managed_connection_present ? 'success' : source.configured ? 'warning' : 'disabled'}
                    />
                  </div>
                  <div className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {source.env_keys.join(', ')}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {data.connections.map((connection) => (
            <BackofficeStackCard key={connection.connection_id} className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold text-slate-950 dark:text-white">
                    {connection.display_name}
                  </h3>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {connection.provider_id} · {connection.kind}
                  </p>
                </div>
                <BackofficeStatusBadge label={connection.status} status={statusTone(connection.status)} />
              </div>
              <div className="grid gap-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                <div>Base URL: {connection.base_url || '-'}</div>
                <div>Enabled: {connection.enabled ? 'yes' : 'no'}</div>
                <div>Configured: {connection.configured ? 'yes' : 'no'}</div>
                <div>Capabilities: {labelList(connection.capability_ids)}</div>
                <div>Profiles: {labelList(connection.runtime_profile_ids)}</div>
              </div>
              {connectionTestResults[connection.connection_id] ? (
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-600 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-300">
                  <div className="flex items-center justify-between gap-3">
                    <span>Last test: {connectionTestResults[connection.connection_id].stage}</span>
                    <BackofficeStatusBadge
                      label={connectionTestResults[connection.connection_id].status}
                      status={connectionTestResults[connection.connection_id].ok ? 'success' : 'warning'}
                    />
                  </div>
                  <div className="mt-1">{connectionTestResults[connection.connection_id].message}</div>
                  {connectionTestResults[connection.connection_id].catalog?.model_count ? (
                    <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      Catalog models: {connectionTestResults[connection.connection_id].catalog?.model_count} · {labelList(connectionTestResults[connection.connection_id].catalog?.sample_model_ids || [])}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => editProviderConnection(connection)}
                >
                  Edit
                </button>
                {connection.managed_by === 'cloud_provider_connections' ? (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={testingConnectionId === connection.connection_id}
                    onClick={() => void testProviderConnection(connection.connection_id)}
                  >
                    {testingConnectionId === connection.connection_id ? 'Testing...' : 'Test'}
                  </button>
                ) : null}
                {connection.managed_by === 'cloud_provider_connections' ? (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={savingConnection}
                    onClick={() => void deleteProviderConnection(connection.connection_id)}
                  >
                    Delete
                  </button>
                ) : null}
                {connection.detail_href && connection.managed_by !== 'cloud_provider_connections' ? (
                  <Link href={connection.detail_href} className="btn btn-secondary">
                    Configure {connection.display_name}
                  </Link>
                ) : null}
              </div>
            </BackofficeStackCard>
          ))}
        </div>
          </BackofficeSectionPanel>

          {preferences ? (
            <BackofficeSectionPanel>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Profile preferences</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                Runtime profile selection for Admin audio tools. This does not edit prompts, router rules, or WordPress write policy.
              </p>
            </div>
            <BackofficeStatusBadge label="Runtime metadata" status="info" />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <label className="grid gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              Audio summary text profile
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
              Article narration audio profile
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
              Audio summary playback profile
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
            <span>Stored in {preferences.env_path}. Secrets are not part of this save path.</span>
            <button
              type="button"
              onClick={saveProfilePreferences}
              disabled={savingPreferences}
              className="btn btn-primary justify-center disabled:cursor-not-allowed disabled:opacity-60"
            >
              {savingPreferences ? 'Saving...' : 'Save profile preferences'}
            </button>
          </div>
            </BackofficeSectionPanel>
          ) : null}
        </>
      ) : null}

      {activeView === 'usage' ? (
        <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Feature usage</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
          Feature-to-model evidence from Cloud runtime metadata. Prompt text, result content, and provider secrets are not exposed.
        </p>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1.1fr_8rem_1fr_1.2fr_1fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>Feature</span>
            <span>Status</span>
            <span>Profile</span>
            <span>Provider / model</span>
            <span>Last run</span>
            <span>Cost / latency</span>
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
                <div>{row.last_run?.status || 'not observed'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {row.last_run?.run_id || '-'}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{formatCost(row.last_provider_call?.cost)} credits</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {row.last_provider_call?.latency_ms ? `${row.last_provider_call.latency_ms}ms` : '-'}
                  {row.last_provider_call?.error_code ? ` · ${row.last_provider_call.error_code}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
          Evidence source: run_records and provider_call_records. This view is read-only and does not change routing, prompts, abilities, or WordPress writes.
        </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeView === 'health' ? (
        <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Model health</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
          Provider/model health from provider_call_records. Metadata only: prompts, results, and provider secrets are not exposed.
        </p>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1.2fr_8rem_1fr_1fr_1fr_1.2fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>Provider / model</span>
            <span>Status</span>
            <span>Calls</span>
            <span>Latency</span>
            <span>Tokens / cost</span>
            <span>Last error</span>
          </div>
          {(data.provider_model_health?.rows || []).map((row) => (
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
                <div>{row.call_count} calls · {formatRate(row.success_rate)}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {row.success_count} ok · {row.error_count} errors
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{typeof row.avg_latency_ms === 'number' ? `${row.avg_latency_ms}ms avg` : '-'}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {typeof row.p95_latency_ms === 'number' ? `${row.p95_latency_ms}ms p95` : '-'}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{row.tokens_in + row.tokens_out} tokens</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {formatCost(row.cost)} credits · {row.retry_count} retries · {row.fallback_count} fallback
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
          {data.provider_model_health?.rows?.length ? null : (
            <div className="px-4 py-6 text-sm text-slate-500 dark:text-slate-400">
              No provider call records observed in the current evidence window.
            </div>
          )}
        </div>
        <div className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
          Evidence source: {data.provider_model_health?.source || 'provider_call_records'}; recent call limit {data.provider_model_health?.recent_call_limit || 200}. This view is read-only diagnostics and does not change routing, prompts, abilities, or WordPress writes.
        </div>
        </BackofficeSectionPanel>
      ) : null}

      {activeView === 'matrix' ? (
        <>
          <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Runtime resolution</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
          Current Cloud runtime resolution by capability. This is read-only operator evidence, not a router editor.
        </p>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1fr_8rem_1fr_1.2fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>Capability</span>
            <span>Status</span>
            <span>Profile</span>
            <span>Provider / model</span>
            <span>Connections</span>
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
                  adapter {row.runtime_provider_available ? 'available' : 'not loaded'}
                </div>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                <div>{labelList(row.ready_connection_ids)}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  selected {labelList(row.selected_connection_ids)}
                </div>
              </div>
            </div>
          ))}
        </div>
          </BackofficeSectionPanel>

          <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Capability Matrix</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
          Cloud runtime mapping from capability to profile, provider, model, and write posture. This is operator detail, not a WordPress ability editor.
        </p>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1fr_8rem_1.1fr_1.2fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>Capability</span>
            <span>Status</span>
            <span>Profiles</span>
            <span>Provider / model</span>
            <span>Write posture</span>
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
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Runtime profiles</h2>
        <div className="mt-4 grid gap-3">
          {data.runtime_profiles.map((profile) => (
            <BackofficeStackCard key={profile.profile_id} className="grid gap-3 lg:grid-cols-[1fr_9rem_1.2fr_1fr] lg:items-center">
              <div>
                <div className="font-semibold text-slate-950 dark:text-white">{profile.profile_id}</div>
                <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {profile.kind} · {labelList(profile.used_by)}
                  {profile.selected_for?.length ? ` · selected for ${labelList(profile.selected_for)}` : ''}
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
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Recent runtime evidence</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              Last observed run metadata for each profile. Prompt and result content are not exposed here.
            </p>
          </div>
          <BackofficeStatusBadge
            label={data.recent_runtime_evidence?.content_exposed ? 'Review' : 'Metadata only'}
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
                    {evidence?.run_id || 'No recent run'}
                  </div>
                </div>
                <BackofficeStatusBadge
                  label={evidence?.status || 'not observed'}
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
