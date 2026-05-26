'use client';

import React from 'react';
import { useLocale } from '@/contexts/LocaleContext';
import { cn } from '@/lib/utils';

export type AlertVariant = 'info' | 'success' | 'warning' | 'error';

interface AlertProps {
  variant?: AlertVariant;
  title?: string;
  children?: React.ReactNode;
  onDismiss?: () => void;
  className?: string;
  icon?: React.ReactNode;
}

const variantStyles: Record<AlertVariant, string> = {
  info: 'bg-blue-50 border-blue-200 text-blue-800 dark:bg-blue-900/20 dark:border-blue-800 dark:text-blue-300',
  success: 'bg-green-50 border-green-200 text-green-800 dark:bg-green-900/20 dark:border-green-800 dark:text-green-300',
  warning: 'bg-yellow-50 border-yellow-200 text-yellow-800 dark:bg-yellow-900/20 dark:border-yellow-800 dark:text-yellow-300',
  error: 'bg-red-50 border-red-200 text-red-800 dark:bg-red-900/20 dark:border-red-800 dark:text-red-300',
};

const variantIcons: Record<AlertVariant, React.ReactNode> = {
  info: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
  success: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
  warning: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
  ),
  error: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
};

/**
 * 警告/提示组件
 * 用于显示各种类型的提示信息
 */
export function Alert({
  variant = 'info',
  title,
  children,
  onDismiss,
  className,
  icon,
}: AlertProps) {
  const { t } = useLocale();

  return (
    <div
      className={cn(
        'border rounded-lg p-4',
        variantStyles[variant],
        className
      )}
      role="alert"
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0">
          {icon || variantIcons[variant]}
        </div>
        <div className="flex-1 min-w-0">
          {title && (
            <h3 className="font-medium mb-1">{title}</h3>
          )}
          <div className={cn('text-sm', title ? '' : '')}>
            {children}
          </div>
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="flex-shrink-0 p-1 rounded hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
            aria-label={t('common.close')}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * 错误显示组件
 * 专门用于显示错误信息
 */
interface ErrorDisplayProps {
  error?: string | Error;
  errorTitle?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorDisplay({
  error,
  errorTitle,
  onRetry,
  className,
}: ErrorDisplayProps) {
  const { t } = useLocale();
  const errorMessage = error instanceof Error ? error.message : String(error);

  return (
    <Alert
      variant="error"
      title={errorTitle || t('common.error')}
      className={className}
    >
      <div className="space-y-2">
        <p>{errorMessage}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-2 px-4 py-2 bg-red-600 text-white text-sm font-medium rounded hover:bg-red-700 transition-colors"
          >
            {t('common.retry')}
          </button>
        )}
      </div>
    </Alert>
  );
}

/**
 * 加载提示组件
 */
interface LoadingDisplayProps {
  message?: string;
  className?: string;
}

export function LoadingDisplay({
  message,
  className,
}: LoadingDisplayProps) {
  const { t } = useLocale();

  return (
    <div
      className={cn(
        'flex items-center justify-center gap-3 text-gray-600 dark:text-gray-400',
        className
      )}
    >
      <div className="animate-spin">
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
      </div>
      <span className="text-sm">{message || t('common.loading')}</span>
    </div>
  );
}

/**
 * 空状态组件
 */
interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
}: EmptyStateProps) {
  const { t } = useLocale();

  return (
    <div
      className={cn(
        'text-center py-12 px-4',
        className
      )}
    >
      <div className="flex justify-center mb-4">
        {icon || (
          <svg className="w-12 h-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
        )}
      </div>
      {(title || t('common.not_found')) && (
        <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100 mb-1">
          {title || t('common.not_found')}
        </h3>
      )}
      {description && (
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          {description}
        </p>
      )}
      {action && (
        <div className="flex justify-center gap-2">
          {action}
        </div>
      )}
    </div>
  );
}
