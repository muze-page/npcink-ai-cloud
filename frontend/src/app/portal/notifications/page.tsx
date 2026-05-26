'use client';

import React, { Suspense, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficePageStack, BackofficeStackCard } from '@/components/backoffice/BackofficeScaffold';
import { PortalActionRequestResultStrip } from '@/components/portal/PortalActionRequestResultStrip';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  formatPortalActionRequestStatusLabel,
  formatPortalActionRequestTypeLabel,
} from '@/lib/portal-action-request-display';
import { portalClient, type PortalActionRequest } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatDate } from '@/lib/utils';

function PortalNotificationsContent() {
  const { t } = useLocale();
  const router = useRouter();
  const { session, isLoading: sessionLoading, isAuthenticated } = useSession();
  const [items, setItems] = useState<PortalActionRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSavingId, setIsSavingId] = useState('');
  const [error, setError] = useState<string | null>(null);

  const loadNotifications = useCallback(async () => {
    if (!session || !isAuthenticated) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await portalClient.listNotifications({ status: 'open', limit: 100 });
      setItems(response.data.items || []);
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated, session, t]);

  useEffect(() => {
    void loadNotifications();
  }, [loadNotifications]);

  useEffect(() => {
    if (!items.length) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadNotifications();
    }, 20000);
    return () => window.clearInterval(timer);
  }, [items.length, loadNotifications]);

  const handleAck = async (requestId: string) => {
    setIsSavingId(requestId);
    setError(null);
    try {
      await portalClient.acknowledgeNotification(requestId);
      setItems((current) => current.filter((item) => item.request_id !== requestId));
      router.refresh();
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setIsSavingId('');
    }
  };

  if (sessionLoading || isLoading) {
    return <PortalLoadingState message={t('common.loading')} />;
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('auth.not_signed_in')}
        description={t('auth.please_sign_in')}
        actionLabel={t('nav.sign_in')}
      />
    );
  }

  if (error && !items.length) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={error}
        retryLabel={t('common.retry')}
        onRetry={() => void loadNotifications()}
      />
    );
  }

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.nav_notifications', {}, 'To-dos')}
        title={t('portal.nav_notifications', {}, '待办')}
        eyebrowInfo={t(
          'portal.notifications.desc',
          {},
          '这里集中显示套餐申请、站点删除申请、用量预警、密钥到期和鉴权拦截等需要用户确认的事项。'
        )}
        currentPage="notifications"
        selectedSiteId={session.site_id}
        metrics={[
          {
            label: t('portal.notifications.open_count', {}, 'Open to-dos'),
            value: String(items.length),
            detail: t('portal.notifications.open_count_detail', {}, '仅显示当前用户可见且尚未处理的事项。'),
          },
        ]}
        metricsColumnsClassName="lg:grid-cols-1"
        primaryAction={
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadNotifications()}>
            {t('common.refresh')}
          </button>
        }
      />

      {error ? (
        <div className="rounded-[1.1rem] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
          {error}
        </div>
      ) : null}

      {items.length === 0 ? (
        <PortalEmptyState
          title={t('portal.notifications.empty_title', {}, '暂无待办')}
          description={t(
            'portal.notifications.empty_desc',
            {},
            '当前没有需要处理的申请、预警或诊断事项。后续如果触发套餐申请、站点删除申请或用量阈值，会显示在这里。'
          )}
          actionLabel={t('portal.workspace_label', {}, 'Workspace')}
          actionHref="/portal"
          diagnosticCode="portal.notifications.empty.open"
        />
      ) : (
        <section className="space-y-3">
          {items.map((item) => (
            <BackofficeStackCard key={item.request_id} className="bg-white/90 dark:bg-slate-950/45">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                      {formatPortalActionRequestTypeLabel(t, item.request_type)}
                    </span>
                    <BackofficeStatusBadge
                      label={formatPortalActionRequestStatusLabel(t, item.status)}
                      status={item.status}
                    />
                    <span className="text-xs text-slate-500 dark:text-slate-400">{formatDate(item.created_at)}</span>
                  </div>
                  <h2 className="mt-3 text-lg font-semibold text-slate-950 dark:text-white">{item.title}</h2>
                  {item.message ? (
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">{item.message}</p>
                  ) : null}
                  <PortalActionRequestResultStrip item={item} />
                  {item.site_id ? (
                    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                      {t('common.site')}: {item.site_id}
                    </p>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2 lg:justify-end">
                  {item.site_id ? (
                    <Link href={`/portal/sites?site=${item.site_id}`} className="btn btn-secondary btn-sm">
                      {t('portal.nav_sites', {}, 'Sites')}
                    </Link>
                  ) : null}
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={isSavingId === item.request_id}
                    onClick={() => void handleAck(item.request_id)}
                  >
                    {isSavingId === item.request_id
                      ? t('common.saving')
                      : t('portal.notifications.ack', {}, '标记已处理')}
                  </button>
                </div>
              </div>
            </BackofficeStackCard>
          ))}
        </section>
      )}
    </BackofficePageStack>
  );
}

export default function PortalNotificationsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalNotificationsContent />
    </Suspense>
  );
}
