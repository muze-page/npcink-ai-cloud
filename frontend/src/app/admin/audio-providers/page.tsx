'use client';

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

type MiniMaxProviderState = {
  provider_id: 'minimax';
  display_name: string;
  enabled: boolean;
  configured: boolean;
  status: string;
  base_url: string;
  api_key: {
    configured: boolean;
    display: string;
  };
  group_id: {
    configured: boolean;
    display: string;
    optional: boolean;
  };
};

type AudioProviderConfig = {
  provider_mode: string;
  env_path: string;
  requires_worker_restart_after_save: boolean;
  providers: {
    minimax: MiniMaxProviderState;
  };
  runtime: {
    timeout_seconds: number;
    default_voice_id: string;
    models: string[];
    supported_intents: string[];
  };
};

type MiniMaxForm = {
  enabled: boolean;
  base_url: string;
  secret: string;
  clear_secret: boolean;
  group_id: string;
  clear_group_id: boolean;
};

type AudioTestResult = {
  provider_id: string;
  status: string;
  generated_at: string;
  sample_text: string;
  model_id: string;
  profile_id: string;
  default_voice_id: string;
  latency_ms: number;
  artifact: {
    provider_response_format?: string;
    usage?: {
      characters?: number;
      duration_ms?: number;
      trace_id?: string;
    };
    audios?: Array<{
      url?: string;
      b64_json?: string;
      mime_type?: string;
      format?: string;
      duration_seconds?: number;
      transcript?: string;
    }>;
  };
  boundary: {
    direct_wordpress_write: boolean;
    final_writes: string;
  };
};

const DEFAULT_CONFIG: AudioProviderConfig = {
  provider_mode: 'disabled',
  env_path: '',
  requires_worker_restart_after_save: true,
  providers: {
    minimax: {
      provider_id: 'minimax',
      display_name: 'MiniMax',
      enabled: false,
      configured: false,
      status: 'missing_secret',
      base_url: 'https://api.minimaxi.com',
      api_key: { configured: false, display: 'missing' },
      group_id: { configured: false, display: 'not_configured', optional: true },
    },
  },
  runtime: {
    timeout_seconds: 30,
    default_voice_id: 'male-qn-qingse',
    models: ['speech-2.8-turbo', 'speech-2.8-hd'],
    supported_intents: ['article_narration', 'article_audio_summary'],
  },
};

function normalizeConfig(raw: any): AudioProviderConfig {
  const provider = raw?.providers?.minimax ?? {};
  return {
    provider_mode: String(raw?.provider_mode ?? DEFAULT_CONFIG.provider_mode),
    env_path: String(raw?.env_path ?? ''),
    requires_worker_restart_after_save: Boolean(raw?.requires_worker_restart_after_save ?? true),
    providers: {
      minimax: {
        provider_id: 'minimax',
        display_name: String(provider.display_name ?? 'MiniMax'),
        enabled: Boolean(provider.enabled),
        configured: Boolean(provider.configured),
        status: String(provider.status ?? 'missing_secret'),
        base_url: String(provider.base_url ?? DEFAULT_CONFIG.providers.minimax.base_url),
        api_key: {
          configured: Boolean(provider.api_key?.configured),
          display: String(provider.api_key?.display ?? 'missing'),
        },
        group_id: {
          configured: Boolean(provider.group_id?.configured),
          display: String(provider.group_id?.display ?? 'not_configured'),
          optional: Boolean(provider.group_id?.optional ?? true),
        },
      },
    },
    runtime: {
      timeout_seconds: Number(raw?.runtime?.timeout_seconds ?? DEFAULT_CONFIG.runtime.timeout_seconds),
      default_voice_id: String(raw?.runtime?.default_voice_id ?? DEFAULT_CONFIG.runtime.default_voice_id),
      models: Array.isArray(raw?.runtime?.models) ? raw.runtime.models.map(String) : DEFAULT_CONFIG.runtime.models,
      supported_intents: Array.isArray(raw?.runtime?.supported_intents)
        ? raw.runtime.supported_intents.map(String)
        : DEFAULT_CONFIG.runtime.supported_intents,
    },
  };
}

function formFromConfig(config: AudioProviderConfig): MiniMaxForm {
  return {
    enabled: config.providers.minimax.enabled,
    base_url: config.providers.minimax.base_url,
    secret: '',
    clear_secret: false,
    group_id: '',
    clear_group_id: false,
  };
}

function audioPreviewSource(result: AudioTestResult | null): string {
  const audio = result?.artifact?.audios?.[0];
  if (!audio) {
    return '';
  }
  if (audio.url) {
    return `/api/admin/audio-preview?url=${encodeURIComponent(audio.url)}`;
  }
  if (audio.b64_json) {
    return `data:${audio.mime_type || 'audio/mpeg'};base64,${audio.b64_json}`;
  }
  return '';
}

