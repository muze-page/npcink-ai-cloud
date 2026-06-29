'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { PortalSiteConnectPanel } from '@/components/portal/PortalSiteConnectPanel';
import {
  PortalEmptyState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { Modal } from '@/components/ui/Modal';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import { portalClient, type PortalSiteSummaryRecord } from '@/lib/portal-client';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import {
  getPortalSiteDisplayName,
  getPortalSiteSecondaryLabel,
  getPortalSiteWordPressUrl,
} from '@/lib/portal-site-display';
import { formatDate } from '@/lib/utils';

const EMPTY_SITES: Array<{
  site_id: string;
  site_name: string;
  account_id?: string;
  status: string;
  plan_name?: string;
  created_at: string;
}> = [];
type PortalSiteListItem = (typeof EMPTY_SITES)[number];

function PortalSitesContent() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading, isAuthenticated, selectSite, refresh } = useSession();
  const [searchQuery, setSearchQuery] = useState(() => searchParams?.get('q') || '');
  const [siteFilter, setSiteFilter] = useState<'all' | 'active' | 'inactive' | 'archived' | 'missing_url' | 'uncovered'>(
    () => (searchParams?.get('filter') as 'all' | 'active' | 'inactive' | 'archived' | 'missing_url' | 'uncovered') || 'all'
  );
  const [siteSort, setSiteSort] = useState<'current' | 'recent' | 'name'>(
    () => (searchParams?.get('sort') as 'current' | 'recent' | 'name') || 'current'
  );
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [siteActionMessage, setSiteActionMessage] = useState<string | null>(null);
  const [siteActionError, setSiteActionError] = useState<string | null>(null);
  const [siteActionSiteId, setSiteActionSiteId] = useState('');
  const [exportFormat, setExportFormat] = useState<'csv' | 'json'>('csv');
  const [failedSiteNamesToCopy, setFailedSiteNamesToCopy] = useState('');
  const [copiedFailedNames, setCopiedFailedNames] = useState(false);
  const [failedBatchAction, setFailedBatchAction] = useState<{ action: 'archive' | 'restore'; siteIds: string[] } | null>(null);
  const [selectedSiteIds, setSelectedSiteIds] = useState<string[]>([]);
  const [openSiteMenuId, setOpenSiteMenuId] = useState('');
  const [pendingBatchAction, setPendingBatchAction] = useState<{
    action: 'archive' | 'restore';
    siteIds: string[];
  } | null>(null);
  const [siteSummaryCache, setSiteSummaryCache] = useState<Record<string, PortalSiteSummaryRecord>>({});
  const siteMenuRef = useRef<HTMLDivElement>(null);
  const sites = session?.sites ?? EMPTY_SITES;
  const siteIdsKey = sites.map((site) => site.site_id).join('|');
  const activeSite = sites.find((site) => site.status === 'active') || null;
  const selectedSiteId = session?.site_id || activeSite?.site_id || '';
  const selectedSite = sites.find((site) => site.site_id === selectedSiteId) || activeSite || sites[0] || null;
  const selectedSiteWordPressUrl = getPortalSiteWordPressUrl(selectedSite);
  const addonConnectMode = searchParams?.get('connect') === 'wordpress-addon';
  const addonWordPressUrl = searchParams?.get('site_url') || '';
  const addonSiteName = searchParams?.get('site_name') || '';
  const addonReturnUrl = searchParams?.get('return_url') || '';
  const addonState = searchParams?.get('state') || '';
  const canArchiveSites = Boolean(session?.allowed_actions?.includes('archive_sites'));
  const getSiteSummary = useCallback((siteId: string) => siteSummaryCache[siteId] || null, [siteSummaryCache]);
  const getSiteCoverage = useCallback((site: PortalSiteListItem) => getSiteSummary(site.site_id)?.coverage || null, [getSiteSummary]);
  const hasSiteCoverage = useCallback((site: PortalSiteListItem) => Boolean(getSiteCoverage(site) || site.plan_name), [getSiteCoverage]);
  const getSitePackageLabel = (site: PortalSiteListItem) => {
    const coverage = getSiteCoverage(site);
    return (
      resolveCustomerPackageDisplay(t, {
        planId: coverage?.plan_id,
        planVersionId: coverage?.plan_version_id,
        packageAlias: coverage?.package_alias,
        formalPlanName: site.plan_name,
        coverageState: coverage || site.plan_name ? 'covered' : 'uncovered',
      }).display_package_label || t('common.not_found')
    );
  };
  const filteredSites = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return sites.filter((site) => {
      if (siteFilter === 'active' && site.status !== 'active') {
        return false;
      }
      if (siteFilter === 'inactive' && site.status !== 'inactive') {
        return false;
      }
      if (siteFilter === 'archived' && site.status !== 'archived') {
        return false;
      }
      if (siteFilter === 'missing_url' && getPortalSiteWordPressUrl(site)) {
        return false;
      }
      if (siteFilter === 'uncovered' && hasSiteCoverage(site)) {
        return false;
      }
      if (!query) {
        return true;
      }
      return (
        site.site_name.toLowerCase().includes(query) ||
        site.site_id.toLowerCase().includes(query) ||
        (site.account_id || '').toLowerCase().includes(query)
      );
    });
  }, [hasSiteCoverage, searchQuery, siteFilter, sites]);
  const sortedSites = useMemo(() => {
    const next = [...filteredSites];
    if (siteSort === 'name') {
      next.sort((left, right) => getPortalSiteDisplayName(left).localeCompare(getPortalSiteDisplayName(right)));
      return next;
    }
    if (siteSort === 'recent') {
      next.sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime());
      return next;
    }
    next.sort((left, right) => {
      if (left.site_id === selectedSiteId) {
        return -1;
      }
      if (right.site_id === selectedSiteId) {
        return 1;
      }
      return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
    });
    return next;
  }, [filteredSites, selectedSiteId, siteSort]);
  const visibleSiteIds = useMemo(() => sortedSites.map((site) => site.site_id), [sortedSites]);
  const selectedSites = useMemo(
    () => sites.filter((site) => selectedSiteIds.includes(site.site_id)),
    [selectedSiteIds, sites]
  );
  const selectedArchivedCount = selectedSites.filter((site) => site.status === 'archived').length;
  const selectedActiveCount = selectedSites.length - selectedArchivedCount;
  const pendingBatchSites = useMemo(
    () => sites.filter((site) => pendingBatchAction?.siteIds.includes(site.site_id)),
    [pendingBatchAction?.siteIds, sites]
  );
  const missingUrlCount = sites.filter((site) => !getPortalSiteWordPressUrl(site)).length;
  const uncoveredCount = sites.filter((site) => !hasSiteCoverage(site)).length;
  const inactiveCount = sites.filter((site) => site.status === 'inactive').length;

  useEffect(() => {
    if (!isAuthenticated || !siteIdsKey) {
      setSiteSummaryCache({});
      return;
    }

    let isCancelled = false;

    void Promise.allSettled(sites.map((site) => portalClient.getSiteSummary(site.site_id))).then((results) => {
      if (isCancelled) {
        return;
      }
      const next: Record<string, PortalSiteSummaryRecord> = {};
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') {
          next[sites[index].site_id] = result.value.data as PortalSiteSummaryRecord;
        }
      });
      setSiteSummaryCache(next);
    });

    return () => {
      isCancelled = true;
    };
  }, [isAuthenticated, siteIdsKey, sites]);

  useEffect(() => {
    setSelectedSiteIds((current) => current.filter((siteId) => visibleSiteIds.includes(siteId)));
  }, [visibleSiteIds]);

  useEffect(() => {
    setSearchQuery(searchParams?.get('q') || '');
    setSiteFilter(
      (searchParams?.get('filter') as 'all' | 'active' | 'inactive' | 'archived' | 'missing_url' | 'uncovered') || 'all'
    );
    setSiteSort((searchParams?.get('sort') as 'current' | 'recent' | 'name') || 'current');
  }, [searchParams]);

  useEffect(() => {
    if (addonConnectMode && isAuthenticated) {
      setShowConnectModal(true);
    }
  }, [addonConnectMode, isAuthenticated]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams?.toString() || '');
    if (searchQuery.trim()) {
      params.set('q', searchQuery.trim());
    } else {
      params.delete('q');
    }
    if (siteFilter !== 'all') {
      params.set('filter', siteFilter);
    } else {
      params.delete('filter');
    }
    if (siteSort !== 'current') {
      params.set('sort', siteSort);
    } else {
      params.delete('sort');
    }
    const nextQuery = params.toString();
    const currentQuery = searchParams?.toString() || '';
    if (nextQuery !== currentQuery) {
      router.replace(`${pathname}${nextQuery ? `?${nextQuery}` : ''}`, { scroll: false });
    }
  }, [pathname, router, searchParams, searchQuery, siteFilter, siteSort]);

  useEffect(() => {
    if (!openSiteMenuId) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (siteMenuRef.current && !siteMenuRef.current.contains(event.target as Node)) {
        setOpenSiteMenuId('');
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenSiteMenuId('');
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [openSiteMenuId]);

  if (isLoading) {
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

  const handleSiteCreated = async (siteId: string) => {
    await selectSite(siteId);
    setShowConnectModal(false);
  };

  const toggleSiteSelection = (siteId: string) => {
    setSelectedSiteIds((current) =>
      current.includes(siteId) ? current.filter((value) => value !== siteId) : [...current, siteId]
    );
  };

  const toggleSelectAllVisible = () => {
    setSelectedSiteIds((current) => {
      const allVisibleSelected =
        visibleSiteIds.length > 0 && visibleSiteIds.every((siteId) => current.includes(siteId));
      if (allVisibleSelected) {
        return current.filter((siteId) => !visibleSiteIds.includes(siteId));
      }
      const next = new Set(current);
      visibleSiteIds.forEach((siteId) => next.add(siteId));
      return Array.from(next);
    });
  };

  const clearSelection = () => {
    setSelectedSiteIds([]);
  };

  const handleCopyFailedSiteNames = async () => {
    if (!failedSiteNamesToCopy) {
      return;
    }
    try {
      await navigator.clipboard.writeText(failedSiteNamesToCopy);
      setCopiedFailedNames(true);
      window.setTimeout(() => setCopiedFailedNames(false), 2000);
    } catch (error) {
      console.error('Failed to copy failed site names:', error);
    }
  };

  const handleExportFilteredSites = () => {
    const exportRows = sortedSites.map((site) => ({
      site_name: getPortalSiteDisplayName(site),
      site_id: site.site_id,
      status: site.status,
      wordpress_url: getPortalSiteWordPressUrl(site) || '',
      secondary_label: getPortalSiteSecondaryLabel(site) || '',
      plan_name: getSitePackageLabel(site),
      coverage_state: hasSiteCoverage(site) ? 'covered' : 'uncovered',
      account_id: site.account_id || '',
      created_at: site.created_at,
      is_current: site.site_id === selectedSiteId,
      missing_url: !getPortalSiteWordPressUrl(site),
    }));
    const fileBaseName = `portal-sites-${siteFilter}-${siteSort}`;
    const blob =
      exportFormat === 'json'
        ? new Blob([JSON.stringify(exportRows, null, 2)], {
            type: 'application/json;charset=utf-8;',
          })
        : new Blob(
            [
              [
                [
                  'site_name',
                  'site_id',
                  'status',
                  'wordpress_url',
                  'secondary_label',
                  'plan_name',
                  'coverage_state',
                  'account_id',
                  'created_at',
                  'is_current',
                  'missing_url',
                ].join(','),
                ...exportRows.map((row) =>
                  Object.values(row)
                    .map((value) => `"${String(value).replace(/"/g, '""')}"`)
                    .join(',')
                ),
              ].join('\n'),
            ],
            { type: 'text/csv;charset=utf-8;' }
          );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${fileBaseName}.${exportFormat}`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  };

  const retryFailedBatchAction = () => {
    if (!failedBatchAction?.siteIds.length) {
      return;
    }
    setPendingBatchAction(failedBatchAction);
  };

  const handleActivateSite = async (siteId: string) => {
    if (!canArchiveSites || !window.confirm(t('portal.activate_site_confirm', {}, 'Enable this site? It will become the only active site that can use Cloud services.'))) {
      return;
    }
    setSiteActionSiteId(siteId);
    setSiteActionMessage(null);
    setSiteActionError(null);
    try {
      await portalClient.activateSite(siteId);
      await refresh();
      setSiteActionMessage(
        t('portal.site_activate_success', {}, 'Site enabled. Other active sites in this account were disabled.')
      );
    } catch (error) {
      console.error('Failed to activate site:', error);
      setSiteActionError(formatPortalErrorMessage(error, t, t('portal.site_activate_failed', {}, 'Failed to enable this site.')));
    } finally {
      setSiteActionSiteId('');
    }
  };

  const handleDeactivateSite = async (siteId: string) => {
    if (!canArchiveSites || !window.confirm(t('portal.deactivate_site_confirm', {}, 'Disable Cloud services for this site? The site record, keys, usage, and audit history will be kept.'))) {
      return;
    }
    setSiteActionSiteId(siteId);
    setSiteActionMessage(null);
    setSiteActionError(null);
    try {
      await portalClient.deactivateSite(siteId);
      await refresh();
      setSiteActionMessage(
        t('portal.site_deactivate_success', {}, 'Site disabled. It can be enabled again later.')
      );
    } catch (error) {
      console.error('Failed to deactivate site:', error);
      setSiteActionError(formatPortalErrorMessage(error, t, t('portal.site_deactivate_failed', {}, 'Failed to disable this site.')));
    } finally {
      setSiteActionSiteId('');
    }
  };

  const handleArchiveSite = async (siteId: string) => {
    if (!canArchiveSites || !window.confirm(t('portal.archive_site_confirm', {}, 'Archive this site? It will be hidden from the default workspace and site switcher until restored.'))) {
      return;
    }
    setSiteActionSiteId(siteId);
    setSiteActionMessage(null);
    setSiteActionError(null);
    try {
      await portalClient.archiveSite(siteId);
      await refresh();
      setSiteActionMessage(
        t('portal.site_archive_success', {}, 'Site archived. It is now hidden from the default workspace flow.')
      );
    } catch (error) {
      console.error('Failed to archive site:', error);
      setSiteActionError(t('portal.site_archive_failed', {}, 'Failed to archive this site.'));
    } finally {
      setSiteActionSiteId('');
    }
  };

  const handleRestoreSite = async (siteId: string) => {
    if (!canArchiveSites || !window.confirm(t('portal.restore_site_confirm', {}, 'Restore this site to the active workspace?'))) {
      return;
    }
    setSiteActionSiteId(siteId);
    setSiteActionMessage(null);
    setSiteActionError(null);
    try {
      await portalClient.restoreSite(siteId);
      await refresh();
      setSiteActionMessage(
        t('portal.site_restore_success', {}, 'Site restored. It is available in the active workspace again.')
      );
    } catch (error) {
      console.error('Failed to restore site:', error);
      setSiteActionError(t('portal.site_restore_failed', {}, 'Failed to restore this site.'));
    } finally {
      setSiteActionSiteId('');
    }
  };

  const openBatchSiteAction = (action: 'archive' | 'restore') => {
    if (!canArchiveSites) {
      return;
    }
    const targetSiteIds = selectedSites
      .filter((site) => (action === 'archive' ? site.status !== 'archived' : site.status === 'archived'))
      .map((site) => site.site_id);
    if (targetSiteIds.length === 0) {
      return;
    }
    setPendingBatchAction({ action, siteIds: targetSiteIds });
  };

  const handleBatchSiteAction = async () => {
    if (!canArchiveSites || !pendingBatchAction) {
      return;
    }
    const { action, siteIds: targetSiteIds } = pendingBatchAction;
    setSiteActionSiteId(action === 'archive' ? '__batch_archive__' : '__batch_restore__');
    setSiteActionMessage(null);
    setSiteActionError(null);
    setFailedSiteNamesToCopy('');
    setCopiedFailedNames(false);
    setFailedBatchAction(null);
    const results = await Promise.allSettled(
      targetSiteIds.map((siteId) =>
        action === 'archive' ? portalClient.archiveSite(siteId) : portalClient.restoreSite(siteId)
      )
    );
    const successCount = results.filter((result) => result.status === 'fulfilled').length;
    const failedSiteNames = results.flatMap((result, index) =>
      result.status === 'rejected'
        ? [
            getPortalSiteDisplayName(
              sites.find((site) => site.site_id === targetSiteIds[index]) || {
                site_id: targetSiteIds[index],
                site_name: targetSiteIds[index],
                created_at: '',
                status: '',
              }
            ),
          ]
        : []
    );
    const failureCount = failedSiteNames.length;
    try {
      await refresh();
      setSelectedSiteIds((current) => current.filter((siteId) => !targetSiteIds.includes(siteId)));
      if (successCount > 0) {
        setSiteActionMessage(
          action === 'archive'
            ? t(
                'portal.site_archive_batch_success',
                { count: String(successCount) },
                '{{count}} sites archived. They are now hidden from the default workspace flow.'
              )
            : t(
                'portal.site_restore_batch_success',
                { count: String(successCount) },
                '{{count}} sites restored. They are available in the active workspace again.'
              )
        );
      }
      if (failureCount > 0) {
        const failedNames = failedSiteNames.join('、');
        setFailedSiteNamesToCopy(failedNames);
        setFailedBatchAction({
          action,
          siteIds: results.flatMap((result, index) => (result.status === 'rejected' ? [targetSiteIds[index]] : [])),
        });
        setSiteActionError(
          `${action === 'archive'
            ? t(
                'portal.site_archive_batch_failed',
                { count: String(failureCount) },
                'Failed to archive {{count}} selected sites.'
              )
            : t(
                'portal.site_restore_batch_failed',
                { count: String(failureCount) },
                'Failed to restore {{count}} selected sites.'
              )} ${t(
            'portal.site_batch_failed_names',
            { sites: failedNames },
            'Failed sites: {{sites}}'
          )}`
        );
      }
    } finally {
      setPendingBatchAction(null);
      setSiteActionSiteId('');
    }
  };

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.nav_sites', {}, 'Sites')}
        title={t('portal.nav_sites', {}, 'Sites')}
        eyebrowInfo={t(
          'portal.sites.desc',
          {},
          'Use this page to see which sites are bound to you, switch the current site, and open the record for a specific site.'
        )}
        currentPage="sites"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSite?.site_name}
        sites={session.sites}
        onSiteChange={(siteId) => void selectSite(siteId)}
        secondaryActions={(
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setShowConnectModal(true)}
            disabled={!selectedSite?.account_id}
          >
            {t('portal.connect_site_action', {}, 'Add site')}
          </button>
        )}
        metrics={[
          { label: t('common.sites', {}, 'Sites'), value: session.sites.length },
          {
            label: t('portal.home.filter_attention_only', {}, 'Needs attention'),
            value: session.sites.filter((site) => site.status !== 'active' || !hasSiteCoverage(site)).length,
          },
          {
            label: t('common.current', {}, 'Current'),
            value: getPortalSiteDisplayName(selectedSite) || t('common.not_found'),
            detail: selectedSiteWordPressUrl || t('portal.site_url_missing', {}, 'WordPress URL not configured'),
          },
        ]}
        metricsColumnsClassName="lg:grid-cols-3"
      />

      <BackofficeSectionPanel className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.home.my_sites_title', {}, 'My sites')}
            </h2>
          </div>
          <div className="flex w-full flex-col gap-3 lg:w-auto lg:flex-row lg:items-center">
            <button
              type="button"
              className="btn btn-primary btn-sm lg:hidden"
              onClick={() => setShowConnectModal(true)}
              disabled={!selectedSite?.account_id}
            >
              {t('portal.connect_site_action', {}, 'Add site')}
            </button>
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t('portal.home.search_sites_placeholder', {}, 'Search site, WordPress URL, or customer')}
              className="input w-full lg:max-w-sm"
            />
          </div>
        </div>

        {siteActionMessage ? (
          <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-100">
            {siteActionMessage}
          </BackofficeStackCard>
        ) : null}
        {siteActionError ? (
          <BackofficeStackCard className="border-red-200 bg-red-50 text-red-900 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-100">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <span>{siteActionError}</span>
              <div className="flex flex-wrap gap-2">
                {failedBatchAction?.siteIds.length ? (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={retryFailedBatchAction}>
                    {t('portal.retry_failed_sites', {}, 'Retry failed')}
                  </button>
                ) : null}
                {failedSiteNamesToCopy ? (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => void handleCopyFailedSiteNames()}>
                    {copiedFailedNames
                      ? t('portal.site_batch_failed_names_copied', {}, 'Copied failed names')
                      : t('portal.copy_failed_site_names', {}, 'Copy failed names')}
                  </button>
                ) : null}
              </div>
            </div>
          </BackofficeStackCard>
        ) : null}

        <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={`btn btn-sm ${siteFilter === 'all' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setSiteFilter('all')}
                >
                  {t('portal.all_sites_filter', {}, 'All')}
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${siteFilter === 'active' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setSiteFilter('active')}
                >
                  {t('portal.active_sites_filter', {}, 'Active')}
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${siteFilter === 'inactive' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setSiteFilter('inactive')}
                >
                  {t('portal.inactive_sites_filter', { count: String(inactiveCount) }, 'Inactive')}
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${siteFilter === 'archived' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setSiteFilter('archived')}
                >
                  {t('portal.archived_sites_filter', {}, 'Archived')}
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${siteFilter === 'missing_url' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setSiteFilter('missing_url')}
                >
                  {t('portal.missing_url_sites_filter', { count: String(missingUrlCount) }, 'Missing URL')}
                </button>
                <button
                  type="button"
                  className={`btn btn-sm ${siteFilter === 'uncovered' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setSiteFilter('uncovered')}
                >
                  {t('portal.uncovered_sites_filter', { count: String(uncoveredCount) }, 'Uncovered')}
                </button>
                <select
                  value={siteSort}
                  onChange={(event) => setSiteSort(event.target.value as 'current' | 'recent' | 'name')}
                  className="rounded-full border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-blue-400 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200"
                >
                  <option value="current">{t('portal.sites_sort_current', {}, 'Current first')}</option>
                  <option value="recent">{t('portal.sites_sort_recent', {}, 'Recently connected')}</option>
                  <option value="name">{t('portal.sites_sort_name', {}, 'Name A-Z')}</option>
                </select>
              </div>
              <input
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder={t('portal.home.search_sites_placeholder', {}, 'Search site, WordPress URL, or customer')}
                className="input w-full lg:max-w-sm"
              />
            </div>
            {canArchiveSites ? (
              <div className="flex flex-col gap-3 border-t border-slate-200/80 pt-3 dark:border-slate-800">
                <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                  <p className="text-sm text-gray-600 dark:text-gray-300">
                    {selectedSiteIds.length > 0
                      ? t(
                          'portal.bulk_site_actions_selection',
                          {
                            count: String(selectedSiteIds.length),
                            activeCount: String(selectedActiveCount),
                            archivedCount: String(selectedArchivedCount),
                          },
                          '{{count}} selected: {{activeCount}} active, {{archivedCount}} archived.'
                        )
                      : t(
                          'portal.bulk_site_actions_desc',
                          {},
                          'Select multiple sites to archive or restore them in one step.'
                        )}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <select
                      value={exportFormat}
                      onChange={(event) => setExportFormat(event.target.value as 'csv' | 'json')}
                      className="rounded-full border border-slate-200/80 bg-white/90 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-blue-400 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200"
                    >
                      <option value="csv">{t('portal.export_format_csv', {}, 'CSV')}</option>
                      <option value="json">{t('portal.export_format_json', {}, 'JSON')}</option>
                    </select>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={handleExportFilteredSites}>
                      {t('portal.export_filtered_sites', {}, 'Export filtered')}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={toggleSelectAllVisible}
                      disabled={visibleSiteIds.length === 0}
                    >
                      {visibleSiteIds.length > 0 && visibleSiteIds.every((siteId) => selectedSiteIds.includes(siteId))
                        ? t('portal.deselect_visible_sites', {}, 'Deselect visible')
                        : t('portal.select_visible_sites', {}, 'Select visible')}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={clearSelection}
                      disabled={selectedSiteIds.length === 0}
                    >
                      {t('portal.clear_site_selection', {}, 'Clear selection')}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => openBatchSiteAction('archive')}
                      disabled={selectedActiveCount === 0 || siteActionSiteId !== ''}
                    >
                      {t('portal.archive_selected_sites', { count: String(selectedActiveCount) }, 'Archive selected ({{count}})')}
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => openBatchSiteAction('restore')}
                      disabled={selectedArchivedCount === 0 || siteActionSiteId !== ''}
                    >
                      {t('portal.restore_selected_sites', { count: String(selectedArchivedCount) }, 'Restore selected ({{count}})')}
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </BackofficeStackCard>

        <div className="grid gap-3">
          {filteredSites.length === 0 ? (
            <PortalEmptyState
              title={
                siteFilter === 'archived'
                  ? t('portal.archived_sites_empty_title', {}, 'No archived sites')
                  : t('portal.sites.empty_title', {}, 'No sites match this search')
              }
              description={t(
                siteFilter === 'archived' ? 'portal.archived_sites_empty_desc' : 'portal.sites.empty_desc',
                {},
                siteFilter === 'archived'
                  ? 'Archived sites will appear here after you archive them from the site register.'
                  : 'No connected site matches the current search term. Clear the search or return to the workspace.'
              )}
              actionLabel={t('portal.workspace_label', {}, 'Workspace')}
              actionHref="/portal"
            />
          ) : sortedSites.map((site) => (
            <BackofficeStackCard
              key={site.site_id}
              className={
                site.site_id === selectedSiteId
                  ? 'border-[color:var(--brand-primary)]/20 bg-[color:var(--brand-primary-soft)]/35 ring-1 ring-[color:var(--brand-primary)]/10 dark:bg-blue-500/10'
                  : 'bg-white/80 dark:bg-slate-950/55'
              }
            >
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {canArchiveSites ? (
                      <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                        <input
                          type="checkbox"
                          checked={selectedSiteIds.includes(site.site_id)}
                          onChange={() => toggleSiteSelection(site.site_id)}
                          className="checkbox checkbox-sm"
                        />
                        <span className="sr-only">
                          {t('portal.select_site_row', { site: getPortalSiteDisplayName(site) }, 'Select {site}')}
                        </span>
                      </label>
                    ) : null}
                    <p className="truncate text-lg font-semibold text-gray-950 dark:text-white">
                      {getPortalSiteDisplayName(site)}
                    </p>
                    <BackofficeStatusBadge
                      status={site.status === 'active' ? 'active' : 'warning'}
                      label={t(`status.${site.status}`, undefined, site.status)}
                      className="text-[0.68rem]"
                    />
                    {!getPortalSiteWordPressUrl(site) ? (
                      <span className="rounded-full bg-amber-100 px-2 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                        {t('portal.missing_url_badge', {}, 'Missing URL')}
                      </span>
                    ) : null}
                    {!hasSiteCoverage(site) ? (
                      <span className="rounded-full bg-rose-100 px-2 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-rose-700 dark:bg-rose-900/30 dark:text-rose-300">
                        {t('portal.uncovered_sites_filter', {}, 'Uncovered')}
                      </span>
                    ) : null}
                    {site.site_id === selectedSiteId ? (
                      <span className="rounded-full bg-[color:var(--brand-primary-soft)] px-2 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-[color:var(--brand-primary)]">
                        {t('common.current', {}, 'Current')}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                    {getPortalSiteWordPressUrl(site) ||
                      getPortalSiteSecondaryLabel(site) ||
                      t('portal.site_url_missing_short', {}, 'Site URL not configured')}
                  </p>
                  <BackofficeMetricStrip
                    items={[
                      {
                        label: t('common.plan'),
                        value: getSitePackageLabel(site),
                      },
                      { label: t('site_details.connected', {}, 'Connected'), value: formatDate(site.created_at) },
                    ]}
                    columnsClassName="lg:grid-cols-2"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                  {site.status === 'archived' ? (
                    <button
                      type="button"
                      onClick={() => void handleRestoreSite(site.site_id)}
                      className="btn btn-primary btn-sm"
                      disabled={!canArchiveSites || siteActionSiteId === site.site_id}
                    >
                      {t('portal.restore_site_action', {}, 'Restore site')}
                    </button>
                  ) : site.status !== 'active' ? (
                    <button
                      type="button"
                      onClick={() => void handleActivateSite(site.site_id)}
                      className="btn btn-primary btn-sm"
                      disabled={!canArchiveSites || siteActionSiteId === site.site_id}
                    >
                      {t('portal.activate_site_action', {}, 'Enable service')}
                    </button>
                  ) : site.site_id !== selectedSiteId ? (
                    <button type="button" onClick={() => void selectSite(site.site_id)} className="btn btn-primary btn-sm">
                      {t('portal.home.select_site_action', {}, 'Select')}
                    </button>
                  ) : null}
                  <Link href={`/portal/sites/${site.site_id}`} className="btn btn-secondary btn-sm">
                    {t('portal.site_record', {}, 'Site record')}
                  </Link>
                  {site.status !== 'archived' ? (
                    <div ref={openSiteMenuId === site.site_id ? siteMenuRef : undefined} className="relative">
                      <button
                        type="button"
                        aria-haspopup="menu"
                        aria-expanded={openSiteMenuId === site.site_id}
                        className="btn btn-secondary btn-sm"
                        onClick={() => setOpenSiteMenuId((current) => (current === site.site_id ? '' : site.site_id))}
                      >
                        {t('portal.nav_more', {}, 'More')}
                      </button>
                      {openSiteMenuId === site.site_id ? (
                        <div
                          className="absolute right-0 top-full z-10 mt-2 min-w-44 rounded-2xl border border-slate-200/80 bg-white p-2 shadow-xl dark:border-slate-800 dark:bg-slate-950"
                          role="menu"
                        >
                          <Link
                            href={`/portal/usage?site=${site.site_id}`}
                            role="menuitem"
                            className="block rounded-xl px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                            onClick={() => setOpenSiteMenuId('')}
                          >
                            {t('nav.usage')}
                          </Link>
                          {canArchiveSites && site.status === 'active' ? (
                            <button
                              type="button"
                              role="menuitem"
                              onClick={() => {
                                setOpenSiteMenuId('');
                                void handleDeactivateSite(site.site_id);
                              }}
                              className="block w-full rounded-xl px-3 py-2 text-left text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                              disabled={siteActionSiteId === site.site_id}
                            >
                              {t('portal.deactivate_site_action', {}, 'Disable service')}
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>
            </BackofficeStackCard>
          ))}
        </div>
      </BackofficeSectionPanel>

      <Modal
        isOpen={Boolean(pendingBatchAction)}
        onClose={() => {
          if (siteActionSiteId === '__batch_archive__' || siteActionSiteId === '__batch_restore__') {
            return;
          }
          setPendingBatchAction(null);
        }}
        title={
          pendingBatchAction?.action === 'archive'
            ? t('portal.archive_sites_modal_title', {}, 'Archive selected sites')
            : t('portal.restore_sites_modal_title', {}, 'Restore selected sites')
        }
        description={
          pendingBatchAction?.action === 'archive'
            ? t(
                'portal.archive_sites_confirm',
                { count: String(pendingBatchAction?.siteIds.length || 0) },
                'Archive {count} selected sites? They will be hidden from the default workspace and site switcher until restored.'
              )
            : t(
                'portal.restore_sites_confirm',
                { count: String(pendingBatchAction?.siteIds.length || 0) },
                'Restore {count} selected sites to the active workspace?'
              )
        }
        footer={
          <>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPendingBatchAction(null)}
              disabled={siteActionSiteId === '__batch_archive__' || siteActionSiteId === '__batch_restore__'}
            >
              {t('common.cancel')}
            </button>
            <button
              type="button"
              className={`btn ${pendingBatchAction?.action === 'archive' ? 'btn-secondary' : 'btn-primary'}`}
              onClick={() => void handleBatchSiteAction()}
              disabled={siteActionSiteId === '__batch_archive__' || siteActionSiteId === '__batch_restore__'}
            >
              {pendingBatchAction?.action === 'archive'
                ? t('portal.archive_selected_sites', { count: String(pendingBatchSites.length) }, 'Archive selected ({count})')
                : t('portal.restore_selected_sites', { count: String(pendingBatchSites.length) }, 'Restore selected ({count})')}
            </button>
          </>
        }
        size="lg"
      >
        <div className="space-y-3">
          <BackofficeMetricStrip
            items={[
              {
                label: t('portal.batch_sites_modal_list_label', {}, 'Affected sites'),
                value: pendingBatchSites.length,
              },
              {
                label: t('portal.active_sites_filter', {}, 'Active'),
                value: pendingBatchSites.filter((site) => site.status !== 'archived').length,
              },
              {
                label: t('portal.archived_sites_filter', {}, 'Archived'),
                value: pendingBatchSites.filter((site) => site.status === 'archived').length,
              },
            ]}
            columnsClassName="lg:grid-cols-3"
          />
          <p className="text-sm text-gray-600 dark:text-gray-300">
            {t('portal.batch_sites_modal_list_label', {}, 'Affected sites')}
          </p>
          <div className="max-h-80 space-y-2 overflow-y-auto">
            {pendingBatchSites.map((site) => (
              <div
                key={site.site_id}
                className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/60"
              >
                <p className="text-sm font-semibold text-slate-950 dark:text-white">
                  {getPortalSiteDisplayName(site)}
                </p>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                  {getPortalSiteWordPressUrl(site) ||
                    getPortalSiteSecondaryLabel(site) ||
                    site.site_id}
                </p>
              </div>
            ))}
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={showConnectModal}
        onClose={() => setShowConnectModal(false)}
        title={t('portal.connect_site_heading', undefined, 'Add another WordPress site')}
        description={t(
          'portal.connect_site_desc',
          undefined,
          'Create the Cloud-side site record for the current customer, then issue a site key and finish the addon binding inside WordPress.'
        )}
        size="lg"
      >
        {selectedSite?.account_id ? (
          <PortalSiteConnectPanel
            accountId={selectedSite.account_id}
            currentSiteId={selectedSite.site_id}
            sites={session.sites}
            onSiteCreated={(siteId) => handleSiteCreated(siteId)}
            mode="modal"
            onClose={() => setShowConnectModal(false)}
            initialWordPressUrl={addonWordPressUrl}
            initialSiteName={addonSiteName}
            addonReturnUrl={addonReturnUrl}
            addonState={addonState}
          />
        ) : (
          <PortalEmptyState
            title={t('portal.connect_site_account_required_title', {}, 'Switch into a customer-backed site first')}
            description={t(
              'portal.connect_site_account_required_desc',
              {},
              'Select a current site that is already bound to a customer account before adding another site here.'
            )}
            actionLabel={t('portal.workspace_label', {}, 'Workspace')}
            actionHref="/portal"
          />
        )}
      </Modal>
    </BackofficePageStack>
  );
}

export default function PortalSitesPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalSitesContent />
    </Suspense>
  );
}
