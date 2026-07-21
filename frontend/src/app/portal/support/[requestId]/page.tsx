'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  PortalPageStack,
  PortalSection,
  PortalCard,
} from '@/components/portal/PortalScaffold';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import {
  PortalEmptyState,
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
  type PortalSupportRequestAttachment,
  type PortalSupportRequestFeedback,
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

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || '').split(',', 2)[1] || '');
    reader.onerror = () => reject(reader.error || new Error('failed to read file'));
    reader.readAsDataURL(file);
  });
}

function downloadAttachmentFile(attachment: PortalSupportRequestAttachment): void {
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

export default function PortalSupportRequestDetailPage() {
  const params = useParams<{ requestId?: string }>();
  const requestId = String(params?.requestId || '');
  const { t } = useLocale();
  const { session, isLoading, isAuthenticated } = useSession();
  const contextSiteId = session?.selected_context?.site.site_id || '';
  const [supportRequest, setSupportRequest] = useState<PortalSupportRequest | null>(null);
  const [messages, setMessages] = useState<PortalSupportRequestMessage[]>([]);
  const [attachments, setAttachments] = useState<PortalSupportRequestAttachment[]>([]);
  const [feedback, setFeedback] = useState<PortalSupportRequestFeedback | null>(null);
  const [reply, setReply] = useState('');
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [feedbackResolved, setFeedbackResolved] = useState(true);
  const [feedbackRating, setFeedbackRating] = useState(5);
  const [feedbackComment, setFeedbackComment] = useState('');
  const [isDetailLoading, setIsDetailLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isUploadingAttachment, setIsUploadingAttachment] = useState(false);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const contextSiteIdRef = useRef(contextSiteId);
  const requestIdRef = useRef(requestId);
  const contextRequestVersionRef = useRef(0);
  const detailRequestVersionRef = useRef(0);

  const loadDetail = useCallback(async () => {
    const requestContextSiteId = contextSiteIdRef.current;
    const capturedRequestId = requestIdRef.current;
    if (!isAuthenticated || !requestContextSiteId || !capturedRequestId) return;
    const contextRequestVersion = contextRequestVersionRef.current;
    const detailRequestVersion = ++detailRequestVersionRef.current;
    setIsDetailLoading(true);
    setError('');
    try {
      const response = await portalClient.getSupportRequest(capturedRequestId);
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || detailRequestVersion !== detailRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setSupportRequest(response.data.request);
      setMessages(response.data.messages || []);
      setAttachments(response.data.attachments || []);
      setFeedback(response.data.feedback || null);
      if (response.data.feedback) {
        setFeedbackResolved(response.data.feedback.resolved);
        setFeedbackRating(response.data.feedback.rating || 5);
        setFeedbackComment(response.data.feedback.comment || '');
      }
    } catch (err) {
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || detailRequestVersion !== detailRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setError(formatPortalErrorMessage(err, t, t('error.failed_load', {}, 'Failed to load')));
    } finally {
      if (
        contextRequestVersion === contextRequestVersionRef.current
        && detailRequestVersion === detailRequestVersionRef.current
        && requestContextSiteId === contextSiteIdRef.current
        && capturedRequestId === requestIdRef.current
      ) setIsDetailLoading(false);
    }
  }, [isAuthenticated, t]);

  useLayoutEffect(() => {
    contextSiteIdRef.current = contextSiteId;
    requestIdRef.current = requestId;
    contextRequestVersionRef.current += 1;
    detailRequestVersionRef.current += 1;
    setSupportRequest(null);
    setMessages([]);
    setAttachments([]);
    setFeedback(null);
    setReply('');
    setAttachmentFile(null);
    setFeedbackResolved(true);
    setFeedbackRating(5);
    setFeedbackComment('');
    setIsDetailLoading(Boolean(isAuthenticated && contextSiteId && requestId));
    setIsSubmitting(false);
    setIsUploadingAttachment(false);
    setIsSubmittingFeedback(false);
    setError('');
    setNotice('');
  }, [contextSiteId, isAuthenticated, requestId]);

  useEffect(() => {
    if (!isAuthenticated || !contextSiteId || !requestId) return;
    void loadDetail();
    return () => {
      detailRequestVersionRef.current += 1;
    };
  }, [contextSiteId, isAuthenticated, loadDetail, requestId]);

  const handleReply = async () => {
    const requestContextSiteId = contextSiteIdRef.current;
    const capturedRequestId = requestIdRef.current;
    const contextRequestVersion = contextRequestVersionRef.current;
    if (
      !contextSiteId
      || !requestContextSiteId
      || contextSiteId !== requestContextSiteId
      || !capturedRequestId
    ) return;
    const body = reply.trim();
    if (!body) return;
    setIsSubmitting(true);
    setError('');
    setNotice('');
    try {
      const response = await portalClient.createSupportRequestMessage(capturedRequestId, { body });
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setSupportRequest(response.data.request);
      setMessages((current) => [...current, response.data.message]);
      setReply('');
      setNotice(t('portal.support_message_created', {}, 'Reply submitted.'));
    } catch (err) {
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setError(formatPortalErrorMessage(err, t, t('error.failed_save', {}, 'Failed to save')));
    } finally {
      if (
        contextRequestVersion === contextRequestVersionRef.current
        && requestContextSiteId === contextSiteIdRef.current
        && capturedRequestId === requestIdRef.current
      ) setIsSubmitting(false);
    }
  };

  const handleAttachmentUpload = async () => {
    const requestContextSiteId = contextSiteIdRef.current;
    const capturedRequestId = requestIdRef.current;
    const contextRequestVersion = contextRequestVersionRef.current;
    if (
      !contextSiteId
      || !requestContextSiteId
      || contextSiteId !== requestContextSiteId
      || !capturedRequestId
    ) return;
    if (!attachmentFile) return;
    setIsUploadingAttachment(true);
    setError('');
    setNotice('');
    try {
      const contentBase64 = await readFileAsBase64(attachmentFile);
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      const response = await portalClient.createSupportRequestAttachment(capturedRequestId, {
        filename: attachmentFile.name,
        content_type: attachmentFile.type || 'application/octet-stream',
        content_base64: contentBase64,
      });
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setSupportRequest(response.data.request);
      setAttachments((current) => [...current, response.data.attachment]);
      setAttachmentFile(null);
      setNotice(t('portal.support_attachment_created', {}, 'Attachment uploaded.'));
    } catch (err) {
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setError(formatPortalErrorMessage(err, t, t('error.failed_save', {}, 'Failed to save')));
    } finally {
      if (
        contextRequestVersion === contextRequestVersionRef.current
        && requestContextSiteId === contextSiteIdRef.current
        && capturedRequestId === requestIdRef.current
      ) setIsUploadingAttachment(false);
    }
  };

  const handleAttachmentDownload = async (attachment: PortalSupportRequestAttachment) => {
    const requestContextSiteId = contextSiteIdRef.current;
    const capturedRequestId = requestIdRef.current;
    const contextRequestVersion = contextRequestVersionRef.current;
    if (
      !contextSiteId
      || !requestContextSiteId
      || contextSiteId !== requestContextSiteId
      || !capturedRequestId
    ) return;
    setError('');
    try {
      const response = await portalClient.getSupportRequestAttachment(
        capturedRequestId,
        attachment.attachment_id
      );
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      downloadAttachmentFile(response.data.attachment);
    } catch (err) {
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setError(formatPortalErrorMessage(err, t, t('error.failed_load', {}, 'Failed to load')));
    }
  };

  const handleFeedbackSubmit = async () => {
    const requestContextSiteId = contextSiteIdRef.current;
    const capturedRequestId = requestIdRef.current;
    const contextRequestVersion = contextRequestVersionRef.current;
    if (
      !contextSiteId
      || !requestContextSiteId
      || contextSiteId !== requestContextSiteId
      || !capturedRequestId
    ) return;
    setIsSubmittingFeedback(true);
    setError('');
    setNotice('');
    try {
      const response = await portalClient.submitSupportRequestFeedback(capturedRequestId, {
        resolved: feedbackResolved,
        rating: feedbackRating,
        comment: feedbackComment,
      });
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setSupportRequest(response.data.request);
      setFeedback(response.data.feedback);
      setNotice(t('portal.support_feedback_submitted', {}, 'Feedback submitted.'));
    } catch (err) {
      if (
        contextRequestVersion !== contextRequestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
        || capturedRequestId !== requestIdRef.current
      ) return;
      setError(formatPortalErrorMessage(err, t, t('error.failed_save', {}, 'Failed to save')));
    } finally {
      if (
        contextRequestVersion === contextRequestVersionRef.current
        && requestContextSiteId === contextSiteIdRef.current
        && capturedRequestId === requestIdRef.current
      ) setIsSubmittingFeedback(false);
    }
  };

  if (isLoading) {
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

  if (!contextSiteId || !session.selected_context) {
    return (
      <PortalPageStack>
        <PortalWorkspaceHeader
          eyebrow={t('portal.support_requests_title', {}, 'Tickets')}
          title={t('portal.support_request_detail_title', {}, 'Ticket detail')}
          currentPage="support"
        />
        <PortalEmptyState
          title={t('portal.site_selection_required_title', {}, 'Select a site context')}
          description={t(
            'portal.site_selection_required_desc',
            {},
            'Choose a current site before viewing this support ticket.'
          )}
          actionLabel={t('portal.select_site_action', {}, 'Select site')}
          actionHref="/portal#sites"
        />
      </PortalPageStack>
    );
  }

  if (isDetailLoading) {
    return <PortalLoadingState message={t('common.loading', {}, 'Loading...')} />;
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
    <PortalPageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.support_requests_title', {}, 'Tickets')}
        title={supportRequest?.title || t('portal.support_request_detail_title', {}, 'Ticket detail')}
        description={supportRequest?.description || ''}
        currentPage="support"
        sites={[session.selected_context.site]}
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
        <PortalSection>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <PortalStatusBadge
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
        </PortalSection>
      ) : null}

      <PortalSection>
        <div className="space-y-3">
          {messages.map((message) => (
            <PortalCard
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
            </PortalCard>
          ))}
        </div>
      </PortalSection>

      <PortalSection>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.support_attachments_title', {}, 'Attachments')}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('portal.support_attachment_limit', {}, 'PDF, image, text, CSV, or JSON. Max 5 MB each.')}
          </p>
        </div>
        {attachments.length ? (
          <div className="mb-4 divide-y divide-slate-200 rounded-2xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {attachments.map((attachment) => (
              <div key={attachment.attachment_id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">{attachment.filename}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
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
        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          <label className="flex-1 text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('portal.support_attachment_choose_label', {}, 'Choose attachment')}
            <input
              className="input mt-2"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.csv,.json,application/pdf,image/png,image/jpeg,image/webp,image/gif,text/plain,text/csv,application/json"
              onChange={(event) => setAttachmentFile(event.target.files?.[0] || null)}
            />
          </label>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={isUploadingAttachment || !attachmentFile}
            onClick={() => void handleAttachmentUpload()}
          >
            {isUploadingAttachment
              ? t('common.saving', {}, 'Saving...')
              : t('portal.support_attachment_upload_action', {}, 'Upload attachment')}
          </button>
        </div>
      </PortalSection>

      <PortalSection>
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
      </PortalSection>

      {supportRequest?.status === 'resolved' || supportRequest?.status === 'closed' ? (
        <PortalSection>
          <div className="mb-4">
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('portal.support_feedback_title', {}, 'Close evaluation')}
            </p>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t('portal.support_feedback_desc', {}, 'Confirm whether the issue is resolved. If not, the ticket will reopen.')}
            </p>
          </div>
          {feedback ? (
            <div className="mb-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200">
              {t('portal.support_feedback_existing', {}, 'Feedback has been submitted. You can update it if needed.')}
            </div>
          ) : null}
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('portal.support_feedback_resolved_label', {}, 'Issue status')}
              <select
                className="input mt-2"
                value={feedbackResolved ? 'yes' : 'no'}
                onChange={(event) => setFeedbackResolved(event.target.value === 'yes')}
              >
                <option value="yes">{t('portal.support_feedback_resolved_yes', {}, 'Resolved')}</option>
                <option value="no">{t('portal.support_feedback_resolved_no', {}, 'Not resolved')}</option>
              </select>
            </label>
            <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('portal.support_feedback_rating_label', {}, 'Rating')}
              <select
                className="input mt-2"
                value={feedbackRating}
                onChange={(event) => setFeedbackRating(Number(event.target.value))}
              >
                {[5, 4, 3, 2, 1].map((rating) => (
                  <option key={rating} value={rating}>
                    {rating}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <textarea
            className="input mt-4 min-h-24"
            value={feedbackComment}
            maxLength={2000}
            onChange={(event) => setFeedbackComment(event.target.value)}
            placeholder={t('portal.support_feedback_comment_placeholder', {}, 'Optional note for support.')}
          />
          <button
            type="button"
            className="btn btn-primary mt-4"
            disabled={isSubmittingFeedback}
            onClick={() => void handleFeedbackSubmit()}
          >
            {isSubmittingFeedback
              ? t('common.saving', {}, 'Saving...')
              : t('portal.support_feedback_submit_action', {}, 'Submit evaluation')}
          </button>
        </PortalSection>
      ) : null}
    </PortalPageStack>
  );
}
