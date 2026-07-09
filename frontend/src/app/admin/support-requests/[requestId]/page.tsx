'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import {
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { readResponsePayload } from '@/lib/safe-response';
import { formatDate } from '@/lib/utils';

type SupportRequestStatus = 'open' | 'in_progress' | 'resolved' | 'closed';

type SupportRequest = {
  request_id: string;
  account_id: string;
  site_id?: string;
  principal_id?: string;
  email: string;
  topic: string;
  title: string;
  description: string;
  status: SupportRequestStatus;
  priority: string;
  admin_note?: string;
  created_at?: string;
  updated_at?: string;
};

type SupportRequestMessage = {
  message_id: string;
  request_id: string;
  author_kind: string;
  visibility: string;
  body: string;
  created_at?: string;
};

type SupportRequestDetailPayload = {
  request?: SupportRequest;
  messages?: SupportRequestMessage[];
};

const NEXT_STATUSES: SupportRequestStatus[] = ['open', 'in_progress', 'resolved', 'closed'];

function statusTone(status: string): string {
  if (status === 'open') return 'warning';
  if (status === 'resolved') return 'success';
  if (status === 'closed') return 'inactive';
  return 'read_only';
}

async function fetchSupportRequest(requestId: string): Promise<Response> {
  return fetch(`/api/admin/support-requests/${encodeURIComponent(requestId)}`, {
    credentials: 'include',
    cache: 'no-store',
  });
}

