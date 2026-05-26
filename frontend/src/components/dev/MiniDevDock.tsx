'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { isMiniDevDockEnabled } from '@/lib/env';

export function MiniDevDock() {
  const { t } = useLocale();
  const [enabled, setEnabled] = useState(false);
  const [currentOrigin, setCurrentOrigin] = useState('');
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setEnabled(isMiniDevDockEnabled());
    if (typeof window !== 'undefined') {
      setCurrentOrigin(window.location.origin);
    }
  }, []);

  if (!enabled) {
    return null;
  }

  const portalDevEntryHref = currentOrigin
    ? `/portal/dev-entry?origin=${encodeURIComponent(currentOrigin)}&redirect=${encodeURIComponent('/portal')}`
    : '/portal/dev-entry?redirect=%2Fportal';
  const adminDevEntryHref = currentOrigin
    ? `/admin/dev-entry?origin=${encodeURIComponent(currentOrigin)}&redirect=${encodeURIComponent('/admin')}`
    : '/admin/dev-entry?redirect=%2Fadmin';

  return (
    <aside className="fixed right-0 top-1/2 z-[80] -translate-y-1/2">
      <div
        className={`flex items-stretch gap-3 rounded-l-[1.75rem] rounded-r-none border border-r-0 border-slate-900 bg-white/96 p-3 shadow-[-18px_18px_45px_rgba(15,23,42,0.18)] backdrop-blur transition-transform dark:border-white/20 dark:bg-slate-950/92 ${
          expanded ? 'translate-x-0 pr-5' : 'translate-x-[1.25rem] pr-3'
        }`}
      >
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className="flex min-h-[9.5rem] w-11 items-center justify-center rounded-full bg-slate-950 text-white dark:bg-white dark:text-slate-950"
          aria-expanded={expanded}
          aria-label={expanded ? t('common.close') : t('common.open_menu', undefined, 'Open menu')}
        >
          <span className="[writing-mode:vertical-rl] text-[0.68rem] font-semibold uppercase tracking-[0.22em]">
            {t('dev.mini_label', undefined, 'MINI')}
          </span>
        </button>
        <div
          className={`overflow-hidden transition-[max-width,opacity] duration-200 ${
            expanded ? 'max-w-[12rem] opacity-100' : 'max-w-0 opacity-0'
          }`}
        >
          <div className="flex min-w-[11rem] flex-col justify-center gap-2">
            <Link
              href={portalDevEntryHref}
              className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-800 transition hover:border-slate-300 hover:bg-white hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-slate-700 dark:hover:bg-slate-800"
            >
              {t('dev.portal_login_shortcut', undefined, 'Portal 登录')}
            </Link>
            <Link
              href={adminDevEntryHref}
              className="rounded-2xl bg-blue-600 px-4 py-3 text-sm font-medium text-white transition hover:bg-blue-500"
            >
              {t('dev.admin_login_shortcut', undefined, '后台登录')}
            </Link>
          </div>
        </div>
      </div>
    </aside>
  );
}
