'use client';

import Link from 'next/link';
import React, { Suspense, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import {
  BackofficeLayer,
  BackofficePageStack,
  BackofficePrimaryPanel,
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
  step: 'request' | 'verify';
  status: 'idle' | 'submitting' | 'verifying' | 'error';
  message: string;
}

function LoginFormContent() {
  const router = useRouter();
  const { t } = useLocale();
  const { requestLoginCode, verifyLoginCode } = useSession();
  const [form, setForm] = useState<FormState>({
    email: '',
    code: '',
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
      await verifyLoginCode(normalizedEmail, normalizedCode);
      router.push('/portal');
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
    <div className="mx-auto min-h-[80vh] w-full max-w-5xl px-4 py-10">
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow={t('portal.login.chip')}
          title={t('auth.welcome_back')}
          description={t(
            'auth.sign_in_desc',
            undefined,
            'Use your Portal email address to receive a one-time verification code.'
          )}
          summary={(
            <div className="grid gap-4 lg:grid-cols-2">
              <BackofficeStackCard>
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                  {t('portal.login.surface_label')}
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t('portal.login.surface_desc')}
                </p>
              </BackofficeStackCard>
              <BackofficeStackCard>
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                  {t('auth.email_verification', undefined, 'Email verification')}
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t(
                    'auth.email_verification_desc',
                    undefined,
                    'Existing users can sign in with email verification. New users can create a Free account first.'
                  )}
                </p>
              </BackofficeStackCard>
            </div>
          )}
        >
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
            <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
              {t('portal.login.surface_label')}
            </p>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t(
                'portal.login.notice',
                undefined,
                'Enter your Portal email address, receive a verification code, then continue into the portal workspace.'
              )}
            </p>
          </BackofficeStackCard>
        </BackofficePrimaryPanel>

        <BackofficeLayer
          eyebrow={t('portal.login.surface_label')}
          title={t(
            form.step === 'request' ? 'auth.request_code_title' : 'auth.verify_code_title',
            undefined,
            form.step === 'request' ? 'Request verification code' : 'Verify code'
          )}
          description={t(
            form.step === 'request' ? 'auth.request_code_desc' : 'auth.verify_code_desc',
            undefined,
            form.step === 'request'
              ? 'We will send a short-lived code to your Portal email address.'
              : 'Enter the code you received to create your portal session.'
          )}
        />

        <BackofficeSectionPanel className="mx-auto w-full max-w-2xl space-y-6">
          <form
            onSubmit={form.step === 'request' ? handleRequestCode : handleVerifyCode}
            className="space-y-6"
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
                  disabled={form.status === 'verifying'}
                />
              </div>
            ) : null}

            {form.message ? (
              <div
                className={cn(
                  'text-sm',
                  form.status === 'error'
                    ? 'text-red-600 dark:text-red-400'
                    : 'text-slate-600 dark:text-slate-300'
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
                <button
                  type="button"
                  className="btn btn-secondary justify-center"
                  onClick={resetFlow}
                >
                  {t('auth.try_another_email')}
                </button>
              ) : null}
            </div>
          </form>

          <div className="border-t border-gray-200 pt-6 dark:border-gray-700">
            <p className="text-center text-sm text-gray-600 dark:text-gray-400">
              {t(
                'auth.no_password',
                undefined,
                'Portal sign-in is passwordless. New users can create a Free account and bind QQ quick login after signing in.'
              )}
            </p>
            <p className="mt-3 text-center text-sm text-gray-600 dark:text-gray-400">
              <Link href="/portal/register" className="font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300">
                {t('auth.create_free_account', undefined, 'Create a Free account')}
              </Link>
            </p>
          </div>
        </BackofficeSectionPanel>

        <BackofficeLayer
          eyebrow={t('backoffice.layer_secondary')}
          title={t('auth.get_started')}
          description={t('portal.login.footer')}
        />
        <BackofficeSectionPanel className="mx-auto w-full max-w-2xl text-center">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {t('portal.login.footer')}
          </p>
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
