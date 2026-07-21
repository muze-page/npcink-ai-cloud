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
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';
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

type SupportRequestAttachment = {
  attachment_id: string;
  request_id: string;
  uploader_kind: string;
  visibility: string;
  filename: string;
  content_type: string;
  byte_size: number;
  content_base64?: string;
  created_at?: string;
};

type SupportRequestFeedback = {
  feedback_id: string;
  request_id: string;
  resolved: boolean;
  rating: number;
  comment?: string;
  created_at?: string;
};

type SupportRequestDetailPayload = {
  request?: SupportRequest;
  messages?: SupportRequestMessage[];
  attachments?: SupportRequestAttachment[];
  feedback?: SupportRequestFeedback | null;
};

const NEXT_STATUSES: SupportRequestStatus[] = ['open', 'in_progress', 'resolved', 'closed'];
const supportRequestDetailClient = createApiClient({
  cache: 'default',
  idempotencyPrefix: 'admin_support_request_detail',
});

function statusTone(status: string): string {
  if (status === 'open') return 'warning';
  if (status === 'resolved') return 'success';
  if (status === 'closed') return 'inactive';
  return 'read_only';
}

async function fetchSupportRequest(requestId: string): Promise<SupportRequestDetailPayload> {
  return (await supportRequestDetailClient.request<SupportRequestDetailPayload>(
    `/api/admin/support-requests/${encodeURIComponent(requestId)}`,
    { cache: 'no-store' }
  )).data;
}

async function updateSupportRequest(
  requestId: string,
  status: string
): Promise<{ request?: SupportRequest }> {
  return (await supportRequestDetailClient.request<{ request?: SupportRequest }>(
    `/api/admin/support-requests/${encodeURIComponent(requestId)}`,
    {
      method: 'PATCH',
      body: { status, admin_note: '' },
    }
  )).data;
}

async function createSupportRequestMessage(
  requestId: string,
  body: string,
  visibility: 'public' | 'internal'
): Promise<{
  request?: SupportRequest;
  message?: SupportRequestMessage;
  notification?: { delivered?: boolean };
}> {
  return (await supportRequestDetailClient.request<{
    request?: SupportRequest;
    message?: SupportRequestMessage;
    notification?: { delivered?: boolean };
  }>(`/api/admin/support-requests/${encodeURIComponent(requestId)}/messages`, {
    method: 'POST',
    body: { body, visibility },
  })).data;
}

async function createSupportRequestAttachment(
  requestId: string,
  payload: {
    filename: string;
    content_type: string;
    content_base64: string;
    visibility: 'public' | 'internal';
  }
): Promise<{ request?: SupportRequest; attachment?: SupportRequestAttachment }> {
  return (await supportRequestDetailClient.request<{
    request?: SupportRequest;
    attachment?: SupportRequestAttachment;
  }>(`/api/admin/support-requests/${encodeURIComponent(requestId)}/attachments`, {
    method: 'POST',
    body: payload,
  })).data;
}

