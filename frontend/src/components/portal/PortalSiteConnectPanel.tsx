'use client';

import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStackCard } from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import { type Site } from '@/lib/portal-client';

interface PortalSiteConnectPanelProps {
  accountId: string;
  currentSiteId?: string;
  sites?: Site[];
  onCreated?: () => void;
  onSiteCreated?: (siteId: string) => void;
  mode?: string;
  onClose?: () => void;
}

export function PortalSiteConnectPanel({
  accountId,
  currentSiteId = '',
  sites = [],
}: PortalSiteConnectPanelProps) {
  const { t } = useLocale();

  return (
    <BackofficeStackCard className="space-y-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
          {t('portal.connect_site_title', undefined, 'Site provisioning')}
        </p>
        <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
          {t('portal.connect_site_operator_title', undefined, 'Ask an operator to provision Cloud access')}
        </h2>
        <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">
          {t(
            'portal.connect_site_operator_desc',
            undefined,
            'Portal is read-only for site lifecycle. Operators create site records and issue the first key from the service plane.'
          )}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-[1rem] border border-gray-200 bg-white px-3 py-3 dark:border-gray-800 dark:bg-gray-950">
          <p className="text-xs text-gray-500 dark:text-gray-400">{t('common.account', undefined, 'Account')}</p>
          <BackofficeIdentifier value={accountId || t('common.not_found', undefined, 'Not found')} className="mt-1 block" />
        </div>
        <div className="rounded-[1rem] border border-gray-200 bg-white px-3 py-3 dark:border-gray-800 dark:bg-gray-950">
          <p className="text-xs text-gray-500 dark:text-gray-400">{t('common.site', undefined, 'Site')}</p>
          <BackofficeIdentifier value={currentSiteId || sites[0]?.site_id || t('common.not_found', undefined, 'Not found')} className="mt-1 block" />
        </div>
      </div>
    </BackofficeStackCard>
  );
}

export default PortalSiteConnectPanel;
