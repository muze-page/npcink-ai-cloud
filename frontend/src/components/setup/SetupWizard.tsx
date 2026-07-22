'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LocaleSwitcher } from '@/components/ui/LocaleSwitcher';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { ApiError } from '@/lib/errors';
import { generateIdempotencyKey } from '@/lib/idempotency';
import type {
  SetupDatabaseInput,
  SetupDatabaseTestData,
  SetupInstallData,
  SetupSessionData,
  SetupStateData,
} from '@/lib/setup';
import { cn } from '@/lib/utils';

type WizardStep = 1 | 2 | 3 | 4;
type RequestState = 'idle' | 'loading' | 'success' | 'error';

const setupClient = createApiClient({
  baseUrl: '/api/setup',
  idempotencyPrefix: 'cloud_first_install',
});

const EMPTY_DATABASE: SetupDatabaseInput = {
  host: '',
  port: 5432,
  database: '',
  username: '',
  password: '',
  ssl_mode: 'verify-full',
  ca_pem: '',
};

function setupErrorTranslationKey(errorCode: string): string {
  const keys: Record<string, string> = {
    'setup.session_required': 'setup.error_session_required',
    'setup.code_invalid': 'setup.error_code_invalid',
    'setup.rate_limited': 'setup.error_rate_limited',
    'setup.installation_in_progress': 'setup.error_installation_in_progress',
    'setup.database_unreachable': 'setup.error_database_unreachable',
    'setup.database_tls_required': 'setup.error_database_tls_required',
    'setup.database_version_unsupported': 'setup.error_database_version',
    'setup.database_not_empty': 'setup.error_database_not_empty',
    'setup.database_permissions_insufficient': 'setup.error_database_permissions',
    'setup.migration_failed': 'setup.error_migration_failed',
    'setup.config_write_failed': 'setup.error_config_write_failed',
    'setup.already_complete': 'setup.error_already_complete',
    'setup.state_unavailable': 'setup.error_state_unavailable',
    'proxy.setup_unreachable': 'setup.error_state_unavailable',
    'setup.cloud_name_required': 'setup.error_cloud_name_required',
    'setup.public_base_url_invalid': 'setup.error_public_url_invalid',
    'setup.public_base_url_mismatch': 'setup.error_public_url_invalid',
    'setup.public_origin_unavailable': 'setup.error_state_unavailable',
  };
  return keys[errorCode] || 'setup.error_generic';
}

