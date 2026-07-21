'use client';

import { Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
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
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ListPagination } from '@/components/ui/ListPagination';
import { Modal } from '@/components/ui/Modal';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalSupportRequest,
  type PortalSupportRequestStatus,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import {
  getPortalSiteDisplayName,
  getPortalSiteSecondaryLabel,
} from '@/lib/portal-site-display';
import { formatDate } from '@/lib/utils';

const SUPPORT_TOPICS = ['billing', 'payment', 'site', 'usage', 'account', 'general'] as const;
const SUPPORT_STATUSES: Array<PortalSupportRequestStatus | ''> = ['', 'open', 'in_progress', 'resolved', 'closed'];
const PAGE_SIZE = 10;

function statusTone(status: string): 'ok' | 'warning' | 'neutral' | 'danger' {
  if (status === 'open') return 'warning';
  if (status === 'in_progress') return 'neutral';
  if (status === 'resolved') return 'ok';
  if (status === 'closed') return 'neutral';
  return 'neutral';
}

function PortalSupportContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading, isAuthenticated } = useSession();
  const selectedContextSite = session?.selected_context?.site || null;
  const contextSiteId = selectedContextSite?.site_id || '';
  const initialTopic = String(searchParams?.get('topic') || 'general').toLowerCase();
  const initialSiteId = searchParams?.get('site') || '';
  const shouldOpenForm = searchParams?.get('new') === '1';
  const [items, setItems] = useState<PortalSupportRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<PortalSupportRequestStatus | ''>('');
  const [isListLoading, setIsListLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [showForm, setShowForm] = useState(shouldOpenForm);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [topic, setTopic] = useState(() =>
    SUPPORT_TOPICS.includes(initialTopic as (typeof SUPPORT_TOPICS)[number]) ? initialTopic : 'general'
  );
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [siteId, setSiteId] = useState('');
  const contextSiteIdRef = useRef(contextSiteId);
  const requestVersionRef = useRef(0);

  const loadRequests = useCallback(async () => {
    const requestContextSiteId = contextSiteIdRef.current;
    if (!isAuthenticated || !requestContextSiteId) return;
    const requestVersion = ++requestVersionRef.current;
    setIsListLoading(true);
    setError('');
    try {
      const response = await portalClient.listSupportRequests({
        status: statusFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      if (
        requestVersion !== requestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
      ) return;
      setItems(response.data.items || []);
      setTotal(Number(response.data.pagination?.total || 0));
    } catch (err) {
      if (
        requestVersion !== requestVersionRef.current
        || requestContextSiteId !== contextSiteIdRef.current
      ) return;
      setError(formatPortalErrorMessage(err, t, t('error.failed_load', {}, 'Failed to load')));
    } finally {
      if (
        requestVersion === requestVersionRef.current
        && requestContextSiteId === contextSiteIdRef.current
      ) setIsListLoading(false);
    }
  }, [isAuthenticated, offset, statusFilter, t]);

  useLayoutEffect(() => {
    const previousContextSiteId = contextSiteIdRef.current;
    contextSiteIdRef.current = contextSiteId;
    requestVersionRef.current += 1;
    setItems([]);
    setTotal(0);
    setOffset(0);
    setStatusFilter('');
    setError('');
    setNotice('');
    setIsListLoading(Boolean(isAuthenticated && contextSiteId));
    setIsSubmitting(false);
    setShowForm(Boolean(
      contextSiteId
      && shouldOpenForm
      && (!previousContextSiteId || previousContextSiteId === contextSiteId)
    ));
    setTopic(
      SUPPORT_TOPICS.includes(initialTopic as (typeof SUPPORT_TOPICS)[number])
        ? initialTopic
        : 'general'
    );
    setTitle('');
    setDescription('');
    setSiteId(initialSiteId === contextSiteId ? contextSiteId : '');
  }, [contextSiteId, initialSiteId, initialTopic, isAuthenticated, shouldOpenForm]);

  useEffect(() => {
    if (!isAuthenticated || !contextSiteId) return;
    void loadRequests();
    return () => {
      requestVersionRef.current += 1;
    };
  }, [contextSiteId, isAuthenticated, loadRequests]);

  const visibleSites = selectedContextSite ? [selectedContextSite] : [];
  const supportStatusRules = [
    {
      key: 'open',
      label: t('portal.support_rule_open', {}, 'Open tickets are waiting for support triage.'),
    },
    {
      key: 'in_progress',
      label: t('portal.support_rule_in_progress', {}, 'In-progress tickets are being checked by support.'),
    },
    {
      key: 'resolved',
      label: t('portal.support_rule_resolved', {}, 'Resolved tickets can receive your close evaluation.'),
    },
    {
      key: 'closed',
      label: t('portal.support_rule_closed', {}, 'If a closed issue is still not solved, reply with feedback or submit a new ticket.'),
    },
  ];

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

  if (!contextSiteId || !selectedContextSite) {
    return (
      <PortalPageStack>
        <PortalWorkspaceHeader
          eyebrow={t('portal.support_request_list_title', {}, 'Recent tickets')}
          title={t('portal.support_requests_title', {}, 'Tickets')}
          currentPage="support"
        />
        <PortalEmptyState
          title={t('portal.site_selection_required_title', {}, 'Select a site context')}
          description={t(
            'portal.site_selection_required_desc',
            {},
            'Choose a current site before viewing or creating support tickets.'
          )}
          actionLabel={t('portal.select_site_action', {}, 'Select site')}
          actionHref="/portal#sites"
        />
      </PortalPageStack>
    );
  }

  const handleSubmit = async () => {
    const requestContextSiteId = contextSiteIdRef.current;
    if (!isAuthenticated || !requestContextSiteId) return;
    setIsSubmitting(true);
    setError('');
    setNotice('');
    try {
      const response = await portalClient.createSupportRequest({
        topic,
        title,
        description,
        site_id: siteId === requestContextSiteId ? requestContextSiteId : '',
        source_path: '/portal/support',
        context: {
          source: 'portal_support_tab',
        },
      });
      if (requestContextSiteId !== contextSiteIdRef.current) return;
      setItems((current) => [response.data.request, ...current]);
      setTotal((current) => current + 1);
      setNotice(t('portal.support_request_created', {}, 'Ticket submitted.'));
      setTitle('');
      setDescription('');
      setShowForm(false);
    } catch (err) {
      if (requestContextSiteId !== contextSiteIdRef.current) return;
      setError(formatPortalErrorMessage(err, t, t('error.failed_save', {}, 'Failed to save')));
    } finally {
      if (requestContextSiteId === contextSiteIdRef.current) setIsSubmitting(false);
    }
  };

  return (
    <PortalPageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.support_request_list_title', {}, 'Recent tickets')}
        title={t('portal.support_requests_title', {}, 'Tickets')}
        description={t(
          'portal.support_requests_desc',
          {},
          'Send billing, site, usage, or account issues to the support queue.'
        )}
        currentPage="support"
        sites={visibleSites}
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
            {t('portal.support_request_new_action', {}, 'Submit ticket')}
          </button>
        }
      />

      {notice ? (
        <div className="rounded-[1rem] border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200">
          {notice}
        </div>
      ) : null}

      <Modal
        isOpen={showForm}
        onClose={() => setShowForm(false)}
        closeLabel={t('common.close', {}, 'Close')}
        size="lg"
        title={t('portal.support_request_form_title', {}, 'Submit ticket')}
        description={t(
          'portal.support_request_form_desc',
          {},
          'Include the affected page, order, or site so support can inspect the right Cloud record.'
        )}
      >
        <div data-portal-support="new-ticket-dialog">
          {error ? (
            <p className="mb-4 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950/30 dark:text-rose-200" role="alert">
              {error}
            </p>
          ) : null}
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('portal.support_request_topic', {}, 'Topic')}
              <select className="input mt-2" value={topic} onChange={(event) => setTopic(event.target.value)}>
                {SUPPORT_TOPICS.map((item) => (
                  <option key={item} value={item}>
                    {t(`portal.support_topic_${item}`, {}, item)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('portal.support_request_site', {}, 'Related site')}
              <select className="input mt-2" value={siteId} onChange={(event) => setSiteId(event.target.value)}>
                <option value="">{t('portal.support_request_no_site', {}, 'Account-level issue')}</option>
                {visibleSites.map((site) => (
                  <option key={site.site_id} value={site.site_id}>
                    {getPortalSiteDisplayName(site)} ({getPortalSiteSecondaryLabel(site)})
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="mt-4 block text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('portal.support_request_title_label', {}, 'Title')}
            <input
              className="input mt-2"
              value={title}
              maxLength={191}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t('portal.support_request_title_placeholder', {}, 'Payment order status looks wrong')}
            />
          </label>
          <label className="mt-4 block text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('portal.support_request_desc_label', {}, 'Description')}
            <textarea
              aria-describedby="portal-support-description-help"
              className="input mt-2 min-h-32"
              value={description}
              maxLength={4000}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t('portal.support_request_desc_placeholder', {}, 'Describe what happened and which page or order should be checked.')}
            />
          </label>
          <p id="portal-support-description-help" className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {t(
              'portal.support_request_desc_help',
              { count: String(description.trim().length) },
              'Enter at least 10 characters. Current length: {{count}}.'
            )}
          </p>
          <div className="mt-5 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={isSubmitting || !title.trim() || description.trim().length < 10}
              onClick={() => void handleSubmit()}
            >
              {isSubmitting ? t('common.saving', {}, 'Saving...') : t('portal.support_request_submit', {}, 'Submit')}
            </button>
            <button type="button" className="btn btn-secondary" disabled={isSubmitting} onClick={() => setShowForm(false)}>
              {t('common.cancel', {}, 'Cancel')}
            </button>
          </div>
        </div>
      </Modal>

      {error ? (
        <PortalErrorState
          title={t('error.failed_load', {}, 'Failed to load')}
          description={error}
          retryLabel={t('common.retry', {}, 'Retry')}
          onRetry={() => void loadRequests()}
        />
      ) : null}

      <PortalSection>
        <div className="mb-5">
          <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
            {t('portal.support_request_list_title', {}, 'Recent tickets')}
          </h2>
          <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t('portal.support_request_list_desc', {}, 'Open and in-progress tickets stay visible until support resolves them.')}
          </p>
        </div>
        <div className="mb-4 flex flex-wrap gap-2">
          {SUPPORT_STATUSES.map((status) => (
            <button
              key={status || 'all'}
              type="button"
              className={statusFilter === status ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
              aria-pressed={statusFilter === status}
              onClick={() => {
                setOffset(0);
                setStatusFilter(status);
              }}
            >
              {status ? t(`portal.support_status_${status}`, {}, status) : t('common.all', {}, 'All')}
            </button>
          ))}
        </div>

        {isListLoading ? (
          <LoadingFallback />
        ) : items.length ? (
          <div className="space-y-3">
            {items.map((item) => (
              <PortalCard key={item.request_id} variant="portal" className="bg-white/70 dark:bg-slate-950/35">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.title}</p>
                      <PortalStatusBadge
                        status={statusTone(item.status)}
                        label={t(`portal.support_status_${item.status}`, {}, item.status)}
                      />
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {item.description}
                    </p>
                    <Link
                      className="mt-3 inline-flex min-h-11 items-center text-sm font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200"
                      href={`/portal/support/${encodeURIComponent(item.request_id)}`}
                    >
                      {t('portal.support_request_view_detail', {}, 'View detail')}
                    </Link>
                  </div>
                  <div className="shrink-0 text-sm text-slate-500 dark:text-slate-400 lg:text-right">
                    <p>{t(`portal.support_topic_${item.topic}`, {}, item.topic)}</p>
                    <p className="mt-1">{item.updated_at ? formatDate(item.updated_at) : item.request_id}</p>
                  </div>
                </div>
              </PortalCard>
            ))}
          </div>
        ) : (
          <PortalEmptyState
            title={t('portal.support_request_empty_title', {}, 'No tickets yet')}
            description={t('portal.support_request_empty_desc', {}, 'Submit a ticket when package, payment, site, or usage information needs support review.')}
            actionButton={
              <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
                {t('portal.support_request_new_action', {}, 'Submit ticket')}
              </button>
            }
          />
        )}
        <ListPagination
          offset={offset}
          limit={PAGE_SIZE}
          total={total}
          isLoading={isListLoading}
          onOffsetChange={setOffset}
          className="mt-4 px-0 pb-0"
        />
      </PortalSection>

      <details className="rounded-[1rem] border border-slate-200/80 bg-white/70 dark:border-slate-800 dark:bg-slate-950/35" data-portal-support="status-rules">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-950 dark:text-white">
          {t('portal.support_status_rules_title', {}, 'Ticket status')}
        </summary>
        <div className="space-y-3 border-t border-slate-200/80 p-4 dark:border-slate-800">
          <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t(
              'portal.support_status_rules_desc',
              {},
              'Use tickets for package, payment, site, usage, or account issues; support updates the status as the issue moves.'
            )}
          </p>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {supportStatusRules.map((rule) => (
              <div key={rule.key} className="rounded-xl border border-slate-200 bg-white/70 px-3 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/35 dark:text-slate-300">
                <p className="font-semibold text-slate-950 dark:text-white">
                  {t(`portal.support_status_${rule.key}`, {}, rule.key)}
                </p>
                <p className="mt-1 text-xs leading-5">{rule.label}</p>
              </div>
            ))}
          </div>
        </div>
      </details>
    </PortalPageStack>
  );
}

export default function PortalSupportPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalSupportContent />
    </Suspense>
  );
}
