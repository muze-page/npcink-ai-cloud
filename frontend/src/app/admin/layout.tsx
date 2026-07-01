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
  labelKey: string;
  fallback: string;
  activePrefixes?: string[];
};

type AdminNavGroup = {
  groupKey: string;
  descKey: string;
  fallback: string;
  descFallback: string;
  items: AdminNavItem[];
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

  const navGroups: AdminNavGroup[] = [
    {
      groupKey: 'admin.nav_group_overview',
      descKey: 'admin.nav_group_overview_desc',
      fallback: 'Overview',
      descFallback: 'Platform posture and next operator actions.',
      items: [
        { href: '/admin', labelKey: 'nav.overview', fallback: 'Overview' },
      ],
    },
    {
      groupKey: 'admin.nav_group_customer_service',
      descKey: 'admin.nav_group_customer_service_desc',
      fallback: 'Customers and service',
      descFallback: 'Accounts, coverage, subscriptions, and package records.',
      items: [
        {
          href: '/admin/accounts',
          labelKey: 'common.accounts',
          fallback: 'Customers',
          activePrefixes: ['/admin/accounts', '/admin/sites'],
        },
        {
          href: '/admin/coverage',
          labelKey: 'admin.nav_coverage',
          fallback: 'Service Status',
        },
        {
          href: '/admin/subscriptions',
          labelKey: 'admin.nav_subscriptions',
          fallback: 'Subscriptions',
        },
        {
          href: '/admin/plans',
          labelKey: 'admin.nav_plan_catalog',
          fallback: 'Package Catalog',
        },
        {
          href: '/admin/portal-users',
          labelKey: 'admin.nav_portal_users',
          fallback: 'Portal Users',
        },
      ],
    },
    {
      groupKey: 'admin.nav_group_runtime_ops',
      descKey: 'admin.nav_group_runtime_ops_desc',
      fallback: 'Runtime',
      descFallback: 'Provider readiness and Cloud runtime model binding.',
      items: [
        {
          href: '/admin/ai-resources',
          labelKey: 'admin.nav_ai_resources',
          fallback: 'Runtime Resources',
          activePrefixes: ['/admin/ai-resources', '/admin/wordpress-ai-routing'],
        },
        {
          href: '/admin/ability-models',
          labelKey: 'admin.nav_ability_models',
          fallback: 'Runtime Model Binding',
        },
      ],
    },
    {
      groupKey: 'admin.nav_group_diagnostics',
      descKey: 'admin.nav_group_diagnostics_desc',
      fallback: 'Advanced diagnostics',
      descFallback: 'Read-only evidence for runtime, plugin, media, vector, and feedback quality.',
      items: [
        {
          href: '/admin/troubleshooting',
          labelKey: 'admin.nav_advanced_troubleshooting',
          fallback: 'Advanced Troubleshooting',
          activePrefixes: [
            '/admin/troubleshooting',
            '/admin/plugin-observability',
            '/admin/media-observability',
            '/admin/agent-feedback',
            '/admin/ai-advisor',
            '/admin/vector-observability',
          ],
        },
      ],
    },
    {
      groupKey: 'admin.nav_group_system',
      descKey: 'admin.nav_group_system_desc',
      fallback: 'System',
      descFallback: 'Cloud-owned service configuration.',
      items: [
        {
          href: '/admin/service-settings',
          labelKey: 'admin.nav_service_settings',
          fallback: 'Service Settings',
        },
      ],
    },
  ];
  const primaryNavItems = navGroups.flatMap((group) => group.items);

  const isPathMatch = (targetPath: string) => pathname === targetPath || pathname.startsWith(`${targetPath}/`);

  const isActive = (item: AdminNavItem) => {
    const href = item.href;
    if (href === '/admin') {
      return pathname === '/admin';
    }
    return (item.activePrefixes || [href]).some(isPathMatch);
  };
  const activePrimaryItem = primaryNavItems.find((item) => isActive(item)) ?? primaryNavItems[0];
  const activePrimaryLabel = t(activePrimaryItem.labelKey, {}, activePrimaryItem.fallback);

  const renderNavGroups = (variant: 'desktop' | 'mobile') => (
    <nav
      data-ui={variant === 'desktop' ? 'admin-primary-nav' : 'admin-mobile-primary-nav'}
      className={cn(
        variant === 'desktop'
          ? 'space-y-4'
          : 'space-y-4'
      )}
      aria-label={t('admin.console', {}, 'Admin console')}
    >
      {navGroups.map((group) => (
        <div key={group.groupKey} className="space-y-1.5">
          <div className={variant === 'desktop' ? 'px-2' : ''}>
            <p className="text-[0.66rem] font-bold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
              {t(group.groupKey, {}, group.fallback)}
            </p>
            {variant === 'desktop' ? (
              <p className="sr-only">
                {t(group.descKey, {}, group.descFallback)}
              </p>
            ) : null}
          </div>
          <div className="space-y-1">
            {group.items.map((item) => {
              const active = isActive(item);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={false}
                  className={cn(
                    'admin-nav-link flex w-full min-w-0 items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors',
                    active
                      ? 'admin-nav-link-active bg-slate-200/85 text-slate-950 dark:bg-slate-800 dark:text-white'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-white'
                  )}
                  onClick={variant === 'mobile' ? () => setMobileNavOpen(false) : undefined}
                >
                  <span className="min-w-0 truncate">{t(item.labelKey, {}, item.fallback)}</span>
                  {active ? (
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-80" aria-hidden="true" />
                  ) : null}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );

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
    <div className="admin-shell min-h-screen bg-slate-50 text-slate-950 dark:bg-slate-950 dark:text-slate-100 lg:flex">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col border-r border-slate-200/80 bg-slate-50/96 px-3 py-3 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/94 lg:flex">
        <div className="flex h-11 items-center justify-between gap-3">
          <Link href="/admin" className="flex min-w-0 items-center gap-3">
            <span className="brand-mark h-9 w-9 shrink-0" aria-hidden="true">
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none">
                <path d="M6 15.25 12.2 4l.6 6.55H18l-6.2 9.45-.5-6.2H6Z" fill="currentColor" />
              </svg>
            </span>
            <span className="min-w-0 flex flex-col leading-none">
              <span className="truncate text-[0.66rem] font-bold uppercase tracking-[0.24em] text-blue-600 dark:text-blue-300">
                Magick AI
              </span>
              <span className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t('admin.console')}
              </span>
            </span>
          </Link>
        </div>

        <div className="mt-5 min-h-0 flex-1 overflow-y-auto pr-1">
          {renderNavGroups('desktop')}
        </div>

        <div className="mt-3 border-t border-slate-200/70 pt-3 dark:border-slate-800">
          <Link
            href="/portal"
            className="flex items-center justify-between rounded-lg border border-slate-200 bg-white/80 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900/55 dark:text-slate-200 dark:hover:border-slate-700 dark:hover:text-white"
          >
            <span>{t('nav.portal')}</span>
            <span aria-hidden="true">→</span>
          </Link>
        </div>
      </aside>

      <div className="flex min-h-screen min-w-0 flex-1 flex-col lg:pl-60">
        <header className="sticky top-0 z-50 border-b border-slate-200/70 bg-white/86 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/86">
          <div className="flex min-h-12 items-center justify-between gap-3 px-4 py-1.5 md:px-5">
            <Link
              href="/admin"
              className="flex items-center gap-3 lg:hidden"
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

            <div className="hidden min-w-0 items-center gap-2 text-sm lg:flex">
              <span className="text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                {t('admin.operator_surface', {}, 'Operator surface')}
              </span>
              <span className="text-slate-300 dark:text-slate-700" aria-hidden="true">/</span>
              <span className="truncate font-semibold text-slate-900 dark:text-slate-100">
                {activePrimaryLabel}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="hidden rounded-full border border-blue-200/80 bg-blue-50 px-2.5 py-1 text-[0.62rem] font-bold uppercase tracking-[0.16em] text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/40 dark:text-blue-200 md:inline-flex">
                {t('admin.internal_only')}
              </span>
              <div className="hidden items-center gap-2 md:flex">
                <LocaleSwitcher />
                <ThemeToggle />
              </div>
              <Link
                href="/admin/logout"
                prefetch={false}
                className="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white md:inline-flex"
              >
                {t('portal.logout')}
              </Link>
              <Link
                href="/portal"
                className="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white md:inline-flex"
              >
                {t('nav.portal')} →
              </Link>
              <button
                type="button"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200/80 bg-white/85 text-slate-600 shadow-sm transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white lg:hidden"
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

        <div
          id="admin-mobile-nav"
          className={cn(
            'border-t border-slate-200/70 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 lg:hidden',
            mobileNavOpen ? 'block' : 'hidden'
          )}
        >
          <div className="space-y-4 px-4 py-4">
            <div className="flex items-center gap-2">
              <LocaleSwitcher />
              <ThemeToggle />
              <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[0.64rem] font-bold uppercase tracking-[0.22em] text-blue-700 dark:border-blue-900/80 dark:bg-blue-950/40 dark:text-blue-200">
                {t('admin.internal_only')}
              </span>
            </div>
            {renderNavGroups('mobile')}
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
          <div className="mx-auto w-full max-w-[110rem] px-3 py-4 md:px-5 md:py-5">
            {children}
          </div>
        </main>

        {/* Admin Footer */}
        <footer className="border-t border-gray-200 py-2 dark:border-gray-800">
          <div className="mx-auto w-full max-w-[110rem] px-4 text-center text-xs text-gray-500 md:px-5">
            <p>{t('admin.footer')}</p>
          </div>
        </footer>
      </div>
    </div>
  );
}