async function fetchSupportRequestAttachment(
  requestId: string,
  attachmentId: string
): Promise<{ attachment?: SupportRequestAttachment }> {
  return (await supportRequestDetailClient.request<{ attachment?: SupportRequestAttachment }>(
    `/api/admin/support-requests/${encodeURIComponent(requestId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { cache: 'no-store' }
  )).data;
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || '').split(',', 2)[1] || '');
    reader.onerror = () => reject(reader.error || new Error('failed to read file'));
    reader.readAsDataURL(file);
  });
}

function downloadAttachmentFile(attachment: SupportRequestAttachment): void {
  if (!attachment.content_base64) return;
  const binary = atob(attachment.content_base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const url = URL.createObjectURL(new Blob([bytes], { type: attachment.content_type || 'application/octet-stream' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = attachment.filename || 'support-attachment';
  anchor.click();
  URL.revokeObjectURL(url);
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
  const [attachments, setAttachments] = useState<SupportRequestAttachment[]>([]);
  const [feedback, setFeedback] = useState<SupportRequestFeedback | null>(null);
  const [statusDraft, setStatusDraft] = useState<SupportRequestStatus>('open');
  const [publicReply, setPublicReply] = useState('');
  const [internalNote, setInternalNote] = useState('');
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [attachmentVisibility, setAttachmentVisibility] = useState<'public' | 'internal'>('public');
  const [isLoading, setIsLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadDetail = useCallback(async () => {
    if (!requestId) return;
    setIsLoading(true);
    setError('');
    try {
      const data = await fetchSupportRequest(requestId);
      if (!data.request) {
        throw new Error(t('error.failed_load'));
      }
      setSupportRequest(data.request);
      setMessages(data.messages || []);
      setAttachments(data.attachments || []);
      setFeedback(data.feedback || null);
      setStatusDraft(data.request.status);
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
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
      const data = await updateSupportRequest(requestId, statusDraft);
      if (!data.request) {
        throw new Error(t('error.failed_save'));
      }
      setSupportRequest(data.request);
      setNotice(t('admin.support_requests_updated_notice', {}, 'Ticket updated.'));
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_save')));
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
      const data = await createSupportRequestMessage(requestId, body, visibility);
      const updatedRequest = data.request;
      const createdMessage = data.message;
      if (!updatedRequest || !createdMessage) {
        throw new Error(t('error.failed_save'));
      }
      setSupportRequest(updatedRequest);
      setStatusDraft(updatedRequest.status);
      setMessages((current) => [...current, createdMessage]);
      if (visibility === 'public') {
        setPublicReply('');
        setNotice(
          data.notification?.delivered
            ? t('admin.support_message_public_sent', {}, 'Reply sent and customer notified.')
            : t('admin.support_message_public_saved', {}, 'Reply saved. Email notification was not delivered.')
        );
      } else {
        setInternalNote('');
        setNotice(t('admin.support_message_internal_saved', {}, 'Internal note saved.'));
      }
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_save')));
    } finally {
      setPendingAction('');
    }
  };

  const handleAttachmentUpload = async () => {
    if (!attachmentFile) return;
    setPendingAction('attachment');
    setError('');
    setNotice('');
    try {
      const contentBase64 = await readFileAsBase64(attachmentFile);
      const data = await createSupportRequestAttachment(requestId, {
        filename: attachmentFile.name,
        content_type: attachmentFile.type || 'application/octet-stream',
        content_base64: contentBase64,
        visibility: attachmentVisibility,
      });
      if (!data.request || !data.attachment) {
        throw new Error(t('error.failed_save'));
      }
      setSupportRequest(data.request);
      setAttachments((current) => [...current, data.attachment as SupportRequestAttachment]);
      setAttachmentFile(null);
      setNotice(t('admin.support_attachment_created', {}, 'Attachment uploaded.'));
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_save')));
    } finally {
      setPendingAction('');
    }
  };

  const handleAttachmentDownload = async (attachment: SupportRequestAttachment) => {
    setError('');
    try {
      const data = await fetchSupportRequestAttachment(requestId, attachment.attachment_id);
      if (!data.attachment) {
        throw new Error(t('error.failed_load'));
      }
      downloadAttachmentFile(data.attachment);
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
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

      <BackofficeSectionPanel>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('admin.support_attachments_title', {}, 'Attachments')}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('admin.support_attachment_limit', {}, 'PDF, image, text, CSV, or JSON. Max 5 MB each.')}
          </p>
        </div>
        {attachments.length ? (
          <div className="mb-4 divide-y divide-slate-200 rounded-2xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {attachments.map((attachment) => (
              <div key={attachment.attachment_id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-slate-950 dark:text-white">{attachment.filename}</p>
                    <BackofficeStatusBadge
                      status={attachment.visibility === 'internal' ? 'warning' : 'read_only'}
                      label={
                        attachment.visibility === 'internal'
                          ? t('admin.support_attachment_internal', {}, 'Internal')
                          : t('admin.support_attachment_public', {}, 'Public')
                      }
                    />
                  </div>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {attachment.content_type} · {Math.ceil((attachment.byte_size || 0) / 1024)} KB
                  </p>
                </div>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => void handleAttachmentDownload(attachment)}>
                  {t('common.download', {}, 'Download')}
                </button>
              </div>
            ))}
          </div>
        ) : null}
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_12rem_auto] md:items-center">
          <input
            className="input"
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.csv,.json,application/pdf,image/png,image/jpeg,image/webp,image/gif,text/plain,text/csv,application/json"
            onChange={(event) => setAttachmentFile(event.target.files?.[0] || null)}
          />
          <select
            className="input"
            value={attachmentVisibility}
            onChange={(event) => setAttachmentVisibility(event.target.value as 'public' | 'internal')}
          >
            <option value="public">{t('admin.support_attachment_public', {}, 'Public')}</option>
            <option value="internal">{t('admin.support_attachment_internal', {}, 'Internal')}</option>
          </select>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={pendingAction === 'attachment' || !attachmentFile}
            onClick={() => void handleAttachmentUpload()}
          >
            {pendingAction === 'attachment'
              ? t('common.saving', {}, 'Saving...')
              : t('admin.support_attachment_upload_action', {}, 'Upload')}
          </button>
        </div>
      </BackofficeSectionPanel>

      {feedback ? (
        <BackofficeSectionPanel>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-slate-950 dark:text-white">
                {t('admin.support_feedback_title', {}, 'Close evaluation')}
              </p>
              <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {feedback.comment || t('admin.support_feedback_no_comment', {}, 'No comment provided.')}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <BackofficeStatusBadge
                status={feedback.resolved ? 'success' : 'warning'}
                label={
                  feedback.resolved
                    ? t('admin.support_feedback_resolved', {}, 'Resolved')
                    : t('admin.support_feedback_unresolved', {}, 'Not resolved')
                }
              />
              <BackofficeStatusBadge
                status="read_only"
                label={t(
                  'admin.support_feedback_rating_value',
                  { rating: String(feedback.rating) },
                  '{{rating}}/5'
                )}
              />
            </div>
          </div>
        </BackofficeSectionPanel>
      ) : null}

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
