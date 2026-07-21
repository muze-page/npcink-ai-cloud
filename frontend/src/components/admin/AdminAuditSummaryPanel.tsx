'use client';

import Link from 'next/link';
import React, { useEffect, useMemo, useState } from 'react';
import {
  BackofficeMetricStrip,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { resolveUiErrorMessage } from '@/lib/errors';
import {
  formatDate,
  formatNumber as formatInteger,
} from '@/lib/utils';

const adminAuditSummaryClient = createApiClient({ idempotencyPrefix: 'admin_audit_summary' });

type AuditSummaryGroup = {
  event_kind?: string;
  outcome?: string;
  count?: number;
  first_seen_at?: string;
  last_seen_at?: string;
};

type AuditSummaryPayload = {
  generated_at?: string;
  totals?: {
    events?: number;
    succeeded?: number;
    error?: number;
  };
  groups?: AuditSummaryGroup[];
};

export function AdminAuditSummaryPanel({
  title,
  siteId,
  accountId,
  trailHref,
  windowMinutes = 1440,
  limit = 5,
}: {
  title?: string;
  siteId?: string;
  accountId?: string;
  trailHref?: string;
  windowMinutes?: number;
  limit?: number;
}) {
  const { t } = useLocale();
  const [summary, setSummary] = useState<AuditSummaryPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const href = useMemo(() => {
    const params = new URLSearchParams();
    if (siteId) {
      params.set('site_id', siteId);
    }
    if (accountId) {
      params.set('account_id', accountId);
    }
    params.set('window_minutes', String(windowMinutes));
    params.set('limit', String(limit));
    return `/api/admin/audit-events/summary?${params.toString()}`;
  }, [accountId, limit, siteId, windowMinutes]);

  useEffect(() => {
    let cancelled = false;

    const loadSummary = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const response = await adminAuditSummaryClient.request<AuditSummaryPayload>(href);

        if (!cancelled) {
          setSummary(response.data ?? null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            resolveUiErrorMessage(
              err,
              t(
                'admin.audit_summary.load_failed',
                {},
                'Failed to load recent audit summary.'
              )
            )
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void loadSummary();

    return () => {
      cancelled = true;
    };
  }, [href, reloadKey, t]);

  const totals = summary?.totals ?? {};
  const groups = Array.isArray(summary?.groups) ? summary.groups : [];

  return (
    <BackofficeStackCard>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {title || t('admin.audit_summary.title', {}, 'Recent audit summary')}
          </p>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
            {t(
              'admin.audit_summary.description',
              {},
              'Use this bounded summary to decide whether you need deeper raw audit review.'
            )}
          </p>
        </div>
        {trailHref ? (
          <Link href={trailHref} className="btn btn-secondary" target="_blank">
            {t('admin.view_audit_trail', {}, 'View audit trail')}
          </Link>
        ) : null}
      </div>

      {isLoading ? (
        <p className="mt-4 text-sm text-slate-500 dark:text-slate-400" role="status">
          {t('common.loading', {}, 'Loading...')}
        </p>
      ) : error ? (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-3 py-3 dark:border-red-900/70 dark:bg-red-950/30" role="alert">
          <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
          <button
            type="button"
            className="btn btn-secondary btn-sm mt-3"
            onClick={() => setReloadKey((current) => current + 1)}
          >
            {t('common.retry', {}, 'Retry')}
          </button>
        </div>
      ) : (
        <>
          <div className="mt-4">
            <BackofficeMetricStrip
              columnsClassName="md:grid-cols-3 xl:grid-cols-3"
              items={[
                {
                  label: t('admin.audit_summary.events', {}, 'Events'),
                  value: formatInteger(Number(totals.events || 0)),
                },
                {
                  label: t('admin.audit_summary.succeeded', {}, 'Succeeded'),
                  value: formatInteger(Number(totals.succeeded || 0)),
                },
                {
                  label: t('admin.audit_summary.errors', {}, 'Errors'),
                  value: formatInteger(Number(totals.error || 0)),
                  toneClassName:
                    Number(totals.error || 0) > 0
                      ? 'text-red-600 dark:text-red-400'
                      : undefined,
                },
              ]}
            />
          </div>

          <div className="mt-4 space-y-3">
            {groups.length > 0 ? (
              groups.slice(0, limit).map((group, index) => (
                <div
                  key={`${group.event_kind || 'event'}-${group.outcome || 'outcome'}-${index}`}
                  className="rounded-xl border border-slate-200/70 px-3 py-3 dark:border-slate-800"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-950 dark:text-white">
                      {group.event_kind || t('common.unknown', {}, 'Unknown')}
                    </p>
                    <p className="text-xs uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                      {group.outcome || t('common.unknown', {}, 'Unknown')}
                    </p>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-600 dark:text-slate-300">
                    <span>
                      {t('admin.audit_summary.group_count', { count: String(group.count || 0) }, `${group.count || 0} events`)}
                    </span>
                    {group.last_seen_at ? (
                      <span>
                        {t('admin.audit_summary.last_seen', { date: formatDate(group.last_seen_at) }, `Last seen ${formatDate(group.last_seen_at)}`)}
                      </span>
                    ) : null}
                  </div>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {t(
                  'admin.audit_summary.empty',
                  {},
                  'No recent audit groups are available for the current scope.'
                )}
              </p>
            )}
          </div>

          {summary?.generated_at ? (
            <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
              {t(
                'admin.audit_summary.generated_at',
                { date: formatDate(summary.generated_at) },
                `Generated ${formatDate(summary.generated_at)}`
              )}
            </p>
          ) : null}
        </>
      )}
    </BackofficeStackCard>
  );
}
