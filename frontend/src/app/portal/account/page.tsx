'use client';

import Link from 'next/link';
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalIdentityProviderStatus,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { cn, formatDate } from '@/lib/utils';

type AccountActionState = 'idle' | 'loading' | 'binding' | 'unbinding' | 'error';

function AccountPageContent() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const { session, isLoading, isAuthenticated, refresh } = useSession();
  const [providers, setProviders] = useState<PortalIdentityProviderStatus[]>([]);
  const [status, setStatus] = useState<AccountActionState>('loading');
  const [message, setMessage] = useState('');

  const qqProvider = useMemo(
    () => providers.find((provider) => provider.provider === 'qq') || null,
    [providers]
  );
  const primaryAccount = session?.accounts?.[0] || null;
  const packageLabel =
    session?.current_subscription?.package_alias ||
    session?.current_subscription?.tier_id ||
    session?.current_subscription?.plan_id ||
    t('common.not_found');
  const accountEmail = session?.site_admin_ref || session?.principal_id || '';
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
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('portal.account.eyebrow', undefined, 'Account')}
        title={t('portal.account.title', undefined, 'Account Center')}
        description={t(
          'portal.account.description',
          undefined,
          'Email remains the primary identity. QQ is only a quick-login binding, and Portal stays separate from platform admin.'
        )}
        aside={(
          <BackofficeStatusBadge
            label={qqProvider?.bound ? t('portal.account.qq_bound_label', undefined, 'QQ bound') : t('portal.account.qq_unbound_label', undefined, 'QQ not bound')}
            status={qqProvider?.bound ? 'active' : 'inactive'}
          />
        )}
        summary={(
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-2 xl:grid-cols-4"
            items={[
              {
                label: t('portal.account.email_label', undefined, 'Account'),
                value: accountEmail || t('common.not_found'),
                size: 'compact',
              },
              {
                label: t('portal.account.package_label', undefined, 'Package'),
                value: packageLabel,
                size: 'compact',
              },
              {
                label: t('portal.account.site_count_label', undefined, 'Sites'),
                value: String(session.sites?.length || 0),
              },
              {
                label: t('portal.account.account_count_label', undefined, 'Accounts'),
                value: String(session.accounts?.length || 0),
              },
            ]}
          />
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
        <BackofficeSectionPanel className="space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t('portal.account.identity_label', undefined, 'Identity')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
                {t('portal.account.login_methods_title', undefined, 'Login methods')}
              </h2>
            </div>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void loadProviders()}
              disabled={status === 'loading'}
            >
              {t('common.refresh', undefined, 'Refresh')}
            </button>
          </div>

          <BackofficeStackCard className="space-y-4 bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold text-slate-950 dark:text-white">
                    {t('portal.account.email_login_title', undefined, 'Email verification code')}
                  </h3>
                  <BackofficeStatusBadge
                    label={t('portal.account.primary_identity', undefined, 'Primary identity')}
                    status="active"
                  />
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {accountEmail || t('common.not_found')}
                </p>
              </div>
              <Link href="/portal/login" className="btn btn-secondary">
                {t('portal.account.login_page', undefined, 'Login page')}
              </Link>
            </div>
          </BackofficeStackCard>

          <BackofficeStackCard className="space-y-4 bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold text-slate-950 dark:text-white">
                    {t('portal.account.qq_login_title', undefined, 'QQ quick login')}
                  </h3>
                  <BackofficeStatusBadge
                    label={
                      qqProvider?.bound
                        ? t('portal.account.bound', undefined, 'Bound')
                        : t('portal.account.unbound', undefined, 'Unbound')
                    }
                    status={qqProvider?.bound ? 'active' : 'inactive'}
                  />
                  {!qqProvider?.configured ? (
                    <BackofficeStatusBadge
                      label={t('portal.account.not_configured', undefined, 'Not configured')}
                      status="warning"
                    />
                  ) : null}
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {qqProvider?.bound
                    ? t('portal.account.qq_bound_desc', undefined, 'Use the bound QQ account for quick Portal login.')
                    : t('portal.account.qq_unbound_desc', undefined, 'Bind QQ for quick login. Email remains the primary identity.')}
                </p>
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
          </BackofficeStackCard>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('portal.account.scope_label', undefined, 'Portal')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
              {t('portal.account.portal_scope_title', undefined, 'Current Portal permissions')}
            </h2>
          </div>
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('portal.account.account_name_label', undefined, 'Account')}
            </p>
            <p className="mt-2 text-base font-semibold text-slate-950 dark:text-white">
              {primaryAccount?.name || t('portal.connect_site_current_customer', undefined, 'Current customer')}
            </p>
            {(primaryAccount?.account_id || session.account_id) ? (
              <details className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                <summary className="cursor-pointer font-medium">
                  {t('portal.support_information', undefined, 'Support information')}
                </summary>
                <div className="mt-2">
                  <BackofficeIdentifier value={primaryAccount?.account_id || session.account_id || t('common.not_found')} full />
                </div>
              </details>
            ) : null}
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('portal.account.role_label', undefined, 'Role')}
            </p>
            <p className="mt-2 text-base font-semibold text-slate-950 dark:text-white">
              {session.role || t('common.not_found')}
            </p>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('portal.account.principal_label', undefined, 'Principal')}
            </p>
            <p className="mt-2 break-all text-sm font-semibold text-slate-950 dark:text-white">
              {session.principal_id || t('common.not_found')}
            </p>
          </BackofficeStackCard>
        </BackofficeSectionPanel>
      </div>
    </BackofficePageStack>
  );
}

export default function PortalAccountPage() {
  return (
    <Suspense fallback={<PortalLoadingState message="Loading Account Center" />}>
      <AccountPageContent />
    </Suspense>
  );
}
