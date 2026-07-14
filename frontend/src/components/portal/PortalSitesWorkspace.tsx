'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useMemo, useState } from 'react';
import { PortalSection, PortalCard } from '@/components/portal/PortalScaffold';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import { PortalTag } from '@/components/portal/PortalTag';
import { PortalEmptyState } from '@/components/portal/PortalPageState';
import { PortalSiteConnectPanel } from '@/components/portal/PortalSiteConnectPanel';
import { Modal } from '@/components/ui/Modal';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  getPortalSiteDisplayName,
  getPortalSiteWordPressUrl,
  getVisiblePortalSites,
  portalSiteNeedsAttention,
} from '@/lib/portal-site-display';
import { portalClient, type PortalSiteSummaryRecord, type Site } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatDate } from '@/lib/utils';

type PortalSitesWorkspaceProps = {
  siteSummaries?: Record<string, PortalSiteSummaryRecord>;
};

function workspaceSiteNeedsAttention(
  site: Site,
  siteSummaries: Record<string, PortalSiteSummaryRecord>
): boolean {
  return portalSiteNeedsAttention(site)
    || Boolean(siteSummaries[site.site_id]?.customer_status?.needs_attention);
}

function PortalSitesWorkspaceContent({ siteSummaries = {} }: PortalSitesWorkspaceProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isAuthenticated, refresh } = useSession();
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('q') || '');
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [pendingRemoveSite, setPendingRemoveSite] = useState<Site | null>(null);
  const [removeError, setRemoveError] = useState('');
  const [removeNotice, setRemoveNotice] = useState('');
  const [isRemovingSite, setIsRemovingSite] = useState(false);
  const sites = session?.sites || [];
  const visibleSites = getVisiblePortalSites(sites);
  const portalAccountId = session?.account_id
    || session?.accounts?.find((account) => account.account_id)?.account_id
    || '';
  const canRemoveSites = Boolean(
    session?.allowed_actions?.includes('remove_sites')
    || session?.accounts?.some((account) => account.allowed_actions?.includes('remove_sites'))
  );
  const addonConnectMode = searchParams.get('connect') === 'wordpress-addon';
  const addonWordPressUrl = searchParams.get('site_url') || '';
  const addonSiteName = searchParams.get('site_name') || '';
  const addonReturnUrl = searchParams.get('return_url') || '';
  const addonState = searchParams.get('state') || '';

  const filteredSites = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return visibleSites.filter((site) => {
      if (!query) return true;
      const siteUrl = getPortalSiteWordPressUrl(site);
      return getPortalSiteDisplayName(site).toLowerCase().includes(query)
        || siteUrl.toLowerCase().includes(query);
    });
  }, [searchQuery, visibleSites]);
  const sortedSites = useMemo(() => {
    return [...filteredSites].sort((left, right) => {
      const attentionDelta = Number(workspaceSiteNeedsAttention(right, siteSummaries))
        - Number(workspaceSiteNeedsAttention(left, siteSummaries));
      if (attentionDelta !== 0) return attentionDelta;
      return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
    });
  }, [filteredSites, siteSummaries]);
  const restrictedCount = visibleSites.filter((site) => workspaceSiteNeedsAttention(site, siteSummaries)).length;
  const clearCount = visibleSites.length - restrictedCount;

  useEffect(() => {
    setSearchQuery(searchParams.get('q') || '');
  }, [searchParams]);

  useEffect(() => {
    if (addonConnectMode && isAuthenticated) {
      setShowConnectModal(true);
    }
  }, [addonConnectMode, isAuthenticated]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams.toString());
    if (searchQuery.trim()) {
      params.set('q', searchQuery.trim());
    } else {
      params.delete('q');
    }
    const nextQuery = params.toString();
    if (nextQuery !== searchParams.toString()) {
      router.replace(`${pathname}${nextQuery ? `?${nextQuery}` : ''}#sites`, { scroll: false });
    }
  }, [pathname, router, searchParams, searchQuery]);

  const handleSiteCreated = async () => {
    await refresh();
    setShowConnectModal(false);
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
      setRemoveNotice(
        t('portal.site_remove_success', {}, 'Site removed. Active keys were revoked and history was kept.')
      );
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
    <section id="sites" className="scroll-mt-24" data-portal-home="sites-workspace">
      <PortalSection className="space-y-4" variant="portal">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
              {t('portal.site_register', {}, 'Sites')}
            </p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950 dark:text-white">
              {t('portal.home.my_sites_title', {}, 'My sites')}
            </h2>
            <div className="mt-3 flex flex-wrap gap-2">
              <PortalTag>{visibleSites.length} {t('common.site')}</PortalTag>
              <PortalTag tone="warning">
                {restrictedCount} {t('portal.home.filter_attention_only', {}, 'Needs attention')}
              </PortalTag>
              <PortalTag tone="success">
                {clearCount} {t('portal.home.filter_clear', {}, 'Clear')}
              </PortalTag>
            </div>
          </div>
          <div className="w-full lg:max-w-sm">
            <label htmlFor="portal-service-site-search" className="sr-only">
              {t('portal.home.search_sites_placeholder', {}, 'Search site name or URL')}
            </label>
            <input
              id="portal-service-site-search"
              type="search"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder={t('portal.home.search_sites_placeholder', {}, 'Search site name or URL')}
              className="input"
            />
          </div>
        </div>

        {visibleSites.length === 0 && !searchQuery.trim() ? (
          <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-950 dark:border-blue-900/50 dark:bg-blue-950/30 dark:text-blue-100">
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
        ) : null}

        {removeNotice ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-100">
            {removeNotice}
          </div>
        ) : null}

        <div className="grid gap-3">
          {sortedSites.length === 0 ? (
            <PortalEmptyState
              title={visibleSites.length
                ? t('portal.sites.empty_title', {}, 'No sites match this search')
                : t('portal.no_sites', {}, 'No sites')}
              description={visibleSites.length
                ? t('portal.sites.empty_desc', {}, 'No connected site matches the current search term. Clear the search to see every site.')
                : t('portal.home.no_sites_empty_desc', {}, 'Open npcink-cloud-addon in WordPress and start the connection there.')}
            />
          ) : sortedSites.map((site) => (
            <PortalCard key={site.site_id} variant="portal">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="truncate text-lg font-semibold text-slate-950 dark:text-white">
                      {getPortalSiteDisplayName(site)}
                    </p>
                    <PortalStatusBadge
                      status={workspaceSiteNeedsAttention(site, siteSummaries) ? 'warning' : 'active'}
                      label={workspaceSiteNeedsAttention(site, siteSummaries)
                        ? t('portal.home.filter_attention_only', {}, 'Needs attention')
                        : t('portal.home.risk_level_normal', {}, 'Normal')}
                      className="normal-case tracking-normal"
                    />
                  </div>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                    {getPortalSiteWordPressUrl(site)
                      || t('portal.site_url_missing_short', {}, 'Site URL not configured')}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {t('site_details.connected', {}, 'Connected')} {formatDate(site.created_at)}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                  <Link href={`/portal/sites/${site.site_id}`} className="btn btn-secondary btn-sm">
                    {t('portal.site_record', {}, 'Site record')}
                  </Link>
                  {canRemoveSites && site.status !== 'suspended' ? (
                    <button
                      type="button"
                      onClick={() => {
                        setRemoveError('');
                        setPendingRemoveSite(site);
                      }}
                      className="btn btn-secondary btn-sm text-red-700 hover:border-red-300 hover:bg-red-50 dark:text-red-300 dark:hover:border-red-900 dark:hover:bg-red-950/30"
                    >
                      {t('portal.remove_site_action', {}, 'Remove site')}
                    </button>
                  ) : null}
                </div>
              </div>
            </PortalCard>
          ))}
        </div>
      </PortalSection>

      <Modal
        isOpen={addonConnectMode && showConnectModal}
        onClose={() => setShowConnectModal(false)}
        closeLabel={t('common.close', {}, 'Close')}
        title={t('portal.connect_site_addon_title', undefined, 'Finish WordPress connection')}
        description={t('portal.connect_site_addon_desc', undefined, 'Confirm this site connection, then return to WordPress to finish setup.')}
        size="lg"
        className="portal-commercial-dialog rounded-[18px] shadow-[0_16px_44px_rgba(15,23,42,0.14)]"
      >
        {portalAccountId ? (
          <PortalSiteConnectPanel
            accountId={portalAccountId}
            sites={sites}
            onSiteCreated={() => void handleSiteCreated()}
            mode="modal"
            onClose={() => setShowConnectModal(false)}
            initialWordPressUrl={addonWordPressUrl}
            initialSiteName={addonSiteName}
            addonReturnUrl={addonReturnUrl}
            addonState={addonState}
          />
        ) : (
          <PortalEmptyState
            title={t('portal.connect_site_account_required_title', {}, 'Customer account missing')}
            description={t('portal.connect_site_account_required_desc', {}, 'Your signed-in user has no active customer account. Please create a service center account, then restart the WordPress addon connection.')}
          />
        )}
      </Modal>

      <Modal
        isOpen={Boolean(pendingRemoveSite)}
        onClose={closeRemoveSiteModal}
        closeLabel={t('common.close', {}, 'Close')}
        closeOnOverlay={!isRemovingSite}
        title={t('portal.remove_site_action', {}, 'Remove site')}
        description={t('portal.remove_site_confirm', {}, 'Remove this site? Cloud service will stop, active keys will be revoked, and usage history will be kept.')}
        className="portal-commercial-dialog rounded-[18px] shadow-[0_16px_44px_rgba(15,23,42,0.14)]"
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
              {getPortalSiteWordPressUrl(pendingRemoveSite)
                || t('portal.site_url_missing_short', {}, 'Site URL not configured')}
            </p>
          ) : null}
          {removeError ? (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
              {removeError}
            </p>
          ) : null}
        </div>
      </Modal>
    </section>
  );
}

export function PortalSitesWorkspace({ siteSummaries = {} }: PortalSitesWorkspaceProps) {
  return (
    <Suspense fallback={<div className="h-48 rounded-[18px] bg-slate-100 dark:bg-slate-900" aria-hidden="true" />}>
      <PortalSitesWorkspaceContent siteSummaries={siteSummaries} />
    </Suspense>
  );
}
