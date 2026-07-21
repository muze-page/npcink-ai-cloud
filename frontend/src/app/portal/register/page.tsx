'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import React, { Suspense, useEffect, useState } from 'react';
import { PortalAuthShell } from '@/components/portal/PortalAuthShell';
import { PortalCard } from '@/components/portal/PortalScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import { portalClient } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { cn } from '@/lib/utils';

interface RegisterFormState {
  email: string;
  code: string;
  step: 'request' | 'verify';
  status: 'idle' | 'submitting' | 'verifying' | 'error';
  message: string;
}

function RegisterFormContent() {
  const router = useRouter();
  const { t } = useLocale();
  const { isAuthenticated, isLoading, refresh } = useSession();
  const [form, setForm] = useState<RegisterFormState>({
    email: '',
    code: '',
    step: 'request',
    status: 'idle',
    message: '',
  });

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace('/portal');
    }
  }, [isAuthenticated, isLoading, router]);

  if (isLoading || isAuthenticated) {
    return <LoadingFallback />;
  }

  const setField = (key: keyof RegisterFormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value, status: 'idle', message: '' }));
  };

  const handleRequestCode = async (event: React.FormEvent) => {
    event.preventDefault();
    const email = form.email.trim().toLowerCase();
    if (!email) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: t(
          'portal.register.required',
          undefined,
          'Please enter your email address.'
        ),
      }));
      return;
    }

    setForm((prev) => ({ ...prev, status: 'submitting', email, message: '' }));
    try {
      const response = await portalClient.requestRegistrationCode({
        email,
      });
      setForm((prev) => ({
        ...prev,
        step: 'verify',
        status: 'idle',
        code: response.data?.code || '',
        message: t(
          'portal.register.code_sent',
          { email },
          `Verification code sent to ${email}.`
        ),
      }));
    } catch (error) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: formatPortalErrorMessage(
          error,
          t,
          t('portal.register.failed_send_code', undefined, 'Failed to send verification code')
        ),
      }));
    }
  };

  const handleVerifyCode = async (event: React.FormEvent) => {
    event.preventDefault();
    const email = form.email.trim().toLowerCase();
    const code = form.code.trim();
    if (!email || !code) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: t(
          'portal.register.code_required',
          undefined,
          'Please enter the verification code.'
        ),
      }));
      return;
    }
    setForm((prev) => ({ ...prev, status: 'verifying', message: '' }));
    try {
      await portalClient.verifyRegistration({ email, code });
      await refresh();
      window.location.replace('/portal');
    } catch (error) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: formatPortalErrorMessage(
          error,
          t,
          t(
            'portal.register.invalid_code',
            undefined,
            'Invalid or expired verification code.'
          )
        ),
      }));
    }
  };

  const handleResendCode = async () => {
    const email = form.email.trim().toLowerCase();
    if (!email) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: t(
          'portal.register.required',
          undefined,
          'Please enter your email address.'
        ),
      }));
      return;
    }

    setForm((prev) => ({ ...prev, status: 'submitting', email, message: '' }));
    try {
      const response = await portalClient.requestRegistrationCode({
        email,
      });
      setForm((prev) => ({
        ...prev,
        step: 'verify',
        status: 'idle',
        code: response.data?.code || '',
        message: t(
          'portal.register.code_resent',
          { email },
          `Verification code resent to ${email}.`
        ),
      }));
    } catch (error) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: formatPortalErrorMessage(
          error,
          t,
          t('portal.register.failed_send_code', undefined, 'Failed to send verification code')
        ),
      }));
    }
  };

  const resetFlow = () => {
    setForm((prev) => ({
      ...prev,
      step: 'request',
      code: '',
      status: 'idle',
      message: '',
    }));
  };

  return (
    <PortalAuthShell
      eyebrow={t('portal.register.chip', undefined, 'Free signup')}
      title={t('portal.register.title', undefined, 'Create your Portal account')}
      description={t(
        form.step === 'request' ? 'portal.register.request_desc' : 'portal.register.verify_desc',
        undefined,
        form.step === 'request'
          ? 'Enter your email address to create a Free account.'
          : 'Enter the code from your email to finish registration.'
      )}
      aside={(
        <>
          <PortalCard className="bg-white/70 dark:bg-slate-950/35">
            <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
              {t('portal.register.free_label', undefined, 'Free')}
            </p>
            <h2 className="mt-3 text-lg font-semibold text-slate-950 dark:text-white">
              {t('portal.register.free_title', undefined, 'Start with one WordPress site')}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t(
                'portal.register.desc',
                undefined,
                'Use email verification to open a Free account for one WordPress site. QQ quick login can be bound after you sign in.'
              )}
            </p>
          </PortalCard>
          <PortalCard className="mt-4 bg-white/70 dark:bg-slate-950/35">
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('portal.register.already_title', undefined, 'Already have an account?')}
            </p>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t('portal.register.already_desc', undefined, 'Use your email verification code to log in.')}
            </p>
            <Link href="/portal/login" className="btn btn-secondary mt-4 w-full justify-center">
              {t('nav.sign_in')}
            </Link>
          </PortalCard>
        </>
      )}
    >
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
                    autoComplete="email"
                    value={form.email}
                    onChange={(event) => setField('email', event.target.value)}
                    placeholder={t('auth.email_placeholder')}
                    className={cn('input', form.status === 'error' && 'border-red-500 focus:ring-red-500')}
                    disabled={form.status === 'submitting' || form.status === 'verifying' || form.step === 'verify'}
                  />
                </div>

                {form.step === 'request' ? (
                  null
                ) : (
                  <div>
                    <label htmlFor="code" className="mb-2 block text-sm font-medium">
                      {t('auth.verification_code', undefined, 'Verification code')}
                    </label>
                    <input
                      id="code"
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      value={form.code}
                      onChange={(event) => setField('code', event.target.value)}
                      placeholder={t('auth.verification_code_placeholder', undefined, 'Enter the 6-digit code')}
                      className={cn('input', form.status === 'error' && 'border-red-500 focus:ring-red-500')}
                      disabled={form.status === 'submitting' || form.status === 'verifying'}
                    />
                  </div>
                )}

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
                        : t('portal.register.send_code', undefined, 'Send verification code')
                      : form.status === 'verifying'
                        ? t('portal.register.opening', undefined, 'Opening...')
                        : t('portal.register.verify_continue', undefined, 'Verify and continue')}
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
    </PortalAuthShell>
  );
}

function RegisterForm() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <RegisterFormContent />
    </Suspense>
  );
}

export default function RegisterPage() {
  return <RegisterForm />;
}
