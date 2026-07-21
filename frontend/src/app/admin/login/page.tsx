'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useLocale } from '@/contexts/LocaleContext';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { createApiClient } from '@/lib/api-client';

const adminLoginSessionClient = createApiClient({ idempotencyPrefix: 'admin_login_session' });

function resolveAdminLoginRedirect(value: string | null): string {
  const redirect = String(value || '').trim();
  if (
    redirect === '/admin' ||
    redirect.startsWith('/admin/') ||
    redirect.startsWith('/admin?') ||
    redirect.startsWith('/admin#')
  ) {
    return redirect;
  }
  return '/admin';
}

function AdminLoginPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { t } = useLocale();
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [isTokenVisible, setIsTokenVisible] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const error = searchParams.get('error');
  const detail = searchParams.get('detail');
  const traceId = searchParams.get('trace_id');
  const redirectTo = resolveAdminLoginRedirect(searchParams.get('redirect'));
  const errorMessage = (() => {
    switch (error) {
      case 'auth.admin_bootstrap_token_invalid':
        return t('admin.login_error_invalid');
      case 'auth.admin_bootstrap_token_required':
        return t('admin.login_error_required');
      case 'auth.admin_bootstrap_not_configured':
        return t('admin.login_error_not_configured');
      case 'auth.origin_not_allowed':
      case 'auth.browser_origin_not_allowed':
        return t('admin.login_error_origin');
      case 'auth.dev_entry_unreachable':
        return t('admin.login_error_unreachable');
      default:
        return detail || error || '';
    }
  })();

  useEffect(() => {
    let cancelled = false;
    void adminLoginSessionClient
      .request('/admin/session')
      .then(() => {
        if (cancelled) {
          return;
        }
        router.replace(redirectTo);
      })
      .catch(() => {
        if (!cancelled) {
          setIsCheckingSession(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [redirectTo, router]);

  if (isCheckingSession) {
    return <LoadingFallback />;
  }

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] w-full max-w-lg items-center px-4 py-8 sm:py-12">
      <section
        className="w-full rounded-2xl border border-slate-200/90 bg-white p-6 shadow-[0_20px_55px_rgba(37,69,125,0.10)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_20px_55px_rgba(2,6,23,0.38)] sm:p-8"
        aria-labelledby="admin-login-title"
      >
        <div className="mb-7">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700 dark:text-blue-300">
            {t('admin.login_eyebrow', {}, 'Internal operations')}
          </p>
          <h1 id="admin-login-title" className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 dark:text-white">
            {t('admin.login_title', {}, 'Sign in to admin')}
          </h1>
          <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t('admin.login_desc', {}, 'For platform operators only. Enter the current Cloud admin bootstrap token.')}
          </p>
        </div>

        <div className="space-y-5">
          {error ? (
            <div id="admin-login-error" role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
              <p className="font-medium">{errorMessage}</p>
              {error || traceId ? (
                <details className="mt-2 text-xs text-red-600/85 dark:text-red-300/85">
                  <summary className="cursor-pointer font-medium">
                    {t('portal.support_information', {}, 'Support information')}
                  </summary>
                  {error ? <p className="mt-1 break-all font-mono">{t('admin.login_error_code')}: {error}</p> : null}
                  {traceId ? <p className="mt-1 break-all font-mono">Trace: {traceId}</p> : null}
                </details>
              ) : null}
            </div>
          ) : null}

          <form action="/admin/auth/bootstrap" method="post" className="space-y-5" onSubmit={() => setIsSubmitting(true)}>
            <input type="hidden" name="redirect" value={redirectTo} />

            <div>
              <label
                htmlFor="token"
                className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200"
              >
                {t('admin.internal_auth_token')}
              </label>
              <div className="relative">
                <input
                  id="token"
                  name="token"
                  type={isTokenVisible ? 'text' : 'password'}
                  autoComplete="current-password"
                  autoFocus
                  required
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? 'admin-login-token-help admin-login-error' : 'admin-login-token-help'}
                  className="input h-12 rounded-xl pr-20 font-mono"
                  placeholder={t('admin.internal_auth_token_placeholder')}
                />
                <button
                  type="button"
                  className="absolute inset-y-1.5 right-1.5 rounded-lg px-3 text-xs font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500/40 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
                  aria-pressed={isTokenVisible}
                  onClick={() => setIsTokenVisible((current) => !current)}
                >
                  {isTokenVisible ? t('admin.login_hide_token') : t('admin.login_show_token')}
                </button>
              </div>
              <p id="admin-login-token-help" className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {t('admin.login_token_help')}
              </p>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 active:scale-[0.98] focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-wait disabled:opacity-70 dark:bg-blue-500 dark:text-slate-950 dark:hover:bg-blue-400 dark:focus:ring-offset-slate-950"
            >
              {isSubmitting ? t('admin.login_submitting') : t('admin.open_admin_with_internal_token')}
            </button>
          </form>

          <p className="border-t border-slate-200 pt-5 text-center text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
            {t('admin.login_portal_prompt')}{' '}
            <Link
              href="/portal"
              className="font-medium text-slate-700 underline-offset-4 hover:text-blue-700 hover:underline dark:text-slate-200 dark:hover:text-blue-300"
            >
              {t('admin.login_portal_link')}
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}

export default function AdminLoginPage() {
  return (
    <Suspense fallback={null}>
      <AdminLoginPageContent />
    </Suspense>
  );
}
