import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { DEFAULT_LOCALE, resolveLocale, type Locale } from '@/lib/i18n';

/**
 * Merge Tailwind CSS classes with clsx
 * 
 * @example
 * cn('btn', 'btn-primary', { 'btn-disabled': disabled })
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

function getCurrentLocale(): Locale {
  if (typeof document === 'undefined') {
    return DEFAULT_LOCALE;
  }
  return resolveLocale(document.documentElement.lang) ?? DEFAULT_LOCALE;
}

function getValidDate(date: string | Date | undefined): Date | null {
  if (!date) {
    return null;
  }
  const normalizedDate =
    typeof date === 'string' && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(date.trim())
      ? `${date.trim().replace(' ', 'T')}Z`
      : date;
  const value = typeof normalizedDate === 'string' ? new Date(normalizedDate) : normalizedDate;
  if (Number.isNaN(value.getTime())) {
    return null;
  }
  return value;
}

/**
 * Format date to local string
 */
export function formatDate(date: string | Date | undefined): string {
  const value = getValidDate(date);
  if (!value) {
    return '';
  }
  return new Intl.DateTimeFormat(getCurrentLocale(), {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(value);
}

export function formatNumber(value: number, options: Intl.NumberFormatOptions = {}): string {
  return new Intl.NumberFormat(getCurrentLocale(), options).format(value);
}

export function formatCompactNumber(value: number, options: Intl.NumberFormatOptions = {}): string {
  return new Intl.NumberFormat(getCurrentLocale(), {
    notation: 'compact',
    maximumFractionDigits: 1,
    ...options,
  }).format(value);
}

export function formatCurrency(
  value: number,
  currency = 'USD',
  options: Intl.NumberFormatOptions = {}
): string {
  return new Intl.NumberFormat(getCurrentLocale(), {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    ...options,
  }).format(value);
}

/**
 * Format relative time (e.g., "2 hours ago")
 */
export function formatRelativeTime(date: string | Date | undefined): string {
  const value = getValidDate(date);
  if (!value) {
    return '';
  }
  const now = new Date();
  const diffMs = value.getTime() - now.getTime();
  const diffMins = Math.round(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  const formatter = new Intl.RelativeTimeFormat(getCurrentLocale(), { numeric: 'auto' });

  if (Math.abs(diffMins) < 1) {
    return formatter.format(0, 'minute');
  }
  if (Math.abs(diffMins) < 60) {
    return formatter.format(diffMins, 'minute');
  }
  if (Math.abs(diffHours) < 24) {
    return formatter.format(diffHours, 'hour');
  }
  if (Math.abs(diffDays) < 7) {
    return formatter.format(diffDays, 'day');
  }
  return formatDate(date);
}

/**
 * Truncate string with ellipsis
 */
export function truncate(str: string, length: number): string {
  if (str.length <= length) {
    return str;
  }
  return str.slice(0, length) + '...';
}

/**
 * Mask sensitive string (e.g., API key secret)
 * Shows first 4 and last 4 characters
 */
export function maskSensitive(str: string, visibleAtStart = 4, visibleAtEnd = 4): string {
  if (str.length <= visibleAtStart + visibleAtEnd) {
    return '••••••••';
  }
  return str.slice(0, visibleAtStart) + '••••••' + str.slice(-visibleAtEnd);
}

/**
 * Parse scopes string to array
 */
export function parseScopes(value: string | string[] | undefined): string[] {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  return value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Generate a simple unique ID
 */
export function generateId(prefix = 'id'): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
}
