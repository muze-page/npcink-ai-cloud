'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import React, { Suspense, useState } from 'react';
import {
  BackofficeLayer,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { portalClient } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { cn } from '@/lib/utils';

interface RegisterFormState {
  email: string;
  siteUrl: string;
  siteName: string;
  useCase: string;
  code: string;
  step: 'request' | 'verify';
  status: 'idle' | 'submitting' | 'verifying' | 'error';
  message: string;
}

function RegisterFormContent() {
  const router = useRouter();
  const { t } = useLocale();
  const [form, setForm] = useState<RegisterFormState>({
    email: '',
    siteUrl: '',
    siteName: '',
    useCase: '',
    code: '',
    step: 'request',
    status: 'idle',
    message: '',
  });

  const setField = (key: keyof RegisterFormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value, status: 'idle', message: '' }));
  };

  const handleRequestCode = async (event: React.FormEvent) => {
    event.preventDefault();
    const email = form.email.trim().toLowerCase();
    const siteUrl = form.siteUrl.trim();
    if (!email || !siteUrl) {
      setForm((prev) => ({
        ...prev,
        status: 'error',
        message: t(
          'portal.register.required',
          undefined,
          'Please enter your email address and WordPress site URL.'
        ),
      }));
      return;
    }

    setForm((prev) => ({ ...prev, status: 'submitting', email, siteUrl, message: '' }));
    try {
      const response = await portalClient.requestRegistrationCode({
        email,
        site_url: siteUrl,
        site_name: form.siteName.trim(),
        use_case: form.useCase.trim(),
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
      router.push('/portal');
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
    <div className="mx-auto min-h-[80vh] w-full max-w-5xl px-4 py-10">
      <BackofficePageStack>
        <BackofficePrimaryPanel
          eyebrow={t('portal.register.chip', undefined, 'Free signup')}
          title={t('portal.register.title', undefined, 'Create your Portal account')}
          description={t(
            'portal.register.desc',
            undefined,
            'Use email verification to open a Free account for one WordPress site. QQ quick login can be bound after you sign in.'
          )}
          summary={(
            <div className="grid gap-4 lg:grid-cols-2">
              <BackofficeStackCard>
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                  {t('portal.register.free_label', undefined, 'Free')}
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t(
                    'portal.register.free_desc',
                    undefined,
                    'The Free package is opened automatically after your email code is verified.'
                  )}
                </p>
              </BackofficeStackCard>
              <BackofficeStackCard>
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                  {t('portal.register.qq_label', undefined, 'QQ')}
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {t(
                    'portal.register.qq_desc',
                    undefined,
                    'Bind QQ quick login from your account page after the email account is active.'
                  )}
                </p>
              </BackofficeStackCard>
            </div>
          )}
        />

        <BackofficeLayer
          eyebrow={t('portal.register.form_label', undefined, 'Signup')}
          title={t(
            form.step === 'request'
              ? 'portal.register.request_title'
              : 'portal.register.verify_title',
            undefined,
            form.step === 'request' ? 'Request verification code' : 'Verify and open Free'
          )}
          description={t(
            form.step === 'request'
              ? 'portal.register.request_desc'
              : 'portal.register.verify_desc',
            undefined,
            form.step === 'request'
              ? 'Enter the email and WordPress site that will own this Free account.'
              : 'Enter the code from your email to finish registration.'
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
                onChange={(event) => setField('email', event.target.value)}
                placeholder={t('auth.email_placeholder')}
                className={cn('input', form.status === 'error' && 'border-red-500 focus:ring-red-500')}
                disabled={form.status === 'submitting' || form.status === 'verifying' || form.step === 'verify'}
              />
            </div>

            {form.step === 'request' ? (
              <>
                <div>
                  <label htmlFor="siteUrl" className="mb-2 block text-sm font-medium">
                    {t('portal.register.site_url', undefined, 'WordPress site URL')}
                  </label>
                  <input
                    id="siteUrl"
                    type="url"
                    value={form.siteUrl}
                    onChange={(event) => setField('siteUrl', event.target.value)}
                    placeholder="https://example.com"
                    className={cn('input', form.status === 'error' && 'border-red-500 focus:ring-red-500')}
                    disabled={form.status === 'submitting'}
                  />
                </div>
                <div>
                  <label htmlFor="siteName" className="mb-2 block text-sm font-medium">
                    {t('portal.register.site_name', undefined, 'Site name')}
                  </label>
                  <input
                    id="siteName"
                    type="text"
                    value={form.siteName}
                    onChange={(event) => setField('siteName', event.target.value)}
                    placeholder={t('portal.register.site_name_placeholder', undefined, 'My WordPress site')}
                    className="input"
                    disabled={form.status === 'submitting'}
                  />
                </div>
                <div>
                  <label htmlFor="useCase" className="mb-2 block text-sm font-medium">
                    {t('portal.register.use_case', undefined, 'Use case')}
                  </label>
                  <textarea
                    id="useCase"
                    value={form.useCase}
                    onChange={(event) => setField('useCase', event.target.value)}
                    placeholder={t('portal.register.use_case_placeholder', undefined, 'Content generation, site knowledge, automation...')}
                    className="input min-h-24 resize-y"
                    disabled={form.status === 'submitting'}
                  />
                </div>
              </>
            ) : (
              <div>
                <label htmlFor="code" className="mb-2 block text-sm font-medium">
                  {t('auth.verification_code', undefined, 'Verification code')}
                </label>
                <input
                  id="code"
                  type="text"
                  inputMode="numeric"
                  value={form.code}
                  onChange={(event) => setField('code', event.target.value)}
                  placeholder={t('auth.verification_code_placeholder', undefined, 'Enter the 6-digit code')}
                  className={cn('input', form.status === 'error' && 'border-red-500 focus:ring-red-500')}
                  disabled={form.status === 'verifying'}
                />
              </div>
            )}

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
                    : t('portal.register.send_code', undefined, 'Send verification code')
                  : form.status === 'verifying'
                    ? t('portal.register.opening', undefined, 'Opening...')
                    : t('portal.register.verify_continue', undefined, 'Verify and continue')}
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

          <div className="border-t border-gray-200 pt-6 text-center text-sm text-gray-600 dark:border-gray-700 dark:text-gray-400">
            <Link href="/portal/login" className="font-medium text-blue-600 hover:text-blue-700 dark:text-blue-300">
              {t('portal.register.login_link', undefined, 'Already have an account? Sign in')}
            </Link>
          </div>
        </BackofficeSectionPanel>
      </BackofficePageStack>
    </div>
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
