'use client';

import React from 'react';
import { PortalMetricStrip } from '@/components/portal/PortalScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import {
  getPortalSiteDisplayName,
  getPortalSiteSecondaryLabel,
  getPortalSiteUrl,
  getVisiblePortalSites,
} from '@/lib/portal-site-display';
import { cn, formatDate } from '@/lib/utils';

export type PortalWorkspacePage =
  | 'keys'
  | 'usage'
  | 'billing'
  | 'audit'
  | 'monitoring'
  | 'record'
  | 'sites'
  | 'support';

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
  site_url: string;
  platform_kind: 'wordpress';
  metadata?: Record<string, unknown>;
  created_at?: string;
};

type PortalWorkspaceHeaderProps = {
  eyebrow: string;
  title: string;
  description?: string;
  eyebrowInfo?: string;
  currentPage: PortalWorkspacePage;
  selectedSiteId?: string;
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
  selectedSiteId = '',
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
  const selectedSiteUrl = getPortalSiteUrl(selectedSite);
  const shouldShowEyebrow = eyebrow.trim().toLowerCase() !== title.trim().toLowerCase();
  const summary = (
    <div className="grid gap-4 xl:grid-cols-[minmax(16rem,0.8fr)_minmax(0,1.9fr)_auto] xl:items-center">
      <div className="min-w-0">
        {shouldShowEyebrow ? (
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
            {eyebrow}
          </p>
        ) : null}
        <h1 className={cn(
          'text-2xl font-semibold leading-tight text-gray-950 dark:text-white md:text-[1.75rem]',
          shouldShowEyebrow ? 'mt-1.5' : ''
        )}>
          {title}
        </h1>
        {eyebrowInfo ? <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-300">{eyebrowInfo}</p> : null}
        {showSiteContextSummary ? (
          <p className="mt-2 max-w-md truncate text-sm text-gray-600 dark:text-gray-400">
            {selectedSiteName || selectedSiteUrl || t('portal.current_site', {}, 'Site record')}
            {' · '}
            {selectedSiteUrl ||
              t('portal.site_url_missing', {}, 'WordPress URL not configured')}
          </p>
        ) : null}
        {description ? <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600 dark:text-gray-300">{description}</p> : null}
      </div>
      {metrics.length ? (
        <PortalMetricStrip items={metrics} columnsClassName={metricsColumnsClassName} variant="portal" />
      ) : null}
      {resolvedActions ? <div className="flex flex-wrap gap-2 xl:justify-end">{resolvedActions}</div> : null}
    </div>
  );

  return (
    <section className="space-y-4 border-b border-slate-200/75 pb-5 dark:border-slate-800">
      {summary}
      {onSiteChange && getVisiblePortalSites(sites).length > 1 ? (
        <div className="max-w-md">
          <label htmlFor={`portal-${currentPage}-site-selector`} className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('portal.current_site', {}, 'Current site')}
          </label>
          <select
            id={`portal-${currentPage}-site-selector`}
            className="input"
            value={selectedSiteId}
            onChange={(event) => onSiteChange(event.target.value)}
          >
            {getVisiblePortalSites(sites).map((site) => (
              <option key={site.site_id} value={site.site_id}>
                {getPortalSiteDisplayName(site)} ({getPortalSiteSecondaryLabel(site)}{site.created_at ? `, ${formatDate(site.created_at)}` : ''})
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {children}
    </section>
  );
}
