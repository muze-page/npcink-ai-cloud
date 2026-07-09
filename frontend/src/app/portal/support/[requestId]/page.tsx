'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalSupportRequest,
  type PortalSupportRequestMessage,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatDate } from '@/lib/utils';

function statusTone(status: string): 'ok' | 'warning' | 'neutral' | 'danger' {
  if (status === 'open') return 'warning';
  if (status === 'resolved') return 'ok';
  return 'neutral';
}

function authorLabel(authorKind: string, t: ReturnType<typeof useLocale>['t']): string {
  if (authorKind === 'operator') return t('portal.support_message_author_operator', {}, 'Support');
  if (authorKind === 'system') return t('portal.support_message_author_system', {}, 'System');
  return t('portal.support_message_author_customer', {}, 'You');
}

export default function PortalSupportRequestDetailPage() {
  const params = useParams<{ requestId?: string }>();
  const requestId = String(params?.requestId || '');
  const { t } = useLocale();
  const { session, isLoading, isAuthenticated } = useSession();
  const [supportRequest, setSupportRequest] = useState<PortalSupportRequest | null>(null);
  const [messages, setMessages] = useState<PortalSupportRequestMessage[]>([]);
  const [reply, setReply] = useState('');
  const [isDetailLoading, setIsDetailLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadDetail = useCallback(async () => {
    if (!isAuthenticated || !requestId) {
      return;
    }
    setIsDetailLoading(true);
    setError('');
    try {
      const response = await portalClient.getSupportRequest(requestId);
      setSupportRequest(response.data.request);
      setMessages(response.data.messages || []);
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_load', {}, 'Failed to load')));
    } finally {
      setIsDetailLoading(false);
    }
  }, [isAuthenticated, requestId, t]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const handleReply = async () => {
    const body = reply.trim();
    if (!body) return;
    setIsSubmitting(true);
    setError('');
    setNotice('');
    try {
      const response = await portalClient.createSupportRequestMessage(requestId, { body });
      setSupportRequest(response.data.request);
      setMessages((current) => [...current, response.data.message]);
      setReply('');
      setNotice(t('portal.support_message_created', {}, 'Reply submitted.'));
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_save', {}, 'Failed to save')));
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading || isDetailLoading) {
    return <PortalLoadingState message={t('common.loading', {}, 'Loading...')} />;
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

  if (error && !supportRequest) {
    return (
      <PortalErrorState
        title={t('error.failed_load', {}, 'Failed to load')}
        description={error}
        retryLabel={t('common.retry', {}, 'Retry')}
        onRetry={() => void loadDetail()}
      />
    );
  }

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.workspace_label', {}, 'Portal')}
        title={supportRequest?.title || t('portal.support_request_detail_title', {}, 'Ticket detail')}
        description={supportRequest?.description || ''}
        currentPage="support"
        selectedSiteId={session.site_id || ''}
        sites={(session.sites || []).filter((site) => site.status !== 'archived')}
        actions={
          <Link className="btn btn-secondary" href="/portal/support">
            {t('common.back', {}, 'Back')}
          </Link>
        }
      />

      {notice ? (
        <div className="rounded-[1rem] border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200">
          {notice}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-[1rem] border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200">
          {error}
        </div>
      ) : null}

      {supportRequest ? (
        <BackofficeSectionPanel>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <BackofficeStatusBadge
                status={statusTone(supportRequest.status)}
                label={t(`portal.support_status_${supportRequest.status}`, {}, supportRequest.status)}
              />
              <span className="text-sm text-slate-500 dark:text-slate-400">
                {t(`portal.support_topic_${supportRequest.topic}`, {}, supportRequest.topic)}
              </span>
            </div>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {supportRequest.updated_at ? formatDate(supportRequest.updated_at) : supportRequest.request_id}
            </span>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      <BackofficeSectionPanel>
        <div className="space-y-3">
          {messages.map((message) => (
            <BackofficeStackCard
              key={message.message_id}
              variant="portal"
              className={message.author_kind === 'operator' ? 'bg-blue-50/70 dark:bg-blue-950/20' : 'bg-white/70 dark:bg-slate-950/35'}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-950 dark:text-white">
                  {authorLabel(message.author_kind, t)}
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {message.created_at ? formatDate(message.created_at) : message.message_id}
                </p>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700 dark:text-slate-200">
                {message.body}
              </p>
            </BackofficeStackCard>
          ))}
        </div>
      </BackofficeSectionPanel>

      <BackofficeSectionPanel>
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
          {t('portal.support_message_reply_label', {}, 'Reply')}
          <textarea
            className="input mt-2 min-h-32"
            value={reply}
            maxLength={4000}
            onChange={(event) => setReply(event.target.value)}
            placeholder={t('portal.support_message_reply_placeholder', {}, 'Add more details for support.')}
          />
        </label>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn btn-primary"
            disabled={isSubmitting || !reply.trim()}
            onClick={() => void handleReply()}
          >
            {isSubmitting ? t('common.saving', {}, 'Saving...') : t('portal.support_message_reply_action', {}, 'Send reply')}
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => void loadDetail()}>
            {t('common.refresh', {}, 'Refresh')}
          </button>
        </div>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}
