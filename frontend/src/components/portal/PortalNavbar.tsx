'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useMemo, useState } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { useSession } from '@/hooks/useSession';
import { cn } from '@/lib/utils';
import { LocaleSwitcher } from '@/components/ui/LocaleSwitcher';
import { ThemeToggle } from '@/components/ui/ThemeToggle';

export function PortalNavbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useLocale();
  const { isAuthenticated, logout } = useSession();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const primaryNavItems = useMemo(
    () => [
      { href: '/portal', label: t('portal.nav_service', {}, 'Service') },
      { href: '/portal/billing', label: t('portal.nav_package', {}, 'Package') },
      { href: '/portal/usage', label: t('portal.nav_usage', {}, 'Usage') },
      { href: '/portal/support', label: t('portal.nav_support_requests', {}, 'Tickets') },
      { href: '/portal/account', label: t('portal.nav_account', {}, 'Account') },
    ],
    [t]
  );
  const isActive = useCallback(
    (href: string) => {
      const baseHref = href.split('?')[0] || href;
      if (baseHref === '/portal') {
        return pathname === '/portal' || pathname.startsWith('/portal/sites');
      }

      return pathname === baseHref || pathname.startsWith(`${baseHref}/`);
    },
    [pathname]
  );

  const handleLogout = useCallback(async () => {
    await logout();
    router.push('/portal/login');
  }, [logout, router]);

  const isLoginPage = pathname === '/portal/login';
  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200/70 bg-white/78 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/78">
      <div className="container mx-auto px-4">
        <div className="grid min-h-[3.9rem] grid-cols-[auto_1fr] items-center gap-4 py-2.5 lg:grid-cols-[auto_1fr_auto]">
          <Link href="/portal" className="flex min-h-11 items-center gap-3">
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

          {isAuthenticated ? (
            <nav data-ui="portal-primary-nav" className="hidden min-w-0 items-center justify-center gap-1 lg:flex">
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
                  {item.label}
                </Link>
              ))}
            </nav>
          ) : <span />}

          <div className="flex items-center justify-end gap-2">
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
              className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-slate-200/80 bg-white/85 text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white md:hidden"
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
          <div className="hidden border-t border-slate-200/70 py-1.5 dark:border-slate-800 md:block lg:hidden">
            <div className="flex items-center gap-2 overflow-visible">
              <div className="max-w-full overflow-x-auto pb-0.5">
                <nav data-ui="portal-tablet-nav" className="flex min-w-max items-center gap-1">
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
