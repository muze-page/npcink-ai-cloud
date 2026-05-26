'use client';

import React from 'react';
import { cn } from '@/lib/utils';

export interface CardProps {
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'elevated' | 'outlined' | 'soft';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  as?: React.ElementType;
}

/**
 * 卡片组件 - 基础容器组件
 *
 * @example
 * <Card variant="elevated">
 *   <CardHeader title="Title" />
 *   <CardContent>Content here</CardContent>
 * </Card>
 */
export function Card({
  children,
  className,
  variant = 'default',
  padding = 'md',
  as: Component = 'div',
}: CardProps) {
  const variantStyles = {
    default: 'bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800',
    elevated: 'bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-md',
    outlined: 'bg-transparent border-2 border-gray-300 dark:border-gray-700',
    soft: 'bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800',
  };

  const paddingStyles = {
    none: '',
    sm: 'p-3',
    md: 'p-4',
    lg: 'p-6',
  };

  return (
    <Component
      className={cn(
        'rounded-xl transition-all',
        variantStyles[variant],
        paddingStyles[padding],
        className
      )}
    >
      {children}
    </Component>
  );
}

export interface CardHeaderProps {
  title?: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

/**
 * 卡片头部组件
 */
export function CardHeader({
  title,
  description,
  action,
  className,
}: CardHeaderProps) {
  return (
    <div className={cn('flex items-start justify-between gap-4 mb-4', className)}>
      <div className="flex-1 min-w-0">
        {title && (
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100 truncate">
            {title}
          </h3>
        )}
        {description && (
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
            {description}
          </p>
        )}
      </div>
      {action && <div className="flex-shrink-0">{action}</div>}
    </div>
  );
}

export interface CardContentProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * 卡片内容组件
 */
export function CardContent({ children, className }: CardContentProps) {
  return <div className={cn('text-sm', className)}>{children}</div>;
}

export interface CardFooterProps {
  children: React.ReactNode;
  className?: string;
  divider?: boolean;
}

/**
 * 卡片底部组件
 */
export function CardFooter({ children, className, divider = false }: CardFooterProps) {
  return (
    <div
      className={cn(
        'mt-4 pt-4 flex items-center gap-2',
        divider && 'border-t border-gray-200 dark:border-gray-800',
        className
      )}
    >
      {children}
    </div>
  );
}
