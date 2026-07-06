'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import {
  DEFAULT_LOCALE,
  persistLocale,
  readStoredLocale,
  resolveLocale,
  translate as translateMessage,
  type Locale,
} from '@/lib/i18n';

interface LocaleContextType {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, params?: Record<string, string>, fallback?: string) => string;
  mounted: boolean;
}

export const LocaleContext = createContext<LocaleContextType | undefined>(undefined);

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setLocaleState(readStoredLocale());
  }, []);

  const setLocale = useCallback((newLocale: Locale) => {
    const normalizedLocale = resolveLocale(newLocale) ?? DEFAULT_LOCALE;
    setLocaleState(normalizedLocale);
    persistLocale(normalizedLocale);
  }, []);

  useEffect(() => {
    if (!mounted) {
      return;
    }
    document.documentElement.lang = locale;
  }, [locale, mounted]);

  const translate = useCallback(
    (key: string, params?: Record<string, string>, fallback?: string) => {
      return translateMessage(locale, key, params, fallback);
    },
    [locale]
  );

  return (
    <LocaleContext.Provider value={{ locale, setLocale, t: translate, mounted }}>
      {children}
    </LocaleContext.Provider>
  );
}

export function useLocale() {
  const context = useContext(LocaleContext);
  if (context === undefined) {
    throw new Error('useLocale must be used within a LocaleProvider');
  }
  return context;
}
