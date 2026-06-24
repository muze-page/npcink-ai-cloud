'use client';

import Link from 'next/link';
import React, { Suspense, useEffect, useMemo, useState } from 'react';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
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
  runtime_profiles: RuntimeProfile[];
  profile_preferences: ProfilePreferences;
  boundary: {
    direct_wordpress_write: boolean;
    final_writes: string;
    secret_exposure: string;
    not_a_control_plane: boolean;
  };
};

function statusTone(status: ResourceStatus): 'success' | 'warning' | 'disabled' | 'info' {
  if (status === 'ready') return 'success';
  if (status === 'disabled') return 'disabled';
  if (status === 'missing_secret' || status === 'missing_provider') return 'warning';
  return 'info';
}

function labelList(values: string[]): string {
  return values.length ? values.join(', ') : '-';
}

function AiResourcesContent() {
  const [data, setData] = useState<AiResources | null>(null);
  const [preferences, setPreferences] = useState<ProfilePreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingPreferences, setSavingPreferences] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    let mounted = true;
    async function loadResources() {
      setLoading(true);
      setError('');
      try {
        const response = await fetch('/api/admin/ai-resources', { credentials: 'include' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(resolveUiErrorMessage(payload, 'Failed to load AI resources.'));
        }
        if (mounted) {
          const normalized = payload.data as AiResources;
          setData(normalized);
          setPreferences(normalized.profile_preferences);
        }
      } catch (loadError) {
        if (mounted) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load AI resources.');
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    loadResources();
    return () => {
      mounted = false;
    };
  }, []);

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

  function updatePreferences(patch: Partial<ProfilePreferences>) {
    setPreferences((current) => (current ? { ...current, ...patch } : current));
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

  if (loading) {
    return <LoadingFallback />;
  }

  if (error || !data) {
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
        <BackofficeStackCard className="flex flex-col gap-3 text-sm leading-6 text-slate-600 dark:text-slate-300 lg:flex-row lg:items-center lg:justify-between">
          <span>
            Provider keys stay in Cloud runtime settings. WordPress writes, approvals, abilities, workflows, prompts, and router truth stay outside this page.
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

      <BackofficeSectionPanel>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Connections</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              Masked provider connection status. Secrets are never returned to the browser.
            </p>
          </div>
        </div>
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
                <div>Capabilities: {labelList(connection.capability_ids)}</div>
                <div>Profiles: {labelList(connection.runtime_profile_ids)}</div>
              </div>
              {connection.detail_href ? (
                <Link href={connection.detail_href} className="btn btn-secondary w-fit">
                  Configure {connection.display_name}
                </Link>
              ) : null}
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

      <BackofficeSectionPanel>
        <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Capabilities</h2>
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <div className="grid grid-cols-[1fr_9rem_1.2fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
            <span>Capability</span>
            <span>Status</span>
            <span>Default profile</span>
            <span>Write posture</span>
          </div>
          {data.capabilities.map((capability) => (
            <div
              key={capability.capability_id}
              className="grid grid-cols-[1fr_9rem_1.2fr_1fr] gap-3 border-b border-slate-200 px-4 py-3 text-sm last:border-b-0 dark:border-slate-800"
            >
              <div>
                <div className="font-medium text-slate-950 dark:text-white">{capability.label}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {labelList(capability.used_by)}
                </div>
              </div>
              <BackofficeStatusBadge label={capability.status} status={statusTone(capability.status)} />
              <div className="text-slate-600 dark:text-slate-300">{capability.default_profile_id}</div>
              <div className="text-slate-600 dark:text-slate-300">{capability.write_posture}</div>
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
