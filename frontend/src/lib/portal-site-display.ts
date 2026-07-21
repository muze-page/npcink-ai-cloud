import type { Site } from '@/lib/portal-client';

type SiteLike = Pick<Site, 'site_id' | 'name' | 'site_url'> & {
  status?: string;
};

function normalizeString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function getPortalSiteUrl(site: SiteLike | null | undefined): string {
  if (!site) {
    return '';
  }

  return normalizeString(site.site_url);
}

export function getPortalSiteDisplayName(site: SiteLike | null | undefined): string {
  if (!site) {
    return '';
  }

  const siteName = normalizeString(site.name);
  if (siteName) {
    return siteName;
  }

  const siteUrl = getPortalSiteUrl(site);
  if (siteUrl) {
    return siteUrl;
  }

  return normalizeString(site.site_id);
}

export function getPortalSiteSecondaryLabel(site: SiteLike | null | undefined): string {
  if (!site) {
    return '';
  }

  const siteUrl = getPortalSiteUrl(site);
  if (siteUrl) {
    return siteUrl;
  }

  return normalizeString(site.site_id);
}

export function getVisiblePortalSites<T extends SiteLike>(sites: readonly T[] | null | undefined): T[] {
  return (sites || []).filter((site) => normalizeString(site.status).toLowerCase() !== 'archived');
}

export function portalSiteNeedsAttention(site: SiteLike | null | undefined): boolean {
  if (!site) {
    return true;
  }

  return normalizeString(site.status).toLowerCase() !== 'active' || !getPortalSiteUrl(site);
}
