'use client';

import Link from 'next/link';
import { useState, type FormEvent } from 'react';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { useLocale } from '@/contexts/LocaleContext';
import { localizePackageAlias } from '@/lib/admin-plan-copy';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { portalClient, type PortalProvisionedSite, type Site } from '@/lib/portal-client';
import { useToast } from '@/components/ui/Toast';

interface PortalSiteConnectPanelProps {
  accountId: string;
  currentSiteId?: string;
  sites: Site[];
  onSiteCreated?: (siteId: string) => void | Promise<void>;
  mode?: 'inline' | 'modal';
  onClose?: () => void;
}

export function PortalSiteConnectPanel({
  accountId,
  currentSiteId,
  sites,
  onSiteCreated,
  mode = 'inline',
  onClose,
}: PortalSiteConnectPanelProps) {
  const { t } = useLocale();
  const toast = useToast();
  const [siteName, setSiteName] = useState('');
  const [wordpressUrl, setWordpressUrl] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<PortalProvisionedSite | null>(null);

  const publicBaseUrl = typeof window !== 'undefined' ? window.location.origin : '';
  const currentSite = sites.find((site) => site.site_id === currentSiteId) || sites[0] || null;
  const createdPackageAlias =
    created?.commercial_onboarding?.package_alias ||
    localizePackageAlias(
      t,
      created?.commercial_onboarding?.tier_id || created?.current_subscription?.plan_id || '',
      t('common.not_found')
    );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    if (!accountId) {
      setError(
        t(
          'portal.connect_site_account_required',
          undefined,
          'Switch into a site-backed account first before adding another site.'
        )
      );
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await portalClient.createSite({
        account_id: accountId,
        site_name: siteName.trim(),
        wordpress_url: wordpressUrl.trim(),
      });
      const payload = response.data;
      setCreated(payload);
      setSiteName('');
      setWordpressUrl('');
      await onSiteCreated?.(payload.site.site_id);
      toast.success(
        payload.commercial_onboarding?.auto_bound
          ? t(
              'portal.connect_site_success_message_with_package',
              undefined,
              'The site record is pending activation and is now covered by the current customer subscription. Issue the first API key to activate it and continue addon setup.'
            )
          : t('portal.connect_site_success_message', undefined, 'The site record is pending activation. Issue the first API key to activate it and continue addon setup.'),
        t('portal.connect_site_success_title', undefined, 'Site created')
      );
    } catch (caughtError) {
      setError(
        formatPortalErrorMessage(
          caughtError,
          t,
          t('portal.connect_site_failed', undefined, 'Failed to add the site to the current account.')
        )
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      {!created || mode === 'inline' ? (
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {t('portal.connect_site_title', undefined, 'Connect Site')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
            {t('portal.connect_site_heading', undefined, 'Add another WordPress site')}
          </h2>
          <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
            {t(
              'portal.connect_site_desc',
              undefined,
              'Create the Cloud-side site record for the current account, then issue a site key and finish the addon binding inside WordPress.'
            )}
          </p>
        </div>
      ) : null}

      {!created || mode === 'inline' ? (
      <div className="rounded-[1.2rem] border border-slate-200/80 bg-slate-50/80 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/45">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('common.account')}
            </p>
            <p className="mt-2 font-mono text-sm text-gray-950 dark:text-white">{accountId || t('common.not_found')}</p>
          </div>
          <div>
            <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.selected_site')}
            </p>
            <p className="mt-2 text-sm text-gray-950 dark:text-white">
              {currentSite?.site_name || t('common.not_found')}
            </p>
          </div>
        </div>
      </div>
      ) : null}

      {!created || mode === 'inline' ? (
      <form className="grid gap-4" onSubmit={handleSubmit}>
        <label className="grid gap-2">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {t('portal.connect_site_url_label', undefined, 'WordPress site URL')}
          </span>
          <input
            type="url"
            value={wordpressUrl}
            onChange={(event) => setWordpressUrl(event.target.value)}
            placeholder="https://customer.example.com"
            className="rounded-[1rem] border border-slate-200/80 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            required
          />
        </label>

        <label className="grid gap-2">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {t('portal.connect_site_name_label', undefined, 'Display name')}
          </span>
          <input
            type="text"
            value={siteName}
            onChange={(event) => setSiteName(event.target.value)}
            placeholder={t('portal.connect_site_name_placeholder', undefined, 'Customer Production')}
            className="rounded-[1rem] border border-slate-200/80 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          />
        </label>

        {error ? (
          <p className="rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            {error}
          </p>
        ) : null}

        <div className="flex flex-wrap gap-3">
          <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
            {isSubmitting
              ? t('common.saving', undefined, 'Saving...')
              : t('portal.connect_site_action', undefined, 'Add site')}
          </button>
          <Link href="/getting-started" className="btn btn-secondary">
            {t('portal.connect_site_docs', undefined, 'Open setup guide')}
          </Link>
        </div>
      </form>
      ) : null}

      {created ? (
        <div className="rounded-[1.4rem] border border-emerald-200 bg-emerald-50/85 px-4 py-4 dark:border-emerald-900/60 dark:bg-emerald-950/30">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-300">
                {t('portal.connect_site_success_label', undefined, 'Next Step')}
              </p>
              <h3 className="mt-2 text-lg font-semibold text-emerald-950 dark:text-emerald-100">
                {created.site.name}
              </h3>
              <p className="mt-2 text-sm leading-6 text-emerald-900/80 dark:text-emerald-100/80">
                {created?.commercial_onboarding?.auto_bound
                  ? t(
                      'portal.connect_site_success_desc_with_package',
                      undefined,
                      'The Cloud-side site record is created in provisioning state and is already covered by the current customer subscription. Use the values below in the WordPress cloud addon, then issue the first API key to activate hosted runtime for this site.'
                    )
                  : t(
                      'portal.connect_site_success_desc',
                      undefined,
                      'The Cloud-side site record is created in provisioning state. Use the values below in the WordPress cloud addon, then issue the first API key to activate hosted runtime for this site.'
                    )}
              </p>
              {mode === 'modal' ? (
                <p className="mt-2 text-sm leading-6 text-emerald-900/80 dark:text-emerald-100/80">
                  {t(
                    'portal.connect_site_modal_success_desc',
                    undefined,
                    'The form is complete. Choose whether to issue the first key now or return to the workspace and keep browsing sites.'
                  )}
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <Link href={created.next.keys_path} className="btn btn-primary">
                {t('portal.connect_site_create_key', undefined, 'Create first key')}
              </Link>
              {mode === 'modal' ? (
                <button type="button" className="btn btn-secondary" onClick={onClose}>
                  {t('portal.connect_site_return_to_workspace', undefined, 'Return to workspace')}
                </button>
              ) : null}
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <div className="rounded-[1rem] border border-emerald-200/70 bg-white/80 px-3 py-3 dark:border-emerald-900/50 dark:bg-slate-950/30">
              <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-300">
                {t('portal.connect_site_base_url_label', undefined, 'Base URL')}
              </p>
              <p className="mt-2 break-all font-mono text-sm text-gray-950 dark:text-white">{publicBaseUrl || t('common.not_found')}</p>
            </div>
            <div className="rounded-[1rem] border border-emerald-200/70 bg-white/80 px-3 py-3 dark:border-emerald-900/50 dark:bg-slate-950/30">
              <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-300">
                {t('portal.connect_site_wordpress_url_label', undefined, 'WordPress URL')}
              </p>
              <p className="mt-2 break-all font-mono text-sm text-gray-950 dark:text-white">{created.wordpress_url}</p>
            </div>
            <div className="rounded-[1rem] border border-emerald-200/70 bg-white/80 px-3 py-3 dark:border-emerald-900/50 dark:bg-slate-950/30">
              <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-300">
                {t('portal.connect_site_record_id_label', undefined, 'Cloud Record ID')}
              </p>
              <div className="mt-2">
                <BackofficeIdentifier value={created.site.site_id} full className="break-all text-sm text-gray-950 dark:text-white" />
              </div>
            </div>
          </div>

          {created?.commercial_onboarding?.auto_bound ? (
            <div className="mt-4 rounded-[1rem] border border-emerald-200/70 bg-white/80 px-3 py-3 dark:border-emerald-900/50 dark:bg-slate-950/30">
              <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-300">
                {t('common.plan', {}, 'Plan')}
              </p>
              <p className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
                {t('portal.current_subscription_label', {}, 'Current subscription')}: {createdPackageAlias}
              </p>
              <p className="mt-1 text-sm leading-6 text-emerald-900/80 dark:text-emerald-100/80">
                {t(
                  'portal.connect_site_success_plan_desc',
                  undefined,
                  'The site is automatically covered by the current customer subscription. If you need more headroom later, the upgrade path stays on account/subscription operations instead of the WordPress site record.'
                )}
              </p>
            </div>
          ) : null}

          <p className="mt-4 text-xs leading-5 text-emerald-900/75 dark:text-emerald-100/70">
            {t(
              'portal.connect_site_success_hint',
              undefined,
              'Cloud created the site record only. The first API key issuance now activates this site for hosted runtime, while WordPress remains the execution control plane for addon binding and final local enablement.'
            )}
          </p>
        </div>
      ) : null}
    </div>
  );
}

export default PortalSiteConnectPanel;
