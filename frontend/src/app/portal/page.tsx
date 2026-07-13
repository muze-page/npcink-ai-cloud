'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import {
  getPortalSiteWordPressUrl,
  getVisiblePortalSites,
  portalSiteNeedsAttention,
} from '@/lib/portal-site-display';
import { cn, formatNumber } from '@/lib/utils';
import {
  portalClient,
  type Entitlements,
  type PortalIdentityProviderStatus,
  type PortalSiteDiagnostics,
  type PortalSiteSummaryRecord,
} from '@/lib/portal-client';
import {
  PortalMetricStrip,
  PortalPageStack,
  PortalSection,
  PortalCard,
} from '@/components/portal/PortalScaffold';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import { PortalTag } from '@/components/portal/PortalTag';
import { PortalSiteInspectorDrawer } from '@/components/portal/PortalSiteInspectorDrawer';
import { PortalSitesWorkspace } from '@/components/portal/PortalSitesWorkspace';

type RestrictionItem = {
  tone: 'warn' | 'info';
  label: string;
  detail: string;
};

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
            'This site is not active yet. Connect or reactivate the WordPress site to enable hosted service access.'
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
            'Open Package to review the current account package state.'
          ),
        }
      : null,
    requestLimit > 0 || tokenLimit > 0
      ? {
          tone: 'info',
          label: t('portal.home.restriction_limit_label', {}, 'Package usage is limited'),
          detail: t(
            'portal.home.restriction_limit_desc',
            {},
            'Open Usage to see what is left in the current package period.'
          ),
        }
      : null,
  ].filter(Boolean) as RestrictionItem[];
}

