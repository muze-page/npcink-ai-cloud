'use client';

import { useEffect, useState } from 'react';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import type { PortalSiteSummaryRecord, Site } from '@/lib/portal-client';
import {
  getPortalSiteDisplayName,
  getPortalSiteUrl,
} from '@/lib/portal-site-display';
import { translateStatusLabel } from '@/lib/status-display';
import { cn } from '@/lib/utils';

type RestrictionItem = {
  tone: 'warn' | 'info';
  label: string;
  detail: string;
};

interface PortalSiteInspectorDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  site: Site | null;
  summary: PortalSiteSummaryRecord | null;
  isLoading: boolean;
  error: string;
  restrictions: RestrictionItem[];
  previousSiteId?: string;
  nextSiteId?: string;
  onNavigateSite: (siteId: string) => void;
  t: (key: string, params?: Record<string, string>, fallback?: string) => string;
}

export function PortalSiteInspectorDrawer({
  isOpen,
  onClose,
  site,
  summary,
  isLoading,
  error,
  restrictions,
  previousSiteId = '',
  nextSiteId = '',
  onNavigateSite,
  t,
}: PortalSiteInspectorDrawerProps) {
  const [showDetail, setShowDetail] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = 'unset';
    };
  }, [isOpen, onClose]);

  if (!isOpen || !site) {
    return null;
  }

  const detailSite: Site = summary?.site || site;
  const postureMetrics = [
    {
      label: t('common.status'),
      value: translateStatusLabel(detailSite.status, t),
      detail: getPortalSiteUrl(detailSite) || t('portal.site_url_missing_short', {}, 'Site URL not configured'),
    },
  ];

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-slate-950/45 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <aside
        className={cn(
          'absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform dark:border-slate-800 dark:bg-slate-950 sm:max-w-xl',
          isOpen ? 'translate-x-0' : 'translate-x-full'
        )}
        role="dialog"
        aria-modal="true"
        aria-labelledby="portal-site-inspector-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-4 py-4 dark:border-slate-800 sm:px-5">
          <div className="min-w-0">
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {t('portal.site_summary', {}, 'Site summary')}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <h2 id="portal-site-inspector-title" className="truncate text-xl font-semibold text-slate-950 dark:text-white">
                {getPortalSiteDisplayName(detailSite)}
              </h2>
              <PortalStatusBadge
                status={detailSite.status}
                label={translateStatusLabel(detailSite.status, t)}
                className="text-[0.68rem]"
              />
            </div>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              {getPortalSiteUrl(detailSite) || t('portal.site_url_missing_short', {}, 'Site URL not configured')}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => previousSiteId && onNavigateSite(previousSiteId)}
                disabled={!previousSiteId}
                className="btn btn-secondary btn-sm flex-1 sm:flex-none"
              >
                {t('common.previous', {}, 'Previous')}
              </button>
              <button
                type="button"
                onClick={() => nextSiteId && onNavigateSite(nextSiteId)}
                disabled={!nextSiteId}
                className="btn btn-secondary btn-sm flex-1 sm:flex-none"
              >
                {t('common.next', {}, 'Next')}
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-900 dark:hover:text-slate-200"
            aria-label={t('common.close')}
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5 sm:py-5">
          {isLoading ? (
            <div className="space-y-3">
              <div className="h-20 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-900" />
              <div className="h-28 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-900" />
              <div className="h-24 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-900" />
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
              {error}
            </div>
          ) : (
            <div className="space-y-5">
              <section className="rounded-[1.4rem] border border-slate-200/80 bg-slate-50/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/45">
                <div className="flex flex-col gap-2">
                  <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                    {t('portal.home.drawer_posture_label', {}, 'Quick view')}
                  </p>
                  <h3 className="text-lg font-semibold text-slate-950 dark:text-white">
                    {t('portal.home.drawer_posture_title', {}, 'Site details')}
                  </h3>
                  <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {t(
                      'portal.home.drawer_posture_desc',
                      {},
                      'Use this quick view to confirm the site status before opening a dedicated page.'
                    )}
                  </p>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <Metric
                    label={t('common.site')}
                    value={getPortalSiteDisplayName(detailSite)}
                    detail={getPortalSiteUrl(detailSite) || t('portal.site_url_missing_short', {}, 'Site URL not configured')}
                  />
                  {postureMetrics.map((item) => (
                    <Metric key={`${item.label}-${item.value}`} label={item.label} value={item.value} detail={item.detail} />
                  ))}
                </div>
              </section>

              <section className="rounded-[1.4rem] border border-slate-200/80 bg-white/90 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/30">
                <div className="flex items-center justify-between gap-3">
                  <div>
	                    <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
	                      {t('portal.home.drawer_limits_label', {}, 'Review')}
	                    </p>
	                    <h3 className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">
	                      {t('portal.home.drawer_attention_title', {}, 'Things to check')}
	                    </h3>
                  </div>
                  <button type="button" onClick={() => setShowDetail((current) => !current)} className="btn btn-secondary btn-sm">
                    {showDetail ? t('common.hide', {}, 'Hide') : t('common.view_details', {}, 'View details')}
                  </button>
                </div>

	                {showDetail ? (
	                  <div className="mt-4 space-y-4">
	                    <div className="space-y-3">
	                      {restrictions.length ? (
                        restrictions.map((item, index) => (
                          <div
                            key={`${item.label}-${index}`}
                            className={cn(
                              'rounded-2xl border px-4 py-3',
                              item.tone === 'warn'
                                ? 'border-amber-200 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/20'
                                : 'border-blue-200 bg-blue-50 dark:border-blue-900/60 dark:bg-blue-950/20'
                            )}
                          >
                            <p className="font-medium text-slate-950 dark:text-white">{item.label}</p>
                            <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">{item.detail}</p>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-900/60 dark:bg-emerald-950/20">
                          <p className="font-medium text-emerald-900 dark:text-emerald-100">
                            {t('portal.home.recent_issues_empty_title', {}, 'No active restrictions')}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                    {restrictions[0]?.detail ||
                      t('portal.home.recent_issues_empty_desc', {}, 'This site looks ready for normal usage.')}
                  </p>
                )}
              </section>

            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-[1rem] border border-slate-200/80 bg-slate-50/80 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/60">
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-sm font-semibold text-slate-950 dark:text-white">{value}</p>
      {detail ? <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">{detail}</p> : null}
    </div>
  );
}
