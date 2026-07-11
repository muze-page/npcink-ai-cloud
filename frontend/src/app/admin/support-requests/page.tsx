'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ListPagination } from '@/components/ui/ListPagination';
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

type SupportRequestListPayload = {
  items?: SupportRequest[];
  pagination?: {
    total?: number;
    limit?: number;
    offset?: number;
    has_more?: boolean;
  };
  summary?: {
    open?: number;
    in_progress?: number;
  };
};

const STATUS_FILTERS: Array<SupportRequestStatus | ''> = ['', 'open', 'in_progress', 'resolved', 'closed'];
const NEXT_STATUSES: SupportRequestStatus[] = ['open', 'in_progress', 'resolved', 'closed'];
const TOPIC_FILTERS = ['', 'billing', 'payment', 'site', 'usage', 'account', 'general'] as const;
const PAGE_SIZE = 20;

function statusTone(status: string): string {
  if (status === 'open') return 'warning';
  if (status === 'resolved') return 'success';
  if (status === 'closed') return 'inactive';
  return 'read_only';
}

async function fetchSupportRequests(status: string, topic: string, query: string, offset: number): Promise<Response> {
  const params = new URLSearchParams();
  params.set('limit', String(PAGE_SIZE));
  if (offset > 0) params.set('offset', String(offset));
  if (status) params.set('status', status);
  if (topic) params.set('topic', topic);
  if (query.trim()) params.set('q', query.trim());
  return fetch(`/api/admin/support-requests?${params.toString()}`, {
    credentials: 'include',
    cache: 'no-store',
  });
}

