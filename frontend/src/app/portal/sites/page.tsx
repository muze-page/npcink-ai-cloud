'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useMemo, useState } from 'react';
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
import {
  getPortalSiteDisplayName,
  getPortalSiteWordPressUrl,
} from '@/lib/portal-site-display';
import { portalClient } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
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
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [pendingRemoveSite, setPendingRemoveSite] = useState<PortalSiteListItem | null>(null);
  const [removeError, setRemoveError] = useState('');
  const [removeNotice, setRemoveNotice] = useState('');
  const [isRemovingSite, setIsRemovingSite] = useState(false);
  const sites = session?.sites ?? EMPTY_SITES;
  const activeSite = sites.find((site) => site.status === 'active') || null;
  const selectedSiteId = session?.site_id || activeSite?.site_id || '';
  const selectedSite = sites.find((site) => site.site_id === selectedSiteId) || activeSite || sites[0] || null;
  const selectedSiteWordPressUrl = getPortalSiteWordPressUrl(selectedSite);
  const canRemoveSites = Boolean(
    session?.allowed_actions?.includes('remove_sites') ||
      session?.accounts?.some((account) => account.allowed_actions?.includes('remove_sites'))
  );
  const addonConnectMode = searchParams?.get('connect') === 'wordpress-addon';
  const addonWordPressUrl = searchParams?.get('site_url') || '';
  const addonSiteName = searchParams?.get('site_name') || '';
  const addonReturnUrl = searchParams?.get('return_url') || '';
  const addonState = searchParams?.get('state') || '';
  const filteredSites = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return sites.filter((site) => {
      if (site.status === 'archived') {
        return false;
      }
      if (!query) {
        return true;
      }
      const siteUrl = getPortalSiteWordPressUrl(site);
      return (
        getPortalSiteDisplayName(site).toLowerCase().includes(query) ||
        (siteUrl || '').toLowerCase().includes(query)
      );
    });
  }, [searchQuery, sites]);
  const sortedSites = useMemo(() => {
    const next = [...filteredSites];
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
  }, [filteredSites, selectedSiteId]);

  useEffect(() => {
    setSearchQuery(searchParams?.get('q') || '');
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
    params.delete('filter');
    params.delete('sort');
    const nextQuery = params.toString();
    const currentQuery = searchParams?.toString() || '';
    if (nextQuery !== currentQuery) {
      router.replace(`${pathname}${nextQuery ? `?${nextQuery}` : ''}`, { scroll: false });
    }
  }, [pathname, router, searchParams, searchQuery]);

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

  const openRemoveSiteModal = (site: PortalSiteListItem) => {
    setPendingRemoveSite(site);
    setRemoveError('');
  };

  const closeRemoveSiteModal = () => {
    if (isRemovingSite) return;
    setPendingRemoveSite(null);
    setRemoveError('');
  };

  const handleRemoveSite = async () => {
    if (!pendingRemoveSite) return;
    setIsRemovingSite(true);
    setRemoveError('');
    setRemoveNotice('');
    try {
      await portalClient.removeSite(pendingRemoveSite.site_id);
      await refresh();
      setRemoveNotice(t('portal.site_remove_success', {}, 'Site removed. Active keys were revoked and history was kept.'));
      setPendingRemoveSite(null);
    } catch (error) {
      setRemoveError(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.site_remove_failed', {}, 'Failed to remove this site.')
        )
      );
    } finally {
      setIsRemovingSite(false);
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
        metrics={[
          { label: t('common.sites', {}, 'Sites'), value: session.sites.length },
          {
            label: t('portal.home.filter_attention_only', {}, 'Needs attention'),
            value: session.sites.filter((site) => site.status !== 'active' || !getPortalSiteWordPressUrl(site)).length,
          },
          {
            label: t('common.current', {}, 'Current'),
            value: getPortalSiteDisplayName(selectedSite) || t('portal.no_site_selected', {}, 'No site selected'),
            detail: selectedSiteWordPressUrl || t('portal.site_url_missing', {}, 'WordPress URL not configured'),
          },
        ]}
        metricsColumnsClassName="lg:grid-cols-3"
      />

      <BackofficeSectionPanel className="space-y-4" variant="portal">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.home.my_sites_title', {}, 'My sites')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t(
                'portal.sites.simple_list_desc',
                { count: String(sortedSites.length) },
                'Showing connected sites. Use search if you have many sites.'
              )}
            </p>
          </div>
          <div className="w-full lg:w-auto">
            <input
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t('portal.home.search_sites_placeholder', {}, 'Search site name or URL')}
              className="input w-full lg:max-w-sm"
            />
          </div>
        </div>

        <div className="rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-sm text-blue-950 dark:border-blue-900/50 dark:bg-blue-950/30 dark:text-blue-100">
          <p className="font-semibold">
            {t('portal.sites.connect_hint_title', {}, 'Need to connect another site?')}
          </p>
          <p className="mt-1 leading-6 text-blue-900/80 dark:text-blue-100/80">
            {t(
              'portal.sites.connect_hint_desc',
              {},
              'Open npcink-cloud-addon in WordPress and start the connection there. After binding, the site will appear here.'
            )}
          </p>
        </div>

        <div className="grid gap-3">
          {removeNotice ? (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-100">
              {removeNotice}
            </div>
          ) : null}
          {filteredSites.length === 0 ? (
            <PortalEmptyState
              title={t('portal.sites.empty_title', {}, 'No sites match this search')}
              description={t(
                'portal.sites.empty_desc',
                {},
                'No connected site matches the current search term. Clear the search or return to the workspace.'
              )}
              actionLabel={t('portal.workspace_label', {}, 'Workspace')}
              actionHref="/portal"
            />
          ) : sortedSites.map((site) => (
            <BackofficeStackCard
              key={site.site_id}
              variant="portal"
              className={
                site.site_id === selectedSiteId
                  ? 'border-[color:var(--brand-primary)]/20 bg-[color:var(--brand-primary-soft)]/35 ring-1 ring-[color:var(--brand-primary)]/10 dark:bg-blue-500/10'
                  : 'bg-white/80 dark:bg-slate-950/55'
              }
            >
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-lg font-semibold text-gray-950 dark:text-white">
                      {getPortalSiteDisplayName(site)}
                    </p>
                    <BackofficeStatusBadge
                      status={site.status === 'active' && getPortalSiteWordPressUrl(site) ? 'active' : 'warning'}
                      label={
                        site.status === 'active' && getPortalSiteWordPressUrl(site)
                          ? t('portal.home.risk_level_normal', {}, 'Normal')
                          : t('portal.home.filter_attention_only', {}, 'Needs attention')
                      }
                      className="text-[0.68rem]"
                    />
                    {!getPortalSiteWordPressUrl(site) ? (
                      <span className="rounded-full bg-amber-100 px-2 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                        {t('portal.home.site_address_needs_setup', {}, 'Needs setup')}
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
                      t('portal.site_url_missing_short', {}, 'Site URL not configured')}
                  </p>
                  <BackofficeMetricStrip
                    items={[
                      { label: t('site_details.connected', {}, 'Connected'), value: formatDate(site.created_at) },
                    ]}
                    columnsClassName="lg:grid-cols-1"
                    variant="portal"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                  {site.status !== 'active' ? null : site.site_id !== selectedSiteId ? (
                    <button type="button" onClick={() => void selectSite(site.site_id)} className="btn btn-primary btn-sm">
                      {t('portal.home.select_site_action', {}, 'Select')}
                    </button>
                  ) : null}
                  <Link href={`/portal/sites/${site.site_id}`} className="btn btn-secondary btn-sm">
                    {t('portal.site_record', {}, 'Site record')}
                  </Link>
                  {canRemoveSites && site.status !== 'suspended' ? (
                    <button
                      type="button"
                      onClick={() => openRemoveSiteModal(site)}
                      className="btn btn-danger btn-sm"
                    >
                      {t('portal.remove_site_action', {}, 'Remove site')}
                    </button>
                  ) : null}
                </div>
              </div>
            </BackofficeStackCard>
          ))}
        </div>
      </BackofficeSectionPanel>

      <Modal
        isOpen={addonConnectMode && showConnectModal}
        onClose={() => setShowConnectModal(false)}
        title={t('portal.connect_site_addon_title', undefined, 'Finish WordPress connection')}
        description={t(
          'portal.connect_site_addon_desc',
          undefined,
          'Confirm this site connection, then return to WordPress to finish setup.'
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

      <Modal
        isOpen={Boolean(pendingRemoveSite)}
        onClose={closeRemoveSiteModal}
        closeOnOverlay={!isRemovingSite}
        title={t('portal.remove_site_action', {}, 'Remove site')}
        description={t(
          'portal.remove_site_confirm',
          {},
          'Remove this site? Cloud service will stop, active keys will be revoked, and usage history will be kept.'
        )}
        footer={
          <>
            <button type="button" className="btn btn-secondary" onClick={closeRemoveSiteModal} disabled={isRemovingSite}>
              {t('common.cancel')}
            </button>
            <button type="button" className="btn btn-danger" onClick={() => void handleRemoveSite()} disabled={isRemovingSite}>
              {isRemovingSite ? t('common.saving') : t('portal.remove_site_action', {}, 'Remove site')}
            </button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-slate-600 dark:text-slate-300">
          <p className="font-semibold text-slate-950 dark:text-white">
            {getPortalSiteDisplayName(pendingRemoveSite)}
          </p>
          {pendingRemoveSite ? (
            <p className="break-words">
              {getPortalSiteWordPressUrl(pendingRemoveSite) ||
                t('portal.site_url_missing_short', {}, 'Site URL not configured')}
            </p>
          ) : null}
          {removeError ? (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
              {removeError}
            </p>
          ) : null}
        </div>
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
