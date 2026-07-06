'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import {
  getPortalSiteDisplayName,
  getPortalSiteSecondaryLabel,
  getPortalSiteWordPressUrl,
} from '@/lib/portal-site-display';
import { cn } from '@/lib/utils';
import { LocaleSwitcher } from '@/components/ui/LocaleSwitcher';
import { ThemeToggle } from '@/components/ui/ThemeToggle';

export function PortalNavbar() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isAuthenticated, selectSite, logout } = useSession();
  const [isSwitchingSite, setIsSwitchingSite] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [isSiteMenuOpen, setIsSiteMenuOpen] = useState(false);
  const [siteSearchQuery, setSiteSearchQuery] = useState('');
  const siteMenuRef = useRef<HTMLDivElement>(null);

  const primaryNavItems = useMemo(
    () => [
      { href: '/portal', label: t('portal.workspace_label', {}, 'Overview') },
      { href: '/portal/billing', label: t('portal.nav_package', {}, 'Package') },
      { href: '/portal/usage', label: t('portal.nav_usage', {}, 'Usage') },
      { href: '/portal/sites', label: t('portal.nav_sites', {}, 'Sites') },
      { href: '/portal/account', label: t('portal.nav_account', {}, 'Account') },
    ],
    [t]
  );
  const isActive = useCallback(
    (href: string) => {
      const baseHref = href.split('?')[0] || href;
      if (baseHref === '/portal') {
        return pathname === '/portal';
      }

      return pathname === baseHref || pathname.startsWith(`${baseHref}/`);
    },
    [pathname]
  );

  const handleSiteChange = useCallback(
    async (siteId: string) => {
      if (!siteId || siteId === session?.site_id) {
        return;
      }
      setIsSwitchingSite(true);
      try {
        await selectSite(siteId);
        setIsSiteMenuOpen(false);
        setSiteSearchQuery('');
        const params = new URLSearchParams(searchParams?.toString() || '');
        if (pathname !== '/portal') {
          params.set('site', siteId);
        }
        const nextUrl =
          pathname === '/portal'
            ? '/portal'
            : `${pathname}${params.toString() ? `?${params.toString()}` : ''}`;
        router.replace(nextUrl);
        router.refresh();
      } finally {
        setIsSwitchingSite(false);
      }
    },
    [pathname, router, searchParams, selectSite, session?.site_id]
  );

  const handleLogout = useCallback(async () => {
    await logout();
    router.push('/portal/login');
  }, [logout, router]);

  useEffect(() => {
    setIsSiteMenuOpen(false);
    setSiteSearchQuery('');
  }, [pathname]);

  useEffect(() => {
    if (!isSiteMenuOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (siteMenuRef.current && !siteMenuRef.current.contains(event.target as Node)) {
        setIsSiteMenuOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsSiteMenuOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isSiteMenuOpen]);

  const visibleSites = useMemo(
    () => (session?.sites || []).filter((site) => site.status !== 'archived'),
    [session?.sites]
  );
  const filteredVisibleSites = useMemo(() => {
    const query = siteSearchQuery.trim().toLowerCase();
    if (!query) {
      return visibleSites;
    }
    return visibleSites.filter((site) => {
      const displayName = getPortalSiteDisplayName(site).toLowerCase();
      const secondary = (getPortalSiteSecondaryLabel(site) || '').toLowerCase();
      const siteId = site.site_id.toLowerCase();
      return (
        displayName.includes(query) ||
        secondary.includes(query) ||
        siteId.includes(query)
      );
    });
  }, [siteSearchQuery, visibleSites]);
  const selectedSiteId =
    (session?.site_id && visibleSites.some((site) => site.site_id === session.site_id)
      ? session.site_id
      : '') ||
    visibleSites[0]?.site_id ||
    '';
  const selectedSite = visibleSites.find((site) => site.site_id === selectedSiteId) || null;
  const isLoginPage = pathname === '/portal/login';
  const visibleSiteLabel = useCallback(
    (site: typeof visibleSites[number]) =>
      site.site_name || getPortalSiteWordPressUrl(site) || t('portal.current_site', {}, 'Current site'),
    [t]
  );
  const visibleSiteSecondaryLabel = useCallback(
    (site: typeof visibleSites[number]) =>
      getPortalSiteWordPressUrl(site) || t('portal.site_url_missing_short', {}, 'Site URL not configured'),
    [t]
  );
  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200/70 bg-white/78 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/78">
      <div className="container mx-auto px-4">
        <div className="flex min-h-[3.9rem] items-center justify-between gap-4 py-2.5">
          <Link href="/portal" className="flex items-center gap-3">
            <span className="brand-mark" aria-hidden="true">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none">
                <path d="M6 15.25 12.2 4l.6 6.55H18l-6.2 9.45-.5-6.2H6Z" fill="currentColor" />
              </svg>
            </span>
            <span className="flex flex-col leading-none">
              <span className="text-[0.68rem] font-bold uppercase tracking-[0.3em] text-blue-600 dark:text-blue-300">
                Npcink AI
              </span>
              <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t('portal.nav_title', undefined, 'Workspace')}
              </span>
            </span>
          </Link>

          <div className="flex items-center gap-2">
            {isAuthenticated && visibleSites.length ? (
              <div ref={siteMenuRef} className="relative hidden items-center gap-2 md:flex">
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  {t('common.site')}
                </span>
                <button
                  type="button"
                  aria-haspopup="listbox"
                  aria-expanded={isSiteMenuOpen}
                  className="flex w-[min(22rem,40vw)] min-w-0 items-center justify-between rounded-full border border-slate-200/80 bg-white/90 px-4 py-2 text-left text-sm text-slate-700 outline-none transition hover:border-slate-300 focus:border-blue-400 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200 dark:hover:border-slate-600"
                  onClick={() => setIsSiteMenuOpen((current) => !current)}
                  disabled={isSwitchingSite}
                >
                  <span className="truncate">
                    {selectedSite
                      ? `${visibleSiteLabel(selectedSite)} · ${visibleSiteSecondaryLabel(selectedSite)}`
                      : t('portal.no_site_selected', {}, 'No site selected')}
                  </span>
                  <svg className="ml-3 h-4 w-4 shrink-0" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path d="m5 7.5 5 5 5-5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
                  </svg>
                </button>
                {isSiteMenuOpen ? (
                  <div className="absolute right-0 top-full z-20 mt-2 w-[26rem] rounded-3xl border border-slate-200/80 bg-white p-3 shadow-2xl dark:border-slate-800 dark:bg-slate-950">
                    <input
                      type="search"
                      value={siteSearchQuery}
                      onChange={(event) => setSiteSearchQuery(event.target.value)}
                      placeholder={t('portal.search_sites_short', {}, 'Search sites')}
                      className="input mb-3 w-full"
                    />
                    <div className="max-h-80 space-y-1 overflow-y-auto">
                      {filteredVisibleSites.length === 0 ? (
                        <div className="rounded-2xl px-3 py-6 text-center text-sm text-slate-500 dark:text-slate-400">
                          {t('portal.site_search_empty', {}, 'No sites match this search.')}
                        </div>
                      ) : (
                        filteredVisibleSites.map((site) => (
                          <button
                            key={site.site_id}
                            type="button"
                            role="option"
                            aria-selected={site.site_id === selectedSiteId}
                            className={cn(
                              'block w-full rounded-2xl px-3 py-3 text-left transition-colors',
                              site.site_id === selectedSiteId
                                ? 'bg-slate-900 text-white dark:bg-blue-500 dark:text-slate-950'
                                : 'text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800'
                            )}
                            onClick={() => void handleSiteChange(site.site_id)}
                          >
                            <p className="truncate text-sm font-semibold">
                              {visibleSiteLabel(site)}
                            </p>
                            <p
                              className={cn(
                                'mt-1 truncate text-xs',
                                site.site_id === selectedSiteId
                                  ? 'text-slate-200 dark:text-slate-900'
                                  : 'text-slate-500 dark:text-slate-400'
                              )}
                            >
                              {visibleSiteSecondaryLabel(site)}
                            </p>
                          </button>
                        ))
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="hidden items-center gap-2 md:flex">
              <LocaleSwitcher />
              <ThemeToggle />
            </div>
            {isAuthenticated ? (
              <button
                type="button"
                onClick={() => void handleLogout()}
                className="hidden rounded-full px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white md:inline-flex"
              >
                {t('portal.logout')}
              </button>
            ) : !isLoginPage ? (
              <Link
                href="/portal/login"
                className="hidden rounded-full px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white md:inline-flex"
              >
                {t('nav.sign_in')}
              </Link>
            ) : null}
            <button
              type="button"
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200/80 bg-white/85 text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white md:hidden"
              aria-controls="portal-mobile-nav"
              aria-expanded={mobileNavOpen}
              aria-label={mobileNavOpen ? t('common.close') : t('common.open_menu', undefined, 'Open menu')}
              onClick={() => setMobileNavOpen((current) => !current)}
            >
              {mobileNavOpen ? (
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18 18 6M6 6l12 12" />
                </svg>
              ) : (
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7h16M4 12h16M4 17h16" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {isAuthenticated ? (
          <div className="hidden border-t border-slate-200/70 py-1.5 dark:border-slate-800 md:block">
            <div className="flex items-center gap-2 overflow-visible">
              <div className="max-w-full overflow-x-auto pb-0.5">
                <nav data-ui="portal-primary-nav" className="flex min-w-max items-center gap-1">
                  {primaryNavItems.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cn(
                        'rounded-full px-3 py-2 text-sm font-medium transition-all',
                        isActive(item.href)
                          ? 'bg-slate-900 text-white shadow-sm dark:bg-blue-500 dark:text-slate-950'
                          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white'
                      )}
                    >
                      <span className="inline-flex items-center gap-2">
                        {item.label}
                      </span>
                    </Link>
                  ))}
                </nav>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <div
        id="portal-mobile-nav"
        className={cn(
          'border-t border-slate-200/70 bg-white/92 backdrop-blur dark:border-slate-800 dark:bg-slate-950/92 md:hidden',
          mobileNavOpen ? 'block' : 'hidden'
        )}
      >
        <div className="container mx-auto space-y-4 px-4 py-4">
          {visibleSites.length ? (
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                {t('common.site')}
              </p>
              <select
                className="w-full rounded-2xl border border-slate-200/80 bg-white/90 px-3 py-3 text-sm text-slate-700 outline-none transition focus:border-blue-400 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200"
                value={selectedSiteId}
                onChange={(event) => void handleSiteChange(event.target.value)}
                disabled={isSwitchingSite}
              >
                {visibleSites.map((site) => (
                  <option key={site.site_id} value={site.site_id}>
                    {visibleSiteLabel(site)}
                    {' · '}
                    {visibleSiteSecondaryLabel(site)}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {isAuthenticated ? (
            primaryNavItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'block rounded-2xl px-4 py-3 text-sm font-medium transition-colors',
                  isActive(item.href)
                    ? 'bg-slate-900 text-white dark:bg-blue-500 dark:text-slate-950'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white'
                )}
                onClick={() => setMobileNavOpen(false)}
              >
                {item.label}
              </Link>
            ))
          ) : null}
          <div className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <LocaleSwitcher />
              <ThemeToggle />
            </div>
            {isAuthenticated ? (
              <button
                type="button"
                onClick={() => {
                  setMobileNavOpen(false);
                  void handleLogout();
                }}
                className="block w-full rounded-2xl px-4 py-3 text-left text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
              >
                {t('portal.logout')}
              </button>
            ) : !isLoginPage ? (
              <Link
                href="/portal/login"
                className="block rounded-2xl px-4 py-3 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                onClick={() => setMobileNavOpen(false)}
              >
                {t('nav.sign_in')}
              </Link>
            ) : null}
          </div>
        </div>
      </div>
    </header>
  );
}

export default PortalNavbar;