function AudioProvidersAdminContent() {
  const [config, setConfig] = useState<AudioProviderConfig | null>(null);
  const [form, setForm] = useState<MiniMaxForm | null>(null);
  const [testResult, setTestResult] = useState<AudioTestResult | null>(null);
  const [timeoutSeconds, setTimeoutSeconds] = useState(30);
  const [defaultVoiceId, setDefaultVoiceId] = useState('male-qn-qingse');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let mounted = true;
    async function loadConfig() {
      setLoading(true);
      setError('');
      try {
        const response = await fetch('/api/admin/audio-providers', { credentials: 'include' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(resolveUiErrorMessage(payload, 'Failed to load audio provider settings.'));
        }
        const normalized = normalizeConfig(payload.data ?? {});
        if (!mounted) return;
        setConfig(normalized);
        setForm(formFromConfig(normalized));
        setTimeoutSeconds(normalized.runtime.timeout_seconds);
        setDefaultVoiceId(normalized.runtime.default_voice_id);
      } catch (loadError) {
        if (!mounted) return;
        setError(loadError instanceof Error ? loadError.message : 'Failed to load audio provider settings.');
      } finally {
        if (mounted) setLoading(false);
      }
    }
    loadConfig();
    return () => {
      mounted = false;
    };
  }, []);

  const metrics = useMemo(() => {
    if (!config) return [];
    const provider = config.providers.minimax;
    return [
      {
        label: 'Provider',
        value: provider.enabled ? 'MiniMax active' : 'Disabled',
        detail: 'Cloud runtime registration for audio generation.',
      },
      {
        label: 'API key',
        value: provider.configured ? 'Configured' : 'Missing',
        detail: 'Secret status only. The key is never returned to the browser.',
      },
      {
        label: 'GroupId',
        value: provider.group_id.configured ? 'Configured' : 'Optional',
        detail: 'Used only for MiniMax accounts that require GroupId.',
      },
      {
        label: 'Storage',
        value: config.env_path || 'runtime env',
        detail: 'Cloud-side provider settings file.',
        size: 'compact' as const,
      },
    ];
  }, [config]);

  function updateForm(patch: Partial<MiniMaxForm>) {
    setForm((current) => (current ? { ...current, ...patch } : current));
  }

  async function save() {
    if (!form) return;
    setSaving(true);
    setMessage('');
    setError('');
    try {
      const response = await fetch('/api/admin/audio-providers', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_mode: form.enabled ? 'minimax' : 'disabled',
          providers: {
            minimax: form,
          },
          runtime: {
            timeout_seconds: timeoutSeconds,
            default_voice_id: defaultVoiceId,
          },
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to save audio provider settings.'));
      }
      const normalized = normalizeConfig(payload.data ?? {});
      setConfig(normalized);
      setForm(formFromConfig(normalized));
      setTimeoutSeconds(normalized.runtime.timeout_seconds);
      setDefaultVoiceId(normalized.runtime.default_voice_id);
      setMessage('Audio provider settings saved. Restart worker processes for queued runs to pick up the same values.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save audio provider settings.');
    } finally {
      setSaving(false);
    }
  }

  async function testMiniMax() {
    setTesting(true);
    setMessage('');
    setError('');
    setTestResult(null);
    try {
      const response = await fetch('/api/admin/audio-providers/minimax/test', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to generate MiniMax sample audio.'));
      }
      setTestResult(payload.data as AudioTestResult);
      setMessage('MiniMax sample audio generated.');
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : 'Failed to generate MiniMax sample audio.');
    } finally {
      setTesting(false);
    }
  }

  if (loading) {
    return <LoadingFallback />;
  }

  if (!config || !form) {
    return (
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow="Provider settings"
          title="Audio Providers"
          description="Cloud-managed audio provider settings."
        >
          <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
            {error || 'Audio provider settings are unavailable.'}
          </BackofficeStackCard>
        </BackofficePrimaryPanel>
      </BackofficePageStack>
    );
  }

  const provider = config.providers.minimax;
  const previewSource = audioPreviewSource(testResult);
  const previewAudio = testResult?.artifact?.audios?.[0];

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow="Provider settings / Audio providers"
        title="MiniMax"
        description="Configure Cloud-owned MiniMax credentials for article narration and long-form audio summary generation."
        aside={(
          <BackofficeStatusBadge
            label={provider.configured ? (provider.enabled ? 'Ready' : 'Configured') : 'Missing key'}
            status={provider.configured ? (provider.enabled ? 'success' : 'warning') : 'warning'}
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
      </BackofficePrimaryPanel>

      <BackofficeSectionPanel>
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(20rem,0.9fr)]">
          <div className="space-y-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950 dark:text-white">MiniMax connection</h2>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  API key is required. GroupId is optional for accounts that still require it.
                </p>
              </div>
              <label className="inline-flex items-center gap-2 text-sm font-semibold text-slate-700 dark:text-slate-200">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(event) => updateForm({ enabled: event.target.checked })}
                />
                Enable MiniMax
              </label>
            </div>

            <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              Base URL
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={form.base_url}
                onChange={(event) => updateForm({ base_url: event.target.value })}
              />
            </label>

            <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              API key
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={form.secret}
                onChange={(event) => updateForm({ secret: event.target.value, clear_secret: false })}
                placeholder={provider.api_key.configured ? 'Configured. Leave blank to keep existing key.' : 'Paste MiniMax API key'}
                type="password"
                autoComplete="new-password"
              />
            </label>

            <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <input
                type="checkbox"
                checked={form.clear_secret}
                onChange={(event) => updateForm({ clear_secret: event.target.checked, secret: '' })}
              />
              Clear stored API key
            </label>

            <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              GroupId
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={form.group_id}
                onChange={(event) => updateForm({ group_id: event.target.value, clear_group_id: false })}
                placeholder={provider.group_id.configured ? 'Configured. Leave blank to keep existing GroupId.' : 'Optional MiniMax GroupId'}
                type="password"
                autoComplete="new-password"
              />
            </label>

            <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <input
                type="checkbox"
                checked={form.clear_group_id}
                onChange={(event) => updateForm({ clear_group_id: event.target.checked, group_id: '' })}
              />
              Clear stored GroupId
            </label>
          </div>

          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Audio defaults</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                Defaults apply when the runtime request does not specify a voice or a tighter timeout.
              </p>
            </div>

            <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              Timeout seconds
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={timeoutSeconds}
                onChange={(event) => setTimeoutSeconds(Number(event.target.value || 0))}
                type="number"
                min="1"
              />
            </label>

            <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              Default voice ID
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={defaultVoiceId}
                onChange={(event) => setDefaultVoiceId(event.target.value)}
              />
            </label>

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-200">
              <div className="font-semibold text-slate-950 dark:text-white">Runtime scope</div>
              <div className="mt-2">Models: {config.runtime.models.join(', ')}</div>
              <div>Intents: {config.runtime.supported_intents.join(', ')}</div>
            </div>
          </div>
        </div>
      </BackofficeSectionPanel>

      <BackofficeSectionPanel>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
            Saving updates Cloud runtime configuration only. Generated audio remains a candidate artifact; WordPress writes still go through the local governed path.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={testMiniMax}
              disabled={testing || !provider.configured}
              className="inline-flex h-11 items-center justify-center rounded-lg border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-800 shadow-sm transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:hover:bg-slate-900"
            >
              {testing ? 'Generating sample...' : 'Test MiniMax audio'}
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="inline-flex h-11 items-center justify-center rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? 'Saving...' : 'Save MiniMax settings'}
            </button>
          </div>
        </div>
      </BackofficeSectionPanel>

      <BackofficeSectionPanel>
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Connection test</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              Generates one short sample through MiniMax. The result stays a Cloud runtime candidate artifact and is not written to WordPress.
            </p>
          </div>

          {testResult ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,0.65fr)]">
              <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/60">
                <div className="text-sm font-semibold text-slate-950 dark:text-white">Sample playback</div>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {testResult.sample_text}
                </p>
                {previewSource ? (
                  <audio className="mt-4 w-full" controls src={previewSource}>
                    Your browser does not support audio playback.
                  </audio>
                ) : (
                  <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">
                    MiniMax returned metadata but no playable audio URL or base64 payload.
                  </p>
                )}
              </div>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-200">
                <div className="font-semibold text-slate-950 dark:text-white">Result</div>
                <div className="mt-2">Provider: {testResult.provider_id}</div>
                <div>Model: {testResult.model_id}</div>
                <div>Voice: {testResult.default_voice_id || 'default'}</div>
                <div>Duration: {previewAudio?.duration_seconds || 0}s</div>
                <div>Latency: {testResult.latency_ms}ms</div>
                <div>Trace: {testResult.artifact.usage?.trace_id || 'not returned'}</div>
                <div>WordPress write: {testResult.boundary.direct_wordpress_write ? 'yes' : 'no'}</div>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300">
              Run a MiniMax audio test after saving credentials.
            </div>
          )}
        </div>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function AudioProvidersAdminPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AudioProvidersAdminContent />
    </Suspense>
  );
}
