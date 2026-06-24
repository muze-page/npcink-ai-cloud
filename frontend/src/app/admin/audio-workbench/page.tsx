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

type AudioIntent = 'article_narration' | 'article_audio_summary';

type AudioJob = {
  run_id: string;
  status: string;
  trace_id: string;
  provider_id: string;
  model_id: string;
  instance_id: string;
  profile_id: string;
  error_code?: string;
  error_message?: string;
  script?: {
    source: string;
    intent?: string;
    text: string;
    characters: number;
    generation?: {
      mode?: string;
      ability_name?: string;
      contract_version?: string;
      run_id?: string;
      provider_id?: string;
      model_id?: string;
      profile_id?: string;
      status?: string;
    };
  };
  result_ready: boolean;
  result?: {
    artifact_type?: string;
    direct_wordpress_write?: boolean;
    usage?: {
      characters?: number;
      duration_ms?: number;
      trace_id?: string;
    };
    audios?: Array<{
      url?: string;
      b64_json?: string;
      mime_type?: string;
      duration_seconds?: number;
      transcript?: string;
    }>;
  };
  boundary?: {
    direct_wordpress_write?: boolean;
    final_writes?: string;
  };
};

type RuntimeProfile = {
  profile_id: string;
  status: string;
  selected_provider_id: string;
  selected_model_id: string;
  used_by?: string[];
};

type AiResources = {
  runtime_profiles: RuntimeProfile[];
};

const INTENT_OPTIONS: Array<{
  id: AudioIntent;
  label: string;
  help: string;
}> = [
  {
    id: 'article_narration',
    label: 'Article narration',
    help: 'Read the article text as a narration script.',
  },
  {
    id: 'article_audio_summary',
    label: 'Audio summary',
    help: 'Create a short listening script before generating audio.',
  },
];

