'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ListPagination } from '@/components/ui/ListPagination';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalSupportRequest,
  type PortalSupportRequestStatus,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
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
  const [siteId, setSiteId] = useState(initialSiteId);

  useEffect(() => {
    if (shouldOpenForm) {
      setShowForm(true);
    }
  }, [shouldOpenForm]);

  const loadRequests = useCallback(async () => {
    if (!isAuthenticated) {
      return;
    }
    setIsListLoading(true);
    setError('');
    try {
      const response = await portalClient.listSupportRequests({
        status: statusFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setItems(response.data.items || []);
      setTotal(Number(response.data.pagination?.total || 0));
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_load', {}, 'Failed to load')));
    } finally {
      setIsListLoading(false);
    }
  }, [isAuthenticated, offset, statusFilter, t]);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  const visibleSites = useMemo(
    () => (session?.sites || []).filter((site) => site.status !== 'archived'),
    [session?.sites]
  );
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

  const handleSubmit = async () => {
    setIsSubmitting(true);
    setError('');
    setNotice('');
    try {
      const response = await portalClient.createSupportRequest({
        topic,
        title,
        description,
        site_id: siteId,
        source_path: '/portal/support',
        context: {
          source: 'portal_support_tab',
        },
      });
      setItems((current) => [response.data.request, ...current]);
      setNotice(t('portal.support_request_created', {}, 'Ticket submitted.'));
      setTitle('');
      setDescription('');
      setShowForm(false);
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_save', {}, 'Failed to save')));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.workspace_label', {}, 'Portal')}
        title={t('portal.support_requests_title', {}, 'Tickets')}
        description={t(
          'portal.support_requests_desc',
          {},
          'Send billing, site, usage, or account issues to the support queue.'
        )}
        currentPage="support"
        sites={visibleSites}
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setShowForm((current) => !current)}>
            {showForm
              ? t('common.cancel', {}, 'Cancel')
              : t('portal.support_request_new_action', {}, 'Submit ticket')}
          </button>
        }
      />

      <BackofficeSectionPanel className="space-y-3" variant="portal" data-portal-support="status-rules">
        <div>
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.support_status_rules_title', {}, 'Ticket status')}
          </p>
          <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t(
              'portal.support_status_rules_desc',
              {},
              'Use tickets for package, payment, site, usage, or account issues; support updates the status as the issue moves.'
            )}
          </p>
        </div>
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
      </BackofficeSectionPanel>

      {notice ? (
        <div className="rounded-[1rem] border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200">
          {notice}
        </div>
      ) : null}

      {showForm ? (
        <BackofficeSectionPanel>
          <div className="mb-5">
            <p className="text-sm font-semibold text-slate-950 dark:text-white">
              {t('portal.support_request_form_title', {}, 'Submit ticket')}
            </p>
            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t(
                'portal.support_request_form_desc',
                {},
                'Include the affected page, order, or site so support can inspect the right Cloud record.'
              )}
            </p>
          </div>
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
                    {site.site_name || site.wordpress_url || site.site_id}
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
              className="input mt-2 min-h-32"
              value={description}
              maxLength={4000}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t('portal.support_request_desc_placeholder', {}, 'Describe what happened and which page or order should be checked.')}
            />
          </label>
          <div className="mt-5 flex flex-wrap gap-2">
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
        </BackofficeSectionPanel>
      ) : null}

      {error ? (
        <PortalErrorState
          title={t('error.failed_load', {}, 'Failed to load')}
          description={error}
          retryLabel={t('common.retry', {}, 'Retry')}
          onRetry={() => void loadRequests()}
        />
      ) : null}

      <BackofficeSectionPanel>
        <div className="mb-5">
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.support_request_list_title', {}, 'Recent tickets')}
          </p>
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
              <BackofficeStackCard key={item.request_id} variant="portal" className="bg-white/70 dark:bg-slate-950/35">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.title}</p>
                      <BackofficeStatusBadge
                        status={statusTone(item.status)}
                        label={t(`portal.support_status_${item.status}`, {}, item.status)}
                      />
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {item.description}
                    </p>
                    <Link
                      className="mt-3 inline-flex text-sm font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200"
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
              </BackofficeStackCard>
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
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function PortalSupportPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalSupportContent />
    </Suspense>
  );
}