function normalizePublicBaseUrl(value: string): string | null {
  try {
    const parsed = new URL(value.trim());
    if (
      parsed.protocol !== 'https:' ||
      parsed.username ||
      parsed.password ||
      parsed.pathname !== '/' ||
      parsed.search ||
      parsed.hash
    ) {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}

function StatusDot({ state }: { state: 'pending' | 'ok' | 'error' }) {
  return (
    <span
      className={cn(
        'h-2.5 w-2.5 flex-none rounded-full',
        state === 'pending' && 'bg-amber-400',
        state === 'ok' && 'bg-emerald-500',
        state === 'error' && 'bg-red-500'
      )}
      aria-hidden="true"
    />
  );
}

function SetupErrorNotice({ error }: { error: ApiError | null }) {
  const { t } = useLocale();
  if (!error) {
    return null;
  }

  return (
    <div
      className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
      role="alert"
      data-setup-error={error.errorCode}
    >
      <p className="font-medium">{t(setupErrorTranslationKey(error.errorCode))}</p>
      <details className="mt-2 text-xs text-red-700/80 dark:text-red-300/80">
        <summary className="cursor-pointer font-medium">{t('setup.support_information')}</summary>
        <p className="mt-1 break-all font-mono">{t('setup.error_code')}: {error.errorCode}</p>
        {error.traceId ? <p className="mt-1 break-all font-mono">Trace: {error.traceId}</p> : null}
      </details>
    </div>
  );
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  return new ApiError({
    statusCode: 0,
    errorCode: 'client.network_error',
    message: 'setup request failed',
  });
}

export function SetupWizard() {
  const router = useRouter();
  const { t } = useLocale();
  const [step, setStep] = useState<WizardStep>(1);
  const [stateRequest, setStateRequest] = useState<RequestState>('loading');
  const [installationState, setInstallationState] = useState<SetupStateData | null>(null);
  const [setupCode, setSetupCode] = useState('');
  const [cloudName, setCloudName] = useState('');
  const [publicBaseUrl, setPublicBaseUrl] = useState('');
  const [database, setDatabase] = useState<SetupDatabaseInput>(EMPTY_DATABASE);
  const [databaseTest, setDatabaseTest] = useState<SetupDatabaseTestData | null>(null);
  const [requestState, setRequestState] = useState<RequestState>('idle');
  const [error, setError] = useState<ApiError | null>(null);
  const [adminKey, setAdminKey] = useState('');
  const [adminKeyCopied, setAdminKeyCopied] = useState(false);
  const [adminKeySaved, setAdminKeySaved] = useState(false);
  const [isSetupCodeVisible, setIsSetupCodeVisible] = useState(false);
  const [isDatabasePasswordVisible, setIsDatabasePasswordVisible] = useState(false);
  const installIdempotencyKey = useRef(generateIdempotencyKey('cloud_first_install'));
  const installationComplete =
    Boolean(adminKey) || installationState?.installation_state === 'complete';

  const stepLabels = useMemo(
    () => [
      t('setup.step_unlock'),
      t('setup.step_cloud'),
      t('setup.step_database'),
      t('setup.step_initialize'),
    ],
    [t]
  );

  const loadState = useCallback(async () => {
    setStateRequest('loading');
    try {
      const response = await setupClient.request<SetupStateData>('/state');
      setInstallationState(response.data);
      setStateRequest('success');
      if (response.data.installation_state === 'complete') {
        router.replace('/admin/login');
      }
    } catch (caught) {
      setError(toApiError(caught));
      setStateRequest('error');
    }
  }, [router]);

  useEffect(() => {
    void loadState();
  }, [loadState]);

  useEffect(() => {
    if (!publicBaseUrl && typeof window !== 'undefined' && window.location.protocol === 'https:') {
      setPublicBaseUrl(window.location.origin);
    }
  }, [publicBaseUrl]);

  useEffect(() => {
    if (installationState?.installation_state !== 'initializing') {
      return;
    }
    const timer = window.setInterval(() => void loadState(), 3000);
    return () => window.clearInterval(timer);
  }, [installationState?.installation_state, loadState]);

  const clearRequestFeedback = () => {
    setError(null);
    setRequestState('idle');
  };

  const exchangeSetupCode = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!setupCode.trim()) {
      setError(new ApiError({
        statusCode: 400,
        errorCode: 'setup.code_invalid',
        message: 'setup code is required',
      }));
      return;
    }
    setRequestState('loading');
    setError(null);
    try {
      const response = await setupClient.request<SetupSessionData>('/session', {
        method: 'POST',
        body: { setup_code: setupCode },
      });
      setSetupCode('');
      setInstallationState({
        installation_state: response.data.installation_state,
        setup_revision: response.data.setup_revision,
        retry_allowed: response.data.retry_allowed,
      });
      setRequestState('success');
      setStep(2);
    } catch (caught) {
      setRequestState('error');
      setError(toApiError(caught));
    }
  };

  const continueCloudDetails = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedUrl = normalizePublicBaseUrl(publicBaseUrl);
    if (!cloudName.trim() || !normalizedUrl) {
      setError(new ApiError({
        statusCode: 400,
        errorCode: !cloudName.trim() ? 'setup.cloud_name_required' : 'setup.public_base_url_invalid',
        message: 'Cloud details are invalid',
      }));
      return;
    }
    setCloudName(cloudName.trim());
    setPublicBaseUrl(normalizedUrl);
    clearRequestFeedback();
    setStep(3);
  };

  const updateDatabase = <Key extends keyof SetupDatabaseInput>(
    key: Key,
    value: SetupDatabaseInput[Key]
  ) => {
    setDatabase((current) => ({ ...current, [key]: value }));
    setDatabaseTest(null);
    clearRequestFeedback();
  };

  const testDatabase = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRequestState('loading');
    setError(null);
    setDatabaseTest(null);
    try {
      const response = await setupClient.request<SetupDatabaseTestData>('/database/test', {
        method: 'POST',
        body: database,
      });
      setDatabaseTest(response.data);
      setRequestState('success');
    } catch (caught) {
      setRequestState('error');
      setError(toApiError(caught));
    }
  };

  const installCloud = async () => {
    setRequestState('loading');
    setError(null);
    try {
      const response = await setupClient.request<SetupInstallData>('/install', {
        method: 'POST',
        body: {
          cloud_name: cloudName,
          public_base_url: publicBaseUrl,
          database,
        },
        idempotencyKey: installIdempotencyKey.current,
      });
      setAdminKey(response.data.admin_key);
      setDatabase(EMPTY_DATABASE);
      setRequestState('success');
    } catch (caught) {
      setRequestState('error');
      setError(toApiError(caught));
    }
  };

  const copyAdminKey = async () => {
    try {
      await navigator.clipboard.writeText(adminKey);
      setAdminKeyCopied(true);
      window.setTimeout(() => setAdminKeyCopied(false), 2000);
    } catch {
      setAdminKeyCopied(false);
    }
  };

  if (stateRequest === 'loading' && !installationState) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4" aria-live="polite">
        <div className="flex items-center gap-3 text-sm text-slate-600 dark:text-slate-300">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" aria-hidden="true" />
          {t('setup.checking_state')}
        </div>
      </main>
    );
  }

  if (stateRequest === 'error' && !installationState) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-xl items-center px-4 py-12">
        <section className="w-full rounded-2xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-950">
          <h1 className="text-xl font-semibold text-slate-950 dark:text-white">{t('setup.state_unavailable_title')}</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{t('setup.error_state_unavailable')}</p>
          <button type="button" className="btn btn-primary mt-5" onClick={() => void loadState()}>
            {t('common.retry')}
          </button>
        </section>
      </main>
    );
  }

  if (installationState?.installation_state === 'initializing' && !adminKey) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-xl items-center px-4 py-12">
        <section className="w-full rounded-2xl border border-amber-200 bg-white p-6 dark:border-amber-900 dark:bg-slate-950" aria-live="polite">
          <div className="flex items-center gap-3">
            <StatusDot state="pending" />
            <h1 className="text-xl font-semibold text-slate-950 dark:text-white">{t('setup.initializing_title')}</h1>
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">{t('setup.initializing_desc')}</p>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-50/70 px-4 py-6 dark:bg-slate-950 sm:px-6 sm:py-10">
      <div className="mx-auto w-full max-w-6xl">
        <header className="flex items-center justify-between border-b border-slate-200 pb-5 dark:border-slate-800">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-700 dark:text-blue-300">Npcink AI Cloud</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-white">{t('setup.title')}</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">{t('setup.description')}</p>
          </div>
          <div className="flex items-center gap-2">
            <LocaleSwitcher />
            <ThemeToggle />
          </div>
        </header>

        <div className="mt-6 grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
          <aside className="lg:sticky lg:top-6 lg:self-start">
            <ol className="space-y-1" aria-label={t('setup.progress_label')}>
              {stepLabels.map((label, index) => {
                const itemStep = (index + 1) as WizardStep;
                const active = step === itemStep;
                const complete = step > itemStep || Boolean(adminKey);
                return (
                  <li
                    key={label}
                    className={cn(
                      'flex items-center gap-3 rounded-xl px-3 py-3 text-sm',
                      active && !adminKey
                        ? 'bg-blue-50 font-semibold text-blue-800 dark:bg-blue-950/45 dark:text-blue-200'
                        : 'text-slate-500 dark:text-slate-400'
                    )}
                    aria-current={active && !adminKey ? 'step' : undefined}
                  >
                    <span
                      className={cn(
                        'inline-flex h-7 w-7 flex-none items-center justify-center rounded-full border text-xs font-semibold',
                        complete
                          ? 'border-emerald-500 bg-emerald-500 text-white'
                          : active
                            ? 'border-blue-600 bg-blue-600 text-white'
                            : 'border-slate-300 bg-white dark:border-slate-700 dark:bg-slate-900'
                      )}
                      aria-hidden="true"
                    >
                      {complete ? '✓' : itemStep}
                    </span>
                    {label}
                  </li>
                );
              })}
            </ol>
            <div className="mt-5 border-t border-slate-200 px-3 pt-5 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">
              <p
                className="flex items-center gap-2 font-medium text-slate-700 dark:text-slate-200"
                data-setup-installation-state={installationComplete ? 'complete' : 'pending'}
                aria-live="polite"
              >
                <StatusDot state={installationComplete ? 'ok' : 'pending'} />
                {installationComplete
                  ? t('setup.install_complete_status')
                  : t('setup.status_pending')}
              </p>
              <p className="mt-2">{t('setup.boundary_note')}</p>
            </div>
          </aside>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_18px_50px_rgba(15,23,42,0.06)] dark:border-slate-800 dark:bg-slate-950 sm:p-8">
            {adminKey ? (
              <div aria-live="polite">
                <div className="flex items-center gap-3">
                  <StatusDot state="ok" />
                  <p className="text-sm font-semibold text-emerald-700 dark:text-emerald-300">{t('setup.install_complete_status')}</p>
                </div>
                <h2 className="mt-4 text-2xl font-semibold text-slate-950 dark:text-white">{t('setup.admin_key_title')}</h2>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{t('setup.admin_key_desc')}</p>
                <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/30">
                  <label htmlFor="generated_admin_key" className="text-sm font-semibold text-amber-950 dark:text-amber-100">
                    {t('setup.admin_key_label')}
                  </label>
                  <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                    <input
                      id="generated_admin_key"
                      readOnly
                      value={adminKey}
                      className="input min-w-0 flex-1 font-mono"
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <button type="button" className="btn btn-secondary sm:flex-none" onClick={() => void copyAdminKey()}>
                      {adminKeyCopied ? t('common.copied') : t('common.copy')}
                    </button>
                  </div>
                  <p className="mt-3 text-xs leading-5 text-amber-800 dark:text-amber-200">{t('setup.admin_key_warning')}</p>
                </div>
                <label className="mt-6 flex items-start gap-3 text-sm text-slate-700 dark:text-slate-200">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-700"
                    checked={adminKeySaved}
                    onChange={(event) => setAdminKeySaved(event.target.checked)}
                  />
                  <span>{t('setup.admin_key_saved_confirm')}</span>
                </label>
                <button
                  type="button"
                  className="btn btn-primary mt-6 w-full sm:w-auto"
                  disabled={!adminKeySaved}
                  onClick={() => window.location.assign('/admin/login')}
                >
                  {t('setup.open_admin')}
                </button>
              </div>
            ) : null}

            {!adminKey && step === 1 ? (
              <form onSubmit={exchangeSetupCode} className="space-y-6">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700 dark:text-blue-300">{t('setup.step_count', { current: '1', total: '4' })}</p>
                  <h2 className="mt-3 text-2xl font-semibold text-slate-950 dark:text-white">{t('setup.unlock_title')}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{t('setup.unlock_desc')}</p>
                </div>
                <SetupErrorNotice error={error} />
                <div>
                  <label htmlFor="setup_code" className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">{t('setup.code_label')}</label>
                  <div className="relative">
                    <input
                      id="setup_code"
                      type={isSetupCodeVisible ? 'text' : 'password'}
                      autoComplete="one-time-code"
                      autoFocus
                      required
                      value={setupCode}
                      onChange={(event) => {
                        setSetupCode(event.target.value);
                        clearRequestFeedback();
                      }}
                      placeholder="nca_setup_…"
                      className="input h-12 pr-20 font-mono"
                    />
                    <button type="button" className="absolute inset-y-1.5 right-1.5 rounded-lg px-3 text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800" onClick={() => setIsSetupCodeVisible((value) => !value)}>
                      {isSetupCodeVisible ? t('common.hide') : t('setup.show_secret')}
                    </button>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{t('setup.code_help')}</p>
                </div>
                <button type="submit" className="btn btn-primary w-full sm:w-auto" disabled={requestState === 'loading'}>
                  {requestState === 'loading' ? t('setup.verifying_code') : t('setup.verify_code')}
                </button>
              </form>
            ) : null}

            {!adminKey && step === 2 ? (
              <form onSubmit={continueCloudDetails} className="space-y-6">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700 dark:text-blue-300">{t('setup.step_count', { current: '2', total: '4' })}</p>
                  <h2 className="mt-3 text-2xl font-semibold text-slate-950 dark:text-white">{t('setup.cloud_title')}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{t('setup.cloud_desc')}</p>
                </div>
                <SetupErrorNotice error={error} />
                <div className="grid gap-5 sm:grid-cols-2">
                  <div>
                    <label htmlFor="cloud_name" className="mb-2 block text-sm font-medium">{t('setup.cloud_name_label')}</label>
                    <input id="cloud_name" className="input" required maxLength={100} value={cloudName} onChange={(event) => { setCloudName(event.target.value); clearRequestFeedback(); }} placeholder={t('setup.cloud_name_placeholder')} />
                  </div>
                  <div>
                    <label htmlFor="public_base_url" className="mb-2 block text-sm font-medium">{t('setup.public_url_label')}</label>
                    <input id="public_base_url" className="input font-mono" required inputMode="url" value={publicBaseUrl} onChange={(event) => { setPublicBaseUrl(event.target.value); clearRequestFeedback(); }} placeholder="https://cloud.example.com" />
                  </div>
                </div>
                <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{t('setup.public_url_help')}</p>
                <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                  <button type="button" className="btn btn-secondary" onClick={() => setStep(1)}>{t('common.back')}</button>
                  <button type="submit" className="btn btn-primary">{t('common.next')}</button>
                </div>
              </form>
            ) : null}

            {!adminKey && step === 3 ? (
              <form onSubmit={testDatabase} className="space-y-6">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700 dark:text-blue-300">{t('setup.step_count', { current: '3', total: '4' })}</p>
                  <h2 className="mt-3 text-2xl font-semibold text-slate-950 dark:text-white">{t('setup.database_title')}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{t('setup.database_desc')}</p>
                </div>
                <SetupErrorNotice error={error} />
                <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_8rem]">
                  <div>
                    <label htmlFor="database_host" className="mb-2 block text-sm font-medium">{t('setup.database_host')}</label>
                    <input id="database_host" className="input font-mono" required autoComplete="off" value={database.host} onChange={(event) => updateDatabase('host', event.target.value)} placeholder="pgm-….pg.rds.aliyuncs.com" />
                  </div>
                  <div>
                    <label htmlFor="database_port" className="mb-2 block text-sm font-medium">{t('setup.database_port')}</label>
                    <input id="database_port" className="input font-mono" required type="number" min={1} max={65535} value={database.port} onChange={(event) => updateDatabase('port', Number(event.target.value))} />
                  </div>
                </div>
                <div className="grid gap-5 sm:grid-cols-2">
                  <div>
                    <label htmlFor="database_name" className="mb-2 block text-sm font-medium">{t('setup.database_name')}</label>
                    <input id="database_name" className="input font-mono" required autoComplete="off" value={database.database} onChange={(event) => updateDatabase('database', event.target.value)} />
                  </div>
                  <div>
                    <label htmlFor="database_username" className="mb-2 block text-sm font-medium">{t('setup.database_username')}</label>
                    <input id="database_username" className="input font-mono" required autoComplete="off" data-1p-ignore data-lpignore="true" value={database.username} onChange={(event) => updateDatabase('username', event.target.value)} />
                  </div>
                </div>
                <div>
                  <label htmlFor="database_password" className="mb-2 block text-sm font-medium">{t('setup.database_password')}</label>
                  <div className="relative">
                    <input id="database_password" className="input pr-20 font-mono" required type={isDatabasePasswordVisible ? 'text' : 'password'} autoComplete="off" data-1p-ignore data-lpignore="true" value={database.password} onChange={(event) => updateDatabase('password', event.target.value)} />
                    <button type="button" className="absolute inset-y-1.5 right-1.5 rounded-lg px-3 text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800" onClick={() => setIsDatabasePasswordVisible((value) => !value)}>
                      {isDatabasePasswordVisible ? t('common.hide') : t('setup.show_secret')}
                    </button>
                  </div>
                </div>
                <div>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <label htmlFor="database_ca" className="text-sm font-medium">{t('setup.database_ca')}</label>
                    <label className="cursor-pointer text-xs font-semibold text-blue-700 hover:underline dark:text-blue-300">
                      {t('setup.database_ca_upload')}
                      <input
                        type="file"
                        accept=".pem,.crt,.cer,text/plain,application/x-pem-file"
                        className="sr-only"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) {
                            void file.text().then((value) => updateDatabase('ca_pem', value));
                          }
                          event.target.value = '';
                        }}
                      />
                    </label>
                  </div>
                  <textarea id="database_ca" className="input min-h-36 resize-y font-mono text-xs" required spellCheck={false} value={database.ca_pem} onChange={(event) => updateDatabase('ca_pem', event.target.value)} placeholder="-----BEGIN CERTIFICATE-----" />
                  <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{t('setup.database_tls_help')}</p>
                </div>

                {databaseTest ? (
                  <div className="border-y border-slate-200 py-4 dark:border-slate-800" aria-live="polite">
                    <p className="flex items-center gap-2 text-sm font-semibold text-emerald-700 dark:text-emerald-300"><StatusDot state="ok" />{t('setup.database_test_passed')}</p>
                    <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                      <div className="flex justify-between gap-4"><dt className="text-slate-500">{t('setup.database_version_fact')}</dt><dd className="font-mono text-slate-900 dark:text-white">{databaseTest.postgres_major_version ?? 18}</dd></div>
                      <div className="flex justify-between gap-4"><dt className="text-slate-500">TLS</dt><dd className="font-mono text-slate-900 dark:text-white">{databaseTest.ssl_mode || 'verify-full'}</dd></div>
                      <div className="flex justify-between gap-4"><dt className="text-slate-500">{t('setup.database_empty_fact')}</dt><dd className="text-slate-900 dark:text-white">{databaseTest.database_empty ? t('common.yes') : t('common.no')}</dd></div>
                      <div className="flex justify-between gap-4"><dt className="text-slate-500">{t('setup.database_latency_fact')}</dt><dd className="font-mono text-slate-900 dark:text-white">{databaseTest.latency_ms ?? '—'} ms</dd></div>
                      <div className="flex justify-between gap-4"><dt className="text-slate-500">Alembic</dt><dd className="font-mono text-slate-900 dark:text-white">{databaseTest.alembic_state || 'empty'}</dd></div>
                      <div className="flex justify-between gap-4"><dt className="text-slate-500">max_connections</dt><dd className="font-mono text-slate-900 dark:text-white">{databaseTest.max_connections ?? '—'}</dd></div>
                    </dl>
                  </div>
                ) : null}

                <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
                  <button type="button" className="btn btn-secondary" onClick={() => setStep(2)}>{t('common.back')}</button>
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <button type="submit" className="btn btn-secondary" disabled={requestState === 'loading'}>{requestState === 'loading' ? t('setup.testing_database') : t('setup.test_database')}</button>
                    <button type="button" className="btn btn-primary" disabled={!databaseTest || requestState === 'loading'} onClick={() => { clearRequestFeedback(); setStep(4); }}>{t('common.next')}</button>
                  </div>
                </div>
              </form>
            ) : null}

            {!adminKey && step === 4 ? (
              <div className="space-y-6">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700 dark:text-blue-300">{t('setup.step_count', { current: '4', total: '4' })}</p>
                  <h2 className="mt-3 text-2xl font-semibold text-slate-950 dark:text-white">{t('setup.initialize_title')}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{t('setup.initialize_desc')}</p>
                </div>
                <SetupErrorNotice error={error} />
                <dl className="divide-y divide-slate-200 border-y border-slate-200 text-sm dark:divide-slate-800 dark:border-slate-800">
                  <div className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between"><dt className="text-slate-500">{t('setup.cloud_name_label')}</dt><dd className="font-medium text-slate-900 dark:text-white">{cloudName}</dd></div>
                  <div className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between"><dt className="text-slate-500">{t('setup.public_url_label')}</dt><dd className="break-all font-mono text-slate-900 dark:text-white">{publicBaseUrl}</dd></div>
                  <div className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between"><dt className="text-slate-500">{t('setup.database_target')}</dt><dd className="break-all font-mono text-slate-900 dark:text-white">{database.host}:{database.port}/{database.database}</dd></div>
                  <div className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between"><dt className="text-slate-500">TLS</dt><dd className="font-mono text-slate-900 dark:text-white">verify-full</dd></div>
                </dl>
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                  {t('setup.initialize_warning')}
                </div>
                <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
                  <button type="button" className="btn btn-secondary" disabled={requestState === 'loading'} onClick={() => setStep(3)}>{t('common.back')}</button>
                  <button type="button" className="btn btn-primary" disabled={requestState === 'loading'} onClick={() => void installCloud()}>{requestState === 'loading' ? t('setup.initializing_action') : t('setup.initialize_action')}</button>
                </div>
              </div>
            ) : null}
          </section>
        </div>
      </div>
    </main>
  );
}
