'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSiteSwitchingNotice,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalAuditEvent,
  type PortalAuditSummary,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatDate } from '@/lib/utils';

const AUDIT_EVENT_KIND_LABELS: Record<string, string> = {
  'site_admin_access.upsert': 'audit.kind.site_admin_access.upsert',
  'portal_magic_link.requested': 'audit.kind.portal_login_code.requested',
  'portal_magic_link.consumed': 'audit.kind.portal_login_code.verified',
  'api_key.created': 'audit.kind.api_key.created',
  'api_key.rotated': 'audit.kind.api_key.rotated',
  'api_key.revoked': 'audit.kind.api_key.revoked',
  'site.connected': 'audit.kind.site.connected',
  'site.disconnected': 'audit.kind.site.disconnected',
  'subscription.activated': 'audit.kind.subscription.activated',
  'subscription.updated': 'audit.kind.subscription.updated',
  'subscription.canceled': 'audit.kind.subscription.canceled',
};

function humanizeAuditEventKind(eventKind: string) {
  return eventKind
    .replace(/[._]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function PortalAuditClient() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { t } = useLocale();
  const { sites, selectedSiteId, selectedSite, isSwitchingSite, switchingSiteName, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });
  const [auditEvents, setAuditEvents] = useState<PortalAuditEvent[]>([]);
  const [auditSummary, setAuditSummary] = useState<PortalAuditSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [eventKindFilter, setEventKindFilter] = useState<string>(() => searchParams?.get('eventKind') || '');
  const [outcomeFilter, setOutcomeFilter] = useState<string>(() => searchParams?.get('outcome') || '');
  const [limit, setLimit] = useState<number>(() => Number(searchParams?.get('limit') || 50));
  const [preset, setPreset] = useState<'all' | 'errors' | 'denied' | 'recent'>(
    () => (searchParams?.get('preset') as 'all' | 'errors' | 'denied' | 'recent') || 'all'
  );
  const [timeRange, setTimeRange] = useState<'all' | '24h' | '7d' | '30d'>(
    () => (searchParams?.get('range') as 'all' | '24h' | '7d' | '30d') || '7d'
  );
  const [nowMs] = useState(() => Date.now());
  const filteredAuditEvents = useMemo(() => {
    if (timeRange === 'all') {
      return auditEvents;
    }
    const threshold =
      timeRange === '24h'
        ? nowMs - 24 * 60 * 60 * 1000
        : timeRange === '7d'
          ? nowMs - 7 * 24 * 60 * 60 * 1000
          : nowMs - 30 * 24 * 60 * 60 * 1000;
    return auditEvents.filter((event) => new Date(event.created_at).getTime() >= threshold);
  }, [auditEvents, nowMs, timeRange]);
  const eventKinds = useMemo(
    () => Array.from(new Set(filteredAuditEvents.map((event) => event.event_kind))),
    [filteredAuditEvents]
  );
  const successRate = useMemo(() => {
    const total = filteredAuditEvents.length;
    const succeeded = filteredAuditEvents.filter((event) => event.outcome === 'success').length;
    return total > 0 ? Math.round((succeeded / total) * 100) : 0;
  }, [filteredAuditEvents]);

  useEffect(() => {
    setEventKindFilter(searchParams?.get('eventKind') || '');
    setOutcomeFilter(searchParams?.get('outcome') || '');
    setLimit(Number(searchParams?.get('limit') || 50));
    setPreset((searchParams?.get('preset') as 'all' | 'errors' | 'denied' | 'recent') || 'all');
    setTimeRange((searchParams?.get('range') as 'all' | '24h' | '7d' | '30d') || '7d');
  }, [searchParams]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams?.toString() || '');
    if (preset !== 'all') params.set('preset', preset);
    else params.delete('preset');
    if (eventKindFilter) params.set('eventKind', eventKindFilter);
    else params.delete('eventKind');
    if (outcomeFilter) params.set('outcome', outcomeFilter);
    else params.delete('outcome');
    if (limit !== 50) params.set('limit', String(limit));
    else params.delete('limit');
    if (timeRange !== '7d') params.set('range', timeRange);
    else params.delete('range');
    const nextQuery = params.toString();
    const currentQuery = searchParams?.toString() || '';
    if (nextQuery !== currentQuery) {
      router.replace(`${pathname}${nextQuery ? `?${nextQuery}` : ''}`, { scroll: false });
    }
  }, [pathname, router, searchParams, preset, eventKindFilter, outcomeFilter, limit, timeRange]);

  useEffect(() => {
    const loadData = async () => {
      if (!session || !isAuthenticated || !selectedSiteId) {
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const bundle = await portalClient.getAuditBundle(selectedSiteId, {
          eventKind: eventKindFilter || undefined,
          outcome: outcomeFilter || undefined,
          limit,
        });
        setAuditSummary(bundle.summary);
        setAuditEvents(bundle.events);
      } catch (err) {
        setError(
          formatPortalErrorMessage(err, t, t('audit.load_error', {}, 'Failed to load audit data'))
        );
      } finally {
        setIsLoading(false);
      }
    };

    void loadData();
  }, [eventKindFilter, isAuthenticated, limit, outcomeFilter, selectedSiteId, session, t]);

  const handleSiteChange = async (siteId: string) => {
    await setSelectedSiteId(siteId);
    setIsLoading(true);
    setError(null);

    try {
      const bundle = await portalClient.getAuditBundle(siteId, {
        eventKind: eventKindFilter || undefined,
        outcome: outcomeFilter || undefined,
        limit,
      });
      setAuditSummary(bundle.summary);
      setAuditEvents(bundle.events);
    } catch (err) {
      setError(
        formatPortalErrorMessage(err, t, t('audit.load_error', {}, 'Failed to load audit data'))
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleFilterChange = () => {
    if (!selectedSiteId) return;

    setIsLoading(true);
    setError(null);
    portalClient
      .getAuditBundle(selectedSiteId, {
        eventKind: eventKindFilter || undefined,
        outcome: outcomeFilter || undefined,
        limit,
      })
      .then((bundle) => {
        setAuditSummary(bundle.summary);
        setAuditEvents(bundle.events);
      })
      .catch((err) => {
        setError(
          formatPortalErrorMessage(
            err,
            t,
            t('audit.events_load_error', {}, 'Failed to load audit events')
          )
        );
      })
      .finally(() => {
        setIsLoading(false);
      });
  };

  const applyPreset = (nextPreset: 'all' | 'errors' | 'denied' | 'recent') => {
    setPreset(nextPreset);
    setEventKindFilter('');
    setOutcomeFilter(nextPreset === 'errors' ? 'error' : nextPreset === 'denied' ? 'denied' : '');
    setLimit(nextPreset === 'recent' ? 10 : 50);
  };

  const getEventIcon = (eventKind: string) => {
    if (eventKind.includes('key')) return '🔑';
    if (eventKind.includes('auth')) return '🔐';
    if (eventKind.includes('usage')) return '📊';
    if (eventKind.includes('billing')) return '💰';
    if (eventKind.includes('subscription')) return '📋';
    return '📝';
  };

  const translateOutcome = (outcome: string) => {
    if (outcome === 'error') {
      return t('common.error');
    }
    return t(`status.${outcome}`, {}, outcome);
  };

  const translateEventKind = (eventKind: string) => {
    const key = AUDIT_EVENT_KIND_LABELS[eventKind];
    if (key) {
      return t(key);
    }
    return humanizeAuditEventKind(eventKind);
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

  if (error) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={error}
        retryLabel={t('common.retry')}
        onRetry={() => void handleSiteChange(selectedSiteId)}
      />
    );
  }

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.selected_site')}
        title={t('audit.title')}
        eyebrowInfo={t('audit.desc')}
        currentPage="audit"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSite?.site_name}
        sites={sites}
        onSiteChange={handleSiteChange}
        metrics={[
          { label: t('audit.total_events'), value: auditSummary?.totals?.events || 0 },
          { label: t('portal.audit.visible_events', {}, 'Visible events'), value: filteredAuditEvents.length },
          { label: t('audit.event_types'), value: eventKinds.length },
          { label: t('audit.success_rate'), value: `${successRate}%` },
          {
            label: t('portal.updated_at', {}, 'Updated'),
            value: auditSummary?.generated_at ? formatDate(auditSummary.generated_at) : t('common.not_found'),
            size: 'compact',
          },
        ]}
        metricsColumnsClassName="xl:grid-cols-5"
      />

      {isSwitchingSite ? (
        <PortalSiteSwitchingNotice
          message={t(
            'portal.site_switching_notice_with_target',
            { site: switchingSiteName || selectedSite?.site_name || selectedSiteId },
            `Switching to ${switchingSiteName || selectedSite?.site_name || selectedSiteId}. Page data will update automatically.`
          )}
        />
      ) : null}

      <BackofficeSectionPanel className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <button type="button" className={`btn btn-sm ${preset === 'all' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => applyPreset('all')}>
            {t('portal.audit.preset_all', {}, 'All')}
          </button>
          <button type="button" className={`btn btn-sm ${preset === 'errors' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => applyPreset('errors')}>
            {t('portal.audit.preset_errors', {}, 'Failures')}
          </button>
          <button type="button" className={`btn btn-sm ${preset === 'denied' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => applyPreset('denied')}>
            {t('portal.audit.preset_denied', {}, 'Denied')}
          </button>
          <button type="button" className={`btn btn-sm ${preset === 'recent' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => applyPreset('recent')}>
            {t('portal.audit.preset_recent', {}, 'Recent 10')}
          </button>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
          <div>
            <label className="mb-2 block text-sm font-medium">{t('audit.event_type')}</label>
            <select value={eventKindFilter} onChange={(e) => setEventKindFilter(e.target.value)} className="input">
              <option value="">{t('audit.all_types', {}, 'All Types')}</option>
              {eventKinds.map((kind) => (
                <option key={kind} value={kind}>
                  {translateEventKind(kind)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium">{t('audit.outcome')}</label>
            <select value={outcomeFilter} onChange={(e) => setOutcomeFilter(e.target.value)} className="input">
              <option value="">{t('audit.all_outcomes', {}, 'All Outcomes')}</option>
              <option value="success">{t('status.success')}</option>
              <option value="error">{t('common.error')}</option>
              <option value="denied">{t('status.denied')}</option>
              <option value="warning">{t('status.warning')}</option>
            </select>
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium">{t('audit.limit')}</label>
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="input">
              <option value={10}>10</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={500}>500</option>
            </select>
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium">
              {t('portal.audit.range_label', {}, 'Time range')}
            </label>
            <select
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value as 'all' | '24h' | '7d' | '30d')}
              className="input"
            >
              <option value="all">{t('portal.audit.range_all', {}, 'All time')}</option>
              <option value="24h">{t('portal.audit.range_24h', {}, 'Last 24 hours')}</option>
              <option value="7d">{t('portal.audit.range_7d', {}, 'Last 7 days')}</option>
              <option value="30d">{t('portal.audit.range_30d', {}, 'Last 30 days')}</option>
            </select>
          </div>
          <div className="flex items-end">
            <button onClick={handleFilterChange} className="btn btn-primary w-full">
              {t('common.apply_filters')}
            </button>
          </div>
        </div>
      </BackofficeSectionPanel>

      <BackofficeSectionPanel className="overflow-hidden p-0">
        <div className="border-b border-gray-200 px-6 py-5 dark:border-gray-800">
          <h2 className="text-xl font-semibold text-gray-950 dark:text-white">{t('audit.events', {}, 'Audit Events')}</h2>
        </div>
        {filteredAuditEvents.length === 0 ? (
          <div className="p-6">
            <PortalEmptyState
              title={t('portal.audit.empty_title', {}, 'No activity in this view')}
              description={t(
                'portal.audit.empty_desc',
                {},
                'No site activity matches the current filters yet. Clear the filters or return to the workspace.'
              )}
              actionLabel={t('portal.workspace_label', {}, 'Workspace')}
              actionHref="/portal"
            />
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-800">
            {filteredAuditEvents.map((event) => (
              <article key={event.event_id} className="flex items-start gap-4 px-6 py-4">
                <div className="text-2xl">{getEventIcon(event.event_kind)}</div>
                <div className="flex-1">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="font-medium">{translateEventKind(event.event_kind)}</span>
                    <BackofficeStatusBadge status={event.outcome} label={translateOutcome(event.outcome)} />
                  </div>
                  {event.message ? <p className="mb-1 text-sm text-gray-600 dark:text-gray-400">{event.message}</p> : null}
                  <div className="flex flex-wrap items-center gap-3">
                    <p className="text-xs text-gray-500">{formatDate(event.created_at)}</p>
                    <details>
                      <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
                        {t('common.view_details', {}, 'View details')}
                      </summary>
                      <div className="mt-3 grid gap-2 rounded-2xl border border-slate-200/80 bg-slate-50/70 p-3 text-xs text-gray-600 dark:border-slate-800 dark:bg-slate-950/45 dark:text-gray-300 md:grid-cols-2">
                        <AuditDetail label={t('common.created')} value={formatDate(event.created_at)} />
                        <AuditDetail label={t('audit.actor', {}, 'Actor')} value={String(event.metadata?.actor_ref || event.metadata?.subject_ref || '—')} />
                        <AuditDetail label={t('audit.target', {}, 'Target')} value={String(event.metadata?.target_ref || t('portal.current_site', {}, 'Current site'))} />
                        <AuditDetail label={t('audit.failure_reason', {}, 'Failure reason')} value={String(event.metadata?.reason || event.metadata?.error || event.metadata?.error_code || '—')} />
                        <details className="md:col-span-2">
                          <summary className="cursor-pointer font-semibold text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200">
                            {t('portal.support_information', {}, 'Support information')}
                          </summary>
                          <div className="mt-2 grid gap-2 rounded-xl border border-slate-200 bg-white/70 p-3 dark:border-slate-800 dark:bg-slate-950/55 md:grid-cols-2">
                            <AuditDetail label="Event ID" value={event.event_id} />
                            <AuditDetail label={t('common.site', {}, 'Site')} value={String(event.metadata?.site_id || selectedSiteId || '—')} />
                            <AuditDetail label={t('audit.path', {}, 'Path')} value={String(event.metadata?.path || event.metadata?.request_path || '—')} />
                            <AuditDetail label={t('audit.trace_id', {}, 'Trace ID')} value={String(event.metadata?.trace_id || event.metadata?.request_id || '—')} />
                          </div>
                        </details>
                      </div>
                    </details>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

function AuditDetail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-1 break-all text-slate-800 dark:text-slate-200">{value || '—'}</p>
    </div>
  );
}
