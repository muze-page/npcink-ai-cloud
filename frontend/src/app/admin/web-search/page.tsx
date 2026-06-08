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
import {
  CloudWorkflowMetadataPanel,
  normalizeCloudWorkflowMetadata,
  type CloudWorkflowMetadata,
} from '@/components/backoffice/CloudWorkflowMetadataPanel';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { resolveUiErrorMessage } from '@/lib/errors';

type ProviderId = 'tavily' | 'bocha' | 'jina_reader' | 'apify';

type ProviderState = {
  provider_id: ProviderId;
  display_name: string;
  enabled: boolean;
  configured: boolean;
  status: string;
  base_url: string;
  timeout_seconds: number;
  cost: number;
  actor_id?: string;
  max_pages?: number;
};

type WebSearchConfig = {
  provider_mode: string;
  env_path: string;
  requires_worker_restart_after_save: boolean;
  providers: Record<ProviderId, ProviderState>;
  workflowMetadata: CloudWorkflowMetadata;
};

type ProviderForm = {
  base_url: string;
  secret: string;
  clear_secret: boolean;
  timeout_seconds: number;
  cost: number;
  enabled?: boolean;
  actor_id?: string;
  max_pages?: number;
};

const PROVIDERS: ProviderId[] = ['tavily', 'bocha', 'jina_reader', 'apify'];

const MODE_LABELS: Record<string, string> = {
  disabled: 'Disabled',
  auto: 'Auto fallback',
  tavily: 'Tavily',
  bocha: 'Bocha',
  apify: 'Apify',
};

function normalizeConfig(raw: any): WebSearchConfig {
  const providers = raw?.providers ?? {};
  const normalizeProvider = (providerId: ProviderId, fallbackName: string): ProviderState => {
    const provider = providers?.[providerId] ?? {};
    return {
      provider_id: providerId,
      display_name: String(provider.display_name ?? fallbackName),
      enabled: Boolean(provider.enabled),
      configured: Boolean(provider.configured),
      status: String(provider.status ?? 'missing_secret'),
      base_url: String(provider.base_url ?? ''),
      timeout_seconds: Number(provider.timeout_seconds ?? 15),
      cost: Number(provider.cost ?? 0),
      actor_id: provider.actor_id ? String(provider.actor_id) : '',
      max_pages: Number(provider.max_pages ?? 2),
    };
  };
  return {
    provider_mode: String(raw?.provider_mode ?? 'disabled'),
    env_path: String(raw?.env_path ?? ''),
    requires_worker_restart_after_save: Boolean(raw?.requires_worker_restart_after_save),
    providers: {
      tavily: normalizeProvider('tavily', 'Tavily'),
      bocha: normalizeProvider('bocha', 'Bocha'),
      jina_reader: normalizeProvider('jina_reader', 'Jina Reader'),
      apify: normalizeProvider('apify', 'Apify'),
    },
    workflowMetadata: normalizeCloudWorkflowMetadata(raw?.workflow_metadata ?? {}),
  };
}

function emptyForms(config: WebSearchConfig): Record<ProviderId, ProviderForm> {
  return PROVIDERS.reduce((forms, providerId) => {
    const provider = config.providers[providerId];
    forms[providerId] = {
      base_url: provider.base_url,
      secret: '',
      clear_secret: false,
      timeout_seconds: provider.timeout_seconds,
      cost: provider.cost,
      enabled: provider.enabled,
      actor_id: provider.actor_id || '',
      max_pages: provider.max_pages || 2,
    };
    return forms;
  }, {} as Record<ProviderId, ProviderForm>);
}

function providerHelp(providerId: ProviderId): string {
  switch (providerId) {
    case 'tavily':
      return 'General web search provider. Used directly or as the first auto fallback source.';
    case 'bocha':
      return 'Search provider useful for Chinese and broader public source lookup.';
    case 'jina_reader':
      return 'Reader enhancement for selected result URLs. It enriches search results but is not the primary search provider.';
    case 'apify':
      return 'Apify actor-backed search. Configure an actor that returns dataset items with title, URL, and snippet-like fields.';
  }
}

