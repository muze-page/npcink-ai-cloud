'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import {
  getPortalSiteDisplayName,
  getPortalSiteSecondaryLabel,
  getPortalSiteWordPressUrl,
} from '@/lib/portal-site-display';
import { cn, formatDate } from '@/lib/utils';
import {
  portalClient,
  type PortalIdentityProviderStatus,
  type PortalPluginObservabilitySummary,
  type PortalSiteSummaryRecord,
  type Site,
} from '@/lib/portal-client';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { PortalSiteConnectPanel } from '@/components/portal/PortalSiteConnectPanel';
import { PortalEmptyState } from '@/components/portal/PortalPageState';
import { PortalPluginMonitoringPanel } from '@/components/portal/PortalPluginMonitoringPanel';
import { PortalSiteInspectorDrawer } from '@/components/portal/PortalSiteInspectorDrawer';

type RestrictionItem = {
  tone: 'warn' | 'info';
  label: string;
  detail: string;
};

function getHomeRiskLevel({
  selectedSite,
  currentSubscriptionStatus,
  activeKeyCount,
}: {
  selectedSite: Site;
  currentSubscriptionStatus: string;
  activeKeyCount: number | null;
}) {
  if (selectedSite.status !== 'active') return 'setup';
  if (activeKeyCount === 0) return 'setup';
  if (currentSubscriptionStatus && currentSubscriptionStatus !== 'active') return 'package';
  return 'normal';
}

function buildRestrictionItems({
  t,
  siteStatus,
  subscriptionStatus,
  requestLimit,
  tokenLimit,
}: {
  t: (key: string, params?: Record<string, string>, fallback?: string) => string;
  siteStatus: string;
  subscriptionStatus: string;
  requestLimit: number;
  tokenLimit: number;
}): RestrictionItem[] {
  return [
    siteStatus !== 'active'
      ? {
          tone: 'warn',
          label: t('portal.home.restriction_setup_label', {}, 'Site setup still needs attention'),
          detail: t(
            'portal.home.restriction_setup_desc',
            {},
            'This site is not fully active yet. Open API Keys to finish the first key flow and complete hosted service access.'
          ),
        }
      : null,
    subscriptionStatus && subscriptionStatus !== 'active'
      ? {
          tone: 'warn',
          label: t('portal.home.restriction_plan_label', {}, 'Current plan is not fully active'),
          detail: t(
            'portal.home.restriction_plan_desc',
            {},
            'Open Package to review the current coverage state for this site.'
          ),
        }
      : null,
    requestLimit > 0 || tokenLimit > 0
      ? {
          tone: 'info',
          label: t('portal.home.restriction_limit_label', {}, 'Usage is bounded by current limits'),
          detail: t(
            'portal.home.restriction_limit_desc',
            {},
            'Open Usage to compare this period against the request and token limits in your current entitlement.'
          ),
        }
      : null,
  ].filter(Boolean) as RestrictionItem[];
}

