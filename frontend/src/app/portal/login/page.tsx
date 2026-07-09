'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import React, { Suspense, useState } from 'react';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { useSession } from '@/hooks/useSession';
import { cn } from '@/lib/utils';

interface FormState {
  email: string;
  code: string;
  rememberMe: boolean;
  step: 'request' | 'verify';
  status: 'idle' | 'submitting' | 'verifying' | 'error';
  message: string;
}

function resolvePortalLoginRedirect(value: string | null): string {
  const redirect = String(value || '').trim();
  if (
    redirect === '/portal' ||
    redirect.startsWith('/portal/') ||
    redirect.startsWith('/portal?') ||
    redirect.startsWith('/portal#')
  ) {
    return redirect;
  }
  return '/portal';
}

function LoginFormContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { requestLoginCode, verifyLoginCode } = useSession();
  const redirectTo = resolvePortalLoginRedirect(searchParams.get('redirect'));
  const [form, setForm] = useState<FormState>({
    email: '',
    code: '',
    rememberMe: false,
    step: 'request',
    status: 'idle',
    message: '',
  });

  const handleRequestCode = async (event: React.FormEvent) => {
    event.preventDefault();
    const normalizedEmail = form.email.trim().toLowerCase();
    if (!normalizedEmail) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: t('error.email_required', undefined, 'Please enter your email address'),
      }));
      return;
    }

    setForm((prev) => ({
      ...prev,
      status: 'submitting',
      email: normalizedEmail,
      message: '',
    }));

    try {
      const response = await requestLoginCode(normalizedEmail);
      setForm((prev) => ({
        ...prev,
        status: 'idle',
        step: 'verify',
        code: response.code || '',
        message: t(
          'auth.code_sent',
          { email: normalizedEmail },
          `Verification code sent to ${normalizedEmail}.`
        ),
      }));
    } catch (error) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: formatPortalErrorMessage(
          error,
          t,
          t('error.failed_send_code', undefined, 'Failed to send verification code')
        ),
      }));
    }
  };

  const handleVerifyCode = async (event: React.FormEvent) => {
    event.preventDefault();
    const normalizedEmail = form.email.trim().toLowerCase();
    const normalizedCode = form.code.trim();
    if (!normalizedEmail) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: t('error.email_required', undefined, 'Please enter your email address'),
      }));
      return;
    }
    if (!normalizedCode) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: t('error.portal_login_code_required', undefined, 'Please enter the verification code'),
      }));
      return;
    }

    setForm((prev) => ({ ...prev, status: 'verifying', message: '' }));

    try {
      await verifyLoginCode(normalizedEmail, normalizedCode, { rememberMe: form.rememberMe });
      window.location.replace(redirectTo);
    } catch (error) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: formatPortalErrorMessage(
          error,
          t,
          t('error.portal_login_code_invalid', undefined, 'Invalid or expired verification code')
        ),
      }));
    }
  };

  const handleResendCode = async () => {
    const normalizedEmail = form.email.trim().toLowerCase();
    if (!normalizedEmail) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: t('error.email_required', undefined, 'Please enter your email address'),
      }));
      return;
    }

    setForm((prev) => ({
      ...prev,
      status: 'submitting',
      email: normalizedEmail,
      message: '',
    }));

    try {
      const response = await requestLoginCode(normalizedEmail);
      setForm((prev) => ({
        ...prev,
        status: 'idle',
        step: 'verify',
        code: response.code || '',
        message: t(
          'auth.code_resent',
          { email: normalizedEmail },
          `Verification code resent to ${normalizedEmail}.`
        ),
      }));
    } catch (error) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: formatPortalErrorMessage(
          error,
          t,
          t('error.failed_send_code', undefined, 'Failed to send verification code')
        ),
      }));
    }
  };

  const resetFlow = () => {
    setForm((prev) => ({
      ...prev,
      code: '',
      message: '',
      status: 'idle',
      step: 'request',
    }));
  };

  return (
    <div className="mx-auto flex min-h-[72vh] w-full max-w-5xl items-center px-4 py-10">
      <BackofficePageStack>
        <BackofficeSectionPanel className="w-full overflow-hidden p-0" variant="portal">
          <div className="grid gap-0 lg:grid-cols-[minmax(0,1.05fr)_minmax(18rem,0.75fr)]">
            <div className="space-y-6 p-5 md:p-7">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-700 dark:text-blue-300">
                  {t('portal.login.existing_label', undefined, 'Existing account')}
                </p>
                <h1 className="mt-3 text-2xl font-semibold tracking-tight text-gray-950 dark:text-white md:text-[2rem]">
                  {t('portal.login.title', undefined, 'Log in to user service center')}
                </h1>
                <p className="mt-3 max-w-xl text-sm leading-6 text-gray-600 dark:text-gray-300">
                  {t(
                    form.step === 'request' ? 'auth.sign_in_desc' : 'auth.verify_code_desc',
                    undefined,
                    form.step === 'request'
                      ? 'Use your Portal email address to receive a one-time verification code.'
                      : 'Enter the code you received to create your portal session.'
                  )}
                </p>
              </div>

              <form
                onSubmit={form.step === 'request' ? handleRequestCode : handleVerifyCode}
                className="space-y-5"
              >
                <div>
                  <label htmlFor="email" className="mb-2 block text-sm font-medium">
                    {t('auth.email')}
                  </label>
                  <input
                    id="email"
                    type="email"
                    value={form.email}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        email: event.target.value,
                        status: 'idle',
                        message: '',
                      }))
                    }
                    placeholder={t('auth.email_placeholder')}
                    className={cn('input', form.status === 'error' && 'border-red-500 focus:ring-red-500')}
                    disabled={form.status === 'submitting' || form.status === 'verifying' || form.step === 'verify'}
                  />
                </div>

                {form.step === 'verify' ? (
                  <div>
                    <label htmlFor="code" className="mb-2 block text-sm font-medium">
                      {t('auth.verification_code', undefined, 'Verification code')}
                    </label>
                    <input
                      id="code"
                      type="text"
                      inputMode="numeric"
                      value={form.code}
                      onChange={(event) =>
                        setForm((prev) => ({
                          ...prev,
                          code: event.target.value,
                          status: 'idle',
                          message: '',
                        }))
                      }
                      placeholder={t('auth.verification_code_placeholder', undefined, 'Enter the 6-digit code')}
                      className={cn('input', form.status === 'error' && 'border-red-500 focus:ring-red-500')}
                      disabled={form.status === 'submitting' || form.status === 'verifying'}
                    />
                  </div>
            ) : null}

            <label className="flex items-start gap-3 rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 text-left text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-950/55 dark:text-slate-200">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 dark:border-slate-700"
                checked={form.rememberMe}
                disabled={form.status === 'submitting' || form.status === 'verifying'}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    rememberMe: event.target.checked,
                    status: 'idle',
                    message: '',
                  }))
                }
              />
              <span>
                <span className="block font-semibold text-slate-900 dark:text-white">
                  {t('auth.remember_me_7_days', undefined, 'Keep me signed in for 7 days on this device')}
                </span>
                <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {t('auth.remember_me_7_days_desc', undefined, 'Use this only on a private device. Signing out clears this session.')}
                </span>
              </span>
            </label>

            {form.message ? (
              <div
                className={cn(
                      'rounded-2xl px-3 py-2 text-sm',
                      form.status === 'error'
                        ? 'bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300'
                        : 'bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-200'
                    )}
                  >
                    {form.message}
                  </div>
                ) : null}

                <div className="flex flex-col gap-3 sm:flex-row">
                  <button
                    type="submit"
                    disabled={form.status === 'submitting' || form.status === 'verifying'}
                    className="btn btn-primary flex-1 justify-center"
                  >
                    {form.step === 'request'
                      ? form.status === 'submitting'
                        ? t('auth.sending')
                        : t('auth.send_login_code', undefined, 'Send verification code')
                      : form.status === 'verifying'
                        ? t('auth.signing_in')
                        : t('auth.verify_and_continue', undefined, 'Verify and continue')}
                  </button>

                  {form.step === 'verify' ? (
                    <>
                      <button
                        type="button"
                        className="btn btn-secondary justify-center"
                        disabled={form.status === 'submitting' || form.status === 'verifying'}
                        onClick={handleResendCode}
                      >
                        {form.status === 'submitting'
                          ? t('auth.sending')
                          : t('auth.resend_code', undefined, 'Resend code')}
                      </button>

                      <button
                        type="button"
                        className="btn btn-secondary justify-center"
                        disabled={form.status === 'submitting' || form.status === 'verifying'}
                        onClick={resetFlow}
                      >
                        {t('auth.try_another_email')}
                      </button>
                    </>
                  ) : null}
                </div>
              </form>
            </div>

            <aside className="border-t border-slate-200/80 bg-slate-50/70 p-5 dark:border-slate-800 dark:bg-slate-950/35 md:p-7 lg:border-l lg:border-t-0">
              <BackofficeStackCard className="bg-white/70 dark:bg-slate-950/35" variant="portal">
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                  {t('portal.register.free_label', undefined, 'Free')}
                </p>
                <h2 className="mt-3 text-lg font-semibold text-slate-950 dark:text-white">
                  {t('portal.login.new_title', undefined, 'No account yet?')}
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t(
                    'portal.login.new_desc',
                    undefined,
                    'Create a Free account for one WordPress site, then come back to sign in with email.'
                  )}
                </p>
                <Link href="/portal/register" className="btn btn-secondary mt-4 w-full justify-center">
                  {t('auth.create_free_account', undefined, 'Create a Free account')}
                </Link>
              </BackofficeStackCard>

              <p className="mt-4 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {t(
                  'auth.no_password',
                  undefined,
                  'Portal sign-in is passwordless. New users can create a Free account and bind QQ quick login after signing in.'
                )}
              </p>
            </aside>
          </div>
        </BackofficeSectionPanel>
      </BackofficePageStack>
    </div>
  );
}

function LoginForm() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <LoginFormContent />
    </Suspense>
  );
}

export default function LoginPage() {
  return <LoginForm />;
}