export default function PortalPage() {
  const { t } = useLocale();
  const { session, isLoading, isAuthenticated } = useSession();
  const [inspectedSiteId, setInspectedSiteId] = useState('');
  const [isInspectorOpen, setIsInspectorOpen] = useState(false);
  const [siteSummaryCache, setSiteSummaryCache] = useState<Record<string, PortalSiteSummaryRecord>>({});
  const [isInspectorLoading, setIsInspectorLoading] = useState(false);
  const [inspectorError, setInspectorError] = useState('');
  const [currentSiteDiagnostics, setCurrentSiteDiagnostics] = useState<PortalSiteDiagnostics | null>(null);
  const [identityProviders, setIdentityProviders] = useState<PortalIdentityProviderStatus[]>([]);
  const [openTicketCount, setOpenTicketCount] = useState<number | null>(null);
  const [accountEntitlements, setAccountEntitlements] = useState<Entitlements | null>(null);
  const sessionSiteIdsKey = session?.sites?.map((site) => site.site_id).join('|') || '';

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

  const selectedSiteForContext =
    session?.sites?.find((site) => site.site_id === session.site_id) || session?.sites?.[0] || null;
  const selectedSiteForMonitoringId = selectedSiteForContext?.site_id || '';

  useEffect(() => {
    if (!selectedSiteForMonitoringId) {
      setCurrentSiteDiagnostics(null);
      return;
    }

    let isCancelled = false;
    setCurrentSiteDiagnostics(null);

    void portalClient
      .getSiteDiagnostics(selectedSiteForMonitoringId)
      .then((response) => {
        if (!isCancelled) {
          setCurrentSiteDiagnostics(response.data);
        }
      })
      .catch((error) => {
        if (!isCancelled) {
          console.error('Failed to load current site diagnostics:', error);
          setCurrentSiteDiagnostics(null);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [selectedSiteForMonitoringId]);

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

  useEffect(() => {
    if (!isAuthenticated) {
      setOpenTicketCount(null);
      return;
    }

    let isCancelled = false;

    void portalClient
      .listSupportRequests({ limit: 10 })
      .then((response) => {
        if (isCancelled) {
          return;
        }
        const summary = response.data?.summary || {};
        const fallbackTotal = (response.data?.items || []).filter((item) =>
          item.status === 'open' || item.status === 'in_progress'
        ).length;
        setOpenTicketCount(
          Number(summary.open || 0) + Number(summary.in_progress || 0) || fallbackTotal
        );
      })
      .catch((error) => {
        if (!isCancelled) {
          console.error('Failed to load support request summary:', error);
          setOpenTicketCount(null);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) {
      setAccountEntitlements(null);
      return;
    }

    let isCancelled = false;

    void portalClient
      .getAccountEntitlements()
      .then((response) => {
        if (!isCancelled) {
          setAccountEntitlements(response.data);
        }
      })
      .catch((error) => {
        if (!isCancelled) {
          console.error('Failed to load account entitlements:', error);
          setAccountEntitlements(null);
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

  const visibleSites = getVisiblePortalSites(session.sites);
  const selectedSite =
    visibleSites.find((s) => s.site_id === session.site_id) || visibleSites[0] || null;
  const currentSubscription = session.current_subscription;
  const selectedSiteWordPressUrl = selectedSite ? getPortalSiteWordPressUrl(selectedSite) : '';
  const currentPackageDisplay = resolveCustomerPackageDisplay(t, {
    planId: currentSubscription?.plan_id,
    planVersionId: currentSubscription?.plan_version_id,
    packageAlias: currentSubscription?.package_alias,
    planKind: currentSubscription?.plan_kind,
    coverageState: currentSubscription ? 'covered' : 'uncovered',
  });
  const requestLimit = Number(session.entitlements?.requests_limit || 0);
  const tokenLimit = Number(session.entitlements?.tokens_limit || 0);
  const currentSiteActiveKeyCount =
    typeof currentSiteDiagnostics?.active_key_count === 'number'
      ? currentSiteDiagnostics.active_key_count
      : null;
  const restrictionItems = selectedSite
    ? buildRestrictionItems({
        t,
        siteStatus: selectedSite.status,
        subscriptionStatus: currentSubscription?.status || '',
        requestLimit,
        tokenLimit,
      })
    : [
        {
          tone: 'warn' as const,
          label: t('portal.home.restriction_setup_label', {}, 'Site setup still needs attention'),
          detail: t(
            'portal.home.no_sites_empty_desc',
            {},
            'Open npcink-cloud-addon in WordPress and start the connection there. After binding, this page will show your package, usage, and site status.'
          ),
        },
      ];
  const inspectedSite = (session.sites || []).find((site) => site.site_id === inspectedSiteId) || null;
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

  const allSites = session.sites || [];
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

  const restrictedCount = visibleSites.filter(portalSiteNeedsAttention).length;
  const qqProvider = identityProviders.find((provider) => provider.provider === 'qq') || null;
  const hasPackageLabel = Boolean(currentPackageDisplay.display_package_label);
  const selectedSiteRecordHref = selectedSite ? `/portal/sites/${selectedSite.site_id}` : '/portal#sites';
  const isSelectedSiteConnected =
    Boolean(selectedSite) &&
    selectedSite?.status === 'active' &&
    Boolean(selectedSiteWordPressUrl) &&
    currentSiteActiveKeyCount !== null &&
    currentSiteActiveKeyCount > 0;
  const setupChecklistItems = [
    {
      key: 'site',
      done: isSelectedSiteConnected,
      title: t('portal.home.onboarding_site_title', {}, 'Confirm site connection'),
      detail: isSelectedSiteConnected
        ? t('portal.home.onboarding_site_ready', {}, 'The WordPress site is connected and can use the service.')
        : t('portal.home.onboarding_site_needed', {}, 'Open the WordPress plugin to reconnect the site if the address or service connection is not ready.'),
      href: selectedSiteRecordHref,
      action: t('portal.home.onboarding_site_action', {}, 'View site'),
    },
    {
      key: 'package',
      done: Boolean(currentSubscription?.status === 'active' || hasPackageLabel),
      title: t('portal.home.onboarding_package_title', {}, 'Review Free package'),
      detail:
        currentSubscription?.status === 'active'
          ? t('portal.home.onboarding_package_ready', {}, 'The current package is available.')
          : t('portal.home.onboarding_package_needed', {}, 'Review the current package and what remains this period.'),
      href: '/portal/billing',
      action: t('portal.home.onboarding_package_action', {}, 'View package'),
    },
    {
      key: 'qq',
      done: Boolean(qqProvider?.bound),
      title: t('portal.home.onboarding_qq_title', {}, 'Bind QQ quick login'),
      detail: qqProvider?.bound
        ? t('portal.home.onboarding_qq_ready', {}, 'QQ quick login is bound, so future sign-ins can use QQ directly.')
        : t('portal.home.onboarding_qq_needed', {}, 'Email remains the primary identity. Bind QQ for easier login.'),
      href: '/portal/account',
      action: t('portal.home.onboarding_qq_action', {}, 'Account center'),
    },
  ];
  const requiredSetupItems = setupChecklistItems.filter((item) => item.key !== 'qq');
  const requiredAttentionItems = requiredSetupItems.filter((item) => !item.done);
  const shouldShowOnboardingChecklist = requiredAttentionItems.length > 0;
  const currentSubscriptionStatusLabel = currentSubscription?.status === 'active' || hasPackageLabel
      ? t('portal.home.package_available_label', {}, 'Available')
      : t('portal.home.package_pending_label', {}, 'To confirm');
  const remainingCredits = Number(accountEntitlements?.quota_summary?.credit?.remaining ?? 0);
  const accountQuotaStatus = String(accountEntitlements?.quota_summary?.status || '');
  const currentServiceStatusToken =
    visibleSites.length === 0 ||
    restrictedCount > 0 ||
    accountQuotaStatus === 'limited' ||
    (currentSubscription?.status && currentSubscription.status !== 'active') ||
    currentSiteActiveKeyCount === 0
      ? 'warning'
      : 'active';
  const currentServiceStatusLabel =
    currentServiceStatusToken === 'active'
      ? t('portal.home.service_status_live', {}, 'Ready')
      : t('portal.home.service_status_attention', {}, 'Needs attention');
  const activeKeySummaryLabel =
    currentSiteActiveKeyCount === null
      ? t('common.loading')
      : currentSiteActiveKeyCount > 0
        ? t('portal.home.connection_ready_label', {}, 'Connected')
        : t('portal.home.connection_needed_label', {}, 'Needs setup');
  const activeKeySummaryDetail =
    currentSiteActiveKeyCount !== null && currentSiteActiveKeyCount > 0
      ? t('portal.home.onboarding_site_ready', {}, 'The WordPress site is connected and can use the service.')
      : t('portal.home.onboarding_site_needed', {}, 'Open the WordPress plugin to reconnect the site if the address or service connection is not ready.');
  const operationSummaryItems = [
    {
      label: t('portal.home.package_card_label', {}, 'Current package'),
      value: currentPackageDisplay.display_package_label || t('portal.home.package_pending_label', {}, 'To confirm'),
      detail: currentSubscriptionStatusLabel,
      size: 'compact' as const,
    },
    {
      label: t('portal.usage.remaining_credits', {}, 'Remaining'),
      value: remainingCredits > 0 ? formatNumber(remainingCredits) : t('portal.home.package_pending_label', {}, 'To confirm'),
      detail: t('portal.home.account_points_detail', {}, 'Account package points remaining this period.'),
      size: 'compact' as const,
    },
    {
      label: t('portal.home.needs_attention_sites_label', {}, 'Needs attention'),
      value: restrictedCount,
      detail: visibleSites.length
        ? t('portal.home.site_status_attention_detail', { count: String(restrictedCount) }, `${restrictedCount} sites need attention.`)
        : t('portal.home.no_sites_empty_desc', {}, 'Open npcink-cloud-addon in WordPress and start the connection there.'),
      size: 'compact' as const,
    },
    {
      label: t('portal.nav_support_requests', {}, 'Tickets'),
      value: openTicketCount ?? t('common.loading'),
      detail: t('portal.home.open_ticket_detail', {}, 'Open or in-progress support tickets.'),
      size: 'compact' as const,
    },
  ];
  const operationFocusItems = restrictionItems;
  const shouldShowFollowUpSection =
    operationFocusItems.length > 0 || shouldShowOnboardingChecklist;

  return (
    <PortalPageStack>
      <PortalSiteInspectorDrawer
        isOpen={isInspectorOpen}
        onClose={closeInspector}
        site={inspectedSite}
        summary={inspectedSummary}
        isLoading={isInspectorLoading}
        error={inspectorError}
        restrictions={inspectorRestrictions}
        previousSiteId={previousSiteId}
        nextSiteId={nextSiteId}
        onNavigateSite={openInspector}
        t={t}
      />
      <section className="space-y-5" data-portal-home="operation-overview">
        <PortalSection className="space-y-5" variant="portal">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0">
              <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                {t('portal.workspace_label', {}, 'Overview')}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold text-gray-950 dark:text-white">
                  {t('portal.home.title', {}, 'My service')}
                </h1>
                <PortalStatusBadge
                  status={currentServiceStatusToken}
                  label={currentServiceStatusLabel}
                  className="shrink-0 text-[0.68rem]"
                />
              </div>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
                {currentServiceStatusToken === 'active'
                  ? t('portal.home.account_status_ok_desc', {}, 'This account can use the hosted service normally.')
                  : t('portal.home.account_status_issue_desc', {}, 'This account has setup, package, site, or support items that need attention.')}
              </p>
            </div>
          </div>

          <PortalMetricStrip items={operationSummaryItems} columnsClassName="md:grid-cols-2 xl:grid-cols-4" variant="portal" />

          {shouldShowFollowUpSection ? (
            <div className="grid items-start gap-4 xl:grid-cols-[1.1fr_0.9fr]">
              {operationFocusItems.length > 0 ? (
                <PortalCard className="bg-white/70 dark:bg-slate-950/35" variant="portal" data-portal-home="current-focus">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                        {t('common.status')}
                      </p>
                      <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
                        {t('portal.home.current_status_title', {}, 'Service status')}
                      </h2>
                    </div>
                    <PortalTag tone={currentServiceStatusToken === 'active' ? 'success' : 'warning'}>
                      {currentServiceStatusLabel}
                    </PortalTag>
                  </div>
                  <div className="mt-4 space-y-3">
                    {operationFocusItems.slice(0, 3).map((item) => (
                      <div
                        key={item.label}
                        className={cn(
                          'rounded-xl border px-3 py-3',
                          item.tone === 'warn'
                            ? 'border-amber-200 bg-amber-50/75 dark:border-amber-900/70 dark:bg-amber-950/25'
                            : 'border-slate-200/80 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-950/35'
                        )}
                      >
                        <p className="text-sm font-semibold text-gray-950 dark:text-white">{item.label}</p>
                        <p className="mt-1 text-xs leading-5 text-gray-600 dark:text-gray-300">{item.detail}</p>
                      </div>
                    ))}
                  </div>
                </PortalCard>
              ) : null}

              {shouldShowOnboardingChecklist ? (
                <PortalCard className="bg-white/70 dark:bg-slate-950/35" variant="portal" data-portal-home="setup-checklist">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                        {t('portal.home.onboarding_label', {}, 'Needs attention')}
                      </p>
                      <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
                        {t('portal.home.onboarding_title', {}, 'Before you continue')}
                      </h2>
                    </div>
                    <PortalTag tone="warning">
                      {requiredAttentionItems.length} {t('portal.home.filter_attention_only', {}, 'Needs attention')}
                    </PortalTag>
                  </div>
                  <div className="mt-4 divide-y divide-slate-200/80 dark:divide-slate-800">
                    {requiredAttentionItems.map((item, index) => (
                      <Link
                        key={item.key}
                        href={item.href}
                        className="group flex gap-3 py-3 text-sm transition first:pt-0 last:pb-0 hover:text-blue-700 dark:hover:text-blue-300"
                      >
                        <span
                          className={cn(
                            'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[0.68rem] font-semibold',
                            'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-900/70 dark:bg-amber-950/25 dark:text-amber-200'
                          )}
                        >
                          {String(index + 1)}
                        </span>
                        <span className="min-w-0">
                          <span className="block font-semibold text-slate-950 dark:text-white">{item.title}</span>
                          <span className="mt-1 line-clamp-2 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                            {item.detail}
                          </span>
                        </span>
                      </Link>
                    ))}
                  </div>
                </PortalCard>
              ) : null}
            </div>
          ) : null}
        </PortalSection>
      </section>

      <PortalSitesWorkspace />
    </PortalPageStack>
  );
}