export default function PortalPage() {
  const { t } = useLocale();
  const { session, isLoading, isAuthenticated, selectSite } = useSession();
  const [inspectedSiteId, setInspectedSiteId] = useState('');
  const [isInspectorOpen, setIsInspectorOpen] = useState(false);
  const [siteSummaryCache, setSiteSummaryCache] = useState<Record<string, PortalSiteSummaryRecord>>({});
  const [isInspectorLoading, setIsInspectorLoading] = useState(false);
  const [inspectorError, setInspectorError] = useState('');
  const [currentSiteActiveKeyCount, setCurrentSiteActiveKeyCount] = useState<number | null>(null);
  const [currentSiteSummary, setCurrentSiteSummary] = useState<PortalSiteSummaryRecord | null>(null);
  const [currentSiteMonitoring, setCurrentSiteMonitoring] = useState<PortalPluginObservabilitySummary | null>(null);
  const [identityProviders, setIdentityProviders] = useState<PortalIdentityProviderStatus[]>([]);
  const [isMonitoringLoading, setIsMonitoringLoading] = useState(false);
  const [monitoringError, setMonitoringError] = useState('');
  const [monitoringRefreshNonce, setMonitoringRefreshNonce] = useState(0);
  const sessionSiteIdsKey = session?.sites?.map((site) => site.site_id).join('|') || '';

  const handleSiteSelect = async (siteId: string) => {
    try {
      await selectSite(siteId);
    } catch (error) {
      console.error('Failed to select site:', error);
    }
  };

  useEffect(() => {
    if (!isInspectorOpen || !inspectedSiteId || siteSummaryCache[inspectedSiteId]) {
      return;
    }

    let isCancelled = false;
    setIsInspectorLoading(true);
    setInspectorError('');

    void portalClient
      .getSiteSummary(inspectedSiteId)
      .then((response) => {
        if (isCancelled) {
          return;
        }
        setSiteSummaryCache((current) => ({
          ...current,
          [inspectedSiteId]: response.data as PortalSiteSummaryRecord,
        }));
      })
      .catch((error) => {
        if (isCancelled) {
          return;
        }
        console.error('Failed to load site summary:', error);
        setInspectorError(
          t(
            'portal.home.drawer_load_failed',
            {},
            'Failed to load the site summary. Open the full page if you need more detail.'
          )
        );
      })
      .finally(() => {
        if (!isCancelled) {
          setIsInspectorLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [inspectedSiteId, isInspectorOpen, siteSummaryCache, t]);

  const selectedSiteForKeyCheck =
    session?.sites?.find((site) => site.site_id === session.site_id) || session?.sites?.[0] || null;
  const selectedSiteForMonitoringId = selectedSiteForKeyCheck?.site_id || '';

  useEffect(() => {
    if (!selectedSiteForKeyCheck?.site_id) {
      setCurrentSiteActiveKeyCount(null);
      return;
    }

    let isCancelled = false;

    setCurrentSiteActiveKeyCount(null);

    void portalClient
      .listApiKeys(selectedSiteForKeyCheck.site_id)
      .then((response) => {
        if (isCancelled) {
          return;
        }
        const activeKeyCount = Array.isArray(response.data.items)
          ? response.data.items.filter((item) => item.status === 'active').length
          : 0;
        setCurrentSiteActiveKeyCount(activeKeyCount);
      })
      .catch((error) => {
        if (!isCancelled) {
          console.error('Failed to load current site keys:', error);
          setCurrentSiteActiveKeyCount(null);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [selectedSiteForKeyCheck?.site_id]);

  useEffect(() => {
    if (!selectedSiteForKeyCheck?.site_id) {
      setCurrentSiteSummary(null);
      return;
    }

    let isCancelled = false;
    setCurrentSiteSummary(null);

    void portalClient
      .getSiteSummary(selectedSiteForKeyCheck.site_id)
      .then((response) => {
        if (!isCancelled) {
          setCurrentSiteSummary(response.data as PortalSiteSummaryRecord);
        }
      })
      .catch((error) => {
        if (!isCancelled) {
          console.error('Failed to load current site summary:', error);
          setCurrentSiteSummary(null);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [selectedSiteForKeyCheck?.site_id]);

  useEffect(() => {
    if (!selectedSiteForMonitoringId) {
      setCurrentSiteMonitoring(null);
      setMonitoringError('');
      setIsMonitoringLoading(false);
      return;
    }

    let isCancelled = false;
    setIsMonitoringLoading(true);
    setMonitoringError('');

    void portalClient
      .getPluginObservability(selectedSiteForMonitoringId, { windowHours: 24 })
      .then((response) => {
        if (!isCancelled) {
          setCurrentSiteMonitoring(response.data);
        }
      })
      .catch((error) => {
        if (!isCancelled) {
          console.error('Failed to load plugin monitoring:', error);
          setCurrentSiteMonitoring(null);
          setMonitoringError(
            t(
              'portal.monitoring.load_failed',
              {},
              'Plugin monitoring could not be loaded for the current site.'
            )
          );
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setIsMonitoringLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [monitoringRefreshNonce, selectedSiteForMonitoringId, t]);

  useEffect(() => {
    if (!isAuthenticated || !sessionSiteIdsKey || !session?.sites?.length) {
      return;
    }

    let isCancelled = false;
    const siteIds = session.sites
      .filter((site) => site.status !== 'archived')
      .slice(0, 12)
      .map((site) => site.site_id);

    void Promise.allSettled(siteIds.map((siteId) => portalClient.getSiteSummary(siteId))).then((results) => {
      if (isCancelled) {
        return;
      }
      setSiteSummaryCache((current) => {
        const next = { ...current };
        results.forEach((result, index) => {
          if (result.status === 'fulfilled') {
            next[siteIds[index]] = result.value.data as PortalSiteSummaryRecord;
          }
        });
        return next;
      });
    });

    return () => {
      isCancelled = true;
    };
  }, [isAuthenticated, session?.sites, sessionSiteIdsKey]);

  useEffect(() => {
    if (!isAuthenticated) {
      setIdentityProviders([]);
      return;
    }

    let isCancelled = false;

    void portalClient
      .getIdentityProviders()
      .then((response) => {
        if (!isCancelled) {
          setIdentityProviders(response.data?.providers || []);
        }
      })
      .catch((error) => {
        if (!isCancelled) {
          console.error('Failed to load identity provider status:', error);
          setIdentityProviders([]);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [isAuthenticated]);

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <div className="mb-4 text-4xl">⏳</div>
          <p className="text-gray-600 dark:text-gray-400">{t('common.loading')}</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated || !session) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold">{t('auth.not_signed_in')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{t('auth.please_sign_in')}</p>
          <Link href="/portal/login" className="btn btn-primary">
            {t('nav.sign_in')}
          </Link>
        </div>
      </div>
    );
  }

  if (!session.sites || session.sites.length === 0) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="surface-panel max-w-2xl p-8">
          <PortalEmptyState
            title={t('portal.no_sites')}
            description={t(
              'portal.home.no_sites_empty_desc',
              {},
              'You do not have a connected site yet, so the workspace cannot show package, usage, or key activity. Connect a site first.'
            )}
          />
          <div className="mt-6">
            <PortalSiteConnectPanel accountId={session.account_id || ''} currentSiteId="" sites={[]} />
          </div>
        </div>
      </div>
    );
  }

  const visibleSites = session.sites.filter((site) => site.status !== 'archived');
  if (visibleSites.length === 0) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="surface-panel max-w-2xl p-8">
          <PortalEmptyState
            title={t('portal.no_active_sites_title', {}, 'No active sites in the workspace')}
            description={t(
              'portal.no_active_sites_desc',
              {},
              'All of your current sites are archived. Open the site register to restore one or connect another site.'
            )}
            actionLabel={t('portal.nav_sites', {}, 'Sites')}
            actionHref="/portal/sites"
          />
        </div>
      </div>
    );
  }

  const selectedSite =
    visibleSites.find((s) => s.site_id === session.site_id) || visibleSites[0];
  const selectedSiteStatus = t(`status.${selectedSite.status}`, undefined, selectedSite.status);
  const selectedAccount =
    session.accounts?.find((account) => account.account_id === selectedSite.account_id) || null;
  const currentAccountLabel =
    selectedAccount?.name || selectedSite.account_id || session.account_id || t('common.not_found');
  const currentSubscription = session.current_subscription;
  const currentSubscriptionStatus =
    currentSubscription?.status || t('common.not_found');
  const selectedSiteWordPressUrl = getPortalSiteWordPressUrl(selectedSite);
  const currentPackageDisplay = resolveCustomerPackageDisplay(t, {
    planId: currentSiteSummary?.coverage?.plan_id || currentSubscription?.plan_id,
    planVersionId: currentSiteSummary?.coverage?.plan_version_id || currentSubscription?.plan_version_id,
    packageAlias: currentSiteSummary?.coverage?.package_alias || currentSubscription?.package_alias,
    formalPlanName: selectedSite.plan_name,
    planKind: currentSubscription?.plan_kind,
    coverageState: currentSiteSummary?.coverage || currentSubscription ? 'covered' : 'uncovered',
  });
  const getCachedSiteSummary = (site: Site) =>
    site.site_id === selectedSite.site_id ? currentSiteSummary || siteSummaryCache[site.site_id] || null : siteSummaryCache[site.site_id] || null;
  const getCachedSiteCoverage = (site: Site) => getCachedSiteSummary(site)?.coverage || null;
  const hasCachedSiteCoverage = (site: Site) => Boolean(getCachedSiteCoverage(site) || site.plan_name);
  const resolveSitePackageDisplay = (site: Site) => {
    const summary = getCachedSiteSummary(site);
    const coverage = summary?.coverage || null;
    const isCurrent = selectedSite.site_id === site.site_id;
    return resolveCustomerPackageDisplay(t, {
      planId: coverage?.plan_id || (isCurrent ? currentSubscription?.plan_id : undefined),
      planVersionId: coverage?.plan_version_id || (isCurrent ? currentSubscription?.plan_version_id : undefined),
      packageAlias: coverage?.package_alias || summary?.package_alias || (isCurrent ? currentSubscription?.package_alias : undefined),
      formalPlanName: summary?.site?.plan_name || site.plan_name,
      planKind: isCurrent ? currentSubscription?.plan_kind : undefined,
      coverageState: coverage || site.plan_name || isCurrent ? 'covered' : 'uncovered',
    });
  };
  const entitlementFeatureCount = Array.isArray(session.entitlements?.features)
    ? session.entitlements.features.length
    : 0;
  const requestLimit = Number(session.entitlements?.requests_limit || 0);
  const tokenLimit = Number(session.entitlements?.tokens_limit || 0);
  const restrictionItems = buildRestrictionItems({
    t,
    siteStatus: selectedSite.status,
    subscriptionStatus: currentSubscription?.status || '',
    requestLimit,
    tokenLimit,
  });
  const inspectedSite = session.sites.find((site) => site.site_id === inspectedSiteId) || null;
  const inspectedSummary = inspectedSiteId ? siteSummaryCache[inspectedSiteId] || null : null;
  const inspectorRestrictions = inspectedSite
    ? buildRestrictionItems({
        t,
        siteStatus: inspectedSummary?.site.status || inspectedSite.status,
        subscriptionStatus: inspectedSummary?.subscription_status || inspectedSummary?.coverage?.status || '',
        requestLimit: Number(inspectedSummary?.entitlement_snapshot?.requests_limit || 0),
        tokenLimit: Number(inspectedSummary?.entitlement_snapshot?.tokens_limit || 0),
      })
    : [];

  const openInspector = (siteId: string) => {
    setInspectedSiteId(siteId);
    setIsInspectorOpen(true);
  };

  const allSites = session.sites;
  const inspectedIndex = allSites.findIndex((site) => site.site_id === inspectedSiteId);
  const previousSiteId = inspectedIndex > 0 ? allSites[inspectedIndex - 1]?.site_id || '' : '';
  const nextSiteId =
    inspectedIndex >= 0 && inspectedIndex < allSites.length - 1
      ? allSites[inspectedIndex + 1]?.site_id || ''
      : '';

  const closeInspector = () => {
    setIsInspectorOpen(false);
    setInspectorError('');
  };

  const restrictedCount = visibleSites.filter((site) => site.status !== 'active' || !hasCachedSiteCoverage(site)).length;
  const clearCount = visibleSites.length - restrictedCount;
  const archivedCount = session.sites.filter((site) => site.status === 'archived').length;
  const uncoveredCount = visibleSites.filter((site) => !hasCachedSiteCoverage(site)).length;
  const missingUrlCount = visibleSites.filter((site) => !getPortalSiteWordPressUrl(site)).length;
  const sitePreviewLimit = 3;
  const previewSites = [...visibleSites]
    .sort((left, right) => {
      const leftPriority =
        left.site_id === selectedSite.site_id ? 0 : left.status !== 'active' || !hasCachedSiteCoverage(left) || !getPortalSiteWordPressUrl(left) ? 1 : 2;
      const rightPriority =
        right.site_id === selectedSite.site_id ? 0 : right.status !== 'active' || !hasCachedSiteCoverage(right) || !getPortalSiteWordPressUrl(right) ? 1 : 2;
      if (leftPriority !== rightPriority) {
        return leftPriority - rightPriority;
      }
      return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
    })
    .slice(0, sitePreviewLimit);
  const hasHiddenSites = visibleSites.length > previewSites.length;
  const currentRiskLevel = getHomeRiskLevel({
    selectedSite,
    currentSubscriptionStatus: currentSubscription?.status || '',
    activeKeyCount: currentSiteActiveKeyCount,
  });
  const shouldShowStatusPanel = currentRiskLevel !== 'normal';
  const qqProvider = identityProviders.find((provider) => provider.provider === 'qq') || null;
  const setupChecklistItems = [
    {
      key: 'site',
      done: selectedSite.status === 'active' && Boolean(selectedSiteWordPressUrl),
      title: t('portal.home.onboarding_site_title', {}, '确认站点'),
      detail: selectedSiteWordPressUrl
        ? t('portal.home.onboarding_site_ready', {}, '站点地址已记录，当前站点可用于 Portal 工作区。')
        : t('portal.home.onboarding_site_needed', {}, '补齐 WordPress 站点地址，后续 Key 和用量才容易核对。'),
      href: `/portal/sites/${selectedSite.site_id}`,
      action: t('portal.home.onboarding_site_action', {}, '查看站点'),
    },
    {
      key: 'key',
      done: currentSiteActiveKeyCount !== null && currentSiteActiveKeyCount > 0,
      title: t('portal.home.onboarding_key_title', {}, '创建 API Key'),
      detail:
        currentSiteActiveKeyCount !== null && currentSiteActiveKeyCount > 0
          ? t('portal.home.onboarding_key_ready', {}, '当前站点已有可用 Key。')
          : t('portal.home.onboarding_key_needed', {}, '创建第一个 Key，WordPress 站点才能调用 Cloud 服务。'),
      href: `/portal/keys?site=${selectedSite.site_id}`,
      action: t('portal.home.onboarding_key_action', {}, '打开 Key'),
    },
    {
      key: 'package',
      done: Boolean(currentSubscription?.status === 'active'),
      title: t('portal.home.onboarding_package_title', {}, '查看 Free 套餐'),
      detail:
        currentSubscription?.status === 'active'
          ? t('portal.home.onboarding_package_ready', {}, '当前套餐处于可用状态。')
          : t('portal.home.onboarding_package_needed', {}, '查看当前套餐和额度，确认本周期可用范围。'),
      href: `/portal/billing?site=${selectedSite.site_id}`,
      action: t('portal.home.onboarding_package_action', {}, '查看套餐'),
    },
    {
      key: 'qq',
      done: Boolean(qqProvider?.bound),
      title: t('portal.home.onboarding_qq_title', {}, '绑定 QQ 快捷登录'),
      detail: qqProvider?.bound
        ? t('portal.home.onboarding_qq_ready', {}, 'QQ 快捷登录已绑定，后续可直接使用 QQ 登录。')
        : t('portal.home.onboarding_qq_needed', {}, '邮箱仍是主账号，绑定 QQ 后登录更方便。'),
      href: '/portal/account',
      action: t('portal.home.onboarding_qq_action', {}, '账号中心'),
    },
  ];
  const completedSetupCount = setupChecklistItems.filter((item) => item.done).length;
  const shouldShowOnboardingChecklist = completedSetupCount < setupChecklistItems.length;

  return (
    <BackofficePageStack>
      <PortalSiteInspectorDrawer
        isOpen={isInspectorOpen}
        onClose={closeInspector}
        site={inspectedSite}
        summary={inspectedSummary}
        isLoading={isInspectorLoading}
        error={inspectorError}
        restrictions={inspectorRestrictions}
        isCurrentSite={inspectedSiteId === selectedSite.site_id}
        onSelectCurrentSite={handleSiteSelect}
        previousSiteId={previousSiteId}
        nextSiteId={nextSiteId}
        onNavigateSite={openInspector}
        t={t}
      />
      <section className="space-y-5">
        <BackofficeSectionPanel>
          <div className="grid gap-5 xl:grid-cols-[minmax(13rem,0.55fr)_minmax(0,1.45fr)_auto] xl:items-center">
            <div className="min-w-0">
              <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('portal.workspace_label', {}, 'Workspace')}
              </p>
              <h1 className="mt-2 text-2xl font-semibold text-gray-950 dark:text-white">
                {t('portal.home.title', {}, 'Workspace')}
              </h1>
            </div>
            <div className="grid min-w-0 gap-3 md:grid-cols-3">
              <div className="min-w-0 rounded-[1rem] border border-slate-200/80 bg-white/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45">
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                  {t('portal.home.current_site_title', {}, 'Current site')}
                </p>
                <div className="mt-2 flex min-w-0 items-center gap-2">
                  <p className="truncate text-base font-semibold text-gray-950 dark:text-white">
                    {getPortalSiteDisplayName(selectedSite)}
                  </p>
                  <BackofficeStatusBadge
                    status={selectedSite.status === 'active' ? 'active' : 'warning'}
                    label={
                      selectedSite.status === 'active'
                        ? t('portal.home.service_status_live', {}, 'Ready')
                        : t('portal.home.service_status_attention', {}, 'Needs attention')
                    }
                    className="shrink-0 text-[0.68rem]"
                  />
                </div>
                <p className="mt-1 truncate text-xs text-gray-600 dark:text-gray-400">
                  {selectedSiteWordPressUrl ||
                    getPortalSiteSecondaryLabel(selectedSite) ||
                    t('portal.site_url_missing', {}, 'WordPress URL not configured')}
                </p>
              </div>
              <div className="min-w-0 rounded-[1rem] border border-slate-200/80 bg-white/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45">
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                  {t('common.plan')}
                </p>
                <p className="mt-2 truncate text-base font-semibold text-gray-950 dark:text-white">
                  {currentPackageDisplay.display_package_label || t('common.not_found')}
                </p>
                <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                  {t('portal.current_subscription_label', {}, 'Current package')}
                </p>
              </div>
              <div className="min-w-0 rounded-[1rem] border border-slate-200/80 bg-white/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45">
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                  {t('common.status')}
                </p>
                <p className="mt-2 truncate text-base font-semibold text-gray-950 dark:text-white">
                  {selectedSiteStatus}
                </p>
                <p className="mt-1 truncate text-xs text-gray-600 dark:text-gray-400">
                  {currentSubscription?.status && currentSubscription?.status !== selectedSite.status
                    ? t(`status.${currentSubscription.status}`, undefined, currentSubscription.status)
                    : t('portal.home.service_status_desc', {}, 'Current service status for this site.')}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 xl:justify-end">
              <div className="w-full text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400 xl:text-right">
                {t('portal.home.next_action_label', {}, 'Next action')}
              </div>
              <Link href={`/portal/keys?site=${selectedSite.site_id}`} className="btn btn-primary btn-sm">
                {t('portal.home.open_keys_action', {}, 'Open Keys')}
              </Link>
              <Link href={`/portal/sites/${selectedSite.site_id}`} className="btn btn-secondary btn-sm">
                {t('portal.nav_sites', {}, 'Sites')}
              </Link>
            </div>
          </div>
        </BackofficeSectionPanel>

        {shouldShowStatusPanel ? (
          <BackofficeSectionPanel className="space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('common.status')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('portal.home.current_status_title', {}, 'Current status')}
                </h2>
              </div>
            </div>
            <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {t(`portal.home.risk_level_${currentRiskLevel}`, {}, 'Status')}
                  </p>
                  <p className="mt-3 text-lg font-semibold text-gray-950 dark:text-white">
                    {restrictionItems[0]?.label || t('portal.home.recent_issues_empty_title', {}, 'No active restrictions')}
                  </p>
                  <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
                    {restrictionItems[0]?.detail ||
                      t('portal.home.recent_issues_empty_desc', {}, 'The current site looks ready for normal usage. Open Usage or Package if you need more detail.')}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 lg:justify-end">
                  <Link href={`/portal/usage?site=${selectedSite.site_id}`} className="btn btn-secondary btn-sm">
                    {t('portal.home.usage_action', {}, 'View Usage')}
                  </Link>
                  <Link href={`/portal/billing?site=${selectedSite.site_id}`} className="btn btn-secondary btn-sm">
                    {t('portal.home.billing_action', {}, 'View Billing')}
                  </Link>
                  <Link href={`/portal/keys?site=${selectedSite.site_id}`} className="btn btn-secondary btn-sm">
                    {t('portal.home.keys_action', {}, 'Manage Keys')}
                  </Link>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2 text-xs text-gray-500 dark:text-gray-400">
                <span>{requestLimit > 0 ? `${requestLimit} ${t('common.requests')}` : t('common.not_found')}</span>
                <span>{tokenLimit > 0 ? `${tokenLimit} ${t('common.tokens')}` : t('common.not_found')}</span>
                <span>
                  {currentSubscription?.current_period_start && currentSubscription?.current_period_end
                    ? `${formatDate(currentSubscription.current_period_start)} - ${formatDate(currentSubscription.current_period_end)}`
                    : t('common.not_found')}
                </span>
              </div>
            </BackofficeStackCard>
          </BackofficeSectionPanel>
        ) : null}

        {shouldShowOnboardingChecklist ? (
          <BackofficeSectionPanel className="space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('portal.home.onboarding_label', {}, 'Getting started')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('portal.home.onboarding_title', {}, '首次使用清单')}
                </h2>
                <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
                  {t(
                    'portal.home.onboarding_desc',
                    {},
                    '按顺序完成这些动作，Free 账号就能进入可用状态。'
                  )}
                </p>
              </div>
              <BackofficeTag tone={completedSetupCount === setupChecklistItems.length ? 'success' : 'info'}>
                {completedSetupCount} / {setupChecklistItems.length}
              </BackofficeTag>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              {setupChecklistItems.map((item, index) => (
                <Link
                  key={item.key}
                  href={item.href}
                  className={cn(
                    'group flex min-h-32 gap-4 rounded-[1.1rem] border px-4 py-4 transition hover:-translate-y-0.5 hover:shadow-sm',
                    item.done
                      ? 'border-emerald-200 bg-emerald-50/65 dark:border-emerald-900/60 dark:bg-emerald-950/20'
                      : 'border-slate-200/80 bg-white/85 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950/45 dark:hover:bg-slate-900/60'
                  )}
                >
                  <span
                    className={cn(
                      'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-sm font-semibold',
                      item.done
                        ? 'border-emerald-500 bg-emerald-500 text-white'
                        : 'border-slate-300 bg-white text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'
                    )}
                  >
                    {item.done ? 'OK' : String(index + 1)}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-base font-semibold text-slate-950 dark:text-white">
                      {item.title}
                    </span>
                    <span className="mt-2 block text-sm leading-6 text-slate-600 dark:text-slate-300">
                      {item.detail}
                    </span>
                    <span className="mt-3 inline-flex text-sm font-semibold text-blue-700 group-hover:text-blue-800 dark:text-blue-300 dark:group-hover:text-blue-200">
                      {item.action}
                    </span>
                  </span>
                </Link>
              ))}
            </div>
          </BackofficeSectionPanel>
        ) : null}
      </section>

      <div className="space-y-5">
        <PortalPluginMonitoringPanel
          siteId={selectedSite.site_id}
          summary={currentSiteMonitoring}
          isLoading={isMonitoringLoading}
          error={monitoringError}
          compact
          onRetry={() => setMonitoringRefreshNonce((current) => current + 1)}
        />

        <BackofficeSectionPanel className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-4">
            <Link href="/portal/sites?filter=active" className="rounded-[1.25rem] border border-slate-200/80 bg-white/85 px-4 py-4 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950/40 dark:hover:bg-slate-900/60">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('portal.active_sites_filter', {}, 'Active')}</p>
              <p className="mt-2 text-2xl font-semibold text-gray-950 dark:text-white">{visibleSites.length}</p>
            </Link>
            <Link href="/portal/sites?filter=archived" className="rounded-[1.25rem] border border-slate-200/80 bg-white/85 px-4 py-4 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950/40 dark:hover:bg-slate-900/60">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('portal.archived_sites_filter', {}, 'Archived')}</p>
              <p className="mt-2 text-2xl font-semibold text-gray-950 dark:text-white">{archivedCount}</p>
            </Link>
            <Link href="/portal/sites?filter=uncovered" className="rounded-[1.25rem] border border-slate-200/80 bg-white/85 px-4 py-4 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950/40 dark:hover:bg-slate-900/60">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('portal.uncovered_sites_filter', {}, 'Uncovered')}</p>
              <p className="mt-2 text-2xl font-semibold text-gray-950 dark:text-white">{uncoveredCount}</p>
            </Link>
            <Link href="/portal/sites?filter=missing_url" className="rounded-[1.25rem] border border-slate-200/80 bg-white/85 px-4 py-4 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950/40 dark:hover:bg-slate-900/60">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">{t('portal.missing_url_sites_filter', {}, 'Missing URL')}</p>
              <p className="mt-2 text-2xl font-semibold text-gray-950 dark:text-white">{missingUrlCount}</p>
            </Link>
          </div>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('portal.site_register', {}, 'Sites')}
              </p>
              <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                {t('portal.home.my_sites_title', {}, 'My sites')}
              </h2>
            </div>
              <div className="flex flex-wrap items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                <BackofficeTag>
                {previewSites.length} / {visibleSites.length} {t('common.site')}
                </BackofficeTag>
                <BackofficeTag tone="warning">
                  {restrictedCount} {t('portal.home.filter_attention_only', {}, 'Needs attention')}
                </BackofficeTag>
                <BackofficeTag tone="success">
                  {clearCount} {t('portal.home.filter_clear', {}, 'Clear')}
                </BackofficeTag>
              </div>
            </div>

          <div className={cn(
            'overflow-hidden rounded-[1.4rem] border border-slate-200/80 transition-shadow dark:border-slate-800'
          )}>
            <div className="hidden grid-cols-[minmax(0,1.8fr)_120px_140px_240px] gap-4 border-b border-slate-200/80 bg-slate-50/70 px-4 py-3 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:border-slate-800 dark:bg-slate-950/45 dark:text-gray-400 lg:grid">
              <span>{t('common.site')}</span>
              <span>{t('common.status')}</span>
              <span>{t('common.plan')}</span>
              <span>{t('common.actions')}</span>
            </div>

            <div className="divide-y divide-slate-200/80 dark:divide-slate-800">
              {previewSites.map((site) => {
                const isCurrent = session.site_id === site.site_id;
                const hasAttention = site.status !== 'active' || !hasCachedSiteCoverage(site);
                const sitePackageDisplay = resolveSitePackageDisplay(site);
                return (
                  <div
                    key={site.site_id}
                    role="button"
                    tabIndex={0}
                    aria-label={`${getPortalSiteDisplayName(site)} ${t('common.view', {}, 'View')}`}
                    onClick={() => openInspector(site.site_id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        openInspector(site.site_id);
                      }
                    }}
                    className={cn(
                      'group grid cursor-pointer gap-3 px-4 py-4 transition-all active:translate-y-px lg:grid-cols-[minmax(0,1.8fr)_120px_140px_240px] lg:items-center',
                      isCurrent
                        ? 'border-l-4 border-[color:var(--brand-primary)] bg-[color:var(--surface-raised)] ring-1 ring-[color:var(--brand-primary-soft)]'
                        : hasAttention
                          ? 'border-l-4 border-amber-300 bg-amber-50/40 hover:bg-amber-50/70 dark:border-amber-900/60 dark:bg-amber-950/10 dark:hover:bg-amber-950/20'
                          : 'border-l-4 border-transparent bg-white/80 hover:bg-slate-50/90 dark:bg-slate-950/35 dark:hover:bg-slate-900/60'
                    )}
                  >
                    <div className="min-w-0 text-left">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate font-semibold text-gray-950 dark:text-white">
                          {getPortalSiteDisplayName(site)}
                        </p>
                        {isCurrent ? (
                          <BackofficeTag tone="info" className="uppercase tracking-[0.16em]">
                            {t('common.current', {}, 'Current')}
                          </BackofficeTag>
                        ) : hasAttention ? (
                          <BackofficeTag tone="warning" className="uppercase tracking-[0.16em]">
                            {t('portal.home.filter_attention_only', {}, 'Needs attention')}
                          </BackofficeTag>
                        ) : null}
                      </div>
                      <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                        {getPortalSiteWordPressUrl(site) ||
                          getPortalSiteSecondaryLabel(site) ||
                          t('portal.site_url_missing', {}, 'WordPress URL not configured')}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400 lg:hidden">
                        <span>{t('common.status')}: {t(`status.${site.status}`, undefined, site.status)}</span>
                        <span>{t('common.plan')}: {sitePackageDisplay.display_package_label || t('common.not_found')}</span>
                        <span>{t('common.connected_on', { date: formatDate(site.created_at) })}</span>
                      </div>
                      <p className="mt-2 hidden text-xs text-gray-500 dark:text-gray-400 lg:block">
                        {t('common.connected_on', { date: formatDate(site.created_at) })}
                      </p>
                    </div>

                    <div className="hidden lg:block">
                      <BackofficeStatusBadge
                        status={site.status}
                        label={t(`status.${site.status}`, undefined, site.status)}
                        className="text-[0.68rem]"
                      />
                    </div>

                    <div className="hidden text-sm text-gray-700 dark:text-gray-300 lg:block">
                      {sitePackageDisplay.display_package_label || t('common.not_found')}
                    </div>
                    <div className="flex flex-wrap gap-2 lg:col-start-5 lg:justify-end">
                      <Link
                        href={`/portal/sites/${site.site_id}`}
                        onClick={(event) => event.stopPropagation()}
                        className="btn btn-secondary btn-sm"
                      >
                        {t('portal.site_record', {}, 'Site record')}
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
            {hasHiddenSites ? (
              <div className="border-t border-slate-200/80 bg-slate-50/60 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/35">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm text-gray-600 dark:text-gray-300">
                    {t(
                      'portal.home.view_all_sites_desc',
                      { count: String(visibleSites.length - previewSites.length) },
                      `There are ${visibleSites.length - previewSites.length} more sites in the full register.`
                    )}
                  </p>
                  <Link href="/portal/sites" className="btn btn-secondary btn-sm">
                    {t('portal.home.view_all_sites', {}, 'View all sites')}
                  </Link>
                </div>
              </div>
            ) : null}
          </div>
        </BackofficeSectionPanel>
      </div>
    </BackofficePageStack>
  );
}
