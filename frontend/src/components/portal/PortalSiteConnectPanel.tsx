'use client';

import { useState, type FormEvent } from 'react';
import { PortalCard } from '@/components/portal/PortalScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import { portalClient, type PortalAddonConnectionAccount } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';

interface PortalSiteConnectPanelProps {
  accounts: PortalAddonConnectionAccount[];
  accountsError?: string;
  isLoadingAccounts?: boolean;
  onClose?: () => void;
  initialSiteUrl?: string;
  initialSiteName?: string;
  addonReturnUrl?: string;
  addonState?: string;
}

export function PortalSiteConnectPanel({
  accounts,
  accountsError = '',
  isLoadingAccounts = false,
  onClose,
  initialSiteUrl = '',
  initialSiteName = '',
  addonReturnUrl = '',
  addonState = '',
}: PortalSiteConnectPanelProps) {
  const { t } = useLocale();
  const [selectedAccountId, setSelectedAccountId] = useState('');
  const [siteName, setSiteName] = useState(initialSiteName);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const siteUrl = initialSiteUrl.trim();
  const hasAddonConnectionContext = Boolean(siteUrl && addonReturnUrl && addonState);
  const addonSiteLabel =
    siteName.trim() ||
    siteUrl.replace(/^https?:\/\//, '').replace(/\/$/, '') ||
    t('portal.connect_site_new_site', undefined, 'New site');

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage('');
    if (!hasAddonConnectionContext) {
      setErrorMessage(
        t(
          'portal.connect_site_failed',
          undefined,
          'The WordPress addon connection context is incomplete. Restart the connection from WordPress.'
        )
      );
      return;
    }
    if (!accounts.some((account) => account.account_id === selectedAccountId)) {
      setErrorMessage(
        t(
          'portal.connect_site_account_required_desc',
          undefined,
          'Select an active customer account before finishing this connection.'
        )
      );
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await portalClient.createAddonConnection({
        account_id: selectedAccountId,
        site_url: siteUrl,
        site_name: siteName,
        return_url: addonReturnUrl,
        state: addonState,
      });
      window.location.assign(response.data.redirect_url);
    } catch (error) {
      setErrorMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.connect_site_failed', undefined, 'Failed to connect the WordPress site.')
        )
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <PortalCard className="space-y-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
          {t('portal.connect_site_title', undefined, 'Site connection')}
        </p>
        <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
          {t('portal.connect_site_addon_title', undefined, 'Finish WordPress connection')}
        </h2>
        <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
          {t(
            'portal.connect_site_addon_desc',
            undefined,
            'Confirm this site, then return to WordPress to finish setup.'
          )}
        </p>
      </div>

      <div className="rounded-[1rem] border border-gray-200 bg-white px-3 py-3 dark:border-gray-800 dark:bg-gray-950">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t('common.site', undefined, 'Site')}
        </p>
        <p className="mt-1 text-sm font-semibold text-gray-950 dark:text-white">
          {addonSiteLabel}
        </p>
        <p className="mt-1 truncate text-xs text-gray-500 dark:text-gray-400">
          {siteUrl || t('portal.site_url_missing_short', undefined, 'Site URL not configured')}
        </p>
      </div>

      <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
        <label className="block">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {t('portal.connect_site_account_label', undefined, 'Customer account')}
          </span>
          <select
            value={selectedAccountId}
            onChange={(event) => {
              setSelectedAccountId(event.target.value);
              setErrorMessage('');
            }}
            className="input mt-1 w-full"
            disabled={isLoadingAccounts || accounts.length === 0}
            required
          >
            <option value="">
              {isLoadingAccounts
                ? t('common.loading', {}, 'Loading...')
                : accounts.length
                  ? t('portal.connect_site_account_placeholder', undefined, 'Select an account')
                  : t('portal.connect_site_account_empty', undefined, 'No eligible account')}
            </option>
            {accounts.map((account) => (
              <option key={account.account_id} value={account.account_id}>
                {account.name || account.account_id} · {account.site_count} {t('common.site')}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {t('portal.connect_site_name_label', undefined, 'Display name')}
          </span>
          <input
            type="text"
            value={siteName}
            onChange={(event) => setSiteName(event.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-950 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-gray-700 dark:bg-gray-950 dark:text-white"
            placeholder={t('portal.connect_site_name_placeholder', undefined, 'Customer Production')}
          />
        </label>
        {accountsError ? (
          <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
            {accountsError}
          </p>
        ) : null}
        {errorMessage ? (
          <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
            {errorMessage}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSubmitting || isLoadingAccounts || !selectedAccountId}
          >
            {isSubmitting
              ? t('common.saving')
              : t('portal.connect_site_authorize_addon', undefined, 'Finish connection')}
          </button>
          {onClose ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
              disabled={isSubmitting}
            >
              {t('common.cancel')}
            </button>
          ) : null}
        </div>
      </form>
    </PortalCard>
  );
}

export default PortalSiteConnectPanel;
