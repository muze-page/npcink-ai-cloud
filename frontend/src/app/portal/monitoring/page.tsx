'use client';

import { Suspense, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { PortalLoadingState, PortalSignedOutState } from '@/components/portal/PortalPageState';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import { getVisiblePortalSites } from '@/lib/portal-site-display';

function PortalMonitoringRedirect() {
  const { t } = useLocale();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, isLoading, isAuthenticated } = useSession();
  const requestedSiteId = searchParams.get('site') || '';
  const sites = getVisiblePortalSites(session?.sites);
  const selectedSite = sites.find((site) => site.site_id === requestedSiteId)
    || sites.find((site) => site.site_id === session?.site_id)
    || sites[0]
    || null;

  useEffect(() => {
    if (isLoading || !isAuthenticated || !session) return;
    if (!selectedSite) {
      router.replace('/portal#sites');
      return;
    }
    router.replace(`/portal/sites/${encodeURIComponent(selectedSite.site_id)}#service-status`);
  }, [isAuthenticated, isLoading, router, selectedSite, session]);

  if (!isLoading && (!isAuthenticated || !session)) {
    return (
      <PortalSignedOutState
        title={t('auth.not_signed_in')}
        description={t('auth.please_sign_in')}
        actionLabel={t('nav.sign_in')}
      />
    );
  }

  return (
    <PortalLoadingState
      message={t('portal.monitoring.redirecting_to_site', {}, 'Opening site service status...')}
    />
  );
}

export default function PortalMonitoringPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalMonitoringRedirect />
    </Suspense>
  );
}
