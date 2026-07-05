'use client';

import React from 'react';
import { BackofficeMetricStrip } from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import { getPortalSiteWordPressUrl } from '@/lib/portal-site-display';
import { cn } from '@/lib/utils';

export type PortalWorkspacePage =
  | 'keys'
  | 'usage'
  | 'billing'
  | 'audit'
  | 'monitoring'
  | 'record'
  | 'sites';

export type PortalWorkspaceMetric = {
  label: string;
  value: React.ReactNode;
  detail?: string;
  toneClassName?: string;
  size?: 'default' | 'compact';
};

type PortalWorkspaceSite = {
  site_id: string;
  site_name: string;
  wordpress_url?: string;
  metadata?: Record<string, unknown>;
};

type PortalWorkspaceHeaderProps = {
  eyebrow: string;
  title: string;
  description?: string;
  eyebrowInfo?: string;
  currentPage: PortalWorkspacePage;
  selectedSiteId: string;
  selectedSiteName?: string | null;
  showSiteContextSummary?: boolean;
  sites?: PortalWorkspaceSite[];
  onSiteChange?: (siteId: string) => void;
  metrics?: PortalWorkspaceMetric[];
  metricsColumnsClassName?: string;
  primaryAction?: React.ReactNode;
  secondaryActions?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
};

export function PortalWorkspaceHeader({
  eyebrow,
  title,
  description,
  eyebrowInfo,
  currentPage,
  selectedSiteId,
  selectedSiteName,
  showSiteContextSummary = false,
  sites = [],
  onSiteChange,
  metrics = [],
  metricsColumnsClassName = 'lg:grid-cols-4',
  primaryAction,
  secondaryActions,
  actions,
  children,
}: PortalWorkspaceHeaderProps) {
  const { t } = useLocale();
  const resolvedActions =
    actions ?? (primaryAction || secondaryActions ? (
      <>
        {primaryAction}
        {secondaryActions}
      </>
    ) : null);
  const selectedSite = sites.find((site) => site.site_id === selectedSiteId) || null;
  const selectedSiteWordPressUrl = getPortalSiteWordPressUrl(selectedSite);
  const shouldShowEyebrow = eyebrow.trim().toLowerCase() !== title.trim().toLowerCase();
  const summary = (
    <div className="grid gap-4 xl:grid-cols-[minmax(16rem,0.8fr)_minmax(0,1.9fr)_auto] xl:items-center">
      <div className="min-w-0">
        {shouldShowEyebrow ? (
          <div className="flex items-center gap-2">
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
              {eyebrow}
            </p>
            {eyebrowInfo ? (
              <span
                aria-label={eyebrowInfo}
                title={eyebrowInfo}
                className="inline-flex h-5 w-5 cursor-pointer items-center justify-center rounded-full border border-slate-200 bg-white text-[0.68rem] font-semibold text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
              >
                i
              </span>
            ) : null}
          </div>
        ) : null}
        <h1 className={cn(
          'text-2xl font-semibold leading-tight text-gray-950 dark:text-white md:text-[1.75rem]',
          shouldShowEyebrow ? 'mt-1.5' : ''
        )}>
          {title}
        </h1>
        {showSiteContextSummary ? (
          <p className="mt-2 max-w-md truncate text-sm text-gray-600 dark:text-gray-400">
            {selectedSiteName || selectedSiteWordPressUrl || t('portal.current_site', {}, 'Current site')}
            {' · '}
            {selectedSiteWordPressUrl ||
              t('portal.site_url_missing', {}, 'WordPress URL not configured')}
          </p>
        ) : null}
        {description ? <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-300">{description}</p> : null}
      </div>
      {metrics.length ? (
        <BackofficeMetricStrip items={metrics} columnsClassName={metricsColumnsClassName} variant="portal" />
      ) : null}
      {resolvedActions ? <div className="flex flex-wrap gap-2 xl:justify-end">{resolvedActions}</div> : null}
    </div>
  );

  return (
    <section className="space-y-4 border-b border-slate-200/75 pb-5 dark:border-slate-800">
      {summary}
      {children}
    </section>
  );
}
