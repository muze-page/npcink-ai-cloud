import type { NextRequest } from 'next/server';
import { LOCALE_COOKIE_NAME, DEFAULT_LOCALE, resolveLocale, translate, type Locale } from '@/lib/i18n';

export function getRequestLocale(request: NextRequest): Locale {
  return resolveLocale(request.cookies.get(LOCALE_COOKIE_NAME)?.value) ?? DEFAULT_LOCALE;
}

export function tApi(request: NextRequest, key: string, fallback: string, params?: Record<string, string>): string {
  return translate(getRequestLocale(request), key, params, fallback);
}
