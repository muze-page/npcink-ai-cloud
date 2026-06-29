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
          t('portal.account.identity_provider_load_failed', undefined, '无法读取第三方登录状态')
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
      setMessage(t('portal.account.qq_bound', undefined, 'QQ 快捷登录已绑定。'));
      void loadProviders();
      void refresh();
    }
    if (qqStatus === 'binding_required') {
      setMessage(
        t(
          'portal.account.qq_binding_required',
          undefined,
          '当前 QQ 尚未绑定账号，请在登录后从账号中心发起绑定。'
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
        throw new Error(t('portal.account.qq_authorization_missing', undefined, 'QQ 授权地址为空'));
      }
      window.location.assign(authorizationUrl);
    } catch (error) {
      setStatus('error');
      setMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.account.qq_bind_failed', undefined, '无法发起 QQ 绑定')
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
      setMessage(t('portal.account.qq_unbound', undefined, 'QQ 快捷登录已解绑，请重新登录。'));
      await refresh();
    } catch (error) {
      setStatus('error');
      setMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.account.qq_unbind_failed', undefined, '无法解绑 QQ 快捷登录')
        )
      );
    } finally {
      setStatus('idle');
    }
  };

  if (isLoading) {
    return (
      <PortalLoadingState
        message={t('portal.loading_session', undefined, '正在加载 Portal 会话')}
      />
    );
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('portal.account.signed_out_title', undefined, '需要登录')}
        description={t('portal.account.signed_out_desc', undefined, '请登录后查看账号中心。')}
        actionLabel={t('nav.sign_in')}
      />
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('portal.account.eyebrow', undefined, 'Account')}
        title={t('portal.account.title', undefined, '账号中心')}
        description={t(
          'portal.account.description',
          undefined,
          '邮箱是主账号，QQ 用作快捷登录绑定；Portal 和平台管理入口继续保持独立。'
        )}
        aside={(
          <BackofficeStatusBadge
            label={qqProvider?.bound ? t('portal.account.qq_bound_label', undefined, 'QQ 已绑定') : t('portal.account.qq_unbound_label', undefined, 'QQ 未绑定')}
            status={qqProvider?.bound ? 'active' : 'inactive'}
          />
        )}
        summary={(
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-2 xl:grid-cols-4"
            items={[
              {
                label: t('portal.account.email_label', undefined, '账号'),
                value: accountEmail || t('common.not_found'),
                size: 'compact',
              },
              {
                label: t('portal.account.package_label', undefined, '套餐'),
                value: packageLabel,
                size: 'compact',
              },
              {
                label: t('portal.account.site_count_label', undefined, '站点'),
                value: String(session.sites?.length || 0),
              },
              {
                label: t('portal.account.account_count_label', undefined, '账户'),
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
                {t('portal.account.login_methods_title', undefined, '登录方式')}
              </h2>
            </div>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void loadProviders()}
              disabled={status === 'loading'}
            >
              {t('common.refresh', undefined, '刷新')}
            </button>
          </div>

          <BackofficeStackCard className="space-y-4 bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold text-slate-950 dark:text-white">
                    {t('portal.account.email_login_title', undefined, '邮箱验证码')}
                  </h3>
                  <BackofficeStatusBadge
                    label={t('portal.account.primary_identity', undefined, '主账号')}
                    status="active"
                  />
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {accountEmail || t('common.not_found')}
                </p>
              </div>
              <Link href="/portal/login" className="btn btn-secondary">
                {t('portal.account.login_page', undefined, '登录页')}
              </Link>
            </div>
          </BackofficeStackCard>

          <BackofficeStackCard className="space-y-4 bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold text-slate-950 dark:text-white">
                    {t('portal.account.qq_login_title', undefined, 'QQ 快捷登录')}
                  </h3>
                  <BackofficeStatusBadge
                    label={
                      qqProvider?.bound
                        ? t('portal.account.bound', undefined, '已绑定')
                        : t('portal.account.unbound', undefined, '未绑定')
                    }
                    status={qqProvider?.bound ? 'active' : 'inactive'}
                  />
                  {!qqProvider?.configured ? (
                    <BackofficeStatusBadge
                      label={t('portal.account.not_configured', undefined, '未配置')}
                      status="warning"
                    />
                  ) : null}
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  {qqProvider?.bound
                    ? t('portal.account.qq_bound_desc', undefined, '可使用已绑定的 QQ 账号快捷登录 Portal。')
                    : t('portal.account.qq_unbound_desc', undefined, '绑定后可使用 QQ 快捷登录，邮箱仍是主账号。')}
                </p>
                {qqProvider?.binding?.last_login_at ? (
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    {t('portal.account.qq_last_login', undefined, '最近 QQ 登录')}：
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
                      ? t('portal.account.unbinding', undefined, '解绑中')
                      : t('portal.account.unbind_qq', undefined, '解绑 QQ')}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => void handleBindQq()}
                    disabled={!qqProvider?.configured || status === 'binding'}
                  >
                    {status === 'binding'
                      ? t('portal.account.binding', undefined, '跳转中')
                      : t('portal.account.bind_qq', undefined, '绑定 QQ')}
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
              {t('portal.account.portal_scope_title', undefined, '当前 Portal 权限')}
            </h2>
          </div>
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('portal.account.account_name_label', undefined, '账户')}
            </p>
            <p className="mt-2 text-base font-semibold text-slate-950 dark:text-white">
              {primaryAccount?.name || primaryAccount?.account_id || session.account_id || t('common.not_found')}
            </p>
          </BackofficeStackCard>
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('portal.account.role_label', undefined, '角色')}
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
    <Suspense fallback={<PortalLoadingState message="正在加载账号中心" />}>
      <AccountPageContent />
    </Suspense>
  );
}
