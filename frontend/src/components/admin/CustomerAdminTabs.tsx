'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLocale } from '@/contexts/LocaleContext';
import { cn } from '@/lib/utils';

const CUSTOMER_TAB_ITEMS = [
  {
    href: '/admin/accounts',
    labelKey: 'admin.customer_tabs.accounts',
    fallback: 'Customer register',
    activePrefixes: ['/admin/accounts', '/admin/sites'],
  },
  {
    href: '/admin/portal-users',
    labelKey: 'admin.customer_tabs.portal_users',
    fallback: 'Registered users',
    activePrefixes: ['/admin/portal-users'],
  },
  {
    href: '/admin/coverage',
    labelKey: 'admin.customer_tabs.coverage',
    fallback: 'Service follow-up',
    activePrefixes: ['/admin/coverage', '/admin/plans'],
  },
  {
    href: '/admin/subscriptions',
    labelKey: 'admin.customer_tabs.subscriptions',
    fallback: 'Subscription records',
    activePrefixes: ['/admin/subscriptions'],
  },
];

export function CustomerAdminTabs() {
  const pathname = usePathname();
  const { t } = useLocale();

  return (
    <nav
      aria-label={t('common.accounts', {}, 'Customers')}
      className="flex min-w-0 items-center gap-5 border-b border-slate-200 dark:border-slate-800"
    >
      {CUSTOMER_TAB_ITEMS.map((item) => {
        const active = item.activePrefixes.some(
          (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
        );
        return (
          <Link
            key={item.href}
            href={item.href}
            prefetch={false}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'border-b-2 px-1 pb-3 text-sm font-semibold transition-colors',
              active
                ? 'border-blue-600 text-blue-700 dark:border-blue-300 dark:text-blue-200'
                : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-900 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:text-slate-100'
            )}
          >
            {t(item.labelKey, {}, item.fallback)}
          </Link>
        );
      })}
    </nav>
  );
}
