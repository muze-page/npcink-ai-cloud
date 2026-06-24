'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
import { resolveUiErrorMessage } from '@/lib/errors';

type TextInstance = {
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
  group_id: string;
  label: string;
  description: string;
  tasks: string[];
  candidate_instance_ids: string[];
  timeout_ms: number;
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
  available_text_instances: TextInstance[];
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

type EditableProfile = RoutingProfile & {
  note: string;
};

function normalizeRoutingData(raw: any): RoutingData {
  const data = raw ?? {};
  return {
    surface: String(data.surface ?? ''),
    owner: String(data.owner ?? ''),
    local_control_plane: String(data.local_control_plane ?? ''),
    customer_model_selection: Boolean(data.customer_model_selection),
    direct_wordpress_write: Boolean(data.direct_wordpress_write),
    prompt_or_preset_editor: Boolean(data.prompt_or_preset_editor),
    available_text_instances: Array.isArray(data.available_text_instances)
      ? data.available_text_instances.map((item: any) => ({
          instance_id: String(item?.instance_id ?? ''),
          provider_id: String(item?.provider_id ?? ''),
          model_id: String(item?.model_id ?? ''),
          endpoint_variant: String(item?.endpoint_variant ?? ''),
          region: String(item?.region ?? ''),
          health_status: String(item?.health_status ?? ''),
          weight: Number(item?.weight ?? 0) || 0,
          capability_tags: Array.isArray(item?.capability_tags)
            ? item.capability_tags.map(String)
            : [],
          model_status: String(item?.model_status ?? ''),
          model_feature: String(item?.model_feature ?? ''),
        }))
      : [],
    profiles: Array.isArray(data.profiles)
      ? data.profiles.map((profile: any) => ({
          profile_id: String(profile?.profile_id ?? ''),
          group_id: String(profile?.group_id ?? ''),
          label: String(profile?.label ?? ''),
          description: String(profile?.description ?? ''),
          tasks: Array.isArray(profile?.tasks) ? profile.tasks.map(String) : [],
          candidate_instance_ids: Array.isArray(profile?.candidate_instance_ids)
            ? profile.candidate_instance_ids.map(String)
            : [],
          timeout_ms: Number(profile?.timeout_ms ?? 30000) || 30000,
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

function instanceLabel(instance: TextInstance | undefined): string {
  if (!instance) {
    return 'Unassigned';
  }
  return `${instance.instance_id} · ${instance.model_id}`;
}

function idempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `wp-ai-routing-${crypto.randomUUID()}`;
  }
  return `wp-ai-routing-${Date.now()}`;
}

export default function WordPressAIRoutingPage() {
  const [data, setData] = useState<RoutingData | null>(null);
  const [drafts, setDrafts] = useState<EditableProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [savedMessage, setSavedMessage] = useState('');

  const instancesById = useMemo(() => {
    const map = new Map<string, TextInstance>();
    for (const instance of data?.available_text_instances ?? []) {
      map.set(instance.instance_id, instance);
    }
    return map;
  }, [data?.available_text_instances]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/admin/wordpress-ai-routing', {
        credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to load WordPress AI routing.'));
      }
      const normalized = normalizeRoutingData(payload.data);
      setData(normalized);
      setDrafts(normalized.profiles.map((profile) => ({ ...profile, note: '' })));
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : 'Failed to load WordPress AI routing.'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const updateDraft = useCallback(
    (profileId: string, patch: Partial<EditableProfile>) => {
      setDrafts((current) =>
        current.map((profile) =>
          profile.profile_id === profileId ? { ...profile, ...patch } : profile
        )
      );
    },
    []
  );

  const updateCandidate = useCallback(
    (profileId: string, index: number, instanceId: string) => {
      setDrafts((current) =>
        current.map((profile) => {
          if (profile.profile_id !== profileId) {
            return profile;
          }
          const nextCandidates = [...profile.candidate_instance_ids];
          nextCandidates[index] = instanceId;
          const uniqueCandidates = nextCandidates
            .map((value) => value.trim())
            .filter(Boolean)
            .filter((value, candidateIndex, values) => values.indexOf(value) === candidateIndex);
          return { ...profile, candidate_instance_ids: uniqueCandidates };
        })
      );
    },
    []
  );

  const save = useCallback(async () => {
    setSaving(true);
    setError('');
    setSavedMessage('');
    try {
      const response = await fetch('/api/admin/wordpress-ai-routing', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey(),
        },
        body: JSON.stringify({
          profiles: drafts.map((profile) => ({
            profile_id: profile.profile_id,
            candidate_instance_ids: profile.candidate_instance_ids,
            timeout_ms: profile.timeout_ms,
            allow_fallback: profile.allow_fallback,
            max_retries: profile.max_retries,
            note: profile.note,
          })),
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to save WordPress AI routing.'));
      }
      const normalized = normalizeRoutingData(payload.data);
      setData(normalized);
      setDrafts(normalized.profiles.map((profile) => ({ ...profile, note: '' })));
      setSavedMessage(payload.data?.receipt?.effective_summary || 'Routing saved.');
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : 'Failed to save WordPress AI routing.'
      );
    } finally {
      setSaving(false);
    }
  }, [drafts]);

  if (loading) {
    return <LoadingFallback />;
  }

  if (!data) {
    return (
      <BackofficePageStack>
        <BackofficeEmptyState
          title="WordPress AI routing unavailable"
          description={error || 'The routing projection could not be loaded.'}
        />
      </BackofficePageStack>
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow="Platform admin"
        title="WordPress AI routing"
        description="Cloud-managed runtime profiles for bounded WordPress AI connector tasks. WordPress users do not select raw model instances."
        aside={
          <BackofficeStatusBadge
            label={data.boundary.admin_surface || 'platform admin only'}
            status="read_only"
          />
        }
        actions={
          <>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-900"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="rounded-full bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {saving ? 'Saving...' : 'Save routing'}
            </button>
          </>
        }
      >
        <BackofficeMetricStrip
          columnsClassName="xl:grid-cols-4"
          items={[
            {
              label: 'Task groups',
              value: data.profiles.length,
              detail: 'Fixed connector groups',
            },
            {
              label: 'Text instances',
              value: data.available_text_instances.length,
              detail: 'Available catalog candidates',
            },
            {
              label: 'Write posture',
              value: data.boundary.results_write_posture || 'suggestion_only',
              detail: 'Cloud does not write WordPress',
              size: 'compact',
            },
            {
              label: 'Model selection',
              value: data.customer_model_selection ? 'customer' : 'platform',
              detail: 'Configured by platform admin',
              size: 'compact',
            },
          ]}
        />
        {error ? (
          <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
            {error}
          </BackofficeStackCard>
        ) : null}
        {savedMessage ? (
          <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/25 dark:text-emerald-200">
            {savedMessage}
          </BackofficeStackCard>
        ) : null}
      </BackofficePrimaryPanel>

      <div className="space-y-4">
        {drafts.map((profile) => (
          <BackofficeSectionPanel key={profile.profile_id}>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
                    {profile.label}
                  </h2>
                  <BackofficeStatusBadge
                    label={profile.status === 'configured' ? 'configured' : 'needs candidates'}
                    status={profile.status === 'configured' ? 'success' : 'warning'}
                  />
                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                    {profile.profile_id}
                  </span>
                </div>
                <p className="max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {profile.description}
                </p>
                <div className="flex flex-wrap gap-2">
                  {profile.tasks.map((task) => (
                    <span
                      key={task}
                      className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300"
                    >
                      {task}
                    </span>
                  ))}
                </div>
              </div>
              <div className="text-right text-xs text-slate-500 dark:text-slate-400">
                <div>{profile.revision || 'No revision'}</div>
                <div>{profile.updated_at || 'No update timestamp'}</div>
              </div>
            </div>

            <div className="mt-5 grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
              <div className="space-y-3">
                {[0, 1, 2].map((index) => {
                  const selectedId = profile.candidate_instance_ids[index] || '';
                  const selected = instancesById.get(selectedId);
                  return (
                    <label
                      key={`${profile.profile_id}-${index}`}
                      className="block rounded-[1rem] border border-slate-200 bg-white/70 p-3 dark:border-slate-800 dark:bg-slate-950/40"
                    >
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                        {index === 0 ? 'Primary' : `Fallback ${index}`}
                      </span>
                      <select
                        value={selectedId}
                        onChange={(event) =>
                          updateCandidate(profile.profile_id, index, event.target.value)
                        }
                        className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                      >
                        <option value="">Unassigned</option>
                        {data.available_text_instances.map((instance) => (
                          <option
                            key={`${profile.profile_id}-${index}-${instance.instance_id}`}
                            value={instance.instance_id}
                          >
                            {instanceLabel(instance)}
                          </option>
                        ))}
                      </select>
                      {selected ? (
                        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                          {selected.provider_id} · {selected.endpoint_variant} ·{' '}
                          {selected.region || 'global'} · {selected.health_status}
                        </p>
                      ) : null}
                    </label>
                  );
                })}
              </div>

              <div className="space-y-3">
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    Timeout ms
                  </span>
                  <input
                    type="number"
                    min={1000}
                    max={60000}
                    step={1000}
                    value={profile.timeout_ms}
                    onChange={(event) =>
                      updateDraft(profile.profile_id, {
                        timeout_ms: Number(event.target.value) || 30000,
                      })
                    }
                    className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                  />
                </label>
                <label className="flex items-center justify-between rounded-xl border border-slate-200 bg-white/70 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/40">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    Provider fallback
                  </span>
                  <input
                    type="checkbox"
                    checked={profile.allow_fallback}
                    onChange={(event) =>
                      updateDraft(profile.profile_id, {
                        allow_fallback: event.target.checked,
                      })
                    }
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    Retry max
                  </span>
                  <select
                    value={profile.max_retries}
                    onChange={(event) =>
                      updateDraft(profile.profile_id, {
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
                    Operator note
                  </span>
                  <textarea
                    value={profile.note}
                    onChange={(event) =>
                      updateDraft(profile.profile_id, { note: event.target.value })
                    }
                    rows={3}
                    className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    placeholder="Why this routing chain is being changed"
                  />
                </label>
              </div>
            </div>
          </BackofficeSectionPanel>
        ))}
      </div>
    </BackofficePageStack>
  );
}
