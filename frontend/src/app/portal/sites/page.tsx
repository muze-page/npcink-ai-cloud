'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect } from 'react';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { PortalLoadingState, PortalSignedOutState } from '@/components/portal/PortalPageState';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';

function PortalSitesRedirectContent() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { isLoading, isAuthenticated } = useSession();
  const query = searchParams.toString();
  const currentPath = `${pathname}${query ? `?${query}` : ''}`;

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace(`/portal${query ? `?${query}` : ''}#sites`);
    }
  }, [isAuthenticated, isLoading, query, router]);

  if (isLoading || isAuthenticated) {
    return <PortalLoadingState message={t('common.loading')} />;
  }

  return (
    <PortalSignedOutState
      title={t('auth.not_signed_in')}
      description={t('auth.please_sign_in')}
      actionLabel={t('nav.sign_in')}
      actionHref={`/portal/login?redirect=${encodeURIComponent(currentPath)}`}
    />
  );
}

export default function PortalSitesRedirectPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalSitesRedirectContent />
    </Suspense>
  );
}
