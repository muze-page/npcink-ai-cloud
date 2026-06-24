'use client';

import React, { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { useLocale } from '@/contexts/LocaleContext';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { LocaleSwitcher } from '@/components/ui/LocaleSwitcher';

interface AdminLayoutProps {
  children: React.ReactNode;
}

type AdminNavItem = {
  href: string;
  label: string;
  activePrefixes?: string[];
};

export default function AdminLayout({ children }: AdminLayoutProps) {
  const pathname = usePathname();
  const { t } = useLocale();
  const isLoginPage = pathname === '/admin/login';
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (!mobileNavOpen) {
      document.body.style.overflow = '';
      return;
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobileNavOpen(false);
      }
    };

    document.addEventListener('keydown', handleEscape);
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [mobileNavOpen]);





  const toggleMobileNav = useCallback(() => {
    setMobileNavOpen((current) => !current);
  }, []);

  const primaryNavItems: AdminNavItem[] = [
    { href: '/admin', label: t('nav.overview', {}, 'Overview') },
    { href: '/admin/accounts', label: t('common.accounts', {}, 'Customers') },
    {
      href: '/admin/coverage',
      label: t('admin.nav_packages_coverage', {}, 'Packages / Coverage'),
      activePrefixes: ['/admin/coverage', '/admin/subscriptions', '/admin/plans'],
    },
    {
      href: '/admin/troubleshooting',
      label: t('admin.nav_advanced_troubleshooting', {}, 'Advanced Troubleshooting'),
      activePrefixes: [
        '/admin/troubleshooting',
        '/admin/plugin-observability',
        '/admin/media-observability',
        '/admin/agent-feedback',
        '/admin/ai-advisor',
        '/admin/web-search',
        '/admin/image-sources',
        '/admin/ai-resources',
        '/admin/audio-providers',
        '/admin/audio-workbench',
        '/admin/vector-observability',
        '/admin/hosted-models',
        '/admin/wordpress-ai-routing',
      ],
    },
  ];

  const isPathMatch = (targetPath: string) => pathname === targetPath || pathname.startsWith(`${targetPath}/`);

  const isActive = (item: AdminNavItem) => {
    const href = item.href;
    if (href === '/admin') {
      return pathname === '/admin';
    }
    if (href === '/admin/accounts' && pathname.startsWith('/admin/sites/')) {
      return true;
    }
    return (item.activePrefixes || [href]).some(isPathMatch);
  };
  const activePrimaryItem = primaryNavItems.find((item) => isActive(item)) ?? primaryNavItems[0];

  if (isLoginPage) {
    return (
      <div className="flex min-h-screen flex-col bg-[radial-gradient(circle_at_top_left,_rgba(96,165,250,0.18),transparent_22rem),radial-gradient(circle_at_top_right,_rgba(56,189,248,0.16),transparent_24rem),linear-gradient(180deg,#f8fbff_0%,#f7f8fc_54%,#eef3fb_100%)] dark:bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.16),transparent_20rem),radial-gradient(circle_at_top_right,_rgba(37,99,235,0.16),transparent_24rem),linear-gradient(180deg,#07111f_0%,#08101d_54%,#030712_100%)]">
        <header className="border-b border-slate-200/70 bg-white/72 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/72">
          <div className="container mx-auto flex h-14 items-center justify-between px-4">
            <Link
              href="/"
              className="flex items-center gap-3"
            >
              <span className="brand-mark" aria-hidden="true">
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none">
                  <path d="M6 15.25 12.2 4l.6 6.55H18l-6.2 9.45-.5-6.2H6Z" fill="currentColor" />
                </svg>
              </span>
              <span className="flex flex-col leading-none">
                <span className="text-[0.68rem] font-bold uppercase tracking-[0.3em] text-blue-600 dark:text-blue-300">
                  Magick AI
                </span>
                <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {t('admin.console')}
                </span>
              </span>
            </Link>
            <div className="flex items-center gap-2">
              <LocaleSwitcher />
              <ThemeToggle />
            </div>
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-50 w-full border-b border-slate-200/70 bg-white/80 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/82">
        <div className="container mx-auto px-4">
          <div className="flex min-h-[3.6rem] items-center justify-between gap-4 py-2">
            <Link 
              href="/admin" 
              className="flex items-center gap-3"
            >
              <span className="brand-mark" aria-hidden="true">
                <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none">
                  <path d="M6 15.25 12.2 4l.6 6.55H18l-6.2 9.45-.5-6.2H6Z" fill="currentColor" />
                </svg>
              </span>
              <span className="flex flex-col leading-none">
                <span className="text-[0.68rem] font-bold uppercase tracking-[0.3em] text-blue-600 dark:text-blue-300">
                  Magick AI
                </span>
                <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {t('admin.console')}
                </span>
              </span>
            </Link>

            <div className="flex items-center gap-2">
              <span className="hidden rounded-full border border-blue-200/80 bg-blue-50 px-2.5 py-1 text-[0.62rem] font-bold uppercase tracking-[0.2em] text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/40 dark:text-blue-200 md:inline-flex">
                {t('admin.internal_only')}
              </span>
              <div className="hidden items-center gap-2 md:flex">
                <LocaleSwitcher />
                <ThemeToggle />
              </div>
              <Link
                href="/admin/logout"
                prefetch={false}
                className="hidden rounded-full px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white md:inline-flex"
              >
                {t('portal.logout')}
              </Link>
              <Link
                href="/portal"
                className="hidden rounded-full px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white md:inline-flex"
              >
                {t('nav.portal')} →
              </Link>
              <button
                type="button"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200/80 bg-white/85 text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white md:hidden"
                aria-controls="admin-mobile-nav"
                aria-expanded={mobileNavOpen}
                aria-label={mobileNavOpen ? t('common.close') : t('common.open_menu', undefined, 'Open menu')}
                onClick={toggleMobileNav}
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

          <div className="hidden items-center justify-between gap-6 border-t border-slate-200/70 py-2 dark:border-slate-800 md:flex">
            <div className="flex min-w-0 items-center gap-2 overflow-visible">
              <div className="max-w-full overflow-x-auto pb-1">
                <nav
                  data-ui="admin-primary-nav"
                  className="flex min-w-max items-center gap-2"
                  aria-label={t('admin.console', {}, 'Admin console')}
                >
                  {primaryNavItems.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      prefetch={false}
                      className={cn(
                        'admin-nav-link whitespace-nowrap',
                        isActive(item) && 'admin-nav-link-active'
                      )}
                    >
                      {item.label}
                    </Link>
                  ))}
                </nav>
              </div>

            </div>
            <div className="min-w-0 max-w-sm text-right">
              <p className="text-[0.62rem] font-semibold uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400">
                {t('admin.operator_surface', {}, 'Operator surface')}
              </p>
              <p className="truncate text-sm text-slate-600 dark:text-slate-300">
                {activePrimaryItem.label}
              </p>
            </div>
          </div>
        </div>

        <div
          id="admin-mobile-nav"
          className={cn(
            'border-t border-slate-200/70 bg-white/92 backdrop-blur dark:border-slate-800 dark:bg-slate-950/92 md:hidden',
            mobileNavOpen ? 'block' : 'hidden'
          )}
        >
          <div className="container mx-auto space-y-4 px-4 py-4">
            <div className="flex items-center gap-2">
              <LocaleSwitcher />
              <ThemeToggle />
              <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[0.64rem] font-bold uppercase tracking-[0.22em] text-blue-700 dark:border-blue-900/80 dark:bg-blue-950/40 dark:text-blue-200">
              {t('admin.internal_only')}
              </span>
            </div>
            <nav className="space-y-4" aria-label={t('admin.console', {}, 'Admin console')}>
              <div className="space-y-2">
                <p className="text-[0.68rem] font-bold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
                  {t('admin.operator_surface', {}, 'Operator surface')}
                </p>
                <div className="space-y-2">
                  {primaryNavItems.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      prefetch={false}
                      className={cn(
                        'block rounded-2xl px-4 py-3 text-sm font-medium transition-colors',
                        isActive(item)
                          ? 'bg-slate-900 text-white dark:bg-blue-500 dark:text-slate-950'
                          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white'
                      )}
                      onClick={() => setMobileNavOpen(false)}
                    >
                      {item.label}
                    </Link>
                  ))}
                </div>
              </div>
            </nav>
            <div className="grid grid-cols-2 gap-2">
              <Link
                href="/portal"
                className="btn btn-secondary justify-center"
                onClick={() => setMobileNavOpen(false)}
              >
                {t('nav.portal')}
              </Link>
              <Link
                href="/admin/logout"
                prefetch={false}
                className="btn btn-outline justify-center"
                onClick={() => setMobileNavOpen(false)}
              >
                {t('portal.logout')}
              </Link>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 bg-transparent">
        <div className="container mx-auto px-4 py-5 md:py-6">
          {children}
        </div>
      </main>

      {/* Admin Footer */}
      <footer className="border-t border-gray-200 dark:border-gray-800 py-4">
        <div className="container mx-auto px-4 text-center text-sm text-gray-500">
          <p>{t('admin.footer')}</p>
        </div>
      </footer>
    </div>
  );
}
