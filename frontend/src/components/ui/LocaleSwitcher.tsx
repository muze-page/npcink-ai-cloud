'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { localeOptions, type Locale } from '@/lib/i18n';
import { cn } from '@/lib/utils';

export function LocaleSwitcher() {
  const { locale, setLocale, t } = useLocale();
  const buttonId = useId();
  const currentLocale = localeOptions.find((l) => l.value === locale) ?? localeOptions.find((l) => l.value === 'zh-CN') ?? localeOptions[0];
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, []);

  return (
    <div ref={rootRef} className="relative">
      <label htmlFor={buttonId} className="sr-only">
        {t('common.language', undefined, 'Language')}
      </label>
      <button
        id={buttonId}
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-9 items-center gap-1.5 rounded-full border border-slate-200/80 bg-white/85 px-2.5 text-sm font-semibold text-slate-700 shadow-sm transition-all hover:-translate-y-0.5 hover:border-slate-300 hover:bg-white dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-800"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('common.language', undefined, 'Language')}
      >
        <span className="text-base leading-none" aria-hidden="true">{currentLocale?.flag}</span>
        <span className="hidden sm:inline">{currentLocale?.shortLabel}</span>
        <svg className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open ? (
        <div
          className="absolute right-0 top-[calc(100%+0.5rem)] z-50 w-36 rounded-2xl border border-slate-200/80 bg-white/95 p-1.5 shadow-2xl shadow-slate-900/10 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95"
          role="listbox"
          aria-label={t('common.language', undefined, 'Language')}
        >
          {localeOptions.map((option) => {
            const active = option.value === locale;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  setLocale(option.value as Locale);
                  setOpen(false);
                }}
                className={cn(
                  'flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm transition-colors',
                  active
                    ? 'bg-slate-900 text-white dark:bg-blue-500'
                    : 'text-gray-700 hover:bg-slate-100 dark:text-gray-200 dark:hover:bg-slate-800'
                )}
                role="option"
                aria-selected={active}
              >
                <span className="text-base leading-none" aria-hidden="true">{option.flag}</span>
                <span className="min-w-0 flex-1 truncate">{option.label}</span>
                {active ? (
                  <svg className="h-4 w-4 flex-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                  </svg>
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function LocaleSwitcherButton() {
  return <LocaleSwitcher />;
}

export default LocaleSwitcher;
