'use client';

import Link from 'next/link';
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  PortalPageStack,
  PortalPrimaryPanel,
  PortalSection,
  PortalCard,
} from '@/components/portal/PortalScaffold';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import { Modal } from '@/components/ui/Modal';
import {
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalSession,
  type PortalIdentityProviderStatus,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { cn, formatDate } from '@/lib/utils';

type AccountActionState =
  | 'idle'
  | 'loading'
  | 'binding'
  | 'unbinding'
  | 'requesting_email_change'
  | 'verifying_email_change'
  | 'error';

function normalizePortalContact(value?: string): string {
  const trimmed = String(value || '').trim();
  if (!trimmed) {
    return '';
  }
  const withoutPrefix = trimmed.replace(/^user:/, '');
  return withoutPrefix.includes('@') && !withoutPrefix.startsWith('prn_') ? withoutPrefix : '';
}

function resolvePortalContactEmail(session: PortalSession): string {
  const memberRef = (session as PortalSession & { member_ref?: string }).member_ref;
  const candidates = [
    session.email,
    session.site_admin_ref,
    memberRef,
    session.accounts?.[0]?.site_admin_ref,
  ];

  for (const candidate of candidates) {
    const email = normalizePortalContact(candidate);
    if (email) {
      return email;
    }
  }

  return '';
}

function AccountPageContent() {
  const { locale, t } = useLocale();
  const searchParams = useSearchParams();
  const { session, isLoading, isAuthenticated, refresh } = useSession();
  const [providers, setProviders] = useState<PortalIdentityProviderStatus[]>([]);
  const [status, setStatus] = useState<AccountActionState>('loading');
  const [message, setMessage] = useState('');
  const [emailChangeNewEmail, setEmailChangeNewEmail] = useState('');
  const [emailChangeCode, setEmailChangeCode] = useState('');
  const [emailChangePendingEmail, setEmailChangePendingEmail] = useState('');
  const [showEmailChange, setShowEmailChange] = useState(false);

  const qqProvider = useMemo(
    () => providers.find((provider) => provider.provider === 'qq') || null,
    [providers]
  );
  const contactEmail = session ? resolvePortalContactEmail(session) : '';
  const qqStatus = searchParams?.get('qq') || '';

  const loadProviders = useCallback(async () => {
    setStatus('loading');
    setMessage('');
    try {
      const response = await portalClient.getIdentityProviders();
      setProviders(response.data?.providers || []);
      setStatus('idle');
    } catch (error) {
      setStatus('error');
      setMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.account.identity_provider_load_failed', undefined, 'Unable to read third-party login status')
        )
      );
    }
  }, [t]);

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    void loadProviders();
  }, [isAuthenticated, loadProviders]);

  useEffect(() => {
    if (qqStatus === 'bound') {
      setMessage(t('portal.account.qq_bound', undefined, 'QQ quick login is bound.'));
      void loadProviders();
      void refresh();
    }
    if (qqStatus === 'binding_required') {
      setMessage(
        t(
          'portal.account.qq_binding_required',
          undefined,
          'This QQ account is not linked yet. Sign in and start binding from Account Center.'
        )
      );
    }
  }, [loadProviders, qqStatus, refresh, t]);

  const handleBindQq = async () => {
    setStatus('binding');
    setMessage('');
    try {
      const response = await portalClient.startQqBind('/portal/account');
      const authorizationUrl = response.data?.authorization_url || '';
      if (!authorizationUrl) {
        throw new Error(t('portal.account.qq_authorization_missing', undefined, 'QQ authorization URL is empty'));
      }
      window.location.assign(authorizationUrl);
    } catch (error) {
      setStatus('error');
      setMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.account.qq_bind_failed', undefined, 'Unable to start QQ binding')
        )
      );
    }
  };

  const handleUnbindQq = async () => {
    setStatus('unbinding');
    setMessage('');
    try {
      await portalClient.unbindQqLogin();
      setProviders((current) =>
        current.map((provider) =>
          provider.provider === 'qq'
            ? { ...provider, bound: false, binding: null }
            : provider
        )
      );
      setMessage(t('portal.account.qq_unbound', undefined, 'QQ quick login has been unbound. Sign in again.'));
      await refresh();
    } catch (error) {
      setStatus('error');
      setMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.account.qq_unbind_failed', undefined, 'Unable to unbind QQ quick login')
        )
      );
    } finally {
      setStatus('idle');
    }
  };

  const handleRequestEmailChange = async () => {
    const nextEmail = emailChangeNewEmail.trim();
    if (!nextEmail) {
      setStatus('error');
      setMessage(t('portal.account.email_change_required', undefined, 'Enter the new email address.'));
      return;
    }
    setStatus('requesting_email_change');
    setMessage('');
    setEmailChangeCode('');
    try {
      const response = await portalClient.requestEmailChangeCode({
        new_email: nextEmail,
        locale: locale === 'en' ? 'en' : 'zh-CN',
      });
      const pendingEmail = response.data?.new_email || nextEmail;
      setEmailChangePendingEmail(pendingEmail);
      setMessage(
        t(
          'portal.account.email_change_code_sent',
          { email: pendingEmail },
          'Verification code sent to {{email}}. The current email remains active until verification.'
        )
      );
      setStatus('idle');
    } catch (error) {
      setStatus('error');
      setMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.account.email_change_request_failed', undefined, 'Unable to send the email change code')
        )
      );
    }
  };

  const handleVerifyEmailChange = async () => {
    const nextEmail = (emailChangePendingEmail || emailChangeNewEmail).trim();
    const code = emailChangeCode.trim();
    if (!nextEmail || !code) {
      setStatus('error');
      setMessage(t('portal.account.email_change_code_required', undefined, 'Enter the verification code from the new email.'));
      return;
    }
    setStatus('verifying_email_change');
    setMessage('');
    try {
      const response = await portalClient.verifyEmailChangeCode({
        new_email: nextEmail,
        code,
      });
      const changedEmail = response.data?.new_email || nextEmail;
      setEmailChangeNewEmail('');
      setEmailChangePendingEmail('');
      setEmailChangeCode('');
      setMessage(
        t(
          'portal.account.email_change_done',
          { email: changedEmail },
          'Login email changed to {{email}}.'
        )
      );
      await refresh();
      setStatus('idle');
      setShowEmailChange(false);
    } catch (error) {
      setStatus('error');
      setMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.account.email_change_verify_failed', undefined, 'Unable to verify the email change code')
        )
      );
    }
  };

  if (isLoading) {
    return (
      <PortalLoadingState
        message={t('portal.loading_session', undefined, 'Loading Portal session')}
      />
    );
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('portal.account.signed_out_title', undefined, 'Sign-in required')}
        description={t('portal.account.signed_out_desc', undefined, 'Sign in to view Account Center.')}
        actionLabel={t('nav.sign_in')}
      />
    );
  }

  return (
    <PortalPageStack>
      <PortalPrimaryPanel
        eyebrow={t('portal.account.settings_eyebrow', undefined, 'Account settings')}
        title={t('portal.account.title', undefined, 'Contact')}
        description={t(
          'portal.account.description',
          undefined,
          'Manage the email used for verification codes and optional quick login.'
        )}
      />

      {message ? (
        <div
          className={cn(
            'rounded-[1.1rem] border px-4 py-3 text-sm',
            status === 'error'
              ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-200'
              : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/30 dark:text-blue-200'
          )}
        >
          {message}
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.8fr)]">
        <PortalSection className="space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t('portal.account.login_methods_label', undefined, 'Login')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                {t('portal.account.login_methods_title', undefined, 'Login methods')}
              </h2>
            </div>
          </div>

          <PortalCard className="space-y-4 bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold text-slate-950 dark:text-white">
                    {t('portal.account.email_login_title', undefined, 'Email verification code')}
                  </h3>
                  <PortalStatusBadge
                    label={t('portal.account.primary_identity', undefined, 'Primary identity')}
                    status="active"
                  />
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {contactEmail || t('portal.account.contact_missing_desc', undefined, 'Email contact is not visible in this local session.')}
                </p>
              </div>
              <Link href="/portal/audit" className="btn btn-secondary">
                {t('portal.audit.nav_label', undefined, 'Recent activity')}
              </Link>
            </div>
          </PortalCard>

          <PortalCard className="space-y-4 bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold text-slate-950 dark:text-white">
                    {t('portal.account.qq_login_title', undefined, 'QQ quick login')}
                  </h3>
                  <PortalStatusBadge
                    label={
                      qqProvider?.bound
                        ? t('portal.account.bound', undefined, 'Bound')
                        : t('portal.account.unbound', undefined, 'Unbound')
                    }
                    status={qqProvider?.bound ? 'active' : 'inactive'}
                  />
                  {!qqProvider?.configured ? (
                    <PortalStatusBadge
                      label={t('portal.account.not_configured', undefined, 'Not configured')}
                      status="warning"
                    />
                  ) : null}
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {qqProvider?.bound
                    ? t('portal.account.qq_bound_desc', undefined, '可使用已绑定的 QQ 账号快捷登录 Portal。')
                    : t('portal.account.qq_unbound_desc', undefined, '绑定后可使用 QQ 快捷登录，邮箱仍是主账号。')}
                </p>
                {!qqProvider?.configured ? (
                  <p className="mt-2 text-xs leading-5 text-amber-700 dark:text-amber-300">
                    {t('portal.account.qq_unavailable_desc', undefined, 'QQ quick login is not available in the current environment. Email login remains available.')}
                  </p>
                ) : null}
                {qqProvider?.binding?.last_login_at ? (
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    {t('portal.account.qq_last_login', undefined, 'Last QQ login')}:
                    {formatDate(qqProvider.binding.last_login_at)}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                {qqProvider?.bound ? (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => void handleUnbindQq()}
                    disabled={status === 'unbinding'}
                  >
                    {status === 'unbinding'
                      ? t('portal.account.unbinding', undefined, 'Unbinding')
                      : t('portal.account.unbind_qq', undefined, 'Unbind QQ')}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => void handleBindQq()}
                    disabled={!qqProvider?.configured || status === 'binding'}
                  >
                    {status === 'binding'
                      ? t('portal.account.binding', undefined, 'Redirecting')
                      : t('portal.account.bind_qq', undefined, 'Bind QQ')}
                  </button>
                )}
              </div>
            </div>
          </PortalCard>
        </PortalSection>

        <div data-portal-account="contact-info">
          <PortalSection className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t('portal.account.contact_label', undefined, 'Contact')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                {t('portal.account.contact_title', undefined, 'Contact information')}
              </h2>
              <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t(
                  'portal.account.contact_desc',
                  undefined,
                  'This is the information used for login codes, service notices, and support follow-up.'
                )}
              </p>
            </div>

            <PortalCard className="space-y-4 bg-white/80 dark:bg-slate-950/55">
              <p className="text-base font-semibold text-slate-950 dark:text-white">
                {contactEmail || t('portal.account.contact_missing_desc', undefined, 'Email contact is not visible in this local session.')}
              </p>
              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t(
                  'portal.account.contact_change_desc',
                  undefined,
                  'Enter a new email and verify the code sent there. Your current email remains active until verification succeeds.'
                )}
              </p>
              <button type="button" className="btn btn-secondary" onClick={() => setShowEmailChange(true)}>
                {t('portal.account.contact_change_title', undefined, 'Change email')}
              </button>
            </PortalCard>
          </PortalSection>
        </div>
      </div>

      <Modal
        isOpen={showEmailChange}
        onClose={() => setShowEmailChange(false)}
        title={t('portal.account.contact_change_title', undefined, 'Change email')}
        description={t(
          'portal.account.contact_change_desc',
          undefined,
          'Enter a new email and verify the code sent there. Your current email remains active until verification succeeds.'
        )}
      >
        <div className="grid gap-3" data-portal-account="email-change-dialog">
          {message ? (
            <p
              className={cn(
                'rounded-xl px-3 py-2 text-sm',
                status === 'error'
                  ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-200'
                  : 'bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-200'
              )}
              role="status"
            >
              {message}
            </p>
          ) : null}
          <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('portal.account.email_change_new_email', undefined, 'New email')}
            <input
              type="email"
              value={emailChangeNewEmail}
              onChange={(event) => setEmailChangeNewEmail(event.target.value)}
              placeholder={t('auth.email_placeholder', undefined, 'you@example.com')}
              className="input"
              autoComplete="email"
            />
          </label>
          <button
            type="button"
            className="btn btn-secondary justify-center"
            onClick={() => void handleRequestEmailChange()}
            disabled={status === 'requesting_email_change'}
          >
            {status === 'requesting_email_change'
              ? t('portal.account.email_change_sending', undefined, 'Sending')
              : t('portal.account.email_change_send_code', undefined, 'Send verification code')}
          </button>
          {emailChangePendingEmail ? (
            <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/40">
              <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                {t(
                  'portal.account.email_change_pending_desc',
                  { email: emailChangePendingEmail },
                  'Enter the code sent to {{email}} to switch the login email.'
                )}
              </p>
              <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                {t('portal.account.email_change_code', undefined, 'Verification code')}
                <input
                  type="text"
                  inputMode="numeric"
                  value={emailChangeCode}
                  onChange={(event) => setEmailChangeCode(event.target.value)}
                  placeholder="000000"
                  className="input"
                  autoComplete="one-time-code"
                />
              </label>
              <button
                type="button"
                className="btn btn-primary justify-center"
                onClick={() => void handleVerifyEmailChange()}
                disabled={status === 'verifying_email_change'}
              >
                {status === 'verifying_email_change'
                  ? t('portal.account.email_change_verifying', undefined, 'Verifying')
                  : t('portal.account.email_change_confirm', undefined, 'Confirm email change')}
              </button>
            </div>
          ) : null}
        </div>
      </Modal>
    </PortalPageStack>
  );
}

export default function PortalAccountPage() {
  return (
    <Suspense fallback={<PortalLoadingState message="Loading Account Center" />}>
      <AccountPageContent />
    </Suspense>
  );
}
