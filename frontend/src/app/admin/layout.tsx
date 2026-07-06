'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { useLocale } from '@/contexts/LocaleContext';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { LocaleSwitcher } from '@/components/ui/LocaleSwitcher';
import { AdminRouteTransition } from '@/components/admin/AdminRouteTransition';

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

type AdminCommandItem = AdminNavItem & {
  groupLabel: string;
  groupFallback: string;
  label: string;
  href: string;
};

const ADMIN_SIDEBAR_STORAGE_KEY = 'npcink_admin_sidebar_collapsed';

function adminNavInitial(label: string): string {
  const trimmed = label.trim();
  if (!trimmed) {
    return '·';
  }
  return trimmed.slice(0, 1).toUpperCase();
}

function isTypingShortcutTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tagName = target.tagName.toLowerCase();
  return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable;
}

export default function AdminLayout({ children }: AdminLayoutProps) {
  const pathname = usePathname();
  const { t } = useLocale();
  const isLoginPage = pathname === '/admin/login';
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState('');
  const commandInputRef = useRef<HTMLInputElement>(null);

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

  useEffect(() => {
    try {
      setSidebarCollapsed(window.localStorage.getItem(ADMIN_SIDEBAR_STORAGE_KEY) === 'true');
    } catch {
      setSidebarCollapsed(false);
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(ADMIN_SIDEBAR_STORAGE_KEY, sidebarCollapsed ? 'true' : 'false');
    } catch {
      // Local storage is best-effort UI preference only.
    }
  }, [sidebarCollapsed]);

  useEffect(() => {
    const handleKeyboardShortcut = (event: KeyboardEvent) => {
      const isMetaShortcut = event.metaKey || event.ctrlKey;
      if (!isMetaShortcut || isTypingShortcutTarget(event.target)) {
        return;
      }

      const key = event.key.toLowerCase();
      if (key === 'b') {
        event.preventDefault();
        setSidebarCollapsed((current) => !current);
        return;
      }

      if (key === 'k') {
        event.preventDefault();
        setCommandOpen((current) => !current);
      }
    };

    window.addEventListener('keydown', handleKeyboardShortcut);
    return () => window.removeEventListener('keydown', handleKeyboardShortcut);
  }, []);

  useEffect(() => {
    if (!commandOpen) {
      setCommandQuery('');
      return;
    }

    const focusTimer = window.setTimeout(() => commandInputRef.current?.focus(), 0);
    const handleCommandEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setCommandOpen(false);
      }
    };

    document.addEventListener('keydown', handleCommandEscape);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleCommandEscape);
    };
  }, [commandOpen]);

  const toggleMobileNav = useCallback(() => {
    setMobileNavOpen((current) => !current);
  }, []);

  const navGroups = useMemo<AdminNavGroup[]>(() => [
    {
      groupKey: 'admin.nav_group_overview',
      descKey: 'admin.nav_group_overview_desc',
      fallback: 'Workspace',
      descFallback: 'Platform posture and next operator actions.',
      items: [
        { href: '/admin', labelKey: 'nav.overview', fallback: 'Overview' },
      ],
    },
    {
      groupKey: 'admin.nav_group_customer_service',
      descKey: 'admin.nav_group_customer_service_desc',
      fallback: 'Customer Ops',
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
      fallback: 'Runtime Plane',
      descFallback: 'Provider readiness and Cloud runtime model binding.',
      items: [
        {
          href: '/admin/ai-resources',
          labelKey: 'admin.nav_ai_resources',
          fallback: 'Providers',
          activePrefixes: ['/admin/ai-resources'],
        },
        {
          href: '/admin/ability-models',
          labelKey: 'admin.nav_ability_models',
          fallback: 'Model Binding',
        },
        {
          href: '/admin/troubleshooting',
          labelKey: 'admin.nav_runtime_diagnostics',
          fallback: 'Runtime Diagnostics',
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
  ], []);
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
  const commandItems = useMemo<AdminCommandItem[]>(
    () =>
      navGroups.flatMap((group) => {
        const groupLabel = t(group.groupKey, {}, group.fallback);
        return group.items.map((item) => ({
          ...item,
          href: item.href,
          groupLabel,
          groupFallback: group.fallback,
          label: t(item.labelKey, {}, item.fallback),
        }));
      }),
    [navGroups, t]
  );
  const normalizedCommandQuery = commandQuery.trim().toLowerCase();
  const filteredCommandItems = commandItems.filter((item) => {
    if (!normalizedCommandQuery) {
      return true;
    }
    return [item.label, item.fallback, item.groupLabel, item.groupFallback, item.href]
      .join(' ')
      .toLowerCase()
      .includes(normalizedCommandQuery);
  });

  const renderNavGroups = (variant: 'desktop' | 'mobile') => {
    const collapsed = variant === 'desktop' && sidebarCollapsed;
    return (
    <nav
      data-ui={variant === 'desktop' ? 'admin-primary-nav' : 'admin-mobile-primary-nav'}
      className={cn(
        variant === 'desktop' && collapsed
          ? 'space-y-2'
          : 'space-y-4'
      )}
      aria-label={t('admin.console', {}, 'Admin console')}
    >
      {navGroups.map((group) => (
        <div key={group.groupKey} className={cn('space-y-1.5', collapsed && 'space-y-1')}>
          <div className={cn(variant === 'desktop' ? 'px-2' : '', collapsed && 'sr-only')}>
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
              const itemLabel = t(item.labelKey, {}, item.fallback);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={itemLabel}
                  aria-label={itemLabel}
                  className={cn(
                    'admin-nav-link flex w-full min-w-0 items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors',
                    collapsed && 'h-10 justify-center px-0 text-xs',
                    active
                      ? 'admin-nav-link-active bg-slate-200/85 text-slate-950 dark:bg-slate-800 dark:text-white'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-white'
                  )}
                  onClick={variant === 'mobile' ? () => setMobileNavOpen(false) : undefined}
                >
                  <span className={cn('min-w-0 truncate', collapsed && 'sr-only')}>{itemLabel}</span>
                  {collapsed ? (
                    <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-slate-100 text-[0.7rem] font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-100" aria-hidden="true">
                      {adminNavInitial(itemLabel)}
                    </span>
                  ) : null}
                  {active && !collapsed ? (
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
  };

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
    <div
      className={cn(
        'admin-shell min-h-screen bg-slate-50 text-slate-950 dark:bg-slate-950 dark:text-slate-100 lg:flex',
        sidebarCollapsed && 'admin-shell-collapsed'
      )}
    >
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-slate-200/80 bg-slate-50/96 px-3 py-3 backdrop-blur-xl transition-[width] duration-200 ease-out dark:border-slate-800 dark:bg-slate-950/94 lg:flex',
          sidebarCollapsed ? 'w-16' : 'w-60'
        )}
      >
        <div className={cn('flex h-11 items-center gap-2', sidebarCollapsed ? 'justify-center' : 'justify-between')}>
          <Link href="/admin" className={cn('flex min-w-0 items-center gap-3', sidebarCollapsed && 'justify-center')}>
            <span className="brand-mark h-9 w-9 shrink-0" aria-hidden="true">
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none">
                <path d="M6 15.25 12.2 4l.6 6.55H18l-6.2 9.45-.5-6.2H6Z" fill="currentColor" />
              </svg>
            </span>
            <span className={cn('min-w-0 flex flex-col leading-none', sidebarCollapsed && 'sr-only')}>
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
      </aside>

      <div className={cn('flex min-h-screen min-w-0 flex-1 flex-col transition-[padding-left] duration-200 ease-out', sidebarCollapsed ? 'lg:pl-16' : 'lg:pl-60')}>
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
              <button
                type="button"
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white/80 text-slate-600 transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:text-white"
                aria-label={
                  sidebarCollapsed
                    ? t('admin.sidebar_expand', {}, 'Expand sidebar')
                    : t('admin.sidebar_collapse', {}, 'Collapse sidebar')
                }
                title={
                  sidebarCollapsed
                    ? t('admin.sidebar_expand', {}, 'Expand sidebar')
                    : t('admin.sidebar_collapse', {}, 'Collapse sidebar')
                }
                onClick={() => setSidebarCollapsed((current) => !current)}
              >
                <svg className={cn('h-4 w-4 transition-transform', sidebarCollapsed && 'rotate-180')} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M15 6 9 12l6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <span className="text-[0.62rem] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                {t('admin.operator_surface', {}, 'Operator surface')}
              </span>
              <span className="text-slate-300 dark:text-slate-700" aria-hidden="true">/</span>
              <span className="truncate font-semibold text-slate-900 dark:text-slate-100">
                {activePrimaryLabel}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                className="hidden h-9 min-w-0 items-center gap-2 rounded-lg border border-slate-200 bg-white/80 px-2.5 text-sm text-slate-500 transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:text-white sm:inline-flex"
                aria-label={t('admin.command_open', {}, 'Open quick switcher')}
                onClick={() => setCommandOpen(true)}
              >
                <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="m21 21-4.2-4.2m1.2-5.3a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
                <span className="hidden min-w-0 truncate lg:inline">{t('common.search', {}, 'Search')}</span>
                <kbd className="hidden rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[0.65rem] font-semibold text-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-500 lg:inline">
                  ⌘K
                </kbd>
              </button>
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

        {commandOpen ? (
          <div
            className="fixed inset-0 z-[70] bg-slate-950/24 px-3 py-16 backdrop-blur-sm dark:bg-slate-950/55"
            role="dialog"
            aria-modal="true"
            aria-label={t('admin.command_title', {}, 'Quick switcher')}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                setCommandOpen(false);
              }
            }}
          >
            <div className="mx-auto flex max-h-[min(32rem,calc(100svh-8rem))] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950">
              <div className="border-b border-slate-200 p-3 dark:border-slate-800">
                <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900/70">
                  <svg className="h-4 w-4 shrink-0 text-slate-400" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="m21 21-4.2-4.2m1.2-5.3a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  <input
                    ref={commandInputRef}
                    className="min-w-0 flex-1 bg-transparent text-sm text-slate-950 outline-none placeholder:text-slate-400 dark:text-slate-100"
                    value={commandQuery}
                    placeholder={t('admin.command_placeholder', {}, 'Search admin pages')}
                    onChange={(event) => setCommandQuery(event.target.value)}
                  />
                  <kbd className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[0.65rem] font-semibold text-slate-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-500">
                    Esc
                  </kbd>
                </div>
                <p className="mt-2 px-1 text-xs text-slate-500 dark:text-slate-400">
                  {t('admin.command_desc', {}, 'Jump between existing Cloud admin pages.')}
                </p>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {filteredCommandItems.length > 0 ? (
                  <div className="space-y-1">
                    {filteredCommandItems.map((item) => (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={cn(
                          'flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-slate-100 dark:hover:bg-slate-900',
                          isActive(item) && 'bg-slate-100 dark:bg-slate-900'
                        )}
                        onClick={() => setCommandOpen(false)}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-slate-950 dark:text-slate-100">
                            {item.label}
                          </span>
                          <span className="mt-0.5 block truncate text-xs text-slate-500 dark:text-slate-400">
                            {item.groupLabel}
                          </span>
                        </span>
                        <span className="shrink-0 text-slate-300 dark:text-slate-600" aria-hidden="true">→</span>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <div className="px-4 py-10 text-center text-sm text-slate-500 dark:text-slate-400">
                    {t('admin.command_empty', {}, 'No admin page matches this search.')}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : null}

        {/* Main Content */}
        <main className="flex-1 bg-transparent">
          <AdminRouteTransition>
            {children}
          </AdminRouteTransition>
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
