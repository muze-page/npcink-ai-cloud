'use client';

import React from 'react';
import { useThemeContext } from '@/contexts/ThemeContext';
import { useLocale } from '@/contexts/LocaleContext';
import { cn } from '@/lib/utils';

/**
 * 简单的主题切换按钮（亮/暗切换）
 */
export function ThemeToggle() {
  const { isDark, toggleTheme, mounted } = useThemeContext();
  const { t } = useLocale();

  // 使用默认值避免 hydration 不匹配
  const displayIsDark = mounted ? isDark : false;
  const handleToggleTheme = () => {
    if (!mounted) {
      return;
    }
    toggleTheme();
  };

  return (
    <button
      type="button"
      onClick={handleToggleTheme}
      className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200/80 bg-white/85 text-slate-600 shadow-sm transition-all hover:-translate-y-0.5 hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      aria-label={displayIsDark ? t('theme.switch_to_light') : t('theme.switch_to_dark')}
      title={displayIsDark ? t('theme.switch_to_light') : t('theme.switch_to_dark')}
    >
      {displayIsDark ? (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
      ) : (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      )}
    </button>
  );
}

/**
 * 主题选择器（亮/暗/系统）
 */
export function ThemeSelector() {
  const { theme, setTheme, isDark, mounted } = useThemeContext();
  const { t } = useLocale();

  if (!mounted) {
    return (
      <div className="flex items-center gap-1">
        <span className="text-sm text-gray-500">{t('common.loading')}</span>
      </div>
    );
  }

  const options: { value: 'light' | 'dark' | 'system'; label: string; icon: string }[] = [
    { value: 'light', label: t('theme.light'), icon: '☀️' },
    { value: 'dark', label: t('theme.dark'), icon: '🌙' },
    { value: 'system', label: t('theme.system'), icon: '💻' },
  ];

  return (
    <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => setTheme(option.value)}
          className={cn(
            'flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
            theme === option.value
              ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 shadow-sm'
              : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100'
          )}
          aria-pressed={theme === option.value}
          aria-label={`Set ${option.label} theme`}
        >
          <span aria-hidden="true">{option.icon}</span>
          <span className="hidden sm:inline">{option.label}</span>
        </button>
      ))}
    </div>
  );
}

/**
 * 下拉式主题选择器
 */
export function ThemeDropdown() {
  const { theme, setTheme, isDark, mounted } = useThemeContext();
  const { t } = useLocale();

  if (!mounted) {
    return null;
  }

  const options: { value: 'light' | 'dark' | 'system'; label: string; icon: string }[] = [
    { value: 'light', label: t('theme.light'), icon: '☀️' },
    { value: 'dark', label: t('theme.dark'), icon: '🌙' },
    { value: 'system', label: t('theme.system'), icon: '💻' },
  ];

  const currentOption = options.find((o) => o.value === theme);

  return (
    <div className="relative">
      <label htmlFor="theme-select" className="sr-only">
        {t('theme.select')}
      </label>
      <select
        id="theme-select"
        value={theme}
        onChange={(e) => setTheme(e.target.value as 'light' | 'dark' | 'system')}
        className="appearance-none bg-transparent border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 pr-8 text-sm font-medium text-gray-700 dark:text-gray-300 hover:border-gray-400 dark:hover:border-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent cursor-pointer"
        aria-label={t('theme.select')}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.icon} {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export default ThemeToggle;
