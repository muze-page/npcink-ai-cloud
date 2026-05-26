'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import React, { useEffect, useState } from 'react';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import {
  PortalErrorState,
  PortalLoadingState,
  PortalSiteSwitchingNotice,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useSession } from '@/hooks/useSession';
import {
  getPortalSiteDisplayName,
  getPortalSiteSecondaryLabel,
} from '@/lib/portal-site-display';
import {
  portalClient,
  type PortalMemberPreferences,
  type PortalMemberSummary,
} from '@/lib/portal-client';
import { translateAllowedAction, translateExternalCommercialRole } from '@/lib/admin-display';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { useTranslation } from '@/hooks/useTranslation';
import { formatDate } from '@/lib/utils';
import { localeOptions, type Locale } from '@/lib/i18n';
import {
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';

interface SiteSummaryItem {
  site_id: string;
  site_name: string;
  status: string;
  created_at: string;
  account_id?: string;
  plan_name?: string;
}

export function PortalPreferencesClient() {
  const searchParams = useSearchParams();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { locale, setLocale, t } = useTranslation();
  const { selectedSiteId, isSwitchingSite, switchingSiteName, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });

  const [sites, setSites] = useState<SiteSummaryItem[]>([]);
  const [memberSummary, setMemberSummary] = useState<PortalMemberSummary | null>(null);
  const [memberPreferences, setMemberPreferences] = useState<PortalMemberPreferences | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSavingPreferences, setIsSavingPreferences] = useState(false);
  const [preferencesLocale, setPreferencesLocale] = useState<Locale>(locale);
  const [preferencesMessage, setPreferencesMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPreferencesLocale(locale);
  }, [locale]);

  useEffect(() => {
    if (!session || !isAuthenticated) {
      return;
    }

    setSites(
      session.sites.map((site) => ({
        site_id: site.site_id,
        site_name: site.site_name,
        status: site.status,
        created_at: site.created_at,
        account_id: site.account_id,
        plan_name: site.plan_name,
      }))
    );
  }, [session, isAuthenticated]);

  useEffect(() => {
    const loadPreferences = async () => {
      if (!session || !isAuthenticated) {
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const [memberSummaryResponse, memberPreferencesResponse] = await Promise.all([
          portalClient.getMemberSummary(),
          portalClient.getMemberPreferences(),
        ]);
        setMemberSummary(memberSummaryResponse.data as PortalMemberSummary);
        const nextPreferences = memberPreferencesResponse.data as PortalMemberPreferences;
        setMemberPreferences(nextPreferences);
        if (nextPreferences.locale) {
          setPreferencesLocale(nextPreferences.locale);
        }
      } catch (err) {
        setMemberSummary(null);
        setMemberPreferences(null);
        setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadPreferences();
  }, [isAuthenticated, session, t]);

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

  const selectedSite = sites.find((site) => site.site_id === selectedSiteId);
  const selectedSiteRecordHref = selectedSiteId ? `/portal/sites/${selectedSiteId}` : '/portal/sites';
  const currentRoleLabel = memberSummary?.roles?.length
    ? memberSummary.roles.map((role) => translateExternalCommercialRole(role, t)).join(', ')
    : t('common.not_found');

  const handlePreferencesSave = async () => {
    setIsSavingPreferences(true);
    setPreferencesMessage(null);
    try {
      const response = await portalClient.updateMemberPreferences({
        locale: preferencesLocale,
        currency: 'CNY',
      });
      const savedPreferences = response.data as PortalMemberPreferences;
      setMemberPreferences(savedPreferences);
      setLocale(preferencesLocale);
      setPreferencesMessage(t('portal.preferences.saved', {}, 'Personal preferences saved.'));
    } catch (err) {
      setPreferencesMessage(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setIsSavingPreferences(false);
    }
  };

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.nav_preferences', {}, 'Preferences')}
        title={t('portal.nav_preferences', {}, 'Preferences')}
        eyebrowInfo={t(
          'portal.preferences.desc_v2',
          {},
          'Keep this page narrow. Only personal preferences belong here; site record, usage, keys, and package stay on their own pages.'
        )}
        currentPage="preferences"
        selectedSiteId={selectedSiteId || session.site_id || ''}
        selectedSiteName={selectedSite?.site_name}
        showSiteContextSummary={false}
        sites={sites}
        onSiteChange={setSelectedSiteId}
      />

      {isSwitchingSite ? (
        <PortalSiteSwitchingNotice
          message={t(
            'portal.site_switching_notice_with_target',
            { site: switchingSiteName || selectedSiteId },
            `正在切换到 ${switchingSiteName || selectedSiteId}，页面数据会自动更新。`
          )}
        />
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
        <BackofficeSectionPanel className="space-y-4">
          <h2 className="text-xl font-semibold">{t('portal.preferences.title', {}, 'Personal preferences')}</h2>
          <BackofficeStackCard className="space-y-4">
            <label className="block space-y-2">
              <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                {t('common.language')}
              </span>
              <select
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none transition focus:border-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                value={preferencesLocale}
                onChange={(event) => setPreferencesLocale(event.target.value as Locale)}
                disabled={isSavingPreferences}
              >
                {localeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-2">
              <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                {t('common.currency')}
              </span>
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-200">
                <span className="font-medium">CNY</span>
                <span className="ml-2 text-slate-500 dark:text-slate-400">
                  {t(
                    'portal.preferences.currency_fixed_note',
                    {},
                    'Amounts are shown in CNY while multi-currency billing is not enabled.'
                  )}
                </span>
              </div>
            </label>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {memberPreferences?.updated_at
                  ? t(
                      'portal.preferences.updated_at',
                      { date: formatDate(memberPreferences.updated_at) },
                      `Last saved ${formatDate(memberPreferences.updated_at)}`
                    )
                  : t('portal.preferences.not_saved', {}, 'No saved personal preference record yet.')}
              </p>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void handlePreferencesSave()}
                disabled={isSavingPreferences}
              >
                {isSavingPreferences ? t('common.saving') : t('common.save')}
              </button>
            </div>
            {preferencesMessage ? (
              <p className="text-sm text-gray-600 dark:text-gray-400">{preferencesMessage}</p>
            ) : null}
          </BackofficeStackCard>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <BackofficeStackCard className="space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('common.site')}
                </p>
                <p className="mt-2 text-sm font-medium text-slate-900 dark:text-slate-100">
                  {getPortalSiteDisplayName(selectedSite) || selectedSiteId || t('common.not_found')}
                </p>
                {getPortalSiteSecondaryLabel(selectedSite) ? (
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {getPortalSiteSecondaryLabel(selectedSite)}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <Link href={selectedSiteRecordHref} className="btn btn-secondary btn-sm">
                  {t('portal.site_record', {}, 'Site record')}
                </Link>
                <Link href={`/portal${selectedSiteId ? `?site=${selectedSiteId}` : ''}`} className="btn btn-secondary btn-sm">
                  {t('portal.workspace_label', {}, 'Workspace')}
                </Link>
              </div>
            </div>
          </BackofficeStackCard>
          <BackofficeStackCard className="space-y-4">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-500 dark:text-gray-400">
              {t('portal.preferences.access_context', {}, 'Access context')}
            </p>
            <div className="divide-y divide-slate-200/80 dark:divide-slate-800">
              <div className="grid gap-2 py-3 md:grid-cols-[9rem_minmax(0,1fr)]">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('common.email')}
                </p>
                <p className="break-all text-sm font-medium text-slate-950 dark:text-slate-100">
                  {memberSummary?.email || t('common.not_found')}
                </p>
              </div>
              <div className="grid gap-2 py-3 md:grid-cols-[9rem_minmax(0,1fr)]">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('portal.preferences.session_ref', {}, 'Session ref')}
                </p>
                <p className="break-all text-sm font-medium text-slate-950 dark:text-slate-100">
                  {memberSummary?.member_ref || session.member_ref || t('common.not_found')}
                </p>
              </div>
              <div className="grid gap-2 py-3 md:grid-cols-[9rem_minmax(0,1fr)]">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('common.role')}
                </p>
                <p className="text-sm font-medium text-slate-950 dark:text-slate-100">
                  {currentRoleLabel}
                </p>
              </div>
              <div className="grid gap-2 py-3 md:grid-cols-[9rem_minmax(0,1fr)]">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('common.actions', {}, 'Actions')}
                </p>
                <p className="text-sm leading-7 text-slate-700 dark:text-slate-200">
                  {memberSummary?.allowed_actions?.length
                    ? memberSummary.allowed_actions.map((action) => translateAllowedAction(action, t)).join('，')
                    : t('common.not_found')}
                </p>
              </div>
            </div>
          </BackofficeStackCard>
        </BackofficeSectionPanel>
      </div>
    </BackofficePageStack>
  );
}
