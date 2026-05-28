'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  BackofficeLayer,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';

function AdminLoginPageContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const error = searchParams.get('error');
  const redirectTo = searchParams.get('redirect') || '/admin';

  return (
    <div className="mx-auto min-h-[74vh] w-full max-w-6xl px-4 py-12">
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow={t('admin.login_eyebrow', {}, 'Admin access')}
          title={t('admin.login_title', {}, 'Bootstrap an internal admin session')}
          description={t(
            'admin.login_desc',
            {},
            'Use the current Cloud admin bootstrap token to open the operator workspace. This path is for platform operations only.'
          )}
          summary={(
            <div className="grid gap-3 text-sm text-slate-600 dark:text-slate-300 lg:grid-cols-2">
              <BackofficeStackCard>
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.22em] text-blue-600 dark:text-blue-300">
                  {t('admin.login_path_label', {}, 'Path')}
                </p>
                <p className="mt-2 font-medium text-slate-900 dark:text-slate-100">POST /admin/auth/bootstrap</p>
                <p className="mt-1">{t('admin.login_namespace_desc')}</p>
              </BackofficeStackCard>
              <BackofficeStackCard>
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                  {t('admin.login_scope_label', {}, 'Scope')}
                </p>
                <p className="mt-2">{t('admin.internal_token_login_note')}</p>
              </BackofficeStackCard>
            </div>
          )}
        >
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
            <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
              {t('admin.login_token_label', {}, 'Token login')}
            </p>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t(
                'admin.login_token_help',
                {},
                'Keep public signup closed. Operators enter through the admin bootstrap token path, then continue account or site work inside the admin workspace.'
              )}
            </p>
          </BackofficeStackCard>
        </BackofficePrimaryPanel>

        <BackofficeLayer
          eyebrow={t('admin.login_form_label', {}, 'Session bootstrap')}
          title={t('admin.login_form_title', {}, 'Open admin workspace')}
          description={t(
            'admin.login_form_desc',
            {},
            'This flow only creates the admin session. Platform state and operator actions stay inside /admin after bootstrap.'
          )}
        />
        <BackofficeSectionPanel className="mx-auto w-full max-w-2xl space-y-6">
          {error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
              {error}
            </div>
          ) : null}

          <form action="/admin/auth/bootstrap" method="post" className="space-y-4">
            <input type="hidden" name="redirect" value={redirectTo} />

            <div>
              <label
                htmlFor="token"
                className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200"
              >
                {t('admin.internal_auth_token')}
              </label>
              <input
                id="token"
                name="token"
                type="password"
                autoComplete="current-password"
                required
                className="input"
                placeholder={t('admin.internal_auth_token_placeholder')}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary w-full justify-center py-3"
            >
              {t('admin.open_admin_with_internal_token')}
            </button>
          </form>
        </BackofficeSectionPanel>

        <BackofficeLayer
          eyebrow={t('admin.login_secondary_label', {}, 'Other surface')}
          title={t('nav.portal')}
          description={t(
            'admin.login_secondary_help',
            {},
            'Use portal when you need the customer-facing surface, not platform operations.'
          )}
        />
        <BackofficeSectionPanel className="mx-auto w-full max-w-2xl">
          <div className="space-y-3 text-sm">
            <p className="text-slate-600 dark:text-slate-300">
              {t(
                'admin.login_other_surface_desc',
                {},
                'Portal remains the separate customer workspace. It is not the place for plans, runtime diagnostics, or provider operations.'
              )}
            </p>
            <Link
              href="/portal"
              className="text-slate-500 underline-offset-4 hover:text-slate-900 hover:underline dark:text-slate-400 dark:hover:text-white"
            >
              {t('nav.portal')}
            </Link>
          </div>
        </BackofficeSectionPanel>
      </BackofficePageStack>
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