async function updateSupportRequest(requestId: string, status: string): Promise<Response> {
  return fetch(`/api/admin/support-requests/${encodeURIComponent(requestId)}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, admin_note: '' }),
  });
}

async function createSupportRequestMessage(
  requestId: string,
  body: string,
  visibility: 'public' | 'internal'
): Promise<Response> {
  return fetch(`/api/admin/support-requests/${encodeURIComponent(requestId)}/messages`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body, visibility }),
  });
}

function authorLabel(authorKind: string, visibility: string, t: ReturnType<typeof useLocale>['t']): string {
  if (visibility === 'internal') return t('admin.support_message_internal_note', {}, 'Internal note');
  if (authorKind === 'operator') return t('admin.support_message_author_operator', {}, 'Support');
  if (authorKind === 'system') return t('admin.support_message_author_system', {}, 'System');
  return t('admin.support_message_author_customer', {}, 'Customer');
}

export default function AdminSupportRequestDetailPage() {
  const params = useParams<{ requestId?: string }>();
  const requestId = String(params?.requestId || '');
  const { t } = useLocale();
  const [supportRequest, setSupportRequest] = useState<SupportRequest | null>(null);
  const [messages, setMessages] = useState<SupportRequestMessage[]>([]);
  const [statusDraft, setStatusDraft] = useState<SupportRequestStatus>('open');
  const [publicReply, setPublicReply] = useState('');
  const [internalNote, setInternalNote] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadDetail = useCallback(async () => {
    if (!requestId) return;
    setIsLoading(true);
    setError('');
    try {
      const response = await fetchSupportRequest(requestId);
      const payload = await readResponsePayload<{ data?: SupportRequestDetailPayload; message?: string }>(response);
      if (!response.ok || !('data' in payload) || !payload.data?.request) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
      }
      setSupportRequest(payload.data.request);
      setMessages(payload.data.messages || []);
      setStatusDraft(payload.data.request.status);
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [requestId, t]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const handleStatusUpdate = async () => {
    setPendingAction('status');
    setError('');
    setNotice('');
    try {
      const response = await updateSupportRequest(requestId, statusDraft);
      const payload = await readResponsePayload<{ data?: { request?: SupportRequest }; message?: string }>(response);
      if (!response.ok || !('data' in payload) || !payload.data?.request) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_save')));
      }
      setSupportRequest(payload.data.request);
      setNotice(t('admin.support_requests_updated_notice', {}, 'Ticket updated.'));
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setPendingAction('');
    }
  };

  const handleMessage = async (visibility: 'public' | 'internal') => {
    const body = (visibility === 'public' ? publicReply : internalNote).trim();
    if (!body) return;
    setPendingAction(visibility);
    setError('');
    setNotice('');
    try {
      const response = await createSupportRequestMessage(requestId, body, visibility);
      const payload = await readResponsePayload<{
        data?: { request?: SupportRequest; message?: SupportRequestMessage; notification?: { delivered?: boolean } };
        message?: string;
      }>(response);
      const responseData = 'data' in payload ? payload.data : undefined;
      const updatedRequest = responseData?.request;
      const createdMessage = responseData?.message;
      if (!response.ok || !updatedRequest || !createdMessage) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_save')));
      }
      setSupportRequest(updatedRequest);
      setStatusDraft(updatedRequest.status);
      setMessages((current) => [...current, createdMessage]);
      if (visibility === 'public') {
        setPublicReply('');
        setNotice(
          responseData?.notification?.delivered
            ? t('admin.support_message_public_sent', {}, 'Reply sent and customer notified.')
            : t('admin.support_message_public_saved', {}, 'Reply saved. Email notification was not delivered.')
        );
      } else {
        setInternalNote('');
        setNotice(t('admin.support_message_internal_saved', {}, 'Internal note saved.'));
      }
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setPendingAction('');
    }
  };

  if (isLoading) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.support_requests_eyebrow', {}, 'Customer support')}
        title={supportRequest?.title || t('admin.support_request_detail_title', {}, 'Ticket detail')}
        description={supportRequest?.description || ''}
        aside={
          supportRequest ? (
            <BackofficeStatusBadge
              status={statusTone(supportRequest.status)}
              label={t(`admin.support_status_${supportRequest.status}`, {}, supportRequest.status)}
            />
          ) : null
        }
        actions={
          <Link href="/admin/support-requests" className="btn btn-secondary">
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
          <div className="grid gap-3 text-sm text-slate-600 dark:text-slate-300 md:grid-cols-2 xl:grid-cols-4">
            <span>{supportRequest.email}</span>
            <span>{supportRequest.account_id}</span>
            <span>{supportRequest.site_id || t('portal.support_request_no_site', {}, 'Account-level issue')}</span>
            <span>{t(`portal.support_topic_${supportRequest.topic}`, {}, supportRequest.topic)}</span>
          </div>
        </BackofficeSectionPanel>
      ) : null}

      <BackofficeSectionPanel>
        <div className="space-y-3">
          {messages.map((message) => (
            <BackofficeStackCard
              key={message.message_id}
              className={message.visibility === 'internal' ? 'bg-amber-50/70 dark:bg-amber-950/20' : 'bg-white/80 dark:bg-slate-950/45'}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-slate-950 dark:text-white">
                  {authorLabel(message.author_kind, message.visibility, t)}
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

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <BackofficeSectionPanel>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('admin.support_message_public_reply', {}, 'Public reply')}
            <textarea
              className="input mt-2 min-h-32"
              value={publicReply}
              maxLength={4000}
              onChange={(event) => setPublicReply(event.target.value)}
              placeholder={t('admin.support_message_public_placeholder', {}, 'Reply to the customer.')}
            />
          </label>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={pendingAction === 'public' || !publicReply.trim()}
              onClick={() => void handleMessage('public')}
            >
              {pendingAction === 'public'
                ? t('common.saving', {}, 'Saving...')
                : t('admin.support_message_public_action', {}, 'Send public reply')}
            </button>
          </div>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('admin.support_request_status_label', {}, 'Status')}
            <select
              className="input mt-2"
              value={statusDraft}
              onChange={(event) => setStatusDraft(event.target.value as SupportRequestStatus)}
            >
              {NEXT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {t(`admin.support_status_${status}`, {}, status)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-secondary mt-3 w-full"
            disabled={pendingAction === 'status'}
            onClick={() => void handleStatusUpdate()}
          >
            {pendingAction === 'status'
              ? t('common.saving', {}, 'Saving...')
              : t('admin.support_request_status_action', {}, 'Update status')}
          </button>

          <label className="mt-5 block text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('admin.support_message_internal_note', {}, 'Internal note')}
            <textarea
              className="input mt-2 min-h-28"
              value={internalNote}
              maxLength={4000}
              onChange={(event) => setInternalNote(event.target.value)}
              placeholder={t('admin.support_message_internal_placeholder', {}, 'Visible only to admins.')}
            />
          </label>
          <button
            type="button"
            className="btn btn-secondary mt-3 w-full"
            disabled={pendingAction === 'internal' || !internalNote.trim()}
            onClick={() => void handleMessage('internal')}
          >
            {pendingAction === 'internal'
              ? t('common.saving', {}, 'Saving...')
              : t('admin.support_message_internal_action', {}, 'Save internal note')}
          </button>
        </BackofficeSectionPanel>
      </div>
    </BackofficePageStack>
  );
}
