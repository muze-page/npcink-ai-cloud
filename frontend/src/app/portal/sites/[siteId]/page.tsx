'use client';

import React, { useState, useEffect, Suspense } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type ApiKey,
  type PortalSiteSummaryRecord,
} from '@/lib/portal-client';
import { translateAllowedAction, translateExternalCommercialRole } from '@/lib/admin-display';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { translateStatusLabel } from '@/lib/status-display';
import {
  getPortalSiteSecondaryLabel,
  getPortalSiteWordPressUrl,
} from '@/lib/portal-site-display';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import { cn, formatCompactNumber, formatDate, formatNumber } from '@/lib/utils';

function SiteDetailsContent() {
  const params = useParams();
  const router = useRouter();
  const { siteId } = params as { siteId: string };
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, refresh } = useSession();
  
  const [siteDetails, setSiteDetails] = useState<PortalSiteSummaryRecord | null>(null);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [siteActionMessage, setSiteActionMessage] = useState<string | null>(null);
  const [siteActionError, setSiteActionError] = useState<string | null>(null);
  const [isSiteActionLoading, setIsSiteActionLoading] = useState(false);
  const [hasPendingDeleteRequest, setHasPendingDeleteRequest] = useState(false);

  useEffect(() => {
    const loadData = async () => {
      if (!session || !isAuthenticated) return;

      setIsLoading(true);
      setError(null);

      try {
        const [bundle, notificationsResponse] = await Promise.all([
          portalClient.getSiteBundle(siteId),
          portalClient.listNotifications({ status: 'open', limit: 100 }).catch(() => null),
        ]);
        setSiteDetails(bundle.summary);
        setApiKeys(bundle.apiKeys);
        setHasPendingDeleteRequest(
          Boolean(
            notificationsResponse?.data.items?.some(
              (item) => item.request_type === 'site_delete' && item.site_id === siteId
            )
          )
        );
      } catch (err) {
        setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadData();
  }, [session, isAuthenticated, siteId, t]);

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
        onRetry={() => window.location.reload()}
      />
    );
  }

  const entitlements = siteDetails?.entitlement_snapshot?.entitlements || {};
  const entitlementFeatures = Object.entries(entitlements).flatMap(([group, values]) =>
    Array.isArray(values) ? values.map((value) => `${group}:${value}`) : []
  );
  const tokenLimit = siteDetails?.entitlement_snapshot?.budgets?.max_tokens_per_period || 0;
  const runLimit = siteDetails?.entitlement_snapshot?.budgets?.max_runs_per_period || 0;
  const activeKeyCount = apiKeys.filter((key) => key.status === 'active').length;
  const mostRecentKey = apiKeys.find((key) => key.last_used_at) || apiKeys[0];
  const periodStart = siteDetails?.coverage?.current_period_start_at || siteDetails?.coverage?.current_period_start;
  const periodEnd = siteDetails?.coverage?.current_period_end_at || siteDetails?.coverage?.current_period_end;
  const selectedSite = session.sites.find((site) => site.site_id === siteId);
  const siteOptions = session.sites.map((site) => ({
    site_id: site.site_id,
    site_name: site.site_name,
  }));
  const packageDisplay = resolveCustomerPackageDisplay(t, {
    planId: siteDetails?.coverage?.plan_id,
    planVersionId: siteDetails?.coverage?.plan_version_id,
    packageAlias: siteDetails?.package_alias || siteDetails?.coverage?.package_alias,
    formalPlanName: siteDetails?.site?.plan_name || selectedSite?.plan_name,
    coverageState: siteDetails?.coverage ? 'covered' : 'uncovered',
  });

  const handleSiteChange = (nextSiteId: string) => {
    router.push(`/portal/sites/${nextSiteId}`);
  };

  const canArchiveSite = Boolean(siteDetails?.allowed_actions?.includes('archive_sites'));
  const isArchivedSite = siteDetails?.site.status === 'archived';

  const handleArchiveToggle = async () => {
    if (!siteDetails || !canArchiveSite || isSiteActionLoading) {
      return;
    }
    const confirmed = window.confirm(
      isArchivedSite
        ? t('portal.restore_site_confirm', {}, 'Restore this site to the active workspace?')
        : t('portal.archive_site_confirm', {}, 'Archive this site? It will be hidden from the default workspace and site switcher until restored.')
    );
    if (!confirmed) {
      return;
    }

    setIsSiteActionLoading(true);
    setSiteActionMessage(null);
    setSiteActionError(null);
    try {
      if (isArchivedSite) {
        await portalClient.restoreSite(siteId);
        setSiteActionMessage(
          t('portal.site_restore_success', {}, 'Site restored. It is available in the active workspace again.')
        );
      } else {
        await portalClient.archiveSite(siteId);
        setSiteActionMessage(
          t('portal.site_archive_success', {}, 'Site archived. It is now hidden from the default workspace flow.')
        );
      }
      await refresh();
      const bundle = await portalClient.getSiteBundle(siteId);
      setSiteDetails(bundle.summary);
      setApiKeys(bundle.apiKeys);
    } catch (caughtError) {
      console.error('Failed to change site archive state:', caughtError);
      setSiteActionError(
        isArchivedSite
          ? t('portal.site_restore_failed', {}, 'Failed to restore this site.')
          : t('portal.site_archive_failed', {}, 'Failed to archive this site.')
      );
    } finally {
      setIsSiteActionLoading(false);
    }
  };

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.site_record', {}, 'Site Record')}
        title={siteDetails?.site.site_name || siteId}
        eyebrowInfo={t(
          'portal.site_detail.primary_desc',
          {},
          'This is the clearest place to confirm the current package, current period, your role, and allowed actions for this site.'
        )}
        currentPage="record"
        selectedSiteId={siteId}
        selectedSiteName={siteDetails?.site.site_name}
        sites={siteOptions}
        onSiteChange={handleSiteChange}
        metrics={[
          {
            label: t('common.status'),
            value: siteDetails ? translateStatusLabel(siteDetails.site.status, t) : t('common.not_found'),
          },
          {
            label: t('common.plan'),
            value: packageDisplay.display_package_label || t('common.not_found'),
          },
          {
            label: t('portal.current_period', {}, 'Current Period'),
            value:
              periodStart && periodEnd
                ? `${formatDate(periodStart)} - ${formatDate(periodEnd)}`
                : t('common.not_found'),
            size: 'compact',
          },
          {
            label: t('keys.active_keys'),
            value: activeKeyCount,
          },
        ]}
        metricsColumnsClassName="lg:grid-cols-4"
        primaryAction={
          isArchivedSite ? null : (
            <Link href={`/portal/keys?site=${siteId}`} className="btn btn-primary">
              + {t('keys.create_short', {}, 'Create key')}
            </Link>
          )
        }
        secondaryActions={
          <>
            {canArchiveSite ? (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => void handleArchiveToggle()}
                disabled={isSiteActionLoading}
              >
                {isArchivedSite
                  ? t('portal.restore_site_action', {}, 'Restore site')
                  : t('portal.archive_site_action', {}, 'Archive site')}
              </button>
            ) : null}
            <Link href={`/portal?site=${siteId}`} className="btn btn-secondary">
              ← {t('portal.back_to_portal')}
            </Link>
          </>
        }
      />

      {siteActionMessage ? (
        <BackofficeStackCard className="border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-100">
          {siteActionMessage}
        </BackofficeStackCard>
      ) : null}
      {siteActionError ? (
        <BackofficeStackCard className="border-red-200 bg-red-50 text-red-900 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-100">
          {siteActionError}
        </BackofficeStackCard>
      ) : null}
      {isArchivedSite ? (
        <BackofficeStackCard className="border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-100">
          {t(
            'portal.site_archived_notice',
            {},
            'This site is archived. Restore it when you want it to return to the active workspace and site switcher.'
          )}
        </BackofficeStackCard>
      ) : null}
      {hasPendingDeleteRequest ? (
        <BackofficeStackCard className="border-orange-200 bg-orange-50 text-orange-900 dark:border-orange-500/20 dark:bg-orange-500/10 dark:text-orange-100">
          {t(
            'portal.site_delete_pending_notice',
            {},
            '这个站点已有删除/断开申请正在等待运营处理。处理完成前，站点记录和审计仍会保留。'
          )}
        </BackofficeStackCard>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-2">
        {siteDetails ? (
          <>
            <BackofficeSectionPanel className="space-y-4">
              <h2 className="text-xl font-semibold">{t('portal.site_detail.access_title', {}, 'Site access and identity')}</h2>
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-2 xl:grid-cols-2"
                items={[
                  {
                    label: t('settings.site_url', {}, 'Site URL'),
                    value:
                      getPortalSiteWordPressUrl(siteDetails.site) ||
                      t('portal.site_url_missing', {}, 'WordPress URL not configured'),
                  },
                  {
                    label: t('site_details.your_role'),
                    value: siteDetails.identity_type
                      ? translateExternalCommercialRole(siteDetails.identity_type, t)
                      : t('common.not_found'),
                  },
                  {
                    label: t('common.actions', {}, 'Actions'),
                    value: siteDetails.allowed_actions?.length
                      ? siteDetails.allowed_actions.map((action) => translateAllowedAction(action, t)).join(', ')
                      : t('common.not_found'),
                  },
                ]}
              />
              <details className="rounded-2xl border border-slate-200/80 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/40">
                <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('portal.site_detail.internal_record_toggle', {}, 'View technical record detail')}
                </summary>
                <p className="mt-3 text-sm text-gray-600 dark:text-gray-400">
                  {t(
                    'portal.site_detail.internal_record_desc',
                    {},
                    'Internal Cloud record ID for support and debugging only.'
                  )}
                </p>
                <div className="mt-2">
                  <BackofficeIdentifier value={siteDetails.site_id} full className="break-all text-sm text-gray-950 dark:text-white" />
                </div>
              </details>
            </BackofficeSectionPanel>

            {!siteDetails.coverage ? (
              <BackofficeSectionPanel className="space-y-4">
                <h2 className="text-xl font-semibold">{t('portal.site_detail.package_title', {}, 'Current package and coverage')}</h2>
                <BackofficeStackCard>{t('site_details.no_subscription')}</BackofficeStackCard>
              </BackofficeSectionPanel>
            ) : null}
          </>
        ) : null}
      </div>

      {siteDetails?.entitlement_snapshot ? (
        <>
          <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
            <BackofficeSectionPanel className="space-y-4">
              <h2 className="text-xl font-semibold">{t('site_details.limits')}</h2>
              <BackofficeMetricStrip
                items={[
                  { label: t('usage.requests_month'), value: formatNumber(runLimit) },
                  { label: t('usage.tokens_month'), value: formatCompactNumber(tokenLimit) },
                  { label: t('site_details.connected'), value: formatDate(siteDetails.site.created_at) },
                ]}
                columnsClassName="md:grid-cols-3"
              />
            </BackofficeSectionPanel>
            <BackofficeSectionPanel className="space-y-4">
              <h2 className="text-xl font-semibold">{t('site_details.features')}</h2>
              <div className="flex flex-wrap gap-2">
                {entitlementFeatures.map((feature) => (
                  <span
                    key={feature}
                    className="text-xs px-3 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded-full"
                  >
                    {feature}
                  </span>
                ))}
                {entitlementFeatures.length === 0 ? (
                  <span className="text-sm text-gray-500 dark:text-gray-400">{t('common.not_found')}</span>
                ) : null}
              </div>
            </BackofficeSectionPanel>
          </div>
        </>
      ) : null}

      <div className="grid gap-6">
        <BackofficeSectionPanel className="space-y-4">
          <h2 className="text-xl font-semibold">{t('keys.title')}</h2>
          {apiKeys.length === 0 ? (
            <PortalEmptyState
              title={t('portal.site_detail.keys_empty_title', {}, 'No keys for this site')}
              description={t(
                'portal.site_detail.keys_empty_desc',
                {},
                'This site does not have an API key yet. Open the key workspace when you are ready to create the first one.'
              )}
              actionLabel={t('keys.title', {}, 'Open API Keys')}
              actionHref={`/portal/keys?site=${siteId}`}
            />
          ) : (
            <div className="space-y-4">
              <BackofficeMetricStrip
                items={[
                  { label: t('keys.title'), value: apiKeys.length },
                  { label: t('keys.active_keys'), value: activeKeyCount },
                  {
                    label: t('keys.last_used'),
                    value: mostRecentKey?.last_used_at ? formatDate(mostRecentKey.last_used_at) : t('common.never'),
                  },
                ]}
                columnsClassName="md:grid-cols-3"
              />
              {mostRecentKey ? (
                <BackofficeStackCard>
                  <p className="text-xs uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                    {t('portal.keys.summary_title', {}, 'Recent Key Activity')}
                  </p>
                  <div className="mt-3 flex items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{mostRecentKey.label || mostRecentKey.key_id}</span>
                        <BackofficeStatusBadge
                          status={mostRecentKey.status}
                          label={translateStatusLabel(mostRecentKey.status, t)}
                        />
                      </div>
                      <p className="mt-2 text-xs text-gray-500">
                        {mostRecentKey.last_used_at
                          ? `${t('keys.last_used')} ${formatDate(mostRecentKey.last_used_at)}`
                          : `${t('common.created')} ${formatDate(mostRecentKey.created_at)}`}
                      </p>
                    </div>
                    <BackofficeIdentifier value={mostRecentKey.key_id} className="text-sm text-gray-500" />
                  </div>
                </BackofficeStackCard>
              ) : null}
            </div>
          )}
        </BackofficeSectionPanel>
      </div>
    </BackofficePageStack>
  );
}

export default function SiteDetailsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <SiteDetailsContent />
    </Suspense>
  );
}