async function updateSupportRequest(requestId: string, status: string, adminNote: string): Promise<Response> {
  return fetch(`/api/admin/support-requests/${encodeURIComponent(requestId)}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, admin_note: adminNote }),
  });
}

export default function AdminSupportRequestsPage() {
  const { t } = useLocale();
  const [items, setItems] = useState<SupportRequest[]>([]);
  const [summary, setSummary] = useState<SupportRequestListPayload['summary']>({});
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<SupportRequestStatus | ''>('open');
  const [topicFilter, setTopicFilter] = useState('');
  const [query, setQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pendingRequestId, setPendingRequestId] = useState('');
  const [statusDrafts, setStatusDrafts] = useState<Record<string, string>>({});
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});

  const loadRequests = useCallback(async () => {
    setIsLoading(true);
    setError('');
    try {
      const response = await fetchSupportRequests(statusFilter, topicFilter, query, offset);
      const payload = await readResponsePayload<{ data?: SupportRequestListPayload; message?: string }>(response);
      if (!response.ok || !('data' in payload) || !payload.data) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
      }
      setItems(payload.data.items || []);
      setSummary(payload.data.summary || {});
      setTotal(Number(payload.data.pagination?.total || 0));
      setStatusDrafts(
        Object.fromEntries((payload.data.items || []).map((item) => [item.request_id, item.status]))
      );
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [offset, query, statusFilter, topicFilter, t]);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  const openCount = Number(summary?.open || 0);
  const inProgressCount = Number(summary?.in_progress || 0);
  const hasActiveQueue = useMemo(() => openCount + inProgressCount > 0, [inProgressCount, openCount]);

  const handleUpdate = async (item: SupportRequest) => {
    setPendingRequestId(item.request_id);
    setError('');
    setNotice('');
    try {
      const response = await updateSupportRequest(
        item.request_id,
        statusDrafts[item.request_id] || item.status,
        noteDrafts[item.request_id] || ''
      );
      const payload = await readResponsePayload<{ data?: { request?: SupportRequest }; message?: string }>(response);
      if (!response.ok || !('data' in payload) || !payload.data?.request) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_save')));
      }
      setNotice(t('admin.support_requests_updated_notice', {}, 'Ticket updated.'));
      await loadRequests();
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setPendingRequestId('');
    }
  };

  if (isLoading) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.support_requests_eyebrow', {}, 'Customer support')}
        title={t('admin.support_requests_title', {}, 'Tickets')}
        description={t(
          'admin.support_requests_desc',
          {},
          'Handle Portal-submitted billing, site, usage, and account questions from one Cloud-owned queue.'
        )}
        aside={
          <BackofficeStatusBadge
            status={hasActiveQueue ? 'warning' : 'success'}
            label={hasActiveQueue ? t('common.attention', {}, 'Attention') : t('common.ok', {}, 'OK')}
          />
        }
        actions={
          <button type="button" className="btn btn-secondary" onClick={() => void loadRequests()}>
            {t('common.refresh', {}, 'Refresh')}
          </button>
        }
        summary={
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-3"
            items={[
              { label: t('admin.support_requests_open', {}, 'Open'), value: openCount },
              { label: t('admin.support_requests_in_progress', {}, 'In progress'), value: inProgressCount },
              { label: t('admin.support_requests_total', {}, 'Filtered total'), value: total },
            ]}
          />
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

      <BackofficeSectionPanel>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {STATUS_FILTERS.map((status) => (
              <button
                key={status || 'all'}
                type="button"
                className={statusFilter === status ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
                onClick={() => {
                  setOffset(0);
                  setStatusFilter(status);
                }}
              >
                {status ? t(`admin.support_status_${status}`, {}, status) : t('common.all', {}, 'All')}
              </button>
            ))}
          </div>
          <div className="flex w-full flex-col gap-2 lg:w-auto lg:flex-row">
            <select
              className="input lg:w-44"
              value={topicFilter}
              onChange={(event) => {
                setOffset(0);
                setTopicFilter(event.target.value);
              }}
            >
              {TOPIC_FILTERS.map((topic) => (
                <option key={topic || 'all'} value={topic}>
                  {topic ? t(`portal.support_topic_${topic}`, {}, topic) : t('admin.support_topic_all', {}, 'All topics')}
                </option>
              ))}
            </select>
            <input
              className="input w-full lg:w-80"
              value={query}
              onChange={(event) => {
                setOffset(0);
                setQuery(event.target.value);
              }}
              placeholder={t('admin.support_requests_search_placeholder', {}, 'Email, site, account, or title')}
            />
          </div>
        </div>
      </BackofficeSectionPanel>

      {items.length ? (
        <div className="space-y-3">
          {items.map((item) => (
            <BackofficeStackCard key={item.request_id} className="bg-white/80 dark:bg-slate-950/45">
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-slate-950 dark:text-white">{item.title}</p>
                    <BackofficeStatusBadge
                      status={statusTone(item.status)}
                      label={t(`admin.support_status_${item.status}`, {}, item.status)}
                    />
                  </div>
                  <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{item.description}</p>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                    <span>{item.email}</span>
                    <span>{item.account_id}</span>
                    {item.site_id ? <span>{item.site_id}</span> : null}
                    <span>{t(`portal.support_topic_${item.topic}`, {}, item.topic)}</span>
                    <span>{item.updated_at ? formatDate(item.updated_at) : item.request_id}</span>
                  </div>
                </div>
                <div className="space-y-3">
                  <select
                    className="input"
                    value={statusDrafts[item.request_id] || item.status}
                    onChange={(event) =>
                      setStatusDrafts((current) => ({ ...current, [item.request_id]: event.target.value }))
                    }
                  >
                    {NEXT_STATUSES.map((status) => (
                      <option key={status} value={status}>
                        {t(`admin.support_status_${status}`, {}, status)}
                      </option>
                    ))}
                  </select>
                  <textarea
                    className="input min-h-24"
                    value={noteDrafts[item.request_id] || ''}
                    onChange={(event) =>
                      setNoteDrafts((current) => ({ ...current, [item.request_id]: event.target.value }))
                    }
                    placeholder={t('admin.support_requests_note_placeholder', {}, 'Internal handling note')}
                  />
                  <button
                    type="button"
                    className="btn btn-primary w-full"
                    disabled={pendingRequestId === item.request_id}
                    onClick={() => void handleUpdate(item)}
                  >
                    {pendingRequestId === item.request_id
                      ? t('common.saving', {}, 'Saving...')
                      : t('admin.support_requests_update_action', {}, 'Update ticket')}
                  </button>
                  <Link
                    className="btn btn-secondary w-full"
                    href={`/admin/support-requests/${encodeURIComponent(item.request_id)}`}
                  >
                    {t('admin.support_request_view_detail', {}, 'View detail')}
                  </Link>
                </div>
              </div>
            </BackofficeStackCard>
          ))}
        </div>
      ) : (
        <BackofficeSectionPanel>
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('admin.support_requests_empty_title', {}, 'No tickets in this view')}
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {t('admin.support_requests_empty_desc', {}, 'Change the filter or wait for Portal users to submit a ticket.')}
          </p>
        </BackofficeSectionPanel>
      )}
      <ListPagination
        offset={offset}
        limit={PAGE_SIZE}
        total={total}
        isLoading={isLoading}
        onOffsetChange={setOffset}
        className="rounded-[1rem] border border-slate-200 bg-white/80 dark:border-slate-800 dark:bg-slate-950/45"
      />
    </BackofficePageStack>
  );
}