function WebSearchAdminContent() {
  const [config, setConfig] = useState<WebSearchConfig | null>(null);
  const [providerMode, setProviderMode] = useState('disabled');
  const [forms, setForms] = useState<Record<ProviderId, ProviderForm> | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let mounted = true;
    async function loadConfig() {
      setLoading(true);
      setError('');
      try {
        const response = await fetch('/api/admin/web-search-providers', { credentials: 'include' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(resolveUiErrorMessage(payload, 'Failed to load web search provider settings.'));
        }
        const normalized = normalizeConfig(payload.data ?? {});
        if (!mounted) return;
        setConfig(normalized);
        setProviderMode(normalized.provider_mode);
        setForms(emptyForms(normalized));
      } catch (loadError) {
        if (!mounted) return;
        setError(loadError instanceof Error ? loadError.message : 'Failed to load web search provider settings.');
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
    const configuredCount = PROVIDERS.filter((providerId) => config.providers[providerId].configured).length;
    return [
      {
        label: 'Mode',
        value: MODE_LABELS[providerMode] ?? providerMode,
        detail: 'Default cloud search routing mode.',
      },
      {
        label: 'Configured',
        value: `${configuredCount}/4`,
        detail: 'Provider secrets present in Cloud runtime configuration.',
      },
      {
        label: 'Storage',
        value: config.env_path || 'runtime env',
        detail: 'Secrets remain Cloud-side and are not returned to the browser.',
        size: 'compact' as const,
      },
      {
        label: 'Worker',
        value: config.requires_worker_restart_after_save ? 'Restart' : 'Live',
        detail: config.requires_worker_restart_after_save ? 'Restart worker after provider changes.' : 'Changes apply immediately.',
      },
    ];
  }, [config, providerMode]);

  function updateProvider(providerId: ProviderId, patch: Partial<ProviderForm>) {
    setForms((current) => {
      if (!current) return current;
      return {
        ...current,
        [providerId]: {
          ...current[providerId],
          ...patch,
        },
      };
    });
  }

  async function save() {
    if (!forms) return;
    setSaving(true);
    setMessage('');
    setError('');
    try {
      const response = await fetch('/api/admin/web-search-providers', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_mode: providerMode,
          providers: forms,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to save web search provider settings.'));
      }
      const normalized = normalizeConfig(payload.data ?? {});
      setConfig(normalized);
      setProviderMode(normalized.provider_mode);
      setForms(emptyForms(normalized));
      setMessage('Web search provider settings saved. Restart worker processes for queued runs to pick up the same values.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save web search provider settings.');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <LoadingFallback />;
  }

  if (!config || !forms) {
    return (
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow="Cloud Runtime"
          title="Web Search Providers"
          description="Cloud-managed web search provider settings."
        >
          <BackofficeStackCard className="border-rose-200 bg-rose-50 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/25 dark:text-rose-200">
            {error || 'Web search provider settings are unavailable.'}
          </BackofficeStackCard>
        </BackofficePrimaryPanel>
      </BackofficePageStack>
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow="Cloud Runtime"
        title="Web Search Providers"
        description="Configure Cloud-owned search provider credentials. WordPress sites never provide or receive these provider keys."
        aside={<BackofficeStatusBadge label={MODE_LABELS[providerMode] ?? providerMode} status={providerMode === 'disabled' ? 'disabled' : 'active'} />}
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
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Default provider mode</h2>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              Auto tries configured search providers in Cloud order. Jina Reader can enhance results after a search provider returns URLs.
            </p>
          </div>
          <select
            className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            value={providerMode}
            onChange={(event) => setProviderMode(event.target.value)}
          >
            {Object.entries(MODE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
      </BackofficeSectionPanel>

      <CloudWorkflowMetadataPanel metadata={config.workflowMetadata} />

      <div className="grid gap-4 xl:grid-cols-2">
        {PROVIDERS.map((providerId) => {
          const provider = config.providers[providerId];
          const form = forms[providerId];
          return (
            <BackofficeSectionPanel key={providerId}>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{provider.display_name}</h2>
                    <BackofficeStatusBadge
                      label={provider.configured ? 'Configured' : 'Missing key'}
                      status={provider.configured ? 'success' : 'warning'}
                    />
                    {provider.enabled ? <BackofficeStatusBadge label="Active" status="active" /> : null}
                  </div>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{providerHelp(providerId)}</p>
                </div>
              </div>

              <div className="mt-5 grid gap-4">
                {providerId === 'jina_reader' ? (
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                    <input
                      type="checkbox"
                      checked={Boolean(form.enabled)}
                      onChange={(event) => updateProvider(providerId, { enabled: event.target.checked })}
                    />
                    Enable reader enhancement
                  </label>
                ) : null}

                <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                  Base URL
                  <input
                    className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                    value={form.base_url}
                    onChange={(event) => updateProvider(providerId, { base_url: event.target.value })}
                  />
                </label>

                {providerId === 'apify' ? (
                  <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                    Actor ID
                    <input
                      className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                      value={form.actor_id || ''}
                      onChange={(event) => updateProvider(providerId, { actor_id: event.target.value })}
                      placeholder="apify/google-search-scraper"
                    />
                  </label>
                ) : null}

                <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                  {providerId === 'apify' ? 'API token' : 'API key'}
                  <input
                    className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                    value={form.secret}
                    onChange={(event) => updateProvider(providerId, { secret: event.target.value, clear_secret: false })}
                    placeholder={provider.configured ? 'Configured. Leave blank to keep existing secret.' : 'Paste provider secret'}
                    type="password"
                    autoComplete="new-password"
                  />
                </label>

                <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  <input
                    type="checkbox"
                    checked={Boolean(form.clear_secret)}
                    onChange={(event) => updateProvider(providerId, { clear_secret: event.target.checked, secret: '' })}
                  />
                  Clear stored secret
                </label>

                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                    Timeout seconds
                    <input
                      className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                      value={form.timeout_seconds}
                      onChange={(event) => updateProvider(providerId, { timeout_seconds: Number(event.target.value || 0) })}
                      type="number"
                      min="1"
                    />
                  </label>
                  <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                    Cost
                    <input
                      className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                      value={form.cost}
                      onChange={(event) => updateProvider(providerId, { cost: Number(event.target.value || 0) })}
                      type="number"
                      min="0"
                      step="0.000001"
                    />
                  </label>
                </div>

                {providerId === 'jina_reader' ? (
                  <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                    Max pages per search
                    <input
                      className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                      value={form.max_pages || 2}
                      onChange={(event) => updateProvider(providerId, { max_pages: Number(event.target.value || 1) })}
                      type="number"
                      min="1"
                      max="5"
                    />
                  </label>
                ) : null}
              </div>
            </BackofficeSectionPanel>
          );
        })}
      </div>

      <BackofficeSectionPanel>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
            Saving updates Cloud runtime configuration only. Existing WordPress sites continue to call Cloud without seeing provider credentials.
          </p>
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="inline-flex h-11 items-center justify-center rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? 'Saving...' : 'Save provider settings'}
          </button>
        </div>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function WebSearchAdminPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <WebSearchAdminContent />
    </Suspense>
  );
}