function audioSource(job: AudioJob | null): string {
  const audio = job?.result?.audios?.[0];
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

function AudioWorkbenchContent() {
  const [intent, setIntent] = useState<AudioIntent>('article_narration');
  const [siteId, setSiteId] = useState('site_smoke');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [job, setJob] = useState<AudioJob | null>(null);
  const [resources, setResources] = useState<AiResources | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [resourceError, setResourceError] = useState('');

  const terminal = job ? ['succeeded', 'failed', 'canceled'].includes(job.status) : true;
  const source = audioSource(job);
  const audio = job?.result?.audios?.[0];
  const textProfile = resources?.runtime_profiles?.find((profile) => profile.profile_id === 'text.ai');
  const audioProfile = resources?.runtime_profiles?.find((profile) => profile.profile_id === 'audio.narration.default');
  const summaryProfile = resources?.runtime_profiles?.find((profile) => profile.profile_id === 'audio.summary.default');

  useEffect(() => {
    if (!job?.run_id || terminal) {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/admin/audio-jobs/${encodeURIComponent(job.run_id)}`, {
          credentials: 'include',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(resolveUiErrorMessage(payload, 'Failed to load audio job.'));
        }
        if (!cancelled) {
          setJob(payload.data as AudioJob);
        }
      } catch (pollError) {
        if (!cancelled) {
          setError(pollError instanceof Error ? pollError.message : 'Failed to load audio job.');
        }
      }
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.run_id, terminal]);

  useEffect(() => {
    let mounted = true;
    async function loadResources() {
      setResourceError('');
      try {
        const response = await fetch('/api/admin/ai-resources', { credentials: 'include' });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(resolveUiErrorMessage(payload, 'Failed to load AI resources.'));
        }
        if (mounted) {
          setResources(payload.data as AiResources);
        }
      } catch (loadError) {
        if (mounted) {
          setResourceError(loadError instanceof Error ? loadError.message : 'Failed to load AI resources.');
        }
      }
    }
    loadResources();
    return () => {
      mounted = false;
    };
  }, []);

  const metrics = useMemo(() => {
    return [
      {
        label: 'Mode',
        value: intent === 'article_narration' ? 'Narration' : 'Summary',
        detail: intent === 'article_narration' ? 'Full article script' : 'Short listening script',
      },
      {
        label: 'Site',
        value: siteId || 'not set',
        detail: 'Provisioned Cloud site used for runtime quota and audit.',
      },
      {
        label: 'Job',
        value: job?.status || 'not created',
        detail: job?.run_id || 'Create a job to start generation.',
      },
      {
        label: 'Write posture',
        value: 'Candidate only',
        detail: 'No direct WordPress write.',
      },
      {
        label: 'Resource profile',
        value: intent === 'article_audio_summary' ? (summaryProfile?.status || 'checking') : (audioProfile?.status || 'checking'),
        detail: intent === 'article_audio_summary' ? 'text.ai + audio.narration.default' : 'audio.narration.default',
      },
    ];
  }, [audioProfile?.status, intent, job?.run_id, job?.status, siteId, summaryProfile?.status]);

  async function createJob() {
    setCreating(true);
    setError('');
    setMessage('');
    setJob(null);
    try {
      const response = await fetch('/api/admin/audio-jobs', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          site_id: siteId,
          intent,
          title,
          body,
          format: 'mp3',
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload, 'Failed to create audio job.'));
      }
      setJob(payload.data as AudioJob);
      setMessage('Audio job created. Status will update automatically.');
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : 'Failed to create audio job.');
    } finally {
      setCreating(false);
    }
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow="Audio generation"
        title="Article audio workbench"
        description="Create article narration or long-form audio summary jobs through the Cloud runtime."
        aside={(
          <BackofficeStatusBadge
            label={job?.status || 'Ready'}
            status={job?.status === 'failed' ? 'error' : job?.status === 'succeeded' ? 'success' : 'info'}
          />
        )}
        summary={<BackofficeMetricStrip items={metrics} columnsClassName="xl:grid-cols-5" />}
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
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,0.75fr)]">
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/50">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-slate-950 dark:text-white">Runtime resources</h2>
                  <div className="mt-2 grid gap-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
                    <div>Text script: {textProfile ? `${textProfile.selected_provider_id} / ${textProfile.selected_model_id} (${textProfile.status})` : 'checking'}</div>
                    <div>Audio generation: {audioProfile ? `${audioProfile.selected_provider_id} / ${audioProfile.selected_model_id} (${audioProfile.status})` : 'checking'}</div>
                  </div>
                  {resourceError ? (
                    <div className="mt-2 text-xs text-amber-700 dark:text-amber-300">{resourceError}</div>
                  ) : null}
                </div>
                <Link href="/admin/ai-resources" className="btn btn-secondary shrink-0">
                  AI resources
                </Link>
              </div>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              {INTENT_OPTIONS.map((option) => {
                const selected = intent === option.id;
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setIntent(option.id)}
                    className={`rounded-lg border px-4 py-3 text-left transition ${
                      selected
                        ? 'border-blue-500 bg-blue-50 text-blue-950 dark:border-blue-400 dark:bg-blue-950/35 dark:text-blue-100'
                        : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-slate-700'
                    }`}
                  >
                    <div className="text-sm font-semibold">{option.label}</div>
                    <div className="mt-1 text-xs leading-5 opacity-80">{option.help}</div>
                  </button>
                );
              })}
            </div>

            <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              Site ID
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={siteId}
                onChange={(event) => setSiteId(event.target.value)}
              />
            </label>

            <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              Article title
              <input
                className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Optional title"
              />
            </label>

            <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              Article text
              <textarea
                className="min-h-64 rounded-lg border border-slate-300 bg-white px-3 py-3 text-sm leading-6 text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                value={body}
                onChange={(event) => setBody(event.target.value)}
                placeholder="Paste the article body here."
              />
            </label>

            <button
              type="button"
              onClick={createJob}
              disabled={creating || !body.trim() || !siteId.trim()}
              className="inline-flex h-11 items-center justify-center rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {creating ? 'Creating job...' : 'Create audio job'}
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">Result</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                Polling reads the Cloud run result. Audio remains a reviewable artifact.
              </p>
            </div>

            {job ? (
              <div className="space-y-4">
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-700 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-200">
                  <div className="font-semibold text-slate-950 dark:text-white">Job detail</div>
                  <div className="mt-2">Run: {job.run_id}</div>
                  <div>Status: {job.status}</div>
                  <div>Provider: {job.provider_id || 'pending'}</div>
                  <div>Model: {job.model_id || 'pending'}</div>
                  <div>Duration: {audio?.duration_seconds || 0}s</div>
                  <div>Trace: {job.result?.usage?.trace_id || job.trace_id || 'pending'}</div>
                </div>

                {job.script?.text ? (
                  <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/60">
                    <div className="text-sm font-semibold text-slate-950 dark:text-white">Generated script</div>
                    <div className="mt-2 grid gap-1 text-xs text-slate-500 dark:text-slate-400">
                      <div>Source: {job.script.source || 'unknown'}</div>
                      {job.script.generation?.run_id ? (
                        <div>Script run: {job.script.generation.run_id}</div>
                      ) : null}
                      {job.script.generation?.provider_id || job.script.generation?.model_id ? (
                        <div>
                          Script model: {job.script.generation.provider_id || 'provider'} /{' '}
                          {job.script.generation.model_id || 'model'}
                        </div>
                      ) : null}
                    </div>
                    <p className="mt-2 max-h-44 overflow-auto text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {job.script.text}
                    </p>
                  </div>
                ) : null}

                {source ? (
                  <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/60">
                    <div className="text-sm font-semibold text-slate-950 dark:text-white">Playback</div>
                    <audio className="mt-3 w-full" controls src={source}>
                      Your browser does not support audio playback.
                    </audio>
                    {audio?.url ? (
                      <a
                        href={audio.url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-3 inline-flex text-sm font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-300"
                      >
                        Open audio URL
                      </a>
                    ) : null}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300">
                    Waiting for a playable audio artifact.
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-300">
                Create a job to see status, script, and playback.
              </div>
            )}
          </div>
        </div>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function AudioWorkbenchPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AudioWorkbenchContent />
    </Suspense>
  );
}
