'use client';

import { useState, type FormEvent } from 'react';
import { BackofficeStackCard } from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import { portalClient, type Site } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';

interface PortalSiteConnectPanelProps {
  accountId: string;
  currentSiteId?: string;
  sites?: Site[];
  onCreated?: () => void;
  onSiteCreated?: (siteId: string) => void;
  mode?: string;
  onClose?: () => void;
  initialWordPressUrl?: string;
  initialSiteName?: string;
  addonReturnUrl?: string;
  addonState?: string;
}

export function PortalSiteConnectPanel({
  accountId,
  onCreated,
  onSiteCreated,
  onClose,
  initialWordPressUrl = '',
  initialSiteName = '',
  addonReturnUrl = '',
  addonState = '',
}: PortalSiteConnectPanelProps) {
  const { t } = useLocale();
  const [wordpressUrl, setWordpressUrl] = useState(initialWordPressUrl);
  const [siteName, setSiteName] = useState(initialSiteName);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const isAddonConnection = Boolean(addonReturnUrl && addonState);
  const addonSiteLabel =
    siteName.trim() ||
    wordpressUrl.trim().replace(/^https?:\/\//, '').replace(/\/$/, '') ||
    t('portal.connect_site_new_site', undefined, 'New site');

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage('');
    setIsSubmitting(true);
    try {
      if (isAddonConnection) {
        const response = await portalClient.createAddonConnection({
          account_id: accountId,
          wordpress_url: wordpressUrl,
          site_name: siteName,
          return_url: addonReturnUrl,
          state: addonState,
        });
        window.location.assign(response.data.redirect_url);
        return;
      }

      const response = await portalClient.createSite({
        account_id: accountId,
        wordpress_url: wordpressUrl,
        site_name: siteName,
      });
      const siteId = response.data.site?.site_id || '';
      if (siteId) {
        onSiteCreated?.(siteId);
      }
      onCreated?.();
      onClose?.();
    } catch (error) {
      setErrorMessage(
        formatPortalErrorMessage(
          error,
          t,
          t('portal.connect_site_failed', undefined, 'Failed to add the site to the current customer.')
        )
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <BackofficeStackCard className="space-y-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
          {t('portal.connect_site_title', undefined, 'Site connection')}
        </p>
        <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
          {isAddonConnection
            ? t('portal.connect_site_addon_title', undefined, 'Finish WordPress connection')
            : t('portal.connect_site_heading', undefined, 'Add another WordPress site')}
        </h2>
        <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
          {isAddonConnection
            ? t(
	                'portal.connect_site_addon_desc',
	                undefined,
                'Confirm this site, then return to WordPress to finish setup.'
	              )
	            : t(
	                'portal.connect_site_desc',
	                undefined,
	                'Add a WordPress site to this account, then follow the setup steps in WordPress.'
	              )}
        </p>
      </div>
      {isAddonConnection ? (
        <div className="rounded-[1rem] border border-gray-200 bg-white px-3 py-3 dark:border-gray-800 dark:bg-gray-950">
          <p className="text-xs text-gray-500 dark:text-gray-400">{t('common.site', undefined, 'Site')}</p>
          <p className="mt-1 text-sm font-semibold text-gray-950 dark:text-white">
            {addonSiteLabel}
          </p>
          <p className="mt-1 truncate text-xs text-gray-500 dark:text-gray-400">
            {wordpressUrl.trim() || t('portal.site_url_missing_short', undefined, 'Site URL not configured')}
          </p>
        </div>
      ) : null}
      <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
        {!isAddonConnection ? (
          <label className="block">
            <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
              {t('portal.connect_site_url_label', undefined, 'WordPress site URL')}
            </span>
            <input
              type="url"
              required
              value={wordpressUrl}
              onChange={(event) => setWordpressUrl(event.target.value)}
              className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-950 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 dark:border-gray-700 dark:bg-gray-950 dark:text-white"
              placeholder="https://example.com"
            />
          </label>
        ) : null}
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
        {errorMessage ? (
          <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-200">
            {errorMessage}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
            {isSubmitting
              ? t('common.saving')
              : isAddonConnection
                ? t('portal.connect_site_authorize_addon', undefined, 'Finish connection')
                : t('portal.connect_site_action', undefined, 'Add site')}
          </button>
          {onClose ? (
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={isSubmitting}>
              {t('common.cancel')}
            </button>
          ) : null}
        </div>
      </form>
    </BackofficeStackCard>
  );
}

export default PortalSiteConnectPanel;
