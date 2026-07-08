'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, type ReadonlyURLSearchParams } from 'next/navigation';
import type { PortalSession, Site } from '@/lib/portal-client';
import { getPortalSiteDisplayName } from '@/lib/portal-site-display';

type UsePortalSiteSelectionOptions = {
  session: PortalSession | null;
  isAuthenticated: boolean;
  searchParams?: ReadonlyURLSearchParams | URLSearchParams | null;
  selectSite?: (siteId: string) => Promise<void>;
};

type UsePortalSiteSelectionResult = {
  sites: Site[];
  selectedSiteId: string;
  selectedSite: Site | null;
  isSwitchingSite: boolean;
  switchingSiteName: string;
  setSelectedSiteId: (siteId: string) => Promise<void>;
};

export function usePortalSiteSelection({
  session,
  isAuthenticated,
  searchParams,
  selectSite,
}: UsePortalSiteSelectionOptions): UsePortalSiteSelectionResult {
  const router = useRouter();
  const pathname = usePathname();
  const [selectedSiteId, setSelectedSiteIdState] = useState('');
  const [isSwitchingSite, setIsSwitchingSite] = useState(false);
  const [switchingSiteName, setSwitchingSiteName] = useState('');

  const sites = useMemo(
    () => (session?.sites || []).filter((site) => site.status !== 'archived'),
    [session?.sites]
  );

  useEffect(() => {
    if (!session || !isAuthenticated) {
      setSelectedSiteIdState('');
      return;
    }

    const nextSiteId =
      (searchParams?.get('site') &&
      sites.some((site) => site.site_id === searchParams.get('site'))
        ? searchParams.get('site')
        : '') ||
      (session.site_id && sites.some((site) => site.site_id === session.site_id)
        ? session.site_id
        : '') ||
      sites[0]?.site_id ||
      '';

    setSelectedSiteIdState((current) => (current === nextSiteId ? current : nextSiteId));
  }, [isAuthenticated, searchParams, session, sites]);

  const setSelectedSiteId = useCallback(
    async (siteId: string) => {
      const normalizedSiteId = String(siteId || '').trim();
      if (!normalizedSiteId) {
        return;
      }

      const previousSiteId = selectedSiteId;
      if (previousSiteId === normalizedSiteId) {
        return;
      }

      const nextSite = sites.find((site) => site.site_id === normalizedSiteId) || null;
      setIsSwitchingSite(true);
      setSwitchingSiteName(nextSite ? getPortalSiteDisplayName(nextSite) : normalizedSiteId);
      setSelectedSiteIdState(normalizedSiteId);

      try {
        if (selectSite && session?.site_id !== normalizedSiteId) {
          await selectSite(normalizedSiteId);
        }

        const params = new URLSearchParams(searchParams?.toString() || '');
        params.set('site', normalizedSiteId);
        const nextUrl = `${pathname}${params.toString() ? `?${params.toString()}` : ''}`;
        router.replace(nextUrl, { scroll: false });
        router.refresh();
      } catch (error) {
        setSelectedSiteIdState(previousSiteId);
        throw error;
      } finally {
        setIsSwitchingSite(false);
        setSwitchingSiteName('');
      }
    },
    [pathname, router, searchParams, selectSite, selectedSiteId, session, sites]
  );

  const selectedSite = useMemo(
    () => sites.find((site) => site.site_id === selectedSiteId) || null,
    [selectedSiteId, sites]
  );

  return {
    sites,
    selectedSiteId,
    selectedSite,
    isSwitchingSite,
    switchingSiteName,
    setSelectedSiteId,
  };
}
